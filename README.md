# Cronicle Automation Toolkit (bash scripts)

Hand-edited bash scripts for managing **Cronicle (Edge Fork)** at
`https://schedule.osl.team` (and any other instance) over its REST API.
Built for migration of Windows Task Scheduler jobs and bulk maintenance
across hundreds of events without touching the UI.

> **Looking for the conversational version?** A Python MCP that wraps
> all of these scripts as Claude Code / Claude Desktop tools lives in
> `cronicle-mcp/`. Same operations, no shell editing — see
> [`cronicle-mcp/README.md`](cronicle-mcp/README.md). Most users will
> prefer the MCP for interactive work; keep these scripts for cron jobs
> and CI pipelines.

---

## What's in this folder

| File | What it does |
|---|---|
| `bulk_clone_events.sh` | Clone events between targets in the same Cronicle instance, with title and URL substring transforms. |
| `bulk_delete_category.sh` | Delete every event in one category (simple, single-filter). |
| `bulk_delete_events.sh` | Delete events with a 3-mode filter (target / category / both) and `DELETE N` confirmation. |
| `bulk_import_xml.sh` | Read a directory of Windows Task Scheduler `.xml` files and create one Cronicle event per file. Uses `parse_xml.py`. |
| `bulk_move_category.sh` | Move every event in a category to a new category AND new target. |
| `bulk_move_ums3.sh` | Move every event in a category to a new target (keep category). |
| `bulk_toggle_by_target.sh` | Enable or disable every event on a target, across all categories. |
| `bulk_toggle_events.sh` | Enable or disable every event matching a category + target. |
| `bulk_update_schedule.sh` | Change schedule interval (`5m`, `1h`, `daily`, ...) on a 3-mode filter. |
| `bulk_update_timeout.sh` | Change plugin timeout and/or job timeout on a 3-mode filter. GET-modify-PUT to preserve other plugin params. |
| `parse_xml.py` | Helper used by `bulk_import_xml.sh`. Parses one Windows Task XML and prints JSON. UTF-16 BOM aware. |
| `xml_task/` | Directory of Windows Task Scheduler `.xml` files queued for import. |
| `cronicle-mcp/` | The MCP version of the toolkit. |
| `read-this.md` | Build spec for the MCP (historical context). |

---

## Prerequisites

- Linux / macOS / Git Bash on Windows (anything with `bash`, `curl`, `python3 >= 3.6`)
- A Cronicle API key with the privileges your script needs:
  - `event_list` — for read-only / discovery (every script reads first)
  - `event_create` — `bulk_clone_events.sh`, `bulk_import_xml.sh`
  - `event_modify` — every `bulk_move_*` / `bulk_toggle_*` / `bulk_update_*`
  - `event_delete` — `bulk_delete_*.sh`
- Network access to your Cronicle host

Make all scripts executable once:

```bash
chmod +x *.sh parse_xml.py
```

## Where to find IDs

Every script needs at least one ID; here's how to find each in the Cronicle UI:

| ID type | Where |
|---|---|
| **Category** (`cmoXXX`) | Admin → Categories → click a category → top of page |
| **Server Group** / target (`gmoXXX`) | Admin → Servers → click a group → modal |
| **Event** (`emoXXX`) | Edit an event → URL bar: `?sub=edit_event&id=emoXXX` |
| **API key** | Admin → API Keys → Add API Key → grant privileges → copy 32 hex chars |

---

## How every script works

Every `bulk_*.sh` follows the same shape:

1. **CONFIG block** at the top — edit values, save.
2. **Fetch** — pulls the schedule via `get_schedule/v1`.
3. **Filter** — Python one-liner narrows by category / target / both.
4. **Preview** — prints what will be affected (always prints, even in execute mode).
5. **Confirm** — most scripts require typing `yes` or `DELETE N`.
6. **Execute** — loops over matched IDs, sleeps 100ms between API calls.
7. **Summary** — counts of succeeded / failed.

Most scripts have an `EXECUTE="yes"` guard at the top — set it to anything
else (e.g. `"no"`) for a dry run that prints the preview and exits.

---

## Common config block

Variables you'll see across scripts:

