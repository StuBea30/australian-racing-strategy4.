"""Download and strictly filter public-domain senior international results."""
import io
import pandas as pd
import requests
from pathlib import Path
URL="https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
COMPETITIONS={
"FIFA World Cup","FIFA World Cup qualification",
"UEFA Euro","UEFA Euro qualification","UEFA Nations League",
"Copa América","Copa América qualification",
"African Cup of Nations","African Cup of Nations qualification",
"AFC Asian Cup","AFC Asian Cup qualification",
"CONCACAF Gold Cup","CONCACAF Gold Cup qualification",
"CONCACAF Nations League","CONCACAF Nations League qualification",
"Oceania Nations Cup","Oceania Nations Cup qualification",
}
def main():
    r=requests.get(URL,timeout=90);r.raise_for_status()
    df=pd.read_csv(io.BytesIO(r.content))
    print("Source rows",len(df),"columns",list(df.columns),flush=True)
    required={"date","home_team","away_team","home_score","away_score","tournament","neutral"}
    if required-set(df.columns): raise ValueError("Source schema changed")
    print("Recent competition labels:",sorted(df.loc[df.date>="2020-01-01","tournament"].dropna().unique()),flush=True)
    d=df[df.tournament.isin(COMPETITIONS)].copy()
    d=d[(d.date>="2010-01-01")&(d.date<="2026-11-14")]
    d=d.rename(columns={"home_score":"home_goals","away_score":"away_goals","tournament":"competition"})
    d=d[["date","home_team","away_team","home_goals","away_goals","competition","neutral"]]
    d=d.dropna().drop_duplicates()
    if len(d)<1000: raise RuntimeError(f"Only {len(d)} matches after strict filter; inspect competition labels")
    path=Path("international_football/data/competitive_matches.csv")
    path.parent.mkdir(parents=True,exist_ok=True)
    d.to_csv(path,index=False)
    print("Eligible competitive matches",len(d),"through",d.date.max(),flush=True)
if __name__=="__main__":main()
