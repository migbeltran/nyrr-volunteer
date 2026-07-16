#!/usr/bin/env python3
"""
Checks NYRR (Haku Sports) volunteer pages for slot availability.
- Sends an ntfy push notification immediately if any slot's status changed
  since the last run (e.g. Filled -> Available, or vice versa).
- Sends a full status summary every time it's run (intended to run at
  11am and 8pm ET via GitHub Actions cron).

State is persisted in state.json so runs can compare against the past.
"""

import json
import os
import sys
import requests
from bs4 import BeautifulSoup

# --- Configuration ---------------------------------------------------

URLS = [
    "https://events.nyrr.org/nyrr-team-champions-5m-volunteers",
    # add more event URLs here as needed
]

STATE_FILE = "state.json"

# Set this as a GitHub Actions secret and reference it via env var below.
NTFY_TOPIC = os.environ.get("NTFY_TOPIC")  # e.g. "miguel-volunteer-slots-8x2k"
NTFY_URL = f"https://ntfy.sh/{NTFY_TOPIC}" if NTFY_TOPIC else None

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

# --- Scraping ----------------------------------------------------------

def fetch_slots(url):
    """Returns a dict of {slot_name: status} for one event page."""
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    slots = {}
    # Each assignment option is a <li> containing a status <p> tag
    # ("Available" or "All Spots Filled") plus the slot name and tag text.
    status_tags = soup.find_all(
        string=lambda t: t and ("All Spots Filled" in t or t.strip() == "Available")
    )
    # find_all(string=...) returns NavigableString nodes; get their parent tag
    status_tags = [t.parent for t in status_tags]
    for status_tag in status_tags:
        status = "Available" if "Available" in status_tag.get_text() else "All Spots Filled"
        li = status_tag.find_parent("li")
        if not li:
            continue
        # Get all text in the <li>, split into lines, drop the status text
        # and the "Register" link text, keep the first remaining line as
        # the slot name.
        lines = [
            line.strip() for line in li.get_text("\n").split("\n")
            if line.strip() and line.strip() not in (
                "Available", "All Spots Filled", "Register"
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
    return {}


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
    new_state = {}
    changes = []
    summary_lines = []

    for url in URLS:
        try:
            slots = fetch_slots(url)
        except Exception as e:
            summary_lines.append(f"[ERROR] {url}: {e}")
            continue

        new_state[url] = slots
        old_slots = old_state.get(url, {})

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

    # Always send the scheduled summary
    send_notification(
        "Volunteer slots - status check",
        "\n".join(summary_lines) if summary_lines else "No data collected.",
        priority="default",
    )

    save_state(new_state)


if __name__ == "__main__":
    main()
