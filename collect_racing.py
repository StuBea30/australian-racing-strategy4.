
#!/usr/bin/env python3
"""Collect Ladbrokes racecards and historical form for Strategy 4.1.

Rules:
- Exclude maiden races.
- Exclude races containing a first-time competitive starter.
- Trials and jump-outs do not count as competitive starts.
- Do not exclude races solely because of runners' ages.
- Capture advertised race-level total prize money.
- Preserve existing scratching handling.
"""

import argparse
import csv
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from purse_data import extract_history_purse, parse_money_text
from track_states import infer_state


HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; RacingStrategy4/1.0)",
    "Accept": "text/html",
}

FIELDS = [
    "date", "state", "meeting", "race", "race_url",
    "race_name", "distance_m", "race_class", "track",
    "weather", "horse_number", "horse", "barrier",
    "form", "trainer", "jockey", "weight_kg", "rating",
    "career", "distance_record", "good_record",
    "soft_record", "heavy_record", "first_up",
    "second_up", "days_since_start", "settling_position",
    "comments", "scratching_status", "past_starts_count",
    "race_prize_money",
]


def clean(node):
    return node.get_text(" ", strip=True) if node else ""


def labelled(node, label):
    for li in node.select("header li"):
        strong = li.find("strong")
        if strong and clean(strong).rstrip(":").casefold() == label.casefold():
            return clean(li).split(":", 1)[-1].strip()
    return ""


def stats(article):
    result = {}

    heading = next(
        (h for h in article.select("h5")
         if clean(h).casefold() == "stats"),
        None,
    )

    if not heading:
        return result

    grid = heading.find_next_sibling("div")

    if not grid:
        return result

    for h6 in grid.select("h6"):
        value = h6.find_next_sibling("span")
        if value:
            result[clean(h6).casefold()] = clean(value)

    return result


def section_text(article, title):
    heading = next(
        (h for h in article.select("h5")
         if clean(h).casefold() == title.casefold()),
        None,
    )

    if not heading:
        return ""

    sibling = (
        heading.find_next_sibling("div")
        or heading.find_next_sibling("p")
    )
    return clean(sibling)


def is_trial(record):
    text = " ".join(
        str(record.get(key, ""))
        for key in ("Class", "Race Name", "Race Type", "Type")
    )

    return bool(re.search(
        r"\b(?:trial|jump[\s-]?out|practice)\b",
        text,
        re.IGNORECASE,
    ))


def is_maiden_race(race_class, race_name):
    return bool(re.search(
        r"\b(?:maiden|mdn)\b",
        f"{race_class} {race_name}",
        re.IGNORECASE,
    ))


def has_competitive_start(history, career):
    match = re.match(
        r"^\s*(\d+)\s*:\s*\d+\s*-\s*\d+\s*-\s*\d+\s*$",
        str(career or ""),
    )

    if match:
        return int(match.group(1)) > 0

    for record in history:
        if is_trial(record):
            continue
        if record.get("Date") and record.get("Place"):
            return True

    return False


def extract_race_purse(soup, heading, facts):
    """Extract the advertised TOTAL race purse, not horse earnings.

    Ladbrokes displays this in an h3 below the race name:
    <h3>Prize Money: $80,000</h3>

    Search the race header first. Never search runner articles.
    """
    if heading:
        for element in heading.select("h3"):
            text = clean(element)

            match = re.search(
                r"\bPrize\s*Money\s*:\s*"
                r"(A\$|AUD\s*|\$)?\s*"
                r"([\d,]+(?:\.\d+)?\s*[kKmM]?)",
                text,
                re.IGNORECASE,
            )

            if match:
                amount = parse_money_text(
                    (match.group(1) or "") + match.group(2)
                )
                if amount is not None:
                    return str(amount)

    # Fallback: explicitly labelled race facts only.
    for key, value in facts.items():
        if re.search(
            r"^(?:prize\s*money|prizemoney|total\s*prize|purse)$",
            key.strip(),
            re.IGNORECASE,
        ):
            amount = parse_money_text(value)
            if amount is not None:
                return str(amount)

    return ""


