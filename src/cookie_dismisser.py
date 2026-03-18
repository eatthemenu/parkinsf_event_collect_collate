"""Cookie consent modal detection and dismissal.

Attempts to dismiss cookie banners using a priority list of CSS selectors,
falling back to an AI vision model if no selector matches.
"""

import asyncio
import logging

from playwright.async_api import Page

from .ai_vision.base import VisionProvider
from .ai_vision.prompt_templates import build_cookie_ai_prompt

logger = logging.getLogger(__name__)

# Timeout in milliseconds for each locator visibility / click check.
_SELECTOR_TIMEOUT_MS = 2000


async def dismiss_cookie_modal(
    page: Page,
    selectors: list[dict],
    provider: VisionProvider | None = None,
    venue_id: str = "unknown",
) -> bool:
    """Attempt to dismiss a cookie consent modal.

    Strategy:
      1. Wait briefly (1 second) for a modal to appear.
      2. Try each CSS selector from the selectors list in order. For each:
         check if the element exists and is visible, then click it. If a click
         succeeds, wait 0.5 s and return True.
      3. If no selector matched and provider is not None: take a viewport
         screenshot, send to AI with build_cookie_ai_prompt(), parse the
         response as a CSS selector string, and try to click it. Return True
         if AI-assisted click succeeded.
      4. Return False if nothing worked (may mean no modal is present).

    Args:
        page: Playwright Page (already navigated to the target URL).
        selectors: List of selector dicts from cookie_selectors.yaml. Each
            dict has keys: css_selector, description, site_pattern.
        provider: Optional VisionProvider for AI-assisted fallback.
        venue_id: Used in log messages.

    Returns:
        True if a modal was dismissed, False otherwise.
    """
    # Step 1: brief wait for a modal to appear.
    await asyncio.sleep(1.0)

    # Step 2: try each configured CSS selector.
    for selector_dict in selectors:
        css_selector: str = selector_dict.get("css_selector", "").strip()
        if not css_selector:
            continue

        try:
            locator = page.locator(css_selector).first
            # Use a short timeout so we do not block on absent elements.
            is_visible = await locator.is_visible(timeout=_SELECTOR_TIMEOUT_MS)
            if not is_visible:
                continue

            await locator.click(timeout=_SELECTOR_TIMEOUT_MS)
            await asyncio.sleep(0.5)
            logger.info(
                "dismiss_cookie_modal: dismissed modal for venue_id=%s using selector %r",
                venue_id,
                css_selector,
            )
            return True

        except Exception as exc:
            logger.debug(
                "dismiss_cookie_modal: selector %r not usable for venue_id=%s (%s)",
                css_selector,
                venue_id,
                exc,
            )
            continue

    logger.debug(
        "dismiss_cookie_modal: no configured selector matched for venue_id=%s",
        venue_id,
    )

    # Step 3: AI vision fallback.
    if provider is None:
        return False

    logger.debug("dismiss_cookie_modal: attempting AI fallback for venue_id=%s", venue_id)

    try:
        screenshot_bytes: bytes = await page.screenshot()
    except Exception as exc:
        logger.warning(
            "dismiss_cookie_modal: screenshot for AI fallback failed for venue_id=%s: %s",
            venue_id,
            exc,
        )
        return False

    prompt = build_cookie_ai_prompt()
    try:
        ai_results: list[dict] = await provider.extract_events(
            screenshots=[screenshot_bytes],
            prompt=prompt,
            venue_context={"venue_id": venue_id},
        )
    except Exception as exc:
        logger.warning(
            "dismiss_cookie_modal: AI call failed for venue_id=%s: %s",
            venue_id,
            exc,
        )
        return False

    # The cookie AI prompt asks the model to return a single CSS selector string
    # (not a JSON event list). We use extract_events() for interface uniformity,
    # but the response will arrive as raw text wrapped in a list by the provider.
    # Retrieve the raw text from the first result item if possible, otherwise
    # fall back to treating the entire result list as a text response.
    ai_selector: str = _extract_ai_selector_text(ai_results)

    if not ai_selector or ai_selector.upper() == "NONE":
        logger.debug(
            "dismiss_cookie_modal: AI found no cookie modal for venue_id=%s",
            venue_id,
        )
        return False

    logger.info(
        "dismiss_cookie_modal: AI suggested selector %r for venue_id=%s",
        ai_selector,
        venue_id,
    )

    try:
        locator = page.locator(ai_selector).first
        is_visible = await locator.is_visible(timeout=_SELECTOR_TIMEOUT_MS)
        if not is_visible:
            logger.warning(
                "dismiss_cookie_modal: AI selector %r not visible for venue_id=%s",
                ai_selector,
                venue_id,
            )
            return False

        await locator.click(timeout=_SELECTOR_TIMEOUT_MS)
        await asyncio.sleep(0.5)
        logger.info(
            "dismiss_cookie_modal: AI-assisted dismissal succeeded for "
            "venue_id=%s using selector %r",
            venue_id,
            ai_selector,
        )
        return True

    except Exception as exc:
        logger.warning(
            "dismiss_cookie_modal: AI selector %r click failed for venue_id=%s: %s",
            ai_selector,
            venue_id,
            exc,
        )
        return False


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _extract_ai_selector_text(ai_results: list[dict]) -> str:
    """Extract the plain CSS selector string from AI provider results.

    The cookie AI prompt instructs the model to respond with a bare CSS
    selector string or the word NONE. Provider implementations wrap responses
    in list[dict], so we look for the raw text in the first result dict.

    Args:
        ai_results: List of dicts returned by VisionProvider.extract_events().

    Returns:
        The CSS selector string, "NONE", or an empty string if not parseable.
    """
    if not ai_results:
        return ""

    first = ai_results[0]
    if isinstance(first, dict):
        # Some providers may return the raw text response under a 'text' or
        # 'label' key if the response was not parseable as a structured event.
        for key in ("text", "label", "raw_response", "selector"):
            val = first.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()

    # If the dict itself has no useful string field, fall back to the string
    # representation of the first item (may be the selector itself).
    raw = str(first).strip()
    return raw
