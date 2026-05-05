#!/bin/bash

# === CONFIG (edit these before running) ===
API_KEY="054ac51662da079a6a1cc91a68f50b1e"
BASE_URL="https://schedule.osl.team/api/app"

# === SOURCE (events to clone FROM) ===
SOURCE_CATEGORY_ID="cmmso11u05t"     # Auto Blank Detection (UMS-0 side)
SOURCE_TARGET_ID="gmofkmxjpy4"       # UMS-0 target

# === DESTINATION (where clones will be created) ===
DEST_CATEGORY_ID="cmmso11u05t"       # Auto Blank Detection (UMS-3 side — same in this case)
DEST_TARGET_ID="gmofejw40q7"         # UMS-3 target

# === TRANSFORM RULES ===
# Title rename: replace this in the title with that
SRC_TITLE_PATTERN="ums-0-"
DST_TITLE_PATTERN="ums-6-"

# URL rename: replace this in the URL with that
# Example: https://ums-schedule.osl.team/...  →  https://ums-schedule-3.osl.team/...
SRC_URL_PATTERN="ums-schedule.osl.team"
DST_URL_PATTERN="ums-schedule-6.osl.team"

# === BEHAVIOR ===
CREATE_AS_DISABLED="no"             # "yes" = clone created disabled, "no" = match source enabled state

# === SAFETY ===
EXECUTE="yes"                         # "yes" = create clones, anything else = dry run

# === SCRIPT ===
echo "=========================================="
echo "  Cronicle Bulk Clone"
echo "=========================================="
echo "Source category: $SOURCE_CATEGORY_ID"
echo "Source target:   $SOURCE_TARGET_ID"
echo "Dest category:   $DEST_CATEGORY_ID"
echo "Dest target:     $DEST_TARGET_ID"
echo ""
echo "Title transform: '$SRC_TITLE_PATTERN' → '$DST_TITLE_PATTERN'"
echo "URL transform:   '$SRC_URL_PATTERN' → '$DST_URL_PATTERN'"
echo "Disabled clones: $CREATE_AS_DISABLED"
echo "Execute:         $EXECUTE"
echo "=========================================="
echo ""

echo "Fetching source events..."

# Get full event objects (not just IDs) so we can clone all properties
EVENTS_JSON=$(curl -s -X POST "$BASE_URL/get_schedule/v1" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"limit": 5000}')

# Filter source events and prepare clone payloads
CLONE_DATA=$(echo "$EVENTS_JSON" | python3 -c "
import sys, json

data = json.load(sys.stdin)
src_cat = '$SOURCE_CATEGORY_ID'
src_tgt = '$SOURCE_TARGET_ID'
dst_cat = '$DEST_CATEGORY_ID'
dst_tgt = '$DEST_TARGET_ID'
src_title = '$SRC_TITLE_PATTERN'
dst_title = '$DST_TITLE_PATTERN'
src_url = '$SRC_URL_PATTERN'
dst_url = '$DST_URL_PATTERN'
disable_clones = '$CREATE_AS_DISABLED' == 'yes'

matched = []
for e in data.get('rows', []):
    if e.get('category') == src_cat and e.get('target') == src_tgt:
        matched.append(e)

# Output preview line per event AND full payload (delimited)
for e in matched:
    old_title = e.get('title', '')
    new_title = old_title.replace(src_title, dst_title) if src_title else old_title
    
    # Build the new event payload as a clone
    payload = dict(e)
    
    # Remove fields that are unique to the source event
    for field in ['id', 'created', 'modified', 'username']:
        payload.pop(field, None)
    
    # Override identity fields
    payload['title'] = new_title
    payload['category'] = dst_cat
    payload['target'] = dst_tgt
    
    if disable_clones:
        payload['enabled'] = 0
    
    # Transform URL inside params
    if 'params' in payload and isinstance(payload['params'], dict):
        if 'url' in payload['params'] and payload['params']['url']:
            old_url = payload['params']['url']
            new_url = old_url.replace(src_url, dst_url) if src_url else old_url
            payload['params']['url'] = new_url
        else:
            old_url = ''
            new_url = ''
    else:
        old_url = ''
        new_url = ''
    
    # Print: PREVIEW LINE then JSON payload then separator
    print(f'PREVIEW||{old_title}||{new_title}||{old_url}||{new_url}')
    print('PAYLOAD||' + json.dumps(payload))
    print('---END---')
")

if [ -z "$CLONE_DATA" ]; then
  echo "No source events match category=$SOURCE_CATEGORY_ID and target=$SOURCE_TARGET_ID."
  echo "Nothing to clone."
  exit 0
fi

# Count events by counting PREVIEW lines
TOTAL=$(echo "$CLONE_DATA" | grep -c "^PREVIEW||")

echo ""
echo "=========================================="
echo "  PREVIEW — $TOTAL events to clone"
echo "=========================================="
echo "$CLONE_DATA" | grep "^PREVIEW||" | awk -F'\\|\\|' '{
  printf "  Title:  %s\n      →  %s\n  URL:    %s\n      →  %s\n  ---\n", $2, $3, $4, $5
}'
echo "=========================================="

# Dry-run mode — stop here
if [ "$EXECUTE" != "yes" ]; then
  echo ""
  echo "DRY RUN — no clones were created."
  echo "Set EXECUTE=\"yes\" in the script to actually create clones."
  exit 0
fi

# Execute mode — confirmation required
echo ""
echo "About to create $TOTAL cloned events on destination."
read -p "Type 'yes' to proceed, anything else to cancel: " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
  echo "Cancelled. No events were created."
  exit 0
fi

echo ""
echo "Starting clone..."
echo "---"

COUNT=0
SUCCESS=0
FAILED=0

# Iterate by walking the CLONE_DATA, picking up PAYLOAD lines
while IFS= read -r LINE; do
  if [[ "$LINE" == PAYLOAD\|\|* ]]; then
    COUNT=$((COUNT + 1))
    PAYLOAD="${LINE#PAYLOAD\|\|}"
    
    NEW_TITLE=$(echo "$PAYLOAD" | python3 -c "import sys,json; print(json.load(sys.stdin)['title'])" 2>/dev/null)
    
    RESULT=$(curl -s -X POST "$BASE_URL/create_event/v1" \
      -H "X-API-Key: $API_KEY" \
      -H "Content-Type: application/json" \
      -d "$PAYLOAD")
    
    CODE=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('code',-1))" 2>/dev/null)
    
    if [ "$CODE" = "0" ]; then
      NEW_ID=$(echo "$RESULT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
      echo "[$COUNT/$TOTAL] ✓ Created $NEW_ID — $NEW_TITLE"
      SUCCESS=$((SUCCESS + 1))
    else
      echo "[$COUNT/$TOTAL] ✗ FAILED $NEW_TITLE — $RESULT"
      FAILED=$((FAILED + 1))
    fi
    
    sleep 0.1
  fi
done <<< "$CLONE_DATA"

echo ""
echo "=========================================="
echo "  SUMMARY"
echo "=========================================="
echo "Total source events: $TOTAL"
echo "Cloned successfully: $SUCCESS"
echo "Failed:              $FAILED"
if [ "$CREATE_AS_DISABLED" = "yes" ]; then
  echo ""
  echo "Note: Clones were created DISABLED."
  echo "Use bulk_toggle_events.sh with category=$DEST_CATEGORY_ID and target=$DEST_TARGET_ID to enable when ready."
fi
echo "=========================================="
