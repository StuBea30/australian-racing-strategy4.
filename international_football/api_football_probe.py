"""Read-only API-Football free-plan odds availability probe. Never prints credentials."""
import json,os,requests
BASE="https://v3.football.api-sports.io"
key=os.getenv("API_FOOTBALL_KEY")
report={"provider":"API-Football","key_configured":bool(key),"checks":[],"conclusion":"unverified"}
if key:
    headers={"x-apisports-key":key}
    for endpoint,params in [
        ("/status",{}),
        ("/fixtures",{"date":__import__("datetime").datetime.now(__import__("zoneinfo").ZoneInfo("Europe/London")).strftime("%Y-%m-%d"),"timezone":"Europe/London"}),
    ]:
        try:
            r=requests.get(BASE+endpoint,headers=headers,params=params,timeout=25)
            body=r.json()
            item={"endpoint":endpoint,"http_status":r.status_code,
                  "api_errors":body.get("errors"),"results":body.get("results")}
            if endpoint=="/status":
                item["account_requests"]=body.get("response",{}).get("requests")
            if endpoint=="/fixtures":
                fixtures=body.get("response",[])
                intl=[f for f in fixtures if f.get("league",{}).get("type")=="Cup" and any(t in (f.get("league",{}).get("name","").lower()) for t in ("world cup","nations league","euro","africa cup","asian cup","gold cup","copa america"))]
                item["possible_international_fixtures"]=[{"fixture_id":f["fixture"]["id"],"competition":f["league"]["name"],"home":f["teams"]["home"]["name"],"away":f["teams"]["away"]["name"]} for f in intl[:5]]
            report["checks"].append(item)
            if r.status_code!=200 or body.get("errors"):break
        except Exception as exc:
            report["checks"].append({"endpoint":endpoint,"error":str(exc)});break
    # Examine pre-match betting catalogues and a small, bounded sample of future odds.
    # Do not request additional pages: this is a cost-controlled diagnostic only.
    if len(report["checks"])==2 and all(x.get("http_status")==200 and not x.get("api_errors") for x in report["checks"]):
        from datetime import datetime,timedelta
        from zoneinfo import ZoneInfo
        local=datetime.now(ZoneInfo("Europe/London"))
        for endpoint,params in [
            ("/odds/bets",{}),
            ("/odds",{"date":(local+timedelta(days=1)).strftime("%Y-%m-%d"),"page":1}),
            ("/odds",{"date":(local+timedelta(days=2)).strftime("%Y-%m-%d"),"page":1})
        ]:
            try:
                r=requests.get(BASE+endpoint,headers=headers,params=params,timeout=25)
                body=r.json()
                check={"endpoint":endpoint,"params":params,"http_status":r.status_code,
                       "api_errors":body.get("errors"),"results":body.get("results"),
                       "paging":body.get("paging")}
                rows=body.get("response",[])
                if endpoint=="/odds/bets":
                    check["markets_matching"]=[{"id":x.get("id"),"name":x.get("name")} for x in rows if any(n in (x.get("name") or "").lower() for n in ("both teams","goals over","over/under"))][:20]
                else:
                    check["sample"]=[]
                    for x in rows[:10]:
                        names=[{"bookmaker":b.get("name"),"markets":[z.get("name") for z in b.get("bets",[]) if any(n in (z.get("name") or "").lower() for n in ("both teams","goals over","over/under"))]} for b in x.get("bookmakers",[])]
                        check["sample"].append({"fixture_id":x.get("fixture",{}).get("id"),"league":x.get("league",{}).get("name"),"bookmakers":names[:5]})
                report["checks"].append(check)
                if r.status_code!=200 or body.get("errors"):
                    print(f"{endpoint}: HTTP {r.status_code}, errors={body.get('errors')}")
            except Exception as exc:
                report["checks"].append({"endpoint":endpoint,"error":str(exc)})
    # Check free-plan odds coverage by competition on TODAY only, not a paid future date.
    # One page per query, with an explicit three-call cap to avoid burning quota.
    try:
        today=local.strftime("%Y-%m-%d")
        res=requests.get(BASE+"/leagues",headers=headers,params={"current":"true"},timeout=25)
        payload=res.json()
        leagues=payload.get("response",[]) if not payload.get("errors") else []
        names=("UEFA Nations League","World Cup","Euro Championship","CONCACAF Nations League",
               "Copa America","Africa Cup of Nations","Asian Cup")
        matches=[]
        for x in leagues:
            league=x.get("league",{})
            name=league.get("name") or ""
            typ=league.get("type")
            if typ=="Cup" and any(q.lower() in name.lower() for q in names):
                matches.append({"id":league.get("id"),"name":name,"type":typ,"season":next((p.get("year") for p in x.get("seasons",[]) if p.get("current")),None)})
        report["checks"].append({"endpoint":"/leagues","http_status":res.status_code,
               "api_errors":payload.get("errors"),"matched_competitions":matches[:20]})
        # International competitions may be between seasons; only inspect active feeds.
        # Prefer senior men's qualifying competitions, and exclude women's, youth and club tournaments.
        eligible=[m for m in matches if m["season"] is not None and not any(t in m["name"].lower() for t in ("women","femenina","u17","u18","u19","u20","u21","u23","club","qualification - women"))]
        preferred=sorted(eligible,key=lambda m:(0 if "world cup - qualification" in m["name"].lower() else 1,m["name"]))
        for league in preferred[:3]:
            r=requests.get(BASE+"/odds",headers=headers,
                 params={"league":league["id"],"season":league["season"],"date":today,"page":1},timeout=25)
            body=r.json()
            rows=body.get("response") or []
            examples=[]
            for x in rows[:5]:
                offers=[]
                for b in x.get("bookmakers",[]):
                    relevant=[z for z in b.get("bets",[]) if z.get("id") in (5,8)]
                    if relevant:
                        offers.append({"bookmaker":b.get("name"),
                         "markets":[{"id":m.get("id"),"name":m.get("name"),
                          "sample_values":[{"value":v.get("value"),"odd":v.get("odd")} for v in m.get("values",[]) if v.get("value") in ("Over 2.5","Yes")][:2]}
                         for m in relevant]})
                examples.append({"fixture_id":x.get("fixture",{}).get("id"),
                                 "bookmakers_with_target_markets":offers[:5]})
            report["checks"].append({"endpoint":"/odds","target_competition":league,
              "date":today,"http_status":r.status_code,"api_errors":body.get("errors"),
              "results":body.get("results"),"paging":body.get("paging"),
              "sample":examples})
    except Exception as e:
        report["checks"].append({"endpoint":"international_coverage","error":str(e)})
    odds_checks=[c for c in report["checks"] if c.get("endpoint") in ("/odds","/odds/bets")]
    report["conclusion"]="odds_checked" if odds_checks and all(c.get("http_status")==200 and not c.get("api_errors") for c in odds_checks) else "odds_limited_or_unavailable"
print(json.dumps(report,indent=2,default=str))
open("international_football_api_probe.json","w").write(json.dumps(report,indent=2,default=str))
