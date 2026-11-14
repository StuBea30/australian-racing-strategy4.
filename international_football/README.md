# International Football Strategy 1.0 — research only

This is a **separate, inactive** model for **senior men's competitive international matches**, restricted to **Over 2.5 goals** and **BTTS Yes**. It does not change existing football/racing workflows, send Telegram messages or place bets.

## Data required
Supply a **curated** historical CSV with columns:
`date,home_team,away_team,home_goals,away_goals,competition,neutral`.

**Important:** The input must be vetted to exclude friendlies, youth and women's matches. The script cannot verify competition eligibility from labels alone. Neutral should be true/false. Do not feed the domestic league data into this model.

## Run
```bash
pip install pandas numpy scipy
python international_football/model.py --matches /path/to/competitive_internationals.csv
```
Outputs `international_football_results/predictions.csv` and `calibration.csv`.

## Method
Independent Poisson goal model, team attack/defence strengths, neutral-venue handling, 365-day exponential half-life and regularisation. Year-by-year forward-only holdout: each year's predictions use matches from previous years only. This is **not** yet Dixon–Coles, and not an odds-based profitability backtest.

## Promotion criteria
Before enabling live alerts, obtain licensed/verified competitive international fixtures and **historical bookmaker odds**; validate probabilities and actual net ROI out of sample. Apply two-bookmaker confirmation, odds >=1.80, model edge >=5 percentage points, £5 stake, maximum three distinct fixtures daily. Avoid assuming a profitable edge without that test.
