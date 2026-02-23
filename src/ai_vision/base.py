"""Abstract base class for AI vision providers."""
from abc import ABC, abstractmethod


class VisionProvider(ABC):
    """Abstract interface for AI vision model providers.

    All providers must implement this interface so they can be swapped
    via a CLI flag with no changes to pipeline code.
    """

    @abstractmethod
    async def extract_events(
        self,
        screenshots: list[bytes],
        prompt: str,
        venue_context: dict,
    ) -> list[dict]:
        """Send screenshot(s) + prompt, return structured event data.

        Args:
            screenshots: List of PNG image bytes (one per page chunk).
            prompt: Extraction prompt from prompt_templates.
            venue_context: Dict with venue_id, venue_name, site_type,
                event_window_start, event_window_end.

        Returns:
            List of RawExtractedEvent dicts.
        """

    @abstractmethod
    def estimate_cost(self, screenshots: list[bytes]) -> float:
        """Estimate cost in USD before sending.

        Args:
            screenshots: List of PNG image bytes.

        Returns:
            Estimated cost in USD.
        """

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return short provider name (e.g. 'google', 'openai', 'anthropic')."""

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the model ID being used."""
