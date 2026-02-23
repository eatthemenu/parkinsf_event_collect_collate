"""Tests for src/validators.py — validate_event() and deduplicate_events()."""

from datetime import date

import pytest

from src.validators import deduplicate_events, validate_event

# Fixed reference dates used throughout all tests.
TODAY = date(2026, 2, 20)
MAX_FUTURE = date(2026, 8, 20)


# ---------------------------------------------------------------------------
# Fixture: a known-good event dict
# ---------------------------------------------------------------------------


@pytest.fixture()
def valid_event() -> dict:
    """Return a minimal event dict that passes all validate_event() checks."""
    return {
        "label": "Hamilton",
        "location_label": "Curran Theater",
        "latitude": 37.7862,
        "longitude": -122.4123,
        "radius": 0.3,
        "event_start_date": "2026-04-15",
        "event_start_time": "19:30:00",
        "web": "https://sfcurran.com/events",
        "icon": "theater",
        "affected_garages_ids": "1",
        "event_duration": "02:00:00",
        "hours_before_start": "01:00:00",
        "hours_after_end": "00:30:00",
        "details": None,
        "affected_areas": None,
    }


# ---------------------------------------------------------------------------
# Tests: validate_event — happy path
# ---------------------------------------------------------------------------


def test_valid_event_passes(valid_event):
    """A complete, correct event should return (True, [])."""
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is True
    assert errors == []


# ---------------------------------------------------------------------------
# Tests: validate_event — label
# ---------------------------------------------------------------------------


def test_label_empty_fails(valid_event):
    """Empty string label should fail validation."""
    valid_event["label"] = ""
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("label" in e for e in errors)


def test_label_whitespace_only_fails(valid_event):
    """Whitespace-only label should fail because it's empty after stripping."""
    valid_event["label"] = "   "
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("label" in e for e in errors)


def test_label_missing_fails(valid_event):
    """Missing label key should fail validation."""
    del valid_event["label"]
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("label" in e for e in errors)


def test_label_exactly_255_chars_passes(valid_event):
    """A label of exactly 255 characters should pass."""
    valid_event["label"] = "A" * 255
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is True
    assert errors == []


def test_label_256_chars_fails(valid_event):
    """A label of 256 characters should fail the length check."""
    valid_event["label"] = "A" * 256
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("label" in e and "255" in e for e in errors)


# ---------------------------------------------------------------------------
# Tests: validate_event — latitude
# ---------------------------------------------------------------------------


def test_latitude_too_low_fails(valid_event):
    """Latitude 36.9 is outside the SF Bay Area range [37.0, 38.0]."""
    valid_event["latitude"] = 36.9
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("latitude" in e for e in errors)


def test_latitude_too_high_fails(valid_event):
    """Latitude 38.1 is outside the SF Bay Area range [37.0, 38.0]."""
    valid_event["latitude"] = 38.1
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("latitude" in e for e in errors)


def test_latitude_exactly_37_passes(valid_event):
    """Latitude exactly 37.0 is the lower boundary and should pass."""
    valid_event["latitude"] = 37.0
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is True
    assert errors == []


def test_latitude_exactly_38_passes(valid_event):
    """Latitude exactly 38.0 is the upper boundary and should pass."""
    valid_event["latitude"] = 38.0
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is True
    assert errors == []


# ---------------------------------------------------------------------------
# Tests: validate_event — longitude
# ---------------------------------------------------------------------------


def test_longitude_out_of_range_fails(valid_event):
    """Longitude -120.0 is outside the SF Bay Area range [-123.0, -121.5]."""
    valid_event["longitude"] = -120.0
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("longitude" in e for e in errors)


def test_longitude_lower_boundary_passes(valid_event):
    """Longitude exactly -123.0 is the lower boundary and should pass."""
    valid_event["longitude"] = -123.0
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is True
    assert errors == []


def test_longitude_upper_boundary_passes(valid_event):
    """Longitude exactly -121.5 is the upper boundary and should pass."""
    valid_event["longitude"] = -121.5
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is True
    assert errors == []


# ---------------------------------------------------------------------------
# Tests: validate_event — radius
# ---------------------------------------------------------------------------


def test_radius_zero_fails(valid_event):
    """Radius of exactly 0 should fail because radius must be greater than 0."""
    valid_event["radius"] = 0
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("radius" in e for e in errors)


def test_radius_negative_fails(valid_event):
    """A negative radius should fail validation."""
    valid_event["radius"] = -0.5
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("radius" in e for e in errors)


def test_radius_positive_passes(valid_event):
    """A small positive radius should pass."""
    valid_event["radius"] = 0.1
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is True
    assert errors == []


# ---------------------------------------------------------------------------
# Tests: validate_event — event_start_date
# ---------------------------------------------------------------------------


