#!/usr/bin/env python3
"""
Sync the homepage gallery from a shared Google Drive folder.

Drive is the source of truth. This script reads the curated "KBC Website Gallery"
folder, downloads the photos, shrinks them for the web, and rewrites
_data/gallery.yml. Nobody needs to touch YAML or git to update the gallery.

Expected Drive layout:

    KBC Website Gallery/
      2026-04-03 KBC Hills & Valleys Camping Trip @ Holywell/
        photo1.jpg
        photo2.jpg
      2026-02-28 Meeting #8 @ Ragamuffin Cafe/
        ...

The folder name supplies the caption for every photo inside it. A photo's Drive
"description" field, if set, overrides the caption for that one photo.

Needs GOOGLE_API_KEY (repo secret) and DRIVE_FOLDER_ID (repo variable).
"""

import io
import json
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
import yaml
from PIL import Image, ImageOps

# iPhone photos are usually HEIC, which Pillow can't read on its own.
try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass

DRIVE_API = "https://www.googleapis.com/drive/v3/files"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

REPO_ROOT = Path(__file__).resolve().parent.parent
IMAGE_DIR = REPO_ROOT / "images" / "gallery"
GALLERY_YML = REPO_ROOT / "_data" / "gallery.yml"
EXTRA_YML = REPO_ROOT / "_data" / "gallery-extra.yml"
MANIFEST = REPO_ROOT / "_data" / "gallery-sync.json"


def folder_id_from(value):
    """Accept either a bare folder ID or a pasted Drive share link."""
    value = value.strip()
    match = re.search(r"/folders/([A-Za-z0-9_-]+)", value)
    if match:
        return match.group(1)
    # Some share links use ?id=<folder id> instead.
    match = re.search(r"[?&]id=([A-Za-z0-9_-]+)", value)
    if match:
        return match.group(1)
    return value


API_KEY = os.environ.get("GOOGLE_API_KEY", "").strip()
FOLDER_ID = folder_id_from(os.environ.get("DRIVE_FOLDER_ID", ""))
MAX_EVENTS = int(os.environ.get("MAX_EVENTS", "6"))
MAX_PER_EVENT = int(os.environ.get("MAX_PER_EVENT", "3"))
MAX_LOOSE = int(os.environ.get("MAX_LOOSE", "4"))
MAX_WIDTH = int(os.environ.get("MAX_WIDTH", "1600"))
JPEG_QUALITY = int(os.environ.get("JPEG_QUALITY", "82"))
DRY_RUN = os.environ.get("DRY_RUN", "").lower() in ("1", "true", "yes")

DATED_FOLDER = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[\s_-]+(.+)$")

# Dates the way people actually type them in folder names: "May 30th 2026",
# "Aug 1st, 2026", "30 May 2026", or just "June 27".
MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]
_MONTH = r"([A-Za-z]{3,9})\.?"
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"
_YEAR = r"(?:,?\s+(\d{4}))?"
MONTH_FIRST = re.compile(rf"\b{_MONTH}\s+{_DAY}\b{_YEAR}", re.IGNORECASE)
DAY_FIRST = re.compile(rf"\b{_DAY}\s+(?:of\s+)?{_MONTH}\b{_YEAR}", re.IGNORECASE)
MEETING_NUMBER = re.compile(r"#\s*(\d+)")


def log(msg):
    print(msg, flush=True)


def fail(msg):
    print(f"::error::{msg}", flush=True)
    sys.exit(1)


# --------------------------------------------------------------------------
# Google Drive
# --------------------------------------------------------------------------


