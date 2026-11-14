"""Last-12-month outcome report, clearly separated from odds-qualified bets."""
import argparse
import pandas as pd
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--predictions",required=True)
    ap.add_argument("--end",default="2026-11-14")
    args=ap.parse_args()
    d=pd.read_csv(args.predictions,parse_dates=["date"])
    end=pd.Timestamp(args.end)
    start=end-pd.DateOffset(years=1)
    d=d[(d.date>=start)&(d.date<end)]
    print(f"LAST 12 MONTHS: {start.date()} to {(end-pd.Timedelta(days=1)).date()}")
    print(f"Matches with model predictions: {len(d)}")
    for m in ("over25","btts"):
        p=d[f"{m}_p"];result=d[f"{m}_result"]
        print(f"{m}: all outcomes {int(result.sum())}/{len(result)} = {result.mean()*100:.2f}%" if len(d) else f"{m}: no matches")
        # Model-only candidate threshold: at minimum acceptable odds 1.80, 5pp edge
        # would require p >= 1/1.80 + .05. This is NOT a valid odds-qualified selection.
        candidate=d[p>=1/1.8+0.05]
        r=candidate[f"{m}_result"]
        print(f"{m}: hypothetical model-only candidates p>=60.56%: {int(r.sum())}/{len(r)} = {r.mean()*100:.2f}% (NOT verified bets)" if len(r) else f"{m}: no model-only candidates")
    print("Historical prices missing: cannot calculate win rate for actual 2-bookmaker/edge-qualified bets.")
if __name__=="__main__":main()
