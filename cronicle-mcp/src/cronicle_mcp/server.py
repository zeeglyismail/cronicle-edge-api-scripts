"""MCP server entry point — defines all cronicle_* tools."""

from __future__ import annotations

import time
from collections import Counter
from typing import Any, Literal, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from pathlib import Path

from .client import CronicleAPIError, CronicleClient
from .config import Config, HostConfig, load as load_config
from .filters import EventFilter
from .timing import SUPPORTED as SUPPORTED_INTERVALS, interval_to_timing
from .transforms import (
    build_clone_payload,
    parse_windows_xml_task,
    xml_interval_to_timing,
)

mcp = FastMCP("cronicle")

# Lazy global so config errors surface on first tool call (not at import time
# during MCP capability negotiation).
_config: Config | None = None


def _cfg() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def _resolve_host(host: Optional[str]) -> HostConfig:
    return _cfg().get(host)


# --- output models -----------------------------------------------------------


class EventSummary(BaseModel):
    id: str
    title: str
    category: str
    target: str
    enabled: bool
    plugin: Optional[str] = None
    timing_summary: str
    url: Optional[str] = None  # populated only when the caller asks (include_url=True)


def _summarize_timing(timing: dict | None) -> str:
    """Render a Cronicle timing object as a short human string."""
    if timing is None:
        return "on-demand"
    if not timing:
        return "every minute (empty timing)"

    minutes = timing.get("minutes")
    hours = timing.get("hours")
    weekdays = timing.get("weekdays")
    months = timing.get("months")
    days = timing.get("days")

    parts: list[str] = []

    if minutes is not None:
        if len(minutes) == 60:
            parts.append("every minute")
        elif len(minutes) >= 2:
            step = minutes[1] - minutes[0]
            if all(minutes[i] - minutes[i - 1] == step for i in range(1, len(minutes))):
                parts.append(f"every {step}m")
            else:
                parts.append(f"minutes={minutes}")
        else:
            parts.append(f"@:{minutes[0]:02d}")

    if hours is not None:
        if len(hours) == 24:
            pass  # every hour, implied
        elif len(hours) >= 2:
            step = hours[1] - hours[0]
            if all(hours[i] - hours[i - 1] == step for i in range(1, len(hours))):
                parts.append(f"every {step}h")
            else:
                parts.append(f"hours={hours}")
        else:
            parts.append(f"at hour {hours[0]:02d}")

    if weekdays is not None:
        parts.append(f"weekdays={weekdays}")
    if days is not None:
        parts.append(f"days={days}")
    if months is not None:
        parts.append(f"months={months}")

    return ", ".join(parts) if parts else "every minute"


class WriteResult(BaseModel):
    """Standard return shape for every mutation tool.

    On dry_run=True, `executed=False` and `matched` shows what WOULD change,
    plus `notes` describes the change. On dry_run=False, `executed=True` and
    `succeeded`/`failed`/`errors` reflect the actual outcome per event.
    """

    host: str
    executed: bool
    matched_count: int
    matched: list["EventSummary"]
    succeeded: int = 0
    failed: int = 0
    errors: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def _guard_all_mode(filter: EventFilter, i_understand: bool, action_label: str) -> None:
    """Block accidental wholesale mutations when filter.mode == 'all'.

    Caller must explicitly pass i_understand_this_affects_everything=True to
    proceed when the filter would match every event in the host.
    """
    if filter.mode == "all" and not i_understand:
        raise ValueError(
            f"{action_label}: filter mode 'all' affects every event on the host. "
            "Pass i_understand_this_affects_everything=True to proceed."
        )


def _to_summary(event: dict, include_url: bool = False) -> EventSummary:
    url = None
    if include_url:
        url = (event.get("params") or {}).get("url") or ""
    return EventSummary(
        id=event.get("id", ""),
        title=event.get("title", ""),
        category=event.get("category", ""),
        target=event.get("target", ""),
        enabled=bool(event.get("enabled", 0)),
        plugin=event.get("plugin"),
        timing_summary=_summarize_timing(event.get("timing")),
        url=url,
    )


# --- tools -------------------------------------------------------------------


@mcp.tool()
def cronicle_list_events(
    filter: EventFilter,
    include_disabled: bool = True,
    include_url: bool = False,
    host: Optional[str] = None,
) -> list[EventSummary]:
    """List Cronicle events matching a filter.

    Always call this first to see what exists before any mutation. Returns
    compact summaries (id, title, category, target, enabled, plugin, timing).
    Use cronicle_get_event for the full event payload of a specific id.

    filter.mode is one of:
      - "target_only"          requires target_id
      - "category_only"        requires category_id
      - "category_and_target"  requires both (most precise — preferred)
      - "all"                  every event (use sparingly)

    include_url: when True, each summary also includes the plugin `url` field
    (the endpoint the event hits). Use this for "list events on target X with
    their URLs" -- no need to call cronicle_get_event per event. The URL comes
    from the already-fetched schedule data, so it's free.

    host: which configured host to query. Defaults to the 'default' host in
    .config/hosts.json. Pass an explicit host name (e.g. "schedule2") to
    target a different Cronicle instance.
    """
    hc = _resolve_host(host)
    with CronicleClient(hc) as client:
        events = client.list_events()

    matched = [e for e in events if filter.matches(e)]
    if not include_disabled:
        matched = [e for e in matched if e.get("enabled")]
    matched.sort(key=lambda e: e.get("title", ""))
    return [_to_summary(e, include_url=include_url) for e in matched]


@mcp.tool()
def cronicle_get_event(event_id: str, host: Optional[str] = None) -> dict:
    """Fetch the full event object (all fields, including params, timing, notes).

    Use this after cronicle_list_events when the user wants details on a
    specific event — its plugin URL, headers, exact timing arrays, timeouts,
    notes. The returned object mirrors what's stored in Cronicle.

    Common fields:
      id, title, enabled, category, target, plugin, timing (minutes/hours/...),
      params (plugin-specific: url, method, headers, timeout, ...),
      timeout (outer job kill switch in seconds), timezone, notes,
      max_children, queue, retries, retry_delay, log_expire_days

    host: configured host name (default = the 'default' from hosts.json).
    """
    hc = _resolve_host(host)
    with CronicleClient(hc) as client:
        return client.get_event(event_id)


