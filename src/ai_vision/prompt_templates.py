"""Prompt templates for AI vision event extraction."""


def build_extraction_prompt(venue_context: dict, is_detail_page: bool = False) -> str:
    """Build the extraction prompt for the AI vision model.

    For list pages (is_detail_page=False):
    - Instructs to extract: show title, date, SHOW START time (not door time).
    - For multi_venue: also extract the venue/sub-venue name per event.
    - Date range: event_window_start to event_window_end.
    - CRITICAL instruction about doors vs show time.
    - Returns JSON: {"events": [{...}, ...]}

    For detail pages (is_detail_page=True):
    - Instructs to extract specific missing fields from a single event page.

    Args:
        venue_context: Dict with venue_id, venue_name, site_type,
            event_window_start, event_window_end.
        is_detail_page: If True, use detail-page variant of prompt.

    Returns:
        Prompt string to send to the AI model.
    """
    venue_name: str = venue_context.get("venue_name", "Unknown Venue")
    site_type: str = venue_context.get("site_type", "single_venue")
    window_start: str = venue_context.get("event_window_start", "")
    window_end: str = venue_context.get("event_window_end", "")

    if is_detail_page:
        return _build_detail_page_prompt(venue_name, site_type, window_start, window_end)

    return _build_list_page_prompt(venue_name, site_type, window_start, window_end)


def _build_list_page_prompt(
    venue_name: str,
    site_type: str,
    window_start: str,
    window_end: str,
) -> str:
    """Build the prompt for a schedule list page.

    Args:
        venue_name: Canonical venue name.
        site_type: Either 'single_venue' or 'multi_venue'.
        window_start: Inclusive start of event window, YYYY-MM-DD.
        window_end: Inclusive end of event window, YYYY-MM-DD.

    Returns:
        Prompt string.
    """
    if site_type == "multi_venue":
        venue_instruction = (
            f"This is a multi-venue schedule page for '{venue_name}' "
            f"which lists events across multiple sub-venues or locations. "
            f"For each event, extract the sub-venue or location name and place it in "
            f"the 'location_label' field."
        )
        location_label_note = (
            "  - location_label: The sub-venue or room name where this event takes place "
            "(string, required for multi-venue sites)."
        )
    else:
        venue_instruction = (
            f"This is the event schedule for '{venue_name}', a single SF Bay Area venue. "
            f"All events on this page take place at '{venue_name}'. "
            f"Set 'location_label' to null for every event."
        )
        location_label_note = "  - location_label: null (this is a single-venue site)."

    prompt = f"""You are an expert event data extractor for SF Bay Area live music and entertainment venues.

TASK: Extract the show schedule from the provided screenshot(s) of an event listing page.

VENUE CONTEXT:
{venue_instruction}

DATE RANGE: Only include events that fall within {window_start} through {window_end} (inclusive).
Discard any events outside this date range. If an event's date is unclear, include it with
event_start_date set to null and note the ambiguity.

CRITICAL — SHOW START TIME vs DOORS OPEN TIME:
Extract the SHOW START TIME, not the doors open time.
- If the page shows "Doors 7:00pm / Show 8:00pm", the event_start_time is 20:00:00, NOT 19:00:00.
- If the page shows "Doors 6:30 | Show 7:30", the event_start_time is 19:30:00, NOT 18:30:00.
- Only use the door time as event_start_time if NO show time is listed anywhere on the page.
- If only a door time is present and no show time can be determined, set event_start_time to null
  and set notes to "only door time available".

FIELDS TO EXTRACT per event:
  - label: The show or event title (string or null if not readable).
{location_label_note}
  - event_start_date: The date of the show in YYYY-MM-DD format (string or null).
  - event_start_time: The SHOW START time in HH:MM:SS 24-hour format (string or null).
    Examples: "20:00:00", "19:30:00", "14:00:00". NOT the doors time.
  - confidence: How confident you are in the extracted data:
      "high"   — all fields clearly readable with no ambiguity.
      "medium" — minor uncertainty (e.g. partially obscured text, inferred date).
      "low"    — significant uncertainty; data may be wrong.
  - notes: Any ambiguities, caveats, or extraction issues (string or null).
  - requires_detail_page: Set to true if critical information (date or time) is missing and
    would likely be found by navigating to the event's detail page. Otherwise false.

OUTPUT FORMAT — respond with ONLY valid JSON, no markdown fences, no extra text:
{{"events": [
  {{
    "label": "Show Title Here",
    "location_label": null,
    "event_start_date": "YYYY-MM-DD",
    "event_start_time": "HH:MM:SS",
    "confidence": "high",
    "notes": null,
    "requires_detail_page": false
  }}
]}}

If no events are found in the date range, return: {{"events": []}}

IMPORTANT REMINDERS:
- Dates must be YYYY-MM-DD (e.g. "2026-03-15"), times must be HH:MM:SS 24-hour (e.g. "20:00:00").
- Do NOT include events outside {window_start} to {window_end}.
- Do NOT use door open times as show start times.
- If a field is genuinely unavailable, use null — do not guess or fabricate.
- Include every event visible in the screenshots within the date range, even if data is partial.
"""
    return prompt.strip()


