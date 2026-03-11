"""Full-page and chunked screenshot capture.

Captures one or more PNG screenshots of a fully-expanded Playwright page,
chunking tall pages into overlapping viewport-height slices.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from playwright.async_api import Page

from .venue_config import Settings

logger = logging.getLogger(__name__)


async def take_screenshots(
    page: Page,
    settings: Settings,
    save_dir: Path,
    venue_id: str,
) -> list[bytes]:
    """Capture screenshots of the full page, chunking if too tall.

    If page height <= settings.screenshot_max_height_px:
        Take one full-page screenshot.
    Else:
        Scroll through the page in viewport-height chunks with
        settings.screenshot_overlap_px overlap between chunks.
        Take a viewport screenshot at each position.

    Screenshots are saved to
    save_dir/{venue_id}_{YYYYMMDD}_{HHMMSS}_page_{N}.png and also returned
    as bytes.

    Args:
        page: Playwright Page (fully expanded, at top of page).
        settings: Runtime settings (screenshot_max_height_px, viewport_height,
            screenshot_overlap_px).
        save_dir: Directory to save screenshot files.
        venue_id: Used in the filename.

    Returns:
        List of PNG image bytes (one per chunk or one full-page).
    """
    save_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Scroll back to the very top before measuring / shooting.
    try:
        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.3)
    except Exception as exc:
        logger.debug("take_screenshots: scroll to top error (ignored): %s", exc)

    # Measure the full scrollable height.
    try:
        total_height: int = await page.evaluate("document.body.scrollHeight")
    except Exception as exc:
        logger.warning(
            "take_screenshots: could not read scrollHeight for venue_id=%s (%s); "
            "defaulting to viewport height",
            venue_id,
            exc,
        )
        total_height = settings.viewport_height

    screenshots: list[bytes] = []

    if total_height <= settings.screenshot_max_height_px:
        # Single full-page screenshot.
        page_num = 1
        file_path = save_dir / f"{venue_id}_{timestamp_str}_page_{page_num}.png"
        try:
            img_bytes: bytes = await page.screenshot(full_page=True)
            file_path.write_bytes(img_bytes)
            screenshots.append(img_bytes)
            logger.debug(
                "take_screenshots: full-page screenshot saved to %s (%d bytes)",
                file_path,
                len(img_bytes),
            )
        except Exception as exc:
            logger.error(
                "take_screenshots: full-page screenshot failed for venue_id=%s: %s",
                venue_id,
                exc,
                exc_info=True,
            )
    else:
        # Chunked mode: scroll through the page in viewport-height steps with
        # overlap between adjacent chunks.
        viewport_height = settings.viewport_height
        overlap = settings.screenshot_overlap_px
        step = viewport_height - overlap
        if step <= 0:
            # Safety: if overlap >= viewport_height, just use half-viewport steps.
            step = max(1, viewport_height // 2)

        y_positions: list[int] = []
        y = 0
        while True:
            y_positions.append(y)
            if y + viewport_height >= total_height:
                break
            y += step

        for page_num, y_pos in enumerate(y_positions, start=1):
            file_path = save_dir / f"{venue_id}_{timestamp_str}_page_{page_num}.png"
            try:
                await page.evaluate(f"window.scrollTo(0, {y_pos})")
                await asyncio.sleep(0.3)
                img_bytes = await page.screenshot()
                file_path.write_bytes(img_bytes)
                screenshots.append(img_bytes)
                logger.debug(
                    "take_screenshots: chunk %d (y=%d) saved to %s (%d bytes)",
                    page_num,
                    y_pos,
                    file_path,
                    len(img_bytes),
                )
            except Exception as exc:
                logger.error(
                    "take_screenshots: chunk %d (y=%d) failed for venue_id=%s: %s",
                    page_num,
                    y_pos,
                    venue_id,
                    exc,
                    exc_info=True,
                )
                # Continue with remaining chunks even if one fails.

    logger.info(
        "take_screenshots: captured %d screenshot(s) for venue_id=%s (page height=%d px)",
        len(screenshots),
        venue_id,
        total_height,
    )
    return screenshots
