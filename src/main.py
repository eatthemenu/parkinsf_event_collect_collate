"""CLI entry point for the event aggregator pipeline.

Run as::

    python -m src.main --input data/event_source_sample.csv

For a dry run (browser + expansion only, no AI calls or CSV output)::

    python -m src.main --dry-run --log-level DEBUG
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from .ai_vision import CostTracker, get_provider
from .ai_vision.prompt_templates import build_extraction_prompt
from .assembler import assemble_event
from .browser import BrowserController
from .cookie_dismisser import dismiss_cookie_modal
from .csv_io import read_event_source_csv, write_event_table_csv
from .detail_handler import fetch_event_detail
from .logger import setup_logging
from .normalizer import VenueNormalizer
from .page_expander import expand_page
from .report import RunReport
from .screenshot import take_screenshots
from .validators import deduplicate_events, validate_event
from .venue_config import (
    Settings,
    VenueMapping,
    VenueSource,
    load_cookie_selectors,
    load_settings,
    load_venue_aliases,
    load_venue_mappings,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser.

    Returns:
        Configured :class:`argparse.ArgumentParser` instance.
    """
    parser = argparse.ArgumentParser(
        description="SF Bay Area venue event schedule aggregator.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input",
        default="data/event_source_sample.csv",
        help="Path to the Event Source CSV file.",
    )
    parser.add_argument(
        "--output",
        default="",
        help=(
            "Path to write the Event Table Update CSV. "
            "Defaults to data/event_table_update_YYYYMMDD.csv."
        ),
    )
    parser.add_argument(
        "--config-dir",
        default="config",
        help="Directory containing settings.yaml and venue CSV/YAML files.",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Base directory for screenshots and AI response files.",
    )
    parser.add_argument(
        "--log-dir",
        default="logs",
        help="Directory for run log, cost log, and summary report files.",
    )
    parser.add_argument(
        "--log-level",
        default="",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", ""],
        help="Override the log level from settings.yaml.",
    )
    parser.add_argument(
        "--provider",
        default="",
        help="Override the primary AI provider from settings.yaml.",
    )
    parser.add_argument(
        "--event-window-months",
        type=int,
        default=0,
        help="Override how many months ahead to collect events (0 = use settings.yaml).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load pages and expand them but skip AI calls and CSV output.",
    )
    return parser


# ---------------------------------------------------------------------------
# Per-event processing helpers
# ---------------------------------------------------------------------------


def _build_human_review_item(
    venue_id: str,
    issue_type: str,
    severity: str,
    details: str,
    suggested_action: str,
    raw_data: str,
    today: date,
) -> dict:
    """Build a HumanReviewItem dict.

    Args:
        venue_id: Venue identifier for the item.
        issue_type: Short issue category string.
        severity: One of "low", "medium", "high".
        details: Human-readable description.
        suggested_action: Recommended next step.
        raw_data: JSON-serialised or str supporting data.
        today: Current date, used for the timestamp field.

    Returns:
        HumanReviewItem dict ready to pass to :meth:`RunReport.add_human_review_item`.
    """
    return {
        "timestamp": today.isoformat() + "T00:00:00Z",
        "venue_id": venue_id,
        "issue_type": issue_type,
        "severity": severity,
        "details": details,
        "suggested_action": suggested_action,
        "raw_data": raw_data,
    }


