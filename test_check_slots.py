"""
Test parse_html() against fake HTML snippets - no network needed.
Run with: python3 test_check_slots.py
"""

import sys
sys.path.insert(0, ".")
from check_slots import parse_html, is_excluded_slot, is_notifiable_slot

# Reproduces the exact bug from the screenshot: a new status label
# ("Near Capacity", goldenrod #DAA520) that didn't exist before.
FAKE_HTML_NEAR_CAPACITY = """
<html><body>
<div class="event-info-bar-text-color">Sunday, July 26, 2026 at 05:00 AM</div>
<ul class="race-list list-unstyled">
  <li>
    <div class="category-box u-border-radius-0-i">
      <div class="u-display-block u-padding-bottom-20 u-padding-top-10">
        <span style="color: #DAA520">Near Capacity</span>
      </div>
      Volunteer Leaders and Leaders in Training (NO +1)
      No +1
    </div>
  </li>
  <li>
    <div class="category-box u-border-radius-0-i">
      <div class="u-display-block u-padding-bottom-20 u-padding-top-10">
        <p style="color: #FF0000">All Spots Filled</p>
      </div>
      Bag Check
      9+1
    </div>
  </li>
  <li>
    <div class="category-box u-border-radius-0-i">
      <div class="u-display-block u-padding-bottom-20 u-padding-top-10">
        <p style="color: #15803D">Available</p>
      </div>
      Course Marshal North
      9+1
    </div>
  </li>
</ul>
</body></html>
"""


def test_near_capacity_name_extraction():
    """The bug: 'Near Capacity' label was being mistaken for the slot name."""
    event_date, slots = parse_html(FAKE_HTML_NEAR_CAPACITY)

    print("Parsed slots:")
    for name, status in slots.items():
        print(f"  '{name}': '{status}'")
    print()

    # The real slot name should be preserved, NOT "Near Capacity"
    expected_name = "Volunteer Leaders and Leaders in Training (NO +1)"
    assert expected_name in slots, (
        f"FAIL: expected slot name '{expected_name}' not found. "
        f"Got keys: {list(slots.keys())}"
    )
    assert "Near Capacity" not in slots, (
        "FAIL: 'Near Capacity' (the status label) was mistaken for a slot name"
    )
    assert slots[expected_name] == "Near Capacity", (
        f"FAIL: expected 'Near Capacity' status, got '{slots[expected_name]}'"
    )

    # And the exclusion filter should now correctly catch it
    assert is_excluded_slot(expected_name), (
        "FAIL: exclusion filter should catch this slot name now that it's "
        "extracted correctly"
    )

    # Sanity check the other two normal slots still parse fine
    assert slots.get("Bag Check") == "All Spots Filled"
    assert slots.get("Course Marshal North") == "Available"

    print("PASS: 'Near Capacity' bug is fixed, exclusion filter works correctly.")


# Verifies the new architecture: Medical Available must now be CAPTURED
# (not silently dropped during parsing), even though it's still suppressed
# from notifications via the separate decision layer.
FAKE_HTML_MEDICAL = """
<html><body>
<ul class="race-list list-unstyled">
  <li>
    <div class="category-box">
      <div class="u-display-block">
        <span style="color: #1E90FF">Medical Available</span>
      </div>
      Medical Team
      2+1
    </div>
  </li>
  <li>
    <div class="category-box">
      <div class="u-display-block">
        <p style="color: #15803D">Available</p>
      </div>
      Bag Check
      9+1
    </div>
  </li>
</ul>
</body></html>
"""


def test_medical_available_is_captured_but_not_notifiable():
    event_date, slots = parse_html(FAKE_HTML_MEDICAL)

    print("Parsed slots (Medical test):")
    for name, status in slots.items():
        print(f"  '{name}': '{status}'")
    print()

    # Stage 1 check: must be CAPTURED - this is the whole point of the
    # restructure. It should NOT be silently missing from raw data.
    assert "Medical Team" in slots, (
        "FAIL: Medical Available slot was dropped during parsing - it "
        "should always be captured, regardless of notification decisions"
    )
    assert slots["Medical Team"] == "Medical Available"

    # Stage 2 check: still correctly suppressed from notifications
    assert not is_notifiable_slot("Medical Team", "Medical Available"), (
        "FAIL: Medical Available should be suppressed from notifications"
    )

    # Sanity: a normal Available slot should still be notifiable
    assert is_notifiable_slot("Bag Check", "Available")

    print("PASS: Medical Available is captured in raw data but correctly "
          "suppressed from notifications.")


def test_near_capacity_is_notifiable_by_default():
    """New/unrecognized statuses should default to notifiable (visible),
    per the 'default to visible' decision - nothing new goes unnoticed."""
    assert is_notifiable_slot(
        "Course Marshal South", "Unknown status (color #123456)"
    ), "FAIL: unrecognized statuses should default to notifiable"
    print("PASS: unrecognized/new statuses default to notifiable.")


def test_excluded_name_with_hidden_status_is_still_excluded():
    """A Leaders slot that happens to ALSO have a hidden status should
    still be excluded (name-based exclusion applies independently)."""
    assert not is_notifiable_slot(
        "Volunteer Leaders and Leaders in Training (NO +1)", "Available"
    ), "FAIL: Leaders slots should be excluded regardless of their status"
    print("PASS: name-based exclusion works independently of status.")


if __name__ == "__main__":
    test_near_capacity_name_extraction()
    test_medical_available_is_captured_but_not_notifiable()
    test_near_capacity_is_notifiable_by_default()
    test_excluded_name_with_hidden_status_is_still_excluded()
    print("\nAll tests passed.")
