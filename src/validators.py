"""Event record validation and deduplication for the event aggregator.

Provides:
- :func:`validate_event`: checks all fields of an assembled event dict
  against the rules required for MySQL import.
- :func:`deduplicate_events`: removes duplicate events, keeping the
  most-complete record when duplicates collide.
"""

import logging
import re
from datetime import date, datetime

logger = logging.getLogger(__name__)

_AFFECTED_GARAGES_PATTERN = re.compile(r"^(\d+(,\d+)*)?$")


def validate_event(
    event: dict,
    today: date,
    max_future_date: date,
) -> tuple[bool, list[str]]:
    """Validate all fields of an assembled event dict.

    Validation rules applied:

    - ``label``: non-empty after stripping whitespace, ≤ 255 characters.
    - ``location_label``: non-empty, ≤ 255 characters.
    - ``latitude``: float-convertible, within 37.0–38.0 (SF Bay Area).
    - ``longitude``: float-convertible, within -123.0 to -121.5 (SF Bay Area).
    - ``radius``: float-convertible, greater than 0.
    - ``event_start_date``: valid ``YYYY-MM-DD``, ≥ today, ≤ max_future_date.
    - ``event_start_time``: valid ``HH:MM:SS`` in 24-hour format,
      between ``06:00:00`` and ``23:59:59`` inclusive.
    - ``web``: string that starts with ``"https://"``, ≤ 255 characters.
    - ``icon``: non-empty string, ≤ 255 characters.
    - ``affected_garages_ids``: matches ``r"^(\\d+(,\\d+)*)?$"`` or empty
      string, ≤ 1024 characters.

    Args:
        event: Assembled event dict with keys matching the output column names.
        today: The current date; used as the lower bound for event_start_date.
        max_future_date: Upper bound (inclusive) for event_start_date.

    Returns:
        A tuple ``(is_valid, errors)`` where ``is_valid`` is ``True`` when
        all checks pass and ``errors`` is an empty list.  If any check fails
        ``is_valid`` is ``False`` and ``errors`` contains one message per
        failing check.
    """
    errors: list[str] = []

    # --- label ---
    label_raw = event.get("label")
    if label_raw is None:
        errors.append("label: field is missing")
    else:
        label = str(label_raw).strip()
        if not label:
            errors.append("label: must be non-empty after stripping whitespace")
        elif len(label) > 255:
            errors.append(f"label: exceeds 255 characters (got {len(label)})")

    # --- location_label ---
    location_label_raw = event.get("location_label")
    if location_label_raw is None:
        errors.append("location_label: field is missing")
    else:
        location_label = str(location_label_raw).strip()
        if not location_label:
            errors.append("location_label: must be non-empty")
        elif len(location_label) > 255:
            errors.append(f"location_label: exceeds 255 characters (got {len(location_label)})")

    # --- latitude ---
    latitude_raw = event.get("latitude")
    if latitude_raw is None or str(latitude_raw).strip() == "":
        errors.append("latitude: field is missing or empty")
    else:
        try:
            latitude = float(latitude_raw)
            if not (37.0 <= latitude <= 38.0):
                errors.append(f"latitude: {latitude} is outside SF Bay Area range [37.0, 38.0]")
        except (ValueError, TypeError):
            errors.append(f"latitude: cannot convert {latitude_raw!r} to float")

    # --- longitude ---
    longitude_raw = event.get("longitude")
    if longitude_raw is None or str(longitude_raw).strip() == "":
        errors.append("longitude: field is missing or empty")
    else:
        try:
            longitude = float(longitude_raw)
            if not (-123.0 <= longitude <= -121.5):
                errors.append(
                    f"longitude: {longitude} is outside SF Bay Area range [-123.0, -121.5]"
                )
        except (ValueError, TypeError):
            errors.append(f"longitude: cannot convert {longitude_raw!r} to float")

    # --- radius ---
    radius_raw = event.get("radius")
    if radius_raw is None or str(radius_raw).strip() == "":
        errors.append("radius: field is missing or empty")
    else:
        try:
            radius = float(radius_raw)
            if radius <= 0:
                errors.append(f"radius: must be greater than 0 (got {radius})")
        except (ValueError, TypeError):
            errors.append(f"radius: cannot convert {radius_raw!r} to float")

    # --- event_start_date ---
    date_raw = event.get("event_start_date")
    if date_raw is None or str(date_raw).strip() == "":
        errors.append("event_start_date: field is missing or empty")
    else:
        try:
            event_date = datetime.strptime(str(date_raw).strip(), "%Y-%m-%d").date()
            if event_date < today:
                errors.append(f"event_start_date: {event_date} is in the past (today is {today})")
            elif event_date > max_future_date:
                errors.append(
                    f"event_start_date: {event_date} exceeds max future date {max_future_date}"
                )
        except ValueError:
            errors.append(f"event_start_date: {date_raw!r} is not a valid YYYY-MM-DD date")

    # --- event_start_time ---
    time_raw = event.get("event_start_time")
    if time_raw is None or str(time_raw).strip() == "":
        errors.append("event_start_time: field is missing or empty")
    else:
        time_str = str(time_raw).strip()
        try:
            parsed_time = datetime.strptime(time_str, "%H:%M:%S").time()
            min_time = datetime.strptime("06:00:00", "%H:%M:%S").time()
            max_time = datetime.strptime("23:59:59", "%H:%M:%S").time()
            if not (min_time <= parsed_time <= max_time):
                errors.append(
                    f"event_start_time: {time_str} is outside allowed range [06:00:00, 23:59:59]"
                )
        except ValueError:
            errors.append(f"event_start_time: {time_raw!r} is not a valid HH:MM:SS time")

    # --- web ---
    web_raw = event.get("web")
    if web_raw is None or str(web_raw).strip() == "":
        errors.append("web: field is missing or empty")
    else:
        web = str(web_raw).strip()
        if not web.startswith("https://"):
            errors.append(f"web: must start with 'https://' (got {web!r})")
        if len(web) > 255:
            errors.append(f"web: exceeds 255 characters (got {len(web)})")

    # --- icon ---
    icon_raw = event.get("icon")
    if icon_raw is None:
        errors.append("icon: field is missing")
    else:
        icon = str(icon_raw).strip()
        if not icon:
            errors.append("icon: must be non-empty")
        elif len(icon) > 255:
            errors.append(f"icon: exceeds 255 characters (got {len(icon)})")

    # --- affected_garages_ids ---
    garages_raw = event.get("affected_garages_ids")
    garages_str = "" if garages_raw is None else str(garages_raw).strip()

    if len(garages_str) > 1024:
        errors.append(f"affected_garages_ids: exceeds 1024 characters (got {len(garages_str)})")
    elif not _AFFECTED_GARAGES_PATTERN.match(garages_str):
        errors.append(
            f"affected_garages_ids: {garages_str!r} does not match"
            r" pattern r'^(\d+(,\d+)*)?$'"
        )

    is_valid = len(errors) == 0
    return is_valid, errors