class ScheduleSummary(BaseModel):
    host: str
    base_url: str
    total_events: int
    enabled: int
    disabled: int
    on_demand: int = Field(description="Events with no `timing` field -- only run when manually triggered")
    by_category: list[dict[str, Any]] = Field(
        description="One entry per category: {id, name, count}. name is null when unresolved."
    )
    by_target: list[dict[str, Any]] = Field(
        description="One entry per target: {id, name, count}. name comes from hosts.json groups map (null if not configured)."
    )
    by_category_and_target: list[dict[str, Any]] = Field(
        description="One entry per (category, target) pair: {category_id, category_name, target_id, target_name, count, enabled, disabled}"
    )
    unknown_targets: list[str] = Field(
        default_factory=list,
        description="Target IDs found on this host that aren't in hosts.json groups map. Add them there for cleaner output."
    )


@mcp.tool()
def cronicle_summarize_schedule(host: Optional[str] = None) -> ScheduleSummary:
    """Orientation tool -- counts of events grouped by category, target, and both.

    Best first call when the user asks 'what's running where' or 'how many
    events on UMS-3'. Includes friendly NAMES alongside IDs:
      - category names auto-resolved via Cronicle's get_categories endpoint
      - target names resolved via the 'groups' map in hosts.json (manual,
        because Cronicle Edge does not expose a server-groups list endpoint)

    `unknown_targets` lists any target IDs the host uses that aren't in
    the groups map -- those should be added to hosts.json for cleaner output.

    host: configured host name (default = the 'default' from hosts.json).
    """
    hc = _resolve_host(host)
    with CronicleClient(hc) as client:
        events = client.list_events()
        # Best-effort category enrichment. Some keys may not have manager priv;
        # we degrade silently in that case.
        try:
            cat_rows = client.list_categories()
            cat_names = {c.get("id"): c.get("title") for c in cat_rows}
        except Exception:
            cat_names = {}

    enabled = sum(1 for e in events if e.get("enabled"))
    on_demand = sum(1 for e in events if e.get("timing") is None)
    by_cat = Counter(e.get("category", "?") for e in events)
    by_tgt = Counter(e.get("target", "?") for e in events)

    pair_counts: dict[tuple[str, str], dict[str, int]] = {}
    for e in events:
        key = (e.get("category", "?"), e.get("target", "?"))
        bucket = pair_counts.setdefault(key, {"count": 0, "enabled": 0, "disabled": 0})
        bucket["count"] += 1
        if e.get("enabled"):
            bucket["enabled"] += 1
        else:
            bucket["disabled"] += 1

    pairs = [
        {
            "category_id": cat,
            "category_name": cat_names.get(cat),
            "target_id": tgt,
            "target_name": hc.group_name_for(tgt),
            **counts,
        }
        for (cat, tgt), counts in sorted(
            pair_counts.items(), key=lambda kv: kv[1]["count"], reverse=True
        )
    ]

    by_category_list = [
        {"id": cat, "name": cat_names.get(cat), "count": n}
        for cat, n in by_cat.most_common()
    ]
    by_target_list = [
        {"id": tgt, "name": hc.group_name_for(tgt), "count": n}
        for tgt, n in by_tgt.most_common()
    ]

    unknown = [t for t in by_tgt if hc.group_name_for(t) is None]

    return ScheduleSummary(
        host=hc.name,
        base_url=hc.base_url,
        total_events=len(events),
        enabled=enabled,
        disabled=len(events) - enabled,
        on_demand=on_demand,
        by_category=by_category_list,
        by_target=by_target_list,
        by_category_and_target=pairs,
        unknown_targets=unknown,
    )


@mcp.tool()
def cronicle_toggle_events(
    filter: EventFilter,
    action: Literal["enable", "disable"],
    dry_run: bool = True,
    host: Optional[str] = None,
    i_understand_this_affects_everything: bool = False,
) -> WriteResult:
    """Enable or disable every event matching the filter.

    Replaces bulk_toggle_events.sh and bulk_toggle_by_target.sh.

    Always defaults to dry_run=True. The first call returns the matched events
    so the caller can review. Re-call with dry_run=False to apply.

    action:
      "enable"   sets enabled=1 -- events become live and will run on schedule
      "disable"  sets enabled=0 -- events stop running immediately

    SAFETY: filter.mode='all' is blocked unless i_understand_this_affects_everything=True.
    Enabling a wide filter on a production host could fire many jobs at once.
    """
    _guard_all_mode(filter, i_understand_this_affects_everything, "cronicle_toggle_events")
    target_value = 1 if action == "enable" else 0
    hc = _resolve_host(host)

    with CronicleClient(hc) as client:
        events = client.list_events()
        matched = [e for e in events if filter.matches(e)]
        summaries = [_to_summary(e) for e in matched]

        if dry_run:
            already = sum(1 for e in matched if int(e.get("enabled", 0)) == target_value)
            will_change = len(matched) - already
            return WriteResult(
                host=hc.name,
                executed=False,
                matched_count=len(matched),
                matched=summaries,
                notes=[
                    f"Would {action} {will_change} events ({already} already in target state).",
                    f"Re-call with dry_run=False to apply.",
                ],
            )

        succeeded = 0
        failed = 0
        errors: list[str] = []
        for e in matched:
            try:
                client.update_event(e["id"], {"enabled": target_value})
                succeeded += 1
            except CronicleAPIError as ex:
                failed += 1
                errors.append(f"{e.get('id')}: {ex.description}")
            except Exception as ex:
                failed += 1
                errors.append(f"{e.get('id')}: {type(ex).__name__}: {ex}")
            time.sleep(hc.rate_limit_delay_ms / 1000.0)

        return WriteResult(
            host=hc.name,
            executed=True,
            matched_count=len(matched),
            matched=summaries,
            succeeded=succeeded,
            failed=failed,
            errors=errors,
            notes=[f"{action}d {succeeded} events ({failed} failed)."],
        )


