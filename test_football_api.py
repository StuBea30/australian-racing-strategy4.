"""Check football-data.org access for Football Strategy 3.0.

Requires the FOOTBALL_DATA_API_KEY environment variable.
Uses only the Python standard library.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE_URL = "https://api.football-data.org/v4"
LEAGUES = {
    "BL1": "Bundesliga",
    "DED": "Eredivisie",
    "ELC": "Championship",
    "SA": "Serie A",
}


def get_json(path, token):
    request = urllib.request.Request(
        BASE_URL + path,
        headers={"X-Auth-Token": token, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            payload = json.load(response)
            remaining = response.headers.get("X-Requests-Available-Minute", "unknown")
            return payload, remaining
    except urllib.error.HTTPError as error:
        detail = error.read(600).decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code}: {detail}") from error


def main():
    token = os.environ.get("FOOTBALL_DATA_API_KEY", "").strip()
    if not token:
        print("ERROR: FOOTBALL_DATA_API_KEY is not configured.")
        return 1

    failures = 0
    for code, name in LEAGUES.items():
        try:
            data, remaining = get_json(f"/competitions/{code}/matches", token)
            matches = data.get("matches", [])
            finished = sum(m.get("status") == "FINISHED" for m in matches)
            upcoming = sum(m.get("status") in {"SCHEDULED", "TIMED"} for m in matches)
            season = data.get("filters", {}).get("season", "current")
            print(f"PASS {name} ({code}): {len(matches)} matches; "
                  f"{finished} finished; {upcoming} upcoming; "
                  f"season={season}; requests remaining/min={remaining}")
            for match in sorted(
                (m for m in matches if m.get("status") in {"SCHEDULED", "TIMED"}),
                key=lambda m: m.get("utcDate", ""),
            )[:2]:
                home = match.get("homeTeam", {}).get("name", "?")
                away = match.get("awayTeam", {}).get("name", "?")
                print(f"  Next: {match.get('utcDate', '?')} | {home} vs {away}")
        except (RuntimeError, urllib.error.URLError, TimeoutError, ValueError) as error:
            failures += 1
            print(f"FAIL {name} ({code}): {error}")
        time.sleep(7)  # Stay comfortably below the free tier's 10 calls/minute.

    print(f"\nResult: {len(LEAGUES) - failures}/{len(LEAGUES)} leagues accessible.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
