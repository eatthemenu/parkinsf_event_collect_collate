"""CSV I/O utilities for the event aggregator.

Provides:
- :func:`read_event_source_csv`: reads the Event Source CSV into
  :class:`~venue_config.VenueSource` objects.
- :func:`write_event_table_csv`: writes assembled event dicts to the
  Event Table Update CSV in the exact column order required by MySQL.
"""

import csv
import logging
from pathlib import Path

from .venue_config import VenueSource

logger = logging.getLogger(__name__)

OUTPUT_COLUMNS: list[str] = [
    "label",
    "location_label",
    "latitude",
    "longitude",
    "radius",
    "event_start_date",
    "event_start_time",
    "event_duration",
    "hours_before_start",
    "hours_after_end",
    "details",
    "web",
    "icon",
    "affected_garages_ids",
    "affected_areas",
]

_REQUIRED_SOURCE_COLUMNS: frozenset[str] = frozenset(
    {"venue_id", "venue_name", "schedule_url", "site_type"}
)


def read_event_source_csv(path: Path) -> list[VenueSource]:
    """Read the Event Source CSV and return a list of VenueSource objects.

    The CSV must contain at minimum the columns ``venue_id``, ``venue_name``,
    ``schedule_url``, and ``site_type``.  Rows that are missing a value for
    any required column are logged as warnings and skipped.

    Args:
        path: Absolute path to the Event Source CSV file.

    Returns:
        List of :class:`~venue_config.VenueSource` instances, one per valid row.

    Raises:
        FileNotFoundError: If the file at ``path`` does not exist.
        ValueError: If one or more required columns are absent from the header.
    """
    if not path.exists():
        raise FileNotFoundError(f"Event Source CSV not found at {path}")

    sources: list[VenueSource] = []

    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)

        if reader.fieldnames is None:
            logger.warning("Event Source CSV at %s appears to be empty", path)
            return sources

        present_columns = set(reader.fieldnames)
        missing_columns = _REQUIRED_SOURCE_COLUMNS - present_columns
        if missing_columns:
            raise ValueError(
                f"Event Source CSV is missing required columns: {sorted(missing_columns)}"
            )

        for row_num, row in enumerate(reader, start=2):
            venue_id = row.get("venue_id", "").strip()
            venue_name = row.get("venue_name", "").strip()
            schedule_url = row.get("schedule_url", "").strip()
            site_type = row.get("site_type", "").strip()

            missing_values: list[str] = []
            if not venue_id:
                missing_values.append("venue_id")
            if not venue_name:
                missing_values.append("venue_name")
            if not schedule_url:
                missing_values.append("schedule_url")
            if not site_type:
                missing_values.append("site_type")

            if missing_values:
                logger.warning(
                    "Row %d in Event Source CSV is missing values for %s — skipped",
                    row_num,
                    missing_values,
                    extra={"venue_id": venue_id or "<unknown>"},
                )
                continue

            sources.append(
                VenueSource(
                    venue_id=venue_id,
                    venue_name=venue_name,
                    schedule_url=schedule_url,
                    site_type=site_type,
                )
            )

    logger.debug("Read %d venue sources from %s", len(sources), path)
    return sources


def write_event_table_csv(events: list[dict], path: Path) -> int:
    """Write assembled event dicts to the Event Table Update CSV.

    Columns are written in the exact order defined by :data:`OUTPUT_COLUMNS`.
    ``None`` values are written as empty strings rather than the literal
    string ``"None"`` or ``"NULL"``.

    Args:
        events: List of event dicts.  Each dict is expected to contain keys
            matching :data:`OUTPUT_COLUMNS`; extra keys are silently ignored and
            missing keys produce empty strings.
        path: Destination file path.  Parent directories are created if absent.

    Returns:
        Number of data rows written (excluding the header row).
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    rows_written = 0

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=OUTPUT_COLUMNS,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()

        for event in events:
            # Replace None values with empty string.
            sanitised_row: dict[str, str] = {
                col: ("" if event.get(col) is None else str(event.get(col, "")))
                for col in OUTPUT_COLUMNS
            }
            writer.writerow(sanitised_row)
            rows_written += 1

    logger.debug("Wrote %d event rows to %s", rows_written, path)
    return rows_written