@mcp.tool()
def cronicle_move_events(
    filter: EventFilter,
    new_category_id: Optional[str] = None,
    new_target_id: Optional[str] = None,
    dry_run: bool = True,
    host: Optional[str] = None,
    i_understand_this_affects_everything: bool = False,
) -> WriteResult:
    """Move matched events to a new category and/or new target (server group).

    Replaces bulk_move_category.sh and bulk_move_ums3.sh.

    At least one of new_category_id or new_target_id must be set. Pass only
    one to change just that field; pass both to change both.

    Always defaults to dry_run=True. Common workflow:
      1. Call with dry_run=True, review the matched list
      2. Re-call with dry_run=False to commit

    SAFETY: filter.mode='all' is blocked unless i_understand_this_affects_everything=True.
    """
    if not new_category_id and not new_target_id:
        raise ValueError(
            "cronicle_move_events: must set at least one of new_category_id or new_target_id"
        )
    _guard_all_mode(filter, i_understand_this_affects_everything, "cronicle_move_events")
    hc = _resolve_host(host)

    update_fields: dict[str, str] = {}
    if new_category_id:
        update_fields["category"] = new_category_id
    if new_target_id:
        update_fields["target"] = new_target_id

    with CronicleClient(hc) as client:
        events = client.list_events()
        matched = [e for e in events if filter.matches(e)]
        summaries = [_to_summary(e) for e in matched]

        if dry_run:
            change_descrs: list[str] = []
            if new_category_id:
                cats = Counter(e.get("category") for e in matched)
                change_descrs.append(
                    f"category: {dict(cats)} -> all become {new_category_id}"
                )
            if new_target_id:
                tgts = Counter(e.get("target") for e in matched)
                change_descrs.append(
                    f"target: {dict(tgts)} -> all become {new_target_id}"
                )
            return WriteResult(
                host=hc.name,
                executed=False,
                matched_count=len(matched),
                matched=summaries,
                notes=change_descrs + ["Re-call with dry_run=False to apply."],
            )

        succeeded = 0
        failed = 0
        errors: list[str] = []
        for e in matched:
            try:
                client.update_event(e["id"], update_fields)
                succeeded += 1
            except CronicleAPIError as ex:
                failed += 1
                errors.append(f"{e.get('id')}: {ex.description}")
            except Exception as ex:
                failed += 1
                errors.append(f"{e.get('id')}: {type(ex).__name__}: {ex}")
            time.sleep(hc.rate_limit_delay_ms / 1000.0)

        return WriteResult(
            host=hc.name,
            executed=True,
            matched_count=len(matched),
            matched=summaries,
            succeeded=succeeded,
            failed=failed,
            errors=errors,
            notes=[f"moved {succeeded} events ({failed} failed). fields={update_fields}"],
        )


@mcp.tool()
def cronicle_update_schedule(
    filter: EventFilter,
    interval: str,
    start_hour: int = 0,
    start_minute: int = 0,
    dry_run: bool = True,
    host: Optional[str] = None,
    i_understand_this_affects_everything: bool = False,
) -> WriteResult:
    """Change the schedule interval (timing) for every matched event.

    Replaces bulk_update_schedule.sh.

    Supported intervals (port from the bash preset table -- byte-identical):
      Sub-hour: "1m", "2m", "3m", "5m", "10m", "15m", "20m", "30m"
                -> emits minutes only, no hours constraint
      "1h"      -> minutes: [start_minute], no hours (every hour at :MM)
      "2h", "3h", "4h", "6h", "8h", "12h"
                -> minutes: [start_minute], hours: [0, step, 2*step, ...]
                   start_hour is IGNORED for these
      "daily"   -> minutes: [start_minute], hours: [start_hour]

    Common workflow:
      1. dry_run=True (default) -> see matched count + what timing would be set
      2. dry_run=False -> apply

    SAFETY: filter.mode='all' is blocked unless i_understand_this_affects_everything=True.
    """
    _guard_all_mode(filter, i_understand_this_affects_everything, "cronicle_update_schedule")
    timing, label = interval_to_timing(interval, start_hour, start_minute)
    hc = _resolve_host(host)

    with CronicleClient(hc) as client:
        events = client.list_events()
        matched = [e for e in events if filter.matches(e)]
        summaries = [_to_summary(e) for e in matched]

        if dry_run:
            return WriteResult(
                host=hc.name,
                executed=False,
                matched_count=len(matched),
                matched=summaries,
                notes=[
                    f"Would set schedule to: {label}",
                    f"timing JSON: {timing}",
                    "Re-call with dry_run=False to apply.",
                ],
            )

        succeeded, failed = 0, 0
        errors: list[str] = []
        for e in matched:
            try:
                client.update_event(e["id"], {"timing": timing})
                succeeded += 1
            except CronicleAPIError as ex:
                failed += 1
                errors.append(f"{e.get('id')}: {ex.description}")
            except Exception as ex:
                failed += 1
                errors.append(f"{e.get('id')}: {type(ex).__name__}: {ex}")
            time.sleep(hc.rate_limit_delay_ms / 1000.0)

        return WriteResult(
            host=hc.name,
            executed=True,
            matched_count=len(matched),
            matched=summaries,
            succeeded=succeeded,
            failed=failed,
            errors=errors,
            notes=[f"set schedule to {label} on {succeeded} events ({failed} failed)"],
        )


