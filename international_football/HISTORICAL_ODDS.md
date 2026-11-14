# Historical odds ROI backtest

Run after the probability backtest, with **real, timestamped bookmaker quotes**:

```bash
python international_football/odds_backtest.py \
  --predictions international_football_results/predictions.csv \
  --odds /path/to/licensed_historical_odds.csv
```

The quotes CSV must contain:
`date,home,away,market,bookmaker,decimal_odds,observed_utc,kickoff_utc`

Use market `over25` or `btts`. Times must be valid UTC timestamps. Dates and team labels must match the predictions. Provide one row per observed bookmaker quote. This is a strict join; no fuzzy guesses.

Rules: quotes must be recorded at least **2 hours before kickoff** and within the preceding **24 hours**; latest eligible quote per bookmaker; at least **two distinct bookmakers**; odds >=1.80; estimated edge >=5 percentage points; £5 stake; maximum one bet per fixture and three per day. Profit uses the best eligible recorded price, with no commissions.

**Important limitations:** Prediction model was calibrated using historical outcomes, not prices; this is a retrospective simulation, not independently verified executable prices. Source coverage, bookmaker restrictions, timestamp validity, event identity and licensing must be audited. The public results CSV alone has no odds. Do not claim ROI until a real quotes dataset has been ingested. A robust strategy needs an untouched holdout and bookmaker-price sensitivity checks.