def _process_raw_events(
    raw_events: list[dict],
    venue_source: VenueSource,
    venue_mappings: dict[str, VenueMapping],
    normalizer: VenueNormalizer,
    today: date,
    max_future_date: date,
    run_report: RunReport,
) -> list[dict]:
    """Normalize, assemble, and validate raw AI-extracted events.

    For each raw event:
      1. Determine the venue name to normalize (from AI or venue config).
      2. Resolve to a canonical venue_id via the normalizer.
      3. Assemble a full event dict using :func:`~assembler.assemble_event`.
      4. Validate via :func:`~validators.validate_event`.

    Failed normalization and validation are logged and added to the human
    review queue on the ``run_report``.

    Args:
        raw_events: List of RawExtractedEvent dicts from the AI provider.
        venue_source: The :class:`~venue_config.VenueSource` being processed.
        venue_mappings: Dict of venue_id -> :class:`~venue_config.VenueMapping`.
        normalizer: Initialised :class:`~normalizer.VenueNormalizer`.
        today: Current date used as the validation lower bound.
        max_future_date: Validation upper bound.
        run_report: :class:`~report.RunReport` for appending human review items.

    Returns:
        List of fully assembled and validated event dicts.
    """
    venue_id = venue_source.venue_id
    validated: list[dict] = []

    for raw_event in raw_events:
        # Determine which name to normalize.
        if venue_source.site_type == "single_venue":
            name_to_normalize = venue_source.venue_name
        else:
            name_to_normalize = (
                raw_event.get("location_label") or venue_source.venue_name
            )

        resolved_id, _method = normalizer.normalize(name_to_normalize)

        if resolved_id is None:
            run_report.add_human_review_item(
                _build_human_review_item(
                    venue_id=venue_id,
                    issue_type="venue_name_unresolved",
                    severity="high",
                    details=(
                        f"Could not resolve venue name {name_to_normalize!r} "
                        f"for event {raw_event.get('label')!r}"
                    ),
                    suggested_action="Add the alias to config/venue_aliases.csv.",
                    raw_data=str(raw_event),
                    today=today,
                )
            )
            continue

        resolved_mapping = venue_mappings.get(resolved_id)
        if resolved_mapping is None:
            logger.warning(
                "Resolved venue_id=%r has no venue_mapping; skipping event %r",
                resolved_id,
                raw_event.get("label"),
                extra={"venue_id": venue_id},
            )
            continue

        canonical_name = (
            normalizer.get_canonical_name(resolved_id) or resolved_mapping.canonical_name
        )

        assembled = assemble_event(
            raw_event=raw_event,
            venue_source=venue_source,
            venue_mapping=resolved_mapping,
            canonical_venue_name=canonical_name,
            source_url=venue_source.schedule_url,
        )

        is_valid, errors = validate_event(assembled, today, max_future_date)
        if is_valid:
            validated.append(assembled)
        else:
            logger.warning(
                "Validation failure for venue_id=%s event=%r: %s",
                venue_id,
                assembled.get("label"),
                errors,
                extra={"venue_id": venue_id},
            )
            run_report.add_human_review_item(
                _build_human_review_item(
                    venue_id=venue_id,
                    issue_type="validation_failure",
                    severity="medium",
                    details=f"Validation errors: {errors}",
                    suggested_action="Review extracted event data and correct the source.",
                    raw_data=str(assembled),
                    today=today,
                )
            )

    return validated


# ---------------------------------------------------------------------------
# Per-venue pipeline
# ---------------------------------------------------------------------------


