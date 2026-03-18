"""Tests for src/assembler.py — assemble_event() and CONSTANTS."""

import pytest

from src.assembler import CONSTANTS, assemble_event
from src.venue_config import VenueMapping, VenueSource

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def single_venue_source() -> VenueSource:
    """Return a single_venue VenueSource for Curran Theater."""
    return VenueSource(
        venue_id="curran",
        venue_name="Curran Theater",
        schedule_url="https://sfcurran.com/events",
        site_type="single_venue",
    )


@pytest.fixture()
def multi_venue_source() -> VenueSource:
    """Return a multi_venue VenueSource for ACT."""
    return VenueSource(
        venue_id="act",
        venue_name="ACT",
        schedule_url="https://www.act-sf.org/whats-on/",
        site_type="multi_venue",
    )


@pytest.fixture()
def curran_mapping() -> VenueMapping:
    """Return a VenueMapping for Curran Theater."""
    return VenueMapping(
        location_label="Curran Theater",
        latitude=37.7862,
        longitude=-122.4123,
        icon="theater",
        radius=0.3,
        affected_garages_ids="1",
        affected_areas="",
    )


@pytest.fixture()
def raw_event() -> dict:
    """Return a minimal RawExtractedEvent dict that passes all fields."""
    return {
        "label": "Hamilton",
        "location_label": None,
        "event_start_date": "2026-04-15",
        "event_start_time": "19:30:00",
        "confidence": "high",
        "notes": None,
        "requires_detail_page": False,
    }


def _assemble(
    raw_event: dict,
    venue_source: VenueSource,
    venue_mapping: VenueMapping,
    canonical_venue_name: str = "Curran Theater",
    source_url: str = "https://sfcurran.com/events",
) -> dict:
    """Thin wrapper around assemble_event for shorter test code."""
    return assemble_event(
        raw_event=raw_event,
        venue_source=venue_source,
        venue_mapping=venue_mapping,
        canonical_venue_name=canonical_venue_name,
        source_url=source_url,
    )


# ---------------------------------------------------------------------------
# Tests: single_venue — location_label resolution
# ---------------------------------------------------------------------------


def test_single_venue_uses_canonical_name(
    raw_event: dict, single_venue_source: VenueSource, curran_mapping: VenueMapping
) -> None:
    """For single_venue, location_label must equal the canonical venue name."""
    result = _assemble(raw_event, single_venue_source, curran_mapping)
    assert result["location_label"] == "Curran Theater"


def test_single_venue_overrides_ai_location_label(
    single_venue_source: VenueSource, curran_mapping: VenueMapping
) -> None:
    """For single_venue, an AI-extracted location_label is ignored."""
    raw = {
        "label": "Hamilton",
        "location_label": "Wrong Sub-Venue Extracted By AI",
        "event_start_date": "2026-04-15",
        "event_start_time": "19:30:00",
    }
    result = _assemble(raw, single_venue_source, curran_mapping)
    assert result["location_label"] == "Curran Theater"


def test_single_venue_null_ai_location_label_still_uses_canonical(
    single_venue_source: VenueSource, curran_mapping: VenueMapping
) -> None:
    """For single_venue, a None AI location_label is replaced by canonical name."""
    raw = {"label": "Hamilton", "location_label": None}
    result = _assemble(raw, single_venue_source, curran_mapping)
    assert result["location_label"] == "Curran Theater"


# ---------------------------------------------------------------------------
# Tests: multi_venue — location_label resolution
# ---------------------------------------------------------------------------


def test_multi_venue_uses_ai_location_label(
    multi_venue_source: VenueSource, curran_mapping: VenueMapping
) -> None:
    """For multi_venue, location_label comes from the AI extraction."""
    raw = {
        "label": "Eureka Day",
        "location_label": "Toni Rembe Theater",
        "event_start_date": "2026-05-01",
        "event_start_time": "20:00:00",
    }
    result = _assemble(raw, multi_venue_source, curran_mapping, canonical_venue_name="ACT")
    assert result["location_label"] == "Toni Rembe Theater"


def test_multi_venue_none_location_label_becomes_empty_string(
    multi_venue_source: VenueSource, curran_mapping: VenueMapping
) -> None:
    """For multi_venue, a None AI location_label becomes an empty string."""
    raw = {
        "label": "Mystery Show",
        "location_label": None,
        "event_start_date": "2026-05-01",
        "event_start_time": "20:00:00",
    }
    result = _assemble(raw, multi_venue_source, curran_mapping, canonical_venue_name="ACT")
    assert result["location_label"] == ""


# ---------------------------------------------------------------------------
# Tests: label handling
# ---------------------------------------------------------------------------


def test_label_whitespace_is_stripped(
    single_venue_source: VenueSource, curran_mapping: VenueMapping
) -> None:
    """Leading and trailing whitespace in label should be stripped."""
    raw = {"label": "  Hamilton  ", "location_label": None}
    result = _assemble(raw, single_venue_source, curran_mapping)
    assert result["label"] == "Hamilton"


def test_label_none_becomes_empty_string(
    single_venue_source: VenueSource, curran_mapping: VenueMapping
) -> None:
    """A None label from AI extraction should become an empty string."""
    raw = {"label": None, "location_label": None}
    result = _assemble(raw, single_venue_source, curran_mapping)
    assert result["label"] == ""


