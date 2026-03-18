"""Playwright browser controller for the event aggregator pipeline.

Provides :class:`BrowserController`, which wraps a Playwright Chromium
instance and creates isolated :class:`~playwright.async_api.BrowserContext`
objects for each venue so cookies and state are never shared across venues.

The browser process is automatically restarted every
``settings.browser_restart_interval`` venues to prevent memory leaks.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from playwright.async_api import Browser, BrowserContext, Page, Playwright

from .venue_config import Settings

logger = logging.getLogger(__name__)


class BrowserController:
    """Manages a Playwright Chromium browser for the aggregator pipeline.

    Creates one isolated :class:`~playwright.async_api.BrowserContext` per
    venue so that cookies, local storage, and session state are never shared
    between venues.  Tracks how many venues have been processed since the last
    browser launch and restarts Chromium at the configured interval to prevent
    memory leaks.

    Usage::

        async with async_playwright() as playwright:
            controller = BrowserController(playwright, settings)
            await controller.start()
            try:
                async with controller.venue_page("curran") as page:
                    await page.goto("https://sfcurran.com/events")
                    ...
            finally:
                await controller.stop()

    Attributes:
        settings: Runtime settings controlling viewport dimensions and the
            browser restart interval.
    """

    def __init__(self, playwright: Playwright, settings: Settings) -> None:
        """Initialize the BrowserController.

        Args:
            playwright: The Playwright instance obtained from
                ``async_playwright()``.
            settings: Runtime settings with ``viewport_width``,
                ``viewport_height``, and ``browser_restart_interval``.
        """
        self._playwright = playwright
        self.settings = settings
        self._browser: Browser | None = None
        self._venues_since_restart: int = 0

    async def start(self) -> None:
        """Launch the underlying Chromium browser process.

        Safe to call multiple times; subsequent calls are no-ops if the browser
        is already running.
        """
        if self._browser is None:
            await self._launch()

    async def stop(self) -> None:
        """Close the Chromium browser process and release all resources."""
        if self._browser is not None:
            try:
                await self._browser.close()
                logger.debug("Browser closed")
            except Exception as exc:
                logger.warning("Error closing browser: %s", exc)
            finally:
                self._browser = None

    @asynccontextmanager
    async def venue_page(self, venue_id: str) -> AsyncGenerator[Page, None]:
        """Context manager that yields an isolated Page for one venue.

        Creates a fresh :class:`~playwright.async_api.BrowserContext` with an
        empty cookie jar and no shared storage, then closes it when the block
        exits.  Restarts the browser process if the venue-count threshold has
        been reached.

        Args:
            venue_id: The venue's stable identifier; used only for logging.

        Yields:
            A :class:`~playwright.async_api.Page` ready for navigation, with
            the viewport configured to ``settings.viewport_width`` ×
            ``settings.viewport_height``.
        """
        if self._browser is None:
            await self._launch()

        # Restart the browser at the configured interval to prevent leaks.
        if (
            self._venues_since_restart > 0
            and self._venues_since_restart % self.settings.browser_restart_interval == 0
        ):
            logger.info(
                "Restarting browser after %d venues (interval=%d)",
                self._venues_since_restart,
                self.settings.browser_restart_interval,
            )
            await self._restart()

        context: BrowserContext = await self._browser.new_context(  # type: ignore[union-attr]
            viewport={
                "width": self.settings.viewport_width,
                "height": self.settings.viewport_height,
            }
        )
        page: Page = await context.new_page()
        self._venues_since_restart += 1

        logger.debug(
            "Created isolated browser context for venue_id=%s (venues_since_restart=%d)",
            venue_id,
            self._venues_since_restart,
        )

        try:
            yield page
        finally:
            try:
                await context.close()
                logger.debug("Browser context closed for venue_id=%s", venue_id)
            except Exception as exc:
                logger.warning("Error closing browser context for venue_id=%s: %s", venue_id, exc)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _launch(self) -> None:
        """Launch a new headless Chromium browser instance.

        Resets the venue-count-since-restart counter.
        """
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._venues_since_restart = 0
        logger.debug("Chromium browser launched (headless=True)")

    async def _restart(self) -> None:
        """Close the current browser and immediately relaunch it."""
        if self._browser is not None:
            try:
                await self._browser.close()
                logger.debug("Browser closed for restart")
            except Exception as exc:
                logger.warning("Error closing browser during restart: %s", exc)
            finally:
                self._browser = None

        await self._launch()
        logger.info("Browser restarted successfully")
