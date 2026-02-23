"""Tests for src/cookie_dismisser.py — dismiss_cookie_modal() and helpers.

Uses :class:`unittest.mock.AsyncMock` to simulate Playwright Page objects
without live browser connections.  AI provider calls are also mocked.
"""

from unittest.mock import AsyncMock, MagicMock

from src.cookie_dismisser import _extract_ai_selector_text, dismiss_cookie_modal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_page(screenshot_bytes: bytes = b"fake_screenshot") -> MagicMock:
    """Return a mock Playwright Page.

    Args:
        screenshot_bytes: Bytes returned by ``page.screenshot()``.

    Returns:
        A :class:`~unittest.mock.MagicMock` with async screenshot and locator.
    """
    page = MagicMock()
    page.url = "https://example.com"
    page.screenshot = AsyncMock(return_value=screenshot_bytes)
    page.locator = MagicMock()
    return page


def _make_selector(css: str, description: str = "Accept cookies") -> dict:
    """Return a selector dict as loaded from cookie_selectors.yaml.

    Args:
        css: CSS selector string.
        description: Human-readable selector description.

    Returns:
        Selector dict with ``css_selector``, ``description``, and ``site_pattern``.
    """
    return {"css_selector": css, "description": description, "site_pattern": "*"}


def _visible_locator() -> MagicMock:
    """Return a locator mock that reports itself as visible and clickable."""
    locator = AsyncMock()
    locator.is_visible = AsyncMock(return_value=True)
    locator.click = AsyncMock()
    return locator


def _invisible_locator() -> MagicMock:
    """Return a locator mock that reports itself as not visible."""
    locator = AsyncMock()
    locator.is_visible = AsyncMock(return_value=False)
    locator.click = AsyncMock()
    return locator


# ---------------------------------------------------------------------------
# Tests: dismiss_cookie_modal — selector path (Tier 1)
# ---------------------------------------------------------------------------


async def test_matching_selector_dismisses_and_returns_true() -> None:
    """When a selector finds a visible element and click succeeds, return True."""
    page = _make_page()
    locator = _visible_locator()
    page.locator.return_value.first = locator

    result = await dismiss_cookie_modal(
        page, [_make_selector("#accept-cookies")], venue_id="curran"
    )
    assert result is True
    locator.click.assert_called_once()


async def test_no_visible_selector_returns_false_with_no_provider() -> None:
    """When no selector matches and no AI provider is given, return False."""
    page = _make_page()
    page.locator.return_value.first = _invisible_locator()

    result = await dismiss_cookie_modal(
        page, [_make_selector("#accept-cookies")], provider=None, venue_id="curran"
    )
    assert result is False


async def test_empty_selectors_list_returns_false() -> None:
    """An empty selectors list with no provider should return False immediately."""
    page = _make_page()
    result = await dismiss_cookie_modal(page, selectors=[], provider=None, venue_id="test")
    assert result is False
    page.locator.assert_not_called()


async def test_selector_with_empty_css_string_is_skipped() -> None:
    """A selector dict with an empty css_selector value should be silently skipped."""
    page = _make_page()
    selectors = [{"css_selector": "", "description": "empty", "site_pattern": "*"}]

    result = await dismiss_cookie_modal(page, selectors, provider=None, venue_id="test")
    assert result is False
    page.locator.assert_not_called()


async def test_click_exception_skips_selector_and_returns_false() -> None:
    """If click() raises, the selector is skipped and False is returned."""
    page = _make_page()
    locator = AsyncMock()
    locator.is_visible = AsyncMock(return_value=True)
    locator.click = AsyncMock(side_effect=Exception("not interactable"))
    page.locator.return_value.first = locator

    result = await dismiss_cookie_modal(
        page, [_make_selector("#bad-button")], provider=None, venue_id="test"
    )
    assert result is False


async def test_first_matching_selector_is_used_not_later_ones() -> None:
    """Only the first matching selector should be clicked; others are not tried."""
    page = _make_page()
    clicked: list[str] = []

    def make_locator(selector: str) -> MagicMock:
        outer = MagicMock()
        inner = AsyncMock()
        inner.is_visible = AsyncMock(return_value=True)

        async def click(**kwargs) -> None:
            clicked.append(selector)

        inner.click = click
        outer.first = inner
        return outer

    page.locator.side_effect = make_locator

    selectors = [_make_selector("#first"), _make_selector("#second")]
    result = await dismiss_cookie_modal(page, selectors, provider=None, venue_id="test")

    assert result is True
    assert len(clicked) == 1
    assert clicked[0] == "#first"


async def test_multiple_selectors_second_one_matches() -> None:
    """If the first selector is invisible, the second matching one should be used."""
    page = MagicMock()
    page.url = "https://example.com"
    page.screenshot = AsyncMock(return_value=b"fake")

    first_call = True

    def make_locator(selector: str) -> MagicMock:
        nonlocal first_call
        outer = MagicMock()
        inner = AsyncMock()
        if first_call:
            inner.is_visible = AsyncMock(return_value=False)
            first_call = False
        else:
            inner.is_visible = AsyncMock(return_value=True)
        inner.click = AsyncMock()
        outer.first = inner
        return outer

    page.locator = MagicMock(side_effect=make_locator)

    selectors = [_make_selector("#no-match"), _make_selector("#real-accept")]
    result = await dismiss_cookie_modal(page, selectors, provider=None, venue_id="test")
    assert result is True


