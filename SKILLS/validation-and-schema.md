# Skill: Validation Rules and MySQL Schema

Read this file before modifying `validators.py`, `assembler.py`, or `csv_io.py`.

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
| `icon` | VARCHAR | 255 | Event Source CSV `icon` column (if set), else venue mappings lookup |
| `affected_garages_ids` | VARCHAR | 1024 | Venue mappings lookup |
| `affected_areas` | VARCHAR | 256 | Constant: `NULL` |

**Critical**: `event_start_time` is the show start time, NOT the door open time. The AI prompt must explicitly distinguish these. If only a door time is available and no show time, log the event for human review rather than guessing.

## Per-Field Validation Rules

Every event record must pass all validators before being written to the output CSV. Records that fail are excluded and logged to `human_review_*.csv`. See `SKILLS/error-handling.md` for logging format.

- `label`: non-empty, ≤ 255 characters, whitespace trimmed.
- `location_label`: must resolve to a canonical venue via the normalizer (see `SKILLS/venue-normalization.md`), ≤ 255 characters.
- `latitude`: valid decimal, within 37.0–38.0 (SF Bay Area).
- `longitude`: valid decimal, within -123.0 to -121.5 (SF Bay Area).
- `radius`: positive number.
- `event_start_date`: valid `YYYY-MM-DD`, must be ≥ today, must be ≤ today + 6 months.
- `event_start_time`: valid `HH:MM:SS` 24-hour, reasonable range 06:00:00–23:59:59.
- `web`: starts with `https://`, ≤ 255 characters.
- `icon`: non-empty, ≤ 255 characters.
- `affected_garages_ids`: matches comma-separated integers pattern or empty, ≤ 1024 characters.

## Deduplication

Records with identical (`label`, `location_label`, `event_start_date`, `event_start_time`) are duplicates. Keep the record with more complete data.

## Quality Gates (every run)

All of these must be true before the output CSV is used:

1. All venues in the input were attempted (none silently dropped).
2. Event count per venue is plausible (≥ 1 for active venues, < 500).
3. All `event_start_date` values are future dates within the configured window.
4. All `event_start_time` values are valid 24-hour format.
5. All `location_label` values resolved to canonical venue location labels.
6. All coordinates are within the SF Bay Area bounding box.
7. No duplicate (`label`, `location_label`, `date`, `time`) tuples in output.
8. Total AI cost is within the per-run budget. See `SKILLS/ai-providers.md`.
9. Human review queue is < 15% of total events extracted.
