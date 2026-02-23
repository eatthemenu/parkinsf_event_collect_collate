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
    """

    venue_id: str
    venue_name: str
    schedule_url: str
    site_type: str


@dataclass
class VenueMapping:
    """Geographic and display metadata for a venue, loaded from venue_mappings.csv.

    Attributes:
        venue_id: Stable, unique identifier matching VenueSource.venue_id.
        canonical_name: The authoritative display name for this venue.
        latitude: WGS-84 latitude of the venue.
        longitude: WGS-84 longitude of the venue.
        radius: Radius (in miles) around the venue used by the parking app.
        icon: Icon identifier string for the parking app UI.
        affected_garages_ids: Comma-separated garage IDs as a raw string
            (e.g. ``"12,34,56"``).
    """

    venue_id: str
    canonical_name: str
    latitude: float
    longitude: float
    radius: float
    icon: str
    affected_garages_ids: str


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
        logger.warning(
            "settings.yaml not found at %s — using all defaults", settings_path
        )
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


def load_venue_mappings(config_dir: Path) -> dict[str, VenueMapping]:
    """Load venue geographic and display metadata from venue_mappings.csv.

    The CSV must contain the following headers (in any order):
    ``venue_id``, ``canonical_name``, ``latitude``, ``longitude``,
    ``radius``, ``icon``, ``affected_garages_ids``.

    Args:
        config_dir: Directory that contains ``venue_mappings.csv``.

    Returns:
        Dict mapping ``venue_id`` strings to :class:`VenueMapping` instances.

    Raises:
        FileNotFoundError: If ``venue_mappings.csv`` does not exist.
        ValueError: If required columns are absent from the CSV header.
    """
    mappings_path = config_dir / "venue_mappings.csv"

    if not mappings_path.exists():
        raise FileNotFoundError(f"venue_mappings.csv not found at {mappings_path}")

    required_columns = {
        "venue_id",
        "canonical_name",
        "latitude",
        "longitude",
        "radius",
        "icon",
        "affected_garages_ids",
    }

    result: dict[str, VenueMapping] = {}

    with mappings_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)

        if reader.fieldnames is None:
            logger.warning("venue_mappings.csv appears to be empty")
            return result

        present = set(reader.fieldnames)
        missing = required_columns - present
        if missing:
            raise ValueError(
                f"venue_mappings.csv is missing required columns: {sorted(missing)}"
            )

        for row_num, row in enumerate(reader, start=2):
            venue_id = row.get("venue_id", "").strip()
            if not venue_id:
                logger.warning("Row %d in venue_mappings.csv has no venue_id — skipped", row_num)
                continue

            try:
                mapping = VenueMapping(
                    venue_id=venue_id,
                    canonical_name=row["canonical_name"].strip(),
                    latitude=float(row["latitude"]),
                    longitude=float(row["longitude"]),
                    radius=float(row["radius"]),
                    icon=row["icon"].strip(),
                    affected_garages_ids=row["affected_garages_ids"].strip(),
                )
            except (ValueError, KeyError) as exc:
                logger.warning(
                    "Row %d in venue_mappings.csv could not be parsed (%s) — skipped",
                    row_num,
                    exc,
                )
                continue

            result[venue_id] = mapping

    logger.debug("Loaded %d venue mappings from %s", len(result), mappings_path)
    return result


def load_venue_aliases(config_dir: Path) -> dict[str, str]:
    """Load the alias-to-canonical-venue mapping from venue_aliases.csv.

    The CSV must contain at least two columns: ``alias`` and
    ``canonical_venue_id``.  Alias keys are lowercased so lookups are
    case-insensitive.

    Args:
        config_dir: Directory that contains ``venue_aliases.csv``.

    Returns:
        Dict mapping lowercase alias strings to canonical venue ID strings.

    Raises:
        FileNotFoundError: If ``venue_aliases.csv`` does not exist.
        ValueError: If required columns are absent from the CSV header.
    """
    aliases_path = config_dir / "venue_aliases.csv"

    if not aliases_path.exists():
        raise FileNotFoundError(f"venue_aliases.csv not found at {aliases_path}")

    required_columns = {"alias", "canonical_venue_id"}
    result: dict[str, str] = {}

    with aliases_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)

        if reader.fieldnames is None:
            logger.warning("venue_aliases.csv appears to be empty")
            return result

        present = set(reader.fieldnames)
        missing = required_columns - present
        if missing:
            raise ValueError(
                f"venue_aliases.csv is missing required columns: {sorted(missing)}"
            )

        for row_num, row in enumerate(reader, start=2):
            alias = row.get("alias", "").strip()
            canonical_id = row.get("canonical_venue_id", "").strip()

            if not alias:
                logger.warning(
                    "Row %d in venue_aliases.csv has an empty alias — skipped", row_num
                )
                continue
            if not canonical_id:
                logger.warning(
                    "Row %d in venue_aliases.csv has no canonical_venue_id for alias %r"
                    " — skipped",
                    row_num,
                    alias,
                )
                continue

            result[alias.lower()] = canonical_id

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
            "cookie_selectors.yaml top-level value is not a list (got %s)"
            " — no selectors loaded",
            type(raw).__name__,
        )
        return []

    logger.debug("Loaded %d cookie selectors from %s", len(raw), selectors_path)
    return raw
