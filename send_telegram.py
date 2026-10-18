
#!/usr/bin/env python3
"""
Australian Racing Strategy 4.0
Code 8 - Automatic Telegram Delivery

Reads the provisional top-three report created by
score_racing.py and sends it to an existing Telegram bot.

GitHub repository secrets required:
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID

No additional Python packages required.
"""

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


def load_csv(path):
    with path.open(
        "r",
        newline="",
        encoding="utf-8-sig",
    ) as file:
        return list(csv.DictReader(file))


def show(value, fallback="N/A"):
    value = str(value or "").strip()
    return value if value else fallback


def build_message(racing_date, selections, manifest):
    try:
        formatted_date = datetime.strptime(
            racing_date, "%Y-%m-%d"
        ).strftime("%A %d %B %Y")
    except ValueError:
        formatted_date = racing_date

    lines = [
        "🏇 AUSTRALIAN RACING",
        "STRATEGY 4.0 - TOP THREE",
        "",
        f"📅 {formatted_date}",
        "",
    ]

    if not selections:
        lines.extend([
            "No eligible provisional selections today.",
            "",
        ])

    for position, horse in enumerate(selections[:3], 1):
        meeting = show(horse.get("meeting"))
        race = show(horse.get("race"))
        leader = show(horse.get("first_horse"))
        score = show(horse.get("first_score"))
        second = show(horse.get("second_horse"))
        second_score = show(horse.get("second_score"))
        gap = show(horse.get("gap"))

        lines.extend([
            f"🏆 SELECTION {position}",
            f"📍 {meeting} - Race {race}",
            f"🐎 {leader}",
            f"⭐ Strategy score: {score}/100",
            f"🥈 Second: {second}",
            f"Second score: {second_score}/100",
            f"📈 Advantage: +{gap} points",
            "",
        ])

    lines.extend([
        "📊 STRATEGY 4.0 SCORING",
        "Recent form: 30",
        "Class: 25",
        "Distance: 15",
        "Going: 15",
        "Barrier/weight: 10",
        "Fitness: 5",
        "",
        "⚠️ PROVISIONAL REPORT",
        "Scratchings have not been verified.",
        "Scores are not validated win probabilities.",
        "Check final runners and odds before betting.",
    ])

    return "\n".join(lines)


def send_telegram(token, chat_id, message):
    url = (
        "https://api.telegram.org/"
        f"bot{token}/sendMessage"
    )

    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type":
                "application/x-www-form-urlencoded"
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.HTTPError as error:
        # Avoid printing URLs containing bot credentials.
        raise RuntimeError(
            f"Telegram returned HTTP {error.code}. "
            "Check the bot token and chat ID."
        ) from None

    except urllib.error.URLError:
        raise RuntimeError(
            "Unable to connect to Telegram."
        ) from None

    if not result.get("ok"):
        raise RuntimeError(
            "Telegram did not accept the message."
        )

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Send Australian Racing Strategy 4.0 to Telegram"
    )

    parser.add_argument(
        "--date",
        required=True,
        help="Racing date in YYYY-MM-DD format",
    )

    parser.add_argument(
        "--reports",
        default="reports",
        help="Reports directory",
    )

    args = parser.parse_args()

    token = os.environ.get(
        "TELEGRAM_BOT_TOKEN", ""
    ).strip()

    chat_id = os.environ.get(
        "TELEGRAM_CHAT_ID", ""
    ).strip()

    if not token:
        parser.error(
            "Missing TELEGRAM_BOT_TOKEN GitHub secret"
        )

    if not chat_id:
        parser.error(
            "Missing TELEGRAM_CHAT_ID GitHub secret"
        )

    report_folder = Path(args.reports) / args.date

    selections_file = (
        report_folder / "top_three_provisional.csv"
    )

    manifest_file = (
        report_folder / "scoring_manifest.json"
    )

    if not selections_file.exists():
        parser.error(
            f"Missing report: {selections_file}"
        )

    if not manifest_file.exists():
        parser.error(
            f"Missing manifest: {manifest_file}"
        )

    selections = load_csv(selections_file)

    manifest = json.loads(
        manifest_file.read_text(encoding="utf-8")
    )

    if manifest.get("date") != args.date:
        parser.error(
            "Report date does not match requested date"
        )

    message = build_message(
        args.date,
        selections,
        manifest,
    )

    print(
        f"Sending racing report for {args.date}..."
    )

    response = send_telegram(
        token,
        chat_id,
        message,
    )

    message_id = response.get(
        "result", {}
    ).get("message_id", "unknown")

    print(
        f"Telegram message delivered successfully. "
        f"Message ID: {message_id}"
    )


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(
            f"ERROR: {error}",
            file=sys.stderr,
        )
        sys.exit(1)
