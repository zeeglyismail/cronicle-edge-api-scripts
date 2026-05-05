# cronicle-mcp

A Model Context Protocol (MCP) server that exposes **Cronicle (Edge Fork)**
operations as conversational tools in Claude Desktop or the Claude Code CLI.

Replaces ~10 hand-edited bash scripts (in the parent folder) with a single
MCP that you talk to in plain English: list events, clone between targets,
toggle, move, change schedule/timeout, delete with safety, import Windows
Task XMLs, abort running jobs, and manage categories/server groups.

**18 tools across 4 groups: read-only, setup, mutations, runtime job control.**

---

## Quick start

1. Install dependencies (one-time):
   ```bash
   cd C:\Users\ismai\Downloads\cronicle-edge-api-scripts\cronicle-mcp
   uv sync
   ```
2. Edit `.config\api_keys.json` and put your real API keys per host.
3. Wire into Claude Desktop **or** Claude Code CLI (sections below).
4. Restart the client (full quit, not just window close).
5. Talk to it.

---

## Requirements

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** for project management
- **A Cronicle API key** with these privileges:
  - `event_list` (manager) — read tools
  - `event_create` / `event_modify` / `event_delete` — write tools
  - `cat_admin` / `grp_admin` — `cronicle_create_category` / `cronicle_create_server_group`
  - `abort_events` — `cronicle_abort_job` / `cronicle_abort_jobs`
- **Network access** to your Cronicle host(s) over HTTPS

You don't need every privilege. Tools that need a privilege you lack will
return a clear error; everything else still works.

---

## Configuration

