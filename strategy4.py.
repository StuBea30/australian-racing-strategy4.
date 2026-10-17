
#!/usr/bin/env python3
"""
Australian Racing Strategy 4.0
Persistent scoring engine and top-three gap report.

Requires Python 3.11+.
Uses Python's standard library only.
"""

import argparse
import csv
import datetime as dt
import pathlib
import sqlite3

WEIGHTS = {
    "form": 30,
    "class": 25,
    "distance": 15,
    "going": 15,
    "barrier_weight": 10,
    "fitness": 5,
}

STATES_ALL = {"VIC", "NSW", "SA"}
STATES_METRO = {"QLD", "WA", "TAS", "ACT"}

FIELDS = [
    "date", "state", "metro", "meeting",
    "race", "race_time_local", "horse",
    "scratched", "form", "class",
    "distance", "going", "barrier_weight",
    "fitness", "notes", "source"
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS runners (
    date TEXT NOT NULL,
    state TEXT NOT NULL,
    meeting TEXT NOT NULL,
    race INTEGER NOT NULL,
    race_time_local TEXT,
    horse TEXT NOT NULL,
    scratched INTEGER NOT NULL,
    form REAL,
    class REAL,
    distance REAL,
    going REAL,
    barrier_weight REAL,
    fitness REAL,
    notes TEXT,
    source TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (date, state, meeting, race, horse)
);
"""


def connect(database):
    connection = sqlite3.connect(database)
    connection.execute(SCHEMA)
    return connection


def eligible(state, metro):
    state = state.strip().upper()

    if state in STATES_ALL:
        return True

    return state in STATES_METRO and metro


def is_true(value):
    return str(value).strip().lower() in {
        "1", "yes", "true", "metro", "scratched"
    }


def import_runners(connection, filename):
    count = 0

    with open(filename, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        for row in reader:
            state = row["state"].strip().upper()
            metro = is_true(row.get("metro", ""))

            if not eligible(state, metro):
                continue

            scores = {}

            for factor, maximum in WEIGHTS.items():
                raw = str(row.get(factor, "") or "").strip()

                if raw:
                    value = float(raw)

                    if not 0 <= value <= maximum:
                        raise ValueError(
                            f"{row['horse']}: {factor} must "
                            f"be between 0 and {maximum}"
                        )

                    scores[factor] = value
                else:
                    scores[factor] = None

            values = [
                row["date"].strip(),
                state,
                row["meeting"].strip(),
                int(row["race"]),
                row.get("race_time_local", ""),
                row["horse"].strip(),
                int(is_true(row.get("scratched", ""))),
                *[scores[factor] for factor in WEIGHTS],
                row.get("notes", ""),
                row.get("source", ""),
                dt.datetime.now(
                    dt.timezone.utc
                ).isoformat(),
            ]

            placeholders = ",".join("?" for _ in values)

            connection.execute(
                f"INSERT OR REPLACE INTO runners "
                f"VALUES ({placeholders})",
                values,
            )

            count += 1

    connection.commit()
    return count


def evaluate(connection, race_date):
    connection.row_factory = sqlite3.Row

    rows = [
        dict(row)
        for row in connection.execute(
            """
            SELECT *
            FROM runners
            WHERE date = ?
            ORDER BY state, meeting, race, horse
            """,
            (race_date,),
        )
    ]

    for row in rows:
        missing = [
            factor
            for factor in WEIGHTS
            if row[factor] is None
        ]

        row["missing_factors"] = ",".join(missing)
        row["provisional"] = bool(missing)

        # Neutral half-weight for unavailable factors.
        row["total"] = round(
            sum(
                row[factor]
                if row[factor] is not None
                else WEIGHTS[factor] / 2
                for factor in WEIGHTS
            ),
            2,
        )

    active = [
        row for row in rows
        if not row["scratched"]
    ]

    races = {}

    for row in active:
        key = (
            row["state"],
            row["meeting"],
            row["race"],
        )

        races.setdefault(key, []).append(row)

    gaps = []

    for key, horses in races.items():
        horses.sort(
            key=lambda horse: (
                -horse["total"],
                horse["horse"],
            )
        )

        for position, horse in enumerate(
            horses, start=1
        ):
            horse["rank"] = position

        if len(horses) < 2:
            continue

        first, second = horses[:2]

        gaps.append({
            "state": key[0],
            "meeting": key[1],
            "race": key[2],
            "race_time_local":
                first["race_time_local"],
            "horse": first["horse"],
            "score": first["total"],
            "runner_up": second["horse"],
            "runner_up_score": second["total"],
            "gap": round(
                first["total"] - second["total"], 2
            ),
            "notes": first["notes"],
            "source": first["source"],
            "provisional": (
                first["provisional"]
                or second["provisional"]
            ),
        })

    gaps.sort(
        key=lambda item: (
            -item["gap"],
            -item["score"],
            item["meeting"],
            item["race"],
        )
    )

    return rows, active, races, gaps


def write_csv(filename, rows, columns):
    with open(
        filename, "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=columns,
            extrasaction="ignore",
        )

        writer.writeheader()
        writer.writerows(rows)


def report(connection, race_date, output):
    rows, active, races, gaps = evaluate(
        connection, race_date
    )

    folder = pathlib.Path(output)
    folder.mkdir(parents=True, exist_ok=True)

    runner_columns = (
        list(rows[0].keys()) if rows else FIELDS
    )

    gap_columns = [
        "state", "meeting", "race",
        "race_time_local", "horse",
        "score", "runner_up",
        "runner_up_score", "gap",
        "notes", "source", "provisional",
    ]

    write_csv(
        folder / f"{race_date}_all_runners.csv",
        rows,
        runner_columns,
    )

    write_csv(
        folder / f"{race_date}_race_gaps.csv",
        gaps,
        gap_columns,
    )

    meetings = {
        (row["state"], row["meeting"])
        for row in active
    }

    lines = [
        f"# Australian Racing Strategy 4.0",
        f"## Racing date: {race_date}",
        "",
        f"Meetings assessed: {len(meetings)}",
        f"Races assessed: {len(races)}",
        f"Active runners assessed: {len(active)}",
        "",
        "## Top three by scoring advantage",
        "",
    ]

    for position, selection in enumerate(
        gaps[:3], start=1
    ):
        lines.extend([
            (
                f"### {position}. "
                f"{selection['horse']} — "
                f"{selection['meeting']} "
                f"Race {selection['race']}"
            ),
            "",
            (
                f"Score: {selection['score']}/100. "
                f"Second: {selection['runner_up']} "
                f"({selection['runner_up_score']}/100). "
                f"Gap: {selection['gap']} points."
            ),
            (
                "Race time: "
                f"{selection['race_time_local']}"
            ),
            (
                "Why: "
                f"{selection['notes'] or 'No explanation recorded'}"
            ),
            (
                "Source: "
                f"{selection['source'] or 'Not recorded'}"
            ),
            (
                "Provisional: "
                f"{selection['provisional']}"
            ),
            "",
        ])

    lines.extend([
        "## Coverage warning",
        "",
        (
            "This report includes only imported runners. "
            "It does not independently confirm that every "
            "eligible meeting, race or runner was collected."
        ),
        (
            "Missing factor scores receive neutral "
            "half-weight assessments and are flagged."
        ),
        (
            "A complete national top three cannot be "
            "certified without checking the full racecard."
        ),
    ])

    result = "\n".join(lines)

    (folder / f"{race_date}_top_three.md").write_text(
        result + "\n",
        encoding="utf-8",
    )

    print(result)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--database",
        default="strategy4.sqlite",
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    importer = commands.add_parser("import")
    importer.add_argument("csv_file")

    reporter = commands.add_parser("report")
    reporter.add_argument("date")
    reporter.add_argument(
        "--output",
        default="reports",
    )

    arguments = parser.parse_args()

    connection = connect(arguments.database)

    try:
        if arguments.command == "import":
            count = import_runners(
                connection,
                arguments.csv_file,
            )
            print(f"Imported {count} runner records.")

        elif arguments.command == "report":
            report(
                connection,
                arguments.date,
                arguments.output,
            )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
