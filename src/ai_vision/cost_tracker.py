"""Per-call AI cost tracking and budget enforcement."""

import logging

logger = logging.getLogger(__name__)

# Cost per 1M tokens (input, output) in USD
COST_PER_MILLION_TOKENS: dict[str, tuple[float, float]] = {
    "gemini-flash": (0.075, 0.30),
    "gemini-pro": (1.25, 5.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "claude-sonnet": (3.00, 15.00),
    "claude-opus": (15.00, 75.00),
}


def calculate_cost(provider_key: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate estimated cost for an API call.

    Args:
        provider_key: The model/provider key matching COST_PER_MILLION_TOKENS,
            e.g. 'gemini-flash', 'gpt-4o', 'claude-sonnet'.
        input_tokens: Number of input tokens consumed.
        output_tokens: Number of output tokens consumed.

    Returns:
        Estimated cost in USD.

    Raises:
        KeyError: If provider_key is not found in COST_PER_MILLION_TOKENS.
    """
    input_rate, output_rate = COST_PER_MILLION_TOKENS[provider_key]
    input_cost = (input_tokens / 1_000_000) * input_rate
    output_cost = (output_tokens / 1_000_000) * output_rate
    return input_cost + output_cost


class CostTracker:
    """Tracks per-call AI costs and enforces a per-run spending cap.

    Example:
        tracker = CostTracker(max_cost_usd=1.00)
        tracker.record_call(cost_record)
        if tracker.is_over_budget():
            raise RuntimeError("Budget exceeded")
    """

    def __init__(self, max_cost_usd: float) -> None:
        """Initialize the cost tracker with a spending cap.

        Args:
            max_cost_usd: Maximum allowed spending for this run, in USD.
        """
        self._max_cost_usd: float = max_cost_usd
        self._total_cost: float = 0.0
        self._records: list[dict] = []

    def record_call(self, cost_record: dict) -> None:
        """Record a completed API call and accumulate cost.

        Logs the provider, model, venue_id, estimated_cost_usd, and whether the
        run is now over budget.

        Args:
            cost_record: A CostRecord dict containing at minimum:
                provider, model, venue_id, estimated_cost_usd, success,
                input_tokens, output_tokens, timestamp, error_message.
        """
        self._records.append(cost_record)
        call_cost = float(cost_record.get("estimated_cost_usd", 0.0))
        self._total_cost += call_cost

        provider = cost_record.get("provider", "unknown")
        model = cost_record.get("model", "unknown")
        venue_id = cost_record.get("venue_id", "unknown")
        over_budget = self.is_over_budget()

        logger.info(
            "AI call recorded: provider=%s model=%s venue_id=%s cost=$%.6f "
            "total=$%.6f over_budget=%s",
            provider,
            model,
            venue_id,
            call_cost,
            self._total_cost,
            over_budget,
        )

        if over_budget:
            logger.warning(
                "Budget cap exceeded: total=$%.6f max=$%.6f",
                self._total_cost,
                self._max_cost_usd,
            )

    def get_total_cost(self) -> float:
        """Return the total accumulated cost across all recorded calls.

        Returns:
            Total cost in USD.
        """
        return self._total_cost

    def is_over_budget(self) -> bool:
        """Check whether the accumulated cost has exceeded the cap.

        Returns:
            True if total cost >= max_cost_usd, otherwise False.
        """
        return self._total_cost >= self._max_cost_usd

    def get_remaining_budget(self) -> float:
        """Return how much budget remains before the cap is hit.

        Returns:
            Remaining budget in USD. May be negative if over budget.
        """
        return self._max_cost_usd - self._total_cost

    def get_all_records(self) -> list[dict]:
        """Return a copy of all recorded CostRecord dicts.

        Returns:
            List of CostRecord dicts in the order they were recorded.
        """
        return list(self._records)

    def get_cheapest_provider_name(self) -> str:
        """Return the name of the cheapest available provider.

        Returns:
            'gemini-flash' — always the cheapest option.
        """
        return "gemini-flash"