Two files in `.config\` (both git-ignored). Keep them out of source control.

### `.config\hosts.json` — base URLs, timezone, default host, target name map

```json
{
  "default": "schedule",
  "hosts": {
    "schedule": {
      "base_url": "https://schedule.osl.team",
      "timezone": "Asia/Dhaka",
      "request_timeout": 30,
      "rate_limit_delay_ms": 100,
      "groups": {
        "UMS-0": "gmofkmxjpy4",
        "UMS-3": "gmofejw40q7"
      }
    },
    "schedule2": {
      "base_url": "https://schedule2.osl.team",
      "timezone": "Asia/Dhaka",
      "groups": {
        "UMS-6": "gmos3w3e710",
        "UMS-1": "gmos50k4w1z"
      }
    }
  }
}
```

The `groups` map is **manual** because Cronicle Edge has no `get_server_groups`
endpoint. Paste `gmoXXX` IDs from the Cronicle UI (Admin → Servers → click a
group → modal shows the ID). Tools that show targets (`summarize_schedule`,
`get_active_jobs`) display the friendly name where known. Tools that take
`target_id` as input still expect the raw `gmoXXX` ID — Claude can look it
up via `cronicle_list_targets` and pass the right one.

### `.config\api_keys.json` — the only file you edit on key rotation

```json
{
  "schedule":  "054ac51662da079a6a1cc91a68f50b1e",
  "schedule2": "PASTE_KEY_HERE"
}
```

Both files have `.example.json` templates committed. Copy them and fill in
real values.

If a key file is missing or contains a `REPLACE_*` placeholder, the server
fails at first tool call with a clear message naming the file to fix. The
API key is never written to logs, error messages, or `repr()` output.

### Where the config files live

By default, the MCP looks for `.config\` next to its source (i.e. the
`cronicle-mcp/.config/` directory in this repo). Override with the env var
`CRONICLE_MCP_CONFIG_DIR` if you want config elsewhere.

---

## Setup: Claude Desktop

Edit `%APPDATA%\Claude\claude_desktop_config.json` and add a `cronicle`
entry under `mcpServers`:

```json
{
  "mcpServers": {
    "cronicle": {
      "command": "C:\\Users\\ismai\\.local\\bin\\uv.exe",
      "args": [
        "--directory",
        "C:\\Users\\ismai\\Downloads\\cronicle-edge-api-scripts\\cronicle-mcp",
        "run",
        "cronicle-mcp"
      ]
    }
  }
}
```

Notes:
- Run `where uv` in a terminal to find the absolute path on your machine.
- Backslashes in Windows paths must be escaped (`\\`).
- **Fully quit Claude Desktop** (system tray → right-click → Quit) and reopen.
  Closing the window doesn't restart the MCP child processes.
- Click the tool icon at the bottom of a chat — `cronicle` should show 18
  tools.

To verify outside Claude Desktop:

```bash
C:\Users\ismai\.local\bin\uv.exe --directory C:\Users\ismai\Downloads\cronicle-edge-api-scripts\cronicle-mcp run cronicle-mcp
```

Should sit there waiting for stdin input (Ctrl+C to exit). Any traceback
that prints first is a config error to fix.

---

## Setup: Claude Code CLI

One command, registers globally for every project:

```bash
claude mcp add cronicle -- uv --directory C:/Users/ismai/Downloads/cronicle-edge-api-scripts/cronicle-mcp run cronicle-mcp
```

Verify:

```bash
claude mcp list
# expected: cronicle  Connected
```

Then `claude` from any directory and the tools are available.

---

## Tools (18 total)

### Read-only

| Tool | Purpose |
|---|---|
| `cronicle_list_hosts` | Show configured hosts and which is default. Never returns API keys. |
| `cronicle_list_events` | List events matching an `EventFilter`. Compact summaries (id, title, category, target, enabled, plugin, timing). |
| `cronicle_get_event` | Full event payload by id (params, timing, all timeouts, notes, etc.). |
| `cronicle_summarize_schedule` | Counts grouped by category, by target, by (category, target). Resolves friendly names. Best orientation tool. |
| `cronicle_list_categories` | All categories on a host (id, title, description, color). |
| `cronicle_list_targets` | Friendly-name → server-group-id map for a host (from `hosts.json` — Cronicle Edge has no list API for groups). |
| `cronicle_get_active_jobs` | Currently in-progress jobs with friendly category/target names + elapsed time. |

### Setup (admin privilege required)

| Tool | Purpose |
|---|---|
| `cronicle_create_category` | Create a category (returns new id). |
| `cronicle_create_server_group` | Create a server group / target (returns new id). Default `regexp="^nomatch$"` makes it a safe "no servers match" group. |

### Mutations (`dry_run=True` by default; `mode="all"` blocked unless `i_understand_this_affects_everything=True`)

| Tool | Replaces | Purpose |
|---|---|---|
| `cronicle_toggle_events` | `bulk_toggle_events.sh` + `bulk_toggle_by_target.sh` | Bulk enable/disable. |
| `cronicle_move_events` | `bulk_move_category.sh` + `bulk_move_ums3.sh` | Bulk move to new category and/or target. |
| `cronicle_update_schedule` | `bulk_update_schedule.sh` | Change timing. Presets: `1m`, `2m`, `3m`, `5m`, `10m`, `15m`, `20m`, `30m`, `1h`, `2h`, `3h`, `4h`, `6h`, `8h`, `12h`, `daily`. |
| `cronicle_update_timeouts` | `bulk_update_timeout.sh` | Plugin timeout (`params.timeout`, string seconds) and/or job timeout (`timeout`, int seconds). GET-modify-PUT preserves other plugin params. |
| `cronicle_delete_events` | `bulk_delete_events.sh` + `bulk_delete_category.sh` | Delete. **Extra safety**: `confirm_count` must equal matched count exactly when `dry_run=False`. |
| `cronicle_clone_events` | `bulk_clone_events.sh` (and `seed_schedule2.py`) | Clone to a new target / category / host. Title and URL substring replacements. |
| `cronicle_import_xml_tasks` | `bulk_import_xml.sh` + `parse_xml.py` | Import a directory of Windows Task Scheduler XML files. UTF-16 BOM aware. Maps Windows intervals (`PT5M`, `P1D`, ...) to Cronicle timing. |

### Runtime job control (`abort_events` privilege required for the abort pair)

| Tool | Purpose |
|---|---|
| `cronicle_abort_job` | Abort one running job by job id (`j*`). |
| `cronicle_abort_jobs` | Bulk abort by `event_id` / `category_id` / `target_id` / `plugin`. At least one filter required (refuses to abort everything). `dry_run=True` default. |

---

## Filter model

Most tools take an `EventFilter`:

```python
{
  "mode": "target_only" | "category_only" | "category_and_target" | "all",
  "category_id": "cmoXXXXXXXX",   # required for category_only and category_and_target
  "target_id":   "gmoXXXXXXXX"    # required for target_only and category_and_target
}
```

`mode="all"` matches every event — useful for orientation, dangerous for
mutations. Tools refuse it unless you also pass
`i_understand_this_affects_everything=True`.

---

## Mutation contract

Every mutation tool returns a `WriteResult`:

```json
{
  "host": "schedule2",
  "executed": false,
  "matched_count": 34,
  "matched": [ /* EventSummary objects */ ],
  "succeeded": 0,
  "failed": 0,
  "errors": [],
  "notes": ["Would enable 34 events ...", "Re-call with dry_run=False to apply."]
}
```

Workflow Claude follows naturally:
1. First call with `dry_run=True` (the default) — gets `matched_count` and a
   preview.
2. Re-call with `dry_run=False` to apply.
3. For `cronicle_delete_events`, also pass `confirm_count=<matched_count>`.

---

## Multi-host

Every tool takes an optional `host` argument naming a host from
`hosts.json`. Without it, the default host is used.

```
> list events on schedule2
> compare summary of schedule and schedule2
> clone the 34 events from schedule.UMS.UMS-3 to schedule2.Storage.UMS-6, prefix "test-"
```

Cross-host clones (`cronicle_clone_events` with `dest_host`) work end-to-end.

---

## Examples

```
# Orientation
> what hosts are configured?
> summarize the schedule on schedule
> what targets are on schedule2?
> what's running right now on schedule?

