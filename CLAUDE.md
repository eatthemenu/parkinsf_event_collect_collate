# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Project: Event Schedule Aggregator

## Purpose

This program reads SF Bay Area venue show schedule web pages using AI multimodal vision models and produces structured CSV data for import into a production MySQL events table. It uses headless browser screenshots — not traditional web scraping — so that layout and style changes on venue websites do not break data collection.

The program feeds a live production application that displays parking scarcity information around event venues. Bad data has real user impact.

## Architecture Overview

- **Language**: Python 3.11+ with async support
- **Browser Automation**: Playwright (headless Chromium)
- **AI Vision**: Abstracted multi-provider interface (Google Gemini, OpenAI GPT-4o, Anthropic Claude)
- **Venue Matching**: Deterministic alias table → fuzzy matching → AI-assisted (tiered, cheapest first)
- **Config**: YAML for settings, CSV for venue data, `.env` for secrets
- **Platform**: Debian Linux 13.3 (VirtualBox)
- **Database**: MySQL (read-only in V2, read-write in V3+)

### Pipeline Flow

```
Event Source CSV → Browser (load, expand, screenshot) → AI Vision (extract events)
→ Venue Normalizer (alias → fuzzy → AI) → Validator → Assembler → Event Table Update CSV
```

### Key Design Principle

**Deterministic first, AI fallback.** Always try the cheapest local approach before spending AI tokens. This applies to cookie modal dismissal, venue name matching, and (in future versions) page change detection via hashing.

## Development Workflow

1. Before making changes, create and checkout a branch named per the branch conventions below.
2. Write or update tests for any new or changed functionality.
3. Run `ruff check .` and `ruff format --check .` — fix all issues before committing.
4. Run `pytest` and ensure all tests pass.
5. Write commit messages using Conventional Commits format.
6. Commit to the feature branch. Do not commit directly to `main`.
7. After review and testing, merge to `main` and tag if appropriate.

## Code Standards

- Follow PEP 8, enforced by `ruff`. Max line length: 99 characters.
- Type hints required on all function signatures and return types.
- Google-style docstrings required on all public functions and classes.
- Use `async`/`await` for all Playwright browser operations.
- Use `pathlib.Path` for all file system paths, never raw strings.
- Use `logging` module exclusively for output; never use bare `print()` in `src/`.
- All AI provider calls must go through the `VisionProvider` abstract base class. Never call a provider SDK directly from pipeline code.
- All configuration values must come from `config/settings.yaml`, `config/venue_*.csv`, or environment variables. No hardcoded URLs, API keys, thresholds, or magic numbers in source code.

## AI Provider Rules

**IMPORTANT**: The AI vision provider abstraction is a core architectural boundary. All providers must implement the `VisionProvider` base class. This enables A/B quality testing and instant provider switching for cost or quality reasons.

- Primary provider: Google Gemini 2.5 Flash (cheapest).
- Fallback providers: OpenAI GPT-4o, Anthropic Claude Sonnet.
- Every AI call must be logged with: provider, model, venue_id, token counts, estimated cost, success/failure.
- The `cost_tracker` module enforces a per-run spending cap. If the cap is reached, the program switches to the cheapest available provider and logs a warning. It never silently exceeds budget.
- AI responses must be saved as JSON to `data/ai_responses/` for debugging and regression testing.

## Browser Automation Rules

- One isolated browser context per venue. Never share cookies or state across venues.
- Maximize free local processing before making AI calls: scroll pages, click "Load More" buttons, expand calendars, and dismiss cookie modals using Playwright — all before taking screenshots.
- Cookie modals: attempt deterministic dismissal via `config/cookie_selectors.yaml` first. Only use an AI call if the deterministic approach fails and content is still obscured.
- Screenshot resolution: 1280×900 viewport. Split pages taller than 3000px into overlapping viewport-sized chunks.
- Respect a configurable delay between page loads to avoid triggering bot detection.
- Restart the browser process every 10 venues to prevent memory leaks.

## Venue Name Normalization Rules

Venue names on websites are inconsistent. The same venue may appear as "ACT Geary Theater," "Toni Rembe Theater," or "ACT Rembe Theater." Always resolve names using this priority:

1. **Alias table lookup** (`config/venue_aliases.csv`): exact match against known aliases. Free and deterministic.
2. **Fuzzy matching** (`thefuzz`, threshold ≥ 85): only if alias lookup finds no match. Log the match and score as a warning.
3. **AI-assisted** (cheap text model call): only if fuzzy matching scores below threshold. Log result for human review.