@mcp.tool()
def cronicle_update_timeouts(
    filter: EventFilter,
    plugin_timeout_seconds: Optional[int] = None,
    job_timeout_seconds: Optional[int] = None,
    dry_run: bool = True,
    host: Optional[str] = None,
    i_understand_this_affects_everything: bool = False,
) -> WriteResult:
    """Update plugin and/or job timeout for every matched event.

    Replaces bulk_update_timeout.sh.

    Cronicle has TWO distinct timeouts on each event -- this tool can update
    either or both:
      plugin_timeout_seconds -> stored as params.timeout (string seconds).
                                The HTTP plugin's own timeout. Typical: 1200.
      job_timeout_seconds    -> stored as top-level timeout (int seconds).
                                Cronicle's outer kill switch on the whole job.
                                Typical: 3600.

    At least one of the two must be specified.

    Implementation note: when updating params.timeout, this tool does
    GET-modify-PUT because Cronicle replaces the entire `params` object on
    update (NOT a merge), so we have to read all the existing plugin params
    first (url, headers, etc.) and write them back with just the timeout
    changed. job_timeout_seconds is a single top-level field and merges fine.

    SAFETY: filter.mode='all' is blocked unless i_understand_this_affects_everything=True.
    """
    if plugin_timeout_seconds is None and job_timeout_seconds is None:
        raise ValueError(
            "cronicle_update_timeouts: must set at least one of "
            "plugin_timeout_seconds or job_timeout_seconds"
        )
    _guard_all_mode(filter, i_understand_this_affects_everything, "cronicle_update_timeouts")
    hc = _resolve_host(host)

    with CronicleClient(hc) as client:
        events = client.list_events()
        matched = [e for e in events if filter.matches(e)]
        summaries = [_to_summary(e) for e in matched]

        if dry_run:
            notes = []
            if plugin_timeout_seconds is not None:
                notes.append(
                    f"Would set params.timeout = '{plugin_timeout_seconds}' (string seconds, plugin)"
                )
            if job_timeout_seconds is not None:
                notes.append(
                    f"Would set timeout = {job_timeout_seconds} (int seconds, outer job kill)"
                )
            notes.append("Re-call with dry_run=False to apply.")
            return WriteResult(
                host=hc.name,
                executed=False,
                matched_count=len(matched),
                matched=summaries,
                notes=notes,
            )

        succeeded, failed = 0, 0
        errors: list[str] = []
        for e in matched:
            try:
                update_fields: dict = {}
                if plugin_timeout_seconds is not None:
                    # GET full event so we can preserve other params
                    full = client.get_event(e["id"])
                    new_params = dict(full.get("params") or {})
                    new_params["timeout"] = str(plugin_timeout_seconds)
                    update_fields["params"] = new_params
                if job_timeout_seconds is not None:
                    update_fields["timeout"] = job_timeout_seconds

                client.update_event(e["id"], update_fields)
                succeeded += 1
            except CronicleAPIError as ex:
                failed += 1
                errors.append(f"{e.get('id')}: {ex.description}")
            except Exception as ex:
                failed += 1
                errors.append(f"{e.get('id')}: {type(ex).__name__}: {ex}")
            time.sleep(hc.rate_limit_delay_ms / 1000.0)

        notes = [f"updated {succeeded} events ({failed} failed)"]
        if plugin_timeout_seconds is not None:
            notes.append(f"plugin timeout (params.timeout) = '{plugin_timeout_seconds}'s")
        if job_timeout_seconds is not None:
            notes.append(f"job timeout (top-level) = {job_timeout_seconds}s")
        return WriteResult(
            host=hc.name,
            executed=True,
            matched_count=len(matched),
            matched=summaries,
            succeeded=succeeded,
            failed=failed,
            errors=errors,
            notes=notes,
        )


@mcp.tool()
def cronicle_delete_events(
    filter: EventFilter,
    dry_run: bool = True,
    confirm_count: Optional[int] = None,
    host: Optional[str] = None,
    i_understand_this_affects_everything: bool = False,
) -> WriteResult:
    """PERMANENTLY DELETE every event matching the filter.

    Replaces bulk_delete_events.sh and bulk_delete_category.sh.

    Workflow:
      1. dry_run=True (default) -> returns matched_count
      2. dry_run=False AND confirm_count=<that exact number> -> deletes
      3. If confirm_count doesn't match the live matched count, the call is
         REJECTED with an error. This guards against the set having changed
         since the preview (e.g. new events created in between).

    SAFETY:
      - filter.mode='all' is blocked unless i_understand_this_affects_everything=True.
      - confirm_count mismatch is always rejected -- you cannot bypass this.

    Cronicle deletes are permanent; there is no undo.
    """
    _guard_all_mode(filter, i_understand_this_affects_everything, "cronicle_delete_events")
    hc = _resolve_host(host)

    with CronicleClient(hc) as client:
        events = client.list_events()
        matched = [e for e in events if filter.matches(e)]
        summaries = [_to_summary(e) for e in matched]

        if dry_run:
            return WriteResult(
                host=hc.name,
                executed=False,
                matched_count=len(matched),
                matched=summaries,
                notes=[
                    f"Would PERMANENTLY DELETE {len(matched)} events.",
                    f"To execute: re-call with dry_run=False AND confirm_count={len(matched)}.",
                ],
            )

        # Execute path -- require exact confirm_count match
        if confirm_count is None:
            raise ValueError(
                f"cronicle_delete_events: confirm_count is required when dry_run=False. "
                f"Current matched count is {len(matched)}. "
                f"Pass confirm_count={len(matched)} to proceed."
            )
        if confirm_count != len(matched):
            raise ValueError(
                f"cronicle_delete_events: confirm_count={confirm_count} does NOT match "
                f"current matched count {len(matched)}. The matched set may have changed "
                f"since the last preview. Re-run with dry_run=True to see the current "
                f"count, then pass that exact number as confirm_count."
            )

        succeeded, failed = 0, 0
        errors: list[str] = []
        for e in matched:
            try:
                client.delete_event(e["id"])
                succeeded += 1
            except CronicleAPIError as ex:
                failed += 1
                errors.append(f"{e.get('id')}: {ex.description}")
            except Exception as ex:
                failed += 1
                errors.append(f"{e.get('id')}: {type(ex).__name__}: {ex}")
            time.sleep(hc.rate_limit_delay_ms / 1000.0)

        return WriteResult(
            host=hc.name,
            executed=True,
            matched_count=len(matched),
            matched=summaries,
            succeeded=succeeded,
            failed=failed,
            errors=errors,
            notes=[f"deleted {succeeded} events ({failed} failed)"],
        )


