# Skill: Error Handling and Logging

Read this file when adding retry logic, fallback behavior, or modifying logging configuration.

## Retry and Fallback Rules

### Network / Browser Errors
- Retry up to **2 times** with exponential backoff, then skip the venue and log an ERROR.
- See also: `SKILLS/browser-automation.md` for browser-specific error handling.

### AI API Errors (rate limit, server error)
- Retry up to **3 times** with exponential backoff.
- Then try the next fallback provider (see provider priority in `SKILLS/ai-providers.md`).
- If all providers fail, skip the venue and log an ERROR.

### Authentication Walls / CAPTCHAs
- Detect, skip the venue, log as "requires manual intervention."

### Validation Failures
- Exclude the individual record, log to `human_review_*.csv`.
- **Never skip an entire venue because one event failed validation.**

### Budget Exceeded
- Switch to the cheapest provider, log a WARNING.
- **Never silently exceed the per-run spending cap.** See `SKILLS/ai-providers.md` for cost tracking details.

### Missing Config (API keys, venue mappings)
- CRITICAL log, abort the run immediately.

## Error Message Requirements

All errors must include:
- Timestamp
- Severity level
- Module name
- `venue_id` (when applicable)
- Human-readable message

Use structured JSON logging for machine parsing.

## Logging Configuration

Use Python's `logging` module with two handlers:

1. **Console**: human-readable format, level controlled by `--log-level` CLI flag (default: INFO).
2. **File**: JSON-structured format to `logs/run_YYYYMMDD_HHMMSS.log`, always at DEBUG level.

For code-level logging rules (no `print()`, use `logging` module only), see `SKILLS/code-quality.md`.

## Output Files (generated each run)

- `logs/cost_YYYYMMDD.log`: per-call AI cost tracking (provider, model, venue, tokens, cost).
- `logs/human_review_YYYYMMDD.csv`: events and venues needing human attention.
- `logs/summary_YYYYMMDD.txt`: run summary with counts, cost totals, and next steps.

## Sensitive Data

Never log API keys, passwords, or credentials. Mask sensitive values in error messages. See also: `SKILLS/security.md`.
