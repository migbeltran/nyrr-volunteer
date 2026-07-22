"""
Tests parse_html() against the ACTUAL current live pages, not fake data.
Run with: python3 test_with_live_data.py

This fetches every URL in check_slots.py's URLS list right now and shows
exactly what the parser extracts - so you can visually confirm no slot
name looks wrong (e.g. a status label like "Near Capacity" being mistaken
for a slot name), and see if any new/unknown status colors show up on
any of your real tracked events today.
"""

import requests
from check_slots import parse_html, URLS, HEADERS, is_notifiable_slot

for url in URLS:
    print(f"\n{'='*70}\n{url}\n{'='*70}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ERROR fetching: {e}")
        continue

    event_date, slots = parse_html(resp.text)
    print(f"Event date: {event_date}")

    if not slots:
        print("  (no slots found - check if page structure changed)")
        continue

    for name, status in slots.items():
        excluded_tag = "" if is_notifiable_slot(name, status) else " [SUPPRESSED FROM NOTIFICATIONS]"
        unknown_tag = " <-- UNKNOWN STATUS, CHECK THIS" if "Unknown status" in status else ""
        # Flag anything that looks suspicious: a slot "name" that's
        # suspiciously short/generic could indicate the same bug we just
        # fixed (a status label mistaken for a name).
        suspicious = ""
        if name in ("Available", "All Spots Filled", "Medical Available",
                    "Near Capacity", "Register") or len(name) < 4:
            suspicious = " <-- SUSPICIOUS NAME, MIGHT BE A MIS-PARSED STATUS LABEL"
        print(f"  '{name}': '{status}'{excluded_tag}{unknown_tag}{suspicious}")