@mcp.tool()
def cronicle_clone_events(
    filter: EventFilter,
    dest_target_id: str,
    dest_category_id: Optional[str] = None,
    dest_host: Optional[str] = None,
    title_replace_from: Optional[str] = None,
    title_replace_to: Optional[str] = None,
    url_replace_from: Optional[str] = None,
    url_replace_to: Optional[str] = None,
    create_disabled: bool = True,
    dry_run: bool = True,
    host: Optional[str] = None,
    i_understand_this_affects_everything: bool = False,
) -> WriteResult:
    """Clone every matched event to a new target (and optionally a new
    category and/or a different Cronicle host).

    Replaces bulk_clone_events.sh and the seed_schedule2.py script.

    Defaults:
      - dest_category_id  = same as source (clone within the same category)
      - dest_host         = same as source (clone within the same Cronicle instance)
      - create_disabled   = True (clones land disabled until you enable them)

    Common patterns:

    Same-host, different target (typical "ums-0 -> ums-3" clone):
      filter            = mode='category_and_target', cat=UMS, tgt=<UMS-0 id>
      dest_target_id    = <UMS-3 group id>
      title_replace_from='ums-0-', title_replace_to='ums-3-'
      url_replace_from='ums-schedule.osl.team', url_replace_to='ums-schedule-3.osl.team'

    Cross-host seeding (production -> test):
      host='schedule', dest_host='schedule2'
      filter=mode='category_and_target', cat=..., tgt=...
      dest_category_id=..., dest_target_id=...
      title_replace_from='ums-3-', title_replace_to='test-'

    Title and URL replacement use Python str.replace() -- substring match,
    not regex. Pass both _from and _to (or neither). Skipping URL transform
    keeps the original URL, which is fine if dest events stay disabled.

    SAFETY: filter.mode='all' is blocked unless i_understand_this_affects_everything=True.
    """
    if (title_replace_from is None) != (title_replace_to is None):
        raise ValueError(
            "cronicle_clone_events: title_replace_from and title_replace_to must both be set, or neither"
        )
    if (url_replace_from is None) != (url_replace_to is None):
        raise ValueError(
            "cronicle_clone_events: url_replace_from and url_replace_to must both be set, or neither"
        )
    _guard_all_mode(filter, i_understand_this_affects_everything, "cronicle_clone_events")

    src_hc = _resolve_host(host)
    dst_hc = _resolve_host(dest_host) if dest_host else src_hc

    with CronicleClient(src_hc) as src_client:
        events = src_client.list_events()
    matched = [e for e in events if filter.matches(e)]
    summaries = [_to_summary(e) for e in matched]

    # Build all clone payloads up front so dry_run shows the same data
    # the execute path would use.
    clone_specs: list[tuple[dict, str, str, str, str]] = []
    for e in matched:
        spec = build_clone_payload(
            e,
            dst_category=dest_category_id or e.get("category", ""),
            dst_target=dest_target_id,
            title_replace_from=title_replace_from,
            title_replace_to=title_replace_to,
            url_replace_from=url_replace_from,
            url_replace_to=url_replace_to,
            force_disabled=create_disabled,
        )
        clone_specs.append(spec)

    if dry_run:
        notes = [
            f"Would clone {len(matched)} events: '{src_hc.name}' -> '{dst_hc.name}'",
            f"Destination: cat={dest_category_id or '(same as source)'}  tgt={dest_target_id}",
            f"Disabled state: {'forced disabled' if create_disabled else 'inherit from source'}",
        ]
        for _, old_title, new_title, old_url, new_url in clone_specs[:3]:
            notes.append(f"  '{old_title}' -> '{new_title}'")
            if old_url and new_url and new_url != old_url:
                notes.append(f"    url: '{old_url[:50]}...' -> '{new_url[:50]}...'")
        if len(clone_specs) > 3:
            notes.append(f"  ... ({len(clone_specs) - 3} more)")
        notes.append("Re-call with dry_run=False to apply.")
        return WriteResult(
            host=dst_hc.name,
            executed=False,
            matched_count=len(matched),
            matched=summaries,
            notes=notes,
        )

    succeeded, failed = 0, 0
    errors: list[str] = []
    new_ids: list[str] = []
    with CronicleClient(dst_hc) as dst_client:
        for payload, _old_t, new_title, _old_u, _new_u in clone_specs:
            try:
                new_id = dst_client.create_event(payload)
                new_ids.append(new_id)
                succeeded += 1
            except CronicleAPIError as ex:
                failed += 1
                if "already exists" in (ex.description or "").lower():
                    errors.append(f"DUPLICATE TITLE: {new_title}")
                else:
                    errors.append(f"{new_title}: {ex.description}")
            except Exception as ex:
                failed += 1
                errors.append(f"{new_title}: {type(ex).__name__}: {ex}")
            time.sleep(dst_hc.rate_limit_delay_ms / 1000.0)

    return WriteResult(
        host=dst_hc.name,
        executed=True,
        matched_count=len(matched),
        matched=summaries,
        succeeded=succeeded,
        failed=failed,
        errors=errors,
        notes=[
            f"cloned {succeeded} events to '{dst_hc.name}' (cat={dest_category_id or '(same)'}, tgt={dest_target_id})",
            f"first new ids: {new_ids[:5]}{'...' if len(new_ids) > 5 else ''}",
        ],
    )


