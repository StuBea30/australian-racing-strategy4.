"""Football Strategy 3.0 v4: nested chronological validation, no betting.
Uses the existing football_model.py unchanged. Fetches 2024/25–2026/27 data.
Tune on 2025/26, independently evaluate on 2026/27. No future-result leakage.
"""
import argparse
import csv
import json
import math
import os
from pathlib import Path
import time
import types
from datetime import datetime, timezone, timedelta
import requests
import numpy as np

LEAGUES = {'BL1':'Bundesliga','DED':'Eredivisie','ELC':'Championship','SA':'Serie A'}
CONFIGS = [
    {'half_life': 90, 'ridge': 1.0, 'rho_bound': 0.05},
    {'half_life': 120, 'ridge': 2.0, 'rho_bound': 0.05},  # v2 baseline
    {'half_life': 180, 'ridge': 2.0, 'rho_bound': 0.10},
    {'half_life': 240, 'ridge': 4.0, 'rho_bound': 0.10},
]

def load_model(path, cfg):
    # The only source modification is the existing literal rho bounds.
    # Runs repository-owned Python code, never remote code.
    source = Path(path).read_text(encoding='utf-8')
    old = '(-0.05, 0.05)'
    if source.count(old) != 1:
        raise RuntimeError('Expected exactly one rho bound in football_model.py; model changed. Stop and review.')
    source = source.replace(old, f'(-{cfg["rho_bound"]}, {cfg["rho_bound"]})')
    module = types.ModuleType('football_model_v4_runtime')
    module.__dict__['__name__'] = 'football_model_v4_runtime'
    exec(compile(source, path, 'exec'), module.__dict__)
    module.HALF_LIFE_DAYS = cfg['half_life']
    module.RIDGE = cfg['ridge']
    return module

def fetch(session, code, season, token):
    r = session.get(f'https://api.football-data.org/v4/competitions/{code}/matches',
                    params={'season':season}, headers={'X-Auth-Token':token}, timeout=45)
    r.raise_for_status()
    return r.json()['matches']

def score(rows):
    if not rows: return {'n':0}
    out={'n':len(rows)}
    for name in ('over_2_5','over_3_5','btts_yes'):
        out[name+'_brier'] = sum((r['p_'+name]-r['y_'+name])**2 for r in rows)/len(rows)
        out[name+'_mean_p'] = sum(r['p_'+name] for r in rows)/len(rows)
        out[name+'_actual'] = sum(r['y_'+name] for r in rows)/len(rows)
    out['brier_average'] = sum(out[x+'_brier'] for x in ('over_2_5','over_3_5','btts_yes'))/3
    out['goals_predicted'] = sum(r['pred_goals'] for r in rows)/len(rows)
    out['goals_actual'] = sum(r['actual_goals'] for r in rows)/len(rows)
    out['rho_boundary_fraction'] = sum(r['rho_boundary'] for r in rows)/len(rows)
    return out

