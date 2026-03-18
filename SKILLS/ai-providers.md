# Skill: AI Provider Rules

Read this file before modifying anything in `src/ai_vision/`.

## Core Principle

**Deterministic first, AI fallback.** Always try the cheapest local approach before spending AI tokens. This principle applies project-wide — see also `SKILLS/browser-automation.md` (cookie dismissal) and `SKILLS/venue-normalization.md` (name matching).

## VisionProvider Abstraction

**IMPORTANT**: The AI vision provider abstraction is a core architectural boundary.

- All providers must implement the `VisionProvider` base class in `src/ai_vision/base.py`.
- This enables A/B quality testing and instant provider switching for cost or quality reasons.
- Never call a provider SDK directly from pipeline code. All calls go through the abstraction.

## Provider Priority

- **Primary**: Google Gemini 2.5 Flash (cheapest).
- **Fallback 1**: OpenAI GPT-4o.
- **Fallback 2**: Anthropic Claude Sonnet.

## Logging Requirements

Every AI call must be logged with:
- Provider name
- Model identifier
- `venue_id`
- Token counts (input + output)
- Estimated cost
- Success or failure status

## Cost Tracking and Budget

- The `cost_tracker` module enforces a per-run spending cap defined in `config/settings.yaml`.
- If the cap is reached, the program switches to the cheapest available provider and logs a WARNING.
- It **never** silently exceeds the budget. See also: `SKILLS/error-handling.md` for budget-exceeded behavior.

## Response Storage

- AI responses must be saved as JSON to `data/ai_responses/` for debugging and regression testing.
- File naming: `{venue_id}_{YYYYMMDD}_{HHMMSS}_response_{N}.json`
- These files are gitignored and auto-cleaned after 30 days. See `SKILLS/security.md`.
