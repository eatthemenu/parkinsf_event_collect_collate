# Skill: Code Quality Standards

Read this file before writing or modifying any source code in `src/`.

## Style and Formatting

- Follow PEP 8, enforced by `ruff`. Max line length: 99 characters.
- Run `ruff check .` and `ruff format --check .` before committing. Fix all issues.

## Type Hints

- Required on all function signatures and return types.

## Docstrings

- Google-style docstrings required on all public functions and classes.

## Async

- Use `async`/`await` for all Playwright browser operations. See also: `SKILLS/browser-automation.md`.

## Path Handling

- Use `pathlib.Path` for all file system paths. Never use raw strings for paths.

## Logging

- Use the `logging` module exclusively for output. Never use bare `print()` in `src/`.
- For log format and handler details, see `SKILLS/error-handling.md`.

## Configuration

- All configuration values must come from `config/settings.yaml`, `config/venue_*.csv`, or environment variables.
- No hardcoded URLs, API keys, thresholds, or magic numbers in source code.

## Architectural Boundaries

- All AI provider calls must go through the `VisionProvider` abstract base class. Never call a provider SDK directly from pipeline code. See `SKILLS/ai-providers.md` for full provider rules.
