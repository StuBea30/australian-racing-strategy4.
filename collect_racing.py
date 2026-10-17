
#!/usr/bin/env python3
"""
Australian Racing Strategy 4.0
Live programme discovery and source capture.

Sources:
  Ladbrokes Form Guide
  Racing and Sports (reference source)

This module discovers meetings and race links,
saves source HTML and creates a coverage manifest.

It does not invent horses, form or scores.
"""

import argparse
import csv
import datetime as dt
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE = "https://ladbrokesform.com.au"

ALL_STATES = {"VIC", "NSW", "SA"}
METRO_STATES = {"QLD", "WA", "TAS", "ACT"}

# A starter mapping for known racecourses.
# Unknown courses remain unclassified and
# are reported for review, never silently
# treated as ineligible.
COURSES = {
    "Moe": ("VIC", False),
    "Horsham": ("VIC", False),
    "Caulfield": ("VIC", True),
    "Flemington": ("VIC", True),
    "Moonee Valley": ("VIC", True),
    "Sandown": ("VIC", True),
    "Bendigo": ("VIC", False),
    "Ballarat": ("VIC", False),
    "Geelong": ("VIC", False),
    "Wodonga": ("VIC", False),
    "Warrnambool": ("VIC", False),
    "Mornington": ("VIC", False),
    "Randwick": ("NSW", True),
    "Rosehill": ("NSW", True),
    "Warwick Farm": ("NSW", True),
    "Canterbury": ("NSW", True),
    "Nowra": ("NSW", False),
    "Lismore": ("NSW", False),
    "Newcastle": ("NSW", False),
    "Kembla Grange": ("NSW", False),
    "Goulburn": ("NSW", False),
    "Wagga": ("NSW", False),
    "Hawkesbury": ("NSW", False),
    "Morphettville": ("SA", True),
    "Murray Bridge": ("SA", False),
    "Strathalbyn": ("SA", False),
    "Balaklava": ("SA", False),
    "Gawler": ("SA", False),
    "Oakbank": ("SA", False),
    "Port Lincoln": ("SA", False),
    "Doomben": ("QLD", True),
    "Eagle Farm": ("QLD", True),
    "Gold Coast": ("QLD", False),
    "Townsville": ("QLD", False),
    "Sunshine Coast": ("QLD", False),
    "Ascot": ("WA", True),
    "Belmont": ("WA", True),
    "Pinjarra": ("WA", False),
    "Kalgoorlie": ("WA", False),
    "Hobart": ("TAS", True),
    "Launceston": ("TAS", True),
    "Devonport": ("TAS", False),
    "Canberra": ("ACT", True),
}

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (compatible; "
        "RacingStrategy4Research/1.0)"
    ),
    "Accept": "text/html,application/xhtml+xml",
})

TIMEOUT = 25


def tomorrow_in_sydney():
    return (
        dt.datetime.now(ZoneInfo("Australia/Sydney"))
        + dt.timedelta(days=1)
    ).date().isoformat()


def normalise(value):
    return re.sub(r"\s+", " ", value).strip()


def classify_course(name):
    name = normalise(name).lower()

    for course, details in COURSES.items():
        if course.lower() == name:
            return details

    return None, None


def eligible(state, metro):
    if state in ALL_STATES:
        return True

    return state in METRO_STATES and metro is True


