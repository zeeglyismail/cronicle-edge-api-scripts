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