def _build_detail_page_prompt(
    venue_name: str,
    site_type: str,
    window_start: str,
    window_end: str,
) -> str:
    """Build the prompt for a single event detail page.

    Args:
        venue_name: Canonical venue name.
        site_type: Either 'single_venue' or 'multi_venue'.
        window_start: Inclusive start of event window, YYYY-MM-DD.
        window_end: Inclusive end of event window, YYYY-MM-DD.

    Returns:
        Prompt string.
    """
    if site_type == "multi_venue":
        location_note = (
            "  - location_label: The sub-venue or room name where this event takes place "
            "(string or null)."
        )
    else:
        location_note = "  - location_label: null (single-venue site)."

    prompt = f"""You are an expert event data extractor for SF Bay Area live music and entertainment venues.

TASK: Extract detailed event information from this single event detail page for '{venue_name}'.

DATE RANGE: This event should fall within {window_start} through {window_end}.

CRITICAL — SHOW START TIME vs DOORS OPEN TIME:
Extract the SHOW START TIME, not the doors open time.
- If the page shows "Doors 7:00pm / Show 8:00pm", the event_start_time is 20:00:00, NOT 19:00:00.
- If the page shows "Doors 6:30 | Show 7:30", the event_start_time is 19:30:00, NOT 18:30:00.
- Only use the door time as event_start_time if NO show time is listed anywhere on the page.
- If only a door time is present and no show time can be determined, set event_start_time to null
  and set notes to "only door time available".

FIELDS TO EXTRACT:
  - label: The show or event title (string or null).
{location_note}
  - event_start_date: The date of the show in YYYY-MM-DD format (string or null).
  - event_start_time: The SHOW START time in HH:MM:SS 24-hour format (string or null).
  - confidence: "high", "medium", or "low" based on clarity of the data.
  - notes: Any ambiguities, caveats, or issues (string or null).
  - requires_detail_page: false (we are already on the detail page).

OUTPUT FORMAT — respond with ONLY valid JSON, no markdown fences, no extra text:
{{"events": [
  {{
    "label": "Show Title Here",
    "location_label": null,
    "event_start_date": "YYYY-MM-DD",
    "event_start_time": "HH:MM:SS",
    "confidence": "high",
    "notes": null,
    "requires_detail_page": false
  }}
]}}

Return exactly one event object in the list (or an empty list if no event data is found).
"""
    return prompt.strip()


def build_cookie_ai_prompt() -> str:
    """Build a prompt asking the AI to identify a cookie modal dismiss button.

    The AI should analyze the screenshot and return a CSS selector string
    that targets the button or element used to dismiss the cookie consent modal.

    Returns:
        Short prompt string. AI should respond with a CSS selector string.
    """
    return (
        "Look at this screenshot. If there is a cookie consent banner or modal visible, "
        "identify the button or link that dismisses it (e.g. 'Accept', 'Accept All', "
        "'Reject All', 'Close', 'Got it', 'I Agree', 'OK'). "
        "Respond with ONLY a CSS selector string that targets that dismiss button "
        "(e.g. '#cookie-accept', '.cookie-banner button.accept', '[data-action=\"accept\"]'). "
        "If there is no cookie banner or modal visible, respond with the single word: NONE"
    )
