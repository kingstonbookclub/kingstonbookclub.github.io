#!/usr/bin/env python3
"""
Sync upcoming events from a public Google Calendar.

Members add meetings to the club calendar; this writes _data/events.yml and
keeps the "Currently Reading" date and chapters in step with the next meeting.

The calendar event's title is used verbatim as the event description, so it
should read the way it should appear on the site:

    Crime and Punishment (Part 6 - first half)

Whatever is in parentheses becomes the "chapters" line under Currently Reading
("Part 6 - first half"). A title with no parentheses - "Short-form Science Week"
- still lists as an event but leaves Currently Reading alone.

Needs CALENDAR_ICS_URL (repository variable). A public Google Calendar's iCal
address needs no API key.
"""

import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import recurring_ical_events
import requests
import yaml
from icalendar import Calendar

REPO_ROOT = Path(__file__).resolve().parent.parent
EVENTS_YML = REPO_ROOT / "_data" / "events.yml"
CURRENT_YML = REPO_ROOT / "_data" / "current-reading.yml"

ICS_URL = os.environ.get("CALENDAR_ICS_URL", "").strip()
MAX_UPCOMING = int(os.environ.get("MAX_UPCOMING", "4"))
UPDATE_CURRENT_READING = os.environ.get("UPDATE_CURRENT_READING", "true").lower() in (
    "1",
    "true",
    "yes",
)
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

# The club is in Jamaica, which has no daylight saving. Using local time here
# stops an evening meeting from looking like it's already passed.
TZ = ZoneInfo("America/Jamaica")

PARENTHETICAL = re.compile(r"\(([^)]+)\)")


def log(msg):
    print(msg, flush=True)


def fail(msg):
    print(f"::error::{msg}", flush=True)
    sys.exit(1)


def ordinal(n):
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def as_date(value):
    """ICS gives dates for all-day events and datetimes for timed ones."""
    if isinstance(value, datetime):
        return value.astimezone(TZ).date() if value.tzinfo else value.date()
    return value


def fetch_events():
    """Upcoming events from the calendar, soonest first."""
    try:
        resp = requests.get(ICS_URL, timeout=60)
    except requests.RequestException as exc:
        fail(f"Could not reach the calendar: {exc}")

    if resp.status_code == 404:
        fail(
            "Calendar not found (404). Check CALENDAR_ICS_URL, and that the "
            'calendar is set to "Make available to public" in Google Calendar '
            "settings - the secret iCal address expires and is not public."
        )
    resp.raise_for_status()

    if "BEGIN:VCALENDAR" not in resp.text:
        fail(
            "That URL did not return a calendar feed. Use the *public* address "
            "in iCal format from Google Calendar settings - it ends in .ics"
        )

    calendar = Calendar.from_ical(resp.text)
    today = datetime.now(TZ).date()

    # Expand any repeating events into individual dates.
    occurrences = recurring_ical_events.of(calendar).between(
        today, today + timedelta(days=365)
    )

    events = []
    for occurrence in occurrences:
        starts = as_date(occurrence.get("DTSTART").dt)
        if starts < today:
            continue
        title = str(occurrence.get("SUMMARY") or "").strip()
        if not title:
            log(f"  ! Skipping an untitled event on {starts}")
            continue
        events.append({"date": starts, "title": title})

    events.sort(key=lambda e: e["date"])
    return events


def write_events(events):
    entries = [
        # "AUG 8, 2026" - month abbreviated and capitalised, day not zero-padded.
        {"date": f"{e['date'].strftime('%b').upper()} {e['date'].day}, {e['date'].year}",
         "description": e["title"]}
        for e in events
    ]
    header = (
        "# GENERATED FILE - DO NOT EDIT BY HAND.\n"
        "#\n"
        "# Rewritten by .github/workflows/sync-calendar.yml from the club's Google\n"
        "# Calendar. To change what's here, add or edit the event in the calendar.\n\n"
    )
    body = yaml.safe_dump(
        {"events": entries}, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    EVENTS_YML.write_text(header + body, encoding="utf-8")


def update_current_reading(next_event):
    """Point Currently Reading at the next meeting, leaving the book alone."""
    data = yaml.safe_load(CURRENT_YML.read_text(encoding="utf-8")) or {}

    when = next_event["date"]
    data["current_date"] = (
        f"{when.strftime('%B')} {ordinal(when.day)}, {when.year}"
    )

    match = PARENTHETICAL.search(next_event["title"])
    if match:
        data["chapters"] = match.group(1).strip()
    else:
        log(
            f"  ! '{next_event['title']}' has no (parentheses), so the chapters "
            f"line stays as \"{data.get('chapters', '')}\". Edit it by hand if the "
            "next meeting covers something different."
        )

    header = (
        "# Current Reading Book Information\n"
        "#\n"
        "# current_date and chapters are set automatically from the next event on\n"
        "# the club calendar. The book title, author, image and links are NOT -\n"
        "# edit those here when starting a new book.\n\n"
    )
    body = yaml.safe_dump(
        data, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    CURRENT_YML.write_text(header + body, encoding="utf-8")
    return data


def main():
    if not ICS_URL:
        log("::notice::Calendar sync not configured yet - CALENDAR_ICS_URL is unset.")
        log("Nothing to do. Add it in Settings > Secrets and variables > Actions.")
        return

    log("Reading the club calendar\n")
    events = fetch_events()

    if not events:
        # Never blank the events section because someone forgot to add dates.
        fail(
            "The calendar has no upcoming events, so there is nothing to publish. "
            "Leaving _data/events.yml untouched. Add the next few meetings to the "
            "calendar and run this again."
        )

    upcoming = events[:MAX_UPCOMING]
    log(f"{len(events)} upcoming event(s) found; publishing the next {len(upcoming)}:\n")
    for event in upcoming:
        log(f"  {event['date']}  {event['title']}")

    if DRY_RUN:
        log("\nDRY RUN - nothing written.")
        if UPDATE_CURRENT_READING:
            match = PARENTHETICAL.search(upcoming[0]["title"])
            when = upcoming[0]["date"]
            log(
                f"\nCurrently Reading would become:\n"
                f"  current_date: {when.strftime('%B')} {ordinal(when.day)}, {when.year}\n"
                f"  chapters:     {match.group(1).strip() if match else '(unchanged)'}"
            )
        return

    write_events(upcoming)
    log(f"\nWrote {EVENTS_YML.relative_to(REPO_ROOT)}")

    if UPDATE_CURRENT_READING:
        data = update_current_reading(upcoming[0])
        log(
            f"Wrote {CURRENT_YML.relative_to(REPO_ROOT)} "
            f"(chapters: \"{data.get('chapters', '')}\", "
            f"date: \"{data.get('current_date', '')}\")"
        )


if __name__ == "__main__":
    main()
