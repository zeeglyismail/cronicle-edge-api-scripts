#!/bin/bash

# === CONFIG (edit these before running) ===
API_KEY="054ac51662da079a6a1cc91a68f50b1e"
BASE_URL="https://schedule2.osl.team/api/app"

# Filter mode: "target_only", "category_only", or "category_and_target"
FILTER_MODE="target_only"

CATEGORY_ID="cmmso11u05t"        # used when mode is category_only or category_and_target
TARGET_ID="allgrp"          # used when mode is target_only or category_and_target

# === SAFETY ===
# Set to "yes" to actually delete. Anything else = dry run (preview only, no deletion).
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
