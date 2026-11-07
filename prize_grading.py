
#!/usr/bin/env python3
"""Strategy 4.1 prize-money class grading.

Uses six configured minimum advertised race purses in AUD.

VIC, NSW and QLD use the standard thresholds.
WA, SA and TAS use thresholds reduced by 15%.

This module does not estimate or invent prize money.
"""

import math
import re


STANDARD_STATES = {"VIC", "NSW", "QLD"}
DISCOUNT_STATES = {"WA", "SA", "TAS"}

ALL_STATES = STANDARD_STATES | DISCOUNT_STATES


def parse_purse(value):
    """Parse a total advertised race purse in Australian dollars."""
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        if not math.isfinite(value) or value <= 0:
            return None
        return float(value)

    text = str(value).strip()

    if not text or text.lower() in (
        "none", "unknown", "n/a", "na", "-"
    ):
        return None

    match = re.fullmatch(
        r"(?:A\$|AUD\s*|\$)?\s*"
        r"(\d[\d,]*(?:\.\d+)?)\s*([kKmM])?",
        text
    )

    if not match:
        return None

    amount = float(match.group(1).replace(",", ""))
    suffix = (match.group(2) or "").lower()

    if suffix == "k":
        amount *= 1000
    elif suffix == "m":
        amount *= 1000000

    return amount if math.isfinite(amount) and amount > 0 else None


def validate_minima(values):
    """Require exactly six strictly increasing positive thresholds."""
    if not isinstance(values, (list, tuple)):
        raise ValueError(
            "Prize-money thresholds must be a list of six values"
        )

    if len(values) != 6:
        raise ValueError(
            "Exactly six prize-money thresholds are required"
        )

    parsed = []

    for value in values:
        amount = parse_purse(value)

        if amount is None:
            raise ValueError(
                f"Invalid prize-money threshold: {value}"
            )

        parsed.append(amount)

    if any(
        parsed[i] >= parsed[i + 1]
        for i in range(5)
    ):
        raise ValueError(
            "Prize-money thresholds must be strictly increasing"
        )

    return parsed


def adjusted_minima(state, minima):
    """Apply the agreed 15% threshold discount where applicable."""
    state = str(state or "").strip().upper()

    if state not in ALL_STATES:
        return None

    thresholds = validate_minima(minima)

    multiplier = (
        0.85 if state in DISCOUNT_STATES else 1.0
    )

    return [
        threshold * multiplier
        for threshold in thresholds
    ]


def grade(purse, state, minima):
    """Return class grade 1-6, or None if evidence is missing.

    Grade 1: at least the first minimum.
    Grade 2: at least the second minimum.
    ...
    Grade 6: at least the sixth minimum.

    Below Grade 1 or missing data: unclassified.
    """
    amount = parse_purse(purse)

    if amount is None:
        return None

    thresholds = adjusted_minima(state, minima)

    if thresholds is None:
        return None

    result = None

    for index, minimum in enumerate(thresholds, start=1):
        if amount >= minimum:
            result = index
        else:
            break

    return result


if __name__ == "__main__":
    # Synthetic examples for checking the calculation.
    # These are NOT verified live prize-money thresholds.
    example = [10000, 20000, 30000, 40000, 50000, 60000]

    assert grade(30000, "VIC", example) == 3
    assert grade(30000, "WA", example) == 3
    assert grade(51000, "SA", example) == 6
    assert grade(9000, "NSW", example) is None
    assert grade(None, "QLD", example) is None

    print("Prize-money grading checks passed.")