def drive_list(parent_id, required=True):
    """List every child of a Drive folder, following pagination.

    When required is False an unreadable folder is skipped with a warning rather
    than killing the run. That happens with shortcuts pointing into folders that
    were never shared - the shortcut is visible but its target is not.
    """
    items = []
    page_token = None
    while True:
        params = {
            "q": f"'{parent_id}' in parents and trashed = false",
            "key": API_KEY,
            "fields": (
                "nextPageToken, files(id, name, mimeType, description, "
                "createdTime, modifiedTime, size, shortcutDetails, "
                "imageMediaMetadata(time))"
            ),
            "pageSize": 200,
            "orderBy": "name",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token

        resp = requests.get(DRIVE_API, params=params, timeout=60)
        if resp.status_code in (403, 404) and not required:
            log(
                f"    ! Can't read folder {parent_id} (HTTP {resp.status_code}). If "
                "this is a shortcut, the folder it points at isn't shared. Skipping."
            )
            return items
        if resp.status_code == 403:
            fail(
                "Drive API returned 403. Check that the API key has the Drive API "
                "enabled and has no HTTP-referrer restriction (GitHub Actions sends "
                "no referrer, so set Application restrictions to None)."
            )
        if resp.status_code == 404:
            fail(
                f"Drive folder {parent_id} not found. Check DRIVE_FOLDER_ID, and "
                'that the folder is shared as "Anyone with the link can view".'
            )
        resp.raise_for_status()

        payload = resp.json()
        items.extend(payload.get("files", []))
        page_token = payload.get("nextPageToken")
        if not page_token:
            return items


def resolve_shortcut(item):
    """Turn a Drive shortcut into the thing it points at, keeping its name."""
    if item.get("mimeType") != SHORTCUT_MIME:
        return item
    details = item.get("shortcutDetails") or {}
    target_id = details.get("targetId")
    if not target_id:
        return None
    resolved = dict(item)
    resolved["id"] = target_id
    resolved["mimeType"] = details.get("targetMimeType", "")
    return resolved


def drive_download(file_id):
    """Fetch a photo's bytes, or None if Drive won't share it with us."""
    resp = requests.get(
        f"{DRIVE_API}/{file_id}",
        params={"alt": "media", "key": API_KEY, "supportsAllDrives": "true"},
        timeout=300,
    )
    if resp.status_code in (403, 404):
        return None
    resp.raise_for_status()
    return resp.content


# --------------------------------------------------------------------------
# Captions
# --------------------------------------------------------------------------


def ordinal(n):
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def month_number(word):
    """'Aug', 'august', 'Sept' -> 8, 8, 9. Anything else -> None."""
    word = word.lower()
    for index, name in enumerate(MONTH_NAMES, 1):
        if name.startswith(word):
            return index
    return None


def make_date(year, month, day):
    """Build a date, guessing the year when the folder name left it out."""
    try:
        if year:
            return date(int(year), month, int(day))
        today = date.today()
        guess = date(today.year, month, int(day))
        # "Dec 20" written in January means last December, not next.
        if guess > today + timedelta(days=7):
            guess = date(today.year - 1, month, int(day))
        return guess
    except ValueError:
        return None


def date_in_text(text):
    """Find a written-out date anywhere in a folder name."""
    for match in MONTH_FIRST.finditer(text):
        word, day, year = match.groups()
        month = month_number(word)
        if month and (found := make_date(year, month, day)):
            return found
    for match in DAY_FIRST.finditer(text):
        day, word, year = match.groups()
        month = month_number(word)
        if month and (found := make_date(year, month, day)):
            return found
    return None


def parse_event_folder(name):
    """Work out an event folder's date and title.

    Returns (date, title, date_is_prefix). A "2026-04-03 Title" prefix is
    stripped from the title and re-added to the caption in a readable form.
    A date written anywhere else - "KBC Meeting #21 - May 30th 2026" - is left
    in the title as the member wrote it and only used for ordering.
    """
    name = name.strip()
    match = DATED_FOLDER.match(name)
    if match:
        year, month, day, title = match.groups()
        found = make_date(year, int(month), day)
        if found:
            return found, title.strip(), True
    return date_in_text(name), name, False


def parse_drive_time(value):
    """Drive timestamps ('2026-05-30T14:22:01.000Z') or EXIF ones ('2026:05:30 14:22:01')."""
    if not value:
        return None
    try:
        if value[4] == ":":
            return datetime.strptime(value[:19], "%Y:%m:%d %H:%M:%S")
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, IndexError):
        return None


def build_caption(event_date, title):
    if event_date is None:
        return title
    stamp = f"{event_date.strftime('%B')} {ordinal(event_date.day)}, {event_date.year}"
    return f"{title} - {stamp}"