async def _process_venue(
    venue_source: VenueSource,
    settings: Settings,
    controller: BrowserController,
    provider,
    normalizer: VenueNormalizer,
    venue_mappings: dict[str, VenueMapping],
    cookie_selectors: list[dict],
    run_report: RunReport,
    data_dir: Path,
    today: date,
    max_future_date: date,
    dry_run: bool,
) -> list[dict]:
    """Process a single venue: browse, screenshot, extract, assemble, validate.

    Wraps the full per-venue pipeline in a retry loop with exponential backoff.
    On each attempt, a fresh isolated browser context is created.

    Args:
        venue_source: The venue to process.
        settings: Runtime settings.
        controller: Active :class:`~browser.BrowserController`.
        provider: :class:`~ai_vision.base.VisionProvider` for AI extraction
            (may be ``None`` when ``dry_run=True``).
        normalizer: Initialised :class:`~normalizer.VenueNormalizer`.
        venue_mappings: Dict of venue_id -> :class:`~venue_config.VenueMapping`.
        cookie_selectors: Selector list from ``cookie_selectors.yaml``.
        run_report: :class:`~report.RunReport` for recording results.
        data_dir: Base data directory for screenshots.
        today: Current date (validation lower bound).
        max_future_date: Validation upper bound.
        dry_run: If ``True``, skip AI calls and return an empty list.

    Returns:
        List of validated event dicts for this venue; empty on failure.
    """
    venue_id = venue_source.venue_id
    run_report.record_venue_attempt(venue_id)

    venue_mapping = venue_mappings.get(venue_id)
    if venue_mapping is None:
        reason = f"No venue_mapping found for venue_id={venue_id!r}"
        logger.error(reason, extra={"venue_id": venue_id})
        run_report.record_venue_skip(venue_id, reason)
        return []

    venue_context: dict = {
        "venue_id": venue_id,
        "venue_name": venue_source.venue_name,
        "site_type": venue_source.site_type,
        "event_window_start": today.isoformat(),
        "event_window_end": max_future_date.isoformat(),
    }

    screenshots_dir = data_dir / "screenshots"

    for attempt in range(settings.max_retry_count + 1):
        try:
            async with controller.venue_page(venue_id) as page:
                logger.info(
                    "Loading %s for venue_id=%s (attempt %d/%d)",
                    venue_source.schedule_url,
                    venue_id,
                    attempt + 1,
                    settings.max_retry_count + 1,
                    extra={"venue_id": venue_id},
                )

                await page.goto(
                    venue_source.schedule_url,
                    wait_until="networkidle",
                    timeout=30_000,
                )
                await asyncio.sleep(settings.page_load_delay_seconds)

                # Deterministic cookie dismissal (no AI fallback on first pass).
                await dismiss_cookie_modal(
                    page=page,
                    selectors=cookie_selectors,
                    provider=None,
                    venue_id=venue_id,
                )

                # Free local work: scroll, load more, calendar pagination.
                await expand_page(page, settings)

                if dry_run:
                    logger.info(
                        "dry-run: skipping AI call for venue_id=%s",
                        venue_id,
                        extra={"venue_id": venue_id},
                    )
                    run_report.record_venue_success(venue_id, 0)
                    return []

                screenshots = await take_screenshots(
                    page=page,
                    settings=settings,
                    save_dir=screenshots_dir,
                    venue_id=venue_id,
                )

                if not screenshots:
                    reason = "No screenshots captured"
                    logger.warning(
                        "%s for venue_id=%s",
                        reason,
                        venue_id,
                        extra={"venue_id": venue_id},
                    )
                    run_report.record_venue_skip(venue_id, reason)
                    return []

                # AI extraction.
                prompt = build_extraction_prompt(venue_context, is_detail_page=False)
                raw_events: list[dict] = await provider.extract_events(
                    screenshots=screenshots,
                    prompt=prompt,
                    venue_context=venue_context,
                )

                logger.info(
                    "AI extracted %d raw event(s) for venue_id=%s",
                    len(raw_events),
                    venue_id,
                    extra={"venue_id": venue_id},
                )

                # Fetch detail pages for events that require them.
                enriched_events: list[dict] = []
                for raw_event in raw_events:
                    if raw_event.get("requires_detail_page"):
                        detail_url = (
                            raw_event.get("detail_url") or raw_event.get("web")
                        )
                        if detail_url:
                            extra_fields = await fetch_event_detail(
                                page=page,
                                event_url=detail_url,
                                missing_fields=["event_start_time", "event_start_date"],
                                provider=provider,
                                venue_context=venue_context,
                                settings=settings,
                                save_dir=screenshots_dir,
                            )
                            enriched_events.append({**raw_event, **extra_fields})
                        else:
                            enriched_events.append(raw_event)
                    else:
                        enriched_events.append(raw_event)

            # Outside the context manager so the browser context is closed.
            validated = _process_raw_events(
                raw_events=enriched_events,
                venue_source=venue_source,
                venue_mappings=venue_mappings,
                normalizer=normalizer,
                today=today,
                max_future_date=max_future_date,
                run_report=run_report,
            )

            run_report.record_venue_success(venue_id, len(validated))
            logger.info(
                "venue_id=%s: %d event(s) passed validation",
                venue_id,
                len(validated),
                extra={"venue_id": venue_id},
            )
            return validated

        except Exception as exc:
            logger.error(
                "Error processing venue_id=%s (attempt %d/%d): %s",
                venue_id,
                attempt + 1,
                settings.max_retry_count + 1,
                exc,
                exc_info=True,
                extra={"venue_id": venue_id},
            )
            if attempt < settings.max_retry_count:
                backoff = settings.retry_backoff_base_seconds * (2**attempt)
                logger.info(
                    "Retrying venue_id=%s in %.1f s",
                    venue_id,
                    backoff,
                    extra={"venue_id": venue_id},
                )
                await asyncio.sleep(backoff)
            else:
                run_report.record_venue_skip(
                    venue_id, f"Max retries exceeded: {exc}"
                )

    return []


