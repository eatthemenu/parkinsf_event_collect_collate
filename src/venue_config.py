"""Venue configuration loaders and shared dataclasses.

Provides dataclass definitions for VenueSource, VenueMapping, and Settings,
plus functions that load each configuration artefact from the config/ directory.
"""

import csv
import logging
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class VenueSource:
    """Represents a single row from the Event Source CSV.

    Attributes:
        venue_id: Stable, unique identifier for the venue (e.g. ``sf_symphony``).
        venue_name: Human-readable venue name.
        schedule_url: Full URL of the venue's schedule page.
        site_type: Either ``"single_venue"`` or ``"multi_venue"``.
        icon: Optional icon path override for this source.  When set, it takes
            precedence over the icon from the venue mapping.  Use this when the
            same physical venue hosts events from multiple producers that each
            have their own icon (e.g. SF Opera vs SF Ballet at War Memorial).
    """

    venue_id: str
    venue_name: str
    schedule_url: str
    site_type: str
    icon: str = ""


@dataclass
class VenueMapping:
    """Geographic and display metadata for a venue, loaded from venue_to_lat_lon_mapping.csv.

    Attributes:
        location_label: The authoritative display name for this venue, used as
            the primary key.  Matches the ``location_label`` field in the output
            CSV and the MySQL events table.
        latitude: WGS-84 latitude of the venue.
        longitude: WGS-84 longitude of the venue.
        icon: Icon path string for the parking app UI (e.g.
            ``"/img/event_icon/sf_opera.png"``).  May be overridden by
            :attr:`VenueSource.icon` when the same venue hosts events from
            multiple producers.
        radius: Radius (in miles) around the venue used by the parking app.
        affected_garages_ids: Comma-separated garage IDs as a raw string
            (e.g. ``"12,34"``), or empty string if none.
        affected_areas: Reserved field; currently always empty.
    """

    location_label: str
    latitude: float
    longitude: float
    icon: str
    radius: float
    affected_garages_ids: str
    affected_areas: str


@dataclass
class Settings:
    """Runtime configuration for the aggregator pipeline.

    All values have sensible defaults and can be overridden via
    ``config/settings.yaml``.

    Attributes:
        max_retry_count: Maximum browser/network retry attempts per venue.
        ai_max_retry_count: Maximum AI API retry attempts per call.
        retry_backoff_base_seconds: Base delay (seconds) for exponential backoff.
        max_cost_usd: Per-run AI spending cap in US dollars.
        event_window_months: How many months ahead to collect events.
        page_load_delay_seconds: Seconds to wait after each page load.
        max_load_more_clicks: Maximum "Load More" button clicks per page.
        max_calendar_page_clicks: Maximum calendar pagination clicks per venue.
        browser_restart_interval: Restart the browser every N venues.
        scroll_pause_seconds: Seconds to pause between scroll steps.
        screenshot_max_height_px: Maximum page height before chunking screenshots.
        viewport_width: Browser viewport width in pixels.
        viewport_height: Browser viewport height in pixels.
        screenshot_overlap_px: Pixel overlap between screenshot chunks.
        fuzzy_match_threshold: Minimum thefuzz score to accept a fuzzy venue match.
        primary_provider: AI provider slug used for the primary call.
        fallback_provider: AI provider slug used when the primary call fails.
        log_level: Logging level string (DEBUG, INFO, WARNING, ERROR).
        data_retention_days: Days to retain data/ artefacts before auto-cleanup.
    """

    max_retry_count: int = 2
    ai_max_retry_count: int = 3
    retry_backoff_base_seconds: float = 2.0
    max_cost_usd: float = 40.0
    event_window_months: int = 6
    page_load_delay_seconds: float = 2.0
    max_load_more_clicks: int = 20
    max_calendar_page_clicks: int = 12
    browser_restart_interval: int = 10
    scroll_pause_seconds: float = 1.0
    screenshot_max_height_px: int = 3000
    viewport_width: int = 1280
    viewport_height: int = 900
    screenshot_overlap_px: int = 100
    fuzzy_match_threshold: int = 85
    primary_provider: str = "gemini-flash"
    fallback_provider: str = "gpt-4o"
    log_level: str = "INFO"
    data_retention_days: int = 30


def load_settings(config_dir: Path) -> Settings:
    """Load runtime settings from config/settings.yaml.

    Keys present in the YAML file override dataclass defaults. Unknown keys
    are silently ignored so that the YAML can contain comments or future
    fields without breaking older code.

    Args:
        config_dir: Directory that contains ``settings.yaml``.

    Returns:
        A fully populated :class:`Settings` instance.
    """
    settings_path = config_dir / "settings.yaml"

    if not settings_path.exists():
        logger.warning("settings.yaml not found at %s — using all defaults", settings_path)
        return Settings()

    with settings_path.open("r", encoding="utf-8") as fh:
        raw: Any = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        logger.warning(
            "settings.yaml did not parse to a dict (got %s) — using all defaults",
            type(raw).__name__,
        )
        return Settings()

    valid_field_names = {f.name for f in fields(Settings)}
    overrides: dict[str, Any] = {}

    for key, value in raw.items():
        if key in valid_field_names:
            overrides[key] = value
        else:
            logger.debug("Ignoring unknown settings key: %r", key)

    settings = Settings(**overrides)
    logger.debug("Settings loaded from %s: %s", settings_path, overrides)
    return settings


