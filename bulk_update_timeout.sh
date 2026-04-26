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
