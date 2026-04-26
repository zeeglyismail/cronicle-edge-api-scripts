#!/usr/bin/env python3
import xml.etree.ElementTree as ET
import json
import re
import sys

xml_file = sys.argv[1]

try:
    with open(xml_file, "rb") as f:
        raw = f.read()
    
    # Handle UTF-16 BOM that Windows Task Scheduler exports
    if raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff'):
        content = raw.decode('utf-16')
    else:
        content = raw.decode('utf-8', errors='replace')
    
    # Strip namespace for easier XPath
    content = re.sub(r'\sxmlns="[^"]+"', '', content, count=1)
    root = ET.fromstring(content)
    
    # Extract URI for naming
    uri = root.find('.//URI')
    uri_text = uri.text if uri is not None else ""
    name_part = re.split(r'[\\/]', uri_text.rstrip('/\\'))[-1] if uri_text else "unknown"
    
    # Extract URL from Arguments
    args = root.find('.//Actions/Exec/Arguments')
    args_text = args.text if args is not None else ""
    url_match = re.search(r'(https?://[^\s"]+)', args_text)
    url = url_match.group(1) if url_match else ""
    
    # Extract repetition interval (for sub-day intervals)
    interval_elem = root.find('.//Repetition/Interval')
    interval = interval_elem.text if interval_elem is not None else ""
    
    # Extract StartBoundary (for daily/weekly tasks — gives the hour to run at)
    start_elem = root.find('.//StartBoundary')
    start_text = start_elem.text if start_elem is not None else ""
    start_hour = 0
    start_minute = 0
    if start_text:
        time_match = re.search(r'T(\d{2}):(\d{2})', start_text)
        if time_match:
            start_hour = int(time_match.group(1))
            start_minute = int(time_match.group(2))
    
    # Detect schedule type
    has_daily = root.find('.//ScheduleByDay') is not None
    has_weekly = root.find('.//ScheduleByWeek') is not None
    has_repetition = root.find('.//Repetition') is not None
    
    # Default interval if nothing detected
    if not interval and has_daily and not has_repetition:
        interval = "P1D"
    elif not interval:
        interval = "PT2M"
    
    print(json.dumps({
        "name": name_part,
        "url": url,
        "interval": interval,
        "start_hour": start_hour,
        "start_minute": start_minute,
        "has_daily": has_daily,
        "has_weekly": has_weekly
    }))
    
except Exception as e:
    print(json.dumps({"error": str(e), "name": "", "url": "", "interval": "", "start_hour": 0, "start_minute": 0}))
