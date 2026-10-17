
#!/usr/bin/env python3
"""
Australian Racing Strategy 4.0
Programme collector — corrected for the
Ladbrokes Form Guide HTML structure.

Discovers eligible Australian thoroughbred
meetings and numbered race links.

Does not yet collect runners or score horses.
"""

import argparse
import csv
import datetime as dt
import json
import re
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://ladbrokesform.com.au"

ALL_MEETINGS_STATES = {"VIC", "NSW", "SA"}
METRO_ONLY_STATES = {"QLD", "WA", "TAS", "ACT"}

METRO_COURSES = {
    "QLD": {
        "Eagle Farm", "Doomben",
    },
    "WA": {
        "Ascot", "Belmont", "Belmont Park",
    },
    "TAS": {
        "Hobart", "Launceston",
    },
    "ACT": {
        "Canberra",
    },
}

FIELDS = [
    "date", "state", "meeting", "metro",
    "race", "race_name", "race_url",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(compatible; RacingStrategy4/1.0)"
    ),
    "Accept": "text/html,application/xhtml+xml",
}


def tomorrow_sydney():
    now = dt.datetime.now(
        ZoneInfo("Australia/Sydney")
    )
    return (
        now.date() + dt.timedelta(days=1)
    ).isoformat()


def eligible(state, meeting):
    if state in ALL_MEETINGS_STATES:
        return True, False

    if state in METRO_ONLY_STATES:
        metro = meeting.casefold() in {
            name.casefold()
            for name in METRO_COURSES.get(
                state, set()
            )
        }
        return metro, metro

    return False, False


def fetch_programme(date):
    url = f"{BASE_URL}/{date}"

    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    return response.text, response.url


def find_thoroughbred_section(soup):
    for section in soup.find_all("section"):
        heading = section.find("h3")

        if heading and heading.get_text(
            " ", strip=True
        ).casefold() == "horse racing":
            return section

    return None


def parse_programme(html, source_url, date):
    soup = BeautifulSoup(
        html, "html.parser"
    )

    section = find_thoroughbred_section(soup)

    if section is None:
        raise ValueError(
            "Australian thoroughbred section "
            "not found in source HTML"
        )

    table = section.find("table")

    if table is None:
        raise ValueError(
            "Race programme table not found"
        )

    meetings = []
    races = []
    excluded = []
    unknown = []

    for tr in table.select("tbody tr"):
        cells = tr.find_all(
            "td", recursive=False
        )

        if not cells:
            continue

        venue_text = cells[0].get_text(
            " ", strip=True
        )

        match = re.match(
            r"^(.*?)\s*\(\s*"
            r"(VIC|NSW|SA|QLD|WA|TAS|ACT|NZ)"
            r"\s*\)$",
            venue_text,
            flags=re.IGNORECASE,
        )

        if not match:
            unknown.append(venue_text)
            continue

        meeting = match.group(1).strip()
        state = match.group(2).upper()

        include, metro = eligible(
            state, meeting
        )

        if not include:
            excluded.append({
                "meeting": meeting,
                "state": state,
            })
            continue

        meeting_races = []

        # The table columns themselves identify
        # Race 1, Race 2, Race 3, etc.
        for race_number, cell in enumerate(
            cells[1:], start=1
        ):
            link = cell.find(
                "a", href=True
            )

            if link is None:
                continue

            href = link["href"]

            if not href.startswith("/form/"):
                continue

            row = {
                "date": date,
                "state": state,
                "meeting": meeting,
                "metro": metro,
                "race": race_number,
                "race_name": "",
                "race_url": urljoin(
                    source_url, href
                ),
            }

            races.append(row)
            meeting_races.append(
                race_number
            )

        meetings.append({
            "meeting": meeting,
            "state": state,
            "metro": metro,
            "race_count": len(meeting_races),
            "race_numbers": meeting_races,
        })

    return {
        "date": date,
        "source": source_url,
        "meetings": meetings,
        "races": races,
        "excluded": excluded,
        "unknown": unknown,
    }


def save_results(result, html, output):
    folder = Path(output) / result["date"]
    source_folder = folder / "sources"

    source_folder.mkdir(
        parents=True, exist_ok=True
    )

    (
        source_folder / "programme.html"
    ).write_text(
        html, encoding="utf-8"
    )

    with (
        folder / "races.csv"
    ).open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=FIELDS,
        )
        writer.writeheader()
        writer.writerows(
            result["races"]
        )

    manifest = {
        "date": result["date"],
        "source": result["source"],
        "collected_at": (
            dt.datetime.now(
                dt.timezone.utc
            ).isoformat()
        ),
        "status": (
            "race_links_found"
            if result["races"]
            else "no_race_links"
        ),
        "meeting_count": len(
            result["meetings"]
        ),
        "race_link_count": len(
            result["races"]
        ),
        "meetings": result["meetings"],
        "excluded": result["excluded"],
        "unknown": result["unknown"],
        "runner_collection": "not_implemented",
        "scoring": "not_implemented",
    }

    (
        folder / "manifest.json"
    ).write_text(
        json.dumps(
            manifest,
            indent=2,
        ),
        encoding="utf-8",
    )

    return manifest


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--date",
        default=tomorrow_sydney(),
    )

    parser.add_argument(
        "--output",
        default="data",
    )

    args = parser.parse_args()

    dt.date.fromisoformat(args.date)

    html, source_url = fetch_programme(
        args.date
    )

    result = parse_programme(
        html,
        source_url,
        args.date,
    )

    manifest = save_results(
        result,
        html,
        args.output,
    )

    print(
        json.dumps(
            manifest,
            indent=2,
        )
    )

    if not result["races"]:
        raise SystemExit(
            "No eligible race links found"
        )


if __name__ == "__main__":
    main()
