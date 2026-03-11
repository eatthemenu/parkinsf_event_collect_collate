"""Tests for src/normalizer.py — VenueNormalizer."""

import pytest

from src.normalizer import VenueNormalizer
from src.venue_config import VenueMapping

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_mapping(location_label: str) -> VenueMapping:
    """Build a minimal VenueMapping for testing.

    Args:
        location_label: Authoritative display name for the venue.

    Returns:
        A :class:`~venue_config.VenueMapping` with placeholder coordinates.
    """
    return VenueMapping(
        location_label=location_label,
        latitude=37.7862,
        longitude=-122.4123,
        icon="/img/event_icon/theater.png",
        radius=0.3,
        affected_garages_ids="1",
        affected_areas="",
    )


@pytest.fixture()
def aliases() -> dict[str, str]:
    """Return a representative lowercase alias -> location_label mapping."""
    return {
        "curran theater": "Curran Theater",
        "the curran": "Curran Theater",
        "san francisco symphony": "Davies Symphony Hall",
        "sf symphony": "Davies Symphony Hall",
        "davies symphony hall": "Davies Symphony Hall",
        "act toni rembe theater": "ACT Toni Rembe Theater",
        "toni rembe theater": "ACT Toni Rembe Theater",
    }


@pytest.fixture()
def mappings() -> dict[str, VenueMapping]:
    """Return a representative location_label -> VenueMapping dict."""
    return {
        "Curran Theater": _make_mapping("Curran Theater"),
        "Davies Symphony Hall": _make_mapping("Davies Symphony Hall"),
        "ACT Toni Rembe Theater": _make_mapping("ACT Toni Rembe Theater"),
    }


@pytest.fixture()
def normalizer(aliases: dict, mappings: dict) -> VenueNormalizer:
    """Return a VenueNormalizer with no AI text func and no review queue."""
    return VenueNormalizer(aliases=aliases, mappings=mappings)


# ---------------------------------------------------------------------------
# Tests: Tier 1 — exact alias lookup
# ---------------------------------------------------------------------------


def test_tier1_exact_match(normalizer: VenueNormalizer) -> None:
    """An exact alias string (correct case) should resolve via Tier 1."""
    location_label, method = normalizer.normalize("Curran Theater")
    assert location_label == "Curran Theater"
    assert method == "alias"


def test_tier1_case_insensitive(normalizer: VenueNormalizer) -> None:
    """Alias lookup should be case-insensitive."""
    location_label, method = normalizer.normalize("CURRAN THEATER")
    assert location_label == "Curran Theater"
    assert method == "alias"


def test_tier1_strips_leading_trailing_whitespace(normalizer: VenueNormalizer) -> None:
    """Leading and trailing whitespace should be stripped before alias lookup."""
    location_label, method = normalizer.normalize("  Curran Theater  ")
    assert location_label == "Curran Theater"
    assert method == "alias"


def test_tier1_alternative_alias_same_venue(normalizer: VenueNormalizer) -> None:
    """Multiple aliases mapping to the same location_label should all resolve."""
    v1, _ = normalizer.normalize("Davies Symphony Hall")
    v2, _ = normalizer.normalize("SF Symphony")
    assert v1 == "Davies Symphony Hall"
    assert v2 == "Davies Symphony Hall"


def test_tier1_multi_venue_alias(normalizer: VenueNormalizer) -> None:
    """An alias for the ACT Rembe venue should resolve correctly."""
    location_label, method = normalizer.normalize("Toni Rembe Theater")
    assert location_label == "ACT Toni Rembe Theater"
    assert method == "alias"


# ---------------------------------------------------------------------------
# Tests: Tier 2 — fuzzy matching
# ---------------------------------------------------------------------------


def test_tier2_close_typo_resolves(normalizer: VenueNormalizer) -> None:
    """A name with a small typo should resolve via Tier 2 fuzzy matching."""
    # "Curran Theatr" is close to "curran theater" alias.
    location_label, method = normalizer.normalize("Curran Theatr")
    assert location_label == "Curran Theater"
    assert method == "fuzzy"


def test_tier2_below_threshold_returns_none() -> None:
    """A completely unrelated name below the fuzzy threshold returns (None, 'unknown')."""
    n = VenueNormalizer(
        aliases={"curran theater": "Curran Theater"},
        mappings={"Curran Theater": _make_mapping("Curran Theater")},
        fuzzy_threshold=85,
    )
    location_label, method = n.normalize("Oracle Park Baseball Stadium")
    assert location_label is None
    assert method == "unknown"


def test_tier2_high_threshold_forces_unknown(aliases: dict, mappings: dict) -> None:
    """Setting fuzzy_threshold=100 (impossible) means fuzzy never matches."""
    n = VenueNormalizer(aliases=aliases, mappings=mappings, fuzzy_threshold=100)
    venue_id, method = n.normalize("Curran Theatr")
    # May be unknown (fuzzy cannot hit 100) unless it happens to match alias exactly.
    if method == "fuzzy":
        # Acceptable only if the score was somehow 100 (unlikely for a typo).
        assert venue_id == "curran"
    else:
        assert venue_id is None


def test_tier2_fuzzy_populates_human_review_when_score_below_95(
    aliases: dict, mappings: dict
) -> None:
    """A fuzzy match with score < 95 should add an item to the human review queue."""
    from unittest.mock import patch

    queue: list[dict] = []
    n = VenueNormalizer(
        aliases=aliases,
        mappings=mappings,
        fuzzy_threshold=85,
        human_review_queue=queue,
    )
    # Patch extractOne to return a known score of 88 (>=85 so it matches, <95 so
    # a review item is added).
    with patch("src.normalizer.fuzz_process.extractOne") as mock_extract:
        mock_extract.return_value = ("curran theater", 88)
        location_label, method = n.normalize("Curran Theatr")

    assert method == "fuzzy"
    assert location_label == "Curran Theater"
    assert len(queue) >= 1
    assert any(item["issue_type"] == "name_mismatch_fuzzy_resolved" for item in queue)


