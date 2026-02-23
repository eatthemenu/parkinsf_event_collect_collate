"""Click-through handler for event detail pages.

Navigates to an individual event detail page, captures a screenshot, and uses
the AI vision provider to extract fields that were missing or incomplete on the
schedule list page.
"""

import asyncio
import logging
from pathlib import Path

from playwright.async_api import Page

from .ai_vision.base import VisionProvider
from .ai_vision.prompt_templates import build_extraction_prompt
from .venue_config import Settings

logger = logging.getLogger(__name__)


async def fetch_event_detail(
    page: Page,
    event_url: str,
    missing_fields: list[str],
    provider: VisionProvider,
    venue_context: dict,
    settings: Settings,
    save_dir: Path,
) -> dict:
    """Navigate to an event detail page and extract missing fields.

    Used when the list-page screenshot returned requires_detail_page=True or
    when event_start_time or location_label is None.

    Steps:
      1. Navigate to event_url.
      2. Wait for network idle + settings.page_load_delay_seconds.
      3. Take a single full-page screenshot (or viewport if too tall).
      4. Build prompt with is_detail_page=True.
      5. Call provider.extract_events() with the detail screenshot.
      6. From the response (which may be a list of 1 event), extract the first
         event's missing_fields values.
      7. Navigate back to the previous page.
      8. Return dict of {field_name: value} for only the missing_fields.

    On any error: log ERROR, navigate back if possible, return {} (empty dict).

    Args:
        page: Playwright Page (on the list page before navigation).
        event_url: Full URL of the detail page.
        missing_fields: List of field names we need (e.g. ["event_start_time"]).
        provider: Vision provider for AI extraction.
        venue_context: Dict with venue_id, venue_name, site_type,
            event_window_start, event_window_end.
        settings: Runtime settings.
        save_dir: Directory for saving detail-page screenshots.

    Returns:
        Dict of {field_name: extracted_value} for only the missing_fields that
        were found. Empty dict on error.
    """
    venue_id: str = venue_context.get("venue_id", "unknown")
    previous_url: str = page.url

    save_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Step 1 & 2: Navigate to the detail page and wait for load.
    # ------------------------------------------------------------------
    try:
        await page.goto(event_url, wait_until="networkidle", timeout=30_000)
        await asyncio.sleep(settings.page_load_delay_seconds)
    except Exception as exc:
        logger.error(
            "fetch_event_detail: navigation to %r failed for venue_id=%s: %s",
            event_url,
            venue_id,
            exc,
            exc_info=True,
        )
        await _navigate_back(page, previous_url)
        return {}

    # ------------------------------------------------------------------
    # Step 3: Capture screenshot (single page, or viewport if very tall).
    # ------------------------------------------------------------------
    try:
        total_height: int = await page.evaluate("document.body.scrollHeight")
    except Exception as exc:
        logger.debug(
            "fetch_event_detail: scrollHeight read error for venue_id=%s (%s); "
            "defaulting to viewport",
            venue_id,
            exc,
        )
        total_height = settings.viewport_height

    from datetime import datetime  # local import to keep module-level clean

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    screenshot_path = save_dir / f"{venue_id}_{timestamp_str}_detail.png"

    try:
        if total_height <= settings.screenshot_max_height_px:
            img_bytes: bytes = await page.screenshot(full_page=True)
        else:
            # Tall detail page: just capture the visible viewport.
            img_bytes = await page.screenshot()

        screenshot_path.write_bytes(img_bytes)
        logger.debug(
            "fetch_event_detail: detail screenshot saved to %s (%d bytes)",
            screenshot_path,
            len(img_bytes),
        )
    except Exception as exc:
        logger.error(
            "fetch_event_detail: screenshot failed for venue_id=%s at %r: %s",
            venue_id,
            event_url,
            exc,
            exc_info=True,
        )
        await _navigate_back(page, previous_url)
        return {}

    # ------------------------------------------------------------------
    # Step 4 & 5: Build prompt and call AI.
    # ------------------------------------------------------------------
    prompt = build_extraction_prompt(venue_context, is_detail_page=True)

    try:
        ai_results: list[dict] = await provider.extract_events(
            screenshots=[img_bytes],
            prompt=prompt,
            venue_context=venue_context,
        )
    except Exception as exc:
        logger.error(
            "fetch_event_detail: AI extract_events failed for venue_id=%s at %r: %s",
            venue_id,
            event_url,
            exc,
            exc_info=True,
        )
        await _navigate_back(page, previous_url)
        return {}

    # ------------------------------------------------------------------
    # Step 6: Extract only the requested missing fields from the first event.
    # ------------------------------------------------------------------
    extracted: dict = {}
    if ai_results:
        first_event = ai_results[0]
        if isinstance(first_event, dict):
            for field in missing_fields:
                value = first_event.get(field)
                if value is not None:
                    extracted[field] = value
        else:
            logger.warning(
                "fetch_event_detail: AI result first item is not a dict "
                "(type=%s) for venue_id=%s at %r",
                type(first_event).__name__,
                venue_id,
                event_url,
            )
    else:
        logger.warning(
            "fetch_event_detail: AI returned no events for venue_id=%s at %r",
            venue_id,
            event_url,
        )

    logger.info(
        "fetch_event_detail: extracted %d/%d missing fields for venue_id=%s at %r",
        len(extracted),
        len(missing_fields),
        venue_id,
        event_url,
    )

    # ------------------------------------------------------------------
    # Step 7: Navigate back to the list page.
    # ------------------------------------------------------------------
    await _navigate_back(page, previous_url)

    # ------------------------------------------------------------------
    # Step 8: Return only the fields we found.
    # ------------------------------------------------------------------
    return extracted


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _navigate_back(page: Page, fallback_url: str) -> None:
    """Navigate the page back to the previous URL.

    First tries the browser's built-in back navigation; falls back to a
    direct goto() if that fails.

    Args:
        page: Playwright Page to navigate.
        fallback_url: URL to navigate to if page.go_back() fails.
    """
    try:
        await page.go_back(wait_until="networkidle", timeout=15_000)
        return
    except Exception as exc:
        logger.debug(
            "_navigate_back: go_back() failed (%s); falling back to goto %r",
            exc,
            fallback_url,
        )

    try:
        await page.goto(fallback_url, wait_until="networkidle", timeout=15_000)
    except Exception as exc:
        logger.error(
            "_navigate_back: goto(%r) also failed: %s",
            fallback_url,
            exc,
            exc_info=True,
        )
