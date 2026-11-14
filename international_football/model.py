"""Research-only international football baseline. Input CSV columns:
date,home_team,away_team,home_goals,away_goals,competition,neutral
Only use independently curated senior men's competitive match data.
"""
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson
from scipy.special import gammaln

HALF_LIFE=365
RIDGE=1.5
def load(path):
    d=pd.read_csv(path,parse_dates=["date"])
    required={"date","home_team","away_team","home_goals","away_goals","competition","neutral"}
    if required-set(d.columns): raise ValueError(f"Missing columns: {required-set(d.columns)}")
    if d.empty: raise ValueError("No matches")
    d["neutral"]=d.neutral.astype(str).str.lower().isin(["true","1","yes"])
    d=d.dropna(subset=list(required)).sort_values("date")
    d=d[(d.home_goals>=0)&(d.away_goals>=0)]
    return d
def fit(d,cutoff):
    hist=d[d.date<cutoff]
    if len(hist)<150: raise ValueError("Need at least 150 earlier matches")
    teams=sorted(set(hist.home_team)|set(hist.away_team))
    ix={t:i for i,t in enumerate(teams)}
    n=len(teams)
    h=hist.home_team.map(ix).to_numpy();a=hist.away_team.map(ix).to_numpy()
    hg=hist.home_goals.to_numpy(float);ag=hist.away_goals.to_numpy(float)
    neutral=hist.neutral.to_numpy(bool)
    days=(pd.Timestamp(cutoff)-hist.date).dt.days.to_numpy()
    w=np.exp(-np.log(2)*days/HALF_LIFE)
    def unpack(x):
        return x[:n]-x[:n].mean(),x[n:2*n]-x[n:2*n].mean(),x[-2],x[-1]
    # Analytic gradient avoids finite differences over hundreds of parameters.
    def loss_grad(x):
        attack,defence,base,adv=unpack(x)
        elam=base+attack[h]-defence[a]+adv*(~neutral)
        emu=base+attack[a]-defence[h]
        lam=np.exp(elam);mu=np.exp(emu)
        loss=-np.dot(w,hg*elam-lam-gammaln(hg+1)+ag*emu-mu-gammaln(ag+1))
        loss+=RIDGE*np.sum(x[:2*n]**2)
        eh=w*(lam-hg);ea=w*(mu-ag)
        gatt=np.bincount(h,weights=eh,minlength=n)+np.bincount(a,weights=ea,minlength=n)
        gdef=-np.bincount(a,weights=eh,minlength=n)-np.bincount(h,weights=ea,minlength=n)
        gatt-=gatt.mean();gdef-=gdef.mean()
        g=np.r_[gatt+2*RIDGE*x[:n],gdef+2*RIDGE*x[n:2*n],
                 eh.sum()+ea.sum(),eh[~neutral].sum()]
        return float(loss),g
    result=minimize(loss_grad,np.r_[np.zeros(2*n),np.log(1.2),0.15],
                    jac=True,method="L-BFGS-B",bounds=[(-2.5,2.5)]*(2*n)+[(-1.5,1.5),(-1.0,1.0)],
                    options={"maxiter":1200,"maxfun":1500,"ftol":1e-9})
    if not result.success: raise RuntimeError(str(result.message))
    return ix,unpack(result.x)
def predict(model,home,away,neutral):
    ix,(att,defence,base,adv)=model
    if home not in ix or away not in ix: return None
    h=ix[home];a=ix[away]
    lam=np.exp(base+att[h]-defence[a]+(0 if neutral else adv))
    mu=np.exp(base+att[a]-defence[h])
    return {"over25":float(1-poisson.cdf(2,lam+mu)),
            "btts":float((1-np.exp(-lam))*(1-np.exp(-mu)))}
def backtest(d,first_year=2023):
    rows=[]
    for year in range(first_year,int(d.date.max().year)+1):
        cutoff=pd.Timestamp(f"{year}-01-01")
        if (d.date<cutoff).sum()<150: continue
        model=fit(d,cutoff)
        test=d[(d.date>=cutoff)&(d.date<pd.Timestamp(f"{year+1}-01-01"))]
        for m in test.itertuples():
            p=predict(model,m.home_team,m.away_team,m.neutral)
            if p is None: continue
            rows.append({"date":m.date,"competition":m.competition,"home":m.home_team,"away":m.away_team,
                "over25_p":p["over25"],"btts_p":p["btts"],
                "over25_result":int(m.home_goals+m.away_goals>=3),
                "btts_result":int(m.home_goals>0 and m.away_goals>0)})
    return pd.DataFrame(rows)
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--matches",required=True)
    parser.add_argument("--out",default="international_football_results")
    args=parser.parse_args()
    d=load(args.matches)
    pred=backtest(d)
    if pred.empty: raise SystemExit("No out-of-time predictions; provide more historical data")
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    pred.to_csv(out/"predictions.csv",index=False)
    scores=[]
    for market in ("over25","btts"):
        p=pred[f"{market}_p"].to_numpy();y=pred[f"{market}_result"].to_numpy()
        scores.append({"market":market,"n":len(y),"brier":float(np.mean((p-y)**2)),
            "predicted_rate":float(np.mean(p)),"actual_rate":float(np.mean(y))})
    pd.DataFrame(scores).to_csv(out/"calibration.csv",index=False)
    print(pd.DataFrame(scores).to_string(index=False))
    print("Research only: no bookmaker odds, ROI, Telegram alerts or betting.")
if __name__=="__main__":main()
