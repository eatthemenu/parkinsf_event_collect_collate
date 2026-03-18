# Skill: Browser Automation Rules

Read this file before modifying `browser.py`, `page_expander.py`, `cookie_dismisser.py`, or `screenshot.py`.

## Core Principle

Maximize free local processing before making AI calls. Scroll pages, click "Load More" buttons, expand calendars, and dismiss cookie modals using Playwright — all before taking screenshots. See also: the "deterministic first, AI fallback" principle in `SKILLS/ai-providers.md`.

## Browser Context Isolation

- One isolated browser context per venue. Never share cookies or state across venues.
- Restart the browser process every 10 venues to prevent memory leaks.
- The browser runs as an unprivileged user, never root. See `SKILLS/security.md`.

## Cookie Modal Dismissal

Two-tier approach:

1. **Deterministic** (free): attempt dismissal via CSS selectors defined in `config/cookie_selectors.yaml`.
2. **AI-assisted** (paid): only if the deterministic approach fails and content is still obscured. Log the AI call per `SKILLS/ai-providers.md` logging requirements.

The cookie selector config is a living document — it grows with each run.

## Page Expansion

Before screenshotting, use Playwright to:
- Scroll to the bottom of the page to trigger lazy-loaded content.
- Click "Load More" / "Show All" buttons.
- Expand calendar views to cover the configured event window.
- Wait for dynamic content to render.

## Screenshots

- Viewport resolution: 1280×900.
- Pages taller than 3000px: split into overlapping viewport-sized chunks.
- File naming: `{venue_id}_{YYYYMMDD}_{HHMMSS}_page_{N}.png`
- Screenshots are gitignored and auto-cleaned after 30 days. See `SKILLS/security.md`.

## Rate Limiting

- Respect a configurable delay between page loads (defined in `config/settings.yaml`) to avoid triggering bot detection.

## Error Handling

- Network errors and browser crashes: retry up to 2 times with exponential backoff, then skip the venue and log an ERROR.
- Authentication walls or CAPTCHAs: detect, skip the venue, log as "requires manual intervention."
- For full retry and fallback rules, see `SKILLS/error-handling.md`.
