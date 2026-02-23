"""Google Gemini vision provider."""
import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from google import genai
from google.genai import types

from .base import VisionProvider
from .cost_tracker import CostTracker, calculate_cost

logger = logging.getLogger(__name__)

# Approximate tokens per 1280x900 screenshot for Gemini
_TOKENS_PER_IMAGE = 800

MODEL_IDS: dict[str, str] = {
    "gemini-flash": "gemini-2.5-flash-preview-04-17",
    "gemini-pro": "gemini-2.0-flash",
}


class GoogleProvider(VisionProvider):
    """Google Gemini vision provider (primary — cheapest).

    Uses the google-genai synchronous client wrapped in asyncio.to_thread
    because the google-genai SDK does not provide a fully async interface.

    Example:
        provider = GoogleProvider(
            api_key="AIza...",
            model_key="gemini-flash",
            cost_tracker=tracker,
            data_dir=Path("/data"),
        )
        events = await provider.extract_events(screenshots, prompt, venue_context)
    """

    def __init__(
        self,
        api_key: str,
        model_key: str,
        cost_tracker: CostTracker,
        data_dir: Path,
    ) -> None:
        """Initialize the GoogleProvider.

        Args:
            api_key: Google AI API key.
            model_key: One of 'gemini-flash' or 'gemini-pro'.
            cost_tracker: Shared CostTracker for cost accumulation.
            data_dir: Base directory for saving raw AI responses.

        Raises:
            ValueError: If model_key is not recognized.
        """
        if model_key not in MODEL_IDS:
            raise ValueError(
                f"Unknown model_key '{model_key}'. Must be one of: {list(MODEL_IDS)}"
            )
        self._model_key = model_key
        self._model_id = MODEL_IDS[model_key]
        self._cost_tracker = cost_tracker
        self._data_dir = data_dir
        self._client = genai.Client(api_key=api_key)

    async def extract_events(
        self,
        screenshots: list[bytes],
        prompt: str,
        venue_context: dict,
    ) -> list[dict]:
        """Send screenshot(s) and prompt to Gemini, return structured event data.

        Runs the synchronous genai client in a thread to avoid blocking the
        event loop. Saves the raw response JSON to disk for audit purposes.

        Args:
            screenshots: List of PNG image bytes, one per page chunk.
            prompt: Extraction prompt from prompt_templates.
            venue_context: Dict with venue_id, venue_name, site_type,
                event_window_start, event_window_end.

        Returns:
            List of RawExtractedEvent dicts. Returns empty list on error.
        """
        venue_id: str = venue_context.get("venue_id", "unknown")
        now = datetime.now(UTC)
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")

        def _run_sync() -> types.GenerateContentResponse:
            contents: list = []
            for img_bytes in screenshots:
                contents.append(
                    types.Part.from_bytes(data=img_bytes, mime_type="image/png")
                )
            contents.append(types.Part.from_text(text=prompt))
            return self._client.models.generate_content(
                model=self._model_id,
                contents=contents,
            )

        try:
            response: types.GenerateContentResponse = await asyncio.to_thread(_run_sync)
        except Exception as exc:
            logger.error(
                "GoogleProvider API error for venue_id=%s model=%s: %s",
                venue_id,
                self._model_id,
                exc,
                exc_info=True,
            )
            self._record_failed_call(venue_id, now, str(exc))
            return []

        raw_text: str = response.text if response.text else ""

        # Determine token counts from usage_metadata when available
        input_tokens: int = _TOKENS_PER_IMAGE * len(screenshots)
        output_tokens: int = 0
        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            prompt_tokens = getattr(usage, "prompt_token_count", None)
            candidate_tokens = getattr(usage, "candidates_token_count", None)
            if prompt_tokens is not None:
                input_tokens = int(prompt_tokens)
            if candidate_tokens is not None:
                output_tokens = int(candidate_tokens)
        else:
            # Rough estimate: ~4 chars per token
            output_tokens = max(1, len(raw_text) // 4)

        estimated_cost = calculate_cost(self._model_key, input_tokens, output_tokens)

        # Save raw response to disk
        response_dir = self._data_dir / "ai_responses"
        response_dir.mkdir(parents=True, exist_ok=True)
        response_path = response_dir / f"{venue_id}_{timestamp_str}_response_google.json"
        _save_raw_response(response_path, raw_text, venue_id, self._model_id, now)

        # Record cost
        cost_record: dict = {
            "timestamp": now.isoformat(),
            "provider": self.get_provider_name(),
            "model": self._model_id,
            "venue_id": venue_id,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": estimated_cost,
            "success": True,
            "error_message": None,
        }
        self._cost_tracker.record_call(cost_record)

        # Parse events from response
        events = _parse_events_from_text(raw_text, venue_id, self._model_id)
        logger.info(
            "GoogleProvider extracted %d events for venue_id=%s", len(events), venue_id
        )
        return events

    def _record_failed_call(
        self, venue_id: str, timestamp: datetime, error_message: str
    ) -> None:
        """Record a failed API call with zero cost.

        Args:
            venue_id: The venue identifier for the failed call.
            timestamp: UTC datetime of the call attempt.
            error_message: Error description string.
        """
        cost_record: dict = {
            "timestamp": timestamp.isoformat(),
            "provider": self.get_provider_name(),
            "model": self._model_id,
            "venue_id": venue_id,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_usd": 0.0,
            "success": False,
            "error_message": error_message,
        }
        self._cost_tracker.record_call(cost_record)

    def estimate_cost(self, screenshots: list[bytes]) -> float:
        """Estimate cost in USD for sending the given screenshots.

        Uses a fixed per-image token estimate plus a typical prompt overhead.

        Args:
            screenshots: List of PNG image bytes.

        Returns:
            Estimated cost in USD.
        """
        # Estimate: image tokens + ~500 prompt tokens, ~300 output tokens
        input_tokens = (_TOKENS_PER_IMAGE * len(screenshots)) + 500
        output_tokens = 300
        return calculate_cost(self._model_key, input_tokens, output_tokens)

    def get_provider_name(self) -> str:
        """Return the short provider name.

        Returns:
            'google'
        """
        return "google"

    def get_model_name(self) -> str:
        """Return the full model ID being used.

        Returns:
            The Gemini model ID string, e.g. 'gemini-2.5-flash-preview-04-17'.
        """
        return self._model_id


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences from a string.

    Handles both ```json ... ``` and ``` ... ``` variants.

    Args:
        text: Raw text possibly containing markdown code fences.

    Returns:
        Text with code fences stripped.
    """
    text = text.strip()
    # Remove ```json or ``` at start, ``` at end
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _parse_events_from_text(
    raw_text: str, venue_id: str, model_id: str
) -> list[dict]:
    """Parse RawExtractedEvent dicts from AI response text.

    Args:
        raw_text: The raw text response from the AI model.
        venue_id: Venue identifier for logging context.
        model_id: Model identifier for logging context.

    Returns:
        List of RawExtractedEvent dicts, or empty list on parse failure.
    """
    cleaned = _strip_markdown_fences(raw_text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error(
            "GoogleProvider JSON parse error for venue_id=%s model=%s: %s | raw=%r",
            venue_id,
            model_id,
            exc,
            raw_text[:200],
        )
        return []

    if not isinstance(parsed, dict) or "events" not in parsed:
        logger.error(
            "GoogleProvider response missing 'events' key for venue_id=%s. parsed=%r",
            venue_id,
            str(parsed)[:200],
        )
        return []

    events = parsed["events"]
    if not isinstance(events, list):
        logger.error(
            "GoogleProvider 'events' is not a list for venue_id=%s. type=%s",
            venue_id,
            type(events).__name__,
        )
        return []

    return events


def _save_raw_response(
    path: Path, raw_text: str, venue_id: str, model_id: str, timestamp: datetime
) -> None:
    """Save raw AI response text to a JSON file on disk.

    Args:
        path: Full file path to write.
        raw_text: The raw text from the AI response.
        venue_id: Venue identifier for metadata.
        model_id: Model identifier for metadata.
        timestamp: UTC timestamp of the call.
    """
    payload = {
        "venue_id": venue_id,
        "model": model_id,
        "timestamp": timestamp.isoformat(),
        "raw_response": raw_text,
    }
    try:
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.debug("GoogleProvider saved raw response to %s", path)
    except OSError as exc:
        logger.warning("GoogleProvider could not save raw response to %s: %s", path, exc)
