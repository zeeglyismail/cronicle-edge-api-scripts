"""Cross-instance event seeder for testing the MCP safely.

Reads events matching --src-category-id and --src-target-id from the source
host, force-disables them, applies a title prefix, and creates them on the
destination host under the given dest category/target.

Defaults to dry-run. Pass --execute to actually create events.

Usage:
    uv run python scripts/seed_schedule2.py \
        --src-host schedule \
        --dst-host schedule2 \
        --src-category-id cmmso11u05t \
        --src-target-id gmofejw40q7 \
        --dst-category-id cmoXXXXXXXX \
        --dst-target-id gmoXXXXXXXX \
        --title-prefix "test-" \
        --limit 5             # optional: take only first N (useful for first run)
        # add --execute to actually write
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

from cronicle_mcp.client import CronicleAPIError, CronicleClient
from cronicle_mcp.config import load as load_config


# Fields that are unique to the source event and must NOT be carried over.
STRIP_FIELDS = ("id", "created", "modified", "username")


def build_payload(
    src_event: dict,
    dst_category: str,
    dst_target: str,
    title_prefix: str,
) -> dict[str, Any]:
    payload = dict(src_event)
    for f in STRIP_FIELDS:
        payload.pop(f, None)

    # Force disabled -- non-negotiable safety rail.
    payload["enabled"] = 0

    # Retarget to destination category/target.
    payload["category"] = dst_category
    payload["target"] = dst_target

    # Prefix the title so it's obvious in the UI which events are seeded test
    # data, and so we can never collide with real titles on dst.
    old_title = payload.get("title", "")
    payload["title"] = f"{title_prefix}{old_title}"

    # Notes annotation so anyone looking at the event in the schedule2 UI
    # immediately knows it was seeded for MCP tests.
    existing_notes = payload.get("notes", "")
    seeded_marker = "[Seeded for MCP testing -- safe to delete]"
    payload["notes"] = (
        f"{seeded_marker}\n{existing_notes}".strip()
        if existing_notes
        else seeded_marker
    )

    return payload


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--src-host", required=True, help="source host name from .config/hosts.json")
    p.add_argument("--dst-host", required=True, help="destination host name")
    p.add_argument("--src-category-id", required=True)
    p.add_argument("--src-target-id", required=True)
    p.add_argument("--dst-category-id", required=True)
    p.add_argument("--dst-target-id", required=True)
    p.add_argument("--title-prefix", default="test-")
    p.add_argument("--limit", type=int, default=0, help="0 = all matched (default)")
    p.add_argument("--execute", action="store_true", help="actually create events (default = dry run)")
    args = p.parse_args()

    cfg = load_config()
    try:
        src_host = cfg.get(args.src_host)
        dst_host = cfg.get(args.dst_host)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if src_host.name == dst_host.name:
        print("ERROR: src and dst host must be different", file=sys.stderr)
        return 2

    print("=" * 70)
    print(f"  SEED  {src_host.name}  ->  {dst_host.name}")
    print("=" * 70)
    print(f"  source: cat={args.src_category_id} tgt={args.src_target_id}")
    print(f"  dest:   cat={args.dst_category_id} tgt={args.dst_target_id}")
    print(f"  title prefix: {args.title_prefix!r}")
    print(f"  limit: {args.limit or 'all'}")
    print(f"  mode: {'EXECUTE' if args.execute else 'DRY RUN'}")
    print("=" * 70)

    with CronicleClient(src_host) as src:
        all_events = src.list_events()

    matched = [
        e for e in all_events
        if e.get("category") == args.src_category_id and e.get("target") == args.src_target_id
    ]
    if args.limit > 0:
        matched = matched[: args.limit]

    if not matched:
        print("No events matched. Check --src-category-id and --src-target-id.")
        return 1

    print(f"\nMatched {len(matched)} events on source. Preview:")
    for e in matched:
        old_title = e.get("title", "")
        new_title = f"{args.title_prefix}{old_title}"
        timing = e.get("timing")
        timing_str = "on-demand" if timing is None else (
            "every minute" if not timing else
            f"min={timing.get('minutes', '?')[:3]}{'...' if len(timing.get('minutes', [])) > 3 else ''} hr={timing.get('hours')}"
        )
        print(f"  {e.get('id')}  {old_title[:45]:45} -> {new_title[:50]:50}  {timing_str}")

    if not args.execute:
        print(f"\nDRY RUN -- no events created. Re-run with --execute to commit.")
        return 0

    print(f"\nCreating {len(matched)} events on {dst_host.name}...")
    print("-" * 70)
    succeeded = 0
    failed = 0
    skipped_duplicate = 0
    errors: list[str] = []

    with CronicleClient(dst_host) as dst:
        for i, src_event in enumerate(matched, 1):
            payload = build_payload(
                src_event,
                dst_category=args.dst_category_id,
                dst_target=args.dst_target_id,
                title_prefix=args.title_prefix,
            )
            title = payload["title"]
            try:
                result = dst._post("create_event/v1", payload)
                new_id = result.get("id", "?")
                print(f"  [{i}/{len(matched)}] OK   {new_id}  {title[:55]}")
                succeeded += 1
            except CronicleAPIError as e:
                if "already exists" in (e.description or "").lower():
                    print(f"  [{i}/{len(matched)}] SKIP (duplicate title) {title[:50]}")
                    skipped_duplicate += 1
                else:
                    print(f"  [{i}/{len(matched)}] FAIL  {title[:50]}  -- {e.description}")
                    failed += 1
                    errors.append(f"{title}: {e.description}")
            except Exception as e:
                print(f"  [{i}/{len(matched)}] FAIL  {title[:50]}  -- {type(e).__name__}: {e}")
                failed += 1
                errors.append(f"{title}: {type(e).__name__}: {e}")

            time.sleep(dst_host.rate_limit_delay_ms / 1000.0)

    print("-" * 70)
    print(f"SUMMARY:  created={succeeded}  duplicates_skipped={skipped_duplicate}  failed={failed}")
    if errors:
        print("\nFirst 5 errors:")
        for line in errors[:5]:
            print(f"  - {line}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