# Read drilldown
> list all events in the UMS category on UMS-3
> get full details for emoqxlu74u1
> show me events with timing "every minute"

# Bulk mutations (all default to dry-run)
> dry-run disabling all events on schedule2's UMS-6 target
> actually do it
> change all UMS-3 events to run every 10 minutes
> set plugin timeout to 600 and job timeout to 1800 on UMS-1
> dry-run deleting all schedule2 UMS-6 events

# Cloning
> clone schedule's UMS.UMS-0 events to UMS-3, replace "ums-0-" with "ums-3-"
   and "ums-schedule.osl.team" with "ums-schedule-3.osl.team", create disabled
> verify the clones landed disabled

# XML import
> dry-run importing ../xml_task to schedule2 Storage/UMS-6 with prefix "imported-"
> tell me which intervals appear in those XMLs
> actually import them, all disabled

# Job control
> what jobs are running on schedule with elapsed > 60 seconds?
> abort job jmos5telp6s
> dry-run aborting all running jobs on UMS-3
> abort all urlplug jobs on the Portal category
```

---

## Safety model

- **`dry_run=True`** is the default for every mutation tool.
- **`mode="all"`** filter is blocked unless
  `i_understand_this_affects_everything=True` is also passed.
- **`cronicle_delete_events`** additionally requires
  `confirm_count` to equal the live matched count when `dry_run=False`.
  Mismatch is rejected with an error explaining the drift.
- **`cronicle_abort_jobs`** refuses to run with no filter at all (won't
  abort every running job by accident).
- **API key** is never logged, never appears in `repr()`, never echoed in
  error tracebacks.

---

## Troubleshooting

**MCP shows as "failed" or doesn't appear**
Run the entry directly to see the actual error:
```bash
uv --directory C:\Users\ismai\Downloads\cronicle-edge-api-scripts\cronicle-mcp run cronicle-mcp
```
It should sit waiting for stdin. Any traceback that prints first is the bug.

**`Missing .../hosts.json`**
Copy `.config\hosts.example.json` to `.config\hosts.json`.

**`No API key for host 'X'`**
Edit `.config\api_keys.json` and set the key for X. Make sure it's not
still the `REPLACE_WITH_API_KEY` placeholder.

**`code='session'` or "unauthorized"**
Your API key is wrong, revoked, or doesn't have the privilege the tool
needs. Check Cronicle UI → Admin → API Keys. The exact privilege needed
per tool is in the table above.

**`Unsupported API`**
You hit an endpoint that doesn't exist on Cronicle Edge. Known case:
`get_server_groups` (use `cronicle_list_targets` from the manual map
in `hosts.json` instead).

**Got "Event with title \"...\" already exists"**
Cronicle title uniqueness. The clone/import tool will report it per-event
and continue with the rest. Pick a different title prefix.

**Tools changed but Claude doesn't see them**
You have to fully restart Claude Desktop (system tray Quit) — closing the
window keeps the MCP child running.

---

## Project layout

```
cronicle-mcp\
+-- pyproject.toml
+-- README.md             this file
+-- .gitignore            api_keys.json + hosts.json gitignored
+-- .config\
|   +-- hosts.json              your live config
|   +-- api_keys.json           your live keys
|   +-- hosts.example.json
|   +-- api_keys.example.json
+-- src\cronicle_mcp\
|   +-- server.py         FastMCP entry, all @mcp.tool() defs
|   +-- client.py         httpx wrapper + CronicleAPIError
|   +-- config.py         two-file loader, key redacted in repr
|   +-- filters.py        EventFilter (shared by every selection tool)
|   +-- timing.py         interval preset table (1m..daily)
|   +-- transforms.py     XML parsing + Windows interval map + clone payload
+-- scripts\
|   +-- seed_schedule2.py legacy one-shot seeder; cronicle_clone_events
|                         (with dest_host) replaces this
+-- tests\
```

---

## Relationship to the parent folder

The bash scripts in the parent directory (`bulk_*.sh`, `parse_xml.py`)
remain the cron-friendly fallback for scripted/scheduled automation. The
MCP is for interactive operations from Claude. Both hit the same Cronicle
API — pick whichever fits the moment.

If you only ever talk to Cronicle from Claude, you can ignore the bash
scripts entirely.