def test_event_start_date_in_past_fails(valid_event):
    """A date in the past (before today) should fail validation."""
    valid_event["event_start_date"] = "2026-01-01"
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("event_start_date" in e for e in errors)


def test_event_start_date_equals_today_passes(valid_event):
    """A date equal to today is on the lower boundary and should pass."""
    valid_event["event_start_date"] = TODAY.isoformat()
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is True
    assert errors == []


def test_event_start_date_beyond_max_future_fails(valid_event):
    """A date past max_future_date should fail validation."""
    valid_event["event_start_date"] = "2026-12-31"
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("event_start_date" in e for e in errors)


def test_event_start_date_equals_max_future_passes(valid_event):
    """A date equal to max_future_date is the upper boundary and should pass."""
    valid_event["event_start_date"] = MAX_FUTURE.isoformat()
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is True
    assert errors == []


def test_event_start_date_invalid_format_fails(valid_event):
    """A date string in an invalid format should fail validation."""
    valid_event["event_start_date"] = "15-04-2026"
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("event_start_date" in e for e in errors)


def test_event_start_date_not_a_date_fails(valid_event):
    """A completely non-date string should fail validation."""
    valid_event["event_start_date"] = "not-a-date"
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("event_start_date" in e for e in errors)


# ---------------------------------------------------------------------------
# Tests: validate_event — event_start_time
# ---------------------------------------------------------------------------


def test_event_start_time_too_early_fails(valid_event):
    """05:59:59 is before the 06:00:00 minimum and should fail."""
    valid_event["event_start_time"] = "05:59:59"
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("event_start_time" in e for e in errors)


def test_event_start_time_lower_boundary_passes(valid_event):
    """06:00:00 is exactly the minimum allowed time and should pass."""
    valid_event["event_start_time"] = "06:00:00"
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is True
    assert errors == []


def test_event_start_time_upper_boundary_passes(valid_event):
    """23:59:59 is exactly the maximum allowed time and should pass."""
    valid_event["event_start_time"] = "23:59:59"
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is True
    assert errors == []


def test_event_start_time_bad_format_fails(valid_event):
    """A time string missing seconds should fail validation."""
    valid_event["event_start_time"] = "19:30"
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("event_start_time" in e for e in errors)


def test_event_start_time_not_a_time_fails(valid_event):
    """A non-time string should fail validation."""
    valid_event["event_start_time"] = "seven-thirty-pm"
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("event_start_time" in e for e in errors)


# ---------------------------------------------------------------------------
# Tests: validate_event — web
# ---------------------------------------------------------------------------


def test_web_not_https_fails(valid_event):
    """A URL starting with http:// (not https://) should fail."""
    valid_event["web"] = "http://sfcurran.com/events"
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("web" in e for e in errors)


def test_web_no_scheme_fails(valid_event):
    """A URL with no scheme should fail validation."""
    valid_event["web"] = "sfcurran.com/events"
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("web" in e for e in errors)


def test_web_exactly_255_chars_passes(valid_event):
    """A web URL of exactly 255 characters starting with https:// should pass."""
    base = "https://sfcurran.com/"
    valid_event["web"] = base + "x" * (255 - len(base))
    assert len(valid_event["web"]) == 255
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is True
    assert errors == []


def test_web_too_long_fails(valid_event):
    """A web URL longer than 255 characters should fail validation."""
    valid_event["web"] = "https://sfcurran.com/" + "x" * 240
    assert len(valid_event["web"]) > 255
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("web" in e and "255" in e for e in errors)


# ---------------------------------------------------------------------------
# Tests: validate_event — affected_garages_ids
# ---------------------------------------------------------------------------


def test_affected_garages_ids_comma_separated_passes(valid_event):
    """A comma-separated string of integers should pass validation."""
    valid_event["affected_garages_ids"] = "1,2,3"
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is True
    assert errors == []


def test_affected_garages_ids_single_id_passes(valid_event):
    """A single integer as a string should pass validation."""
    valid_event["affected_garages_ids"] = "42"
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is True
    assert errors == []


def test_affected_garages_ids_alpha_fails(valid_event):
    """A non-numeric string should fail the pattern check."""
    valid_event["affected_garages_ids"] = "abc"
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("affected_garages_ids" in e for e in errors)


def test_affected_garages_ids_empty_string_passes(valid_event):
    """An empty string for affected_garages_ids is permitted (optional field)."""
    valid_event["affected_garages_ids"] = ""
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is True
    assert errors == []


def test_affected_garages_ids_none_passes(valid_event):
    """None for affected_garages_ids is treated as empty string and should pass."""
    valid_event["affected_garages_ids"] = None
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is True
    assert errors == []


def test_affected_garages_ids_mixed_alpha_numeric_fails(valid_event):
    """A string like '1,2,abc' should fail because 'abc' is not an integer."""
    valid_event["affected_garages_ids"] = "1,2,abc"
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert any("affected_garages_ids" in e for e in errors)


