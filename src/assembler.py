"""Event assembly: merges AI-extracted raw events with venue config and constants.

Takes a RawExtractedEvent dict produced by the AI vision layer and combines it
with the corresponding VenueSource, VenueMapping, canonical name, and source URL
to produce a fully assembled event dict ready for validation and CSV output.
"""

import logging
from typing import Any

from .venue_config import VenueMapping, VenueSource

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pipeline constants applied to every assembled event.
# These match the MySQL schema defaults documented in CLAUDE.md.
# ---------------------------------------------------------------------------
CONSTANTS: dict[str, Any] = {
    "event_duration": "02:00:00",
    "hours_before_start": "01:00:00",
    "hours_after_end": "00:30:00",
    "details": None,
    "affected_areas": None,
}


def assemble_event(
    raw_event: dict,
    venue_source: VenueSource,
    venue_mapping: VenueMapping,
    canonical_venue_name: str,
    source_url: str,
) -> dict:
    """Assemble a fully populated event dict from AI output and venue config.

    Combines fields from the raw AI extraction, the venue source metadata,
    the venue geographic/display mapping, and the pipeline constants into a
    single flat dict whose keys exactly match the output CSV column names
    defined in :data:`~csv_io.OUTPUT_COLUMNS`.

    Location label resolution rules:

    - For ``single_venue`` sites the ``location_label`` is always
      ``canonical_venue_name``, overriding whatever the AI may have returned.
    - For ``multi_venue`` sites the ``location_label`` is taken directly from
      ``raw_event["location_label"]`` (the AI-extracted value), since each
      event may belong to a different sub-venue.

    Args:
        raw_event: Dict produced by the AI vision layer.  Expected keys:
            ``label``, ``location_label``, ``event_start_date``,
            ``event_start_time``, ``confidence``, ``notes``,
            ``requires_detail_page``.  Unknown extra keys are ignored.
        venue_source: The :class:`~venue_config.VenueSource` for the venue
            whose schedule page was scraped.
        venue_mapping: The :class:`~venue_config.VenueMapping` supplying
            geographic and display metadata for the venue.
        canonical_venue_name: The authoritative display name resolved by the
            normalizer (may equal ``venue_mapping.canonical_name``).
        source_url: The URL of the schedule page that was scraped; written to
            the ``web`` field.

    Returns:
        Dict with all keys from ``OUTPUT_COLUMNS`` populated.  Fields sourced
        from :data:`CONSTANTS` (``event_duration``, ``hours_before_start``,
        ``hours_after_end``, ``details``, ``affected_areas``) are always set
        to their constant values.
    """
    # Determine location_label based on site_type.
    if venue_source.site_type == "single_venue":
        location_label = canonical_venue_name
        if raw_event.get("location_label") and raw_event["location_label"] != canonical_venue_name:
            logger.debug(
                "single_venue %s: ignoring AI location_label %r; using canonical %r",
                venue_source.venue_id,
                raw_event.get("location_label"),
                canonical_venue_name,
                extra={"venue_id": venue_source.venue_id},
            )
    else:
        # multi_venue: use the AI-extracted location label.
        location_label = raw_event.get("location_label") or ""
        if not location_label:
            logger.warning(
                "multi_venue %s: AI returned empty location_label for event %r",
                venue_source.venue_id,
                raw_event.get("label"),
                extra={"venue_id": venue_source.venue_id},
            )

    # Strip whitespace from the event label.
    label_raw = raw_event.get("label") or ""
    label = str(label_raw).strip()

    assembled: dict[str, Any] = {
        # AI-derived fields
        "label": label,
        "location_label": location_label,
        "event_start_date": raw_event.get("event_start_date"),
        "event_start_time": raw_event.get("event_start_time"),
        # Venue mapping fields
        "latitude": venue_mapping.latitude,
        "longitude": venue_mapping.longitude,
        "radius": venue_mapping.radius,
        "icon": venue_mapping.icon,
        "affected_garages_ids": venue_mapping.affected_garages_ids,
        # Source URL
        "web": source_url,
        # Pipeline constants
        "event_duration": CONSTANTS["event_duration"],
        "hours_before_start": CONSTANTS["hours_before_start"],
        "hours_after_end": CONSTANTS["hours_after_end"],
        "details": CONSTANTS["details"],
        "affected_areas": CONSTANTS["affected_areas"],
    }

    logger.debug(
        "Assembled event: venue=%s label=%r date=%s time=%s",
        venue_source.venue_id,
        label,
        assembled.get("event_start_date"),
        assembled.get("event_start_time"),
        extra={"venue_id": venue_source.venue_id},
    )

    return assembled
