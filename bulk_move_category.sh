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
