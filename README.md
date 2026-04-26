# 🔧 Cronicle Automation Toolkit — Documentation

> **Internal DevOps reference** for managing Cronicle events at scale via REST API.
Cuts down hours of UI clicking to seconds of script execution.
> 

---

## 📋 Table of Contents

1. Overview & Why This Exists
2. Prerequisites
3. Common Configuration
4. Script Reference
    - 4.1 `parse_xml.py`
    - 4.2 `bulk_import_xml.sh`
    - 4.3 `bulk_move_category.sh`
    - 4.4 `bulk_move_ums3.sh`
    - 4.5 `bulk_update_timeout.sh`
    - 4.6 `bulk_toggle_events.sh`
    - 4.7 `bulk_toggle_by_target.sh`
    - 4.8 `bulk_delete_category.sh`
    - 4.9 `bulk_delete_events.sh`
5. Recommended Workflows
6. Cronicle Concepts Cheat Sheet
7. Troubleshooting
8. Security Notes
9. Quick Reference Card

---

## 1. Overview & Why This Exists

This toolkit is a collection of bash + Python scripts that automate bulk operations on **Cronicle (Edge Fork)** via its REST API. It was built to handle migration of Windows Task Scheduler jobs into Cronicle and to perform bulk maintenance operations across hundreds of events without touching the UI.

### What it covers

| Capability | Script |
| --- | --- |
| Migrate Windows `.xml` Task Scheduler files into Cronicle events | `bulk_import_xml.sh` + `parse_xml.py` |
| Bulk-move events between categories and/or targets | `bulk_move_category.sh` |
| Bulk-move events to a different target (same category) | `bulk_move_ums3.sh` |
| Bulk-update HTTP plugin timeout | `bulk_update_timeout.sh` |
| Bulk enable/disable by category + target | `bulk_toggle_events.sh` |
| Bulk enable/disable by target only (across all categories) | `bulk_toggle_by_target.sh` |
| Simple bulk delete by single category | `bulk_delete_category.sh` |
| Bulk delete with three filter modes | `bulk_delete_events.sh` |

---

## 2. Prerequisites

### Environment

- Linux/macOS terminal with `bash`
- `curl` installed
- `python3` installed (3.6+)
- Network access to Cronicle server: `https://schedule.osl.team`

### Cronicle API Key

You need an API key with these privileges:

- **create events** — for bulk import
- **edit events** — for move/update/toggle
- **delete events** — for delete operations

**To create:** Cronicle UI → Admin → API Keys → Add API Key → grant the privileges above → copy the 32-char hex string.

### Directory Layout

Recommended structure:

```
~/cronicle-toolkit/
├── parse_xml.py
├── bulk_import_xml.sh
├── bulk_move_category.sh
├── bulk_move_ums3.sh
├── bulk_update_timeout.sh
├── bulk_toggle_events.sh
├── bulk_toggle_by_target.sh
├── bulk_delete_category.sh
├── bulk_delete_events.sh
└── xml_task/              ← drop Windows Task XML files here
    ├── task1.xml
    └── task2.xml
```

After saving each script, make it executable once:

```bash
chmod +x *.sh parse_xml.py
```

---

## 3. Common Configuration

Every script has a **CONFIG block at the top**. You edit values, save, and run. Common variables:

| Variable | Description | Example |
| --- | --- | --- |
| `API_KEY` | Cronicle API key (32 hex chars) | `054ac51662da079a6a1cc91a68f50b1e` |
| `BASE_URL` | Cronicle API base URL | `https://schedule.osl.team/api/app` |
| `CATEGORY_ID` | Internal category ID | `cmmso11u05t` |
| `TARGET_ID` | Internal server group ID | `gmo85rxfmqq` |
| `PREFIX` | Title prefix for naming convention | `ums-1-` |
| `TIMEZONE` | IANA timezone string | `Asia/Dhaka` |
| `PLUGIN_TIMEOUT` | HTTP Request plugin timeout (seconds) | `1200` |
| `JOB_TIMEOUT` | Outer Cronicle job timeout (seconds) | `3600` |

### How to find IDs in Cronicle UI

- **Category ID** — Admin → Categories → click a category → top of page shows `Category ID: cmoxxxxx`
- **Server Group ID** — Admin → Servers → click a group → modal shows `Group ID: gmoxxxxx`
- **Event ID** — visible in URL when editing an event: `?sub=edit_event&id=emoxxxxx`

---

## 4. Script Reference

### 4.1 🐍 `parse_xml.py`

**Purpose:** Helper script. Parses a Windows Task Scheduler XML file and extracts the fields needed to create a Cronicle event.

**Used by:** `bulk_import_xml.sh`

**What it extracts:**

- `name` — task name (from `<URI>`, last path component)
- `url` — endpoint URL (from `<Arguments>`)
- `interval` — repetition interval (from `<Interval>`, e.g. `PT2M`, `PT1H`, `P1D`)
- `start_hour` / `start_minute` — from `<StartBoundary>` (used for hourly/daily tasks)

**Standalone usage (debugging):**

```bash
python3 parse_xml.py ./xml_task/SomeTask.xml
```

Outputs JSON like:

```json
{"name": "UmsPortal_ZoomOperations", "url": "https://...", "interval": "PT2M", "start_hour": 0, "start_minute": 0}
```

**Special handling:** Windows exports XML in UTF-16 with BOM — the parser detects and decodes correctly.

### Full Script:

```python
#!/usr/bin/env python3
import xml.etree.ElementTree as ET
import json
import re
import sys

xml_file = sys.argv[1]

try:
    with open(xml_file, "rb") as f:
        raw = f.read()

    # Handle UTF-16 BOM that Windows Task Scheduler exports
    if raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff'):
        content = raw.decode('utf-16')
    else:
        content = raw.decode('utf-8', errors='replace')

    # Strip namespace for easier XPath
    content = re.sub(r'\sxmlns="[^"]+"', '', content, count=1)
    root = ET.fromstring(content)

    # Extract URI for naming
    uri = root.find('.//URI')
    uri_text = uri.text if uri is not None else ""
    name_part = re.split(r'[\\/]', uri_text.rstrip('/\\'))[-1] if uri_text else "unknown"

    # Extract URL from Arguments
    args = root.find('.//Actions/Exec/Arguments')
    args_text = args.text if args is not None else ""
    url_match = re.search(r'(https?://[^\s"]+)', args_text)
    url = url_match.group(1) if url_match else ""

    # Extract repetition interval (for sub-day intervals)
    interval_elem = root.find('.//Repetition/Interval')
    interval = interval_elem.text if interval_elem is not None else ""

    # Extract StartBoundary (for daily/weekly tasks — gives the hour to run at)
    start_elem = root.find('.//StartBoundary')
    start_text = start_elem.text if start_elem is not None else ""
    start_hour = 0
    start_minute = 0
    if start_text:
        time_match = re.search(r'T(\d{2}):(\d{2})', start_text)
        if time_match:
            start_hour = int(time_match.group(1))
            start_minute = int(time_match.group(2))

    # Detect schedule type
    has_daily = root.find('.//ScheduleByDay') is not None
    has_weekly = root.find('.//ScheduleByWeek') is not None
    has_repetition = root.find('.//Repetition') is not None

    # Default interval if nothing detected
    if not interval and has_daily and not has_repetition:
        interval = "P1D"
    elif not interval:
        interval = "PT2M"

    print(json.dumps({
        "name": name_part,
        "url": url,
        "interval": interval,
        "start_hour": start_hour,
        "start_minute": start_minute,
        "has_daily": has_daily,
        "has_weekly": has_weekly
    }))

except Exception as e:
    print(json.dumps({"error": str(e), "name": "", "url": "", "interval": "", "start_hour": 0, "start_minute": 0}))
```

---

### 4.2 📥 `bulk_import_xml.sh`

**Purpose:** Migrate a directory of Windows Task XML files into Cronicle events.

**Workflow:**

1. Drop all `.xml` files into `./xml_task/`
2. Edit CONFIG at top of script (PREFIX, CATEGORY_ID, TARGET_ID)
3. Run

**Configuration variables:**

```bash
CATEGORY_ID="cmo8f8622n7"
TARGET_ID="gmo85s9rfqr"
PREFIX="ums-2-"
PLUGIN_TIMEOUT="1200"
JOB_TIMEOUT="3600"
TIMEZONE="Asia/Dhaka"
XML_DIR="./xml_task"
```

**Run:**

```bash
./bulk_import_xml.sh
```

**Features:**

- Pre-flight scan: lists all distinct `<Interval>` values found across XMLs
- Lists files with no `<Interval>` tag (one-off / daily-only tasks)
- Confirmation prompt before execution
- Per-file progress with ✓/✗/⚠ status
- Imports as **disabled by default** — you enable separately when ready
- Adds migration note to each event for traceability

**Interval Mapping (Windows → Cronicle):**

| Windows Interval | Cronicle Timing |
| --- | --- |
| `PT1M` | every minute |
| `PT2M` | every 2 min (`[0,2,4,…58]`) |
| `PT5M` | every 5 min (`[0,5,10,…55]`) |
| `PT10M` | every 10 min |
| `PT15M` | every 15 min |
| `PT30M` | every 30 min (`[0,30]`) |
| `PT1H` | every hour at minute=StartBoundary |
| `PT2H`/`PT3H`/`PT4H`/`PT6H`/`PT8H`/`PT12H` | every N hours, hour list explicit |
| `P1D` / `PT24H` | daily at StartBoundary time |

Unknown intervals get flagged with ⚠ in summary, default to "every 2 minutes" — review manually.

### Full Script:

```bash
#!/bin/bash

# === CONFIG ===
API_KEY="054ac51662da079a6a1cc91a68f50b1e"
BASE_URL="https://schedule.osl.team/api/app"
CATEGORY_ID="cmoff815bsp"
TARGET_ID="gmofejw40q7"
PLUGIN_TIMEOUT="1200"
JOB_TIMEOUT="3600"
TIMEZONE="Asia/Dhaka"
PREFIX="ums-6-"
XML_DIR="./xml_task"
PARSER="./parse_xml.py"

# === PRE-CHECKS ===
if [ ! -f "$PARSER" ]; then
  echo "ERROR: $PARSER not found. Make sure parse_xml.py is in the same directory."
  exit 1
fi

if [ ! -d "$XML_DIR" ]; then
  echo "ERROR: Directory $XML_DIR does not exist."
  exit 1
fi

XML_COUNT=$(find "$XML_DIR" -maxdepth 1 -name "*.xml" | wc -l)
if [ "$XML_COUNT" -eq 0 ]; then
  echo "ERROR: No .xml files found in $XML_DIR"
  exit 1
fi

# === INTERVAL DISCOVERY (helpful pre-check) ===
echo "=========================================="
echo "Distinct intervals found in your XML files:"
echo "=========================================="
grep -h '<Interval>' "$XML_DIR"/*.xml 2>/dev/null | sort -u || echo "(none found in <Interval> tags)"
echo ""
echo "Files with no <Interval> tag (daily/weekly/once-only):"
for f in "$XML_DIR"/*.xml; do
  if ! grep -q '<Interval>' "$f"; then
    echo "  - $(basename "$f")"
  fi
done
echo "=========================================="
echo ""

echo "Found $XML_COUNT XML files in $XML_DIR"
echo "Prefix:   $PREFIX"
echo "Category: $CATEGORY_ID"
echo "Target:   $TARGET_ID"
echo "---"

read -p "Proceed with import? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "Cancelled."
  exit 0
fi

COUNT=0
SUCCESS=0
FAILED=0
WARNED=0

for XML_FILE in "$XML_DIR"/*.xml; do
  COUNT=$((COUNT + 1))
  FNAME=$(basename "$XML_FILE")

  PARSED=$(python3 "$PARSER" "$XML_FILE")

  ERROR=$(echo "$PARSED" | python3 -c "import sys,json; print(json.load(sys.stdin).get('error',''))" 2>/dev/null)
  if [ -n "$ERROR" ]; then
    echo "[$COUNT/$XML_COUNT] ✗ $FNAME — Parse error: $ERROR"
    FAILED=$((FAILED + 1))
    continue
  fi

  NAME=$(echo "$PARSED" | python3 -c "import sys,json; print(json.load(sys.stdin)['name'])")
  URL=$(echo "$PARSED" | python3 -c "import sys,json; print(json.load(sys.stdin)['url'])")
  INTERVAL=$(echo "$PARSED" | python3 -c "import sys,json; print(json.load(sys.stdin)['interval'])")
  START_HOUR=$(echo "$PARSED" | python3 -c "import sys,json; print(json.load(sys.stdin)['start_hour'])")
  START_MINUTE=$(echo "$PARSED" | python3 -c "import sys,json; print(json.load(sys.stdin)['start_minute'])")

  if [ -z "$URL" ]; then
    echo "[$COUNT/$XML_COUNT] ✗ $FNAME — No URL found in XML"
    FAILED=$((FAILED + 1))
    continue
  fi

  TITLE="${PREFIX}${NAME}"
  HOURS=""
  WARN=""

  # === Map Windows interval to Cronicle timing ===
  case "$INTERVAL" in
    "PT1M")
      MINUTES="[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59]"
      ;;
    "PT2M")
      MINUTES="[0,2,4,6,8,10,12,14,16,18,20,22,24,26,28,30,32,34,36,38,40,42,44,46,48,50,52,54,56,58]"
      ;;
    "PT3M")
      MINUTES="[0,3,6,9,12,15,18,21,24,27,30,33,36,39,42,45,48,51,54,57]"
      ;;
    "PT5M")
      MINUTES="[0,5,10,15,20,25,30,35,40,45,50,55]"
      ;;
    "PT10M")
      MINUTES="[0,10,20,30,40,50]"
      ;;
    "PT15M")
      MINUTES="[0,15,30,45]"
      ;;
    "PT20M")
      MINUTES="[0,20,40]"
      ;;
    "PT30M")
      MINUTES="[0,30]"
      ;;
    "PT1H"|"PT60M")
      MINUTES="[$START_MINUTE]"
      ;;
    "PT2H")
      MINUTES="[$START_MINUTE]"
      HOURS="[0,2,4,6,8,10,12,14,16,18,20,22]"
      ;;
    "PT3H")
      MINUTES="[$START_MINUTE]"
      HOURS="[0,3,6,9,12,15,18,21]"
      ;;
    "PT4H")
      MINUTES="[$START_MINUTE]"
      HOURS="[0,4,8,12,16,20]"
      ;;
    "PT6H")
      MINUTES="[$START_MINUTE]"
      HOURS="[0,6,12,18]"
      ;;
    "PT8H")
      MINUTES="[$START_MINUTE]"
      HOURS="[0,8,16]"
      ;;
    "PT12H")
      MINUTES="[$START_MINUTE]"
      HOURS="[0,12]"
      ;;
    "P1D"|"PT24H")
      MINUTES="[$START_MINUTE]"
      HOURS="[$START_HOUR]"
      ;;
    *)
      WARN="UNKNOWN_INTERVAL_${INTERVAL}_DEFAULTED_TO_2MIN"
      MINUTES="[0,2,4,6,8,10,12,14,16,18,20,22,24,26,28,30,32,34,36,38,40,42,44,46,48,50,52,54,56,58]"
      ;;
  esac

  # Build timing JSON
  if [ -n "$HOURS" ]; then
    TIMING="{\"minutes\": $MINUTES, \"hours\": $HOURS}"
  else
    TIMING="{\"minutes\": $MINUTES}"
  fi

  # Build payload
  PAYLOAD=$(cat << EOF
{
  "title": "$TITLE",
  "enabled": 0,
  "category": "$CATEGORY_ID",
  "target": "$TARGET_ID",
  "algo": "random",
  "plugin": "urlplug",
  "timezone": "$TIMEZONE",
  "timing": $TIMING,
  "params": {
    "method": "GET",
    "url": "$URL",
    "headers": "User-Agent: Cronicle/1.0",
    "data": "",
    "timeout": "$PLUGIN_TIMEOUT",
    "follow": 0,
    "ssl_cert_bypass": 0,
    "parse_auth": 0,
    "success_match": "",
    "error_match": ""
  },
  "max_children": 1,
  "timeout": $JOB_TIMEOUT,
  "catch_up": 0,
  "queue_max": 1000,
  "retries": 0,
  "retry_delay": 0,
  "log_expire_days": 7,
  "detached": 0,
  "queue": 0,
  "notes": "Migrated from Windows Task XML: $FNAME (interval: $INTERVAL, start: ${START_HOUR}:${START_MINUTE})"
}
EOF
)

  RESULT=$(curl -s -X POST "$BASE_URL/create_event/v1" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD")

  CODE=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('code',-1))" 2>/dev/null)

  if [ "$CODE" = "0" ]; then
    NEW_ID=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))")
    if [ -n "$WARN" ]; then
      echo "[$COUNT/$XML_COUNT] ⚠ $TITLE  →  $NEW_ID  ($WARN)"
      WARNED=$((WARNED + 1))
    else
      echo "[$COUNT/$XML_COUNT] ✓ $TITLE  →  $NEW_ID  (interval: $INTERVAL, runs at minute=$START_MINUTE hour=$START_HOUR)"
    fi
    SUCCESS=$((SUCCESS + 1))
  else
    echo "[$COUNT/$XML_COUNT] ✗ $TITLE — FAILED: $RESULT"
    FAILED=$((FAILED + 1))
  fi

  sleep 0.1
done

echo ""
echo "=========================================="
echo "SUMMARY"
echo "=========================================="
echo "Total:    $COUNT"
echo "Created:  $SUCCESS"
echo "Failed:   $FAILED"
if [ "$WARNED" -gt 0 ]; then
  echo "Warnings: $WARNED  ← Review these manually in Cronicle UI!"
fi
echo "=========================================="
```

