"""Tests for src/csv_io.py — read_event_source_csv() and write_event_table_csv()."""

import csv
from pathlib import Path

import pytest

from src.csv_io import OUTPUT_COLUMNS, read_event_source_csv, write_event_table_csv
from src.venue_config import VenueSource

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_csv(
    path: Path,
    rows: list[dict],
    fieldnames: list[str] | None = None,
) -> None:
    """Write a CSV file from a list of row dicts.

    Args:
        path: Destination file path.
        rows: List of row dicts. Ignored if empty and fieldnames is None.
        fieldnames: Column names; inferred from the first row when omitted.
    """
    if not rows and fieldnames is None:
        path.write_text("", encoding="utf-8")
        return
    headers = fieldnames or list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Tests: read_event_source_csv — happy path
# ---------------------------------------------------------------------------


def test_read_valid_csv(tmp_path: Path) -> None:
    """A well-formed Event Source CSV should return the expected VenueSource list."""
    csv_path = tmp_path / "sources.csv"
    _write_csv(
        csv_path,
        [
            {
                "venue_id": "curran",
                "venue_name": "Curran Theater",
                "schedule_url": "https://sfcurran.com/events",
                "site_type": "single_venue",
            }
        ],
    )
    sources = read_event_source_csv(csv_path)
    assert len(sources) == 1
    source = sources[0]
    assert source.venue_id == "curran"
    assert source.venue_name == "Curran Theater"
    assert source.schedule_url == "https://sfcurran.com/events"
    assert source.site_type == "single_venue"


def test_read_multiple_rows(tmp_path: Path) -> None:
    """A CSV with multiple rows returns the correct number of VenueSource objects."""
    csv_path = tmp_path / "sources.csv"
    _write_csv(
        csv_path,
        [
            {
                "venue_id": "curran",
                "venue_name": "Curran Theater",
                "schedule_url": "https://sfcurran.com/events",
                "site_type": "single_venue",
            },
            {
                "venue_id": "act_rembe",
                "venue_name": "ACT Toni Rembe Theater",
                "schedule_url": "https://www.act-sf.org/whats-on/",
                "site_type": "multi_venue",
            },
        ],
    )
    sources = read_event_source_csv(csv_path)
    assert len(sources) == 2
    assert sources[0].venue_id == "curran"
    assert sources[1].venue_id == "act_rembe"
    assert sources[1].site_type == "multi_venue"


def test_read_returns_venue_source_instances(tmp_path: Path) -> None:
    """Each item in the returned list should be a VenueSource dataclass instance."""
    csv_path = tmp_path / "sources.csv"
    _write_csv(
        csv_path,
        [
            {
                "venue_id": "sf_symphony",
                "venue_name": "SF Symphony",
                "schedule_url": "https://www.sfsymphony.org/calendar",
                "site_type": "single_venue",
            }
        ],
    )
    sources = read_event_source_csv(csv_path)
    assert len(sources) == 1
    assert isinstance(sources[0], VenueSource)


def test_read_extra_columns_are_ignored(tmp_path: Path) -> None:
    """Extra columns beyond the required four should not cause an error."""
    csv_path = tmp_path / "sources.csv"
    _write_csv(
        csv_path,
        [
            {
                "venue_id": "curran",
                "venue_name": "Curran Theater",
                "schedule_url": "https://sfcurran.com/events",
                "site_type": "single_venue",
                "extra_column": "ignored_value",
            }
        ],
    )
    sources = read_event_source_csv(csv_path)
    assert len(sources) == 1
    assert sources[0].venue_id == "curran"


def test_read_fixture_csv() -> None:
    """The sample_event_source.csv fixture should parse without errors."""
    fixture = Path("tests/fixtures/sample_event_source.csv")
    if not fixture.exists():
        pytest.skip("fixture not found")
    sources = read_event_source_csv(fixture)
    assert len(sources) >= 1
    for s in sources:
        assert isinstance(s, VenueSource)
        assert s.venue_id
        assert s.schedule_url.startswith("https://")


# ---------------------------------------------------------------------------
# Tests: read_event_source_csv — error cases
# ---------------------------------------------------------------------------


