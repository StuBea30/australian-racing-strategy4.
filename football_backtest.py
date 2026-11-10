
"""Walk-forward backtest for Football Strategy 3.0 v2.

Uses football_model.py from the same directory. No betting or odds data.
Models refit at the beginning of each UTC week, using strictly earlier matches.
"""
import argparse
import csv
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests
from scipy.stats import poisson

import football_model as fm

MARKETS = ('over_2_5', 'over_3_5', 'under_2_5', 'under_3_5', 'btts_yes', 'btts_no')
EPS = 1e-12


def score_probs(p, y):
    p = min(1-EPS, max(EPS, float(p)))
    return -(y*math.log(p) + (1-y)*math.log(1-p)), (p-y)**2


def baseline_probs(training, fixture):
    """Independent Poisson, league-wide home and away scoring rates."""
    lam = max(0.05, sum(m['hg'] for m in training)/len(training))
    mu = max(0.05, sum(m['ag'] for m in training)/len(training))
    limit = 10
    while poisson.cdf(limit, lam)*poisson.cdf(limit, mu) < 0.99999:
        limit += 2
    p = np.outer(poisson.pmf(np.arange(limit+1), lam),
                 poisson.pmf(np.arange(limit+1), mu))
    p /= p.sum()
    h, a = np.indices(p.shape)
    hw, dr, aw = float(p[h>a].sum()), float(p[h==a].sum()), float(p[h<a].sum())
    btts = float(p[(h>0)&(a>0)].sum())
    return {'home_win': hw, 'draw': dr, 'away_win': aw,
            'expected_goals_home': lam, 'expected_goals_away': mu,
            'markets': {'over_2_5': float(p[h+a>=3].sum()),
                        'over_3_5': float(p[h+a>=4].sum()),
                        'under_2_5': float(p[h+a<=2].sum()),
                        'under_3_5': float(p[h+a<=3].sum()),
                        'btts_yes': btts, 'btts_no': 1-btts,
                        'home_dnb': {'conditional_win': hw/(hw+aw)},
                        'away_dnb': {'conditional_win': aw/(hw+aw)}}}


def actuals(m):
    h, a = m['hg'], m['ag']
    return {'over_2_5': int(h+a>=3), 'over_3_5': int(h+a>=4),
            'under_2_5': int(h+a<=2), 'under_3_5': int(h+a<=3),
            'btts_yes': int(h>0 and a>0), 'btts_no': int(h==0 or a==0)}


def evaluate(pred, m):
    result = {'goals_home_error': pred['expected_goals_home']-m['hg'],
              'goals_away_error': pred['expected_goals_away']-m['ag']}
    truth = [int(m['hg']>m['ag']), int(m['hg']==m['ag']), int(m['hg']<m['ag'])]
    probs = [pred['home_win'], pred['draw'], pred['away_win']]
    result['result_log_loss'] = -math.log(max(EPS, probs[truth.index(1)]))
    result['result_brier'] = sum((p-y)**2 for p, y in zip(probs, truth))
    for market, y in actuals(m).items():
        ll, bs = score_probs(pred['markets'][market], y)
        result[market+'_log_loss'] = ll
        result[market+'_brier'] = bs
    # DNB: draws are pushes, not binary losses. Conditional scores exclude draws.
    if m['hg'] != m['ag']:
        for side in ('home', 'away'):
            y = int(m['hg']>m['ag']) if side=='home' else int(m['hg']<m['ag'])
            ll, bs = score_probs(pred['markets'][side+'_dnb']['conditional_win'], y)
            result[side+'_dnb_log_loss'] = ll
            result[side+'_dnb_brier'] = bs
    return result