@mcp.tool()
def cronicle_import_xml_tasks(
    xml_dir: str,
    category_id: str,
    target_id: str,
    title_prefix: str = "",
    plugin_timeout_seconds: int = 1200,
    job_timeout_seconds: int = 3600,
    create_disabled: bool = True,
    dry_run: bool = True,
    host: Optional[str] = None,
) -> WriteResult:
    """Import a directory of Windows Task Scheduler XML files as Cronicle events.

    Replaces bulk_import_xml.sh + parse_xml.py. Each .xml file in xml_dir
    becomes one Cronicle event with:
      - title = title_prefix + URI's last path segment
      - URL = first http(s) found in Actions/Exec/Arguments
      - timing = mapped from Repetition/Interval (PT1M..PT12H, P1D, PT24H)
      - plugin = urlplug (HTTP GET), headers="User-Agent: Cronicle/1.0"

    Files with unrecognized intervals default to PT2M (every 2 minutes) and
    show up as warnings in the result -- review them in the Cronicle UI.

    Args:
      xml_dir: filesystem path to directory containing .xml files (non-recursive)
      category_id: destination category (must already exist)
      target_id: destination server group (must already exist)
      title_prefix: e.g. "ums-7-" (prepended to every imported title)
      plugin_timeout_seconds: written as params.timeout (string seconds, default 1200)
      job_timeout_seconds: written as top-level timeout (int seconds, default 3600)
      create_disabled: True (default) means imported events land disabled
      dry_run: True (default) -- preview parsed files + intervals
      host: Cronicle host to import to (default = default host)

    Always preview with dry_run=True first to catch parse errors and review
    the interval distribution before mass-creating events.
    """
    src_dir = Path(xml_dir).expanduser().resolve()
    if not src_dir.is_dir():
        raise ValueError(f"xml_dir does not exist or is not a directory: {src_dir}")

    xml_files = sorted(src_dir.glob("*.xml"))
    if not xml_files:
        raise ValueError(f"no .xml files found in {src_dir}")

    hc = _resolve_host(host)

    # Parse + build all payloads up front so dry_run matches execute exactly.
    payloads: list[tuple[Path, Optional[dict], Optional[str], bool]] = []
    interval_counter: Counter = Counter()
    for f in xml_files:
        try:
            task = parse_windows_xml_task(f)
        except Exception as e:
            payloads.append((f, None, f"{type(e).__name__}: {e}", False))
            continue

        if not task.url:
            payloads.append((f, None, "no URL found in Actions/Exec/Arguments", False))
            continue

        timing, warned = xml_interval_to_timing(
            task.interval, task.start_hour, task.start_minute
        )
        interval_counter[task.interval] += 1
        body = {
            "title": f"{title_prefix}{task.name}",
            "enabled": 0 if create_disabled else 1,
            "category": category_id,
            "target": target_id,
            "algo": "random",
            "plugin": "urlplug",
            "timezone": hc.timezone,
            "timing": timing,
            "params": {
                "method": "GET",
                "url": task.url,
                "headers": "User-Agent: Cronicle/1.0",
                "data": "",
                "timeout": str(plugin_timeout_seconds),
                "follow": 0,
                "ssl_cert_bypass": 0,
                "parse_auth": 0,
                "success_match": "",
                "error_match": "",
            },
            "max_children": 1,
            "timeout": int(job_timeout_seconds),
            "catch_up": 0,
            "queue_max": 1000,
            "retries": 0,
            "retry_delay": 0,
            "log_expire_days": 7,
            "detached": 0,
            "queue": 0,
            "notes": (
                f"Migrated from Windows Task XML: {f.name} "
                f"(interval: {task.interval}, "
                f"start: {task.start_hour:02d}:{task.start_minute:02d})"
            ),
        }
        payloads.append((f, body, None, warned))

    parseable = sum(1 for _, p, _, _ in payloads if p is not None)
    parse_errors = [(f.name, err) for f, p, err, _ in payloads if p is None]
    warned = sum(1 for _, _, _, w in payloads if w)

    if dry_run:
        notes = [
            f"Found {len(xml_files)} XML files in {src_dir}",
            f"Parseable: {parseable}",
            f"Parse errors: {len(parse_errors)}",
            f"Unknown intervals (defaulted to PT2M, will warn on apply): {warned}",
            f"Destination: host={hc.name}  cat={category_id}  tgt={target_id}",
            f"Title prefix: {title_prefix!r}",
            f"Disabled state: {'disabled' if create_disabled else 'enabled'}",
            f"Plugin timeout: {plugin_timeout_seconds}s   Job timeout: {job_timeout_seconds}s",
        ]
        if interval_counter:
            notes.append("Interval distribution: " + ", ".join(
                f"{iv}={n}" for iv, n in interval_counter.most_common()
            ))
        for f, p, err, w in payloads[:5]:
            if p is None:
                notes.append(f"  ERR  {f.name}: {err}")
            else:
                marker = "WARN " if w else "OK   "
                notes.append(f"  {marker}  {p['title'][:50]:50}  timing={p['timing']}")
        if len(payloads) > 5:
            notes.append(f"  ... ({len(payloads) - 5} more)")
        notes.append("Re-call with dry_run=False to apply.")
        return WriteResult(
            host=hc.name,
            executed=False,
            matched_count=parseable,
            matched=[],  # XML files aren't existing events, no EventSummary to populate
            errors=[f"{n}: {e}" for n, e in parse_errors],
            notes=notes,
        )

    succeeded, failed = 0, 0
    errors: list[str] = [f"{n}: {e}" for n, e in parse_errors]
    failed += len(parse_errors)

    with CronicleClient(hc) as client:
        for f, body, parse_err, _w in payloads:
            if body is None:
                continue  # already counted in parse_errors
            try:
                client.create_event(body)
                succeeded += 1
            except CronicleAPIError as ex:
                failed += 1
                errors.append(f"{f.name}: {ex.description}")
            except Exception as ex:
                failed += 1
                errors.append(f"{f.name}: {type(ex).__name__}: {ex}")
            time.sleep(hc.rate_limit_delay_ms / 1000.0)

    notes = [
        f"imported {succeeded} events to '{hc.name}' ({failed} failed)",
        f"destination: cat={category_id} tgt={target_id}",
    ]
    if warned:
        notes.append(
            f"{warned} event(s) had unknown intervals -- defaulted to PT2M, review in UI"
        )
    return WriteResult(
        host=hc.name,
        executed=True,
        matched_count=parseable,
        matched=[],
        succeeded=succeeded,
        failed=failed,
        errors=errors,
        notes=notes,
    )


