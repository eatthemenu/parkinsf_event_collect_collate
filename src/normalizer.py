"""Venue name normalizer: alias table -> fuzzy match -> AI text fallback.

Resolves raw venue name strings (extracted by AI from web pages) to canonical
venue IDs using three tiers, cheapest first:
  Tier 1 -- Exact alias lookup (free)
  Tier 2 -- Fuzzy match via thefuzz (free, threshold configurable)
  Tier 3 -- AI text call (cheap, logs for human review)
"""

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime

from thefuzz import process as fuzz_process

from .venue_config import VenueMapping

logger = logging.getLogger(__name__)


class VenueNormalizer:
    """Resolves raw venue name strings to canonical venue IDs.

    Uses three resolution tiers in order of cost:
      1. Exact alias lookup (O(1) dict lookup).
      2. Fuzzy string match via thefuzz.
      3. AI text call for ambiguous or novel names.

    Attributes:
        aliases: Lowercase alias string -> canonical venue_id mapping.
        mappings: venue_id -> VenueMapping lookup.
        fuzzy_threshold: Minimum thefuzz score (0-100) to accept a fuzzy match.
        ai_text_func: Optional callable for Tier 3 AI-assisted resolution.
        human_review_queue: Optional list to which HumanReviewItem dicts are appended.
    """

    def __init__(
        self,
        aliases: dict[str, str],
        mappings: dict[str, VenueMapping],
        fuzzy_threshold: int = 85,
        ai_text_func: Callable[[str, list[str]], str | None] | None = None,
        human_review_queue: list | None = None,
    ) -> None:
        """Initialise the VenueNormalizer.

        Args:
            aliases: Lowercase alias string -> canonical_venue_id mapping.
            mappings: venue_id -> VenueMapping lookup dict.
            fuzzy_threshold: Minimum thefuzz score (0-100) to accept a fuzzy
                match. Defaults to 85.
            ai_text_func: Optional callable taking (extracted_name,
                canonical_names_list) and returning a venue_id string or None.
                Used as Tier 3 fallback.
            human_review_queue: Optional list to which HumanReviewItem dicts
                are appended for fuzzy (score < 95) and AI-resolved matches, and
                all unresolved names.
        """
        self.aliases = aliases
        self.mappings = mappings
        self.fuzzy_threshold = fuzzy_threshold
        self.ai_text_func = ai_text_func
        self.human_review_queue = human_review_queue

        # Pre-build the list of all alias keys for fuzzy matching.
        self._alias_keys: list[str] = list(aliases.keys())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def normalize(self, extracted_name: str) -> tuple[str | None, str]:
        """Resolve an extracted venue name to a canonical venue_id.

        Tries resolution tiers in order:
          - Tier 1: exact alias lookup (case-insensitive).
          - Tier 2: fuzzy string match against all alias keys.
          - Tier 3: AI text function if configured.

        Args:
            extracted_name: Raw venue name string from AI extraction.

        Returns:
            A 2-tuple of (canonical_venue_id | None, method_used) where
            method_used is one of: "alias", "fuzzy", "ai", "unknown".
        """
        if not extracted_name or not extracted_name.strip():
            logger.warning("normalize() called with empty extracted_name; returning unknown")
            self._append_unresolved("", "empty extracted_name")
            return (None, "unknown")

        # ------------------------------------------------------------------
        # Tier 1: Exact alias lookup
        # ------------------------------------------------------------------
        lowered = extracted_name.strip().lower()
        if lowered in self.aliases:
            venue_id = self.aliases[lowered]
            logger.debug("Tier 1 alias match: %r -> %r", extracted_name, venue_id)
            return (venue_id, "alias")

        # ------------------------------------------------------------------
        # Tier 2: Fuzzy match
        # ------------------------------------------------------------------
        if self._alias_keys:
            result = fuzz_process.extractOne(
                extracted_name,
                self._alias_keys,
                score_cutoff=self.fuzzy_threshold,
            )
            if result is not None:
                matched_alias, score = result[0], result[1]
                venue_id = self.aliases[matched_alias]
                logger.warning(
                    "Tier 2 fuzzy match: %r -> alias %r -> venue_id %r (score=%d)",
                    extracted_name,
                    matched_alias,
                    venue_id,
                    score,
                )
                # Imperfect fuzzy matches (score < 95) need human review.
                if score < 95:
                    self._append_human_review(
                        venue_id=venue_id,
                        issue_type="name_mismatch_fuzzy_resolved",
                        severity="low",
                        details=(
                            f"Fuzzy match: extracted={extracted_name!r} matched "
                            f"alias={matched_alias!r} (score={score})"
                        ),
                        suggested_action=(
                            "Verify this is the correct venue and consider adding "
                            f"'{extracted_name.lower()}' to venue_aliases.csv."
                        ),
                        raw_data=json.dumps(
                            {
                                "extracted_name": extracted_name,
                                "matched_alias": matched_alias,
                                "venue_id": venue_id,
                                "score": score,
                            }
                        ),
                    )
                return (venue_id, "fuzzy")

        # ------------------------------------------------------------------
        # Tier 3: AI text function
        # ------------------------------------------------------------------
        if self.ai_text_func is not None:
            canonical_names = self._canonical_name_list()
            try:
                ai_result = self.ai_text_func(extracted_name, canonical_names)
            except Exception as exc:
                logger.error(
                    "Tier 3 ai_text_func raised an exception for %r: %s",
                    extracted_name,
                    exc,
                    exc_info=True,
                )
                ai_result = None

            if ai_result and ai_result.strip().lower() not in ("none", ""):
                resolved_id = ai_result.strip()
                # Validate that the returned ID actually exists.
                if resolved_id in self.mappings:
                    logger.warning(
                        "Tier 3 AI resolution: %r -> venue_id %r",
                        extracted_name,
                        resolved_id,
                    )
                    self._append_human_review(
                        venue_id=resolved_id,
                        issue_type="name_mismatch_ai_resolved",
                        severity="medium",
                        details=(
                            f"AI resolved extracted name {extracted_name!r} to "
                            f"venue_id={resolved_id!r}."
                        ),
                        suggested_action=(
                            "Verify this is the correct venue and add the alias to "
                            "venue_aliases.csv to avoid future AI calls."
                        ),
                        raw_data=json.dumps(
                            {
                                "extracted_name": extracted_name,
                                "ai_resolved_venue_id": resolved_id,
                            }
                        ),
                    )
                    return (resolved_id, "ai")
                else:
                    logger.warning(
                        "Tier 3 AI returned unknown venue_id %r for extracted_name %r; "
                        "treating as unresolved",
                        resolved_id,
                        extracted_name,
                    )

        # ------------------------------------------------------------------
        # All tiers failed
        # ------------------------------------------------------------------
        logger.error("All normalization tiers failed for extracted_name=%r", extracted_name)
        self._append_unresolved(
            extracted_name=extracted_name,
            reason="No alias, fuzzy, or AI match found.",
        )
        return (None, "unknown")

    def get_canonical_name(self, location_label: str) -> str | None:
        """Return the canonical location_label for a known label, or None if not found.

        Since the mappings dict is keyed by location_label, this returns the
        label itself when it exists in the mapping — confirming it is a known
        canonical value.

        Args:
            location_label: The location_label string to look up.

        Returns:
            The location_label string if found in the mappings dict, else None.
        """
        if location_label not in self.mappings:
            return None
        return location_label

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _canonical_name_list(self) -> list[str]:
        """Return a list of all canonical venue IDs for AI resolution.

        Returns:
            List of venue_id strings from self.mappings.
        """
        return list(self.mappings.keys())

    def _append_human_review(
        self,
        venue_id: str,
        issue_type: str,
        severity: str,
        details: str,
        suggested_action: str,
        raw_data: str,
    ) -> None:
        """Append a HumanReviewItem dict to the human_review_queue if set.

        Args:
            venue_id: Venue identifier associated with the review item.
            issue_type: Short type string for the issue.
            severity: One of "low", "medium", "high".
            details: Human-readable description of the issue.
            suggested_action: Recommended follow-up action.
            raw_data: JSON-serialised supporting data string.
        """
        if self.human_review_queue is None:
            return
        item: dict = {
            "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "venue_id": venue_id,
            "issue_type": issue_type,
            "severity": severity,
            "details": details,
            "suggested_action": suggested_action,
            "raw_data": raw_data,
        }
        self.human_review_queue.append(item)

    def _append_unresolved(self, extracted_name: str, reason: str) -> None:
        """Append an unresolved-name HumanReviewItem to the queue.

        Args:
            extracted_name: The raw name string that could not be resolved.
            reason: Human-readable explanation of why resolution failed.
        """
        self._append_human_review(
            venue_id="unknown",
            issue_type="name_mismatch_unresolved",
            severity="high",
            details=(f"Could not resolve extracted venue name {extracted_name!r}. {reason}"),
            suggested_action=(
                "Manually identify the correct venue and add an alias to venue_aliases.csv."
            ),
            raw_data=json.dumps({"extracted_name": extracted_name, "reason": reason}),
        )