| Variable | Meaning | Example |
|---|---|---|
| `API_KEY` | Cronicle API key (32 hex chars) | `054ac51662da079a6a1cc91a68f50b1e` |
| `BASE_URL` | API base, with `/api/app` suffix | `https://schedule.osl.team/api/app` |
| `CATEGORY_ID` | Category to filter on | `cmmso11u05t` |
| `TARGET_ID` | Server group (target) to filter on | `gmofejw40q7` |
| `FILTER_MODE` | `target_only` / `category_only` / `category_and_target` | `category_and_target` |
| `EXECUTE` | `"yes"` to apply, anything else for dry run | `"no"` |
| `TIMEZONE` | IANA timezone | `Asia/Dhaka` |
| `PLUGIN_TIMEOUT` | HTTP plugin timeout (seconds, string) | `1200` |
| `JOB_TIMEOUT` | Outer job kill timeout (seconds, int) | `3600` |
| `PREFIX` | Title prefix for naming convention (import only) | `ums-1-` |

---

## Script reference

Each section: what it does, the config you must edit, how to run, and
notes. Source code lives in the corresponding `.sh` file — open it to
see exact behavior.

### `bulk_import_xml.sh` + `parse_xml.py`

**Use when:** migrating Windows Task Scheduler XML jobs into Cronicle.

`parse_xml.py` extracts: task name (URI last segment), URL (from
`Actions/Exec/Arguments`), interval (`Repetition/Interval`), and
`StartBoundary` time. Handles UTF-16 BOM that Windows exports.

`bulk_import_xml.sh` walks a directory of `.xml` files, parses each, maps
the Windows interval (`PT2M`, `PT5M`, `P1D`, ...) to a Cronicle timing
JSON, and creates events via `create_event/v1`.

Edit:
```bash
API_KEY="..."
BASE_URL="https://schedule.osl.team/api/app"
CATEGORY_ID="cmo8c3a3w67"
TARGET_ID="gmofkmxjpy4"
PLUGIN_TIMEOUT="1200"
JOB_TIMEOUT="3600"
TIMEZONE="Asia/Dhaka"
PREFIX="ums-0-"
XML_DIR="./xml_task"
PARSER="./parse_xml.py"
```

Run:
```bash
./bulk_import_xml.sh
```

Pre-check prints distinct intervals found in the XMLs so you can spot
unsupported ones before importing. Asks `yes/no` to proceed. Created
events are **always disabled** — enable them in the UI or with
`bulk_toggle_events.sh` once you've verified.

Unknown intervals default to `PT2M` (every 2 minutes) and are flagged in
the output for manual review.

### `bulk_move_category.sh`

**Use when:** moving every event in a category to a different category AND
target (e.g. consolidating jobs into a new server group + category combo).

Edit:
```bash
API_KEY="..."
BASE_URL="https://schedule.osl.team/api/app"
SOURCE_CATEGORY="cmkwd9p4g01"
NEW_CATEGORY="cmogovjri2i"
NEW_TARGET="gmogoupbuqu"
```

Run:
```bash
./bulk_move_category.sh
```

No confirmation prompt. Sets both `category` and `target` on every match.

### `bulk_move_ums3.sh`

**Use when:** moving events from one target to another but keeping the
same category (e.g. failover from UMS-1 to UMS-3).

Edit:
```bash
API_KEY="..."
BASE_URL="https://schedule.osl.team/api/app"
CATEGORY_ID="cmne6hb8nql"
NEW_TARGET="gmo85s9rfqr"
```

Run:
```bash
./bulk_move_ums3.sh
```

Despite the name, it works for any source category → any new target. The
script is named after the original UMS-3 migration use case.

### `bulk_toggle_events.sh`

**Use when:** enabling or disabling every event matching a specific
category AND target.

Edit:
```bash
API_KEY="..."
BASE_URL="https://schedule.osl.team/api/app"
CATEGORY_ID="cmmso11u05t"
TARGET_ID="gmo85rxfmqq"
ACTION="enable"   # or "disable"
```

Run:
```bash
./bulk_toggle_events.sh
```

Useful before/after maintenance windows: disable a target's events,
do work, re-enable.

### `bulk_toggle_by_target.sh`

**Use when:** enabling or disabling every event on a target, regardless
of category. Coarser than `bulk_toggle_events.sh`.

