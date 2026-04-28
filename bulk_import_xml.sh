#!/bin/bash

# === CONFIG ===
API_KEY="054ac51662da079a6a1cc91a68f50b1e"
BASE_URL="https://schedule.osl.team/api/app"
CATEGORY_ID="cmo8c3a3w67"
TARGET_ID="gmofkmxjpy4"
PLUGIN_TIMEOUT="1200"
JOB_TIMEOUT="3600"
TIMEZONE="Asia/Dhaka"
PREFIX="ums-0-"
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
