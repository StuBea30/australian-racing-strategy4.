
#!/usr/bin/env python3
"""Strategy 4.1 - six-factor Australian thoroughbred scoring.

Historical class is determined from advertised total race prize money.
Group 1, Group 2, Group 3, Listed and Maiden races are treated separately.

Requires prize_grading.py and six configured prize-money thresholds.
Provisional model: not independently back-tested.
"""

import argparse
import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from prize_grading import grade, validate_minima


WEIGHTS = {
    "form": 30.0,
    "class": 25.0,
    "distance": 40 / 3,
    "going": 40 / 3,
    "barrier_weight": 40 / 3,
    "fitness": 5.0,
}

KEY = ("date", "meeting", "race", "horse")
RECENCY = (0.35, 0.25, 0.18, 0.13, 0.09)


def number(value):
    match = re.search(
        r"-?\d+(?:\.\d+)?",
        str(value or "").replace(",", "")
    )
    return float(match.group()) if match else None


def clamp(value, low=0.0, high=1.0):
    return max(low, min(high, value))


def date_value(value):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(
                str(value).strip(), fmt
            ).date()
        except ValueError:
            continue
    return None


def weighted(samples):
    if not samples:
        return None
    total = sum(weight for _, weight in samples)
    if not total:
        return None
    return sum(value * weight for value, weight in samples) / total


def evidence_blend(value, count, strength=2):
    if value is None:
        return 0.5
    return (count * value + strength * 0.5) / (count + strength)


def past_finish(value):
    match = re.search(
        r"(\d+)(?:st|nd|rd|th)?\s+of\s+(\d+)",
        str(value or ""),
        re.I
    )
    if not match:
        return None
    place, runners = map(int, match.groups())
    if not 1 <= place <= runners:
        return None
    return place, runners


def performance(row):
    finish = past_finish(row.get("Place"))
    if finish is None:
        return None

    place, runners = finish
    result = 1 - (place - 1) / max(1, runners - 1)
    margin = number(row.get("Margin"))

    if margin is not None and place > 1 and margin >= 0:
        result = (
            0.7 * result +
            0.3 * clamp(1 - margin / 10)
        )

    return clamp(result)


def is_trial(row):
    label = str(row.get("Class") or "").lower()
    return bool(re.search(
        r"\b(?:trial|jump[ -]?out|practice)\b",
        label
    ))


def is_picnic(row):
    label = " ".join(str(row.get(k) or "") for k in (
        "Class", "Race", "Race Name", "Meeting"
    ))
    return bool(re.search(
        r"\b(?:picnic|trophy|amateur|trpy\s*\w*)\b",
        label, re.I
    ))


def going_type(value):
    text = str(value or "").lower()
    for term in ("synthetic", "heavy", "soft", "good", "firm"):
        if term in text:
            return term
    return None


def valid_record(value):
    match = re.fullmatch(
        r"\s*(\d+)\s*:\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*",
        str(value or "")
    )
    if not match:
        return None

    starts, wins, seconds, thirds = map(int, match.groups())

    if starts <= 0 or wins + seconds + thirds > starts:
        return None

    return starts, wins, seconds, thirds


def record_quality(value):
    record = valid_record(value)
    if record is None:
        return None

    starts, wins, seconds, thirds = record
    return clamp(
        (wins + 0.55 * seconds + 0.3 * thirds + 1.5)
        / (starts + 3)
    )


def historical_rows(rows, race_date):
    result = []
    for row in rows:
        date = date_value(row.get("Date"))
        if date is not None and date < race_date:
            result.append((date, row))

    result.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in result]


def race_class(label, purse=None, state=None, minima=None):
    """Return a provisional class index from 0 to 100.

    Group/Listed and Maiden classes have separate model anchors.
    Other classes require a documented total purse and state.
    """
    text = str(label or "").upper()

    if re.search(r"\b(?:G1|GROUP\s*1)\b", text):
        return 100.0
    if re.search(r"\b(?:G2|GROUP\s*2)\b", text):
        return 94.0
    if re.search(r"\b(?:G3|GROUP\s*3)\b", text):
        return 88.0
    if re.search(r"\b(?:LISTED|LR)\b", text):
        return 82.0
    if re.search(r"\b(?:MDN|MAIDEN)\b", text):
        return 35.0

    if minima is None:
        return None

    result = grade(purse, state, minima)
    if result is None:
        return None

    return 35.0 + (result - 1) * 9.0


