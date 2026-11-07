#!/usr/bin/env python3
"""Send provisional Strategy 4.1 Top Ten, or an explicit operational status, to Telegram."""
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

MAX_MESSAGE_LENGTH = 3900


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
        if not points:
            raise ValueError('Top Ten selections contain a gap below the minimum qualifying 3.00')
        blocks.append('\n'.join([
            f'🏆 {position}. {show(horse.get("first_horse"))}',
            f'📍 {show(horse.get("meeting"))} — Race {show(horse.get("race"))} ({show(horse.get("state"))})',
            f'⭐ Score: {leader_score:.2f}/100',
            f'🥈 Second: {show(horse.get("second_horse"))} ({second_score:.2f}/100)',
            f'📈 Gap: +{gap:.2f}',
            f'🎯 {points} point(s) | Minimum WIN odds: {minimum:.2f}',
            '',
        ]))
    if not blocks:
        blocks.append('No qualifying Strategy 4.1 selections for this racing date.\n')

    footer = '\n'.join([
        '',
        '📊 STRATEGY 4.1 WEIGHTS',
        'Form 30 | Class 25 | Distance 13⅓',
        'Going 13⅓ | Barrier/weight 13⅓ | Fitness 5',
        '',
        f'Coverage: {show(manifest.get("runners_scored"), "0")} runners; '
        f'{show(manifest.get("races_with_runners"), "0")} imported races.',
        '⚠️ PROVISIONAL: Scratchings, track updates and odds unverified.',
        'Points bands are conditional, not placed bets.',
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
    request = urllib.request.Request(url, data=payload,
        headers={'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
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
    parser = argparse.ArgumentParser(description='Send Strategy 4.1 Telegram report')
    parser.add_argument('--date', required=True)
    parser.add_argument('--reports', default='reports')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--status', choices=['no-eligible-races', 'failed'],
                        help='Send a status message instead of a selections report')
    args = parser.parse_args()
    try:
        formatted_date = datetime.strptime(args.date, '%Y-%m-%d').strftime('%A %d %B %Y')
    except ValueError:
        parser.error('--date must be YYYY-MM-DD')

    if args.status:
        explanation = ('No eligible Australian thoroughbred races were available under Strategy 4.1 coverage rules.'
                       if args.status == 'no-eligible-races'
                       else 'The racing collection or scoring workflow failed. No selections are being issued. Check GitHub Actions.')
        messages = [f'🏇 AUSTRALIAN RACING — STRATEGY 4.1\n📅 {formatted_date}\n\n'
                    f'{"ℹ️ NO ELIGIBLE RACES" if args.status == "no-eligible-races" else "🚨 REPORT FAILURE"}\n'
                    f'{explanation}']
    else:
        folder = Path(args.reports) / args.date
        selections_file = folder / 'top_ten_provisional.csv'
        manifest_file = folder / 'scoring_manifest.json'
        if not selections_file.is_file():
            parser.error(f'Missing report: {selections_file}. Run score_racing.py first.')
        if not manifest_file.is_file():
            parser.error(f'Missing manifest: {manifest_file}')
        selections = load_csv(selections_file)
        manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
        if manifest.get('date') != args.date:
            parser.error('Manifest date does not match requested date')
        if '4.1' not in str(manifest.get('model', '')):
            parser.error('Refusing to send: scoring manifest is not Strategy 4.1')
        if len(selections) > 10:
            parser.error('Expected at most ten selections')
        messages = build_messages(args.date, selections, manifest)

    if args.dry_run:
        for i, message in enumerate(messages, 1):
            print(f'--- DRY RUN MESSAGE {i}/{len(messages)} ---\n{message}\n')
        return
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    if not token or not chat_id:
        parser.error('Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID GitHub secret')
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
