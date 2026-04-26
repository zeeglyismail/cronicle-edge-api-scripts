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