# ---------------------------------------------------------------------------
# Tests: dismiss_cookie_modal — AI fallback path (Tier 2)
# ---------------------------------------------------------------------------


async def test_ai_fallback_called_when_no_selector_matches() -> None:
    """When no selector matches, the AI provider's extract_events should be called."""
    page = _make_page()
    page.locator.return_value.first = _invisible_locator()

    mock_provider = MagicMock()
    mock_provider.extract_events = AsyncMock(return_value=[{"label": "NONE"}])

    await dismiss_cookie_modal(
        page, [_make_selector("#no-match")], provider=mock_provider, venue_id="curran"
    )
    mock_provider.extract_events.assert_called_once()


async def test_ai_returning_none_word_gives_false() -> None:
    """If AI returns the word NONE, dismiss_cookie_modal should return False."""
    page = _make_page()
    page.locator.return_value.first = _invisible_locator()

    mock_provider = MagicMock()
    mock_provider.extract_events = AsyncMock(return_value=[{"label": "NONE"}])

    result = await dismiss_cookie_modal(
        page, selectors=[], provider=mock_provider, venue_id="curran"
    )
    assert result is False


async def test_ai_screenshot_failure_returns_false() -> None:
    """If screenshot for the AI call fails, return False without calling the provider."""
    page = _make_page()
    page.screenshot = AsyncMock(side_effect=Exception("screenshot failed"))
    page.locator.return_value.first = _invisible_locator()

    mock_provider = MagicMock()
    mock_provider.extract_events = AsyncMock()

    result = await dismiss_cookie_modal(
        page, selectors=[], provider=mock_provider, venue_id="curran"
    )
    assert result is False
    mock_provider.extract_events.assert_not_called()


async def test_ai_provider_extract_events_exception_returns_false() -> None:
    """If AI extract_events raises an exception, dismiss_cookie_modal returns False."""
    page = _make_page()
    page.locator.return_value.first = _invisible_locator()

    mock_provider = MagicMock()
    mock_provider.extract_events = AsyncMock(side_effect=Exception("API error"))

    result = await dismiss_cookie_modal(
        page, selectors=[], provider=mock_provider, venue_id="curran"
    )
    assert result is False


async def test_ai_suggested_invisible_selector_returns_false() -> None:
    """If AI returns a selector but the element is not visible, return False."""
    page = _make_page()
    # All locators invisible, including the AI-suggested one.
    page.locator.return_value.first = _invisible_locator()

    mock_provider = MagicMock()
    mock_provider.extract_events = AsyncMock(return_value=[{"label": "#ai-button"}])

    result = await dismiss_cookie_modal(
        page, selectors=[], provider=mock_provider, venue_id="curran"
    )
    assert result is False


# ---------------------------------------------------------------------------
# Tests: _extract_ai_selector_text
# ---------------------------------------------------------------------------


def test_extract_selector_from_label_key() -> None:
    """_extract_ai_selector_text should read the 'label' key from the first result."""
    assert _extract_ai_selector_text([{"label": "#cookie-accept"}]) == "#cookie-accept"


def test_extract_selector_from_text_key() -> None:
    """_extract_ai_selector_text should read the 'text' key if present."""
    assert (
        _extract_ai_selector_text([{"text": ".cookie-banner button.accept"}])
        == ".cookie-banner button.accept"
    )


def test_extract_selector_from_selector_key() -> None:
    """_extract_ai_selector_text should read the 'selector' key if present."""
    assert (
        _extract_ai_selector_text([{"selector": "[data-action='accept']"}])
        == "[data-action='accept']"
    )


def test_extract_selector_from_raw_response_key() -> None:
    """_extract_ai_selector_text should read the 'raw_response' key if present."""
    assert _extract_ai_selector_text([{"raw_response": "#accept-all"}]) == "#accept-all"


def test_extract_selector_empty_list_returns_empty_string() -> None:
    """_extract_ai_selector_text should return '' for an empty result list."""
    assert _extract_ai_selector_text([]) == ""


def test_extract_selector_prefers_text_over_label() -> None:
    """When both 'text' and 'label' keys exist, 'text' should be preferred (checked first)."""
    result = _extract_ai_selector_text([{"text": "#text-key", "label": "#label-key"}])
    assert result == "#text-key"


def test_extract_selector_whitespace_is_stripped() -> None:
    """_extract_ai_selector_text should strip leading/trailing whitespace."""
    assert _extract_ai_selector_text([{"label": "  #accept  "}]) == "#accept"


def test_extract_selector_none_string_values_fall_through() -> None:
    """When all known keys have None values, a fallback string representation is returned."""
    result = _extract_ai_selector_text([{"confidence": None, "notes": None}])
    # The function falls back to str(first) — we just check no exception is raised
    # and a string is returned.
    assert isinstance(result, str)
