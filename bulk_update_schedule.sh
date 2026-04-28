#!/bin/bash

# === CONFIG (edit these before running) ===
API_KEY="054ac51662da079a6a1cc91a68f50b1e"
BASE_URL="https://schedule.osl.team/api/app"

# Filter mode: "target_only", "category_only", or "category_and_target"
FILTER_MODE="target_only"

CATEGORY_ID="cmmso11u05t"        # used when mode is category_only or category_and_target
TARGET_ID="gmo85s9rfqr"          # used when mode is target_only or category_and_target

# === SCHEDULE INTERVAL ===
# Pick ONE preset by setting INTERVAL to the value you want.
# Supported presets:
#   "1m", "2m", "3m", "5m", "10m", "15m", "20m", "30m"
#   "1h", "2h", "3h", "4h", "6h", "8h", "12h"
#   "daily"
#
# For "1h" and above, also set START_MINUTE (e.g. 0 means runs at HH:00).
# For "daily", also set START_HOUR and START_MINUTE.
INTERVAL="5m"
START_HOUR="0"        # only used for hourly+ / daily intervals
START_MINUTE="0"      # only used for hourly+ / daily intervals

# === SAFETY ===
# Set to "yes" to actually update. Anything else = dry run (preview only, no changes).
EXECUTE="yes"

# === SCRIPT ===
case "$FILTER_MODE" in
  "target_only"|"category_only"|"category_and_target") ;;
  *)
    echo "ERROR: FILTER_MODE must be 'target_only', 'category_only', or 'category_and_target'."
    echo "Got: $FILTER_MODE"
    exit 1
    ;;
esac

# Map interval preset to Cronicle timing JSON
HOURS=""
case "$INTERVAL" in
  "1m")
    MINUTES="[0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45,46,47,48,49,50,51,52,53,54,55,56,57,58,59]"
    LABEL="every 1 minute"
    ;;
  "2m")
    MINUTES="[0,2,4,6,8,10,12,14,16,18,20,22,24,26,28,30,32,34,36,38,40,42,44,46,48,50,52,54,56,58]"
    LABEL="every 2 minutes"
    ;;
  "3m")
    MINUTES="[0,3,6,9,12,15,18,21,24,27,30,33,36,39,42,45,48,51,54,57]"
    LABEL="every 3 minutes"
    ;;
  "5m")
    MINUTES="[0,5,10,15,20,25,30,35,40,45,50,55]"
    LABEL="every 5 minutes"
    ;;
  "10m")
    MINUTES="[0,10,20,30,40,50]"
    LABEL="every 10 minutes"
    ;;
  "15m")
    MINUTES="[0,15,30,45]"
    LABEL="every 15 minutes"
    ;;
  "20m")
    MINUTES="[0,20,40]"
    LABEL="every 20 minutes"
    ;;
  "30m")
    MINUTES="[0,30]"
    LABEL="every 30 minutes"
    ;;
  "1h")
    MINUTES="[$START_MINUTE]"
    LABEL="every hour at minute $START_MINUTE"
    ;;
  "2h")
    MINUTES="[$START_MINUTE]"
    HOURS="[0,2,4,6,8,10,12,14,16,18,20,22]"
    LABEL="every 2 hours at minute $START_MINUTE"
    ;;
  "3h")
    MINUTES="[$START_MINUTE]"
    HOURS="[0,3,6,9,12,15,18,21]"
    LABEL="every 3 hours at minute $START_MINUTE"
    ;;
  "4h")
    MINUTES="[$START_MINUTE]"
    HOURS="[0,4,8,12,16,20]"
    LABEL="every 4 hours at minute $START_MINUTE"
    ;;
  "6h")
    MINUTES="[$START_MINUTE]"
    HOURS="[0,6,12,18]"
    LABEL="every 6 hours at minute $START_MINUTE"
    ;;
  "8h")
    MINUTES="[$START_MINUTE]"
    HOURS="[0,8,16]"
    LABEL="every 8 hours at minute $START_MINUTE"
    ;;
  "12h")
    MINUTES="[$START_MINUTE]"
    HOURS="[0,12]"
    LABEL="every 12 hours at minute $START_MINUTE"
    ;;
  "daily")
    MINUTES="[$START_MINUTE]"
    HOURS="[$START_HOUR]"
    LABEL="daily at ${START_HOUR}:${START_MINUTE}"
    ;;
  *)
    echo "ERROR: Unsupported INTERVAL preset: $INTERVAL"
    echo "Supported: 1m, 2m, 3m, 5m, 10m, 15m, 20m, 30m, 1h, 2h, 3h, 4h, 6h, 8h, 12h, daily"
    exit 1
    ;;
esac

# Build timing JSON
if [ -n "$HOURS" ]; then
  TIMING="{\"minutes\": $MINUTES, \"hours\": $HOURS}"
else
  TIMING="{\"minutes\": $MINUTES}"
fi

echo "=========================================="
echo "  Cronicle Bulk Schedule Update"
echo "=========================================="
echo "Mode:       $FILTER_MODE"
case "$FILTER_MODE" in
  "target_only")
    echo "Target:     $TARGET_ID  (ALL categories on this target)"
    ;;
  "category_only")
    echo "Category:   $CATEGORY_ID  (ALL targets in this category)"
    ;;
  "category_and_target")
    echo "Category:   $CATEGORY_ID"
    echo "Target:     $TARGET_ID"
    ;;
esac
echo "Interval:   $INTERVAL  ($LABEL)"
echo "Timing:     $TIMING"
echo "Execute:    $EXECUTE"
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
  echo "No events match the filter. Nothing to update."
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
echo ""
echo "All matched events will be set to: $LABEL"
echo "=========================================="

# Dry-run mode — stop here
if [ "$EXECUTE" != "yes" ]; then
  echo ""
  echo "DRY RUN — no events were updated."
  echo "Set EXECUTE=\"yes\" in the script to actually apply schedule changes."
  exit 0
fi

# Execute mode — confirmation required
echo ""
echo "About to change schedule for $TOTAL events to: $LABEL"
read -p "Type 'yes' to proceed, anything else to cancel: " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
  echo "Cancelled. No events were updated."
  exit 0
fi

echo ""
echo "Starting update..."
echo "---"

COUNT=0
SUCCESS=0
FAILED=0

while IFS='|' read -r EID ENABLED CAT TGT TITLE; do
  [ -z "$EID" ] && continue
  COUNT=$((COUNT + 1))
  
  # Send update — only timing field needs to change
  RESULT=$(curl -s -X POST "$BASE_URL/update_event/v1" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"id\": \"$EID\", \"timing\": $TIMING}")
  
  CODE=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('code',-1))" 2>/dev/null)
  
  if [ "$CODE" = "0" ]; then
    echo "[$COUNT/$TOTAL] ✓ Updated $EID — $TITLE"
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
echo "Updated:       $SUCCESS"
echo "Failed:        $FAILED"
echo "New schedule:  $LABEL"
echo "=========================================="