def history_class(row, minima):
    purse = (
        row.get("Prize Money AUD")
        or row.get("Prize")
        or row.get("Race Prize")
    )
    state = (
        row.get("Historical State")
        or row.get("State")
    )

    return race_class(
        row.get("Class"), purse, state, minima
    )


def choose_history(past, minima):
    """Use five consecutive complete starts, else three, else one."""
    def complete(row):
        return (
            performance(row) is not None
            and history_class(row, minima) is not None
        )

    for count in (5, 3, 1):
        if len(past) >= count:
            candidate = past[:count]
            if all(complete(row) for row in candidate):
                return candidate

    return []


def class_10_5_10(recent, current, minima):
    """Historical class 10 + movement 5 + performance 10."""
    if current is None or not recent:
        return None

    weights = RECENCY[:len(recent)]
    total = sum(weights)
    classes = []
    results = []

    for row in recent:
        old = history_class(row, minima)
        perf = performance(row)

        if old is None or perf is None:
            return None

        classes.append(old)
        results.append(perf)

    mean_class = sum(
        weight * value
        for weight, value in zip(weights, classes)
    ) / total

    historical = 10 * mean_class / 100

    movement = clamp(
        2.5 + (mean_class - current) / 12,
        0, 5
    )

    demonstrated = 10 * sum(
        weight * perf * clamp(
            1 + (old - current) / 60,
            0.5, 1.5
        )
        for weight, perf, old in zip(
            weights, results, classes
        )
    ) / total

    return clamp(
        historical + movement + min(10, demonstrated),
        0, 25
    )


