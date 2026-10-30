
#!/usr/bin/env python3
"""Strategy 4.1 provisional 100-point horse rankings from collected CSVs.

Model heuristics are transparent and NOT back-tested. Scratchings unverified:
no output is a confirmed betting recommendation. Uses only observed CSV data.
"""
import argparse
import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

WEIGHTS = {'form': 30, 'class': 25, 'distance': 40/3, 'going': 40/3, 'barrier_weight': 40/3, 'fitness': 5}
KEY = ('date', 'meeting', 'race', 'horse')


def number(s):
    m = re.search(r'-?\d+(?:\.\d+)?', str(s or ''))
    return float(m.group()) if m else None


def date_value(s):
    for fmt in ('%d/%m/%y', '%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            pass
    return None


def record(s):
    m = re.search(r'(\d+)\s*:\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)', s or '')
    return tuple(map(int, m.groups())) if m else None


def race_class(s):
    s = (s or '').upper().strip()
    if any(x in s for x in ('G1', 'GROUP 1')): return 10
    if any(x in s for x in ('G2', 'GROUP 2')): return 9
    if any(x in s for x in ('G3', 'GROUP 3')): return 8
    if any(x in s for x in ('LISTED', 'LR ')): return 7
    if 'OPEN' in s or re.search(r'\bOPEN\b', s): return 6
    if 'BM' in s:
        v = number(s.split('BM', 1)[1]); return min(6, max(3, (v or 60) / 20))
    if re.search(r'\b(CL|CLASS)\s*[456]', s): return 5
    if re.search(r'\b(CL|CLASS)\s*[23]', s): return 4
    if re.search(r'\b(CL|CLASS)\s*1\b', s): return 3
    if 'MDN' in s or 'MAIDEN' in s: return 2
    return None


def past_finish(s):
    m = re.search(r'(\d+)(?:st|nd|rd|th)?\s+of\s+(\d+)', s or '', re.I)
    if not m: return None
    p, field = map(int, m.groups())
    return (p, field) if p >= 1 and field >= p else None


def performance(row):
    f = past_finish(row.get('Place'))
    if not f: return None
    p, n = f
    position = 1.0 - (p - 1) / max(1, n - 1)
    margin = number(row.get('Margin'))
    if margin is not None:
        position = 0.75 * position + 0.25 * max(0, 1 - margin / 12)
    return max(0, min(1, position))


def going_type(s):
    s = (s or '').lower()
    for term in ('synthetic', 'heavy', 'soft', 'good', 'firm'):
        if term in s: return term
    return None


def historical_rows(rows, race_date):
    valid = []
    for row in rows:
        d = date_value(row.get('Date'))
        if d and d < race_date:
            valid.append((d, row))
    return [r for _, r in sorted(valid, key=lambda x: x[0], reverse=True)]


def score_runner(horse, history):
    notes = []
    rdate = date_value(horse['date'])
    past = historical_rows(history, rdate)
    distance = number(horse.get('distance_m'))
    surface = going_type(horse.get('track'))
    current_class = race_class(horse.get('race_class'))

    # Recent form: up to six completed starts, newest weighted most heavily.
    form_samples = [(performance(r), 0.83 ** i) for i, r in enumerate(past[:6])]
    form_samples = [(v, w) for v, w in form_samples if v is not None]
    form = 30 * sum(v * w for v, w in form_samples) / sum(w for _, w in form_samples) if form_samples else None
    if form is None: notes.append('no recorded finishing positions')

    # Class: compares historical race level with today's, combined with finishing quality.
    class_samples = []
    for i, r in enumerate(past[:6]):
        c, perf = race_class(r.get('Class')), performance(r)
        if c is None or perf is None or current_class is None: continue
        advantage = max(-3, min(3, c - current_class))
        class_samples.append((max(0, min(1, 0.45 + 0.11 * advantage + 0.25 * (perf - 0.5))), 0.83 ** i))
    class_score = 25 * sum(v * w for v, w in class_samples) / sum(w for _, w in class_samples) if class_samples else None
    if class_score is None: notes.append('class comparison unavailable')

    # Distance: starts within 15% of target, plus published distance record if available.
    dist_samples = []
    if distance and distance > 0:
        for i, r in enumerate(past[:8]):
            d, perf = number(r.get('Distance')), performance(r)
            if d is None or perf is None: continue
            similarity = max(0, 1 - abs(d - distance) / max(200, distance * 0.3))
            dist_samples.append(((0.55 * similarity + 0.45 * perf) * similarity, 0.88 ** i))
    dist_history = sum(v*w for v,w in dist_samples)/sum(w for _,w in dist_samples) if dist_samples else None
    dr = record(horse.get('distance_record'))
    dist_record = (0.25 + 0.75 * (dr[1] + 0.45 * dr[2] + 0.25 * dr[3]) / dr[0]) if dr and dr[0] else None
    distance_parts = [(dist_history, 0.7), (dist_record, 0.3)]
    distance_parts = [(v,w) for v,w in distance_parts if v is not None]
    distance_score = WEIGHTS['distance'] * sum(v*w for v,w in distance_parts)/sum(w for _,w in distance_parts) if distance_parts else None
    if distance_score is None: notes.append('distance evidence unavailable')

    # Going: same surface/condition historical performances and published records.
    going_samples = []
    if surface:
        for i, r in enumerate(past[:8]):
            if going_type(r.get('Cond.')) == surface and performance(r) is not None:
                going_samples.append((performance(r), 0.88 ** i))
    going_hist = sum(v*w for v,w in going_samples)/sum(w for _,w in going_samples) if going_samples else None
    rec = record(horse.get(surface + '_record'))
    going_rec = (0.25 + 0.75 * (rec[1] + 0.45 * rec[2] + 0.25 * rec[3]) / rec[0]) if rec and rec[0] else None
    parts = [(going_hist, 0.7), (going_rec, 0.3)]
    parts = [(v,w) for v,w in parts if v is not None]
    going_score = WEIGHTS['going'] * sum(v*w for v,w in parts)/sum(w for _,w in parts) if parts else None
    if going_score is None: notes.append('going evidence unavailable')

    # Barrier/weight: comparative score assigned at race level below.
    # Fitness: date of most recent recorded start, not unreliable blank collector field.
    days = (rdate - date_value(past[0]['Date'])).days if past else None
    if days is None: fitness = None
    elif 7 <= days <= 28: fitness = 5.0
    elif 4 <= days <= 42: fitness = 4.0
    elif 43 <= days <= 70: fitness = 3.0
    elif 71 <= days <= 120: fitness = 2.0
    else: fitness = 1.0
    if fitness is None: notes.append('fitness evidence unavailable')

    return {'form': form, 'class': class_score, 'distance': distance_score,
            'going': going_score, 'fitness': fitness, 'days_since_last': days,
            'evidence_starts': len(past), 'notes': notes}


def write_csv(path, rows, columns):
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        w.writeheader(); w.writerows(rows)


def staking_rule(gap):
    if gap >= 7: return 3, 1.60
    if gap >= 5: return 2, 2.00
    if gap >= 3: return 1, 3.00
    return 0, None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--date', required=True, help='YYYY-MM-DD')
    ap.add_argument('--input', default='data', help='Folder containing YYYY-MM-DD CSVs')
    ap.add_argument('--output', default='reports', help='Report root folder')
    args = ap.parse_args()
    date_value_required = date_value(args.date)
    if not date_value_required or date_value_required.isoformat() != args.date:
        ap.error('--date must be YYYY-MM-DD')
    folder = Path(args.input) / args.date
    for name in ('runners.csv', 'past_starts.csv'):
        if not (folder/name).is_file():
            ap.error(f'Missing {folder/name}')
    with (folder/'runners.csv').open(encoding='utf-8-sig', newline='') as f:
        runners = list(csv.DictReader(f))
    with (folder/'past_starts.csv').open(encoding='utf-8-sig', newline='') as f:
        histories = list(csv.DictReader(f))
    if not runners:
        ap.error('No runners: refusing to produce empty rankings')
    histories_by_key = defaultdict(list)
    for h in histories:
        histories_by_key[tuple(h.get(k, '') for k in KEY)].append(h)
    groups = defaultdict(list)
    for r in runners:
        if r.get('date') != args.date: continue
        groups[(r['date'], r['state'], r['meeting'], r['race'])].append(r)
    if not groups: ap.error('No runners for requested date')
    ranked = []
    races = []
    for group_key, group in sorted(groups.items(), key=lambda item: (item[0][1], item[0][2], int(number(item[0][3]) or 0))):
        weights = [number(r.get('weight_kg')) for r in group]
        weights = [v for v in weights if v is not None]
        barriers = [number(r.get('barrier')) for r in group]
        barriers = [v for v in barriers if v is not None and v > 0]
        max_barrier = max(barriers) if barriers else None
        low_w, high_w = (min(weights), max(weights)) if weights else (None, None)
        scored = []
        for r in group:
            key = tuple(r.get(k, '') for k in KEY)
            s = score_runner(r, histories_by_key[key])
            b, w = number(r.get('barrier')), number(r.get('weight_kg'))
            bscore = (1 - (b-1)/max(1, max_barrier-1)) if b is not None and b > 0 and max_barrier else None
            wscore = (high_w-w)/max(0.1, high_w-low_w) if w is not None and low_w is not None else None
            components = [(bscore, 0.6), (wscore, 0.4)]
            components = [(v, weight) for v, weight in components if v is not None]
            s['barrier_weight'] = WEIGHTS['barrier_weight']*sum(v*weight for v,weight in components)/sum(weight for _,weight in components) if components else None
            if s['barrier_weight'] is None: s['notes'].append('barrier/weight evidence unavailable')
            available = [k for k in WEIGHTS if s[k] is not None]
            observed = sum(s[k] for k in available)
            coverage = sum(WEIGHTS[k] for k in available)
            # Missing components receive no points; never impute an artificial neutral score.
            status = 'PROVISIONAL - SCRATCHINGS UNVERIFIED'
            if coverage < 75 or len(histories_by_key[key]) == 0:
                status = 'INSUFFICIENT DATA - DO NOT SELECT'
            if (r.get('scratching_status') or '').strip().lower() in ('scratched', 'withdrawn'):
                status = 'SCRATCHED - EXCLUDED'
            result = {
                'date': r['date'], 'state': r['state'], 'meeting': r['meeting'],
                'race': r['race'], 'race_name': r.get('race_name',''), 'horse_number': r.get('horse_number',''),
                'horse': r['horse'], 'barrier': r.get('barrier',''), 'weight_kg': r.get('weight_kg',''),
                'race_url': r.get('race_url',''), 'scratching_status': r.get('scratching_status','unverified'),
                'score': round(observed, 2), 'coverage_points': coverage,
                'form_points': round(s['form'], 2) if s['form'] is not None else '',
                'class_points': round(s['class'], 2) if s['class'] is not None else '',
                'distance_points': round(s['distance'], 2) if s['distance'] is not None else '',
                'going_points': round(s['going'], 2) if s['going'] is not None else '',
                'barrier_weight_points': round(s['barrier_weight'], 2) if s['barrier_weight'] is not None else '',
                'fitness_points': round(s['fitness'], 2) if s['fitness'] is not None else '',
                'days_since_last': s['days_since_last'] if s['days_since_last'] is not None else '',
                'evidence_starts': s['evidence_starts'], 'status': status,
                'notes': '; '.join(s['notes']), 'rank': '', 'gap_to_second': ''
            }
            scored.append(result)
        scored.sort(key=lambda r: (-r['score'], -r['coverage_points'], r['horse']))
        for i, r in enumerate(scored, 1): r['rank'] = i
        ranked.extend(scored)
        eligible = [r for r in scored if r['status'] == 'PROVISIONAL - SCRATCHINGS UNVERIFIED' and abs(r['coverage_points'] - 100) < 0.00001]
        # Do not compare a partial score with a complete score.
        if len(eligible) != len([r for r in scored if r['status'] != 'SCRATCHED - EXCLUDED']):
            continue
        if len(eligible) >= 2:
            first, second = eligible[:2]
            gap = round(first['score']-second['score'], 2)
            first['gap_to_second'] = gap
            points, minimum_odds = staking_rule(gap)
            races.append({'points': points, 'minimum_win_odds': minimum_odds, 'date': first['date'], 'state': first['state'], 'meeting': first['meeting'],
                          'race': first['race'], 'race_name': first['race_name'],
                          'first_horse': first['horse'], 'first_score': first['score'],
                          'second_horse': second['horse'], 'second_score': second['score'],
                          'gap': gap, 'race_url': first['race_url'],
                          'status': 'PROVISIONAL - SCRATCHINGS UNVERIFIED'})
    races.sort(key=lambda r: (-r['gap'], -r['first_score'], r['meeting'], int(number(r['race']) or 0)))
    out = Path(args.output) / args.date
    out.mkdir(parents=True, exist_ok=True)
    cols = list(ranked[0])
    write_csv(out/'all_runner_scores.csv', ranked, cols)
    race_cols = ['points','minimum_win_odds','date','state','meeting','race','race_name','first_horse','first_score','second_horse','second_score','gap','race_url','status']
    write_csv(out/'race_rankings.csv', races, race_cols)
    write_csv(out/'top_ten_provisional.csv', races[:10], race_cols)
    # Compatibility output for an existing workflow expecting this filename.
    write_csv(out/'top_three_provisional.csv', races[:3], race_cols)
    manifest = {'date': args.date, 'races_with_runners': len(groups), 'runners_scored': len(ranked),
                'races_with_two_eligible_runners': len(races), 'provisional_top_ten': len(races[:10]),
                'model': 'Strategy 4.1 heuristic v1 (not back-tested)', 'weights': WEIGHTS,
                'scratchings_verified': False, 'betting_recommendations': False}
    (out/'scoring_manifest.json').write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    lines = [f'# Strategy 4.1 — {args.date}', '', '**PROVISIONAL ONLY. Scratchings unverified; not betting recommendations.**',
             '', f"Scored {len(ranked)} runners across {len(groups)} races. {len(races)} races have two eligible scored runners.",
             '', '| Rank | Meeting | Race | Leader | Score | Second | Score | Gap | Band | Min win odds |',
             '|---:|---|---:|---|---:|---|---:|---:|---|---:|']
    for i, r in enumerate(races[:10], 1):
        lines.append(f"| {i} | {r['meeting']} | {r['race']} | {r['first_horse']} | {r['first_score']:.2f} | {r['second_horse']} | {r['second_score']:.2f} | {r['gap']:.2f} | {r['points'] or 'No bet'} | {r['minimum_win_odds'] or '-'} |")
    if not races: lines.append('No eligible two-runner comparisons; no selections.')
    lines += ['', 'Top ten are ranked by gap without filtering by market odds.',
              'Only races with complete factor scores for all non-scratched runners are ranked.',
              'Scores are deterministic heuristics based on available racecards, not validated probabilities.',
              'Missing evidence receives zero points and is recorded in coverage_points.',
              'Scratchings and late track changes must be verified before any selections.']
    (out/'top_three_provisional.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps(manifest, indent=2))
    print('\n'.join(lines))

if __name__ == '__main__':
    main()
