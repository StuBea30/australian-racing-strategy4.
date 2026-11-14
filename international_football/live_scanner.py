"""International Strategy 1.0 live *suggestions*, separate from domestic model."""
import json,os,sys
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from model import load,fit,predict
from prepare_data import main as prepare
API="https://api.the-odds-api.com/v4"
# European senior men's national teams only, in UEFA competitive fixtures.
# Excludes friendlies, club football, other confederations and neutral-site finals.
ALLOWED={"soccer_uefa_nations_league","soccer_fifa_world_cup_qualifiers_europe"}
ALIASES={"usa":"United States","united states":"United States","south korea":"South Korea",
         "korea republic":"South Korea","ivory coast":"Ivory Coast",
         "cote d ivoire":"Ivory Coast","czechia":"Czech Republic",
         "iran":"Iran","turkiye":"Turkey"}
def norm(s):
    import unicodedata,re
    s=unicodedata.normalize("NFKD",s).encode("ascii","ignore").decode().lower()
    s=re.sub(r"[^a-z0-9]+"," ",s).strip()
    return " ".join(s.split())
def team_key(s): return norm(ALIASES.get(norm(s),s))
def markets(event):
    found={}
    for b in event.get("bookmakers",[]):
        for market in b.get("markets",[]):
            key=market.get("key")
            for o in market.get("outcomes",[]):
                if key=="totals" and o.get("name","").lower()=="over" and o.get("point")==2.5: name="over25"
                elif key=="totals" and o.get("name","").lower()=="under" and o.get("point")==2.5: name="under25"
                else: continue
                try: odds=float(o["price"])
                except (ValueError,TypeError,KeyError): continue
                if odds<=1:continue
                found.setdefault(name,[]).append((b.get("key") or b.get("title"),b.get("title",""),odds))
    return found
