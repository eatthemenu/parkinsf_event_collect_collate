"""Tests for src/page_expander.py — expand_page() and helper functions.

Uses :class:`unittest.mock.AsyncMock` to simulate Playwright Page objects
without making any live browser connections.
"""

from unittest.mock import AsyncMock, MagicMock

from src.page_expander import (
    CALENDAR_NEXT_SELECTORS,
    LOAD_MORE_SELECTORS,
    _try_click_calendar_next,
    _try_click_load_more,
    expand_page,
)
from src.venue_config import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides) -> Settings:
    """Return a Settings instance with test-friendly (fast) defaults.

    Args:
        **overrides: Field values to override on the default Settings.

    Returns:
        A :class:`~venue_config.Settings` with scroll_pause_seconds=0.
    """
    defaults: dict = {
        "max_load_more_clicks": 3,
        "max_calendar_page_clicks": 2,
        "scroll_pause_seconds": 0.0,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _make_page(visible: bool = False) -> MagicMock:
    """Return a Playwright Page mock whose locators return a fixed visibility.

    Args:
        visible: If True, every locator will appear visible and clickable.

    Returns:
        A :class:`~unittest.mock.MagicMock` with async evaluate and locator methods.
    """
    page = MagicMock()
    page.url = "https://example.com"
    page.evaluate = AsyncMock(return_value=None)

    locator_inner = AsyncMock()
    locator_inner.is_visible = AsyncMock(return_value=visible)
    locator_inner.click = AsyncMock()

    locator_outer = MagicMock()
    locator_outer.first = locator_inner
    page.locator = MagicMock(return_value=locator_outer)

    return page


# ---------------------------------------------------------------------------
# Tests: LOAD_MORE_SELECTORS and CALENDAR_NEXT_SELECTORS are defined
# ---------------------------------------------------------------------------


def test_load_more_selectors_not_empty() -> None:
    """LOAD_MORE_SELECTORS must contain at least one CSS selector string."""
    assert len(LOAD_MORE_SELECTORS) > 0
    assert all(isinstance(s, str) for s in LOAD_MORE_SELECTORS)


def test_calendar_next_selectors_not_empty() -> None:
    """CALENDAR_NEXT_SELECTORS must contain at least one CSS selector string."""
    assert len(CALENDAR_NEXT_SELECTORS) > 0
    assert all(isinstance(s, str) for s in CALENDAR_NEXT_SELECTORS)


# ---------------------------------------------------------------------------
# Tests: _try_click_load_more
# ---------------------------------------------------------------------------


async def test_try_click_load_more_returns_true_when_visible_button_clicked() -> None:
    """_try_click_load_more returns True when a visible button is successfully clicked."""
    page = _make_page(visible=True)
    result = await _try_click_load_more(page)
    assert result is True
    # The first locator's .first.click should have been called once.
    page.locator.return_value.first.click.assert_called_once()


async def test_try_click_load_more_returns_false_when_no_visible_button() -> None:
    """_try_click_load_more returns False when no selector finds a visible button."""
    page = _make_page(visible=False)
    result = await _try_click_load_more(page)
    assert result is False


async def test_try_click_load_more_skips_exception_and_tries_next() -> None:
    """_try_click_load_more continues to the next selector if is_visible raises."""
    page = MagicMock()
    page.url = "https://example.com"
    page.evaluate = AsyncMock(return_value=None)

    first_call = True

    def locator_side_effect(selector: str) -> MagicMock:
        nonlocal first_call
        outer = MagicMock()
        inner = AsyncMock()
        if first_call:
            # First selector throws during is_visible.
            inner.is_visible = AsyncMock(side_effect=Exception("selector error"))
            first_call = False
        else:
            # All subsequent selectors: not visible.
            inner.is_visible = AsyncMock(return_value=False)
        inner.click = AsyncMock()
        outer.first = inner
        return outer

    page.locator = MagicMock(side_effect=locator_side_effect)
    result = await _try_click_load_more(page)
    # No button was successfully clicked; result should be False.
    assert result is False


async def test_try_click_load_more_returns_false_when_click_raises() -> None:
    """_try_click_load_more returns False and continues if click() raises."""
    page = MagicMock()
    page.url = "https://example.com"
    page.evaluate = AsyncMock(return_value=None)

    outer = MagicMock()
    inner = AsyncMock()
    inner.is_visible = AsyncMock(return_value=True)
    inner.click = AsyncMock(side_effect=Exception("not interactable"))
    outer.first = inner
    page.locator = MagicMock(return_value=outer)

    result = await _try_click_load_more(page)
    assert result is False


# ---------------------------------------------------------------------------
# Tests: _try_click_calendar_next
# ---------------------------------------------------------------------------


async def test_try_click_calendar_next_returns_true_when_button_found() -> None:
    """_try_click_calendar_next returns True when a visible button is clicked."""
    page = _make_page(visible=True)
    result = await _try_click_calendar_next(page)
    assert result is True
    page.locator.return_value.first.click.assert_called_once()


async def test_try_click_calendar_next_returns_false_when_not_found() -> None:
    """_try_click_calendar_next returns False when no calendar-next button is visible."""
    page = _make_page(visible=False)
    result = await _try_click_calendar_next(page)
    assert result is False


async def test_try_click_calendar_next_skips_exception() -> None:
    """_try_click_calendar_next continues past selectors that raise exceptions."""
    page = MagicMock()
    page.url = "https://example.com"
    page.evaluate = AsyncMock(return_value=None)

    outer = MagicMock()
    inner = AsyncMock()
    inner.is_visible = AsyncMock(side_effect=Exception("timeout"))
    inner.click = AsyncMock()
    outer.first = inner
    page.locator = MagicMock(return_value=outer)

    result = await _try_click_calendar_next(page)
    assert result is False


# ---------------------------------------------------------------------------
# Tests: expand_page
# ---------------------------------------------------------------------------


async def test_expand_page_calls_scroll_at_least_twice() -> None:
    """expand_page should call page.evaluate (scroll) at least twice."""
    page = _make_page(visible=False)
    settings = _make_settings()
    await expand_page(page, settings)
    # scroll_to_bottom is called via evaluate; it runs at steps 1, 3, and 5.
    assert page.evaluate.call_count >= 2


async def test_expand_page_no_buttons_completes_without_error() -> None:
    """expand_page should complete normally when no expandable buttons exist."""
    page = _make_page(visible=False)
    settings = _make_settings()
    # Must not raise.
    await expand_page(page, settings)


async def test_expand_page_respects_max_load_more_clicks() -> None:
    """expand_page must stop clicking 'Load More' after max_load_more_clicks."""
    click_count = 0
    max_clicks = 2

    page = MagicMock()
    page.url = "https://example.com"
    page.evaluate = AsyncMock(return_value=None)

    def make_outer(_selector: str) -> MagicMock:
        nonlocal click_count
        outer = MagicMock()
        inner = AsyncMock()
        inner.is_visible = AsyncMock(return_value=True)

        async def do_click(**kwargs) -> None:
            nonlocal click_count
            click_count += 1

        inner.click = do_click
        outer.first = inner
        return outer

    page.locator = MagicMock(side_effect=make_outer)
    settings = _make_settings(max_load_more_clicks=max_clicks, max_calendar_page_clicks=0)
    await expand_page(page, settings)
    assert click_count <= max_clicks


async def test_expand_page_respects_max_calendar_page_clicks() -> None:
    """expand_page must stop calendar pagination after max_calendar_page_clicks."""
    click_count = 0
    max_clicks = 2

    page = MagicMock()
    page.url = "https://example.com"
    page.evaluate = AsyncMock(return_value=None)

    def make_outer(_selector: str) -> MagicMock:
        nonlocal click_count
        outer = MagicMock()
        inner = AsyncMock()
        inner.is_visible = AsyncMock(return_value=True)

        async def do_click(**kwargs) -> None:
            nonlocal click_count
            click_count += 1

        inner.click = do_click
        outer.first = inner
        return outer

    page.locator = MagicMock(side_effect=make_outer)
    settings = _make_settings(max_load_more_clicks=0, max_calendar_page_clicks=max_clicks)
    await expand_page(page, settings)
    assert click_count <= max_clicks


async def test_expand_page_zero_max_clicks_does_not_click() -> None:
    """With both max clicks set to 0, expand_page should not click any buttons."""
    page = _make_page(visible=True)
    settings = _make_settings(max_load_more_clicks=0, max_calendar_page_clicks=0)
    await expand_page(page, settings)
    page.locator.return_value.first.click.assert_not_called()
