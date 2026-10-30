#!/usr/bin/env python3
"""Strategy 4.1 named-opponent historical scoring v10 (field integrity safeguards; not back-tested).

Drop-in replacement for score_racing.py. Uses only fields in the existing racecard
and past-start CSVs. Unavailable opponent ratings, claims, trials and track bias
are NOT invented. Rankings require all six factors and adequate evidence.
"""
import argparse
import csv
import json
import re
from collections import defaultdict
from functools import lru_cache
from datetime import datetime
from pathlib import Path

WEIGHTS = {'form':30., 'class':25., 'distance':40/3, 'going':40/3,
           'barrier_weight':40/3, 'fitness':5.}
KEY = ('date','meeting','race','horse')
NEUTRAL = 0.5


def number(value):
    m = re.search(r'-?\d+(?:\.\d+)?', str(value or ''))
    return float(m.group()) if m else None


def date_value(value):
    for fmt in ('%d/%m/%y','%d/%m/%Y','%Y-%m-%d'):
        try: return datetime.strptime(str(value).strip(),fmt).date()
        except ValueError: pass
    return None


def clamp(x, lo=0., hi=1.):
    return max(lo,min(hi,x))


def record(value):
    m = re.search(r'(\d+)\s*:\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)',str(value or ''))
    return tuple(map(int,m.groups())) if m else None


def race_class(value):
    """Conservative race-grade scale; avoid assuming every OPEN is elite.

    Numeric benchmark grade is the strongest comparable grade signal.
    Picnic/trophy and quality races are recognised rather than silently
    treated as unknown. OPEN without prize/opposition evidence stays neutral.
    """
    s = str(value or '').upper().strip()
    if re.search(r'\b(?:TRPY\s*\w*|TROPHY|PICNIC|AMATEUR)\b', s): return 1.2
    if re.search(r'\b(?:G1|GROUP\s*1)\b',s): return 10.
    if re.search(r'\b(?:G2|GROUP\s*2)\b',s): return 9.
    if re.search(r'\b(?:G3|GROUP\s*3)\b',s): return 8.
    if re.search(r'\b(?:LISTED|LR)\b',s): return 7.
    m = re.search(r'\b(?:BM\s*0\s*-\s*|BM\s*|BENCHMARK\s*)(\d+)\b',s)
    if m: return clamp((int(m.group(1))-50)/50,0,1)*2.5+3.5
    m = re.search(r'\b(?:CL|CLASS)\s*([1-6])\b',s)
    if m: return 2.5+0.55*int(m.group(1))
    if re.search(r'\b(?:MDN|MAIDEN)\b',s): return 2.
    if re.search(r'\b(?:QLTY|QUALITY)\b',s): return 6.2
    if re.search(r'\bOPEN\b',s): return 5.2
    return None


def past_finish(value):
    m = re.search(r'(\d+)(?:st|nd|rd|th)?\s+of\s+(\d+)',str(value or ''),re.I)
    if not m: return None
    p,n=map(int,m.groups())
    return (p,n) if 1<=p<=n else None


def is_picnic(row):
    """Detect low-grade picnic/amateur starts only when the source labels them."""
    label = ' '.join(str(row.get(k) or '') for k in ('Class', 'Race', 'Race Name', 'Meeting'))
    return bool(re.search(r'\b(?:picnic|trophy|amateur|trpy\s*\w*)\b', label, re.I))


def field_quality(row):
    """Small fields provide weaker evidence of a strong placing."""
    finish = past_finish(row.get('Place'))
    if not finish:
        return 0.5
    _, size = finish
    return clamp((size - 4) / 8)  # 4 runners -> 0; 12+ -> 1


def performance(row):
    finish=past_finish(row.get('Place'))
    if not finish: return None
    p,n=finish
    percentile = 1-(p-1)/max(1,n-1)
    margin=number(row.get('Margin'))
    # Margin conventions are not guaranteed to distinguish winning margin
    # from beaten margin. Only use a positive margin for non-winners.
    if margin is not None and p>1 and margin>=0:
        margin_component=clamp(1-margin/10)
        return clamp(0.7*percentile+0.3*margin_component)
    return clamp(percentile)


def going_type(value):
    s=str(value or '').lower()
    for term in ('synthetic','heavy','soft','good','firm'):
        if term in s: return term
    return None