When a new alias is discovered (via fuzzy or AI match), log it to `human_review_*.csv` with a suggestion to add it to the alias table. Over time, Tiers 2 and 3 should be needed less frequently.

## MySQL Schema

The output CSV must match this schema exactly (all fields except `id`, which MySQL auto-assigns):

| Field | Type | Max Length | Source |
|---|---|---|---|
| `label` | VARCHAR | 255 | AI extraction |
| `location_label` | VARCHAR | 255 | AI extraction + normalization |
| `latitude` | DOUBLE | — | Venue mappings lookup |
| `longitude` | DOUBLE | — | Venue mappings lookup |
| `radius` | DOUBLE | — | Venue mappings lookup |
| `event_start_date` | DATE | — | AI extraction, format `YYYY-MM-DD` |
| `event_start_time` | TIME | — | AI extraction, format `HH:MM:SS` 24hr |
| `event_duration` | TIME | — | Constant: `02:00:00` |
| `hours_before_start` | TIME | — | Constant: `01:00:00` |
| `hours_after_end` | TIME | — | Constant: `00:30:00` |
| `details` | VARCHAR | 255 | Constant: `NULL` |
| `web` | VARCHAR | 255 | Browser: source URL |
| `icon` | VARCHAR | 255 | Venue mappings lookup |
| `affected_garages_ids` | VARCHAR | 1024 | Venue mappings lookup |
| `affected_areas` | VARCHAR | 256 | Constant: `NULL` |

**Critical**: `event_start_time` is the show start time, NOT the door open time. The AI prompt must explicitly distinguish these. If only a door time is available and no show time, log the event for human review rather than guessing.

## Validation Rules

Every event record must pass all validators before being written to the output CSV. Records that fail are excluded and logged to `human_review_*.csv`.

- `label`: non-empty, ≤ 255 characters, whitespace trimmed.
- `location_label`: must resolve to a canonical venue via the normalizer, ≤ 255 characters.
- `latitude`: valid decimal, within 37.0–38.0 (SF Bay Area).
- `longitude`: valid decimal, within -123.0 to -121.5 (SF Bay Area).
- `radius`: positive number.
- `event_start_date`: valid `YYYY-MM-DD`, must be ≥ today, must be ≤ today + 6 months.
- `event_start_time`: valid `HH:MM:SS` 24-hour, reasonable range 06:00:00–23:59:59.
- `web`: starts with `https://`, ≤ 255 characters.
- `icon`: non-empty, ≤ 255 characters.
- `affected_garages_ids`: matches comma-separated integers pattern or empty, ≤ 1024 characters.
- Deduplication: records with identical (`label`, `location_label`, `event_start_date`, `event_start_time`) are duplicates. Keep the record with more complete data.

## Venue Site Types

The Event Source CSV includes a `site_type` column that changes extraction behavior:

- **`single_venue`**: The website only lists events at one location (e.g., Curran Theater). The `location_label` is inferred from the venue config; the AI does not need to extract it per event.
- **`multi_venue`**: The website lists events across multiple sub-venues (e.g., ACT lists shows at Toni Rembe and Strand). The AI must extract `location_label` for each event. The Event Source CSV has separate rows per sub-venue, possibly pointing to the same base URL.

## Error Handling

- Network errors and browser crashes: retry up to 2 times with exponential backoff, then skip the venue and log an ERROR.
- AI API errors (rate limit, server error): retry up to 3 times with exponential backoff, then try the fallback provider, then skip and log.
- Authentication walls or CAPTCHAs: detect, skip the venue, log as "requires manual intervention."
- Validation failures: exclude the individual record, log to human review CSV. Never skip an entire venue because one event failed validation.
- Budget exceeded: switch to cheapest provider, log a WARNING. Never silently exceed the per-run spending cap.
- Missing config (API keys, venue mappings): CRITICAL log, abort the run immediately.

All errors must include: timestamp, severity level, module name, venue_id (when applicable), and a human-readable message. Use structured JSON logging for machine parsing.

## Logging

Use Python's `logging` module with two handlers:

1. **Console**: human-readable format, level controlled by `--log-level` CLI flag (default: INFO).
2. **File**: JSON-structured format to `logs/run_YYYYMMDD_HHMMSS.log`, always at DEBUG level.

Additionally, the program generates these output files after each run:

- `logs/cost_YYYYMMDD.log`: per-call AI cost tracking (provider, model, venue, tokens, cost).
- `logs/human_review_YYYYMMDD.csv`: events and venues needing human attention.
- `logs/summary_YYYYMMDD.txt`: run summary with counts, cost totals, and next steps.

Never log API keys, passwords, or credentials. Mask sensitive values in error messages.

## Security

- API keys and credentials live in `.env` (gitignored). Load via `python-dotenv`.
- `.env` file permissions must be `chmod 600`.
- `.env.example` in the repo contains placeholder values only, never real keys.
- The browser runs as an unprivileged user, never root.
- Screenshots and AI responses in `data/` are gitignored and auto-cleaned after 30 days.
- Git pre-commit: verify no secrets in staged files.
- For V2+: MySQL credentials use a dedicated read-only user. Read-write access only added in V3.
- For V5: Gmail App Password (not main password) stored in `.env`, sent via TLS on port 587.

## Testing

### Test Levels

- **Unit tests**: validators, normalizer, CSV I/O, date parsing, cost tracker. Run with `pytest`. No network or AI calls. Use fixtures in `tests/fixtures/`.
- **Regression tests**: save real AI responses as JSON fixtures. Re-test the parsing and assembly pipeline against saved responses without making API calls. This catches regressions in post-processing logic.
- **Integration tests**: run browser + cookie dismissal + page expansion against a live venue URL with `--dry-run` (no AI calls). Validates that Playwright can load and interact with the site.
- **Provider evaluation**: run the full pipeline against the same venues with different `--provider` flags. Compare output CSVs. Review cost logs. Do this quarterly.
- **End-to-end**: full run with all venues. Human review of output CSV required before any production import.

### Quality Gates (every run)

All of these must be true before the output CSV is used:

1. All venues in the input were attempted (none silently dropped).
2. Event count per venue is plausible (≥ 1 for active venues, < 500).
3. All `event_start_date` values are future dates within the configured window.
4. All `event_start_time` values are valid 24-hour format.
5. All `location_label` values resolved to canonical venue IDs.
6. All coordinates are within the SF Bay Area bounding box.
7. No duplicate (`label`, `location_label`, `date`, `time`) tuples in output.
8. Total AI cost is within the per-run budget.
9. Human review queue is < 15% of total events extracted.

## File Organization

```
event-aggregator/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── requirements.txt
├── .env.example
├── .gitignore
│
├── config/
│   ├── settings.yaml               # Timeouts, retries, model defaults, event window
│   ├── venue_mappings.csv           # lat, lon, radius, icon, garages per venue
│   ├── venue_aliases.csv            # alias string → canonical_venue_id
│   └── cookie_selectors.yaml        # Known cookie modal CSS selectors
│
├── src/
│   ├── __init__.py
│   ├── main.py                      # CLI entry point (argparse)
│   ├── csv_io.py                    # Read Event Source CSV, write Event Table Update CSV
│   ├── venue_config.py              # Load venue mappings, aliases, settings
│   ├── browser.py                   # Playwright browser controller
│   ├── page_expander.py             # "Load more," scroll, paginate (free local work)
│   ├── cookie_dismisser.py          # Deterministic → AI-assisted cookie dismissal
│   ├── screenshot.py                # Full-page and chunked screenshot capture
│   ├── ai_vision/
│   │   ├── __init__.py
│   │   ├── base.py                  # VisionProvider abstract base class
│   │   ├── openai_provider.py
│   │   ├── anthropic_provider.py
│   │   ├── google_provider.py
│   │   ├── prompt_templates.py      # Structured prompts for list and detail pages
│   │   └── cost_tracker.py          # Per-call cost logging and budget enforcement
│   ├── detail_handler.py            # Click-through for event detail pages
│   ├── normalizer.py                # Venue name resolution (alias → fuzzy → AI)
│   ├── assembler.py                 # Merge AI output + lookups + constants
│   ├── validators.py                # MySQL format and field validation
│   ├── report.py                    # Summary, cost report, human review queue
│   └── logger.py                    # Structured logging setup
│
├── tests/
│   ├── test_csv_io.py
│   ├── test_normalizer.py
│   ├── test_assembler.py
│   ├── test_validators.py
│   ├── test_page_expander.py
│   ├── test_cookie_dismisser.py
│   └── fixtures/                    # Sample screenshots, AI responses, CSVs
│
├── logs/                            # Gitignored. Run logs, cost logs, review queues.
├── data/                            # Gitignored. Screenshots, AI responses.
│   ├── screenshots/
│   └── ai_responses/
│
└── scripts/
    ├── setup.sh                     # apt install + pip install + playwright install
    └── run.sh                       # Convenience wrapper
```