---

### 4.3 📦 `bulk_move_category.sh`

**Purpose:** Move all events from one category to another, optionally also changing the target server.

**Configuration:**

```bash
SOURCE_CATEGORY="cmnfjt0vmj8"   # move FROM this
NEW_CATEGORY="cmo8c3a3w67"      # move TO this
NEW_TARGET="gmo85s9rfqr"        # also set target to this
```

**Run:**

```bash
./bulk_move_category.sh
```

**Behavior:**

- Filters events by `category == SOURCE_CATEGORY`
- Updates each event's `category` and `target` in a single API call
- All other settings (URL, timing, params, timeout, name) stay untouched

### Full Script:

```bash
#!/bin/bash

API_KEY="054ac51662da079a6a1cc91a68f50b1e"
BASE_URL="https://schedule.osl.team/api/app"
SOURCE_CATEGORY="cmnfjt0vmj8"
NEW_CATEGORY="cmo8c3a3w67"
NEW_TARGET="gmo85s9rfqr"

echo "Fetching events in category $SOURCE_CATEGORY..."

EVENT_IDS=$(curl -s -X POST "$BASE_URL/get_schedule/v1" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"limit": 1000}' | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
for e in data['rows']:
    if e.get('category') == '$SOURCE_CATEGORY':
        print(e['id'])
")

if [ -z "$EVENT_IDS" ]; then
  echo "No events found in source category. Nothing to move."
  exit 0
fi

TOTAL=$(echo "$EVENT_IDS" | wc -l)
echo "Found $TOTAL events."
echo "  Source category: $SOURCE_CATEGORY"
echo "  New category:    $NEW_CATEGORY"
echo "  New target:      $NEW_TARGET"
echo "---"

COUNT=0
FAILED=0
for EID in $EVENT_IDS; do
  COUNT=$((COUNT + 1))

  RESULT=$(curl -s -X POST "$BASE_URL/update_event/v1" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"id\": \"$EID\", \"category\": \"$NEW_CATEGORY\", \"target\": \"$NEW_TARGET\"}")

  CODE=$(echo "$RESULT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('code', -1))" 2>/dev/null)

  if [ "$CODE" = "0" ]; then
    echo "[$COUNT/$TOTAL] ✓ $EID"
  else
    echo "[$COUNT/$TOTAL] ✗ $EID — FAILED: $RESULT"
    FAILED=$((FAILED + 1))
  fi

  sleep 0.1
done

echo "---"
echo "Done. Moved: $((COUNT - FAILED)), Failed: $FAILED"
```

---

### 4.4 🎯 `bulk_move_ums3.sh` (Target-Only Move)

**Purpose:** Same idea as `bulk_move_category.sh`, but only changes target — keeps category. Variant for moving events to a different server within the same category.

**Configuration:**

```bash
CATEGORY_ID="cmne6hb8nql"     # filter by this category
NEW_TARGET="gmo85s9rfqr"      # change all matching events to this target
```

**When to use:** When you need to swap the server group but keep events in their original category.

### Full Script:

```bash
#!/bin/bash

API_KEY="054ac51662da079a6a1cc91a68f50b1e"
BASE_URL="https://schedule.osl.team/api/app"
CATEGORY_ID="cmne6hb8nql"
NEW_TARGET="gmo85s9rfqr"

echo "Fetching events in category $CATEGORY_ID..."

EVENT_IDS=$(curl -s -X POST "$BASE_URL/get_schedule/v1" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"limit": 1000}' | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
for e in data['rows']:
    if e.get('category') == '$CATEGORY_ID':
        print(e['id'])
")

TOTAL=$(echo "$EVENT_IDS" | grep -c .)
echo "Found $TOTAL events. Moving target to $NEW_TARGET..."
echo "---"

COUNT=0
for EID in $EVENT_IDS; do
  COUNT=$((COUNT + 1))

  RESULT=$(curl -s -X POST "$BASE_URL/update_event/v1" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"id\": \"$EID\", \"target\": \"$NEW_TARGET\"}")

  CODE=$(echo "$RESULT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('code', -1))" 2>/dev/null)

  if [ "$CODE" = "0" ]; then
    echo "[$COUNT/$TOTAL] ✓ $EID"
  else
    echo "[$COUNT/$TOTAL] ✗ $EID — FAILED: $RESULT"
  fi

  sleep 0.1
done

echo "---"
echo "Done."
```

---

### 4.5 ⏱ `bulk_update_timeout.sh`

**Purpose:** Bulk-update the HTTP Request plugin's timeout for all events.

**Configuration:**

```bash
NEW_TIMEOUT="1200"
```

**Important:** This script updates `params.timeout` (the **plugin-level** HTTP timeout shown in plugin parameters). It does **NOT** touch the outer `timeout` field (the overall job timeout near the bottom of the event edit page).

**How it works:**

- Two-step per event: GET event → modify only the timeout → PUT update
- Slower than other scripts (one extra fetch per event) because it preserves all other plugin params intact