def _summarize_job(j: dict) -> dict:
    """Project a Cronicle active-job dict to the useful subset, computing elapsed."""
    now = j.get("now")
    start = j.get("time_start")
    elapsed = (
        int(now - start) if isinstance(now, (int, float)) and isinstance(start, (int, float))
        else None
    )
    return {
        "id": j.get("id"),
        "event": j.get("event"),
        "event_title": j.get("event_title"),
        "category": j.get("category"),
        "category_title": j.get("category_title"),
        "target": j.get("target"),
        "nice_target": j.get("nice_target"),
        "hostname": j.get("hostname"),
        "plugin": j.get("plugin"),
        "pid": j.get("pid"),
        "elapsed_seconds": elapsed,
        "lag_seconds": j.get("lag"),
        "log_file": j.get("log_file"),
        "log_file_size": j.get("log_file_size"),
        "detached": bool(j.get("detached")),
    }


@mcp.tool()
def cronicle_get_active_jobs(host: Optional[str] = None) -> list[dict]:
    """List currently in-progress (running) jobs on a host.

    Returns one entry per job with: id (j*), event (parent emo*), event_title,
    category + category_title, target + nice_target (friendly group name),
    hostname (worker), plugin, pid, elapsed_seconds, lag_seconds, log_file,
    detached. Sorted longest-running first.

    The Cronicle server scrubs `params` from this response (may contain
    secrets), so it isn't included.

    Use before cronicle_abort_job / cronicle_abort_jobs to see what's running
    and pick what to kill.
    """
    hc = _resolve_host(host)
    with CronicleClient(hc) as client:
        jobs = client.get_active_jobs()

    rows = [_summarize_job(j) for j in jobs.values()]
    rows.sort(key=lambda r: r.get("elapsed_seconds") or 0, reverse=True)
    return rows


@mcp.tool()
def cronicle_abort_job(job_id: str, host: Optional[str] = None) -> dict:
    """Abort ONE specific running job by job id.

    Requires the API key to have `abort_events` privilege (in addition to
    manager). If you get back code='session' or 'priv', that's the cause --
    fix in Cronicle UI -> Admin -> API Keys.

    job_id is a `j*` id from cronicle_get_active_jobs (NOT the event id `emo*`).
    To abort by event filter (e.g. all running UMS-3 jobs), use
    cronicle_abort_jobs instead.

    Cronicle sets no_rewind=1 server-side for manual aborts so the schedule
    cursor doesn't move backward.
    """
    if not job_id or not job_id.strip():
        raise ValueError("cronicle_abort_job: job_id is required")
    hc = _resolve_host(host)
    with CronicleClient(hc) as client:
        client.abort_job(job_id.strip())
    return {"host": hc.name, "aborted_job_id": job_id, "ok": True}


@mcp.tool()
def cronicle_abort_jobs(
    event_id: Optional[str] = None,
    category_id: Optional[str] = None,
    target_id: Optional[str] = None,
    plugin: Optional[str] = None,
    no_rewind: bool = True,
    dry_run: bool = True,
    host: Optional[str] = None,
) -> WriteResult:
    """Bulk abort all running jobs matching a filter (event / category / target / plugin).

    Requires the API key to have `abort_events` privilege.

    At least one filter field MUST be set -- this tool will not abort
    everything by accident. Detached jobs are NOT aborted (server policy).

    Common patterns:
      "abort all running jobs of event emoXXX"  -> event_id=emoXXX
      "kill everything running on target gmoYYY" -> target_id=gmoYYY
      "stop all urlplug jobs on UMS-3"          -> target_id=UMS-3 id, plugin='urlplug'

    no_rewind=True (default) means the schedule cursor doesn't move back,
    so the next scheduled run happens normally. Set False to let `catch_up`
    re-trigger the aborted occurrence.

    Always defaults to dry_run=True. Dry-run path fetches active jobs and
    filters client-side to preview what WOULD be aborted (count + ids).
    """
    if not any([event_id, category_id, target_id, plugin]):
        raise ValueError(
            "cronicle_abort_jobs: at least one of event_id, category_id, "
            "target_id, or plugin must be set (refusing to abort everything)"
        )
    hc = _resolve_host(host)

    # Build filter params dict in the shape Cronicle's abort_jobs expects.
    filter_params: dict[str, str] = {}
    if event_id:
        filter_params["event"] = event_id
    if category_id:
        filter_params["category"] = category_id
    if target_id:
        filter_params["target"] = target_id
    if plugin:
        filter_params["plugin"] = plugin

    with CronicleClient(hc) as client:
        active = client.get_active_jobs()
        # Mirror server's matching: AND across all given fields. Skip detached.
        matched = []
        for j in active.values():
            if j.get("detached"):
                continue
            if all(j.get(k) == v for k, v in filter_params.items()):
                matched.append(j)

        if dry_run:
            preview = [_summarize_job(j) for j in matched]
            return WriteResult(
                host=hc.name,
                executed=False,
                matched_count=len(matched),
                matched=[],  # not EventSummary objects -- jobs are different shape
                notes=[
                    f"Would abort {len(matched)} running job(s) matching {filter_params}.",
                    f"no_rewind={no_rewind}",
                    *[
                        f"  job={p['id']}  '{p['event_title']}'  elapsed={p['elapsed_seconds']}s  on {p['hostname']}"
                        for p in preview[:10]
                    ],
                    *(["  ..."] if len(preview) > 10 else []),
                    "Re-call with dry_run=False to abort.",
                ],
            )

        if not matched:
            return WriteResult(
                host=hc.name, executed=True,
                matched_count=0, matched=[],
                notes=["No matching active jobs to abort."],
            )

        # Execute via server-side bulk abort
        try:
            client.abort_jobs(filter_params, no_rewind=1 if no_rewind else 0)
            return WriteResult(
                host=hc.name,
                executed=True,
                matched_count=len(matched),
                matched=[],
                succeeded=len(matched),
                notes=[f"Sent abort for {len(matched)} job(s) matching {filter_params}."],
            )
        except CronicleAPIError as ex:
            return WriteResult(
                host=hc.name, executed=True,
                matched_count=len(matched), matched=[],
                failed=len(matched),
                errors=[ex.description or str(ex)],
                notes=["abort_jobs API call failed -- no jobs were aborted"],
            )