def test_label_empty_string_stays_empty(
    single_venue_source: VenueSource, curran_mapping: VenueMapping
) -> None:
    """An empty-string label should remain an empty string."""
    raw = {"label": "", "location_label": None}
    result = _assemble(raw, single_venue_source, curran_mapping)
    assert result["label"] == ""


# ---------------------------------------------------------------------------
# Tests: venue mapping fields
# ---------------------------------------------------------------------------


def test_latitude_longitude_radius_from_mapping(
    raw_event: dict, single_venue_source: VenueSource, curran_mapping: VenueMapping
) -> None:
    """latitude, longitude, and radius must come from the venue_mapping."""
    result = _assemble(raw_event, single_venue_source, curran_mapping)
    assert result["latitude"] == curran_mapping.latitude
    assert result["longitude"] == curran_mapping.longitude
    assert result["radius"] == curran_mapping.radius


def test_icon_from_mapping(
    raw_event: dict, single_venue_source: VenueSource, curran_mapping: VenueMapping
) -> None:
    """icon falls back to venue_mapping when venue_source.icon is empty."""
    result = _assemble(raw_event, single_venue_source, curran_mapping)
    assert result["icon"] == "theater"


def test_icon_override_from_venue_source(raw_event: dict, curran_mapping: VenueMapping) -> None:
    """A non-empty venue_source.icon overrides the venue_mapping icon."""
    source_with_icon = VenueSource(
        venue_id="war_memorial_opera",
        venue_name="War Memorial Opera House",
        schedule_url="https://sfopera.com/season-tickets-and-more/",
        site_type="single_venue",
        icon="/img/event_icon/sf_opera.png",
    )
    result = assemble_event(
        raw_event=raw_event,
        venue_source=source_with_icon,
        venue_mapping=curran_mapping,
        canonical_venue_name="War Memorial Opera House",
        source_url="https://sfopera.com/season-tickets-and-more/",
    )
    assert result["icon"] == "/img/event_icon/sf_opera.png"


def test_affected_garages_ids_from_mapping(
    raw_event: dict, single_venue_source: VenueSource, curran_mapping: VenueMapping
) -> None:
    """affected_garages_ids must come from the venue_mapping."""
    result = _assemble(raw_event, single_venue_source, curran_mapping)
    assert result["affected_garages_ids"] == "1"


def test_web_is_source_url(
    raw_event: dict, single_venue_source: VenueSource, curran_mapping: VenueMapping
) -> None:
    """The 'web' field must equal the source_url argument."""
    result = _assemble(
        raw_event, single_venue_source, curran_mapping, source_url="https://sfcurran.com/events"
    )
    assert result["web"] == "https://sfcurran.com/events"


# ---------------------------------------------------------------------------
# Tests: pipeline constants
# ---------------------------------------------------------------------------


def test_pipeline_constants_applied(
    raw_event: dict, single_venue_source: VenueSource, curran_mapping: VenueMapping
) -> None:
    """event_duration, hours_before_start, hours_after_end, details, affected_areas
    must equal the values in CONSTANTS regardless of what raw_event contains."""
    result = _assemble(raw_event, single_venue_source, curran_mapping)
    assert result["event_duration"] == CONSTANTS["event_duration"]
    assert result["hours_before_start"] == CONSTANTS["hours_before_start"]
    assert result["hours_after_end"] == CONSTANTS["hours_after_end"]
    assert result["details"] == CONSTANTS["details"]
    assert result["affected_areas"] == CONSTANTS["affected_areas"]


def test_constants_values() -> None:
    """CONSTANTS must contain the exact values specified in CLAUDE.md."""
    assert CONSTANTS["event_duration"] == "02:00:00"
    assert CONSTANTS["hours_before_start"] == "01:00:00"
    assert CONSTANTS["hours_after_end"] == "00:30:00"
    assert CONSTANTS["details"] is None
    assert CONSTANTS["affected_areas"] is None


def test_raw_event_constants_are_overridden(
    single_venue_source: VenueSource, curran_mapping: VenueMapping
) -> None:
    """Even if raw_event contains event_duration, the pipeline constant wins."""
    raw = {
        "label": "Hamilton",
        "location_label": None,
        "event_duration": "04:00:00",  # should be overridden
    }
    result = _assemble(raw, single_venue_source, curran_mapping)
    assert result["event_duration"] == "02:00:00"


# ---------------------------------------------------------------------------
# Tests: date / time pass-through
# ---------------------------------------------------------------------------


def test_event_start_date_passed_through(
    raw_event: dict, single_venue_source: VenueSource, curran_mapping: VenueMapping
) -> None:
    """event_start_date from raw_event should appear unchanged in the assembled dict."""
    result = _assemble(raw_event, single_venue_source, curran_mapping)
    assert result["event_start_date"] == "2026-04-15"


def test_event_start_time_passed_through(
    raw_event: dict, single_venue_source: VenueSource, curran_mapping: VenueMapping
) -> None:
    """event_start_time from raw_event should appear unchanged in the assembled dict."""
    result = _assemble(raw_event, single_venue_source, curran_mapping)
    assert result["event_start_time"] == "19:30:00"


def test_none_date_time_passed_through(
    single_venue_source: VenueSource, curran_mapping: VenueMapping
) -> None:
    """None date and time values from raw_event should be preserved as None."""
    raw = {
        "label": "Unknown",
        "location_label": None,
        "event_start_date": None,
        "event_start_time": None,
    }
    result = _assemble(raw, single_venue_source, curran_mapping)
    assert result["event_start_date"] is None
    assert result["event_start_time"] is None
