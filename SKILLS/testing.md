# Skill: Testing

Read this file before writing or running tests in `tests/`.

## Test Levels

### Unit Tests
- Cover: validators, normalizer, CSV I/O, date parsing, cost tracker.
- Run with: `pytest`
- No network or AI calls. Use fixtures in `tests/fixtures/`.

### Regression Tests
- Save real AI responses as JSON fixtures in `tests/fixtures/`.
- Re-test the parsing and assembly pipeline against saved responses without making API calls.
- This catches regressions in post-processing logic.

### Integration Tests
- Run browser + cookie dismissal + page expansion against a live venue URL with `--dry-run` (no AI calls).
- Validates that Playwright can load and interact with the site.
- For browser rules, see `SKILLS/browser-automation.md`.

### Provider Evaluation
- Run the full pipeline against the same venues with different `--provider` flags.
- Compare output CSVs. Review cost logs.
- Do this quarterly.
- For provider details, see `SKILLS/ai-providers.md`.

### End-to-End
- Full run with all venues.
- Human review of output CSV required before any production import.

## Quality Gates

These must all be true before the output CSV is used. See `SKILLS/validation-and-schema.md` for the full list of 9 quality gate checks.

## Development Workflow Reminder

1. Write or update tests for any new or changed functionality.
2. Run `ruff check .` and `ruff format --check .` — fix all issues.
3. Run `pytest` — all tests must pass.
4. See `SKILLS/code-quality.md` for code standards that apply to test code too.