def is_trial(row):
    """Exclude trials/jump-outs from official racing form, even with a placing."""
    classification = str(row.get('Class') or '').lower()
    return bool(re.search(r'\b(?:trial|jump[ -]?out|barrier trial|practice)\b', classification))


def valid_record(value):
    """Reject dates or malformed records rather than accepting embedded text."""
    match = re.fullmatch(r'\s*(\d+)\s*:\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*', str(value or ''))
    if not match:
        return None
    starts, wins, seconds, thirds = map(int, match.groups())
    if starts <= 0 or wins + seconds + thirds > starts:
        return None
    return starts, wins, seconds, thirds


def historical_rows(rows,race_date):
    found=[]
    for row in rows:
        d=date_value(row.get('Date'))
        if d and d<race_date: found.append((d,row))
    return [r for _,r in sorted(found,key=lambda item:item[0],reverse=True)]


def weighted(samples):
    return sum(v*w for v,w in samples)/sum(w for _,w in samples) if samples else None


def record_quality(rec):
    if not rec or not rec[0]: return None
    starts,wins,seconds,thirds=rec
    return clamp((wins+0.55*seconds+0.3*thirds+1.5)/(starts+3))


def evidence_blend(observed, count, prior=NEUTRAL, strength=2):
    if observed is None: return prior
    return (count*observed+strength*prior)/(count+strength)