Edit:
```bash
API_KEY="..."
BASE_URL="https://schedule.osl.team/api/app"
TARGET_ID="gmo85s9rfqr"
ACTION="disable"
```

Run:
```bash
./bulk_toggle_by_target.sh
```

### `bulk_update_schedule.sh`

**Use when:** rolling out a schedule interval change to a group of events
("throttle UMS-3 events to every 10 minutes").

Edit:
```bash
API_KEY="..."
BASE_URL="https://schedule.osl.team/api/app"
FILTER_MODE="target_only"   # or category_only / category_and_target
CATEGORY_ID="cmmso11u05t"
TARGET_ID="gmo85s9rfqr"
INTERVAL="5m"               # see below
START_HOUR="0"              # used by 1h+ and daily
START_MINUTE="0"            # used by 1h+ and daily
EXECUTE="yes"
```

Supported intervals:
- Sub-hour: `1m`, `2m`, `3m`, `5m`, `10m`, `15m`, `20m`, `30m`
- Hourly: `1h`, `2h`, `3h`, `4h`, `6h`, `8h`, `12h` (uses `START_MINUTE`)
- `daily` (uses both `START_HOUR` and `START_MINUTE`)

For `2h+` the hour pattern always anchors at hour 0 (`[0,2,4,...]`); if
you set `START_HOUR=3` for `4h`, the script ignores it. Only `daily`
honors `START_HOUR`.

Run:
```bash
./bulk_update_schedule.sh
```

Set `EXECUTE="no"` first to preview matches and confirm.

### `bulk_update_timeout.sh`

**Use when:** changing the HTTP plugin timeout (`params.timeout`) and/or
the outer job-kill timeout (`timeout`) on a group of events.

Edit:
```bash
API_KEY="..."
BASE_URL="https://schedule.osl.team/api/app"
FILTER_MODE="target_only"
CATEGORY_ID="cmo8c2nmj41"
TARGET_ID="gmo85s9rfqr"
NEW_PLUGIN_TIMEOUT="3600"   # string seconds (params.timeout)
NEW_JOB_TIMEOUT="3600"      # int seconds; set to "" to skip
EXECUTE="yes"
```

Run:
```bash
./bulk_update_timeout.sh
```

The script does GET → modify → PUT for each event because Cronicle
**replaces the entire `params` object on update** (no merge). Skipping
that step would wipe URL, headers, and other plugin fields.

### `bulk_delete_category.sh`

**Use when:** wiping every event in one category. Single-filter, simple.

Edit:
```bash
API_KEY="..."
BASE_URL="https://schedule.osl.team/api/app"
CATEGORY_ID="cmoff66avp7"
```

Run:
```bash
./bulk_delete_category.sh
```

Asks you to type `DELETE` (all caps) to confirm.

### `bulk_delete_events.sh`

**Use when:** deleting with a more flexible filter (target / category / both).

Edit:
```bash
API_KEY="..."
BASE_URL="https://schedule2.osl.team/api/app"
FILTER_MODE="category_and_target"
CATEGORY_ID="cmmso11u05t"
TARGET_ID="gmo85s9rfqr"
EXECUTE="yes"
```

Run:
```bash
./bulk_delete_events.sh
```

After the preview, prompts you to type `DELETE <N>` where `<N>` is the
exact matched count. Anything else cancels. This guards against the
matched set having drifted since the last preview.

### `bulk_clone_events.sh`

**Use when:** duplicating a set of events to a different target (and
optionally a different category) inside the same Cronicle instance, with
title and URL substring rewrites.

Edit:
```bash
API_KEY="..."
BASE_URL="https://schedule.osl.team/api/app"
SOURCE_CATEGORY_ID="cmmso11u05t"
SOURCE_TARGET_ID="gmofkmxjpy4"
DEST_CATEGORY_ID="cmmso11u05t"
DEST_TARGET_ID="gmofejw40q7"
SRC_TITLE_PATTERN="ums-0-"
DST_TITLE_PATTERN="ums-3-"
SRC_URL_PATTERN="ums-schedule.osl.team"
DST_URL_PATTERN="ums-schedule-3.osl.team"
CREATE_AS_DISABLED="yes"   # or "no"
EXECUTE="yes"
```

Run:
```bash
./bulk_clone_events.sh
```

