"""AI vision provider package.

Exports:
    VisionProvider: Abstract base class.
    GoogleProvider: Gemini provider (primary).
    OpenAIProvider: GPT-4o provider (fallback).
    AnthropicProvider: Claude provider (fallback).
    CostTracker: Per-call cost tracking.
    get_provider: Factory function to instantiate a provider by name.
"""

from pathlib import Path

from .anthropic_provider import AnthropicProvider
from .base import VisionProvider
from .cost_tracker import CostTracker
from .google_provider import GoogleProvider
from .openai_provider import OpenAIProvider

__all__ = [
    "VisionProvider",
    "GoogleProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "CostTracker",
    "get_provider",
]


def get_provider(
    provider_name: str,
    cost_tracker: CostTracker,
    data_dir: Path,
    *,
    google_api_key: str = "",
    openai_api_key: str = "",
    anthropic_api_key: str = "",
) -> VisionProvider:
    """Instantiate a VisionProvider by name.

    Args:
        provider_name: One of: gemini-flash, gemini-pro, gpt-4o, gpt-4o-mini,
            gpt-4.1, claude-sonnet, claude-opus.
        cost_tracker: Shared CostTracker instance.
        data_dir: Base data directory for saving AI responses.
        google_api_key: Google AI API key.
        openai_api_key: OpenAI API key.
        anthropic_api_key: Anthropic API key.

    Returns:
        Configured VisionProvider instance.

    Raises:
        ValueError: If provider_name is unrecognized.
        ValueError: If required API key is empty for the chosen provider.
    """
    if provider_name in ("gemini-flash", "gemini-pro"):
        if not google_api_key:
            raise ValueError(f"GOOGLE_AI_KEY is required for provider '{provider_name}'")
        return GoogleProvider(google_api_key, provider_name, cost_tracker, data_dir)
    elif provider_name in ("gpt-4o", "gpt-4o-mini", "gpt-4.1"):
        if not openai_api_key:
            raise ValueError(f"OPENAI_API_KEY is required for provider '{provider_name}'")
        return OpenAIProvider(openai_api_key, provider_name, cost_tracker, data_dir)
    elif provider_name in ("claude-sonnet", "claude-opus"):
        if not anthropic_api_key:
            raise ValueError(f"ANTHROPIC_API_KEY is required for provider '{provider_name}'")
        return AnthropicProvider(anthropic_api_key, provider_name, cost_tracker, data_dir)
    else:
        raise ValueError(f"Unknown provider: '{provider_name}'")