# ---------------------------------------------------------------------------
# Tests: Tier 3 — AI text function
# ---------------------------------------------------------------------------


def test_tier3_ai_func_called_when_no_alias_or_fuzzy(mappings: dict) -> None:
    """With no alias or fuzzy match, the AI function should be invoked."""
    called_with: list[str] = []

    def fake_ai(extracted_name: str, canonical_names: list[str]) -> str | None:
        called_with.append(extracted_name)
        return "Davies Symphony Hall"

    n = VenueNormalizer(aliases={}, mappings=mappings, ai_text_func=fake_ai)
    location_label, method = n.normalize("Symphony Hall SF")
    assert location_label == "Davies Symphony Hall"
    assert method == "ai"
    assert "Symphony Hall SF" in called_with


def test_tier3_ai_returning_none_gives_unknown(mappings: dict) -> None:
    """If the AI function returns None, the result should be (None, 'unknown')."""
    n = VenueNormalizer(
        aliases={},
        mappings=mappings,
        ai_text_func=lambda name, names: None,
    )
    venue_id, method = n.normalize("Some Obscure Venue")
    assert venue_id is None
    assert method == "unknown"


def test_tier3_ai_returning_unknown_venue_id_gives_unknown(mappings: dict) -> None:
    """If AI returns a venue_id not in mappings, it should be treated as unknown."""
    n = VenueNormalizer(
        aliases={},
        mappings=mappings,
        ai_text_func=lambda name, names: "totally_fictional_venue",
    )
    venue_id, method = n.normalize("Some Venue")
    assert venue_id is None
    assert method == "unknown"


def test_tier3_ai_exception_is_caught_and_returns_unknown(mappings: dict) -> None:
    """If the AI function raises, the exception is caught and unknown is returned."""

    def bad_ai(name: str, canonical_names: list[str]) -> str | None:
        raise RuntimeError("Simulated API error")

    n = VenueNormalizer(aliases={}, mappings=mappings, ai_text_func=bad_ai)
    venue_id, method = n.normalize("Some Venue")
    assert venue_id is None
    assert method == "unknown"


def test_tier3_ai_result_logged_to_human_review(mappings: dict) -> None:
    """A successful AI resolution should add an item to the human review queue."""
    queue: list[dict] = []
    n = VenueNormalizer(
        aliases={},
        mappings=mappings,
        ai_text_func=lambda name, names: "Curran Theater",
        human_review_queue=queue,
    )
    location_label, method = n.normalize("The Curran SF")
    assert location_label == "Curran Theater"
    assert method == "ai"
    assert len(queue) >= 1
    assert any(item["issue_type"] == "name_mismatch_ai_resolved" for item in queue)


# ---------------------------------------------------------------------------
# Tests: edge cases
# ---------------------------------------------------------------------------


def test_empty_string_returns_unknown(normalizer: VenueNormalizer) -> None:
    """An empty extracted_name should return (None, 'unknown')."""
    venue_id, method = normalizer.normalize("")
    assert venue_id is None
    assert method == "unknown"


def test_whitespace_only_returns_unknown(normalizer: VenueNormalizer) -> None:
    """A whitespace-only extracted_name should return (None, 'unknown')."""
    venue_id, method = normalizer.normalize("   ")
    assert venue_id is None
    assert method == "unknown"


def test_empty_string_adds_to_human_review_queue(aliases: dict, mappings: dict) -> None:
    """An empty extracted_name should add a 'name_mismatch_unresolved' review item."""
    queue: list[dict] = []
    n = VenueNormalizer(aliases=aliases, mappings=mappings, human_review_queue=queue)
    n.normalize("")
    assert len(queue) >= 1
    assert queue[0]["issue_type"] == "name_mismatch_unresolved"


def test_all_tiers_fail_adds_to_human_review(aliases: dict, mappings: dict) -> None:
    """When all tiers fail, a high-severity review item should be appended."""
    queue: list[dict] = []
    n = VenueNormalizer(
        aliases=aliases,
        mappings=mappings,
        human_review_queue=queue,
        fuzzy_threshold=99,  # Near-impossible threshold so fuzzy also fails.
    )
    venue_id, method = n.normalize("Completely Unrelated Venue Name XYZ")
    assert venue_id is None
    assert method == "unknown"
    assert len(queue) >= 1
    assert queue[-1]["issue_type"] == "name_mismatch_unresolved"
    assert queue[-1]["severity"] == "high"


def test_no_review_queue_does_not_raise(aliases: dict, mappings: dict) -> None:
    """Normalization with no human_review_queue should not raise any errors."""
    n = VenueNormalizer(aliases=aliases, mappings=mappings, human_review_queue=None)
    # Should not raise even on unknown name.
    venue_id, method = n.normalize("Totally Unknown Place")
    assert method in ("alias", "fuzzy", "ai", "unknown")


# ---------------------------------------------------------------------------
# Tests: get_canonical_name
# ---------------------------------------------------------------------------


def test_get_canonical_name_known_venue(normalizer: VenueNormalizer) -> None:
    """get_canonical_name returns the location_label itself for a known label."""
    assert normalizer.get_canonical_name("Curran Theater") == "Curran Theater"
    assert normalizer.get_canonical_name("Davies Symphony Hall") == "Davies Symphony Hall"


def test_get_canonical_name_unknown_venue(normalizer: VenueNormalizer) -> None:
    """get_canonical_name returns None for a label not in the mappings."""
    assert normalizer.get_canonical_name("not_a_real_venue") is None