def normalise_name(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def result_names(value):
    """Extract only explicitly named first/second/third finishers."""
    s = str(value or "")
    matches = re.findall(r"(?:^|\s)([123])\.\s*(.*?)(?=\s+[123]\.\s*|$)", s)
    return [name.strip(' ,.;') for _, name in matches if name.strip(' ,.;')]


class HistoricalOpponents:
    """Evaluate named opponents using form strictly before the shared race date.

    Unmatched or thinly evidenced rivals contribute nothing (not a low rating).
    Prize money is not read or used anywhere in this model.
    """
    def __init__(self, histories):
        self.by_name=defaultdict(dict)
        for row in histories:
            if is_trial(row): continue
            d=date_value(row.get('Date'))
            name=normalise_name(row.get('horse'))
            if d and name:
                key=(d,normalise_name(row.get('Track')),str(row.get('Distance')),str(row.get('Place')))
                self.by_name[name][key]=row
        self.by_name={k: sorted(v.values(),key=lambda r:date_value(r['Date'])) for k,v in self.by_name.items()}

    @lru_cache(maxsize=120000)
    def rating_before(self, name, cutoff):
        rows=self.by_name.get(name,[])
        prior=[r for r in rows if date_value(r.get('Date')) < cutoff]
        if len(prior)<2: return None
        samples=[]
        for r in prior[-5:]:
            perf=performance(r)
            grade=race_class(r.get('Class'))
            if perf is None or grade is None: continue
            # Two independent observed dimensions: prior grade and result.
            samples.append(0.65*clamp(grade/10)+0.35*perf)
        if len(samples)<2: return None
        return sum(samples)/len(samples)

    def context(self, row):
        cutoff=date_value(row.get('Date'))
        if cutoff is None: return None
        names=result_names(row.get('Result'))
        own=normalise_name(row.get('horse'))
        values=[self.rating_before(normalise_name(n),cutoff) for n in names if normalise_name(n)!=own]
        values=[v for v in values if v is not None]
        if not values: return None
        return sum(values)/len(values),len(values)


def score_runner(horse, history, opponent_index=None):
    rdate=date_value(horse.get('date'))
    if rdate is None: raise ValueError('Runner has invalid date')
    history_all=historical_rows(history,rdate)
    trials=[r for r in history_all if is_trial(r)]
    past=[r for r in history_all if not is_trial(r)]
    last6=past[:6]
    notes=[]
    current_class=race_class(horse.get('race_class'))
    target=number(horse.get('distance_m'))
    surface=going_type(horse.get('track'))

    # Form: results are contextualised by field size and class. A small-field
    # picnic placing must not receive the same credit as a BM50 placing.
    fs=[]
    for i,r in enumerate(last6):
        perf=performance(r)
        if perf is None: continue
        oldclass=race_class(r.get('Class'))
        class_delta=(oldclass-current_class) if oldclass is not None and current_class is not None else 0
        context=clamp(0.5+0.055*class_delta,0.18,0.80)
        field=field_quality(r)
        # Adjust performance toward neutral based on race quality, not by
        # assigning every picnic runner a poor score automatically.
        reliability=clamp(0.55+0.25*field+0.20*context,0.4,1)
        adjusted=clamp(0.5+(perf-0.5)*reliability+0.10*(context-0.5))
        if is_picnic(r):
            adjusted=clamp(adjusted-0.10*max(0,perf-0.5)/0.5)
        fs.append((adjusted,0.8**i))
    form=WEIGHTS['form']*evidence_blend(weighted(fs),len(fs),strength=2)
    if len(fs)<3: notes.append('limited form evidence')

    # Class: reward quality achieved at/above today's level and punish
    # unproven class rises. No invented opponent ratings.
    cs=[]
    if current_class is not None:
        for i,r in enumerate(last6):
            old=race_class(r.get('Class')); perf=performance(r)
            if old is None or perf is None: continue
            level=clamp(0.5+0.19*(old-current_class))
            quality=clamp(0.86*level+0.14*perf)
            if is_picnic(r):
                quality=clamp(quality-0.10)
            # Measured rival quality is an additional, bounded class signal.
            # No missing-rival penalty; do not infer ability from prize money.
            if opponent_index is not None:
                context=opponent_index.context(r)
                if context is not None:
                    rival_quality,matched=context
                    quality=clamp(quality+0.24*(rival_quality-0.5)*min(1,matched/2))
            cs.append((quality,0.8**i))
    class_score=WEIGHTS['class']*evidence_blend(weighted(cs),len(cs),strength=2) if current_class is not None else None
    if class_score is None: notes.append('class evidence unavailable')
    elif len(cs)<3: notes.append('limited class evidence')

    # Distance: gradual similarity (not a cliff); prior is neutral when
    # untried. Published distance record can provide corroboration.
    ds=[]
    if target and target>0:
        for i,r in enumerate(past[:8]):
            old=number(r.get('Distance')); perf=performance(r)
            if old is None or perf is None: continue
            difference=abs(old-target)/target
            similarity=clamp(1-difference/0.45)
            ds.append((0.5+similarity*(perf-0.5),0.85**i*max(0.15,similarity)))
    dr=record_quality(valid_record(horse.get('distance_record')))
    distance_evidence=weighted(ds)
    if distance_evidence is not None and dr is not None: distance_evidence=0.75*distance_evidence+0.25*dr
    elif dr is not None: distance_evidence=dr
    distance_count=len(ds)+(2 if dr is not None else 0)
    distance_score=WEIGHTS['distance']*evidence_blend(distance_evidence,distance_count,strength=3) if target else None
    if distance_score is None: notes.append('distance unavailable')
    elif distance_count<2: notes.append('unproven distance; neutral prior')

    # Going: only like-for-like evidence; unknown is neutral but flagged.
    gs=[]
    if surface:
        for i,r in enumerate(past[:8]):
            perf=performance(r)
            if going_type(r.get('Cond.'))==surface and perf is not None:
                gs.append((perf,0.85**i))
    gr=record_quality(valid_record(horse.get(str(surface)+'_record'))) if surface else None
    going_evidence=weighted(gs)
    if going_evidence is not None and gr is not None: going_evidence=0.75*going_evidence+0.25*gr
    elif gr is not None: going_evidence=gr
    going_count=len(gs)+(2 if gr is not None else 0)
    going_score=WEIGHTS['going']*evidence_blend(going_evidence,going_count,strength=3) if surface else None
    if going_score is None: notes.append('current going unavailable')
    elif going_count<2: notes.append('limited going evidence')

    # Fitness: first/second-up published records when available; otherwise
    # compare performance after historical breaks resembling this layoff.
    days=(rdate-date_value(past[0]['Date'])).days if past else None
    prep=[]
    if days is not None:
        for i,r in enumerate(past[:6]):
            d=date_value(r.get('Date'))
            previous=date_value(past[i+1].get('Date')) if i+1<len(past) else None
            perf=performance(r)
            if d and previous and perf is not None:
                prior_gap=(d-previous).days
                if abs(prior_gap-days)<=max(14,days*0.4): prep.append((perf,0.85**i))
    fitness_evidence=weighted(prep)
    firstup=record_quality(valid_record(horse.get('first_up') or horse.get('first_up_record') or horse.get('firstup_record')))
    secondup=record_quality(valid_record(horse.get('second_up') or horse.get('second_up_record') or horse.get('secondup_record')))
    if days is not None and days>=70 and firstup is not None:
        fitness_evidence=0.6*firstup+0.4*(fitness_evidence if fitness_evidence is not None else NEUTRAL)
    elif days is not None and days<70 and secondup is not None:
        fitness_evidence=0.35*secondup+0.65*(fitness_evidence if fitness_evidence is not None else NEUTRAL)
    # Trials are preparation indicators only; never treat a trial placing as
    # competitive form or as a win at the target distance/going/class.
    recent_trials = [r for r in trials if (rdate-date_value(r.get('Date'))).days <= 45]
    fitness_count=len(prep)+(2 if firstup is not None or secondup is not None else 0)
    if recent_trials:
        notes.append(f'{len(recent_trials)} recent trial(s) recorded (preparation only)')
    fitness=WEIGHTS['fitness']*evidence_blend(fitness_evidence,fitness_count,strength=3) if days is not None else None
    if fitness is None: notes.append('fitness evidence unavailable')
    elif fitness_count==0: notes.append('fitness neutral; no comparable preparation evidence')

    return {'form':form,'class':class_score,'distance':distance_score,
            'going':going_score,'fitness':fitness,'days_since_last':days,
            'evidence_starts':len(past),'trial_starts':len(trials),'form_samples':len(fs),'class_samples':len(cs),
            'distance_samples':distance_count,'going_samples':going_count,
            'fitness_samples':fitness_count,'notes':notes}


def write_csv(path,rows,columns):
    with path.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore')
        writer.writeheader(); writer.writerows(rows)


def staking_rule(gap):
    if gap>=7: return 3,1.60
    if gap>=5: return 2,2.00
    if gap>=3: return 1,3.00
    return 0,None


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--date',required=True)
    ap.add_argument('--input',default='data')
    ap.add_argument('--output',default='reports')
    ap.add_argument('--expected-fields',default='',help='Optional CSV with date,meeting,race,expected_runners; verified against independent racecards')
    args=ap.parse_args()
    race_date=date_value(args.date)
    if not race_date or race_date.isoformat()!=args.date: ap.error('--date must be YYYY-MM-DD')
    folder=Path(args.input)/args.date
    for name in ('runners.csv','past_starts.csv'):
        if not (folder/name).is_file(): ap.error(f'Missing {folder/name}')
    with (folder/'runners.csv').open(encoding='utf-8-sig',newline='') as f: runners=list(csv.DictReader(f))
    with (folder/'past_starts.csv').open(encoding='utf-8-sig',newline='') as f: histories=list(csv.DictReader(f))
    if not runners: ap.error('No runners')
    expected_fields={}
    if args.expected_fields:
        with open(args.expected_fields,encoding='utf-8-sig',newline='') as f:
            for e in csv.DictReader(f):
                count=number(e.get('expected_runners'))
                if count is not None and count>=2:
                    expected_fields[(e.get('date',''),e.get('meeting','').strip().casefold(),str(e.get('race','')).strip())]=int(count)

    histories_by_key=defaultdict(list)
    for h in histories: histories_by_key[tuple(h.get(k,'') for k in KEY)].append(h)
    opponent_index=HistoricalOpponents(histories)
    groups=defaultdict(list)
    for r in runners:
        if date_value(r.get('date'))==race_date:
            groups[(args.date,r['state'],r['meeting'],r['race'])].append(r)
    if not groups: ap.error('No runners for date')
    ranked=[]; races=[]
    for group_key,group in sorted(groups.items(),key=lambda x:(x[0][1],x[0][2],int(number(x[0][3]) or 0))):
        barriers=[number(r.get('barrier')) for r in group]
        barriers=[v for v in barriers if v is not None and v>0]
        max_barrier=max(barriers) if barriers else None
        scored=[]
        expected=expected_fields.get((args.date,group_key[2].strip().casefold(),str(group_key[3])))
        field_incomplete=expected is not None and len(group)<expected
        for r in group:
            key=tuple(r.get(k,'') for k in KEY)
            # Accommodate either date encoding in history/runner records.
            history=histories_by_key[key]
            if not history:
                for date_text in (args.date,race_date.strftime('%d/%m/%Y'),race_date.strftime('%d/%m/%y')):
                    history=histories_by_key[(date_text,r['meeting'],r['race'],r['horse'])]
                    if history: break
            s=score_runner(r,history,opponent_index)
            b=number(r.get('barrier')); w=number(r.get('weight_kg'))
            # Draw is mildly informative only; without course-specific bias
            # avoid treating an inside barrier as a guaranteed advantage.
            draw=clamp(1-(b-1)/max(1,max_barrier-1)) if b is not None and b>0 and max_barrier else None
            draw_component=0.5+0.20*(draw-0.5) if draw is not None else None
            # Compare carried weight to horse's own prior successful weights
            # only when such weights are present in historical CSV.
            successful=[]
            for h in [h for h in historical_rows(history,race_date) if not is_trial(h)][:8]:
                p=past_finish(h.get('Place')); oldw=number(h.get('Weight') or h.get('Wgt'))
                if p and p[0]<=3 and oldw is not None: successful.append(oldw)
            weight_component=clamp(0.5+0.022*(sum(successful)/len(successful)-w)) if successful and w is not None else None
            components=[(v,wt) for v,wt in ((draw_component,0.5),(weight_component,0.5)) if v is not None]
            # Claims are not assumed where the collector has no claim field.
            s['barrier_weight']=WEIGHTS['barrier_weight']*weighted(components) if components else None
            if weight_component is None: s['notes'].append('prior successful weights/claims unverified')
            if draw_component is None: s['notes'].append('barrier evidence unavailable')
            available=[k for k in WEIGHTS if s[k] is not None]
            coverage=sum(WEIGHTS[k] for k in available)
            observed=sum(s[k] for k in available)
            # Confidence is distinct from the rating. It does not create
            # phantom points or penalise a horse for an untried distance.
            confidence=0.35*min(1,s['form_samples']/4)+0.30*min(1,s['class_samples']/4)+0.15*min(1,s['distance_samples']/3)+0.10*min(1,s['going_samples']/3)+0.10*min(1,s['fitness_samples']/2)
            status='PROVISIONAL - SCRATCHINGS UNVERIFIED'
            if coverage<99.999 or s['evidence_starts']<3 or s['form_samples']<3 or s['class_samples']<2 or confidence<0.70:
                status='INSUFFICIENT DATA - DO NOT SELECT'
            if (r.get('scratching_status') or '').strip().lower() in ('scratched','withdrawn'):
                status='SCRATCHED - EXCLUDED'
            result={'date':args.date,'state':r['state'],'meeting':r['meeting'],'race':r['race'],
                    'race_name':r.get('race_name',''),'horse_number':r.get('horse_number',''),
                    'horse':r['horse'],'barrier':r.get('barrier',''),'weight_kg':r.get('weight_kg',''),
                    'race_url':r.get('race_url',''),'scratching_status':r.get('scratching_status','unverified'),
                    'score':round(observed,2),'coverage_points':round(coverage,4),
                    'form_points':round(s['form'],2) if s['form'] is not None else '',
                    'class_points':round(s['class'],2) if s['class'] is not None else '',
                    'distance_points':round(s['distance'],2) if s['distance'] is not None else '',
                    'going_points':round(s['going'],2) if s['going'] is not None else '',
                    'barrier_weight_points':round(s['barrier_weight'],2) if s['barrier_weight'] is not None else '',
                    'fitness_points':round(s['fitness'],2) if s['fitness'] is not None else '',
                    'days_since_last':s['days_since_last'] if s['days_since_last'] is not None else '',
                    'evidence_starts':s['evidence_starts'],'trial_starts':s['trial_starts'],'evidence_confidence':round(confidence,3),
                    'status':status,'notes':'; '.join(s['notes']),'rank':'','gap_to_second':''}
            scored.append(result)
        scored.sort(key=lambda x:(-x['score'],-x['coverage_points'],x['horse']))
        for i,r in enumerate(scored,1): r['rank']=i
        ranked.extend(scored)
        # Require all active runners to be scoreable; no manufactured gap
        # from an incomplete or excluded rival.
        eligible=[r for r in scored if r['status']=='PROVISIONAL - SCRATCHINGS UNVERIFIED']
        if len(eligible)!=len([r for r in scored if r['status']!='SCRATCHED - EXCLUDED']): continue
        if len(eligible)>=2:
            first,second=eligible[:2]
            gap=round(first['score']-second['score'],2)
            first['gap_to_second']=gap
            points,minimum_odds=staking_rule(gap)
            warnings=[]
            if expected is None: warnings.append('FIELD COUNT NOT INDEPENDENTLY VERIFIED')
            if field_incomplete:
                warnings.append(f'INCOMPLETE FIELD: collected {len(group)} of {expected}')
                points,minimum_odds=0,None
            if len(eligible)<=3:
                warnings.append(f'SMALL FIELD: {len(eligible)} active runners; gap needs independent review')
            # Three-runner maiden victories can inflate a form advantage. Flag
            # the actual evidence; do not manipulate six-factor weights or gaps.
            leader_source=next((r for r in group if r['horse']==first['horse']),None)
            if leader_source is not None:
                k=tuple(leader_source.get(c,'') for c in KEY)
                prior=historical_rows(histories_by_key[k],race_date)
                for h in prior[:4]:
                    finish=past_finish(h.get('Place'))
                    if finish and finish[0]==1 and finish[1]<=3 and re.search(r'\b(?:MDN|MAIDEN)\b',str(h.get('Class','')),re.I):
                        warnings.append('LEADER HAS WIN IN THREE-RUNNER MAIDEN: REVIEW GAP')
                        break
            races.append({'points':points,'minimum_win_odds':minimum_odds,'date':first['date'],
                          'state':first['state'],'meeting':first['meeting'],'race':first['race'],
                          'race_name':first['race_name'],'first_horse':first['horse'],
                          'first_score':first['score'],'second_horse':second['horse'],
                          'second_score':second['score'],'gap':gap,'race_url':first['race_url'],
                          'status':'INCOMPLETE FIELD - NO BET' if field_incomplete else 'PROVISIONAL - SCRATCHINGS UNVERIFIED', 'integrity_warnings':'; '.join(warnings), 'collected_runners':len(group), 'expected_runners':expected or ''})
    races.sort(key=lambda r:(-r['gap'],-r['first_score'],r['meeting'],int(number(r['race']) or 0)))
    out=Path(args.output)/args.date; out.mkdir(parents=True,exist_ok=True)
    write_csv(out/'all_runner_scores.csv',ranked,list(ranked[0]))
    cols=['points','minimum_win_odds','date','state','meeting','race','race_name','first_horse','first_score','second_horse','second_score','gap','race_url','status','integrity_warnings','collected_runners','expected_runners']
    write_csv(out/'race_rankings.csv',races,cols)
    write_csv(out/'top_ten_provisional.csv',races[:10],cols)
    write_csv(out/'top_three_provisional.csv',races[:3],cols)
    manifest={'date':args.date,'races_with_runners':len(groups),'runners_scored':len(ranked),
              'races_with_two_eligible_runners':len(races),'provisional_top_ten':len(races[:10]),
              'model':'Strategy 4.1 v10; v9 scoring plus field-integrity audit (NOT back-tested)',
              'weights':WEIGHTS,'scratchings_verified':False,'betting_recommendations':False}
    (out/'scoring_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    lines=[f'# Strategy 4.1 — {args.date}','','**PROVISIONAL ONLY. Scratchings unverified; not betting recommendations.**',
           '',f"Scored {len(ranked)} runners across {len(groups)} races. {len(races)} races eligible.",
           '','| Rank | Meeting | Race | Leader | Score | Second | Score | Gap | Band | Min win odds |',
           '|---:|---|---:|---|---:|---|---:|---:|---|---:|']
    for i,r in enumerate(races[:10],1):
        lines.append(f"| {i} | {r['meeting']} | {r['race']} | {r['first_horse']} | {r['first_score']:.2f} | {r['second_horse']} | {r['second_score']:.2f} | {r['gap']:.2f} | {r['points'] or 'No bet'} | {r['minimum_win_odds'] or '-'} |")
    if not races: lines.append('No eligible two-runner comparisons; no selections.')
    lines+=['','Top ten ranked by gap, not filtered by odds.',
            'Only fully covered races with >=3 competitive historical starts per runner and adequate evidence are ranked.',
            'Trials are preparation evidence only; never counted as competitive races.',
            'Ratings are unvalidated heuristics, not win probabilities.',
            'Opponent ratings, claims and track bias are not inferred from missing data.',
            'Scratchings and late track changes must be verified.']
    (out/'top_three_provisional.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(manifest,indent=2)); print('\n'.join(lines))

if __name__=='__main__': main()
