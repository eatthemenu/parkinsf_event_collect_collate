"""Free local page expansion: scroll, 'Load More', calendar pagination.

Performs all free (non-AI) local work to ensure the full event listing is
visible before screenshots are captured.
"""

import asyncio
import logging

from playwright.async_api import Page

from .venue_config import Settings

logger = logging.getLogger(__name__)

LOAD_MORE_SELECTORS: list[str] = [
    "button:text('Load More')",
    "button:text('Show More')",
    "button:text('See All')",
    "button:text('See All Events')",
    "button:text('View All')",
    "button:text('More Events')",
    "a:text('Load More')",
    "a:text('View All Events')",
    "[class*='load-more']",
    "[class*='show-more']",
    "[data-action='load-more']",
]

CALENDAR_NEXT_SELECTORS: list[str] = [
    "button[aria-label*='Next']",
    "button[aria-label*='next']",
    "button[aria-label*='Next Month']",
    ".fc-next-button",
    "[class*='calendar'][class*='next']",
    "button:text('›')",
    "button:text('>')",
    "button:text('Next')",
]


async def expand_page(page: Page, settings: Settings) -> None:
    """Fully expand a venue schedule page before taking screenshots.

    Performs ALL free local work in this order:
      1. Scroll to bottom once to trigger lazy-load.
      2. Click "Load More" / "Show All" / "See All Events" buttons repeatedly
         until none remain or max_load_more_clicks is reached.
      3. Scroll to bottom again (content may have grown).
      4. Handle calendar "Next Month" pagination up to max_calendar_page_clicks
         times.
      5. Final scroll to bottom.

    Args:
        page: Playwright Page object (already loaded and cookie-dismissed).
        settings: Runtime settings with max_load_more_clicks,
            max_calendar_page_clicks, and scroll_pause_seconds.
    """
    # Step 1: Initial scroll to bottom to trigger lazy-load.
    await _scroll_to_bottom(page, settings.scroll_pause_seconds)

    # Step 2: Click "Load More" style buttons repeatedly.
    load_more_clicks = 0
    while load_more_clicks < settings.max_load_more_clicks:
        clicked = await _try_click_load_more(page)
        if not clicked:
            break
        load_more_clicks += 1
        logger.info(
            "Clicked 'Load More' button (%d/%d) on %s",
            load_more_clicks,
            settings.max_load_more_clicks,
            page.url,
        )
        await asyncio.sleep(settings.scroll_pause_seconds)

    if load_more_clicks > 0:
        logger.info(
            "Total 'Load More' clicks on %s: %d", page.url, load_more_clicks
        )

    # Step 3: Scroll to bottom again after loading more content.
    await _scroll_to_bottom(page, settings.scroll_pause_seconds)

    # Step 4: Calendar pagination.
    calendar_clicks = 0
    while calendar_clicks < settings.max_calendar_page_clicks:
        clicked = await _try_click_calendar_next(page)
        if not clicked:
            break
        calendar_clicks += 1
        logger.info(
            "Turned calendar to next page (%d/%d) on %s",
            calendar_clicks,
            settings.max_calendar_page_clicks,
            page.url,
        )
        await asyncio.sleep(settings.scroll_pause_seconds)

    if calendar_clicks > 0:
        logger.info(
            "Total calendar page turns on %s: %d", page.url, calendar_clicks
        )

    # Step 5: Final scroll to bottom.
    await _scroll_to_bottom(page, settings.scroll_pause_seconds)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _scroll_to_bottom(page: Page, pause_seconds: float) -> None:
    """Scroll the page to the very bottom.

    Args:
        page: Playwright Page object.
        pause_seconds: Seconds to wait after scrolling to let content load.
    """
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(pause_seconds)
    except Exception as exc:
        logger.debug("_scroll_to_bottom: evaluate error (ignored): %s", exc)


async def _try_click_load_more(page: Page) -> bool:
    """Try each load-more selector in order and click the first visible one.

    Args:
        page: Playwright Page object.

    Returns:
        True if a button was found and clicked, False if none were found.
    """
    for selector in LOAD_MORE_SELECTORS:
        try:
            locator = page.locator(selector).first
            # is_visible() with a short timeout avoids long waits for absent
            # elements. We use a 500 ms timeout via expect-visible logic.
            is_visible = await locator.is_visible()
            if not is_visible:
                continue
            await locator.click(timeout=3000)
            logger.debug("_try_click_load_more: clicked selector %r", selector)
            return True
        except Exception as exc:
            logger.debug(
                "_try_click_load_more: selector %r not usable (%s)", selector, exc
            )
            continue
    return False


async def _try_click_calendar_next(page: Page) -> bool:
    """Try each calendar-next selector in order and click the first visible one.

    Args:
        page: Playwright Page object.

    Returns:
        True if a calendar-next button was found and clicked, False otherwise.
    """
    for selector in CALENDAR_NEXT_SELECTORS:
        try:
            locator = page.locator(selector).first
            is_visible = await locator.is_visible()
            if not is_visible:
                continue
            await locator.click(timeout=3000)
            logger.debug(
                "_try_click_calendar_next: clicked selector %r", selector
            )
            return True
        except Exception as exc:
            logger.debug(
                "_try_click_calendar_next: selector %r not usable (%s)",
                selector,
                exc,
            )
            continue
    return False