def predict_period(module, completed, start, end, refit_days, bound):
    tests=[m for m in completed if start <= m['date'] < end]
    rows=[]
    origin=start
    while origin < end:
        train=[m for m in completed if m['date'] < origin]
        block=[m for m in tests if origin <= m['date'] < min(end, origin+timedelta(days=refit_days))]
        if block and len(train)>=module.MIN_MATCHES:
            try: fitted=module.fit_model(train, origin)
            except (ValueError,RuntimeError,OverflowError,FloatingPointError) as exc:
                print(f'WARN fit {origin.date()}: {exc}',flush=True)
                origin+=timedelta(days=refit_days)
                continue
            for m in block:
                if m['home'] not in fitted['index'] or m['away'] not in fitted['index']: continue
                try: p=module.probabilities(fitted,m['home'],m['away'])
                except (ValueError,OverflowError,FloatingPointError): continue
                total=m['hg']+m['ag']
                rows.append({'date':m['date'].isoformat(),'home':m['home_name'],'away':m['away_name'],
                    'p_over_2_5':p['markets']['over_2_5'],'y_over_2_5':int(total>=3),
                    'p_over_3_5':p['markets']['over_3_5'],'y_over_3_5':int(total>=4),
                    'p_btts_yes':p['markets']['btts_yes'],'y_btts_yes':int(m['hg']>0 and m['ag']>0),
                    'pred_goals':p['expected_goals_home']+p['expected_goals_away'],
                    'actual_goals':total,'rho_boundary':int(abs(fitted['rho']) >= bound-1e-5)})
        origin+=timedelta(days=refit_days)
    return rows

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--model',default='football_model.py')
    ap.add_argument('--refit-days',type=int,default=28)
    ap.add_argument('--pause',type=float,default=7)
    args=ap.parse_args()
    token=os.getenv('FOOTBALL_DATA_API_KEY')
    if not token: raise SystemExit('Missing FOOTBALL_DATA_API_KEY')
    if args.refit_days<1: ap.error('refit-days must be >= 1')
    baseline=CONFIGS[1]
    parser=load_model(args.model,baseline)
    now=datetime.now(timezone.utc)
    validation_start=datetime(2025,8,1,tzinfo=timezone.utc)
    holdout_start=datetime(2026,8,1,tzinfo=timezone.utc)
    results={'created_utc':now.isoformat(),'validation':'2025/26','untouched_holdout':'2026/27',
        'selection_metric':'mean of 3 binary-market Brier scores on 2025/26 only',
        'configs':CONFIGS,'leagues':{},'notes':['No bookmaker odds or profitability evaluation.',
        'Holdout results are not used to select parameters.',
        'Promoted or relegated teams with no training history are skipped.',
        'Each refit uses matches strictly before its origin; no results from the same block.']}
    session=requests.Session()
    all_holdout=[]
    for code,name in LEAGUES.items():
        raw=[]; failures=[]
        for season in (2024,2025,2026):
            try:
                data=fetch(session,code,season,token)
                raw.extend(data)
                print(f'{code} {season}: {len(data)} matches',flush=True)
            except requests.RequestException as exc:
                failures.append(f'{season}: {exc}')
                print(f'WARN {code} {season}: {exc}',flush=True)
            time.sleep(args.pause)
        parsed=[p for x in raw if (p:=parser.parse_match(x)) is not None and 'hg' in p and p['date']<=now]
        unique={(m['date'],m['home'],m['away']):m for m in parsed}
        completed=sorted(unique.values(),key=lambda m:m['date'])
        tuning=[]
        for cfg in CONFIGS:
            mod=load_model(args.model,cfg)
            rows=predict_period(mod,completed,validation_start,holdout_start,args.refit_days,cfg['rho_bound'])
            tuning.append({'config':cfg,'validation':score(rows)})
        eligible=[t for t in tuning if t['validation']['n']>=40]
        if not eligible:
            results['leagues'][code]={'name':name,'error':'Insufficient validation matches (at least 40 required)',
                                      'tuning':tuning,'fetch_warnings':failures}
            continue
        winner=min(eligible,key=lambda x:x['validation']['brier_average'])
        selected=winner['config']
        selected_rows=predict_period(load_model(args.model,selected),completed,holdout_start,now,args.refit_days,selected['rho_bound'])
        baseline_rows=predict_period(load_model(args.model,baseline),completed,holdout_start,now,args.refit_days,baseline['rho_bound'])
        for row in selected_rows: row.update({'league':code,'model':'selected'})
        for row in baseline_rows: row.update({'league':code,'model':'baseline'})
        all_holdout.extend(selected_rows+baseline_rows)
        results['leagues'][code]={'name':name,'selected':selected,'tuning':tuning,
            'selected_holdout':score(selected_rows),'baseline_holdout':score(baseline_rows),
            'fetch_warnings':failures}
        print(f'{name}: validation selected {selected}; holdout {len(selected_rows)} fixtures',flush=True)
    results['overall_selected_holdout']=score([r for r in all_holdout if r['model']=='selected'])
    results['overall_baseline_holdout']=score([r for r in all_holdout if r['model']=='baseline'])
    Path('football_v4_results.json').write_text(json.dumps(results,indent=2,allow_nan=False),encoding='utf-8')
    if all_holdout:
        with open('football_v4_holdout.csv','w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=list(all_holdout[0]));writer.writeheader();writer.writerows(all_holdout)
    print(json.dumps({'selected':results['overall_selected_holdout'],
                      'baseline':results['overall_baseline_holdout']},indent=2),flush=True)
    if not all_holdout: raise SystemExit('No holdout predictions: inspect API warnings and training coverage')

if __name__=='__main__': main()
