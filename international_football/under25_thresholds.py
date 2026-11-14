"""Walk-forward model-only calibration for Over/Under 2.5; not a betting ROI study."""
import argparse
import pandas as pd
import numpy as np

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--predictions",required=True)
    ap.add_argument("--out",default="international_football_results/goal_thresholds.csv")
    args=ap.parse_args()
    df=pd.read_csv(args.predictions)
    rows=[]
    for market in ("over25","under25"):
        p=df[f"{market}_p"].astype(float)
        y=df[f"{market}_result"].astype(int)
        for threshold in (0.50,0.55,0.60,0.65,0.70,0.75):
            selected=p>=threshold
            n=int(selected.sum())
            rows.append({"market":market,"minimum_model_probability":threshold,
                "matches":n,"wins":int(y[selected].sum()),
                "win_rate_pct":round(float(y[selected].mean()*100),2) if n else None,
                "mean_model_probability_pct":round(float(p[selected].mean()*100),2) if n else None,
                "brier_score":round(float(np.mean((p[selected]-y[selected])**2)),4) if n else None,
                "break_even_odds_at_observed_win_rate":round(float(1/y[selected].mean()),3) if n and y[selected].mean()>0 else None,
                "note":"No historical bookmaker odds: break-even reference only, NOT ROI"})
    out=pd.DataFrame(rows)
    out.to_csv(args.out,index=False)
    print(out.to_string(index=False))
    print("No historic odds, no two-bookmaker verification, no profitability claim.")

if __name__=="__main__": main()
