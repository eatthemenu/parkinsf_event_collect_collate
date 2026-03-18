"""Run statistics collection and report file generation.

Provides :class:`RunReport`, which accumulates per-venue and per-AI-call
statistics throughout a pipeline run and writes three output files on
:meth:`~RunReport.finalize`:

- ``logs/cost_YYYYMMDD.log``        — one JSON line per AI call + summary.
- ``logs/human_review_YYYYMMDD.csv`` — events/venues requiring human attention.
- ``logs/summary_YYYYMMDD.txt``     — human-readable run summary.
"""

import csv
import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# CSV columns for the human review file.
_HUMAN_REVIEW_COLUMNS: list[str] = [
    "timestamp",
    "venue_id",
    "issue_type",
    "severity",
    "details",
    "suggested_action",
    "raw_data",
]


class RunReport:
    """Collects run statistics and writes the three output report files.

    Intended to be instantiated once per pipeline run, updated incrementally
    via the ``record_*`` and ``add_*`` methods, and finalised at the end of
    the run via :meth:`finalize`.

    Attributes:
        log_dir: Directory where report files are written.
    """

    def __init__(self, log_dir: Path) -> None:
        """Initialise a RunReport for a new pipeline run.

        Args:
            log_dir: Directory where cost, human-review, and summary files
                will be written.  Created if it does not exist.
        """
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self._run_date: str = datetime.now().strftime("%Y%m%d")

        # Per-venue tracking
        self._venues_attempted: list[str] = []
        self._venues_succeeded: dict[str, int] = {}  # venue_id -> event_count
        self._venues_skipped: dict[str, str] = {}  # venue_id -> reason

        # Human review queue
        self._human_review_items: list[dict] = []

        # AI cost tracking
        self._cost_records: list[dict] = []
        self._total_cost_usd: float = 0.0

        logger.debug("RunReport initialised; log_dir=%s", log_dir)

    # ------------------------------------------------------------------
    # Per-venue recording
    # ------------------------------------------------------------------

    def record_venue_attempt(self, venue_id: str) -> None:
        """Record that a venue was attempted.

        Should be called once per venue before any processing begins.

        Args:
            venue_id: The venue's stable identifier.
        """
        self._venues_attempted.append(venue_id)
        logger.debug("Venue attempt recorded: %s", venue_id, extra={"venue_id": venue_id})

    def record_venue_success(self, venue_id: str, event_count: int) -> None:
        """Record a successful venue scrape.

        Args:
            venue_id: The venue's stable identifier.
            event_count: Number of events extracted from the venue's schedule.
        """
        self._venues_succeeded[venue_id] = event_count
        logger.debug(
            "Venue success recorded: %s (%d events)",
            venue_id,
            event_count,
            extra={"venue_id": venue_id},
        )

    def record_venue_skip(self, venue_id: str, reason: str) -> None:
        """Record that a venue was skipped (after exhausting retries).

        Args:
            venue_id: The venue's stable identifier.
            reason: Human-readable explanation for why the venue was skipped.
        """
        self._venues_skipped[venue_id] = reason
        logger.warning("Venue skipped: %s — %s", venue_id, reason, extra={"venue_id": venue_id})

    # ------------------------------------------------------------------
    # Human review queue
    # ------------------------------------------------------------------

    def add_human_review_item(self, item: dict) -> None:
        """Add a HumanReviewItem dict to the human review queue.

        The ``item`` dict must contain the keys defined in the HumanReviewItem
        schema: ``timestamp``, ``venue_id``, ``issue_type``, ``severity``,
        ``details``, ``suggested_action``, ``raw_data``.

        Args:
            item: A dict conforming to the HumanReviewItem schema.
        """
        self._human_review_items.append(item)
        logger.debug(
            "Human review item added: venue=%s issue=%s severity=%s",
            item.get("venue_id"),
            item.get("issue_type"),
            item.get("severity"),
            extra={"venue_id": item.get("venue_id", "")},
        )

    # ------------------------------------------------------------------
    # AI cost tracking
    # ------------------------------------------------------------------

    def record_ai_cost(self, cost_record: dict) -> None:
        """Add a CostRecord dict and accumulate the total cost.

        The ``cost_record`` dict must conform to the CostRecord schema:
        ``timestamp``, ``provider``, ``model``, ``venue_id``,
        ``input_tokens``, ``output_tokens``, ``estimated_cost_usd``,
        ``success``, ``error_message``.

        Args:
            cost_record: A dict conforming to the CostRecord schema.
        """
        self._cost_records.append(cost_record)
        cost = float(cost_record.get("estimated_cost_usd", 0.0))
        self._total_cost_usd += cost
        logger.debug(
            "AI cost recorded: provider=%s model=%s venue=%s cost=$%.4f total=$%.4f",
            cost_record.get("provider"),
            cost_record.get("model"),
            cost_record.get("venue_id"),
            cost,
            self._total_cost_usd,
            extra={"venue_id": cost_record.get("venue_id", "")},
        )

    def get_total_cost(self) -> float:
        """Return the accumulated AI spend for this run in US dollars.

        Returns:
            Total estimated cost in USD.
        """
        return self._total_cost_usd

    def is_over_budget(self, max_cost: float) -> bool:
        """Check whether the accumulated AI spend has exceeded the budget cap.

        Args:
            max_cost: The per-run spending cap in USD.

        Returns:
            ``True`` if total cost exceeds ``max_cost``, otherwise ``False``.
        """
        return self._total_cost_usd > max_cost

    # ------------------------------------------------------------------
    # Finalise: write all three output files
    # ------------------------------------------------------------------

    def finalize(
        self,
        total_events_extracted: int,
        total_events_validated: int,
        total_events_excluded: int,
    ) -> None:
        """Write the three output report files to :attr:`log_dir`.

        Files written:

        1. ``logs/cost_YYYYMMDD.log`` — one JSON line per :class:`CostRecord`,
           followed by a JSON summary line.
        2. ``logs/human_review_YYYYMMDD.csv`` — CSV with one row per
           :class:`HumanReviewItem`.
        3. ``logs/summary_YYYYMMDD.txt`` — human-readable run summary.

        Args:
            total_events_extracted: Total events returned by AI across all venues.
            total_events_validated: Events that passed all validation checks.
            total_events_excluded: Events excluded due to validation failures.
        """
        self._write_cost_log()
        self._write_human_review_csv()
        self._write_summary_txt(
            total_events_extracted=total_events_extracted,
            total_events_validated=total_events_validated,
            total_events_excluded=total_events_excluded,
        )
        logger.info("Run reports written to %s (date suffix: %s)", self.log_dir, self._run_date)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _write_cost_log(self) -> None:
        """Write per-call cost records plus a summary line to the cost log file."""
        cost_path = self.log_dir / f"cost_{self._run_date}.log"

        with cost_path.open("w", encoding="utf-8") as fh:
            for record in self._cost_records:
                fh.write(json.dumps(record, default=str) + "\n")

            # Summary line
            summary = {
                "type": "summary",
                "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "total_calls": len(self._cost_records),
                "total_input_tokens": sum(
                    int(r.get("input_tokens", 0)) for r in self._cost_records
                ),
                "total_output_tokens": sum(
                    int(r.get("output_tokens", 0)) for r in self._cost_records
                ),
                "total_estimated_cost_usd": round(self._total_cost_usd, 6),
                "successful_calls": sum(1 for r in self._cost_records if r.get("success", False)),
                "failed_calls": sum(1 for r in self._cost_records if not r.get("success", True)),
            }
            fh.write(json.dumps(summary, default=str) + "\n")

        logger.debug("Cost log written to %s (%d records)", cost_path, len(self._cost_records))

    def _write_human_review_csv(self) -> None:
        """Write all human review items to the human review CSV file."""
        review_path = self.log_dir / f"human_review_{self._run_date}.csv"

        with review_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=_HUMAN_REVIEW_COLUMNS,
                extrasaction="ignore",
                lineterminator="\n",
            )
            writer.writeheader()

            for item in self._human_review_items:
                sanitised = {
                    col: ("" if item.get(col) is None else str(item.get(col, "")))
                    for col in _HUMAN_REVIEW_COLUMNS
                }
                writer.writerow(sanitised)

        logger.debug(
            "Human review CSV written to %s (%d items)",
            review_path,
            len(self._human_review_items),
        )

    def _write_summary_txt(
        self,
        total_events_extracted: int,
        total_events_validated: int,
        total_events_excluded: int,
    ) -> None:
        """Write a human-readable run summary to the summary text file.

        Args:
            total_events_extracted: Total events returned by AI.
            total_events_validated: Events passing all validators.
            total_events_excluded: Events excluded due to validation failures.
        """
        summary_path = self.log_dir / f"summary_{self._run_date}.txt"

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        venues_attempted_count = len(self._venues_attempted)
        venues_succeeded_count = len(self._venues_succeeded)
        venues_skipped_count = len(self._venues_skipped)

        # Top issue types from human review queue
        issue_counter: Counter = Counter(
            item.get("issue_type", "unknown") for item in self._human_review_items
        )
        top_issues = issue_counter.most_common(10)

        lines: list[str] = [
            "=" * 72,
            "EVENT AGGREGATOR RUN SUMMARY",
            f"Generated: {now_str}",
            "=" * 72,
            "",
            "VENUE STATISTICS",
            "-" * 40,
            f"  Venues attempted : {venues_attempted_count}",
            f"  Venues succeeded : {venues_succeeded_count}",
            f"  Venues skipped   : {venues_skipped_count}",
            "",
            "EVENT STATISTICS",
            "-" * 40,
            f"  Events extracted : {total_events_extracted}",
            f"  Events validated : {total_events_validated}",
            f"  Events excluded  : {total_events_excluded}",
            "",
            "AI COST",
            "-" * 40,
            f"  Total AI cost    : ${self._total_cost_usd:.4f}",
            f"  Total AI calls   : {len(self._cost_records)}",
        ]

        # Per-provider breakdown
        provider_costs: dict[str, float] = {}
        for record in self._cost_records:
            provider = str(record.get("provider", "unknown"))
            provider_costs[provider] = provider_costs.get(provider, 0.0) + float(
                record.get("estimated_cost_usd", 0.0)
            )
        if provider_costs:
            lines.append("  Cost by provider:")
            for provider, cost in sorted(provider_costs.items(), key=lambda x: -x[1]):
                lines.append(f"    {provider}: ${cost:.4f}")

        lines += ["", "SKIPPED VENUES", "-" * 40]
        if self._venues_skipped:
            for venue_id, reason in sorted(self._venues_skipped.items()):
                lines.append(f"  {venue_id}: {reason}")
        else:
            lines.append("  (none)")

        lines += ["", "PER-VENUE EVENT COUNTS", "-" * 40]
        if self._venues_succeeded:
            for venue_id in self._venues_attempted:
                if venue_id in self._venues_succeeded:
                    lines.append(f"  {venue_id}: {self._venues_succeeded[venue_id]} events")
        else:
            lines.append("  (no successes)")

        lines += ["", "HUMAN REVIEW QUEUE", "-" * 40]
        lines.append(f"  Total items      : {len(self._human_review_items)}")
        if total_events_extracted > 0:
            queue_pct = len(self._human_review_items) / total_events_extracted * 100
            lines.append(f"  As % of extracted: {queue_pct:.1f}%")
            if queue_pct >= 15.0:
                lines.append("  WARNING: human review queue exceeds 15% quality gate threshold!")

        if top_issues:
            lines.append("  Top issue types:")
            for issue_type, count in top_issues:
                lines.append(f"    {issue_type}: {count}")
        elif self._human_review_items:
            lines.append("  (no issue types recorded)")
        else:
            lines.append("  (queue empty — all clear)")

        lines += [
            "",
            "=" * 72,
            "END OF SUMMARY",
            "=" * 72,
            "",
        ]

        summary_path.write_text("\n".join(lines), encoding="utf-8")
        logger.debug("Summary written to %s", summary_path)
