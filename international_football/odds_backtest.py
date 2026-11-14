"""Evaluate historical international predictions using real timestamped bookmaker quotes.

Quotes CSV columns:
date,home,away,market,bookmaker,decimal_odds,observed_utc,kickoff_utc
market: over25 or btts. Date YYYY-MM-DD. One row per bookmaker quote.
No synthetic odds. No bets when prices or timestamps are missing.
"""
import argparse
from pathlib import Path
import pandas as pd
import numpy as np

def evaluate(predictions,quotes,cutoff_hours=2,stake=5.0):
    p=pd.read_csv(predictions)
    q=pd.read_csv(quotes)
    required={"date","home","away","market","bookmaker","decimal_odds","observed_utc","kickoff_utc"}
    if required-set(q): raise ValueError(f"Missing odds fields: {sorted(required-set(q))}")
    for df in (p,q):
        df["date"]=pd.to_datetime(df["date"],utc=True).dt.strftime("%Y-%m-%d")
        for col in ("home","away"):
            df[col]=df[col].astype(str).str.strip().str.casefold()
    q["observed_utc"]=pd.to_datetime(q.observed_utc,utc=True,errors="coerce")
    q["kickoff_utc"]=pd.to_datetime(q.kickoff_utc,utc=True,errors="coerce")
    q["decimal_odds"]=pd.to_numeric(q.decimal_odds,errors="coerce")
    q=q[q.market.isin(["over25","btts"]) & q.decimal_odds.ge(1.01)]
    q=q[q.observed_utc.notna() & q.kickoff_utc.notna()]
    # A reproducible pre-match decision point: latest quotes at least 2h before kickoff,
    # and no more than 24h old at the decision time.
    decision=q.kickoff_utc-pd.Timedelta(hours=cutoff_hours)
    q=q[(q.observed_utc<=decision)&(q.observed_utc>=decision-pd.Timedelta(hours=24))]
    q=q.sort_values("observed_utc").drop_duplicates(
        ["date","home","away","market","bookmaker"],keep="last")
    if q.empty: raise ValueError("No valid pre-match quotes")
    prices=q.groupby(["date","home","away","market"]).agg(
        bookmakers=("bookmaker","nunique"),best_odds=("decimal_odds","max")).reset_index()
    prices=prices[prices.bookmakers>=2]
    long=pd.concat([
        p[["date","home","away",f"{m}_p",f"{m}_result"]].rename(
            columns={f"{m}_p":"probability",f"{m}_result":"result"}).assign(market=m)
        for m in ("over25","btts")
    ],ignore_index=True)
    joined=long.merge(prices,on=["date","home","away","market"],how="inner",validate="one_to_one")
    joined["edge"]=joined.probability-1/joined.best_odds
    eligible=joined[(joined.best_odds>=1.80)&(joined.edge>=0.05)].copy()
    eligible["ev_estimate"]=eligible.probability*eligible.best_odds-1
    # At most one selection per fixture; strongest estimated EV first.
    eligible=eligible.sort_values(["date","ev_estimate"],ascending=[True,False])
    eligible=eligible.drop_duplicates(["date","home","away"],keep="first")
    eligible=eligible.groupby("date",group_keys=False).head(3).copy()
    eligible["stake"]=stake
    eligible["profit"]=np.where(eligible.result.eq(1),stake*(eligible.best_odds-1),-stake)
    eligible=eligible.sort_values("date")
    eligible["cumulative_profit"]=eligible.profit.cumsum()
    summary=[]
    for market,g in [("overall",eligible),*[(m,eligible[eligible.market.eq(m)]) for m in ("over25","btts")]]:
        total=g.stake.sum()
        summary.append({"market":market,"bets":len(g),"staked_gbp":round(float(total),2),
            "profit_gbp":round(float(g.profit.sum()),2),
            "roi_pct":round(float(g.profit.sum()/total*100),2) if total else None,
            "win_rate_pct":round(float(g.result.mean()*100),2) if len(g) else None})
    return eligible,pd.DataFrame(summary),len(joined)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--predictions",required=True)
    ap.add_argument("--odds",required=True)
    ap.add_argument("--out",default="international_football_results")
    args=ap.parse_args()
    bets,summary,matched=evaluate(args.predictions,args.odds)
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    bets.to_csv(out/"historical_bets.csv",index=False)
    summary.to_csv(out/"odds_roi_summary.csv",index=False)
    print(f"Matches with two-bookmaker quotes: {matched}")
    print(summary.to_string(index=False))
    if matched==0: raise SystemExit("No matched historical prices: no profitability conclusion")
if __name__=="__main__":main()
