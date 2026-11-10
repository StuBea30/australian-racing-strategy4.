"""Football Strategy 3.0 — historical walk-forward validation.

Place alongside the existing football probability Python module (default:
football_model.py). This script never generates betting selections.
Requires: requests numpy scipy and the FOOTBALL_DATA_API_KEY secret.

Example: python football_backtest_v3.py --model-module football_model --seasons 2024 2025 2026
"""
import argparse
import csv
import importlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np
import requests

API = 'https://api.football-data.org/v4'
LEAGUES = {'BL1': 'Bundesliga', 'DED': 'Eredivisie', 'ELC': 'Championship', 'SA': 'Serie A'}


def fetch_season(session, code, season, token):
    response = session.get(f'{API}/competitions/{code}/matches',
                           params={'season': season},
                           headers={'X-Auth-Token': token}, timeout=40)
    if response.status_code == 429:
        raise RuntimeError('Rate limited by football-data.org; retry later')
    if response.status_code in (401, 403):
        raise RuntimeError(f'HTTP {response.status_code}: season {season} may be unavailable on this plan')
    response.raise_for_status()
    return response.json()['matches']


def logloss(p, actual):
    return -math.log(max(1e-12, min(1.0, p[actual])))


def evaluate(model_module, completed, origin, candidates, max_tests):
    """Train strictly before origin, evaluate subsequent completed games."""
    train = [m for m in completed if m['date'] < origin]
    if len(train) < model_module.MIN_MATCHES:
        return []
    try:
        model = model_module.fit_model(train, origin)
    except (ValueError, RuntimeError, OverflowError, FloatingPointError):
        return []
    rows = []
    for m in candidates[:max_tests]:
        if m['home'] not in model['index'] or m['away'] not in model['index']:
            continue
        try:
            pred = model_module.probabilities(model, m['home'], m['away'])
        except (ValueError, OverflowError, FloatingPointError):
            continue
        outcome = 'H' if m['hg'] > m['ag'] else 'A' if m['hg'] < m['ag'] else 'D'
        p = {'H': pred['home_win'], 'D': pred['draw'], 'A': pred['away_win']}
        observed = {'H': int(outcome == 'H'), 'D': int(outcome == 'D'), 'A': int(outcome == 'A')}
        brier = sum((p[k]-observed[k])**2 for k in p)
        total = m['hg'] + m['ag']
        markets = pred['markets']
        rows.append({
            'kickoff_utc': m['date'].isoformat(),
            'home': m['home_name'], 'away': m['away_name'],
            'home_goals': m['hg'], 'away_goals': m['ag'],
            'p_home': p['H'], 'p_draw': p['D'], 'p_away': p['A'],
            'log_loss_1x2': logloss(p, outcome), 'brier_1x2': brier,
            'expected_goals': pred['expected_goals_home'] + pred['expected_goals_away'],
            'actual_goals': total,
            'p_over_2_5': markets['over_2_5'], 'over_2_5_actual': int(total >= 3),
            'p_over_3_5': markets['over_3_5'], 'over_3_5_actual': int(total >= 4),
            'p_btts': markets['btts_yes'], 'btts_actual': int(m['hg'] > 0 and m['ag'] > 0),
            'rho': model['rho'],
        })
    return rows