def _completeness_score(event: dict) -> int:
    """Count the number of non-None, non-empty-string fields in an event dict.

    Args:
        event: An assembled event dict.

    Returns:
        Integer count of fields that have a meaningful value.
    """
    score = 0
    for value in event.values():
        if value is not None and str(value).strip() != "":
            score += 1
    return score


def deduplicate_events(events: list[dict]) -> list[dict]:
    """Remove duplicate events, keeping the most-complete record per key.

    Duplicate key: ``(label, location_label, event_start_date, event_start_time)``.

    When two or more records share the same key, the one with the greatest
    number of non-None, non-empty field values is retained.  The output list
    preserves the relative order of the first occurrence of each key.

    Args:
        events: List of assembled event dicts, possibly containing duplicates.

    Returns:
        Deduplicated list of event dicts, ordered by first occurrence of each key.
    """
    # Maps dedup key -> (index_of_first_occurrence, best_event, best_score)
    seen: dict[tuple, tuple[int, dict, int]] = {}

    for event in events:
        key = (
            str(event.get("label", "") or "").strip(),
            str(event.get("location_label", "") or "").strip(),
            str(event.get("event_start_date", "") or "").strip(),
            str(event.get("event_start_time", "") or "").strip(),
        )

        score = _completeness_score(event)

        if key not in seen:
            seen[key] = (len(seen), event, score)
        else:
            first_index, current_best, current_score = seen[key]
            if score > current_score:
                logger.debug(
                    "Duplicate event: replacing record with score %d with score %d for key %s",
                    current_score,
                    score,
                    key,
                )
                seen[key] = (first_index, event, score)
            else:
                logger.debug(
                    "Duplicate event: discarding record with score %d"
                    " (keeping score %d) for key %s",
                    score,
                    current_score,
                    key,
                )

    # Re-sort by first-occurrence index to preserve original ordering.
    ordered = sorted(seen.values(), key=lambda t: t[0])
    result = [record for _, record, _ in ordered]

    duplicate_count = len(events) - len(result)
    if duplicate_count:
        logger.info(
            "Deduplicated %d event(s) — %d unique event(s) remain",
            duplicate_count,
            len(result),
        )

    return result