def load_venue_mappings(data_dir: Path) -> dict[str, VenueMapping]:
    """Load venue geographic and display metadata from venue_to_lat_lon_mapping.csv.

    The CSV must contain the following headers (in any order):
    ``location_label``, ``latitude``, ``longitude``, ``icon``, ``radius``,
    ``affected_garages_ids``, ``affected_areas``.

    The dict is keyed by ``location_label``.  If the CSV contains duplicate
    ``location_label`` values (e.g. War Memorial Opera House appearing multiple
    times with different icons), the last row wins and a warning is logged.
    Use the ``icon`` column on the Event Source CSV to select the correct icon
    per producer for such venues.

    The string ``"NULL"`` in any field is normalised to an empty string.

    Args:
        data_dir: Directory that contains ``venue_to_lat_lon_mapping.csv``.

    Returns:
        Dict mapping ``location_label`` strings to :class:`VenueMapping` instances.

    Raises:
        FileNotFoundError: If ``venue_to_lat_lon_mapping.csv`` does not exist.
        ValueError: If required columns are absent from the CSV header.
    """
    mappings_path = data_dir / "venue_to_lat_lon_mapping.csv"

    if not mappings_path.exists():
        raise FileNotFoundError(f"venue_to_lat_lon_mapping.csv not found at {mappings_path}")

    required_columns = {
        "location_label",
        "latitude",
        "longitude",
        "icon",
        "radius",
        "affected_garages_ids",
        "affected_areas",
    }

    def _null_to_empty(value: str) -> str:
        """Return empty string for the literal string 'NULL', else strip whitespace."""
        stripped = value.strip()
        return "" if stripped.upper() == "NULL" else stripped

    result: dict[str, VenueMapping] = {}

    with mappings_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)

        if reader.fieldnames is None:
            logger.warning("venue_to_lat_lon_mapping.csv appears to be empty")
            return result

        present = set(reader.fieldnames)
        missing = required_columns - present
        if missing:
            raise ValueError(
                f"venue_to_lat_lon_mapping.csv is missing required columns: {sorted(missing)}"
            )

        for row_num, row in enumerate(reader, start=2):
            location_label = _null_to_empty(row.get("location_label", ""))
            if not location_label:
                logger.warning(
                    "Row %d in venue_to_lat_lon_mapping.csv has no location_label — skipped",
                    row_num,
                )
                continue

            if location_label in result:
                logger.warning(
                    "Row %d: duplicate location_label %r in venue_to_lat_lon_mapping.csv"
                    " — last row wins (use event source icon override for producer-specific icons)",
                    row_num,
                    location_label,
                )

            try:
                mapping = VenueMapping(
                    location_label=location_label,
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    icon=_null_to_empty(row["icon"]),
                    radius=float(row["radius"]),
                    affected_garages_ids=_null_to_empty(row["affected_garages_ids"]),
                    affected_areas=_null_to_empty(row["affected_areas"]),
                )
            except (ValueError, KeyError) as exc:
                logger.warning(
                    "Row %d in venue_to_lat_lon_mapping.csv could not be parsed (%s) — skipped",
                    row_num,
                    exc,
                )
                continue

            result[location_label] = mapping

    logger.debug("Loaded %d venue mappings from %s", len(result), mappings_path)
    return result


def load_venue_aliases(config_dir: Path) -> dict[str, str]:
    """Load the alias-to-location-label mapping from venue_aliases.csv.

    The CSV must contain at least two columns: ``alias`` and
    ``location_label``.  Alias keys are lowercased so lookups are
    case-insensitive.

    Args:
        config_dir: Directory that contains ``venue_aliases.csv``.

    Returns:
        Dict mapping lowercase alias strings to ``location_label`` strings.

    Raises:
        FileNotFoundError: If ``venue_aliases.csv`` does not exist.
        ValueError: If required columns are absent from the CSV header.
    """
    aliases_path = config_dir / "venue_aliases.csv"

    if not aliases_path.exists():
        raise FileNotFoundError(f"venue_aliases.csv not found at {aliases_path}")

    required_columns = {"alias", "location_label"}
    result: dict[str, str] = {}

    with aliases_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)

        if reader.fieldnames is None:
            logger.warning("venue_aliases.csv appears to be empty")
            return result

        present = set(reader.fieldnames)
        missing = required_columns - present
        if missing:
            raise ValueError(f"venue_aliases.csv is missing required columns: {sorted(missing)}")

        for row_num, row in enumerate(reader, start=2):
            alias = row.get("alias", "").strip()
            location_label = row.get("location_label", "").strip()

            if not alias:
                logger.warning("Row %d in venue_aliases.csv has an empty alias — skipped", row_num)
                continue
            if not location_label:
                logger.warning(
                    "Row %d in venue_aliases.csv has no location_label for alias %r — skipped",
                    row_num,
                    alias,
                )
                continue

            result[alias.lower()] = location_label

    logger.debug("Loaded %d venue aliases from %s", len(result), aliases_path)
    return result


def load_cookie_selectors(config_dir: Path) -> list[dict]:
    """Load cookie-modal CSS selectors from cookie_selectors.yaml.

    The YAML file is expected to contain a top-level list of selector dicts.
    Each dict's schema is defined by the cookie dismissal module.

    Args:
        config_dir: Directory that contains ``cookie_selectors.yaml``.

    Returns:
        List of selector dicts.  Returns an empty list if the file is absent
        or contains no entries.
    """
    selectors_path = config_dir / "cookie_selectors.yaml"

    if not selectors_path.exists():
        logger.warning(
            "cookie_selectors.yaml not found at %s — no selectors loaded", selectors_path
        )
        return []

    with selectors_path.open("r", encoding="utf-8") as fh:
        raw: Any = yaml.safe_load(fh)

    if raw is None:
        logger.warning("cookie_selectors.yaml is empty — no selectors loaded")
        return []

    if not isinstance(raw, list):
        logger.warning(
            "cookie_selectors.yaml top-level value is not a list (got %s) — no selectors loaded",
            type(raw).__name__,
        )
        return []

    logger.debug("Loaded %d cookie selectors from %s", len(raw), selectors_path)
    return raw
