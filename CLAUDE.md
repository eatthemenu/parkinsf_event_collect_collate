This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Project: Event Schedule Aggregator

## Purpose

This program reads SF Bay Area venue show schedule web pages using AI multimodal vision models and produces structured CSV data for import into a production MySQL events table. It uses headless browser screenshots — not traditional web scraping — so that layout and style changes on venue websites do not break data collection.

The program feeds a live production application that displays parking scarcity information around event venues. Bad data has real user impact.

## Key Design Principle

**Deterministic first, AI fallback.** Always try the cheapest local approach before spending AI tokens. This applies to cookie modal dismissal, venue name matching, and (in future versions) page change detection via hashing. See also: `SKILLS/ai-providers.md`, `SKILLS/venue-normalization.md`, `SKILLS/browser-automation.md`.

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

## Development Workflow

1. Before making changes, create and checkout a branch named per the branch conventions below.
2. Write or update tests for any new or changed functionality.
3. Run `ruff check .` and `ruff format --check .` — fix all issues before committing.
4. Run `pytest` and ensure all tests pass.
5. Write commit messages using Conventional Commits format.
6. Commit to the feature branch. Do not commit directly to `main`.
7. After review and testing, merge to `main` and tag if appropriate.

## Skill Files

Read the relevant skill file(s) BEFORE making changes. If a task spans multiple areas, read all applicable files.

| Skill File | Read When Touching | Covers |
|---|---|---|
| `SKILLS/code-quality.md` | Any source code in `src/` | PEP 8, type hints, docstrings, logging, path handling |
| `SKILLS/ai-providers.md` | `src/ai_vision/` | VisionProvider abstraction, cost tracking, budget caps |
| `SKILLS/browser-automation.md` | `browser.py`, `page_expander.py`, `cookie_dismisser.py`, `screenshot.py` | Playwright rules, cookies, screenshots, page expansion |
| `SKILLS/venue-normalization.md` | `normalizer.py`, venue config CSVs | Alias → fuzzy → AI matching, site types, venue identifiers |
| `SKILLS/validation-and-schema.md` | `validators.py`, `assembler.py`, `csv_io.py` | MySQL schema, field rules, dedup, quality gates |
| `SKILLS/error-handling.md` | Any retry/fallback logic, logging config | Retries, backoff, budget enforcement, log formats |
| `SKILLS/testing.md` | `tests/`, running test suites | Test levels, fixtures, quality gates, provider eval |
| `SKILLS/security.md` | `.env`, credentials, deployment | Secrets management, permissions, gitignore, cleanup |

## File Organization

```
event-aggregator/
├── CLAUDE.md
├── SKILLS/
│   ├── code-quality.md
│   ├── ai-providers.md
│   ├── browser-automation.md
│   ├── venue-normalization.md
│   ├── validation-and-schema.md
│   ├── error-handling.md
│   ├── testing.md
│   └── security.md
├── README.md
├── pyproject.toml
├── requirements.txt
├── .env.example
├── .gitignore
│
├── config/
│   ├── settings.yaml                    # Timeouts, retries, model defaults, event window
│   ├── venue_to_lat_lon_mapping.csv     # location_label → lat, lon, radius, icon, garages per venue
│   ├── venue_aliases.csv                # alias string → location_label
│   └── cookie_selectors.yaml            # Known cookie modal CSS selectors
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

### Venue Identifiers

There are two distinct venue identifier concepts. See `SKILLS/venue-normalization.md` for full details.

**`venue_id`** — used in the Event Source CSV (`VenueSource`) to identify which website to scrape:
- All lowercase, underscore-separated: `sf_symphony`, `act_rembe`, `the_fillmore`
- Stable once assigned. Never rename a venue_id; use aliases for name variations.
- Must be unique across all event sources.
- Does **not** appear in the mapping file or the output CSV.

**`location_label`** — the canonical display name used as the mapping key and in the output CSV:
- Human-readable display name matching exactly what appears in `config/venue_to_lat_lon_mapping.csv`.
- Examples: `"ACT Toni Rembe Theater"`, `"Davies Symphony Hall"`, `"The Fillmore"`
- The normalizer resolves extracted venue names to a `location_label`.
- Written directly to the MySQL events table.

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