**Optional filter:** As written, it updates **every** event in Cronicle. To restrict to a category, modify the Python filter line:

```python
[print(e['id']) for e in data['rows'] if e.get('category') == 'YOUR_CATEGORY_ID']
```

### Full Script:

```bash
#!/bin/bash

API_KEY="054ac51662da079a6a1cc91a68f50b1e"
BASE_URL="https://schedule.osl.team/api/app"
NEW_TIMEOUT="1200"

# Fetch all event IDs
echo "Fetching event list..."
EVENT_IDS=$(curl -s -X POST "$BASE_URL/get_schedule/v1" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"limit": 1000}' | \
  python3 -c "import sys, json; data = json.load(sys.stdin); [print(e['id']) for e in data['rows']]")

TOTAL=$(echo "$EVENT_IDS" | wc -l)
echo "Found $TOTAL events. Starting update..."
echo "---"

COUNT=0
for EID in $EVENT_IDS; do
  COUNT=$((COUNT + 1))

  # Get current event to preserve other params
  CURRENT=$(curl -s -X POST "$BASE_URL/get_event/v1" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"id\": \"$EID\"}")

  TITLE=$(echo "$CURRENT" | python3 -c "import sys, json; print(json.load(sys.stdin)['event']['title'])")

  # Build updated params with new timeout, keeping everything else
  UPDATED_PARAMS=$(echo "$CURRENT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
params = data['event'].get('params', {})
params['timeout'] = '$NEW_TIMEOUT'
print(json.dumps(params))
")

  # Send update
  RESULT=$(curl -s -X POST "$BASE_URL/update_event/v1" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"id\": \"$EID\", \"params\": $UPDATED_PARAMS}")

  CODE=$(echo "$RESULT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('code', -1))")

  if [ "$CODE" = "0" ]; then
    echo "[$COUNT/$TOTAL] ✓ $EID — $TITLE"
  else
    echo "[$COUNT/$TOTAL] ✗ $EID — FAILED: $RESULT"
  fi

  sleep 0.1  # small delay to avoid hammering the server
done

echo "---"
echo "Done."
```

---

### 4.6 🔄 `bulk_toggle_events.sh`

**Purpose:** Bulk enable or disable events filtered by category AND target.

**Configuration:**

```bash
CATEGORY_ID="cmmso11u05t"
TARGET_ID="gmo85rxfmqq"
ACTION="enable"        # or "disable"
```

**Run:**

```bash
./bulk_toggle_events.sh
```

**Behavior:**

- Matches events where **both** category AND target match
- Sends `{"id": "...", "enabled": 1|0}` to update_event
- Tight filtering = predictable behavior

**Use cases:**

- After import: enable all newly migrated events when ready to flip the switch
- Before maintenance: disable specific subset
- After maintenance: re-enable

### Full Script:

```bash
#!/bin/bash

# === CONFIG (edit these before running) ===
API_KEY="054ac51662da079a6a1cc91a68f50b1e"
BASE_URL="https://schedule.osl.team/api/app"

CATEGORY_ID="cmmso11u05t"        # which category to target
TARGET_ID="gmo85rxfmqq"          # which server group to target
ACTION="enable"                  # "enable" or "disable"

# === SCRIPT ===
if [ "$ACTION" = "enable" ]; then
  ENABLED_VALUE=1
elif [ "$ACTION" = "disable" ]; then
  ENABLED_VALUE=0
else
  echo "ERROR: ACTION must be 'enable' or 'disable'. Got: $ACTION"
  exit 1
fi

echo "Fetching events..."
echo "  Category: $CATEGORY_ID"
echo "  Target:   $TARGET_ID"
echo "  Action:   $ACTION"
echo "---"

EVENT_IDS=$(curl -s -X POST "$BASE_URL/get_schedule/v1" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"limit": 5000}' | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
for e in data['rows']:
    if e.get('category') == '$CATEGORY_ID' and e.get('target') == '$TARGET_ID':
        print(e['id'])
")

if [ -z "$EVENT_IDS" ]; then
  echo "No events found matching category=$CATEGORY_ID and target=$TARGET_ID. Nothing to do."
  exit 0
fi

TOTAL=$(echo "$EVENT_IDS" | wc -l)
echo "Found $TOTAL events. Starting $ACTION..."
echo "---"

COUNT=0
SUCCESS=0
FAILED=0

for EID in $EVENT_IDS; do
  COUNT=$((COUNT + 1))

  RESULT=$(curl -s -X POST "$BASE_URL/update_event/v1" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"id\": \"$EID\", \"enabled\": $ENABLED_VALUE}")

  CODE=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('code',-1))" 2>/dev/null)

  if [ "$CODE" = "0" ]; then
    echo "[$COUNT/$TOTAL] ✓ ${ACTION}d $EID"
    SUCCESS=$((SUCCESS + 1))
  else
    echo "[$COUNT/$TOTAL] ✗ $EID — FAILED: $RESULT"
    FAILED=$((FAILED + 1))
  fi

  sleep 0.1
done

echo "---"
echo "Done. ${ACTION^}d: $SUCCESS, Failed: $FAILED"
```

---

### 4.7 🌐 `bulk_toggle_by_target.sh`

**Purpose:** Bulk enable or disable **all events on a target server**, regardless of category.

**Configuration:**

```bash
TARGET_ID="gmofd0rdn0s"
ACTION="enable"        # or "disable"
```

**Use cases:**

- **Server going into maintenance:** disable everything pointed at it
- **Emergency stop:** if a server is misbehaving, kill all jobs targeting it in one shot
- **Server replacement:** disable on old server, move events, enable on new server

**Caution:** Affects every event on that target across all categories. Use with intention.

### Full Script:

```bash
#!/bin/bash

# === CONFIG (edit these before running) ===
API_KEY="054ac51662da079a6a1cc91a68f50b1e"
BASE_URL="https://schedule.osl.team/api/app"

TARGET_ID="gmofd0rdn0s"          # which server group to target
ACTION="enable"                  # "enable" or "disable"

# === SCRIPT ===
if [ "$ACTION" = "enable" ]; then
  ENABLED_VALUE=1
elif [ "$ACTION" = "disable" ]; then
  ENABLED_VALUE=0
else
  echo "ERROR: ACTION must be 'enable' or 'disable'. Got: $ACTION"
  exit 1
fi

echo "Fetching events..."
echo "  Target: $TARGET_ID"
echo "  Action: $ACTION  (across ALL categories on this target)"
echo "---"

EVENT_IDS=$(curl -s -X POST "$BASE_URL/get_schedule/v1" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"limit": 5000}' | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
for e in data['rows']:
    if e.get('target') == '$TARGET_ID':
        print(e['id'])
")

if [ -z "$EVENT_IDS" ]; then
  echo "No events found with target=$TARGET_ID. Nothing to do."
  exit 0
fi

TOTAL=$(echo "$EVENT_IDS" | wc -l)
echo "Found $TOTAL events on target $TARGET_ID. Starting $ACTION..."
echo "---"

COUNT=0
SUCCESS=0
FAILED=0

for EID in $EVENT_IDS; do
  COUNT=$((COUNT + 1))

  RESULT=$(curl -s -X POST "$BASE_URL/update_event/v1" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"id\": \"$EID\", \"enabled\": $ENABLED_VALUE}")

  CODE=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('code',-1))" 2>/dev/null)

  if [ "$CODE" = "0" ]; then
    echo "[$COUNT/$TOTAL] ✓ ${ACTION}d $EID"
    SUCCESS=$((SUCCESS + 1))
  else
    echo "[$COUNT/$TOTAL] ✗ $EID — FAILED: $RESULT"
    FAILED=$((FAILED + 1))
  fi

  sleep 0.1
done

echo "---"
echo "Done. ${ACTION^}d: $SUCCESS, Failed: $FAILED"
```

---

### 4.8 🗑 `bulk_delete_category.sh` (Simple Single-Category Delete)

**Purpose:** Delete all events in a single category. Simpler version, with mandatory confirmation prompt.

**Configuration:**

```bash
CATEGORY_ID="cmne4cjpzdt"
```

**Behavior:**

- Lists all matching events
- Requires typing `DELETE` in all caps to proceed
- Continues past failures, shows count at end

### Full Script:

```bash
#!/bin/bash

API_KEY="054ac51662da079a6a1cc91a68f50b1e"
BASE_URL="https://schedule.osl.team/api/app"
CATEGORY_ID="cmne4cjpzdt"

echo "Fetching events in category $CATEGORY_ID..."

EVENT_LIST=$(curl -s -X POST "$BASE_URL/get_schedule/v1" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"limit": 1000}' | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
for e in data['rows']:
    if e.get('category') == '$CATEGORY_ID':
        print(e['id'] + '|' + e['title'])
")

if [ -z "$EVENT_LIST" ]; then
  echo "No events found in category $CATEGORY_ID. Nothing to delete."
  exit 0
fi

TOTAL=$(echo "$EVENT_LIST" | wc -l)

echo ""
echo "=========================================="
echo "ABOUT TO DELETE $TOTAL EVENTS:"
echo "=========================================="
echo "$EVENT_LIST" | awk -F'|' '{print " - " $1 "  " $2}'
echo "=========================================="
echo ""
read -p "Type 'DELETE' (all caps) to confirm, anything else to cancel: " CONFIRM

if [ "$CONFIRM" != "DELETE" ]; then
  echo "Cancelled. No events were deleted."
  exit 0
fi

echo ""
echo "Starting deletion..."
echo "---"

COUNT=0
FAILED=0
while IFS='|' read -r EID TITLE; do
  COUNT=$((COUNT + 1))

  RESULT=$(curl -s -X POST "$BASE_URL/delete_event/v1" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"id\": \"$EID\"}")

  CODE=$(echo "$RESULT" | python3 -c "import sys, json; print(json.load(sys.stdin).get('code', -1))" 2>/dev/null)

  if [ "$CODE" = "0" ]; then
    echo "[$COUNT/$TOTAL] ✓ Deleted $EID — $TITLE"
  else
    echo "[$COUNT/$TOTAL] ✗ FAILED $EID — $RESULT"
    FAILED=$((FAILED + 1))
  fi

  sleep 0.1
done <<< "$EVENT_LIST"

echo "---"
echo "Done. Deleted: $((COUNT - FAILED)), Failed: $FAILED"
```

---

### 4.9 🧹 `bulk_delete_events.sh` (Flexible Multi-Mode Delete)

**Purpose:** Bulk delete with three filter modes — category only, target only, or both.

**Configuration:**

```bash
FILTER_MODE="target_only"   # or "category_only" or "category_and_target"
CATEGORY_ID="cmmso11u05t"
TARGET_ID="gmo85rxfmqq"
EXECUTE="no"                # "no" = dry run preview, "yes" = actually delete
```

**Two-stage safety:**

1. **Dry run first** — keep `EXECUTE="no"`, run, review the preview list
2. **Real run** — change `EXECUTE="yes"`, run, type `DELETE <count>` to confirm (e.g. `DELETE 33`)

The exact count must match — prevents accidental confirmation when the event count has changed.

**When to use which mode:**

| Mode | Scenario |
| --- | --- |
| `target_only` | Decommissioning a server — wipe everything on it |
| `category_only` | Bad batch import — delete entire category |
| `category_and_target` | Most precise, safest — delete only the intersection |

### Full Script:

```bash
#!/bin/bash

# === CONFIG (edit these before running) ===
API_KEY="054ac51662da079a6a1cc91a68f50b1e"
BASE_URL="https://schedule.osl.team/api/app"

# Filter mode: "target_only", "category_only", or "category_and_target"
FILTER_MODE="target_only"

CATEGORY_ID="cmmso11u05t"        # used when mode is category_only or category_and_target
TARGET_ID="allgrp"               # used when mode is target_only or category_and_target

# === SAFETY ===
# Set to "yes" to actually delete. Anything else = dry run (preview only, no deletion).
EXECUTE="no"

# === SCRIPT ===
case "$FILTER_MODE" in
  "target_only"|"category_only"|"category_and_target") ;;
  *)
    echo "ERROR: FILTER_MODE must be 'target_only', 'category_only', or 'category_and_target'."
    echo "Got: $FILTER_MODE"
    exit 1
    ;;
esac

echo "=========================================="
echo "  Cronicle Bulk Delete"
echo "=========================================="
echo "Mode:     $FILTER_MODE"
case "$FILTER_MODE" in
  "target_only")
    echo "Target:   $TARGET_ID  (ALL categories on this target)"
    ;;
  "category_only")
    echo "Category: $CATEGORY_ID  (ALL targets in this category)"
    ;;
  "category_and_target")
    echo "Category: $CATEGORY_ID"
    echo "Target:   $TARGET_ID"
    ;;
esac
echo "Execute:  $EXECUTE"
echo "=========================================="
echo ""

echo "Fetching events..."

EVENT_DATA=$(curl -s -X POST "$BASE_URL/get_schedule/v1" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"limit": 5000}' | \
  python3 -c "
import sys, json
data = json.load(sys.stdin)
mode = '$FILTER_MODE'
cat = '$CATEGORY_ID'
tgt = '$TARGET_ID'

for e in data['rows']:
    match = False
    if mode == 'target_only' and e.get('target') == tgt:
        match = True
    elif mode == 'category_only' and e.get('category') == cat:
        match = True
    elif mode == 'category_and_target' and e.get('category') == cat and e.get('target') == tgt:
        match = True

    if match:
        title = e.get('title', '').replace('|', '_')
        print(f\"{e['id']}|{e.get('enabled',0)}|{e.get('category','?')}|{e.get('target','?')}|{title}\")
")

if [ -z "$EVENT_DATA" ]; then
  echo "No events match the filter. Nothing to delete."
  exit 0
fi

TOTAL=$(echo "$EVENT_DATA" | wc -l)

echo ""
echo "=========================================="
echo "  PREVIEW — $TOTAL events match"
echo "=========================================="
echo "$EVENT_DATA" | awk -F'|' '{
  state = ($2 == "1") ? "[ON] " : "[OFF]"
  printf "  %s %s  cat=%s  tgt=%s  %s\n", state, $1, $3, $4, $5
}'
echo "=========================================="

# Dry-run mode — stop here
if [ "$EXECUTE" != "yes" ]; then
  echo ""
  echo "DRY RUN — no events were deleted."
  echo "Set EXECUTE=\"yes\" in the script to actually delete."
  exit 0
fi

# Execute mode — strong confirmation required
echo ""
echo "⚠ WARNING: You are about to PERMANENTLY DELETE $TOTAL events."
echo "This action cannot be undone."
echo ""
read -p "Type 'DELETE $TOTAL' (with the exact count) to confirm: " CONFIRM

EXPECTED="DELETE $TOTAL"
if [ "$CONFIRM" != "$EXPECTED" ]; then
  echo "Confirmation mismatch. Cancelled. No events were deleted."
  exit 0
fi

echo ""
echo "Starting deletion..."
echo "---"

COUNT=0
SUCCESS=0
FAILED=0

while IFS='|' read -r EID ENABLED CAT TGT TITLE; do
  [ -z "$EID" ] && continue
  COUNT=$((COUNT + 1))

  RESULT=$(curl -s -X POST "$BASE_URL/delete_event/v1" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"id\": \"$EID\"}")

  CODE=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('code',-1))" 2>/dev/null)

  if [ "$CODE" = "0" ]; then
    echo "[$COUNT/$TOTAL] ✓ Deleted $EID — $TITLE"
    SUCCESS=$((SUCCESS + 1))
  else
    echo "[$COUNT/$TOTAL] ✗ FAILED $EID — $RESULT"
    FAILED=$((FAILED + 1))
  fi

  sleep 0.1
done <<< "$EVENT_DATA"

echo ""
echo "=========================================="
echo "  SUMMARY"
echo "=========================================="
echo "Total matched: $TOTAL"
echo "Deleted:       $SUCCESS"
echo "Failed:        $FAILED"
echo "=========================================="
```

---

## 5. Recommended Workflows

### Workflow A — Migrate New Windows Task Batch (e.g. ums-N)

1. Export `.xml` files from Windows Task Scheduler
2. Drop them into `./xml_task/`
3. Open `bulk_import_xml.sh`, edit:
    - `PREFIX="ums-N-"`
    - `CATEGORY_ID="<your category>"`
    - `TARGET_ID="<your target>"`
4. Run. Events created as **disabled**.
5. Spot-check 2-3 events in UI to verify timing
6. When ready, run `bulk_toggle_events.sh` with `ACTION="enable"` to flip them on

### Workflow B — Move Events to Different Server

1. Edit `bulk_move_ums3.sh`:
    - `CATEGORY_ID` = source category
    - `NEW_TARGET` = destination server group ID
2. Run
3. Verify in UI — Target dropdown should show new group

### Workflow C — Server Maintenance

1. **Before maintenance:**
    
    ```bash
    # Edit bulk_toggle_by_target.shTARGET_ID="<server going down>"ACTION="disable"./bulk_toggle_by_target.sh
    ```
    
