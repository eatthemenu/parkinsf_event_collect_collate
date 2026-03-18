"""OpenAI GPT-4o vision provider."""

import base64
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import openai

from .base import VisionProvider
from .cost_tracker import CostTracker, calculate_cost

logger = logging.getLogger(__name__)

_TOKENS_PER_IMAGE = 1105  # high-detail 1280x900

MODEL_IDS: dict[str, str] = {
    "gpt-4o": "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
    "gpt-4.1": "gpt-4.1",
}


class OpenAIProvider(VisionProvider):
    """OpenAI GPT-4o vision provider (fallback).

    Uses the async openai SDK with base64-encoded image_url blocks in the
    chat completion message payload.

    Example:
        provider = OpenAIProvider(
            api_key="sk-...",
            model_key="gpt-4o",
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
        """Initialize the OpenAIProvider.

        Args:
            api_key: OpenAI API key.
            model_key: One of 'gpt-4o', 'gpt-4o-mini', or 'gpt-4.1'.
            cost_tracker: Shared CostTracker for cost accumulation.
            data_dir: Base directory for saving raw AI responses.

        Raises:
            ValueError: If model_key is not recognized.
        """
        if model_key not in MODEL_IDS:
            raise ValueError(f"Unknown model_key '{model_key}'. Must be one of: {list(MODEL_IDS)}")
        self._model_key = model_key
        self._model_id = MODEL_IDS[model_key]
        self._cost_tracker = cost_tracker
        self._data_dir = data_dir
        self._client = openai.AsyncOpenAI(api_key=api_key)

    async def extract_events(
        self,
        screenshots: list[bytes],
        prompt: str,
        venue_context: dict,
    ) -> list[dict]:
        """Send screenshot(s) and prompt to GPT-4o, return structured event data.

        Encodes each screenshot as base64 and builds a user message with
        image_url blocks followed by a text block.

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

        # Build user message content list
        content: list[dict] = []
        for img_bytes in screenshots:
            b64 = base64.b64encode(img_bytes).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{b64}",
                        "detail": "high",
                    },
                }
            )
        content.append({"type": "text", "text": prompt})

        messages: list[dict] = [{"role": "user", "content": content}]

        try:
            response = await self._client.chat.completions.create(
                model=self._model_id,
                messages=messages,
                max_tokens=4096,
            )
        except Exception as exc:
            logger.error(
                "OpenAIProvider API error for venue_id=%s model=%s: %s",
                venue_id,
                self._model_id,
                exc,
                exc_info=True,
            )
            self._record_failed_call(venue_id, now, str(exc))
            return []

        raw_text: str = ""
        if response.choices and response.choices[0].message.content:
            raw_text = response.choices[0].message.content

        # Determine token counts from response usage
        input_tokens: int = _TOKENS_PER_IMAGE * len(screenshots) + 500
        output_tokens: int = max(1, len(raw_text) // 4)
        usage = getattr(response, "usage", None)
        if usage is not None:
            prompt_tokens = getattr(usage, "prompt_tokens", None)
            completion_tokens = getattr(usage, "completion_tokens", None)
            if prompt_tokens is not None:
                input_tokens = int(prompt_tokens)
            if completion_tokens is not None:
                output_tokens = int(completion_tokens)

        estimated_cost = calculate_cost(self._model_key, input_tokens, output_tokens)

        # Save raw response to disk
        response_dir = self._data_dir / "ai_responses"
        response_dir.mkdir(parents=True, exist_ok=True)
        response_path = response_dir / f"{venue_id}_{timestamp_str}_response_openai.json"
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
        logger.info("OpenAIProvider extracted %d events for venue_id=%s", len(events), venue_id)
        return events

    def _record_failed_call(self, venue_id: str, timestamp: datetime, error_message: str) -> None:
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

        Uses a fixed per-image token estimate for high-detail mode plus
        a typical prompt and output token overhead.

        Args:
            screenshots: List of PNG image bytes.

        Returns:
            Estimated cost in USD.
        """
        # Estimate: image tokens (high-detail) + ~500 prompt tokens, ~300 output tokens
        input_tokens = (_TOKENS_PER_IMAGE * len(screenshots)) + 500
        output_tokens = 300
        return calculate_cost(self._model_key, input_tokens, output_tokens)

    def get_provider_name(self) -> str:
        """Return the short provider name.

        Returns:
            'openai'
        """
        return "openai"

    def get_model_name(self) -> str:
        """Return the full model ID being used.

        Returns:
            The OpenAI model ID string, e.g. 'gpt-4o'.
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
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _parse_events_from_text(raw_text: str, venue_id: str, model_id: str) -> list[dict]:
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
            "OpenAIProvider JSON parse error for venue_id=%s model=%s: %s | raw=%r",
            venue_id,
            model_id,
            exc,
            raw_text[:200],
        )
        return []

    if not isinstance(parsed, dict) or "events" not in parsed:
        logger.error(
            "OpenAIProvider response missing 'events' key for venue_id=%s. parsed=%r",
            venue_id,
            str(parsed)[:200],
        )
        return []

    events = parsed["events"]
    if not isinstance(events, list):
        logger.error(
            "OpenAIProvider 'events' is not a list for venue_id=%s. type=%s",
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
        logger.debug("OpenAIProvider saved raw response to %s", path)
    except OSError as exc:
        logger.warning("OpenAIProvider could not save raw response to %s: %s", path, exc)