def slugify(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[\s_-]+", "-", value) or "photo"


# --------------------------------------------------------------------------
# Image processing
# --------------------------------------------------------------------------


def process_image(raw_bytes, dest):
    """Rotate upright, strip EXIF, resize, and save as a web-sized JPEG."""
    with Image.open(io.BytesIO(raw_bytes)) as img:
        # Must happen before we drop EXIF, or phone photos come out sideways.
        img = ImageOps.exif_transpose(img)

        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        if img.width > MAX_WIDTH:
            height = round(img.height * MAX_WIDTH / img.width)
            img = img.resize((MAX_WIDTH, height), Image.LANCZOS)

        # A fresh image drops EXIF entirely, including the GPS coordinates that
        # phone cameras bury in every photo.
        clean = Image.new(img.mode, img.size)
        clean.putdata(list(img.getdata()))

        dest.parent.mkdir(parents=True, exist_ok=True)
        clean.save(dest, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)


# --------------------------------------------------------------------------
# Gathering
# --------------------------------------------------------------------------


def collect_photos():
    """Walk the Drive folder and return the photos that belong on the site."""
    children = drive_list(FOLDER_ID)

    events = []
    for item in children:
        resolved = resolve_shortcut(item)
        if not resolved or resolved.get("mimeType") != FOLDER_MIME:
            continue
        event_date, title, date_is_prefix = parse_event_folder(item["name"])
        if event_date is None:
            created = parse_drive_time(item.get("createdTime"))
            event_date = created.date() if created else date.min
            log(
                f"  ! Folder '{item['name']}' has no date in its name, so it's "
                "ordered by when the folder was made in Drive. Put the meeting "
                "date in the name (e.g. 'May 30th 2026') to be sure it sorts right."
            )
        number = MEETING_NUMBER.search(item["name"])
        events.append(
            {
                "id": resolved["id"],
                "folder_name": item["name"],
                "date": event_date,
                "number": int(number.group(1)) if number else 0,
                "title": title,
                # Only a "2026-04-03 Title" prefix gets a reformatted date in the
                # caption; otherwise the name already reads the way it was typed.
                "caption": build_caption(event_date, title) if date_is_prefix else title,
            }
        )

    # Photos sitting loose at the top level, not filed under an event. These are
    # published with no caption at all.
    loose = []
    for item in children:
        resolved = resolve_shortcut(item)
        if not resolved or not resolved.get("mimeType", "").startswith("image/"):
            continue
        loose.append({**resolved, "name": item["name"], "description": item.get("description")})
    # Newest first: when the photo was taken if the camera recorded it, otherwise
    # when it was uploaded.
    loose.sort(
        key=lambda f: parse_drive_time((f.get("imageMediaMetadata") or {}).get("time"))
        or parse_drive_time(f.get("createdTime"))
        or datetime.min,
        reverse=True,
    )

    if not events and not loose:
        fail(
            f"Nothing to publish from Drive folder {FOLDER_ID}. Add photos directly "
            "to it for uncaptioned shots, or put them in a subfolder named like "
            "'2026-04-03 Meeting #9 @ Ragamuffin' to caption them."
        )

    # Newest event first. Two folders on the same date fall back to the higher
    # meeting number.
    events.sort(key=lambda e: (e["date"], e["number"]), reverse=True)

    kept_events = events[:MAX_EVENTS]
    for dropped in events[MAX_EVENTS:]:
        log(f"  - Skipping '{dropped['folder_name']}' (past the {MAX_EVENTS}-event limit)")

    photos = []
    for event in kept_events:
        log(f"  Event: {event['folder_name']}")
        files = []
        for item in drive_list(event["id"], required=False):
            resolved = resolve_shortcut(item)
            if not resolved:
                continue
            if not resolved.get("mimeType", "").startswith("image/"):
                continue
            files.append(
                {**resolved, "name": item["name"], "description": item.get("description")}
            )

        files.sort(key=lambda f: f["name"].lower())
        if len(files) > MAX_PER_EVENT:
            log(
                f"    ({len(files)} photos here; taking the first {MAX_PER_EVENT} "
                "by filename. Rename to reorder, or raise MAX_PER_EVENT.)"
            )

        for item in files[:MAX_PER_EVENT]:
            description = (item.get("description") or "").strip()
            caption = description or event["caption"]
            photos.append(
                {
                    "drive_id": item["id"],
                    "drive_name": item["name"],
                    "modified": item.get("modifiedTime", ""),
                    "caption": caption,
                    "alt": description or event["title"],
                    "local": f"{slugify(event['title'])}-{item['id'][:10]}.jpg",
                }
            )
            log(f"    + {item['name']}")

    # Loose photos go last, after every captioned event.
    if loose:
        log(f"  Loose photos (no caption)")
        if len(loose) > MAX_LOOSE:
            log(
                f"    ({len(loose)} loose photos; taking the newest {MAX_LOOSE}. "
                "File them into event subfolders, or raise MAX_LOOSE.)"
            )
        for item in loose[:MAX_LOOSE]:
            description = (item.get("description") or "").strip()
            photos.append(
                {
                    "drive_id": item["id"],
                    "drive_name": item["name"],
                    "modified": item.get("modifiedTime", ""),
                    # No folder to inherit from, so no caption unless one was typed
                    # into the photo's Drive description.
                    "caption": description,
                    "alt": description or "Kingston Book Club photo",
                    "local": f"photo-{item['id'][:10]}.jpg",
                }
            )
            log(f"    + {item['name']}")

    return photos


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------


def load_extra():
    """Hand-pinned entries that survive regardless of what's in Drive."""
    if not EXTRA_YML.exists():
        return []
    data = yaml.safe_load(EXTRA_YML.read_text(encoding="utf-8")) or {}
    return data.get("images") or []


def write_gallery(photos):
    entries = [
        {"path": f"/images/gallery/{p['local']}", "alt": p["alt"], "caption": p["caption"]}
        for p in photos
    ]
    entries.extend(load_extra())

    header = (
        "# GENERATED FILE - DO NOT EDIT BY HAND.\n"
        "#\n"
        "# This is rewritten by .github/workflows/sync-gallery.yml from the shared\n"
        "# Google Drive folder. Any edit here is overwritten on the next sync.\n"
        "#\n"
        "# To change the gallery, add or remove photos in the Drive folder.\n"
        "# To pin a photo permanently, use _data/gallery-extra.yml instead.\n"
        f"#\n# Last synced: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n\n"
    )
    body = yaml.safe_dump(
        {"images": entries}, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    GALLERY_YML.write_text(header + body, encoding="utf-8")


def main():
    # Not set up yet. Exit cleanly rather than emailing a failure twice a day.
    if not API_KEY or not FOLDER_ID:
        missing = []
        if not API_KEY:
            missing.append("GOOGLE_API_KEY (repository secret)")
        if not FOLDER_ID:
            missing.append("DRIVE_FOLDER_ID (repository variable)")
        log(f"::notice::Gallery sync not configured yet - missing {', '.join(missing)}.")
        log("Nothing to do. Add them in Settings > Secrets and variables > Actions.")
        return

    log(f"Reading Drive folder {FOLDER_ID}")
    log(
        f"Limits: newest {MAX_EVENTS} events, up to {MAX_PER_EVENT} photos each, "
        f"plus {MAX_LOOSE} uncaptioned\n"
    )

    photos = collect_photos()
    log(f"\n{len(photos)} photos selected for the gallery.")

    if DRY_RUN:
        log("\nDRY RUN - nothing downloaded, nothing written. Gallery would be:\n")
        for p in photos:
            log(f"  {p['caption']}\n    -> /images/gallery/{p['local']}")
        return

    previous = {}
    if MANIFEST.exists():
        previous = json.loads(MANIFEST.read_text(encoding="utf-8")).get("photos", {})

    IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    downloaded = skipped = 0
    published = []
    for photo in photos:
        dest = IMAGE_DIR / photo["local"]
        was = previous.get(photo["drive_id"])
        if dest.exists() and was and was.get("modified") == photo["modified"]:
            skipped += 1
            published.append(photo)
            continue

        log(f"  Downloading {photo['drive_name']}")
        raw = drive_download(photo["drive_id"])
        if raw is None:
            # Usually a shortcut whose target was never shared. Leave it out of
            # the gallery rather than publishing a broken image.
            log(
                f"    ! Drive won't serve '{photo['drive_name']}'. If it's a "
                "shortcut, share the original too, or copy the photo in instead. "
                "Skipping it."
            )
            continue
        process_image(raw, dest)
        downloaded += 1
        published.append(photo)

    if not published:
        fail("Every photo failed to download - refusing to publish an empty gallery.")

    photos = published

    # Drive is the source of truth, so anything no longer selected gets removed.
    keep = {p["local"] for p in photos}
    removed = 0
    for existing in IMAGE_DIR.glob("*.jpg"):
        if existing.name not in keep:
            log(f"  Removing {existing.name} (no longer in Drive)")
            existing.unlink()
            removed += 1

    write_gallery(photos)
    MANIFEST.write_text(
        json.dumps(
            {
                "synced_at": datetime.utcnow().isoformat() + "Z",
                "photos": {
                    p["drive_id"]: {"modified": p["modified"], "local": p["local"]}
                    for p in photos
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    log(f"\nDone. {downloaded} new/updated, {skipped} unchanged, {removed} removed.")


if __name__ == "__main__":
    main()
