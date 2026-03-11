# Skill: Venue Name Normalization Rules

Read this file before modifying `normalizer.py` or any venue config CSVs (`venue_to_lat_lon_mapping.csv`, `venue_aliases.csv`).

## The Problem

Venue names on websites are inconsistent. The same venue may appear as "ACT Geary Theater," "Toni Rembe Theater," or "ACT Rembe Theater."

## Three-Tier Resolution (in priority order)

Always resolve names using this pipeline. Each tier is tried only if the previous one fails. This follows the project-wide "deterministic first, AI fallback" principle — see `SKILLS/ai-providers.md`.

1. **Alias table lookup** (`config/venue_aliases.csv`): exact match against known aliases. Free and deterministic.
2. **Fuzzy matching** (`thefuzz`, threshold ≥ 85): only if alias lookup finds no match. Log the match and score as a WARNING.
3. **AI-assisted** (cheap text model call): only if fuzzy matching scores below threshold. Log result for human review. AI call must follow `SKILLS/ai-providers.md` logging and cost tracking rules.

## Growing the Alias Table

When a new alias is discovered (via fuzzy or AI match), log it to `human_review_*.csv` with a suggestion to add it to the alias table. Over time, Tiers 2 and 3 should be needed less frequently.

The alias table is a living document — design matching logic to read from config, not hardcoded values.

## Venue Site Types

The Event Source CSV includes a `site_type` column that changes extraction behavior:

- **`single_venue`**: The website only lists events at one location (e.g., Curran Theater). The `location_label` is inferred from the venue config; the AI does not need to extract it per event.
- **`multi_venue`**: The website lists events across multiple sub-venues (e.g., ACT lists shows at Toni Rembe and Strand). The AI must extract `location_label` for each event. The Event Source CSV has separate rows per sub-venue, possibly pointing to the same base URL.

## Venue Identifiers

There are two distinct identifier concepts in the pipeline:

### `venue_id` (Event Source CSV only)
- Used in `VenueSource` to identify which website to scrape.
- All lowercase, underscore-separated: `sf_symphony`, `act_rembe`, `the_fillmore`
- Stable once assigned. **Never rename a venue_id**; use aliases for name variations.
- Must be unique across all event sources.
- Does **not** appear in the mapping file or the output CSV.

### `location_label` (mapping key and output field)
- The canonical display name for a venue (e.g., `"ACT Toni Rembe Theater"`, `"Davies Symphony Hall"`).
- Serves as the primary key in `config/venue_to_lat_lon_mapping.csv`.
- Written directly to the `location_label` column in the output CSV and MySQL events table.
- The normalizer resolves extracted venue names to a `location_label`.
- `venue_aliases.csv` maps alias strings → `location_label` values.

### Icon Overrides
Some physical venues host events from multiple producers, each with a different icon
(e.g. War Memorial Opera House: SF Opera, SF Ballet, SHN). In these cases:
- `venue_to_lat_lon_mapping.csv` may have duplicate `location_label` rows — one per producer icon. The last row loaded becomes the default.
- The Event Source CSV has an optional `icon` column. Set it on the relevant source row to override the mapping default for that producer.
- The assembler uses `VenueSource.icon` when non-empty; otherwise falls back to `VenueMapping.icon`.
