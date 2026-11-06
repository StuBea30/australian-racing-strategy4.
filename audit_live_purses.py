
#!/usr/bin/env python3
"""Audit historical prize-money data collected for Strategy 4.1."""

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def read_csv(path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def audit(folder):
    runners = read_csv(folder / "runners.csv")
    history = read_csv(folder / "past_starts.csv")

    class_keys = [
        "Class", "Race Class", "Race Type",
        "Type", "race_class"
    ]

    result = {
        "runners": len(runners),
        "runners_with_today_purse": sum(
            bool(r.get("race_prize_money")) for r in runners
        ),
        "historical_starts": len(history),
        "historical_starts_with_purse": sum(
            bool(r.get("Prize Money AUD")) for r in history
        ),
        "historical_starts_with_state": sum(
            bool(r.get("Historical State")) for r in history
        ),
        "historical_column_names": sorted({
            key for row in history for key in row
        }),
        "historical_class_samples": dict(
            Counter(
                next(
                    (r[k] for k in class_keys if r.get(k)),
                    "(unlabelled)"
                )
                for r in history
            ).most_common(20)
        ),
        "sample_history": [
            {
                k: r.get(k, "")
                for k in (
                    "horse", "Date", "Track", "Place",
                    "Class", "Race Class",
                    "Prize Money AUD", "Historical State"
                )
            }
            for r in history[:10]
        ],
    }

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--output", default="data")
    args = parser.parse_args()

    folder = Path(args.output) / args.date
    folder.mkdir(parents=True, exist_ok=True)

    result = audit(folder)

    (folder / "prize_money_audit.json").write_text(
        json.dumps(result, indent=2),
        encoding="utf-8"
    )

    print(json.dumps(result, indent=2))

    if (
        result["historical_starts"]
        and not result["historical_starts_with_purse"]
    ):
        print("WARNING: No historical race purses collected.")
