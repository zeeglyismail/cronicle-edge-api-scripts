"""Transformations: XML parsing for Windows Task Scheduler imports + clone payload builder.

Two distinct concerns live here:

1. parse_windows_xml_task() + xml_interval_to_timing() -- port of parse_xml.py
   and the interval-mapping case statement in bulk_import_xml.sh.

2. build_clone_payload() -- the field-stripping, title/URL transform, and
   force-disabled logic shared between cronicle_clone_events and the
   one-shot seed_schedule2.py script.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


# Fields that must NEVER be carried from a source event into a create_event payload.
_STRIP_ON_CLONE = ("id", "created", "modified", "username")


@dataclass(frozen=True)
class ParsedTask:
    """The subset of fields we extract from a Windows Task Scheduler XML."""

    name: str           # Task name (last URI segment)
    url: str            # First http(s) URL found in Actions/Exec/Arguments (may be "")
    interval: str       # Raw Windows ISO-8601 duration string, e.g. "PT2M", "P1D"
    start_hour: int     # From StartBoundary, used for daily/hourly anchors
    start_minute: int   # From StartBoundary
    has_daily: bool     # ScheduleByDay node present
    has_weekly: bool    # ScheduleByWeek node present


def parse_windows_xml_task(path: Path | str) -> ParsedTask:
    """Parse a Windows Task Scheduler XML file. Raises ValueError on parse failure.

    Handles:
    - UTF-16 with BOM (Windows export default)
    - UTF-8 fallback
    - Strips xmlns so XPath stays simple
    - Defaults missing interval based on schedule type (P1D for daily, PT2M otherwise)
    """
    p = Path(path)
    raw = p.read_bytes()

    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        content = raw.decode("utf-16")
    else:
        content = raw.decode("utf-8", errors="replace")

    # Strip default namespace once so XPath like .//URI works without prefixes.
    content = re.sub(r'\sxmlns="[^"]+"', "", content, count=1)

    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise ValueError(f"XML parse error: {e}") from e

    uri_elem = root.find(".//URI")
    uri_text = (uri_elem.text or "") if uri_elem is not None else ""
    name = re.split(r"[\\/]", uri_text.rstrip("/\\"))[-1] if uri_text else "unknown"

    args_elem = root.find(".//Actions/Exec/Arguments")
    args_text = (args_elem.text or "") if args_elem is not None else ""
    url_match = re.search(r'(https?://[^\s"]+)', args_text)
    url = url_match.group(1) if url_match else ""

    interval_elem = root.find(".//Repetition/Interval")
    interval = (interval_elem.text or "") if interval_elem is not None else ""

    start_elem = root.find(".//StartBoundary")
    start_text = (start_elem.text or "") if start_elem is not None else ""
    start_hour = 0
    start_minute = 0
    if start_text:
        m = re.search(r"T(\d{2}):(\d{2})", start_text)
        if m:
            start_hour = int(m.group(1))
            start_minute = int(m.group(2))

    has_daily = root.find(".//ScheduleByDay") is not None
    has_weekly = root.find(".//ScheduleByWeek") is not None
    has_repetition = root.find(".//Repetition") is not None

    # Match bash defaulting: if no interval and it's a daily-only schedule,
    # treat as P1D; otherwise default to PT2M (every 2 minutes).
    if not interval and has_daily and not has_repetition:
        interval = "P1D"
    elif not interval:
        interval = "PT2M"

    return ParsedTask(
        name=name,
        url=url,
        interval=interval,
        start_hour=start_hour,
        start_minute=start_minute,
        has_daily=has_daily,
        has_weekly=has_weekly,
    )


# Sub-hour intervals: minutes filled in based on step, no hours constraint.
_SUB_HOUR_MINUTES: dict[str, list[int]] = {
    "PT1M":  list(range(0, 60, 1)),
    "PT2M":  list(range(0, 60, 2)),
    "PT3M":  list(range(0, 60, 3)),
    "PT5M":  list(range(0, 60, 5)),
    "PT10M": list(range(0, 60, 10)),
    "PT15M": list(range(0, 60, 15)),
    "PT20M": list(range(0, 60, 20)),
    "PT30M": list(range(0, 60, 30)),
}

# Multi-hour intervals: minutes is [start_minute], hours is the explicit pattern.
# Mirrors bulk_import_xml.sh exactly (anchored at hour 0, NOT start_hour).
_MULTI_HOUR_HOURS: dict[str, list[int] | None] = {
    "PT1H":  None,  # every hour at start_minute
    "PT60M": None,  # every hour (alias)
    "PT2H":  [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22],
    "PT3H":  [0, 3, 6, 9, 12, 15, 18, 21],
    "PT4H":  [0, 4, 8, 12, 16, 20],
    "PT6H":  [0, 6, 12, 18],
    "PT8H":  [0, 8, 16],
    "PT12H": [0, 12],
}


def xml_interval_to_timing(
    interval: str,
    start_hour: int = 0,
    start_minute: int = 0,
) -> tuple[dict, bool]:
    """Map a Windows interval string to a Cronicle timing dict.

    Returns (timing_dict, warned). warned=True means the interval was
    unrecognized and we fell back to PT2M (every 2 minutes). The caller
    should surface this so the operator can review in the UI.
    """
    if interval in _SUB_HOUR_MINUTES:
        return {"minutes": list(_SUB_HOUR_MINUTES[interval])}, False

    if interval in _MULTI_HOUR_HOURS:
        hours = _MULTI_HOUR_HOURS[interval]
        out: dict = {"minutes": [start_minute]}
        if hours is not None:
            out["hours"] = list(hours)
        return out, False

    if interval in ("P1D", "PT24H"):
        return {"minutes": [start_minute], "hours": [start_hour]}, False

    # Unknown -> default to PT2M (matches bash UNKNOWN_INTERVAL_*_DEFAULTED_TO_2MIN).
    return {"minutes": list(range(0, 60, 2))}, True


def build_clone_payload(
    src_event: dict,
    dst_category: str,
    dst_target: str,
    title_replace_from: str | None = None,
    title_replace_to: str | None = None,
    url_replace_from: str | None = None,
    url_replace_to: str | None = None,
    force_disabled: bool = True,
) -> tuple[dict, str, str, str, str]:
    """Build a create_event/v1 payload from an existing event ("clone").

    Strips id/created/modified/username, retargets category/target, optionally
    rewrites title and params.url via str.replace (substring), and optionally
    forces enabled=0.

    Returns (payload, old_title, new_title, old_url, new_url) so callers can
    show a clean preview without re-doing the work.
    """
    payload = dict(src_event)
    for f in _STRIP_ON_CLONE:
        payload.pop(f, None)

    if force_disabled:
        payload["enabled"] = 0

    payload["category"] = dst_category
    payload["target"] = dst_target

    old_title = payload.get("title", "") or ""
    new_title = (
        old_title.replace(title_replace_from, title_replace_to or "")
        if title_replace_from
        else old_title
    )
    payload["title"] = new_title

    old_url = ""
    new_url = ""
    if isinstance(payload.get("params"), dict):
        # Avoid mutating the source dict in-place.
        new_params = dict(payload["params"])
        old_url = (new_params.get("url") or "")
        if url_replace_from and old_url:
            new_url = old_url.replace(url_replace_from, url_replace_to or "")
            new_params["url"] = new_url
        else:
            new_url = old_url
        payload["params"] = new_params

    return payload, old_title, new_title, old_url, new_url
