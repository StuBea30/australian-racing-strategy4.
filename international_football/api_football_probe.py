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
    odds_checks=[c for c in report["checks"] if c.get("endpoint") in ("/odds","/odds/bets")]
    report["conclusion"]="odds_checked" if odds_checks and all(c.get("http_status")==200 and not c.get("api_errors") for c in odds_checks) else "odds_limited_or_unavailable"
print(json.dumps(report,indent=2,default=str))
open("international_football_api_probe.json","w").write(json.dumps(report,indent=2,default=str))
