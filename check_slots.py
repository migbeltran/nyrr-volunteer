#!/usr/bin/env python3
"""
Checks NYRR (Haku Sports) volunteer pages for slot availability.
- Sends an ntfy push notification immediately if any slot's status changed
  since the last run (e.g. Filled -> Available, or vice versa).
- Sends a full status summary once per Eastern calendar day, on the first
  run that happens after 8pm ET (robust to GitHub Actions schedule drift -
  see should_send_summary logic in main()).

State is persisted in state.json so runs can compare against the past.
"""

import json
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
import requests
from bs4 import BeautifulSoup

# --- Configuration ---------------------------------------------------

URLS = [
    "https://events.nyrr.org/nyrr-team-champions-5m-volunteers",
    "https://events.nyrr.org/tcs-new-york-city-marathon-training-series-12m-volunteers",
    "https://events.nyrr.org/nyrr-jersey-city-5k-volunteers",
    "https://events.nyrr.org/nyrr-staten-island-half-volunteers",
    "https://events.nyrr.org/nyrr-ted-corbitt-15k-volunteers",
    "https://events.nyrr.org/vcp-cross-country-2-volunteers",
    # add more event URLs here as needed
]

STATE_FILE = "state.json"

# The full summary only needs to fire once per day, after 8pm ET. Rather
# than checking for an exact hour match (which breaks if GitHub's scheduler
# drifts, as it often does), we track the LAST DATE a summary was sent.
# Any run - whenever it actually happens to fire - that occurs after 8pm ET
# on a day the summary hasn't gone out yet will send it and mark that date
# done. This is robust to scheduling jitter and handles DST automatically
# via the America/New_York zone (no manual UTC-offset updates needed).
SUMMARY_HOUR_ET = 20  # 8pm local time, Eastern (auto-adjusts for DST)
ET_ZONE = ZoneInfo("America/New_York")

# workflow_dispatch (manual "Run workflow" clicks) always sends the summary
# too, so you can test without waiting for the right hour.
FORCE_SUMMARY = os.environ.get("FORCE_SUMMARY", "false").lower() == "true"

# Set this as a GitHub Actions secret and reference it via env var below.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")  # e.g. "miguel-volunteer-slots-8x2k"
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}" if NTFY_TOPIC else None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

# Status labels are color-coded on this platform rather than always using
# the same wording. We match by color instead of exact text, so we're not
# thrown off by variants like "All Spots Filled" vs. some other future label.
#   #FF0000 (red)    -> Filled
#   #15803D (green)  -> Available
#   #1E90FF (blue)   -> "Medical Available" - deliberately ignored/skipped,
#                        per user preference (not a regular volunteer slot).
COLOR_STATUS_MAP = {
    "#FF0000": "All Spots Filled",
    "#15803D": "Available",
}
IGNORED_COLORS = {"#1E90FF"}  # Medical Available - skip entirely

# --- Scraping ----------------------------------------------------------

def fetch_slots(url):
    """Returns a dict of {slot_name: status} for one event page."""
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    slots = {}
    # Each assignment option is a <li> containing a status tag (<p> or <span>)
    # with an inline "color" style. We identify status by that color rather
    # than the text itself, since wording can vary across events.
    for tag in soup.find_all(["p", "span"], style=True):
        style = tag.get("style", "")
        match = re.search(r"color:\s*(#[0-9A-Fa-f]{3,6})", style)
        if not match:
            continue
        color = match.group(1).upper()

        if color in IGNORED_COLORS:
            continue  # e.g. "Medical Available" - not tracked
        if color not in COLOR_STATUS_MAP:
            continue  # unrecognized color, not a status tag we care about

        status = COLOR_STATUS_MAP[color]

        li = tag.find_parent("li")
        if not li:
            continue

        # Get all text in the <li>, drop known status labels and the
        # "Register" link text, keep the first remaining line as the name.
        lines = [
            line.strip() for line in li.get_text("\n").split("\n")
            if line.strip() and line.strip() not in (
                "Available", "All Spots Filled", "Medical Available", "Register"
            )
        ]
        if not lines:
            continue
        slot_name = lines[0]
        slots[slot_name] = status

    return slots


# --- State handling ------------------------------------------------------

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"slots": {}, "last_summary_date": None}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# --- Notifications -------------------------------------------------------

def send_notification(title, message, priority="default"):
    if not NTFY_URL:
        print("NTFY_TOPIC not set - skipping notification. Message was:")
        print(title, "-", message)
        return
    requests.post(
        NTFY_URL,
        data=message.encode("utf-8"),
        headers={
            "Title": title,
            "Priority": priority,
            "Content-Type": "text/plain; charset=utf-8",
        },
        timeout=10,
    )


# --- Main ------------------------------------------------------------------

def main():
    old_state = load_state()
    old_slots_by_url = old_state.get("slots", {})
    new_slots_by_url = {}
    changes = []
    summary_lines = []

    for url in URLS:
        try:
            slots = fetch_slots(url)
        except Exception as e:
            summary_lines.append(f"[ERROR] {url}: {e}")
            continue

        new_slots_by_url[url] = slots
        old_slots = old_slots_by_url.get(url, {})

        summary_lines.append(f"\n{url}")
        for name, status in slots.items():
            icon = "🟢" if status == "Available" else "🔴"
            summary_lines.append(f"  {icon} {name}: {status}")
            old_status = old_slots.get(name)
            if old_status is not None and old_status != status:
                old_icon = "🟢" if old_status == "Available" else "🔴"
                changes.append(
                    f"{old_icon}->{icon} {name} ({url}): {old_status} -> {status}"
                )

    # Immediate alert on any change
    if changes:
        send_notification(
            "Volunteer slot change!",
            "\n".join(changes),
            priority="high",
        )

    # Send the full summary once per Eastern calendar day, on the first run
    # that happens after 8pm ET - whenever that actually fires. This is
    # robust to GitHub's scheduler drifting, unlike checking for an exact
    # hour match.
    now_et = datetime.now(ET_ZONE)
    today_et_str = now_et.strftime("%Y-%m-%d")
    summary_already_sent_today = old_state.get("last_summary_date") == today_et_str
    should_send_summary = FORCE_SUMMARY or (
        now_et.hour >= SUMMARY_HOUR_ET and not summary_already_sent_today
    )

    new_last_summary_date = old_state.get("last_summary_date")
    if should_send_summary:
        send_notification(
            "Volunteer slots - status check",
            "\n".join(summary_lines) if summary_lines else "No data collected.",
            priority="default",
        )
        # Only actually mark today "done" for real (non-forced) sends, so
        # manual test runs via workflow_dispatch don't block tonight's
        # real scheduled summary from also going out.
        if not FORCE_SUMMARY:
            new_last_summary_date = today_et_str

    new_state = {
        "slots": new_slots_by_url,
        "last_summary_date": new_last_summary_date,
    }
    save_state(new_state)


if __name__ == "__main__":
    main()
