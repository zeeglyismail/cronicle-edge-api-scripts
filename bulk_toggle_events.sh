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
