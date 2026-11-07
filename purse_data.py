
#!/usr/bin/env python3
"""Extract advertised Australian race purses for Strategy 4.1."""

import re
from decimal import Decimal, InvalidOperation


def parse_money_text(value):
    """Convert an advertised race purse to an AUD integer."""
    if value is None or isinstance(value, bool):
        return None

    text = str(value).strip()
    if not text or text.lower() in ("n/a", "none", "-", "unknown"):
        return None

    match = re.fullmatch(
        r"(?:A\$|AUD\s*|\$)?\s*"
        r"(\d[\d,]*(?:\.\d+)?)\s*([kKmM])?",
        text
    )

    if not match:
        return None

    try:
        amount = Decimal(match.group(1).replace(",", ""))
        suffix = (match.group(2) or "").lower()

        if suffix == "k":
            amount *= 1000
        elif suffix == "m":
            amount *= 1000000

        if amount <= 0:
            return None

        return int(amount)

    except (InvalidOperation, ValueError):
        return None


def extract_history_purse(record):
    """
    Extract total advertised race prize money.

    Never use Prize Won or individual horse earnings.
    """
    if not isinstance(record, dict):
        return None

    preferred_columns = (
        "Prize Money AUD",
        "Prize",
        "Race Prize",
        "Race Prize Money",
        "Race Purse",
        "Total Prize Money",
        "Stakes",
    )

    for column in preferred_columns:
        value = record.get(column)

        if value not in (None, ""):
            amount = parse_money_text(value)
            if amount is not None:
                return amount

    return None
