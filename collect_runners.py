
#!/usr/bin/env python3
"""Collect runner-level Ladbrokes form for race links produced by collect_racing.py.
Does not score horses or independently verify scratchings.
"""
import argparse
import csv
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; RacingStrategy4/1.0)', 'Accept': 'text/html'}
FIELDS = ['date','state','meeting','race','race_url','race_name','distance_m','race_class','track','weather','horse_number','horse','barrier','form','trainer','jockey','weight_kg','rating','career','distance_record','good_record','soft_record','heavy_record','first_up','second_up','days_since_start','settling_position','comments','scratching_status','past_starts_count']


def clean(node):
    return node.get_text(' ', strip=True) if node else ''


def labelled(node, label):
    for li in node.select('header li'):
        strong = li.find('strong')
        if strong and clean(strong).rstrip(':').casefold() == label.casefold():
            return clean(li).split(':', 1)[-1].strip()
    return ''


def stats(article):
    result = {}
    h = next((h for h in article.select('h5') if clean(h) == 'Stats'), None)
    if not h:
        return result
    grid = h.find_next_sibling('div')
    if not grid:
        return result
    for h6 in grid.select('h6'):
        value = h6.find_next_sibling('span')
        if value:
            result[clean(h6).casefold()] = clean(value)
    return result


def section_text(article, title):
    h = next((h for h in article.select('h5') if clean(h) == title), None)
    if not h:
        return ''
    sibling = h.find_next_sibling('div') or h.find_next_sibling('p')
    return clean(sibling)


def parse_race(html, meta):
    soup = BeautifulSoup(html, 'html.parser')
    header = soup.select_one('section header h1')
    if not header:
        raise ValueError('Race header not found')
    articles = soup.select('article[id^="runner-"]')
    if not articles:
        raise ValueError('No runner articles found')
    heading = header.find_parent('header')
    race_name = clean(heading.select_one('h2'))
    facts = {}
    for li in soup.select('section > ul li'):
        strong = li.find('strong')
        if strong:
            facts[clean(strong).rstrip(':').casefold()] = clean(li).split(':',1)[-1].strip()
    rows = []
    histories = []
    for article in articles:
        ident = article.get('id','')
        number = ident.removeprefix('runner-')
        name_line = clean(article.select_one('header li'))
        match = re.match(r'(.+?)\s*\(\s*(\d+)\s*\)\s*(.*)$', name_line)
        if not match:
            raise ValueError(f'Cannot parse runner: {name_line}')
        horse, barrier, form = match.groups()
        st = stats(article)
        rating = ''
        for p in article.select('p'):
            if clean(p) == 'Rating':
                parent = p.parent
                spans = parent.find_all('span')
                rating = clean(spans[-1]) if spans else ''
                break
        days = ''
        for h in article.select('h5'):
            if clean(h).startswith('Last Starts'):
                found = re.search(r'(\d+)\s+days since last start', clean(h))
                if found: days = found.group(1)
                break
        settling = ''
        for p in article.select('p'):
            if 'Expected Settling Position:' in clean(p):
                settling = clean(p).split(':',1)[-1].strip()
                break
        tables = article.select('table')
        history = []
        for table in tables:
            labels = [clean(c) for c in table.select('thead tr:first-child > *')]
            if 'Place' not in labels or 'Date' not in labels:
                continue
            for tr in table.select('tbody tr'):
                cells = tr.find_all('td', recursive=False)
                if len(cells) != len(labels):
                    continue
                record = dict(zip(labels, (clean(c) for c in cells)))
                record.update({'date':meta['date'],'meeting':meta['meeting'],'race':meta['race'],'horse':horse})
                history.append(record)
        histories.extend(history)
        rows.append({
            'date':meta['date'],'state':meta['state'],'meeting':meta['meeting'],
            'race':meta['race'],'race_url':meta['race_url'],'race_name':race_name,
            'distance_m':re.sub(r'\D','',facts.get('distance','')),
            'race_class':facts.get('class',''),'track':facts.get('track',''),
            'weather':facts.get('weather',''),'horse_number':number,'horse':horse,
            'barrier':barrier,'form':form,'trainer':labelled(article,'Trainer'),
            'jockey':labelled(article,'Jockey'),
            'weight_kg':re.search(r'\d+(?:\.\d+)?',labelled(article,'Weight')).group(0) if re.search(r'\d+(?:\.\d+)?',labelled(article,'Weight')) else '',
            'rating':rating,'career':st.get('career',''),
            'distance_record':st.get('distance',''),'good_record':st.get('good',''),
            'soft_record':st.get('soft',''),'heavy_record':st.get('heavy',''),
            'first_up':st.get('1st up',''),'second_up':st.get('2nd up',''),
            'days_since_start':days,'settling_position':settling,
            'comments':section_text(article,'Comments'),
            'scratching_status':'unverified',
            'past_starts_count':len(history),
        })
    return rows, histories


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date',required=True)
    parser.add_argument('--output',default='data')
    parser.add_argument('--limit',type=int,default=0,help='Optional number of races for initial testing')
    parser.add_argument('--delay',type=float,default=1.0)
    args = parser.parse_args()
    folder = Path(args.output) / args.date
    with (folder/'races.csv').open(newline='',encoding='utf-8') as f:
        races = list(csv.DictReader(f))
    if args.limit:
        races = races[:args.limit]
    all_runners, all_histories, errors = [], [], []
    raw = folder/'sources'/'racecards'
    raw.mkdir(parents=True,exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)
    for i, race in enumerate(races,1):
        try:
            response = session.get(race['race_url'],timeout=30)
            response.raise_for_status()
            runners, histories = parse_race(response.text,race)
            all_runners.extend(runners)
            all_histories.extend(histories)
            (raw/f'race_{i:03d}.html').write_text(response.text,encoding='utf-8')
            print(f"{race['meeting']} R{race['race']}: {len(runners)} runners, {len(histories)} previous starts")
        except (requests.RequestException,ValueError,KeyError) as exc:
            errors.append({'race_url':race.get('race_url'),'error':str(exc)})
            print(f"FAILED {race.get('race_url')}: {exc}")
        if i < len(races):
            time.sleep(max(args.delay,0))
    with (folder/'runners.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS)
        writer.writeheader(); writer.writerows(all_runners)
    history_fields = ['date','meeting','race','horse']
    for h in all_histories:
        for key in h:
            if key not in history_fields: history_fields.append(key)
    with (folder/'past_starts.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=history_fields)
        writer.writeheader(); writer.writerows(all_histories)
    summary={'date':args.date,'races_requested':len(races),'races_collected':len(races)-len(errors),'runners':len(all_runners),'past_starts':len(all_histories),'errors':errors,'scratchings_verified':False,'strategy_scores_generated':False}
    (folder/'runners_manifest.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))
    if errors or not all_runners:
        raise SystemExit(1)

if __name__=='__main__':
    main()
