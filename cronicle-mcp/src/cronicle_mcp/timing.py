"""Cronicle timing preset table.

Maps human-friendly intervals like "5m", "1h", "daily" to the
{minutes:[...], hours:[...]} selection arrays Cronicle stores.

Ported verbatim from bulk_update_schedule.sh so MCP-issued schedule
changes match the existing bash automation byte-for-byte.

Behavior rules:
  - Sub-hour presets (1m..30m): emit only `minutes`, no `hours` constraint
    (event runs at those minutes of every hour).
  - "1h": emit only `minutes: [start_minute]`, no `hours` (every hour at
    that minute mark).
  - 2h..12h: emit `minutes: [start_minute]` AND `hours: [0, step, 2*step, ...]`.
    `start_hour` is IGNORED -- the hour pattern always anchors at 0.
  - "daily": emit `minutes: [start_minute]` AND `hours: [start_hour]`.

`start_hour` only applies to "daily". `start_minute` applies to "1h" and up.
"""

from __future__ import annotations

# (minutes_array, hours_array_or_None, label)
_SUB_HOUR: dict[str, tuple[list[int], None, str]] = {
    "1m":  (list(range(0, 60, 1)),  None, "every 1 minute"),
    "2m":  (list(range(0, 60, 2)),  None, "every 2 minutes"),
    "3m":  (list(range(0, 60, 3)),  None, "every 3 minutes"),
    "5m":  (list(range(0, 60, 5)),  None, "every 5 minutes"),
    "10m": (list(range(0, 60, 10)), None, "every 10 minutes"),
    "15m": (list(range(0, 60, 15)), None, "every 15 minutes"),
    "20m": (list(range(0, 60, 20)), None, "every 20 minutes"),
    "30m": (list(range(0, 60, 30)), None, "every 30 minutes"),
}

# Hour-step presets (2h+): hours array is fixed, minutes is [start_minute]
_MULTI_HOUR_STEPS: dict[str, int] = {
    "2h":  2,
    "3h":  3,
    "4h":  4,
    "6h":  6,
    "8h":  8,
    "12h": 12,
}

SUPPORTED: list[str] = list(_SUB_HOUR) + ["1h"] + list(_MULTI_HOUR_STEPS) + ["daily"]


def interval_to_timing(
    interval: str,
    start_hour: int = 0,
    start_minute: int = 0,
) -> tuple[dict, str]:
    """Return (timing_dict, human_label) for a preset.

    Raises ValueError on unknown interval.
    """
    key = (interval or "").strip().lower()

    if key in _SUB_HOUR:
        minutes, _hours, label = _SUB_HOUR[key]
        return {"minutes": list(minutes)}, label

    if key == "1h":
        return {"minutes": [start_minute]}, f"every hour at :{start_minute:02d}"

    if key in _MULTI_HOUR_STEPS:
        step = _MULTI_HOUR_STEPS[key]
        hours = list(range(0, 24, step))
        return (
            {"minutes": [start_minute], "hours": hours},
            f"every {step} hours at :{start_minute:02d}",
        )

    if key == "daily":
        return (
            {"minutes": [start_minute], "hours": [start_hour]},
            f"daily at {start_hour:02d}:{start_minute:02d}",
        )

    raise ValueError(
        f"Unknown interval preset {interval!r}. Supported: {', '.join(SUPPORTED)}"
    )