def score_runner(horse, history, minima):
    race_date = date_value(horse.get("date"))
    if race_date is None:
        raise ValueError("Invalid runner date")

    all_history = historical_rows(history, race_date)
    trials = [r for r in all_history if is_trial(r)]
    past = [r for r in all_history if not is_trial(r)]
    recent = choose_history(past, minima)

    current = race_class(
        horse.get("race_class"),
        horse.get("race_prize_money"),
        horse.get("state"),
        minima
    )

    notes = []
    target = number(horse.get("distance_m"))
    surface = going_type(horse.get("track"))

    # FORM - 30 POINTS
    form_samples = []

    for i, row in enumerate(recent):
        perf = performance(row)
        old = history_class(row, minima)

        if perf is None or old is None:
            continue

        delta = old - current if current is not None else 0
        context = clamp(
            0.5 + 0.055 * delta, 0.18, 0.80
        )

        finish = past_finish(row.get("Place"))
        field = clamp(
            (finish[1] - 4) / 8
        ) if finish else 0.5

        reliability = clamp(
            0.55 + 0.25 * field + 0.20 * context,
            0.4, 1
        )

        adjusted = clamp(
            0.5 + (perf - 0.5) * reliability
            + 0.10 * (context - 0.5)
        )

        if is_picnic(row):
            adjusted = clamp(
                adjusted - 0.10 * max(0, perf - 0.5) / 0.5
            )

        form_samples.append((adjusted, 0.8 ** i))

    form = WEIGHTS["form"] * evidence_blend(
        weighted(form_samples), len(form_samples)
    )

    if len(form_samples) < 3:
        notes.append("Limited form evidence")

    # CLASS - 25 POINTS
    class_score = class_10_5_10(
        recent, current, minima
    )

    if class_score is None:
        notes.append("Class evidence unavailable")

    # DISTANCE - 13 1/3 POINTS
    distance_samples = []

    if target is not None and target > 0:
        for i, row in enumerate(past[:8]):
            old = number(row.get("Distance"))
            perf = performance(row)

            if old is None or perf is None:
                continue

            difference = abs(old - target) / target
            similarity = clamp(1 - difference / 0.45)

            distance_samples.append((
                0.5 + similarity * (perf - 0.5),
                (0.85 ** i) * max(0.15, similarity)
            ))

    distance_record = record_quality(
        horse.get("distance_record")
    )

    distance_evidence = weighted(distance_samples)

    if distance_record is not None:
        if distance_evidence is None:
            distance_evidence = distance_record
        else:
            distance_evidence = (
                0.75 * distance_evidence
                + 0.25 * distance_record
            )

    distance_count = (
        len(distance_samples)
        + (2 if distance_record is not None else 0)
    )

    distance_score = (
        WEIGHTS["distance"] * evidence_blend(
            distance_evidence, distance_count, strength=3
        )
        if target is not None and target > 0
        else None
    )

    # GOING - 13 1/3 POINTS
    going_samples = []

    if surface:
        for i, row in enumerate(past[:8]):
            perf = performance(row)

            if (
                going_type(row.get("Cond.")) == surface
                and perf is not None
            ):
                going_samples.append(
                    (perf, 0.85 ** i)
                )

    going_record = record_quality(
        horse.get(surface + "_record")
    ) if surface else None

    going_evidence = weighted(going_samples)

    if going_record is not None:
        if going_evidence is None:
            going_evidence = going_record
        else:
            going_evidence = (
                0.75 * going_evidence
                + 0.25 * going_record
            )

    going_count = (
        len(going_samples)
        + (2 if going_record is not None else 0)
    )

    going_score = (
        WEIGHTS["going"] * evidence_blend(
            going_evidence, going_count, strength=3
        )
        if surface else None
    )

    # FITNESS - 5 POINTS
    days = (
        (race_date - date_value(past[0]["Date"])).days
        if past else None
    )

    preparation = []

    if days is not None:
        for i, row in enumerate(past[:6]):
            current_date = date_value(row.get("Date"))
            previous_date = (
                date_value(past[i + 1].get("Date"))
                if i + 1 < len(past)
                else None
            )
            perf = performance(row)

            if (
                current_date is not None
                and previous_date is not None
                and perf is not None
            ):
                gap = (current_date - previous_date).days

                if abs(gap - days) <= max(14, days * 0.4):
                    preparation.append(
                        (perf, 0.85 ** i)
                    )

    fitness_evidence = weighted(preparation)

    first_up = record_quality(horse.get("first_up"))
    second_up = record_quality(horse.get("second_up"))

    if days is not None and days >= 70 and first_up is not None:
        fitness_evidence = (
            0.6 * first_up
            + 0.4 * (
                fitness_evidence
                if fitness_evidence is not None else 0.5
            )
        )
    elif days is not None and days < 70 and second_up is not None:
        fitness_evidence = (
            0.35 * second_up
            + 0.65 * (
                fitness_evidence
                if fitness_evidence is not None else 0.5
            )
        )

    fitness_count = (
        len(preparation)
        + (2 if first_up is not None or second_up is not None else 0)
    )

    fitness = (
        WEIGHTS["fitness"] * evidence_blend(
            fitness_evidence, fitness_count, strength=3
        )
        if days is not None else None
    )

    if trials:
        notes.append(
            f"{len(trials)} trial(s), preparation only"
        )

    return {
        "form": form,
        "class": class_score,
        "distance": distance_score,
        "going": going_score,
        "fitness": fitness,
        "days_since_last": days,
        "evidence_starts": len(past),
        "trial_starts": len(trials),
        "form_samples": len(form_samples),
        "class_samples": len(recent),
        "distance_samples": distance_count,
        "going_samples": going_count,
        "fitness_samples": fitness_count,
        "notes": notes,
    }


def staking_rule(gap):
    if gap >= 7:
        return 3, 1.60
    if gap >= 5:
        return 2, 2.00
    if gap >= 3:
        return 1, 3.00
    return 0, None


def each_way_rule(points, odds):
    if odds is None:
        return None

    if points == 3 and odds >= 6.00:
        return 1.5, 1.5
    if points == 2 and odds >= 4.50:
        return 1.0, 1.0
    if points == 1 and odds >= 4.00:
        return 0.5, 0.5

    return None


