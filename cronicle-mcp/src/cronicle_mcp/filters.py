"""Shared event filter logic — used by every tool that selects events."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, model_validator


FilterMode = Literal[
    "event_ids", "target_only", "category_only", "category_and_target", "all"
]


class EventFilter(BaseModel):
    """Selects which Cronicle events a tool acts on.

    Modes:
      - event_ids           requires event_ids — an explicit list of `emo*` ids.
                            One id is the single-event case: every bulk tool
                            (toggle, move, update_schedule, update_timeouts,
                            delete, clone, run) accepts it, so "disable just
                            this one event" needs no separate tool.
      - target_only         requires target_id (all categories on that server group)
      - category_only       requires category_id (all targets in that category)
      - category_and_target requires both (most precise — recommended)
      - all                 matches every event (no filter — use sparingly)
    """

    mode: FilterMode
    category_id: Optional[str] = None
    target_id: Optional[str] = None
    event_ids: Optional[list[str]] = None

    @model_validator(mode="after")
    def _check(self) -> "EventFilter":
        if self.mode == "event_ids":
            cleaned = [e.strip() for e in (self.event_ids or []) if e and e.strip()]
            if not cleaned:
                raise ValueError(
                    "filter mode 'event_ids' requires a non-empty event_ids list"
                )
            self.event_ids = cleaned
        if self.mode == "target_only" and not self.target_id:
            raise ValueError("filter mode 'target_only' requires target_id")
        if self.mode == "category_only" and not self.category_id:
            raise ValueError("filter mode 'category_only' requires category_id")
        if self.mode == "category_and_target" and not (self.category_id and self.target_id):
            raise ValueError(
                "filter mode 'category_and_target' requires category_id and target_id"
            )
        return self

    def matches(self, event: dict) -> bool:
        if self.mode == "all":
            return True
        if self.mode == "event_ids":
            return event.get("id") in set(self.event_ids or [])
        if self.mode == "target_only":
            return event.get("target") == self.target_id
        if self.mode == "category_only":
            return event.get("category") == self.category_id
        return (
            event.get("category") == self.category_id
            and event.get("target") == self.target_id
        )