def fetch(url):
    response = SESSION.get(
        url,
        timeout=TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()

    if "html" not in response.headers.get(
        "Content-Type", ""
    ).lower():
        raise ValueError(
            f"Expected HTML from {url}"
        )

    return response.text, response.url


def safe_name(value):
    value = re.sub(
        r"[^a-zA-Z0-9_-]+", "_", value
    )
    return value.strip("_")[:100] or "page"


def save_html(folder, name, html):
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / (safe_name(name) + ".html")
    path.write_text(html, encoding="utf-8")
    return str(path)


def discover_meetings(html, base_url):
    """
    Discover meeting links using anchor structure.

    Only return named racecourses with links.
    A missing course is not proof it is absent.
    """
    soup = BeautifulSoup(html, "html.parser")
    meetings = {}
    unknown_links = []

    for anchor in soup.find_all("a", href=True):
        name = normalise(
            anchor.get_text(" ", strip=True)
        )
        href = urljoin(base_url, anchor["href"])

        state, metro = classify_course(name)

        if state is None:
            continue

        if not eligible(state, metro):
            continue

        if urlparse(href).netloc not in {
            "ladbrokesform.com.au",
            "www.ladbrokesform.com.au",
        }:
            unknown_links.append(href)
            continue

        key = (state, name)

        meetings[key] = {
            "state": state,
            "meeting": name,
            "metro": metro,
            "meeting_url": href,
        }

    return list(meetings.values()), unknown_links


def discover_race_links(html, base_url):
    """
    Extract links whose visible text or URL
    indicates an individual numbered race.

    This is intentionally conservative.
    """
    soup = BeautifulSoup(html, "html.parser")
    races = {}

    for anchor in soup.find_all("a", href=True):
        label = normalise(
            anchor.get_text(" ", strip=True)
        )
        href = urljoin(base_url, anchor["href"])

        patterns = [
            r"\bRace\s*(\d{1,2})\b",
            r"\bR\s*(\d{1,2})\b",
            r"(?:/race/|/races/)(\d{1,2})(?:/|$)",
        ]

        race_number = None

        for pattern in patterns:
            match = re.search(
                pattern,
                label + " " + href,
                re.IGNORECASE,
            )
            if match:
                race_number = int(match.group(1))
                break

        if race_number is None:
            continue

        if not 1 <= race_number <= 15:
            continue

        if urlparse(href).netloc not in {
            "ladbrokesform.com.au",
            "www.ladbrokesform.com.au",
        }:
            continue

        races.setdefault(
            race_number,
            {
                "race": race_number,
                "race_name": label,
                "race_url": href,
            },
        )

    return [
        races[number]
        for number in sorted(races)
    ]


def write_csv(path, rows, fields):
    path.parent.mkdir(
        parents=True, exist_ok=True
    )

    with path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file, fieldnames=fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def collect(race_date, root):
    folder = root / race_date
    source_folder = folder / "sources"

    folder.mkdir(
        parents=True, exist_ok=True
    )

    programme_url = (
        f"{BASE}/{race_date}"
    )

    manifest = {
        "date": race_date,
        "source": programme_url,
        "collected_at": (
            dt.datetime.now(
                dt.timezone.utc
            ).isoformat()
        ),
        "status": "started",
        "meetings": [],
        "errors": [],
        "unclassified": [],
    }

    try:
        html, final_url = fetch(
            programme_url
        )

        save_html(
            source_folder,
            "programme",
            html,
        )

        meetings, unknown = discover_meetings(
            html, final_url
        )

        manifest["unclassified"] = unknown

    except Exception as error:
        manifest["status"] = "source_failed"
        manifest["errors"].append(
            f"Programme: {type(error).__name__}: {error}"
        )
        meetings = []

    race_rows = []

    for meeting in meetings:
        name = meeting["meeting"]

        entry = dict(meeting)
        entry["races"] = []
        entry["status"] = "pending"

        try:
            html, final_url = fetch(
                meeting["meeting_url"]
            )

            entry["source_file"] = save_html(
                source_folder,
                name,
                html,
            )

            races = discover_race_links(
                html, final_url
            )

            entry["races"] = races

            entry["status"] = (
                "race_links_found"
                if races
                else "race_links_not_parsed"
            )

            for race in races:
                race_rows.append({
                    "date": race_date,
                    "state": meeting["state"],
                    "meeting": name,
                    "metro": meeting["metro"],
                    "race": race["race"],
                    "race_name": race["race_name"],
                    "race_url": race["race_url"],
                })

        except Exception as error:
            entry["status"] = "source_failed"
            manifest["errors"].append(
                f"{name}: "
                f"{type(error).__name__}: {error}"
            )

        manifest["meetings"].append(entry)

        # Avoid excessive requests to the source.
        time.sleep(0.5)

    if race_rows:
        manifest["status"] = "race_links_found"
    elif manifest["status"] != "source_failed":
        manifest["status"] = "no_race_links"

    manifest["meeting_count"] = len(
        manifest["meetings"]
    )
    manifest["race_link_count"] = len(
        race_rows
    )

    (folder / "manifest.json").write_text(
        json.dumps(
            manifest,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    write_csv(
        folder / "races.csv",
        race_rows,
        [
            "date", "state", "meeting",
            "metro", "race", "race_name",
            "race_url",
        ],
    )

    print(
        json.dumps(
            {
                "date": race_date,
                "status": manifest["status"],
                "meetings": manifest["meeting_count"],
                "race_links": manifest["race_link_count"],
                "errors": manifest["errors"],
            },
            indent=2,
        )
    )

    # A source failure must be visible in Actions.
    if manifest["status"] != "race_links_found":
        raise SystemExit(
            "Collection incomplete: inspect manifest.json"
        )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--date",
        default=tomorrow_in_sydney(),
    )
    parser.add_argument(
        "--output",
        default="data",
    )

    args = parser.parse_args()

    dt.date.fromisoformat(args.date)

    collect(
        args.date,
        Path(args.output),
    )


if __name__ == "__main__":
    main()