2. **Perform maintenance**
3. **After maintenance:**
    
    ```bash
    ACTION="enable"./bulk_toggle_by_target.sh
    ```
    

### Workflow D — Migrate Events from Old Server to New

1. **Disable** events on old target (`bulk_toggle_by_target.sh`)
2. **Move** events to new target (`bulk_move_ums3.sh`)
3. **Enable** events on new target (`bulk_toggle_by_target.sh`)

### Workflow E — Wipe & Re-import

1. **Dry run delete** — `bulk_delete_events.sh` with `EXECUTE="no"`, review
2. **Real delete** — `EXECUTE="yes"`, run, confirm with `DELETE <count>`
3. **Re-import** — `bulk_import_xml.sh` with corrected config

---

## 6. Cronicle Concepts Cheat Sheet

### Targets

`target` field can be:

- **Server group ID** (e.g. `gmoxxxxx`) — Cronicle picks a server based on `algo`
- **Hostname** (e.g. `worker01.example.com`) — runs on exactly that machine
- **`allgrp`** — special "All Servers" group

### Algorithms

| Value | Behavior |
| --- | --- |
| `random` | Picks random eligible server from group |
| `round_robin` | Rotates through servers |
| `least_cpu` | Picks server with lowest CPU |
| `least_mem` | Picks server with lowest memory usage |
| `multiplex` | Runs on **all** servers in group simultaneously |

### Timing — Selection-Based, Not Cron

Cronicle uses arrays of selected values, NOT cron expressions:

```json
{
  "minutes": [0, 30],
  "hours": [0, 6, 12, 18],
  "weekdays": [1, 3, 5]
}
```

This means "at minute :00 or :30, when hour is 00/06/12/18, on Mon/Wed/Fri".

- **Empty `timing` object** = runs every minute
- **No `timing` field at all** = "on demand" only

### Two Different Timeouts

| Field | Where in UI | What it controls |
| --- | --- | --- |
| `params.timeout` | Plugin Parameters → Timeout (Seconds) | HTTP Request plugin timeout |
| `timeout` (top-level) | Timeout field near bottom | Overall job kill switch |

---

## 7. Troubleshooting

### Empty API response

- **Cause:** Cronicle service might be down, or `get_schedule` rate-limited
- **Fix:** Run `curl -v` against the endpoint, check HTTP status. Wait and retry.

### `JSONDecodeError: Expecting value`

- **Cause:** Empty or non-JSON response (server hiccup, network issue, or unsupported endpoint)
- **Fix:** Check API key validity, server reachability. Retry after a moment.

### Event already exists error

```
{"code":"event","description":"Event with title \"...\" already exists"}
```

- **Cause:** You're re-importing a batch you already imported
- **Fix:** Either delete duplicates first or change the prefix

### Wrong interval mapping

- **Cause:** Windows XML uses an interval not in the mapping table (e.g. `PT45M`)
- **Fix:** Add a new `case` block to `bulk_import_xml.sh` for the missing interval

### Move/update succeeded but jobs aren't running

- **Cause:** Target group is empty, or server in group is offline
- **Fix:** Check Cronicle Admin → Servers — confirm workers are connected and assigned to the group

### `Unsupported API` error on certain endpoints

- **Cause:** Cronicle-Edge Fork has locked down some public APIs
- **Fix:** Use UI to fetch IDs (e.g. server group IDs) — these aren't exposed via API in Edge fork

---

## 8. Security Notes

### API Key Hygiene

- **Rotate API keys** after any session where credentials were exposed (chat logs, screenshots, shared scripts, etc.)
- **Use environment variables** instead of hardcoding for production scripts:
    
    ```bash
    API_KEY="${CRONICLE_API_KEY}"
    ```
    
- **Store keys in secret managers** (HashiCorp Vault, AWS Secrets Manager) or `.env` files excluded from Git

### Pre-flight Safety Checklist

Before running any destructive script:

- [ ]  Did you double-check `CATEGORY_ID` and `TARGET_ID`?
- [ ]  Is `EXECUTE="no"` for the first run? (delete scripts)
- [ ]  Did you spot-check 1-2 events in UI to confirm what they actually are?
- [ ]  Do you have a backup or export of the schedule? (Cronicle UI → Schedule → Export)

### Git Repo Recommendation

Save this toolkit in a private Git repo:

```
.gitignore:
  config.local.sh         # local secrets
  *.env

repo/
  parse_xml.py
  bulk_*.sh
  README.md               # this documentation
  examples/
    sample_task.xml
```

**Benefits:**

- Version history for script changes
- Team-wide reuse
- Rollback capability
- Audit trail

---

## 9. 📌 Quick Reference Card

| Task | Script | Edit |
| --- | --- | --- |
| Import Windows tasks | `bulk_import_xml.sh` | PREFIX, CATEGORY_ID, TARGET_ID, XML_DIR |
| Move to new category + target | `bulk_move_category.sh` | SOURCE_CATEGORY, NEW_CATEGORY, NEW_TARGET |
| Move target only | `bulk_move_ums3.sh` | CATEGORY_ID, NEW_TARGET |
| Update HTTP timeout (all events) | `bulk_update_timeout.sh` | NEW_TIMEOUT |
| Enable/disable by category+target | `bulk_toggle_events.sh` | CATEGORY_ID, TARGET_ID, ACTION |
| Enable/disable whole target | `bulk_toggle_by_target.sh` | TARGET_ID, ACTION |
| Delete (single category) | `bulk_delete_category.sh` | CATEGORY_ID |
| Delete (flexible filters) | `bulk_delete_events.sh` | FILTER_MODE, CATEGORY_ID, TARGET_ID, EXECUTE |

---

*Last updated: 2026-04-26 Maintained by: DevOps team*