@mcp.tool()
def cronicle_list_targets(host: Optional[str] = None) -> dict:
    """Return the friendly-name -> server-group-id map configured for a host.

    Cronicle Edge does NOT expose get_server_groups, so this map is maintained
    manually in .config/hosts.json under each host's "groups" key. Use this
    tool to look up a target ID before calling tools that need target_id
    (cronicle_move_events, cronicle_list_events with target_only filter, etc.).

    Returns:
      {
        "host": "schedule",
        "groups": {"UMS-0": "gmofkmxjpy4", "UMS-3": "gmofejw40q7", ...},
        "note": "..."  // present when the map is empty or has placeholder entries
      }

    If a target ID shows up in cronicle_summarize_schedule's `unknown_targets`,
    add it to hosts.json so future runs can name it properly.
    """
    hc = _resolve_host(host)
    out: dict[str, Any] = {"host": hc.name, "groups": dict(hc.groups)}
    if not hc.groups:
        out["note"] = (
            "No groups configured for this host. Add them to "
            ".config/hosts.json under hosts." + hc.name + ".groups."
        )
    else:
        placeholders = [k for k in hc.groups if k.startswith("unknown-")]
        if placeholders:
            out["note"] = (
                f"{len(placeholders)} target(s) still have placeholder names "
                f"(unknown-*). Rename them in hosts.json once you know the "
                f"real names from the Cronicle UI."
            )
    return out


@mcp.tool()
def cronicle_list_categories(host: Optional[str] = None) -> list[dict]:
    """List all categories on a host. Returns id, title, description, color, max_children.

    Categories group events by purpose ("Auto Blank Detection", "ETL Jobs", etc.).
    Useful when the user asks "what categories exist on schedule2" or before
    creating an event that needs an existing category id.
    """
    hc = _resolve_host(host)
    with CronicleClient(hc) as client:
        rows = client.list_categories()
    # Return the most useful fields, drop noisy internals.
    keys = ("id", "title", "description", "color", "max_children", "enabled", "created", "modified")
    return [{k: r.get(k) for k in keys if k in r} for r in rows]


@mcp.tool()
def cronicle_create_category(
    title: str,
    description: str = "",
    color: str = "blue",
    max_children: int = 1,
    host: Optional[str] = None,
) -> dict:
    """Create a new category on a host. Returns {id, title}.

    Requires the API key to have ADMIN privilege (not just manager). If you
    get back code='session' with description about admin, that's the cause --
    fix the privilege in Cronicle UI -> Admin -> API Keys.

    Common use:
      "create category Auto Blank Detection on schedule2"
      "mirror these schedule categories to schedule2"

    Args:
      title: human-readable name. Required.
      description: optional one-liner shown in the UI.
      color: UI badge color. One word, e.g. "blue", "red", "green", "orange".
      max_children: how many concurrent jobs this category allows. 1 is safe default.
      host: configured host name (defaults to default host).
    """
    hc = _resolve_host(host)
    with CronicleClient(hc) as client:
        new_id = client.create_category(
            title=title,
            description=description or None,
            color=color,
            max_children=max_children,
        )
    return {"id": new_id, "title": title, "host": hc.name}


@mcp.tool()
def cronicle_create_server_group(
    title: str,
    regexp: str = "^nomatch$",
    host: Optional[str] = None,
) -> dict:
    """Create a new server group (target) on a host. Returns {id, title, regexp}.

    Requires the API key to have ADMIN privilege.

    A server group is identified by a JS regex that matches server hostnames.
    The default "^nomatch$" creates a group that no real server will ever
    satisfy -- safe for test/seeding setups where events should never actually
    run, even if accidentally enabled.

    To match real servers, pass an explicit regexp:
      ".*"                       -> any server
      "^ums-7-.*"                -> hosts starting with ums-7-
      "^prod-[0-9]+\\.example$"  -> exact pattern

    Note: Cronicle Edge does NOT expose get_server_groups, so the only way
    to know a group's id after creation is the response from this tool. Save
    it (the user can also see it in Cronicle UI -> Admin -> Servers).
    """
    hc = _resolve_host(host)
    with CronicleClient(hc) as client:
        new_id = client.create_server_group(title=title, regexp=regexp)
    return {"id": new_id, "title": title, "regexp": regexp, "host": hc.name}


@mcp.tool()
def cronicle_list_hosts() -> dict:
    """List configured Cronicle hosts and which one is the default.

    Returns the names + base URLs only — never API keys. Useful when the user
    asks 'what hosts are configured?' or before passing a `host` argument.
    """
    cfg = _cfg()
    return {
        "default": cfg.default_host,
        "hosts": [
            {"name": h.name, "base_url": h.base_url, "timezone": h.timezone}
            for h in cfg.hosts.values()
        ],
    }


def main() -> None:
    """Entry point for the `cronicle-mcp` console script. Stdio transport."""
    # Stdio MCP requires stdout to carry only protocol JSON. Silence httpx
    # access logs and route any other logs to stderr.
    import logging
    import sys

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    mcp.run()


if __name__ == "__main__":
    main()