def summarise(rows):
    if not rows:
        return {'n': 0}
    n = len(rows)
    out = {'n': n,
           'log_loss_1x2': sum(r['log_loss_1x2'] for r in rows)/n,
           'brier_1x2': sum(r['brier_1x2'] for r in rows)/n,
           'goals_mae': sum(abs(r['expected_goals']-r['actual_goals']) for r in rows)/n,
           'mean_predicted_goals': sum(r['expected_goals'] for r in rows)/n,
           'mean_actual_goals': sum(r['actual_goals'] for r in rows)/n,
           'rho_at_boundary_rate': sum(abs(r['rho']) >= .049999 for r in rows)/n}
    for name, actual in [('over_2_5', 'over_2_5_actual'),
                         ('over_3_5', 'over_3_5_actual'), ('btts', 'btts_actual')]:
        key = 'p_' + name
        out[name+'_brier'] = sum((r[key]-r[actual])**2 for r in rows)/n
        out[name+'_predicted_rate'] = sum(r[key] for r in rows)/n
        out[name+'_actual_rate'] = sum(r[actual] for r in rows)/n
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--model-module', default='football_model',
                    help='Python module containing parse_match, fit_model, probabilities')
    ap.add_argument('--seasons', nargs='+', type=int, default=[2024, 2025, 2026],
                    help='Football season start years (2024 = 2024/25)')
    ap.add_argument('--holdout-start', default='2026-08-01',
                    help='First evaluation date (UTC); earlier results train only')
    ap.add_argument('--refit-days', type=int, default=14,
                    help='Refit model every N days; tests within each block are held out')
    ap.add_argument('--min-training', type=int, default=70)
    ap.add_argument('--pause', type=float, default=7.0)
    ap.add_argument('--output', default='football_backtest_results.json')
    ap.add_argument('--csv', default='football_backtest_predictions.csv')
    args = ap.parse_args()
    if args.refit_days < 1 or args.min_training < 1:
        ap.error('refit-days and min-training must be positive')
    token = os.getenv('FOOTBALL_DATA_API_KEY')
    if not token:
        sys.exit('Missing FOOTBALL_DATA_API_KEY')
    model_module = importlib.import_module(args.model_module)
    # Respect model's minimum sample size.
    model_module.MIN_MATCHES = max(args.min_training, model_module.MIN_MATCHES)
    cutoff = datetime.fromisoformat(args.holdout_start).replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    output = {'created_utc': now.isoformat(), 'seasons': args.seasons,
              'holdout_start': cutoff.isoformat(), 'refit_days': args.refit_days,
              'leagues': {}, 'overall': {}, 'notes': [
                  'No future results are used in training at each refit origin.',
                  'This evaluates predictive calibration, not profitability or odds.',
                  'Historical seasons may be restricted by the football-data.org subscription.',
                  'Season-to-season promotions/relegations may cause unseen teams to be skipped.',
                  'Refit-block training excludes matches played within that evaluation block.' ]}
    all_rows = []
    session = requests.Session()
    for code, name in LEAGUES.items():
        raw = []
        failures = []
        for season in args.seasons:
            try:
                fetched = fetch_season(session, code, season, token)
                raw.extend(fetched)
                print(f'{code} {season}: {len(fetched)} records', flush=True)
            except (requests.RequestException, RuntimeError, ValueError) as exc:
                failures.append(f'{season}: {exc}')
                print(f'WARNING {code} {season}: {exc}', file=sys.stderr, flush=True)
            time.sleep(args.pause)
        parsed = [m for raw_match in raw if (m := model_module.parse_match(raw_match)) is not None]
        # Deduplicate matches fetched across overlapping API seasons.
        unique = {(m['date'], m['home'], m['away']): m for m in parsed}
        completed = sorted([m for m in unique.values() if 'hg' in m and m['date'] <= now],
                           key=lambda m: m['date'])
        test = [m for m in completed if m['date'] >= cutoff]
        league_rows = []
        if test:
            origin = test[0]['date']
            while origin <= test[-1]['date']:
                from datetime import timedelta
                end = origin + timedelta(days=args.refit_days)
                candidates = [m for m in test if origin <= m['date'] < end]
                if candidates:
                    league_rows.extend(evaluate(model_module, completed, origin,
                                                candidates, len(candidates)))
                origin = end
        for row in league_rows:
            row['league'] = code
        all_rows.extend(league_rows)
        output['leagues'][code] = {'name': name, 'completed_available': len(completed),
                                  'holdout_matches_available': len(test),
                                  'evaluated': summarise(league_rows),
                                  'fetch_warnings': failures}
        print(f'{name}: {len(league_rows)} out-of-sample predictions', flush=True)
    output['overall'] = summarise(all_rows)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, allow_nan=False)
    if all_rows:
        with open(args.csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=list(all_rows[0]))
            writer.writeheader()
            writer.writerows(all_rows)
    print(json.dumps(output['overall'], indent=2))
    print(f'Wrote {args.output} and {args.csv if all_rows else "no CSV (no predictions)"}')
    if not all_rows:
        sys.exit('No out-of-sample predictions; inspect warnings, historical data access and holdout dates')

if __name__ == '__main__':
    main()
