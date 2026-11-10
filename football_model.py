"""Football Strategy 3.0 probability model v2. Requires requests, numpy, scipy.
Set FOOTBALL_DATA_API_KEY in the environment. Produces forecasts, not bets.
"""
import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone

import numpy as np
import requests
from scipy.optimize import minimize
from scipy.stats import poisson

API = 'https://api.football-data.org/v4'
LEAGUES = {'BL1': 'Bundesliga', 'DED': 'Eredivisie', 'ELC': 'Championship', 'SA': 'Serie A'}
HALF_LIFE_DAYS = 120.0
MIN_MATCHES = 70
RIDGE = 2.0  # Provisional; tune by rolling-origin backtest.
MASS_TARGET = 0.9999


def get_matches(code, token):
    r = requests.get(f'{API}/competitions/{code}/matches',
                     headers={'X-Auth-Token': token}, timeout=30)
    r.raise_for_status()
    return r.json()['matches']


def parse_match(m):
    home, away = m.get('homeTeam') or {}, m.get('awayTeam') or {}
    if home.get('id') is None or away.get('id') is None:
        return None
    dt = datetime.fromisoformat(m['utcDate'].replace('Z', '+00:00'))
    item = {'home': home['id'], 'away': away['id'],
            'home_name': home.get('shortName') or home.get('name') or str(home['id']),
            'away_name': away.get('shortName') or away.get('name') or str(away['id']),
            'date': dt, 'status': m['status']}
    score = (m.get('score') or {}).get('fullTime') or {}
    if m['status'] == 'FINISHED' and score.get('home') is not None and score.get('away') is not None:
        item['hg'], item['ag'] = int(score['home']), int(score['away'])
    return item


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
    teams = sorted({m['home'] for m in completed} | {m['away'] for m in completed})
    if len(completed) < MIN_MATCHES or len(teams) < 4:
        raise ValueError(f'Insufficient sample: {len(completed)} matches')
    index = {team: i for i, team in enumerate(teams)}
    hi = np.array([index[m['home']] for m in completed], dtype=int)
    ai = np.array([index[m['away']] for m in completed], dtype=int)
    hg = np.array([m['hg'] for m in completed], dtype=float)
    ag = np.array([m['ag'] for m in completed], dtype=float)
    days = np.array([max(0, (now - m['date']).total_seconds()/86400) for m in completed])
    weights = np.exp(-np.log(2)*days/HALF_LIFE_DAYS)
    n = len(teams)
    # attack, defence, league baseline, home advantage, rho
    def unpack(x):
        attack = x[:n] - x[:n].mean()
        defence = x[n:2*n] - x[n:2*n].mean()
        return attack, defence, x[-3], x[-2], x[-1]

    def loss(x):
        attack, defence, baseline, home_adv, rho = unpack(x)
        lam = np.exp(baseline + home_adv + attack[hi] - defence[ai])
        mu = np.exp(baseline + attack[ai] - defence[hi])
        tau = np.ones(len(hg))
        m = (hg == 0) & (ag == 0)
        tau[m] = 1 - lam[m]*mu[m]*rho
        m = (hg == 0) & (ag == 1)
        tau[m] = 1 + lam[m]*rho
        m = (hg == 1) & (ag == 0)
        tau[m] = 1 + mu[m]*rho
        m = (hg == 1) & (ag == 1)
        tau[m] = 1-rho
        # The four DC factors must be positive for ALL training fixtures,
        # even if their observed score was not 0-0, 0-1, 1-0 or 1-1.
        if np.any(1-lam*mu*rho <= 0) or np.any(1+lam*rho <= 0) or np.any(1+mu*rho <= 0) or 1-rho <= 0:
            return 1e12
        ll = poisson.logpmf(hg, lam) + poisson.logpmf(ag, mu) + np.log(tau)
        penalty = RIDGE*(np.sum(attack**2) + np.sum(defence**2))
        return -float(np.dot(weights, ll)) + penalty

    x0 = np.zeros(2*n+3)
    home_mean = max(0.1, float(np.average(hg, weights=weights)))
    away_mean = max(0.1, float(np.average(ag, weights=weights)))
    x0[-3] = math.log(away_mean)
    x0[-2] = math.log(home_mean/away_mean)
    bounds = [(-1.5, 1.5)]*(2*n) + [(-1.5, 1.5), (-0.8, 0.8), (-0.05, 0.05)]
    result = minimize(loss, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': 1200, 'ftol': 1e-9})
    if not result.success:
        raise RuntimeError(f'Model optimisation failed: {result.message}')
    attack, defence, baseline, home_adv, rho = unpack(result.x)
    return {'index': index, 'attack': attack, 'defence': defence,
            'baseline': float(baseline), 'home_adv': float(home_adv),
            'rho': float(rho), 'matches': len(completed)}


def probabilities(model, home, away):
    hi, ai = model['index'][home], model['index'][away]
    lam = math.exp(model['baseline'] + model['home_adv'] + float(model['attack'][hi]-model['defence'][ai]))
    mu = math.exp(model['baseline'] + float(model['attack'][ai]-model['defence'][hi]))
    rho = model['rho']
    # If the DC correction is not valid for a forecast, fail rather than silently
    # publishing an invalid distribution.
    factors = [dc_tau(h, a, lam, mu, rho) for h in (0, 1) for a in (0, 1)]
    if min(factors) <= 0:
        raise ValueError(f'Invalid Dixon-Coles correction: lambda={lam:.3f}, mu={mu:.3f}')
    max_goals = max(10, int(math.ceil(max(lam, mu))))
    while poisson.cdf(max_goals, lam)*poisson.cdf(max_goals, mu) < MASS_TARGET:
        max_goals += 2
        if max_goals > 100:
            raise ValueError('Goal distribution failed to converge')
    hp = poisson.pmf(np.arange(max_goals+1), lam)
    ap = poisson.pmf(np.arange(max_goals+1), mu)
    matrix = np.outer(hp, ap)
    for h in (0, 1):
        for a in (0, 1):
            matrix[h, a] *= dc_tau(h, a, lam, mu, rho)
    retained_mass = float(matrix.sum())
    if not 0 < retained_mass <= 1.000001:
        raise ValueError('Invalid matrix mass')
    matrix /= retained_mass
    h, a = np.indices(matrix.shape)
    hw = float(matrix[h > a].sum())
    aw = float(matrix[h < a].sum())
    draw = float(matrix[h == a].sum())
    btts = float(matrix[(h > 0) & (a > 0)].sum())
    markets = {
        'over_2_5': float(matrix[h+a >= 3].sum()),
        'over_3_5': float(matrix[h+a >= 4].sum()),
        'under_2_5': float(matrix[h+a <= 2].sum()),
        'under_3_5': float(matrix[h+a <= 3].sum()),
        'btts_yes': btts, 'btts_no': 1-btts,
        'home_dnb': {'win': hw, 'push': draw, 'lose': aw,
                     'conditional_win': hw/(hw+aw)},
        'away_dnb': {'win': aw, 'push': draw, 'lose': hw,
                     'conditional_win': aw/(hw+aw)},
    }
    return {'expected_goals_home': round(lam, 3), 'expected_goals_away': round(mu, 3),
            'home_win': hw, 'draw': draw, 'away_win': aw,
            'matrix_retained_mass': retained_mass, 'max_goals': max_goals,
            'markets': markets}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=14)
    parser.add_argument('--output', default='football_probabilities.json')
    args = parser.parse_args()
    token = os.getenv('FOOTBALL_DATA_API_KEY')
    if not token:
        sys.exit('Missing FOOTBALL_DATA_API_KEY environment variable')
    now = datetime.now(timezone.utc)
    output = {'generated_utc': now.isoformat(), 'model': 'recency-weighted Dixon-Coles v2',
              'half_life_days': HALF_LIFE_DAYS, 'ridge': RIDGE,
              'leagues': {}, 'fixtures': []}
    for code, name in LEAGUES.items():
        try:
            raw = get_matches(code, token)
            parsed = [p for m in raw if (p := parse_match(m)) is not None]
            finished = [m for m in parsed if 'hg' in m and m['date'] <= now]
            model = fit_model(finished, now)
            upcoming = sorted((m for m in parsed if 'hg' not in m and m['date'] >= now
                               and (m['date']-now).total_seconds() <= args.days*86400),
                              key=lambda m: m['date'])
            league_predictions = []
            for match in upcoming:
                if match['home'] not in model['index'] or match['away'] not in model['index']:
                    continue
                pred = probabilities(model, match['home'], match['away'])
                league_predictions.append({'league': code, 'kickoff_utc': match['date'].isoformat(),
                                           'home': match['home_name'], 'away': match['away_name'], **pred})
            output['fixtures'].extend(league_predictions)
            output['leagues'][code] = {'name': name, 'status': 'ok',
                                       'training_matches': model['matches'],
                                       'rho': model['rho'], 'baseline': model['baseline']}
            print(f'PASS {name}: {len(finished)} finished, {len(league_predictions)} forecast fixtures')
        except (requests.RequestException, ValueError, RuntimeError, KeyError) as exc:
            output['leagues'][code] = {'name': name, 'status': 'error', 'message': str(exc)}
            print(f'FAIL {name}: {exc}', file=sys.stderr)
        time.sleep(7)
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, allow_nan=False)
    print(f'Wrote {len(output["fixtures"])} forecasts to {args.output}')
    if any(v['status'] != 'ok' for v in output['leagues'].values()):
        sys.exit(1)


if __name__ == '__main__':
    main()