def test_read_file_not_found_raises() -> None:
    """A non-existent path should raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="not found"):
        read_event_source_csv(Path("/nonexistent/path/sources.csv"))


def test_read_missing_required_columns_raises(tmp_path: Path) -> None:
    """A CSV missing required columns should raise ValueError."""
    csv_path = tmp_path / "bad.csv"
    _write_csv(csv_path, [{"venue_id": "curran", "venue_name": "Curran"}])
    with pytest.raises(ValueError, match="missing required columns"):
        read_event_source_csv(csv_path)


def test_read_skips_row_with_empty_venue_id(tmp_path: Path) -> None:
    """A row whose venue_id is empty should be skipped; valid rows are kept."""
    csv_path = tmp_path / "sources.csv"
    _write_csv(
        csv_path,
        [
            {
                "venue_id": "",
                "venue_name": "Unknown",
                "schedule_url": "https://example.com",
                "site_type": "single_venue",
            },
            {
                "venue_id": "curran",
                "venue_name": "Curran Theater",
                "schedule_url": "https://sfcurran.com/events",
                "site_type": "single_venue",
            },
        ],
    )
    sources = read_event_source_csv(csv_path)
    assert len(sources) == 1
    assert sources[0].venue_id == "curran"


def test_read_skips_row_with_empty_schedule_url(tmp_path: Path) -> None:
    """A row whose schedule_url is empty should be skipped."""
    csv_path = tmp_path / "sources.csv"
    _write_csv(
        csv_path,
        [
            {
                "venue_id": "curran",
                "venue_name": "Curran Theater",
                "schedule_url": "",
                "site_type": "single_venue",
            },
            {
                "venue_id": "act_rembe",
                "venue_name": "ACT",
                "schedule_url": "https://www.act-sf.org/whats-on/",
                "site_type": "multi_venue",
            },
        ],
    )
    sources = read_event_source_csv(csv_path)
    assert len(sources) == 1
    assert sources[0].venue_id == "act_rembe"


def test_read_empty_csv_returns_empty_list(tmp_path: Path) -> None:
    """An empty CSV file (no headers, no rows) should return an empty list."""
    csv_path = tmp_path / "empty.csv"
    csv_path.write_text("", encoding="utf-8")
    sources = read_event_source_csv(csv_path)
    assert sources == []


def test_read_header_only_csv_returns_empty_list(tmp_path: Path) -> None:
    """A CSV with only a header row and no data rows returns an empty list."""
    csv_path = tmp_path / "header_only.csv"
    _write_csv(csv_path, [], fieldnames=["venue_id", "venue_name", "schedule_url", "site_type"])
    sources = read_event_source_csv(csv_path)
    assert sources == []


# ---------------------------------------------------------------------------
# Tests: write_event_table_csv — happy path
# ---------------------------------------------------------------------------


def test_write_output_columns_in_order(tmp_path: Path) -> None:
    """The output CSV header row must exactly match OUTPUT_COLUMNS in order."""
    out_path = tmp_path / "output.csv"
    write_event_table_csv([], out_path)
    with out_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        headers = next(reader)
    assert headers == OUTPUT_COLUMNS


def test_write_single_event_row(tmp_path: Path) -> None:
    """A single event dict should produce exactly one data row."""
    out_path = tmp_path / "output.csv"
    event = {
        "label": "Hamilton",
        "location_label": "Curran Theater",
        "latitude": 37.7862,
        "longitude": -122.4123,
        "radius": 0.3,
        "event_start_date": "2026-04-15",
        "event_start_time": "19:30:00",
        "event_duration": "02:00:00",
        "hours_before_start": "01:00:00",
        "hours_after_end": "00:30:00",
        "details": None,
        "web": "https://sfcurran.com/events",
        "icon": "theater",
        "affected_garages_ids": "1",
        "affected_areas": None,
    }
    count = write_event_table_csv([event], out_path)
    assert count == 1

    with out_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["label"] == "Hamilton"
    assert rows[0]["location_label"] == "Curran Theater"
    assert rows[0]["event_start_date"] == "2026-04-15"


def test_write_none_values_as_empty_strings(tmp_path: Path) -> None:
    """None field values must be written as '' not the literal string 'None'."""
    out_path = tmp_path / "output.csv"
    event = dict.fromkeys(OUTPUT_COLUMNS)
    event["label"] = "Test Show"
    write_event_table_csv([event], out_path)

    with out_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        row = next(reader)

    assert row["details"] == ""
    assert row["affected_areas"] == ""
    assert "None" not in row.values()


def test_write_extra_keys_silently_ignored(tmp_path: Path) -> None:
    """Keys in the event dict that are not in OUTPUT_COLUMNS are silently dropped."""
    out_path = tmp_path / "output.csv"
    event = dict.fromkeys(OUTPUT_COLUMNS, "x")
    event["surprise_key_not_in_schema"] = "should_not_appear"
    write_event_table_csv([event], out_path)

    with out_path.open(newline="", encoding="utf-8") as fh:
        content = fh.read()

    assert "surprise_key_not_in_schema" not in content


def test_write_creates_parent_directories(tmp_path: Path) -> None:
    """write_event_table_csv should create parent directories that do not exist."""
    out_path = tmp_path / "nested" / "deep" / "output.csv"
    assert not out_path.parent.exists()
    write_event_table_csv([], out_path)
    assert out_path.exists()


def test_write_returns_correct_row_count(tmp_path: Path) -> None:
    """write_event_table_csv should return the number of data rows written."""
    out_path = tmp_path / "output.csv"
    events = [{"label": f"Show {i}"} for i in range(5)]
    count = write_event_table_csv(events, out_path)
    assert count == 5


def test_write_empty_list_produces_header_only(tmp_path: Path) -> None:
    """Writing an empty event list should produce a header-only CSV (0 data rows)."""
    out_path = tmp_path / "output.csv"
    count = write_event_table_csv([], out_path)
    assert count == 0

    with out_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))

    assert len(rows) == 1  # header row only


def test_write_multiple_events_correct_count(tmp_path: Path) -> None:
    """Writing multiple events returns the correct count and all rows are present."""
    out_path = tmp_path / "output.csv"
    events = [
        {
            "label": "Show A",
            "event_start_date": "2026-04-10",
            "event_start_time": "19:00:00",
        },
        {
            "label": "Show B",
            "event_start_date": "2026-04-11",
            "event_start_time": "20:00:00",
        },
    ]
    count = write_event_table_csv(events, out_path)
    assert count == 2

    with out_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        labels = [row["label"] for row in reader]

    assert labels == ["Show A", "Show B"]
