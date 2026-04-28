#!/bin/bash

# === CONFIG (edit these before running) ===
API_KEY="054ac51662da079a6a1cc91a68f50b1e"
BASE_URL="https://schedule.osl.team/api/app"

# Filter mode: "target_only", "category_only", or "category_and_target"
FILTER_MODE="target_only"

CATEGORY_ID="cmo8c2nmj41"        # used when mode is category_only or category_and_target
TARGET_ID="gmo85s9rfqr"          # used when mode is target_only or category_and_target

# Timeout values (in seconds)
NEW_PLUGIN_TIMEOUT="3600"        # HTTP plugin timeout (params.timeout)
NEW_JOB_TIMEOUT="3600"           # Outer job timeout (top-level timeout) — set to "" to skip

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

echo "=========================================="
echo "  Cronicle Bulk Timeout Update"
echo "=========================================="
echo "Mode:           $FILTER_MODE"
case "$FILTER_MODE" in
  "target_only")
    echo "Target:         $TARGET_ID  (ALL categories on this target)"
    ;;
  "category_only")
    echo "Category:       $CATEGORY_ID  (ALL targets in this category)"
    ;;
  "category_and_target")
    echo "Category:       $CATEGORY_ID"
    echo "Target:         $TARGET_ID"
    ;;
esac
echo "Plugin timeout: $NEW_PLUGIN_TIMEOUT seconds"
if [ -n "$NEW_JOB_TIMEOUT" ]; then
  echo "Job timeout:    $NEW_JOB_TIMEOUT seconds"
else
  echo "Job timeout:    (skipped — only updating plugin timeout)"
fi
echo "Execute:        $EXECUTE"
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

# Dry-run mode — stop here
if [ "$EXECUTE" != "yes" ]; then
  echo ""
  echo "DRY RUN — no events were updated."
  echo "Set EXECUTE=\"yes\" in the script to actually apply timeout changes."
  exit 0
fi

# Execute mode — confirmation required
echo ""
echo "About to update timeout on $TOTAL events."
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
  
  # Get current event to preserve other params
  CURRENT=$(curl -s -X POST "$BASE_URL/get_event/v1" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"id\": \"$EID\"}")
  
  # Build updated params with new plugin timeout, keeping everything else
  UPDATED_PARAMS=$(echo "$CURRENT" | python3 -c "
import sys, json
data = json.load(sys.stdin)
params = data['event'].get('params', {})
params['timeout'] = '$NEW_PLUGIN_TIMEOUT'
print(json.dumps(params))
")
  
  # Build update payload — include job timeout only if set
  if [ -n "$NEW_JOB_TIMEOUT" ]; then
    UPDATE_PAYLOAD="{\"id\": \"$EID\", \"params\": $UPDATED_PARAMS, \"timeout\": $NEW_JOB_TIMEOUT}"
  else
    UPDATE_PAYLOAD="{\"id\": \"$EID\", \"params\": $UPDATED_PARAMS}"
  fi
  
  # Send update
  RESULT=$(curl -s -X POST "$BASE_URL/update_event/v1" \
    -H "X-API-Key: $API_KEY" \
    -H "Content-Type: application/json" \
    -d "$UPDATE_PAYLOAD")
  
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
echo "=========================================="
