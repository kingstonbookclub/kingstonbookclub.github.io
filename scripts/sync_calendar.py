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

Short-form reads weeks are driven from the same calendar entry. When the next
event's title mentions "short form" or "short reads", the article list is read
out of that event's *description* - one article per line, with its link - and
published to _data/short-reading.yml with the section switched on. Once a normal
book week is next again, the section switches itself back off.

Needs CALENDAR_ICS_URL (repository variable). A public Google Calendar's iCal
address needs no API key.
"""

import html
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
SHORT_YML = REPO_ROOT / "_data" / "short-reading.yml"

ICS_URL = os.environ.get("CALENDAR_ICS_URL", "").strip()
MAX_UPCOMING = int(os.environ.get("MAX_UPCOMING", "4"))
UPDATE_CURRENT_READING = os.environ.get("UPDATE_CURRENT_READING", "true").lower() in (
    "1",
    "true",
    "yes",
)
UPDATE_SHORT_READS = os.environ.get("UPDATE_SHORT_READS", "true").lower() in (
    "1",
    "true",
    "yes",
)
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

# The club is in Jamaica, which has no daylight saving. Using local time here
# stops an evening meeting from looking like it's already passed.
TZ = ZoneInfo("America/Jamaica")

PARENTHETICAL = re.compile(r"\(([^)]+)\)")
# "The Problem of Pain - Divine Goodness": everything after a spaced dash is the
# chapters. Parentheses win when both are present, so "Crime and Punishment
# (Part 6 - first half)" still yields "Part 6 - first half".
DASHED = re.compile(r"\s+[-\u2013\u2014]\s+")

# "Short-form Poetry Week", "Short Form Reads", "short reads". Requiring the
# second word keeps a book like "A Short History of Nearly Everything" from
# being mistaken for a short-reads week.
SHORT_WEEK = re.compile(r"short[\s-]*(form|read)", re.IGNORECASE)

URL = re.compile(r"https?://[^\s<>\"']+")
LIST_PREFIX = re.compile(r"^\s*(?:\d+\s*[.)\-]|[-*\u2022])\s*")
TRAILING_SEP = re.compile(r"[\s\-\u2013\u2014:;,]+$")
INVISIBLE = re.compile(r"[\u200b-\u200f\u2060-\u2064\ufeff]")

# Links Google Calendar or a member adds for the meeting itself, not readings.
NOT_AN_ARTICLE = (
    "meet.google.com",
    "calendar.google.com",
    "zoom.us",
    "teams.microsoft.com",
    "teams.live.com",
    "webex.com",
    "maps.google.com",
    "goo.gl/maps",
    "wa.me",
    "chat.whatsapp.com",
)


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
        events.append(
            {
                "date": starts,
                "title": title,
                "description": str(occurrence.get("DESCRIPTION") or ""),
            }
        )

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


def chapters_from(title):
    """The part of an event title that names what to read, or "" if absent."""
    match = PARENTHETICAL.search(title)
    if match:
        return match.group(1).strip()
    parts = DASHED.split(title, maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def update_current_reading(next_event):
    """Point Currently Reading at the next meeting, leaving the book alone."""
    data = yaml.safe_load(CURRENT_YML.read_text(encoding="utf-8")) or {}

    when = next_event["date"]
    data["current_date"] = (
        f"{when.strftime('%B')} {ordinal(when.day)}, {when.year}"
    )

    chapters = chapters_from(next_event["title"])
    if chapters:
        data["chapters"] = chapters
    else:
        log(
            f"  ! '{next_event['title']}' has no (parentheses) and no ' - ', so "
            f"the chapters "
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


def clean_description(raw):
    """Flatten a calendar description to plain lines of text."""
    text = str(raw or "")
    # Google sometimes stores descriptions as HTML. Keep link targets by
    # rewriting <a href="URL">Text</a> as "Text URL" before dropping tags.
    text = re.sub(
        r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r"\2 \1", text, flags=re.I | re.S
    )
    text = re.sub(r"<br\s*/?>|</(?:p|div|li|tr)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Pastes out of WhatsApp carry invisible separator characters.
    return INVISIBLE.sub("", text)


def parse_articles(description):
    """Pull "title + link" pairs out of a calendar event's description.

    Accepts the shape people actually paste - a numbered title on one line and
    its link on the next, or both on the same line.
    """
    lines = [LIST_PREFIX.sub("", line).strip() for line in clean_description(description).split("\n")]

    articles = []
    pending_title = ""
    for line in lines:
        found = [
            url.rstrip(".,;:)")
            for url in URL.findall(line)
            if not any(skip in url.lower() for skip in NOT_AN_ARTICLE)
        ]
        if not found:
            # A line with no link is the title for the link on a following line.
            if line and not URL.search(line):
                pending_title = line
            continue
        title = TRAILING_SEP.sub("", URL.sub("", line)).strip() or pending_title
        for url in found:
            articles.append({"title": title or url, "url": url})
        pending_title = ""

    seen = set()
    unique = []
    for article in articles:
        if article["url"] in seen:
            continue
        seen.add(article["url"])
        unique.append(article)
    return unique


def short_reads_for(event):
    """(is this a short-reads week, the articles listed on it)"""
    if not SHORT_WEEK.search(event["title"]):
        return False, []
    return True, parse_articles(event.get("description"))


def write_short_reading(enabled, articles):
    existing = yaml.safe_load(SHORT_YML.read_text(encoding="utf-8")) or {}
    data = {
        "enabled": enabled,
        # Keep the previous list when switching off, so it is not lost.
        "articles": articles or existing.get("articles") or [],
    }
    header = (
        "# GENERATED FILE - DO NOT EDIT BY HAND.\n"
        "#\n"
        "# Rewritten by .github/workflows/sync-calendar.yml. The section switches on\n"
        "# when the next event on the club calendar is a short-reads week, and the\n"
        "# articles come from that event's description - one per line with its link.\n\n"
    )
    body = yaml.safe_dump(
        data, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    SHORT_YML.write_text(header + body, encoding="utf-8")


def sync_short_reads(next_event):
    """Switch the short-reads section on or off to match the next meeting."""
    is_short, articles = short_reads_for(next_event)

    if is_short and not articles:
        log(
            f"\n  ! '{next_event['title']}' looks like a short-reads week, but its "
            "calendar description has no links in it. Leaving "
            f"{SHORT_YML.name} alone rather than publishing an empty list - paste "
            "the articles into the event's description."
        )
        return

    if is_short:
        write_short_reading(True, articles)
        log(f"\nWrote {SHORT_YML.relative_to(REPO_ROOT)} - short reads ON:")
        for article in articles:
            log(f"  - {article['title']}")
        return

    existing = yaml.safe_load(SHORT_YML.read_text(encoding="utf-8")) or {}
    if existing.get("enabled"):
        write_short_reading(False, [])
        log(
            f"\nWrote {SHORT_YML.relative_to(REPO_ROOT)} - short reads OFF "
            f"(next up is '{next_event['title']}'). The article list is kept."
        )


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

    next_event = upcoming[0]
    is_short, articles = short_reads_for(next_event)

    if DRY_RUN:
        log("\nDRY RUN - nothing written.")
        if UPDATE_CURRENT_READING:
            if is_short:
                log(
                    "\nCurrently Reading would be left alone - the next meeting is a "
                    "short-reads week, so that section is hidden anyway."
                )
            else:
                chapters = chapters_from(next_event["title"])
                when = next_event["date"]
                log(
                    f"\nCurrently Reading would become:\n"
                    f"  current_date: {when.strftime('%B')} {ordinal(when.day)}, {when.year}\n"
                    f"  chapters:     {chapters or '(unchanged)'}"
                )
        if UPDATE_SHORT_READS:
            if is_short and articles:
                log("\nShort reads would be switched ON, with:")
                for article in articles:
                    log(f"  - {article['title']}\n      {article['url']}")
            elif is_short:
                log(
                    "\nShort reads: this looks like a short-reads week but the event "
                    "description has no links, so nothing would change."
                )
            else:
                log("\nShort reads would be switched OFF (next up is a book week).")
        return

    write_events(upcoming)
    log(f"\nWrote {EVENTS_YML.relative_to(REPO_ROOT)}")

    if UPDATE_CURRENT_READING and not is_short:
        data = update_current_reading(next_event)
        log(
            f"Wrote {CURRENT_YML.relative_to(REPO_ROOT)} "
            f"(chapters: \"{data.get('chapters', '')}\", "
            f"date: \"{data.get('current_date', '')}\")"
        )
    elif UPDATE_CURRENT_READING:
        log(
            "Left current-reading.yml alone - the next meeting is a short-reads "
            "week, so Currently Reading stays on the main book."
        )

    if UPDATE_SHORT_READS:
        sync_short_reads(next_event)


if __name__ == "__main__":
    main()
