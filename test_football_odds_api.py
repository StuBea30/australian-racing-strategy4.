
import os
import requests

API_KEY = os.environ["ODDS_API_KEY"]

LEAGUES = {
    "Bundesliga": "soccer_germany_bundesliga",
    "Eredivisie": "soccer_netherlands_eredivisie",
    "Championship": "soccer_efl_champ",
    "Serie A": "soccer_italy_serie_a",
}

BASE = "https://api.the-odds-api.com/v4"

def main():
    response = requests.get(
        f"{BASE}/sports",
        params={"apiKey": API_KEY},
        timeout=30,
    )
    response.raise_for_status()
    available = {sport["key"] for sport in response.json()}

    print("FOOTBALL ODDS API TEST")
    print("Remaining credits:",
          response.headers.get("x-requests-remaining", "unknown"))

    for name, key in LEAGUES.items():
        print(f"{name}: {'AVAILABLE' if key in available else 'NOT LISTED'}")

    # One small odds request to test actual bookmaker coverage.
    league = next(
        ((name, key) for name, key in LEAGUES.items() if key in available),
        None,
    )

    if league:
        name, key = league
        response = requests.get(
            f"{BASE}/sports/{key}/odds",
            params={
                "apiKey": API_KEY,
                "regions": "uk",
                "markets": "h2h",
                "oddsFormat": "decimal",
            },
            timeout=30,
        )
        response.raise_for_status()
        fixtures = response.json()
        print(f"{name}: {len(fixtures)} fixtures with odds")
        for fixture in fixtures[:3]:
            print(
                fixture["home_team"], "v",
                fixture["away_team"],
                "- bookmakers:",
                len(fixture.get("bookmakers", [])),
            )
        print("Credits remaining:",
              response.headers.get("x-requests-remaining", "unknown"))

if __name__ == "__main__":
    main()
