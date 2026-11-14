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
    report["conclusion"]="credentials_and_fixture_feed_checked" if len(report["checks"])==2 and all(x.get("http_status")==200 and not x.get("api_errors") for x in report["checks"]) else "api_access_issue"
print(json.dumps(report,indent=2,default=str))
open("international_football_api_probe.json","w").write(json.dumps(report,indent=2,default=str))
