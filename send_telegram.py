#!/usr/bin/env python3
"""Send the Australian Racing Strategy 4.1 provisional TOP TEN to Telegram.

Requires Python 3.11+; standard library only.
GitHub Actions secrets: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
Consumes reports/YYYY-MM-DD/top_ten_provisional.csv and scoring_manifest.json
created by the updated score_racing.py.
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

MAX_MESSAGE_LENGTH = 3900  # Below Telegram's 4096-character limit.


def load_csv(path):
    with path.open('r', newline='', encoding='utf-8-sig') as handle:
        return list(csv.DictReader(handle))


def show(value, fallback='N/A'):
    result = str(value if value is not None else '').strip()
    return result if result else fallback


def as_number(value, label):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f'Invalid numeric field {label}: {value!r}') from None


def points_band(gap):
    if gap >= 7:
        return 3, 1.60
    if gap >= 5:
        return 2, 2.00
    if gap >= 3:
        return 1, 3.00
    return 0, None


def build_messages(racing_date, selections, manifest):
    """Return one or more Telegram messages; never truncate a selection."""
    formatted_date = datetime.strptime(racing_date, '%Y-%m-%d').strftime('%A %d %B %Y')
    header = '\n'.join([
        '🏇 AUSTRALIAN RACING',
        'STRATEGY 4.1 — TOP TEN',
        f'📅 {formatted_date}',
        '📈 Ranked by score gap — odds checked separately',
        '',
    ])
    blocks = []
    for position, horse in enumerate(selections[:10], 1):
        leader_score = as_number(horse.get('first_score'), 'first_score')
        second_score = as_number(horse.get('second_score'), 'second_score')
        gap = as_number(horse.get('gap'), 'gap')
        if abs((leader_score - second_score) - gap) > 0.03:
            raise ValueError(f'Score gap inconsistent for {show(horse.get("first_horse"))}')
        points, minimum = points_band(gap)
        band = (f'{points} point(s) | Minimum WIN odds: {minimum:.2f}'
                if points else 'NO BET — gap below 3.00')
        blocks.append('\n'.join([
            f'🏆 {position}. {show(horse.get("first_horse"))}',
            f'📍 {show(horse.get("meeting"))} — Race {show(horse.get("race"))} ({show(horse.get("state"))})',
            f'⭐ Score: {leader_score:.2f}/100',
            f'🥈 Second: {show(horse.get("second_horse"))} ({second_score:.2f}/100)',
            f'📈 Gap: +{gap:.2f}',
            f'🎯 {band}',
            '',
        ]))
    if not blocks:
        blocks.append('No complete two-runner race comparisons available today.\n')

    footer = '\n'.join([
        '',
        '📊 STRATEGY 4.1 WEIGHTS',
        'Form 30 | Class 25 | Distance 13⅓',
        'Going 13⅓ | Barrier/weight 13⅓ | Fitness 5',
        '',
        f'Coverage: {show(manifest.get("runners_scored"), "0")} runners; '
        f'{show(manifest.get("races_with_runners"), "0")} imported races.',
        '⚠️ PROVISIONAL: National coverage, scratchings and track updates unverified.',
        'Odds are NOT checked; points bands are conditional, not placed bets.',
        'Win and place results are tracked separately after bets are confirmed.',
    ])

    messages = []
    current = header
    for block in blocks:
        if len(current) + len(block) + 2 > MAX_MESSAGE_LENGTH:
            messages.append(current.rstrip())
            current = '🏇 STRATEGY 4.1 — TOP TEN (continued)\n\n'
        if len(current) + len(block) > MAX_MESSAGE_LENGTH:
            raise ValueError('A selection block exceeds Telegram message length')
        current += block + '\n'
    if len(current) + len(footer) > MAX_MESSAGE_LENGTH:
        messages.append(current.rstrip())
        current = '🏇 STRATEGY 4.1 — REPORT NOTES\n'
    messages.append((current + footer).strip())
    return messages


def send_telegram(token, chat_id, message):
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    payload = urllib.parse.urlencode({
        'chat_id': chat_id,
        'text': message,
        'disable_web_page_preview': 'true',
    }).encode('utf-8')
    request = urllib.request.Request(
        url, data=payload,
        headers={'Content-Type': 'application/x-www-form-urlencoded'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as error:
        raise RuntimeError(f'Telegram returned HTTP {error.code}; check bot token and chat ID.') from None
    except urllib.error.URLError:
        raise RuntimeError('Unable to connect to Telegram.') from None
    if not result.get('ok'):
        raise RuntimeError('Telegram did not accept the message.')
    return result


def main():
    parser = argparse.ArgumentParser(description='Send Strategy 4.1 top ten to Telegram')
    parser.add_argument('--date', required=True, help='Racing date YYYY-MM-DD')
    parser.add_argument('--reports', default='reports', help='Reports directory')
    parser.add_argument('--dry-run', action='store_true', help='Print messages without sending')
    args = parser.parse_args()
    try:
        datetime.strptime(args.date, '%Y-%m-%d')
    except ValueError:
        parser.error('--date must be YYYY-MM-DD')

    folder = Path(args.reports) / args.date
    selections_file = folder / 'top_ten_provisional.csv'
    manifest_file = folder / 'scoring_manifest.json'
    if not selections_file.is_file():
        parser.error(f'Missing report: {selections_file}. Run updated score_racing.py first.')
    if not manifest_file.is_file():
        parser.error(f'Missing manifest: {manifest_file}')

    selections = load_csv(selections_file)
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    if manifest.get('date') != args.date:
        parser.error('Manifest date does not match requested date')
    if '4.1' not in str(manifest.get('model', '')):
        parser.error('Refusing to send: scoring manifest is not Strategy 4.1')
    if len(selections) > 10:
        parser.error('Expected at most ten selections in top_ten_provisional.csv')

    messages = build_messages(args.date, selections, manifest)
    if args.dry_run:
        for i, message in enumerate(messages, 1):
            print(f'--- DRY RUN MESSAGE {i}/{len(messages)} ---\n{message}\n')
        return

    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token:
        parser.error('Missing TELEGRAM_BOT_TOKEN GitHub secret')
    if not chat_id:
        parser.error('Missing TELEGRAM_CHAT_ID GitHub secret')

    for index, message in enumerate(messages, 1):
        response = send_telegram(token, chat_id, message)
        message_id = response.get('result', {}).get('message_id', 'unknown')
        print(f'Delivered Telegram message {index}/{len(messages)} (ID {message_id})')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
