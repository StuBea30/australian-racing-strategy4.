"""Football Strategy 3.0: recency-weighted home/away Dixon-Coles model.

Requires: requests, numpy, scipy. Set FOOTBALL_DATA_API_KEY as an environment variable.
This program produces probabilities, not betting recommendations.
"""
import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
import requests
from scipy.optimize import minimize

API = 'https://api.football-data.org/v4'
LEAGUES = {'BL1': 'Bundesliga', 'DED': 'Eredivisie', 'ELC': 'Championship', 'SA': 'Serie A'}
MAX_GOALS = 10
HALF_LIFE_DAYS = 120.0
MIN_MATCHES = 70


def get_matches(code, token):
    response = requests.get(f'{API}/competitions/{code}/matches',
                            headers={'X-Auth-Token': token}, timeout=30)
    response.raise_for_status()
    return response.json()['matches']


def parse_match(m):
    home = m.get('homeTeam') or {}
    away = m.get('awayTeam') or {}
    if not home.get('id') or not away.get('id'):
        return None
    dt = datetime.fromisoformat(m['utcDate'].replace('Z', '+00:00'))
    result = {'home': home['id'], 'away': away['id'],
              'home_name': home.get('shortName') or home.get('name') or str(home['id']),
              'away_name': away.get('shortName') or away.get('name') or str(away['id']),
              'date': dt, 'status': m['status']}
    score = (m.get('score') or {}).get('fullTime') or {}
    if m['status'] == 'FINISHED' and score.get('home') is not None and score.get('away') is not None:
        result['hg'], result['ag'] = int(score['home']), int(score['away'])
    return result


def dc_tau(h, a, lam, mu, rho):
    if h == 0 and a == 0:
        return 1 - lam * mu * rho
    if h == 0 and a == 1:
        return 1 + lam * rho
    if h == 1 and a == 0:
        return 1 + mu * rho
    if h == 1 and a == 1:
        return 1 - rho
    return 1.0