# ---------------------------------------------------------------------------
# Main async run function
# ---------------------------------------------------------------------------


async def run(args: argparse.Namespace) -> int:
    """Execute the full event aggregation pipeline.

    Args:
        args: Parsed command-line arguments from :func:`_build_parser`.

    Returns:
        Exit code: ``0`` on success, ``1`` on critical failure.
    """
    config_dir = Path(args.config_dir)
    data_dir = Path(args.data_dir)
    log_dir = Path(args.log_dir)
    input_path = Path(args.input)

    # Load .env before reading os.environ.
    load_dotenv()

    # Load settings; apply CLI overrides.
    settings = load_settings(config_dir)
    if args.log_level:
        settings.log_level = args.log_level
    if args.provider:
        settings.primary_provider = args.provider
    if args.event_window_months:
        settings.event_window_months = args.event_window_months

    # Setup logging (console + JSON file).
    setup_logging(settings.log_level, log_dir)

    logger.info(
        "Event aggregator starting — provider=%s dry_run=%s",
        settings.primary_provider,
        args.dry_run,
    )

    # Load config.
    try:
        venue_mappings = load_venue_mappings(config_dir)
        venue_aliases = load_venue_aliases(config_dir)
        cookie_selectors = load_cookie_selectors(config_dir)
    except (FileNotFoundError, ValueError) as exc:
        logger.critical("Configuration loading failed: %s", exc)
        return 1

    # Validate required API key for the chosen provider.
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
    google_key = os.environ.get("GOOGLE_AI_KEY", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")

    if not args.dry_run:
        provider_name = settings.primary_provider
        key_needed = ""
        if provider_name in ("gemini-flash", "gemini-pro") and not google_key:
            key_needed = "GOOGLE_AI_KEY"
        elif provider_name in ("gpt-4o", "gpt-4o-mini", "gpt-4.1") and not openai_key:
            key_needed = "OPENAI_API_KEY"
        elif provider_name in ("claude-sonnet", "claude-opus") and not anthropic_key:
            key_needed = "ANTHROPIC_API_KEY"
        if key_needed:
            logger.critical(
                "Required API key %r is not set in .env. Cannot proceed.", key_needed
            )
            return 1

    # Determine event window.
    today = date.today()
    max_future_date = today + timedelta(days=30 * settings.event_window_months)

    # Determine output path.
    if args.output:
        output_path = Path(args.output)
    else:
        output_path = data_dir / f"event_table_update_{today.strftime('%Y%m%d')}.csv"

    # Initialise tracking objects.
    cost_tracker = CostTracker(max_cost_usd=settings.max_cost_usd)
    run_report = RunReport(log_dir=log_dir)

    # Human review items the normalizer appends between venues.
    human_review_buffer: list[dict] = []
    normalizer = VenueNormalizer(
        aliases=venue_aliases,
        mappings=venue_mappings,
        fuzzy_threshold=settings.fuzzy_match_threshold,
        human_review_queue=human_review_buffer,
    )

    # Initialise AI provider (skipped in dry-run).
    provider = None
    if not args.dry_run:
        try:
            provider = get_provider(
                settings.primary_provider,
                cost_tracker,
                data_dir,
                google_api_key=google_key,
                openai_api_key=openai_key,
                anthropic_api_key=anthropic_key,
            )
        except ValueError as exc:
            logger.critical("Failed to initialise AI provider: %s", exc)
            return 1

    # Load venue sources.
    try:
        venue_sources = read_event_source_csv(input_path)
    except (FileNotFoundError, ValueError) as exc:
        logger.critical("Failed to read input CSV %s: %s", input_path, exc)
        return 1

    if not venue_sources:
        logger.warning("No venue sources found in %s — nothing to do.", input_path)
        return 0

    logger.info("Processing %d venue source(s)", len(venue_sources))

    # -----------------------------------------------------------------------
    # Main venue processing loop
    # -----------------------------------------------------------------------
    all_valid_events: list[dict] = []
    total_extracted = 0

    async with async_playwright() as playwright:
        controller = BrowserController(playwright, settings)
        await controller.start()
        try:
            for venue_source in venue_sources:
                # Switch to cheapest provider if budget is blown.
                if not args.dry_run and cost_tracker.is_over_budget():
                    cheapest = cost_tracker.get_cheapest_provider_name()
                    if cheapest != settings.primary_provider:
                        logger.warning(
                            "Budget cap exceeded ($%.4f / $%.4f); "
                            "switching to provider '%s'",
                            cost_tracker.get_total_cost(),
                            settings.max_cost_usd,
                            cheapest,
                        )
                        settings.primary_provider = cheapest
                        try:
                            provider = get_provider(
                                cheapest,
                                cost_tracker,
                                data_dir,
                                google_api_key=google_key,
                                openai_api_key=openai_key,
                                anthropic_api_key=anthropic_key,
                            )
                        except ValueError as exc:
                            logger.error(
                                "Could not switch to provider '%s': %s", cheapest, exc
                            )

                venue_events = await _process_venue(
                    venue_source=venue_source,
                    settings=settings,
                    controller=controller,
                    provider=provider,
                    normalizer=normalizer,
                    venue_mappings=venue_mappings,
                    cookie_selectors=cookie_selectors,
                    run_report=run_report,
                    data_dir=data_dir,
                    today=today,
                    max_future_date=max_future_date,
                    dry_run=args.dry_run,
                )

                # Flush any normalizer-queued review items.
                for item in human_review_buffer:
                    run_report.add_human_review_item(item)
                human_review_buffer.clear()

                total_extracted += len(venue_events)
                all_valid_events.extend(venue_events)

        finally:
            await controller.stop()

    # -----------------------------------------------------------------------
    # Post-processing: dedup, write CSV, reports
    # -----------------------------------------------------------------------
    deduplicated = deduplicate_events(all_valid_events)
    total_excluded = total_extracted - len(deduplicated)

    if not args.dry_run:
        events_written = write_event_table_csv(deduplicated, output_path)
        logger.info("Wrote %d event(s) to %s", events_written, output_path)
    else:
        logger.info("dry-run: skipped writing output CSV")

    # Forward cost records from the cost tracker into the run report.
    for cost_record in cost_tracker.get_all_records():
        run_report.record_ai_cost(cost_record)

    run_report.finalize(
        total_events_extracted=total_extracted,
        total_events_validated=len(deduplicated),
        total_events_excluded=total_excluded,
    )

    logger.info(
        "Run complete — extracted=%d validated=%d excluded=%d cost=$%.4f",
        total_extracted,
        len(deduplicated),
        total_excluded,
        cost_tracker.get_total_cost(),
    )
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Parse CLI arguments and run the aggregation pipeline."""
    parser = _build_parser()
    args = parser.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