# ---------------------------------------------------------------------------
# Standalone factory for Google Gemini Tier-3 text function
# ---------------------------------------------------------------------------


def make_google_ai_text_func(api_key: str) -> Callable[[str, list[str]], str | None]:
    """Create an AI text function using Google Gemini Flash for Tier 3 normalization.

    The returned function takes (extracted_name, canonical_names_list) and
    returns the best matching canonical_venue_id or None.

    Uses google.genai synchronously (cheap text call, not a vision call).
    The prompt asks: "Which of these venues best matches '{extracted_name}'?
    Respond with only the venue_id of the best match, or 'none' if no good match."

    Args:
        api_key: Google AI API key string.

    Returns:
        A callable with signature (extracted_name: str, canonical_names: list[str])
        -> str | None suitable for use as the ai_text_func argument of
        VenueNormalizer.
    """
    import google.genai as genai  # noqa: PLC0415 — deferred to avoid hard dep

    _client = genai.Client(api_key=api_key)
    _model_id = "gemini-2.5-pro"

    def ai_text_func(extracted_name: str, canonical_names: list[str]) -> str | None:
        """Call Gemini Flash to resolve a raw venue name to a venue_id.

        Args:
            extracted_name: The raw venue name string from AI extraction.
            canonical_names: List of known venue_id strings to match against.

        Returns:
            A venue_id string from canonical_names if a good match is found,
            otherwise None.
        """
        if not canonical_names:
            logger.warning("ai_text_func called with empty canonical_names list")
            return None

        names_block = "\n".join(f"  - {name}" for name in canonical_names)
        prompt = (
            f"Which of these venues best matches '{extracted_name}'?\n"
            f"Known venue IDs:\n{names_block}\n\n"
            "Respond with only the venue_id of the best match (exactly as listed), "
            "or respond with the single word 'none' if no good match exists."
        )

        try:
            response = _client.models.generate_content(
                model=_model_id,
                contents=prompt,
            )
            raw = (response.text or "").strip()
        except Exception as exc:
            logger.error(
                "make_google_ai_text_func: Gemini API error for %r: %s",
                extracted_name,
                exc,
                exc_info=True,
            )
            return None

        if not raw or raw.lower() == "none":
            logger.debug(
                "make_google_ai_text_func: Gemini returned 'none' for %r",
                extracted_name,
            )
            return None

        # Validate the returned value is actually in our list before returning.
        if raw in canonical_names:
            return raw

        # Try case-insensitive match as a fallback in case model adds casing.
        raw_lower = raw.lower()
        for name in canonical_names:
            if name.lower() == raw_lower:
                return name

        logger.warning(
            "make_google_ai_text_func: Gemini returned %r which is not a known "
            "venue_id; discarding",
            raw,
        )
        return None

    return ai_text_func