def fit_model(completed, now):
    """Weighted maximum likelihood, separate attack/defence, home advantage, DC rho."""
    teams = sorted({m['home'] for m in completed} | {m['away'] for m in completed})
    if len(completed) < MIN_MATCHES or len(teams) < 4:
        raise ValueError(f'Insufficient sample: {len(completed)} matches')
    index = {t: i for i, t in enumerate(teams)}
    hi = np.array([index[m['home']] for m in completed], dtype=int)
    ai = np.array([index[m['away']] for m in completed], dtype=int)
    hg = np.array([m['hg'] for m in completed], dtype=float)
    ag = np.array([m['ag'] for m in completed], dtype=float)
    days = np.array([max(0, (now - m['date']).total_seconds() / 86400) for m in completed])
    weights = np.exp(-np.log(2) * days / HALF_LIFE_DAYS)
    n = len(teams)
    # Parameters: attack for n teams, defence for n teams, home advantage, rho.
    # Mean-centre attack and defence to remove identifiability ambiguity.
    def unpack(x):
        attack = x[:n] - np.mean(x[:n])
        defence = x[n:2*n] - np.mean(x[n:2*n])
        return attack, defence, x[-2], x[-1]

    def loss(x):
        attack, defence, home_adv, rho = unpack(x)
        lam = np.exp(np.clip(home_adv + attack[hi] - defence[ai], -4, 4))
        mu = np.exp(np.clip(attack[ai] - defence[hi], -4, 4))
        tau = np.ones(len(hg))
        tau[(hg == 0) & (ag == 0)] = 1 - (lam * mu * rho)[(hg == 0) & (ag == 0)]
        tau[(hg == 0) & (ag == 1)] = (1 + lam * rho)[(hg == 0) & (ag == 1)]
        tau[(hg == 1) & (ag == 0)] = (1 + mu * rho)[(hg == 1) & (ag == 0)]
        tau[(hg == 1) & (ag == 1)] = 1 - rho
        if np.any(tau <= 0):
            return 1e10
        ll = hg*np.log(lam) - lam - np.array([math.lgamma(v+1) for v in hg])
        ll += ag*np.log(mu) - mu - np.array([math.lgamma(v+1) for v in ag])
        ll += np.log(tau)
        # Mild shrinkage reduces instability for sparse teams.
        penalty = 0.15 * (np.sum(attack**2) + np.sum(defence**2))
        return -float(np.dot(weights, ll)) + penalty

    x0 = np.zeros(2*n + 2)
    x0[-2] = math.log(max(0.3, float(np.mean(hg))))
    bounds = [(-2.5, 2.5)]*(2*n) + [(-1.5, 1.5), (-0.08, 0.08)]
    result = minimize(loss, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': 800, 'ftol': 1e-10})
    if not result.success:
        raise RuntimeError(f'Model optimisation failed: {result.message}')
    attack, defence, home_adv, rho = unpack(result.x)
    return {'index': index, 'attack': attack, 'defence': defence,
            'home_adv': home_adv, 'rho': rho, 'matches': len(completed)}


def probabilities(model, home, away):
    hi, ai = model['index'][home], model['index'][away]
    lam = math.exp(float(model['home_adv'] + model['attack'][hi] - model['defence'][ai]))
    mu = math.exp(float(model['attack'][ai] - model['defence'][hi]))
    rho = float(model['rho'])
    hp = np.array([math.exp(-lam) * lam**k / math.factorial(k) for k in range(MAX_GOALS+1)])
    ap = np.array([math.exp(-mu) * mu**k / math.factorial(k) for k in range(MAX_GOALS+1)])
    matrix = np.outer(hp, ap)
    for h in (0, 1):
        for a in (0, 1):
            matrix[h, a] *= dc_tau(h, a, lam, mu, rho)
    # Renormalise the truncated 0..10 matrix; discarded tail is normally tiny.
    retained_mass = float(matrix.sum())
    if retained_mass <= 0:
        raise ValueError('Invalid probability matrix')
    matrix /= retained_mass
    h, a = np.indices(matrix.shape)
    home_win = float(matrix[h > a].sum())
    away_win = float(matrix[h < a].sum())
    draw = float(matrix[h == a].sum())
    btts = float(matrix[(h > 0) & (a > 0)].sum())
    markets = {
        'over_2_5': float(matrix[h+a >= 3].sum()),
        'over_3_5': float(matrix[h+a >= 4].sum()),
        'under_2_5': float(matrix[h+a <= 2].sum()),
        'under_3_5': float(matrix[h+a <= 3].sum()),
        'btts_yes': btts,
        'btts_no': 1-btts,
        'home_dnb': {'win': home_win, 'push': draw, 'lose': away_win,
                     'conditional_win': home_win/(home_win+away_win)},
        'away_dnb': {'win': away_win, 'push': draw, 'lose': home_win,
                     'conditional_win': away_win/(home_win+away_win)},
    }
    return {'expected_goals_home': round(lam, 3), 'expected_goals_away': round(mu, 3),
            'home_win': home_win, 'draw': draw, 'away_win': away_win,
            'matrix_retained_mass': retained_mass, 'markets': markets}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=14, help='Days ahead to forecast')
    parser.add_argument('--output', default='football_probabilities.json')
    args = parser.parse_args()
    token = os.getenv('FOOTBALL_DATA_API_KEY')
    if not token:
        sys.exit('Missing FOOTBALL_DATA_API_KEY environment variable')
    now = datetime.now(timezone.utc)
    output = {'generated_utc': now.isoformat(), 'model': 'recency-weighted Dixon-Coles',
              'half_life_days': HALF_LIFE_DAYS, 'leagues': {}, 'fixtures': []}
    for code, name in LEAGUES.items():
        try:
            raw = get_matches(code, token)
            parsed = [p for m in raw if (p := parse_match(m)) is not None]
            finished = [m for m in parsed if 'hg' in m and m['date'] <= now]
            model = fit_model(finished, now)
            output['leagues'][code] = {'name': name, 'status': 'ok',
                                       'training_matches': model['matches'], 'rho': float(model['rho'])}
            upcoming = sorted((m for m in parsed if 'hg' not in m and m['date'] >= now
                               and (m['date']-now).total_seconds() <= args.days*86400),
                              key=lambda m: m['date'])
            count = 0
            for match in upcoming:
                if match['home'] not in model['index'] or match['away'] not in model['index']:
                    continue
                pred = probabilities(model, match['home'], match['away'])
                output['fixtures'].append({'league': code, 'kickoff_utc': match['date'].isoformat(),
                                           'home': match['home_name'], 'away': match['away_name'], **pred})
                count += 1
            print(f'PASS {name}: {len(finished)} finished, {count} forecast fixtures')
        except (requests.RequestException, ValueError, RuntimeError, KeyError) as exc:
            output['leagues'][code] = {'name': name, 'status': 'error', 'message': str(exc)}
            print(f'FAIL {name}: {exc}', file=sys.stderr)
        time.sleep(7)  # Conservative pacing under free-tier rate limit.
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, allow_nan=False)
    print(f'Wrote {len(output["fixtures"])} forecasts to {args.output}')
    if any(v['status'] != 'ok' for v in output['leagues'].values()):
        sys.exit(1)


if __name__ == '__main__':
    main()