Preview shows old → new title and old → new URL per event. Asks `yes` to
proceed. Cronicle rejects creates with duplicate titles, so the URL
prefix and title prefix should both be different from the source.

For **cross-instance** cloning (e.g. production → test instance), use the
MCP tool `cronicle_clone_events` with `dest_host` — this bash script only
clones within one Cronicle instance.

---

## Recommended workflows

**Migrate Windows tasks to a new Cronicle target**
1. Drop XMLs into `xml_task/`
2. Edit `bulk_import_xml.sh` config (category, target, prefix), run it
3. Inspect the imported events in the Cronicle UI
4. Edit `bulk_toggle_events.sh` (matching category + target), set
   `ACTION="enable"`, run

**Failover one target to another**
1. Edit `bulk_toggle_by_target.sh` for the failing target,
   `ACTION="disable"`, run
2. Edit `bulk_move_ums3.sh` to move events to the spare target, run
3. Re-enable on the new target if you didn't move them already-enabled

**Throttle a busy target**
1. Edit `bulk_update_schedule.sh`, set `INTERVAL="10m"`, target the
   right group, `EXECUTE="no"` first
2. Review preview, set `EXECUTE="yes"`, run

**Clean up after a botched import**
1. Edit `bulk_delete_events.sh` with `FILTER_MODE="category_and_target"`
   matching the bad import, `EXECUTE="no"` first
2. Note the matched count, set `EXECUTE="yes"`, run, type `DELETE <N>` at prompt

---

## Cronicle concepts cheat sheet

- **Event** — one scheduled job definition (id `emoXXX`). Has a category,
  a target server group, a plugin (`urlplug`, `shellplug`, etc.),
  timing, params, and two timeouts.
- **Category** (`cmoXXX`) — a tag for grouping events (e.g. "UMS",
  "Storage Sync").
- **Server Group** / **Target** (`gmoXXX`) — a regex-defined collection of
  Cronicle worker servers an event runs on.
- **Job** (`jXXX`) — one runtime execution of an event. View under
  Activity → Active Jobs.
- **Timing** — `{minutes:[...], hours:[...], weekdays:[...]}` selection
  arrays. `{}` runs every minute. No `timing` field at all means
  on-demand only.
- **Two timeouts**:
  - `params.timeout` (string seconds) — HTTP plugin's own timeout
  - `timeout` (int seconds, top-level) — outer Cronicle job kill switch

---

## Edge Fork limitations

Cronicle **Edge Fork** has API gaps the bash scripts work around:

- `get_server_groups` returns "Unsupported API". Server group IDs must
  come from the UI; you cannot enumerate them via the API.
- `update_event/v1` **replaces** `params` wholesale (no merge), so
  timeout / param changes always go GET → modify → PUT.

---

## Troubleshooting

**`"code":"session"` or `"unauthorized"`**
API key is missing, wrong, or lacks the privilege you need. Check Admin
→ API Keys.

**`"code":"event"` `"...already exists"`**
Cronicle title uniqueness was violated. Pick a different prefix in the
clone or import script.

**Script prints empty preview**
The filter matched nothing. Double-check `CATEGORY_ID` and `TARGET_ID` —
common cause is a typo or copying the wrong ID from the UI.

**Connection refused / TLS error**
Network or VPN issue, or wrong `BASE_URL` (must include `/api/app`).

**Mass operation only partly succeeded**
Each script prints per-event success/failure and a final summary. Re-run
with the same filter to retry — successes will skip (toggle, move,
update) or fail with "already exists" (clone, import).

---

## Security notes

- The 32-char API key in these scripts is in **plain text** at the top of
  each file. Don't share / commit a real key. Treat the scripts like
  configuration secrets.
- The bash scripts here historically had a key checked in (the `054ac...`
  string). Rotate it separately. If you fork this folder for your own
  use, generate a new key and edit the scripts before running.
- For unattended cron use, prefer reading the key from an env var or
  secret store and templating it into the script at deploy time.

---

## See also

- [`cronicle-mcp/README.md`](cronicle-mcp/README.md) — the MCP version.
  Same operations as conversational tools in Claude Desktop / Claude Code.
- [`read-this.md`](read-this.md) — original build spec for the MCP, kept
  for historical context.
- Cronicle Edge upstream: <https://github.com/cronicle-edge/cronicle-edge>