def race_facts(soup):
    result = {}

    for li in soup.select("section > ul li"):
        strong = li.find("strong")

        if not strong:
            continue

        key = clean(strong).rstrip(":").casefold()
        value = clean(li).split(":", 1)[-1].strip()

        if key:
            result[key] = value

    return result


def parse_race(html, meta):
    soup = BeautifulSoup(html, "html.parser")

    header = soup.select_one("section header h1")
    if not header:
        raise ValueError("Race header not found")

    articles = soup.select('article[id^="runner-"]')
    if not articles:
        raise ValueError("No runner articles found")

    heading = header.find_parent("header")
    race_name = clean(
        heading.select_one("h2")
    ) if heading else ""

    facts = race_facts(soup)
    current_purse = extract_race_purse(soup, heading, facts)

    rows = []
    histories = []

    for article in articles:
        identifier = article.get("id", "")
        number = identifier.removeprefix("runner-")

        name_line = clean(article.select_one("header li"))

        match = re.match(
            r"(.+?)\s*\(\s*(\d+)\s*\)\s*(.*)$",
            name_line,
        )
        if not match:
            raise ValueError(f"Cannot parse runner: {name_line}")

        horse, barrier, form = match.groups()
        runner_stats = stats(article)

        rating = ""
        for paragraph in article.select("p"):
            if clean(paragraph) == "Rating":
                spans = paragraph.parent.find_all("span")
                rating = clean(spans[-1]) if spans else ""
                break

        days = ""
        for h in article.select("h5"):
            text = clean(h)
            if text.startswith("Last Starts"):
                found = re.search(
                    r"(\d+)\s+days since last start",
                    text,
                )
                if found:
                    days = found.group(1)
                break

        settling = ""
        for paragraph in article.select("p"):
            text = clean(paragraph)
            if "Expected Settling Position:" in text:
                settling = text.split(":", 1)[-1].strip()
                break

        history = []

        for table in article.select("table"):
            labels = [
                clean(cell)
                for cell in table.select(
                    "thead tr:first-child > *"
                )
            ]

            if "Place" not in labels or "Date" not in labels:
                continue

            for tr in table.select("tbody tr"):
                cells = tr.find_all("td", recursive=False)
                if len(cells) != len(labels):
                    continue

                record = dict(zip(
                    labels,
                    (clean(cell) for cell in cells),
                ))

                record.update({
                    "date": meta["date"],
                    "meeting": meta["meeting"],
                    "race": meta["race"],
                    "horse": horse,
                })

                record["Prize Money AUD"] = (
                    extract_history_purse(record) or ""
                )

                historical_state = (
                    record.get("Historical State", "")
                    or record.get("State", "")
                )

                if not historical_state:
                    historical_state = (
                        infer_state(record.get("Track", ""))
                        or ""
                    )

                if (
                    not historical_state
                    and record.get("Track", "").strip().casefold()
                    == meta["meeting"].strip().casefold()
                ):
                    historical_state = meta["state"]

                record["Historical State"] = historical_state
                history.append(record)

        histories.extend(history)

        weight_text = labelled(article, "Weight")
        weight_match = re.search(
            r"\d+(?:\.\d+)?",
            weight_text,
        )

        rows.append({
            "date": meta["date"],
            "state": meta["state"],
            "meeting": meta["meeting"],
            "race": meta["race"],
            "race_url": meta["race_url"],
            "race_name": race_name,
            "distance_m": re.sub(
                r"\D", "", facts.get("distance", "")
            ),
            "race_class": facts.get("class", ""),
            "track": facts.get("track", ""),
            "weather": facts.get("weather", ""),
            "horse_number": number,
            "horse": horse,
            "barrier": barrier,
            "form": form,
            "trainer": labelled(article, "Trainer"),
            "jockey": labelled(article, "Jockey"),
            "weight_kg": (
                weight_match.group(0) if weight_match else ""
            ),
            "rating": rating,
            "career": runner_stats.get("career", ""),
            "distance_record": runner_stats.get("distance", ""),
            "good_record": runner_stats.get("good", ""),
            "soft_record": runner_stats.get("soft", ""),
            "heavy_record": runner_stats.get("heavy", ""),
            "first_up": runner_stats.get("1st up", ""),
            "second_up": runner_stats.get("2nd up", ""),
            "days_since_start": days,
            "settling_position": settling,
            "comments": section_text(article, "Comments"),
            "scratching_status": "unverified",
            "past_starts_count": len(history),
            "race_prize_money": current_purse,
        })

    return rows, histories


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", default="data")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional number of races for testing",
    )
    parser.add_argument("--delay", type=float, default=1.0)
    args = parser.parse_args()

    folder = Path(args.output) / args.date

    with (folder / "races.csv").open(
        newline="", encoding="utf-8"
    ) as file:
        races = list(csv.DictReader(file))

    if args.limit:
        races = races[:args.limit]

    all_runners = []
    all_histories = []
    errors = []
    exclusions = []

    raw = folder / "sources" / "racecards"
    raw.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(HEADERS)

    for index, race in enumerate(races, 1):
        try:
            response = session.get(
                race["race_url"], timeout=30
            )
            response.raise_for_status()

            runners, histories = parse_race(
                response.text, race
            )

            (raw / f"race_{index:03d}.html").write_text(
                response.text, encoding="utf-8"
            )

            race_class = (
                runners[0].get("race_class", "")
                if runners else ""
            )
            race_name = (
                runners[0].get("race_name", "")
                if runners else ""
            )

            exclusion_reason = ""

            if is_maiden_race(race_class, race_name):
                exclusion_reason = "MAIDEN RACE"
            else:
                for runner in runners:
                    runner_history = [
                        item for item in histories
                        if item.get("horse") == runner["horse"]
                    ]

                    if not has_competitive_start(
                        runner_history,
                        runner.get("career", ""),
                    ):
                        exclusion_reason = (
                            "FIRST-TIME STARTER: "
                            + runner["horse"]
                        )
                        break

            if exclusion_reason:
                exclusions.append({
                    "meeting": race["meeting"],
                    "race": race["race"],
                    "reason": exclusion_reason,
                    "runners": len(runners),
                })

                print(
                    f"EXCLUDED {race['meeting']} "
                    f"R{race['race']}: {exclusion_reason}"
                )
            else:
                all_runners.extend(runners)
                all_histories.extend(histories)

                print(
                    f"{race['meeting']} R{race['race']}: "
                    f"{len(runners)} runners, "
                    f"{len(histories)} previous records, "
                    f"purse={runners[0]['race_prize_money']}"
                )

        except (
            requests.RequestException,
            ValueError,
            KeyError,
        ) as error:
            errors.append({
                "race_url": race.get("race_url", ""),
                "error": str(error),
            })
            print(
                f"FAILED {race.get('race_url')}: {error}"
            )

        if index < len(races):
            time.sleep(max(args.delay, 0))

    with (folder / "runners.csv").open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(all_runners)

    history_fields = [
        "date", "meeting", "race", "horse"
    ]

    for history in all_histories:
        for key in history:
            if key not in history_fields:
                history_fields.append(key)

    with (folder / "past_starts.csv").open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(
            file, fieldnames=history_fields
        )
        writer.writeheader()
        writer.writerows(all_histories)

    summary = {
        "date": args.date,
        "races_requested": len(races),
        "races_collected": len(races) - len(errors),
        "races_excluded": len(exclusions),
        "races_eligible": (
            len(races) - len(errors) - len(exclusions)
        ),
        "runners": len(all_runners),
        "past_starts": len(all_histories),
        "runners_with_today_purse": sum(
            bool(r["race_prize_money"])
            for r in all_runners
        ),
        "excluded_races": exclusions,
        "errors": errors,
        "scratchings_verified": False,
        "strategy_scores_generated": False,
    }

    (folder / "runners_manifest.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(summary, indent=2))

    if errors:
        raise SystemExit(1)

    if not all_runners:
        raise SystemExit(
            "No eligible races collected. "
            "Review excluded_races in runners_manifest.json."
        )


if __name__ == "__main__":
    main()