def main():
    now=datetime.now(timezone.utc)
    from datetime import date
    today=date.fromisoformat(os.environ["REPORT_DATE"]) if os.getenv("REPORT_DATE") else now.astimezone(ZoneInfo("Europe/London")).date()
    preview=bool(os.getenv("REPORT_DATE"))
    report={"scope":"European senior mens national teams - UEFA Nations League and European World Cup qualifying", "date_uk":str(today),"generated_utc":now.isoformat(),"status":"incomplete",
            "qualifying":[],"fixtures":[],"warnings":[],"events_checked":0,"requests":0,"preview":preview}
    def save():
        Path("international_football_live.json").write_text(json.dumps(report,indent=2))
    key=os.getenv("ODDS_API_KEY")
    if not key:
        report["warnings"].append("ODDS_API_KEY missing");save();return
    try:
        # A fresh results feed may lag behind the current international window.
        prepare()
        d=load("international_football/data/competitive_matches.csv")
        model=fit(d,now.replace(tzinfo=None))
        team_map={team_key(t):t for t in model[0]}
        sports=requests.get(API+"/sports",params={"apiKey":key},timeout=30)
        sports.raise_for_status()
        active={s["key"] for s in sports.json() if s.get("active") and s["key"] in ALLOWED}
        if not active:
            report["status"]="no_competitions_available"
            save();return
        candidates=[]; incomplete=False
        for sport in sorted(active):
            # Two separate markets per competition; avoid unnecessary requests if budget tight.
            if report["requests"]>=10:
                report["warnings"].append("10-request budget reached; coverage incomplete")
                incomplete=True;break
            # The Odds API may reject combined market requests for some sports.
            # Try each market independently, preserving per-market errors and coverage.
            raw_events={}
            unsupported_markets=[]
            for mk in ("totals",):
                if report["requests"]>=10:
                    report["warnings"].append("10-request budget reached; coverage incomplete")
                    incomplete=True;break
                response=requests.get(API+f"/sports/{sport}/odds",params={
                    "apiKey":key,"regions":"uk","markets":mk,"oddsFormat":"decimal"},timeout=30)
                report["requests"]+=1
                if not response.ok:
                    try:
                        error_code=response.json().get("error_code")
                    except (ValueError,TypeError):
                        error_code=None
                    if response.status_code==422 and error_code=="INVALID_MARKET":
                        unsupported_markets.append(mk)
                        report.setdefault("unsupported_markets",[]).append(f"{sport}: {mk}")
                        print(f"{sport}: {mk} unavailable through odds provider; other market remains eligible")
                        continue
                    report["warnings"].append(f"{sport} {mk}: HTTP {response.status_code} — {response.text[:220]}")
                    incomplete=True;continue
                for item in response.json():
                    target=raw_events.setdefault(item["id"],{**item,"bookmakers":[]})
                    for book in item.get("bookmakers",[]):
                        existing=next((x for x in target["bookmakers"] if x.get("key")==book.get("key")),None)
                        if existing:
                            existing["markets"].extend(book.get("markets",[]))
                        else:
                            target["bookmakers"].append({**book,"markets":list(book.get("markets",[]))})
            if not raw_events and not unsupported_markets:
                incomplete=True
            for e in raw_events.values():
                kick=datetime.fromisoformat(e["commence_time"].replace("Z","+00:00"))
                if not (kick>now and kick.astimezone(ZoneInfo("Europe/London")).date()==today):continue
                report["events_checked"]+=1
                h=team_map.get(team_key(e["home_team"]));a=team_map.get(team_key(e["away_team"]))
                fixture={"competition":sport,"home":e["home_team"],"away":e["away_team"],
                         "kickoff_utc":e["commence_time"],"markets":{}}
                report["fixtures"].append(fixture)
                if not h or not a:
                    report["warnings"].append(f"Unmatched teams: {e['home_team']} v {e['away_team']}")
                    fixture["status"]="unmatched_teams"
                    incomplete=True;continue
                probs=predict(model,h,a,False)
                if probs is None:
                    fixture["status"]="model_unavailable"
                    incomplete=True;continue
                available=markets(e)
                # Strategy 1.1: Under 2.5 uses a conservative provisional calibration.\n                # 0.85 multiplier is a research haircut informed by historical overconfidence,\n                # NOT a fitted/validated calibration curve or proven betting advantage.
                for market in ("over25","under25"):
                    offers=available.get(market,[])
                    unique={b[0] for b in offers}
                    raw_p=(1-probs["over25"]) if market=="under25" else probs["over25"]\n                    p_model=0.85*raw_p if market=="under25" else raw_p
                    if p_model is None:
                        # P(Over 1.5) requires the total-goals Poisson CDF, not
                        # a transformation of P(Over 2.5). Never invent it.
                        fixture["markets"][market]={"status":"model_not_implemented",
                            "bookmakers":[{"name":name,"odds":odds} for _,name,odds in sorted(offers,key=lambda x:-x[2])]}
                        continue
                    detail={"model_probability":round(p_model,4),\n                            "raw_model_probability":round(raw_p,4),\n                            "calibration":"provisional_under25_x0.85_not_validated" if market=="under25" else "none",
                            "bookmakers":[{"name":name,"odds":odds} for _,name,odds in sorted(offers,key=lambda x:-x[2])],
                            "bookmaker_count":len(unique)}
                    fixture["markets"][market]=detail
                    if not offers:
                        detail["status"]="no_prices"
                        continue
                    best=max(offers,key=lambda x:x[2])
                    odds=best[2];p=p_model;edge=p-1/odds
                    detail.update({"best_odds":odds,"best_bookmaker":best[1],
                                   "edge":round(edge,4),"ev":round(p*odds-1,4)})
                    if len(unique)<2: detail["status"]="fewer_than_two_bookmakers"
                    elif odds<1.8: detail["status"]="odds_below_1_80"
                    elif edge<0.05: detail["status"]="edge_below_5pp"
                    elif market=="under25":
                        detail["status"]="research_candidate_not_validated"
                    else:
                        detail["status"]="qualifies"
                        candidates.append({"competition":sport,"home":e["home_team"],"away":e["away_team"],
                            "kickoff_utc":e["commence_time"],"market":market,"odds":odds,
                            "bookmaker":best[1],"model_probability":round(p,4),
                            "edge":round(edge,4),"ev":round(p*odds-1,4),"stake_gbp":5})
        candidates.sort(key=lambda x:x["ev"],reverse=True)
        selected=[];seen=set()
        for c in candidates:
            fixture=(c["competition"],c["home"],c["away"])
            if fixture in seen:continue
            selected.append(c);seen.add(fixture)
            if len(selected)==3:break
        report["qualifying"]=selected\n        report["strategy"]="1.1: over25 odds>=1.80 edge>=5pp; under25 odds>=2.00 edge>=8pp with provisional 0.85 probability haircut; two bookmakers; max 3 combined"
        report["status"]="incomplete" if incomplete else "checked"
    except Exception as e:
        report["warnings"].append(f"Scan failed: {type(e).__name__}: {e}")
    save()
    print(json.dumps(report,indent=2))
    # Send only genuine, fully checked qualifying selections; don't send an
    # unverified no-bet claim. A partial scan can still show verified bets.
    if not preview and report["qualifying"] and os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        lines=[f"🇪🇺 EUROPEAN INTERNATIONAL FOOTBALL 1.0 — {today:%d %b %Y}",
               "Separate from domestic challenge | suggestions only",\n               "Over 2.5: >=1.80, >=5pp edge | Under 2.5: >=2.00, >=8pp edge (provisional calibrated estimate)"]
        for i,c in enumerate(report["qualifying"],1):
            lines.extend(["",f"{i}. {c['home']} v {c['away']}",
                          f"{c['market'].upper()} | {c['odds']:.2f} ({c['bookmaker']})",
                          f"Model {c['model_probability']:.1%} | Edge +{c['edge']:.1%} | £5"])
        if report["status"]=="incomplete":lines.append("WARNING: other fixtures not fully checked")
        resp=requests.post(f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}/sendMessage",
            json={"chat_id":os.environ["TELEGRAM_CHAT_ID"],"text":"\n".join(lines)},timeout=30)
        resp.raise_for_status()
    elif report["status"]=="incomplete":
        print("No Telegram: scan incomplete")
if __name__=="__main__":main()