def write_csv(path, rows, columns):
    with path.open(
        "w", newline="", encoding="utf-8"
    ) as file:
        writer = csv.DictWriter(
            file, fieldnames=columns, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True)
    parser.add_argument("--input", default="data")
    parser.add_argument("--output", default="reports")
    parser.add_argument("--expected-fields", default="")
    parser.add_argument(
        "--purse-thresholds",
        default="",
        help="JSON file containing six verified AUD minimums"
    )

    args = parser.parse_args()

    race_date = date_value(args.date)

    if race_date is None or race_date.isoformat() != args.date:
        parser.error("Date must be YYYY-MM-DD")

    if not args.purse_thresholds:
        parser.error(
            "Six verified purse thresholds are required"
        )

    with open(
        args.purse_thresholds, encoding="utf-8"
    ) as file:
        configuration = json.load(file)

    minima = validate_minima(
        configuration["standard_minima_aud"]
    )

    folder = Path(args.input) / args.date

    for filename in ("runners.csv", "past_starts.csv"):
        if not (folder / filename).is_file():
            parser.error(f"Missing {folder / filename}")

    with (folder / "runners.csv").open(
        encoding="utf-8-sig", newline=""
    ) as file:
        runners = list(csv.DictReader(file))

    with (folder / "past_starts.csv").open(
        encoding="utf-8-sig", newline=""
    ) as file:
        histories = list(csv.DictReader(file))

    if not runners:
        parser.error("No runners found")

    expected_fields = {}

    if args.expected_fields:
        with open(
            args.expected_fields,
            encoding="utf-8-sig",
            newline=""
        ) as file:
            for item in csv.DictReader(file):
                count = number(item.get("expected_runners"))
                if count is not None and count >= 2:
                    key = (
                        item.get("date", ""),
                        item.get("meeting", "").strip().casefold(),
                        str(item.get("race", "")).strip()
                    )
                    expected_fields[key] = int(count)

    histories_by_key = defaultdict(list)

    for item in histories:
        key = tuple(item.get(k, "") for k in KEY)
        histories_by_key[key].append(item)

    groups = defaultdict(list)

    for runner in runners:
        if date_value(runner.get("date")) == race_date:
            key = (
                args.date,
                runner["state"],
                runner["meeting"],
                runner["race"]
            )
            groups[key].append(runner)

    if not groups:
        parser.error("No races found for requested date")

    all_scores = []
    race_rankings = []

    for group_key, group in sorted(groups.items()):
        barriers = [
            number(r.get("barrier")) for r in group
        ]
        barriers = [
            value for value in barriers
            if value is not None and value > 0
        ]
        max_barrier = max(barriers) if barriers else None

        expected = expected_fields.get((
            args.date,
            group_key[2].strip().casefold(),
            str(group_key[3])
        ))

        incomplete_field = (
            expected is not None and len(group) < expected
        )

        scored = []

        for runner in group:
            key = tuple(runner.get(k, "") for k in KEY)
            history = histories_by_key[key]

            if not history:
                for date_text in (
                    args.date,
                    race_date.strftime("%d/%m/%Y"),
                    race_date.strftime("%d/%m/%y")
                ):
                    alternate = (
                        date_text,
                        runner["meeting"],
                        runner["race"],
                        runner["horse"]
                    )
                    history = histories_by_key[alternate]
                    if history:
                        break

            result = score_runner(runner, history, minima)

            barrier = number(runner.get("barrier"))
            weight = number(runner.get("weight_kg"))

            draw_component = None

            if (
                barrier is not None
                and barrier > 0
                and max_barrier is not None
            ):
                draw = clamp(
                    1 - (barrier - 1)
                    / max(1, max_barrier - 1)
                )
                draw_component = 0.5 + 0.2 * (draw - 0.5)

            successful_weights = []

            for row in historical_rows(
                history, race_date
            )[:8]:
                if is_trial(row):
                    continue

                finish = past_finish(row.get("Place"))
                previous_weight = number(
                    row.get("Weight") or row.get("Wgt")
                )

                if (
                    finish is not None
                    and finish[0] <= 3
                    and previous_weight is not None
                ):
                    successful_weights.append(previous_weight)

            weight_component = None

            if successful_weights and weight is not None:
                average = (
                    sum(successful_weights)
                    / len(successful_weights)
                )
                weight_component = clamp(
                    0.5 + 0.022 * (average - weight)
                )

            components = [
                (value, 0.5)
                for value in (
                    draw_component, weight_component
                )
                if value is not None
            ]

            result["barrier_weight"] = (
                WEIGHTS["barrier_weight"]
                * weighted(components)
                if components else None
            )

            available = [
                factor for factor in WEIGHTS
                if result[factor] is not None
            ]

            coverage = sum(
                WEIGHTS[factor] for factor in available
            )
            score = sum(
                result[factor] for factor in available
            )

            confidence = (
                0.35 * min(1, result["form_samples"] / 4)
                + 0.30 * min(1, result["class_samples"] / 4)
                + 0.15 * min(1, result["distance_samples"] / 3)
                + 0.10 * min(1, result["going_samples"] / 3)
                + 0.10 * min(1, result["fitness_samples"] / 2)
            )

            status = "PROVISIONAL - SCRATCHINGS UNVERIFIED"

            if (
                coverage < 99.999
                or result["evidence_starts"] < 3
                or result["form_samples"] < 3
                or result["class_samples"] < 2
                or confidence < 0.70
            ):
                status = "INSUFFICIENT DATA - DO NOT SELECT"

            if str(
                runner.get("scratching_status") or ""
            ).strip().lower() in ("scratched", "withdrawn"):
                status = "SCRATCHED - EXCLUDED"

            entry = {
                "date": args.date,
                "state": runner["state"],
                "meeting": runner["meeting"],
                "race": runner["race"],
                "race_name": runner.get("race_name", ""),
                "horse_number": runner.get("horse_number", ""),
                "horse": runner["horse"],
                "barrier": runner.get("barrier", ""),
                "weight_kg": runner.get("weight_kg", ""),
                "race_url": runner.get("race_url", ""),
                "scratching_status": runner.get(
                    "scratching_status", "unverified"
                ),
                "score": round(score, 2),
                "coverage_points": round(coverage, 4),
                "form_points": round(result["form"], 2),
                "class_points": (
                    round(result["class"], 2)
                    if result["class"] is not None else ""
                ),
                "distance_points": (
                    round(result["distance"], 2)
                    if result["distance"] is not None else ""
                ),
                "going_points": (
                    round(result["going"], 2)
                    if result["going"] is not None else ""
                ),
                "barrier_weight_points": (
                    round(result["barrier_weight"], 2)
                    if result["barrier_weight"] is not None else ""
                ),
                "fitness_points": (
                    round(result["fitness"], 2)
                    if result["fitness"] is not None else ""
                ),
                "days_since_last": (
                    result["days_since_last"]
                    if result["days_since_last"] is not None else ""
                ),
                "evidence_starts": result["evidence_starts"],
                "trial_starts": result["trial_starts"],
                "evidence_confidence": round(confidence, 3),
                "status": status,
                "notes": "; ".join(result["notes"]),
                "rank": "",
                "gap_to_second": "",
            }

            scored.append(entry)

        scored.sort(
            key=lambda r: (
                -r["score"],
                -r["coverage_points"],
                r["horse"]
            )
        )

        for rank, entry in enumerate(scored, 1):
            entry["rank"] = rank

        all_scores.extend(scored)

        active = [
            r for r in scored
            if r["status"] != "SCRATCHED - EXCLUDED"
        ]

        if len(active) < 2:
            continue

        # Compare the actual top two active runners. Do not silently
        # promote a lower-scoring horse past one with limited evidence.
        first, second = active[:2]
        gap = round(first["score"] - second["score"], 2)
        first["gap_to_second"] = gap

        points, minimum_odds = staking_rule(gap)
        warnings = []

        if expected is None:
            warnings.append("FIELD COUNT NOT INDEPENDENTLY VERIFIED")

        if incomplete_field:
            warnings.append("INCOMPLETE FIELD")
            points, minimum_odds = 0, None

        leaders_eligible = all(
            r["status"] == "PROVISIONAL - SCRATCHINGS UNVERIFIED"
            for r in (first, second)
        )
        if not leaders_eligible:
            warnings.append("LEADING RUNNER(S) HAVE INSUFFICIENT DATA")
            points, minimum_odds = 0, None

        if len(active) <= 3:
            warnings.append("SMALL FIELD")

        if incomplete_field:
            ranking_status = "INCOMPLETE FIELD - NO BET"
        elif not leaders_eligible:
            ranking_status = "INSUFFICIENT LEADER EVIDENCE - NO BET"
        elif points == 0:
            ranking_status = "BELOW MINIMUM GAP - NO BET"
        else:
            ranking_status = "PROVISIONAL - SCRATCHINGS UNVERIFIED"

        race_rankings.append({
            "points": points,
            "minimum_win_odds": minimum_odds,
            "date": args.date,
            "state": first["state"],
            "meeting": first["meeting"],
            "race": first["race"],
            "race_name": first["race_name"],
            "first_horse": first["horse"],
            "first_score": first["score"],
            "second_horse": second["horse"],
            "second_score": second["score"],
            "gap": gap,
            "race_url": first["race_url"],
            "status": ranking_status,
            "integrity_warnings": "; ".join(warnings),
            "collected_runners": len(group),
            "expected_runners": expected or "",
        })

    race_rankings.sort(
        key=lambda r: (
            -r["gap"],
            -r["first_score"],
            r["meeting"],
            int(number(r["race"]) or 0)
        )
    )

    qualifying_rankings = [
        race for race in race_rankings if race["points"] > 0
    ]

    output = Path(args.output) / args.date
    output.mkdir(parents=True, exist_ok=True)

    runner_columns = [
        "date", "state", "meeting", "race", "race_name",
        "horse_number", "horse", "barrier", "weight_kg",
        "race_url", "scratching_status", "score",
        "coverage_points", "form_points", "class_points",
        "distance_points", "going_points",
        "barrier_weight_points", "fitness_points",
        "days_since_last", "evidence_starts", "trial_starts",
        "evidence_confidence", "status", "notes",
        "rank", "gap_to_second"
    ]

    ranking_columns = [
        "points", "minimum_win_odds", "date", "state",
        "meeting", "race", "race_name", "first_horse",
        "first_score", "second_horse", "second_score",
        "gap", "race_url", "status", "integrity_warnings",
        "collected_runners", "expected_runners"
    ]

    write_csv(
        output / "all_runner_scores.csv",
        all_scores,
        runner_columns
    )

    write_csv(
        output / "race_rankings.csv",
        race_rankings,
        ranking_columns
    )

    write_csv(
        output / "top_ten_provisional.csv",
        qualifying_rankings[:10],
        ranking_columns
    )

    write_csv(
        output / "top_three_provisional.csv",
        qualifying_rankings[:3],
        ranking_columns
    )

    manifest = {
        "date": args.date,
        "model": "Strategy 4.1 historical prize-money class",
        "weights": WEIGHTS,
        "races_with_runners": len(groups),
        "runners_scored": len(all_scores),
        "races_ranked": len(race_rankings),
        "provisional_top_ten": len(qualifying_rankings[:10]),
        "qualifying_races": len(qualifying_rankings),
        "scratchings_verified": False,
        "betting_recommendations": False,
        "backtested": False,
    }

    (output / "scoring_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8"
    )

    lines = [
        f"# Strategy 4.1 - {args.date}",
        "",
        "**PROVISIONAL - NOT BACK-TESTED**",
        "",
        f"Scored {len(all_scores)} runners "
        f"across {len(groups)} races.",
        "",
        "| Rank | Meeting | Race | Leader | Score | "
        "Second | Score | Gap | Points | Min odds |",
        "|---:|---|---:|---|---:|---|---:|---:|---:|---:|",
    ]

    for rank, race in enumerate(qualifying_rankings[:10], 1):
        lines.append(
            f"| {rank} | {race['meeting']} | "
            f"{race['race']} | {race['first_horse']} | "
            f"{race['first_score']:.2f} | "
            f"{race['second_horse']} | "
            f"{race['second_score']:.2f} | "
            f"{race['gap']:.2f} | "
            f"{race['points'] or 'No bet'} | "
            f"{race['minimum_win_odds'] or '-'} |"
        )

    if not qualifying_rankings:
        lines.append(
            "No qualifying selections with sufficient leader evidence."
        )

    lines.extend([
        "",
        "Top 10 ranked by score gap.",
        "Trials excluded from competitive form.",
        "Class uses historical class 10, movement 5, "
        "and demonstrated performance 10.",
        "Six published prize-money minimums required.",
        "WA, SA and TAS adjustment handled by prize_grading.",
        "Ratings are provisional, not win probabilities.",
    ])

    report = "\n".join(lines) + "\n"

    (output / "top_three_provisional.md").write_text(
        report, encoding="utf-8"
    )

    print(json.dumps(manifest, indent=2))
    print(report)


if __name__ == "__main__":
    main()