def aggregate(rows, model):
    data = [r for r in rows if r['model']==model]
    if not data:
        return {'n': 0}
    metrics = sorted({k for r in data for k in r if k.endswith(('_log_loss', '_brier', '_error'))})
    out = {'n': len(data)}
    for k in metrics:
        vals = [r[k] for r in data if k in r]
        if vals:
            out[k] = round(sum(vals)/len(vals), 6)
            if k.endswith('_error'):
                out[k+'_mae'] = round(sum(abs(v) for v in vals)/len(vals), 6)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--min-training', type=int, default=70)
    ap.add_argument('--days-between-fits', type=int, default=7)
    ap.add_argument('--ridge', type=float, default=2.0)
    ap.add_argument('--output', default='football_backtest_results.json')
    ap.add_argument('--csv', default='football_backtest_predictions.csv')
    args = ap.parse_args()
    if args.min_training < 20 or args.days_between_fits < 1 or args.ridge < 0:
        ap.error('Invalid min-training, days-between-fits or ridge')
    token = os.environ.get('FOOTBALL_DATA_API_KEY')
    if not token:
        ap.error('FOOTBALL_DATA_API_KEY secret is missing')
    fm.RIDGE = args.ridge
    all_rows, leagues, errors = [], {}, []
    for code, name in fm.LEAGUES.items():
        try:
            raw = fm.get_matches(code, token)
            parsed = [p for m in raw if (p := fm.parse_match(m)) is not None]
            # Exclude future games and use only completed results.
            matches = sorted((m for m in parsed if 'hg' in m and m['date'] <= datetime.now(timezone.utc)),
                             key=lambda m: m['date'])
            if len(matches) <= args.min_training:
                raise ValueError(f'Only {len(matches)} completed matches; need more than {args.min_training}')
            first_date = matches[args.min_training]['date']
            last_date = matches[-1]['date']
            cursor = first_date
            rows = []
            failed_fits = 0
            while cursor <= last_date:
                end = cursor + timedelta(days=args.days_between_fits)
                # Strictly before this block; never train on a match within the evaluation block.
                train = [m for m in matches if m['date'] < cursor]
                test = [m for m in matches if cursor <= m['date'] < end]
                if len(train) >= args.min_training and test:
                    try:
                        model = fm.fit_model(train, cursor)
                    except (ValueError, RuntimeError) as exc:
                        failed_fits += 1
                        print(f'WARN {code}: fit at {cursor.date()} failed: {exc}')
                        cursor = end
                        continue
                    for m in test:
                        if m['home'] not in model['index'] or m['away'] not in model['index']:
                            continue
                        for label in ('dc', 'baseline'):
                            try:
                                pred = (fm.probabilities(model, m['home'], m['away'])
                                        if label == 'dc' else baseline_probs(train, m))
                            except (ValueError, OverflowError) as exc:
                                print(f'WARN {code} {m["date"]}: {label} prediction failed: {exc}')
                                continue
                            row = {'league': code, 'model': label, 'kickoff_utc': m['date'].isoformat(),
                                   'home': m['home_name'], 'away': m['away_name'],
                                   'home_goals': m['hg'], 'away_goals': m['ag'],
                                   'training_matches': len(train),
                                   **evaluate(pred, m)}
                            rows.append(row)
                cursor = end
            # Paired comparison: both models must have predicted the same match.
            dc_keys = {(r['kickoff_utc'], r['home'], r['away']) for r in rows if r['model']=='dc'}
            base_keys = {(r['kickoff_utc'], r['home'], r['away']) for r in rows if r['model']=='baseline'}
            common = dc_keys & base_keys
            rows = [r for r in rows if (r['kickoff_utc'], r['home'], r['away']) in common]
            all_rows.extend(rows)
            leagues[code] = {'name': name, 'available_finished': len(matches),
                             'paired_predictions': len(common), 'failed_fits': failed_fits,
                             'dc': aggregate(rows, 'dc'), 'baseline': aggregate(rows, 'baseline')}
            print(f'{code}: {len(common)} out-of-sample paired predictions; {failed_fits} failed refits')
        except (requests.RequestException, KeyError, ValueError, RuntimeError) as exc:
            errors.append(f'{code}: {exc}')
            leagues[code] = {'name': name, 'error': str(exc)}
            print(f'ERROR {code}: {exc}')
        time.sleep(7)
    report = {'generated_utc': datetime.now(timezone.utc).isoformat(),
              'method': 'rolling-origin block backtest; train on matches strictly before each block',
              'min_training': args.min_training, 'days_between_fits': args.days_between_fits,
              'ridge': args.ridge, 'leagues': leagues,
              'overall': {'dc': aggregate(all_rows, 'dc'),
                          'baseline': aggregate(all_rows, 'baseline')}, 'errors': errors,
              'caveats': ['Current-season-only data; limited sample and possible selection bias',
                          'Fixtures within each block are forecast from a model fit at block start',
                          'No bookmaker odds, betting ROI or profitability assessment',
                          'DNB scoring excludes pushes (draws)',
                          'Historical feed timestamps are kickoff times, not confirmed result publication times']}
    Path(args.output).write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    if all_rows:
        fields = list(dict.fromkeys(k for r in all_rows for k in r))
        with open(args.csv, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(all_rows)
    print(f'Wrote {args.output} and {len(all_rows)} prediction rows')
    if errors or not all_rows:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