# ---------------------------------------------------------------------------
# Tests: validate_event — multiple errors accumulate
# ---------------------------------------------------------------------------


def test_multiple_failures_return_multiple_errors(valid_event):
    """Multiple invalid fields should produce multiple distinct error messages."""
    valid_event["label"] = ""
    valid_event["latitude"] = 36.0
    valid_event["radius"] = 0
    is_valid, errors = validate_event(valid_event, TODAY, MAX_FUTURE)
    assert is_valid is False
    assert len(errors) >= 3


# ---------------------------------------------------------------------------
# Tests: deduplicate_events
# ---------------------------------------------------------------------------


def _make_event(
    label: str = "Hamilton",
    location_label: str = "Curran Theater",
    event_start_date: str = "2026-04-15",
    event_start_time: str = "19:30:00",
    **extra,
) -> dict:
    """Helper: create a minimal event dict with a specified dedup key."""
    return {
        "label": label,
        "location_label": location_label,
        "event_start_date": event_start_date,
        "event_start_time": event_start_time,
        **extra,
    }


def test_no_duplicates_unchanged():
    """A list with no duplicates should be returned unchanged."""
    events = [
        _make_event(label="Hamilton"),
        _make_event(label="Chicago"),
    ]
    result = deduplicate_events(events)
    assert len(result) == 2
    labels = [e["label"] for e in result]
    assert "Hamilton" in labels
    assert "Chicago" in labels


def test_exact_duplicate_one_removed():
    """Two identical events should result in one being removed."""
    event = _make_event(label="Hamilton")
    result = deduplicate_events([event, event.copy()])
    assert len(result) == 1
    assert result[0]["label"] == "Hamilton"


def test_duplicate_second_has_more_data_second_kept():
    """When a duplicate has more data, the more-complete record should be kept."""
    sparse = _make_event(label="Hamilton")
    richer = _make_event(label="Hamilton", web="https://sfcurran.com/hamilton", icon="theater")
    result = deduplicate_events([sparse, richer])
    assert len(result) == 1
    # The richer record has more non-None fields, so it should win.
    assert result[0].get("web") == "https://sfcurran.com/hamilton"
    assert result[0].get("icon") == "theater"


def test_duplicate_first_has_more_data_first_kept():
    """When the first record is more complete, it should be kept over the later duplicate."""
    richer = _make_event(label="Hamilton", web="https://sfcurran.com/hamilton", icon="theater")
    sparse = _make_event(label="Hamilton")
    result = deduplicate_events([richer, sparse])
    assert len(result) == 1
    assert result[0].get("web") == "https://sfcurran.com/hamilton"


def test_three_events_two_duplicates_two_unique_remain():
    """Three events where two share a key should yield two unique events."""
    e1 = _make_event(label="Hamilton")
    e2 = _make_event(label="Hamilton", web="https://sfcurran.com/hamilton")
    e3 = _make_event(label="Chicago")
    result = deduplicate_events([e1, e2, e3])
    assert len(result) == 2
    labels = [e["label"] for e in result]
    assert "Hamilton" in labels
    assert "Chicago" in labels


def test_dedup_key_includes_all_four_fields():
    """Events differing in any key field are treated as distinct, not duplicates."""
    base = {
        "label": "Hamilton",
        "location_label": "Curran Theater",
        "event_start_date": "2026-04-15",
        "event_start_time": "19:30:00",
    }
    # Same label/location but different date — not a duplicate.
    different_date = {**base, "event_start_date": "2026-04-16"}
    # Same label/location/date but different time — not a duplicate.
    different_time = {**base, "event_start_time": "14:00:00"}
    # Same label/date/time but different location — not a duplicate.
    different_location = {**base, "location_label": "Strand Theater"}

    events = [base, different_date, different_time, different_location]
    result = deduplicate_events(events)
    assert len(result) == 4


def test_dedup_preserves_first_occurrence_order():
    """The output list should preserve the first-occurrence order of each key."""
    e_chicago = _make_event(label="Chicago")
    e_hamilton = _make_event(label="Hamilton")
    e_hamilton_dup = _make_event(label="Hamilton", web="https://sfcurran.com/h")
    e_wicked = _make_event(label="Wicked")

    result = deduplicate_events([e_chicago, e_hamilton, e_hamilton_dup, e_wicked])
    assert len(result) == 3
    assert result[0]["label"] == "Chicago"
    assert result[1]["label"] == "Hamilton"
    assert result[2]["label"] == "Wicked"


def test_dedup_empty_list_returns_empty():
    """An empty input should return an empty list without error."""
    assert deduplicate_events([]) == []


def test_dedup_single_event_unchanged():
    """A single event should be returned as a one-element list."""
    event = _make_event(label="Hamilton")
    result = deduplicate_events([event])
    assert len(result) == 1
    assert result[0] is event