## Naming Conventions

### Code
- Python modules: `snake_case.py`
- Classes: `PascalCase` (e.g., `VisionProvider`, `CookieDismisser`)
- Functions and variables: `snake_case` (e.g., `extract_events`, `venue_id`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_EVENT_DURATION`)

### Configuration
- Environment variables: `UPPER_SNAKE_CASE` (e.g., `OPENAI_API_KEY`, `GOOGLE_AI_KEY`)
- YAML keys: `lower_snake_case` (e.g., `max_retry_count`)
- CSV headers: `lower_snake_case` (e.g., `venue_id`, `schedule_url`)
- CLI flags: `--kebab-case` (e.g., `--event-window-months`, `--dry-run`)

### Venue IDs
- All lowercase, underscore-separated: `sf_symphony`, `act_rembe`, `the_fillmore`
- Stable once assigned. Never rename a venue_id; use aliases for name variations.
- Must be unique across all venues.

### Files
- Log files: `{purpose}_{YYYYMMDD}_{HHMMSS}.{ext}`
- Screenshots: `{venue_id}_{YYYYMMDD}_{HHMMSS}_page_{N}.png`
- AI responses: `{venue_id}_{YYYYMMDD}_{HHMMSS}_response_{N}.json`

### Git
- Branches: `v1/feature-name`, `v2/feature-name`, `fix/description`, `docs/description`
- Commits: Conventional Commits — `feat:`, `fix:`, `docs:`, `refactor:`, `test:`
- Tags: semantic versioning — `v1.0.0`, `v1.1.0`, `v2.0.0`
- Main branch: `main` (always deployable for the current version)

## Tools and Dependencies

### System Packages (Debian apt)
```
python3  python3-pip  python3-venv  git  chromium
```

### Python Packages
```
# Browser automation
playwright>=1.40

# AI provider SDKs
openai>=1.30
anthropic>=0.30
google-genai>=1.0

# HTTP
httpx>=0.25

# Config and environment
python-dotenv>=1.0
pyyaml>=6.0

# Venue name matching
thefuzz>=0.20
python-Levenshtein>=0.25

# Development
pytest>=8.0
ruff>=0.4
```

### External Services

| Service | Purpose | Versions |
|---|---|---|
| Google AI Studio (Gemini) | Primary vision model | V1+ |
| OpenAI API (GPT-4o) | Fallback vision model | V1+ |
| Anthropic API (Claude) | Fallback vision model | V1+ |
| MySQL | Database read/write | V2+ |
| Gmail SMTP | Email notifications | V5 |

## Roadmap

Each version augments the codebase. No full rewrites — only new modules and CLI flags.

| Version | Input | Output | New Modules |
|---|---|---|---|
| V1 | Event Source CSV | Event Table Update CSV | Core pipeline |
| V2 | MySQL table | Event Table Update CSV | `db_reader.py` |
| V3 | MySQL table | MySQL events table | `db_writer.py` |
| V4 | MySQL table | New DB copy with lifecycle | `db_manager.py` |
| V5 | MySQL table (cron) | MySQL + email notifications | `emailer.py`, `cron_setup.sh` |

### Planned Enhancements (post-V1)
- `scheduled_refresh_date` column in events table for per-venue refresh cadence.
- Page hash change detection (SHA-256) to skip re-extraction when content hasn't changed.
- Adaptive scrape scheduling based on how far out each venue's events extend.

## Expectations and Boundaries

- This program runs quarterly, not in real-time. Optimize for correctness and cost, not speed.
- The 10-hour time limit is generous. Prefer fewer AI calls over faster completion.
- Always prefer free local processing (Playwright scrolling, clicking, deterministic matching) over paid AI calls.
- Never import data into the production database without human review. V1 produces CSV only. Even in V3+, a human must approve before going live.
- When in doubt about an extracted event (ambiguous time, unknown venue name, suspicious data), flag it for human review rather than guessing. A missing event is better than a wrong event in a production parking application.
- The venue alias table and cookie selector config are living documents. They grow with each run. Design all matching and dismissal logic to read from config, not hardcoded values.
