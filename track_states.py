
#!/usr/bin/env python3
"""Identify Australian racing states from historical racecourse names."""

import re

TRACK_STATES = {
    # Victoria
    "flemington": "VIC",
    "caulfield": "VIC",
    "moonee valley": "VIC",
    "sandown": "VIC",
    "sandown hillside": "VIC",
    "sandown lakeside": "VIC",
    "bendigo": "VIC",
    "ballarat": "VIC",
    "geelong": "VIC",
    "cranbourne": "VIC",
    "pakenham": "VIC",
    "mornington": "VIC",
    "sale": "VIC",
    "wangaratta": "VIC",
    "warrnambool": "VIC",

    # New South Wales
    "randwick": "NSW",
    "rosehill": "NSW",
    "warwick farm": "NSW",
    "canterbury": "NSW",
    "kensington": "NSW",
    "newcastle": "NSW",
    "kembla grange": "NSW",
    "gosford": "NSW",
    "hawkesbury": "NSW",
    "wyong": "NSW",
    "scone": "NSW",
    "tamworth": "NSW",
    "dubbo": "NSW",

    # Queensland
    "eagle farm": "QLD",
    "doomben": "QLD",
    "gold coast": "QLD",
    "sunshine coast": "QLD",
    "ipswich": "QLD",
    "toowoomba": "QLD",
    "rockhampton": "QLD",
    "townsville": "QLD",
    "cairns": "QLD",

    # South Australia
    "morphettville": "SA",
    "morphettville parks": "SA",
    "murray bridge": "SA",
    "gawler": "SA",
    "balaklava": "SA",
    "oakbank": "SA",
    "strathalbyn": "SA",
    "port lincoln": "SA",

    # Western Australia
    "ascot": "WA",
    "belmont": "WA",
    "belmont park": "WA",
    "pinjarra": "WA",
    "bunbury": "WA",
    "northam": "WA",
    "geraldton": "WA",
    "albany": "WA",
    "kalgoorlie": "WA",
    "esperance": "WA",

    # Tasmania
    "hobart": "TAS",
    "elwick": "TAS",
    "launceston": "TAS",
    "mowbray": "TAS",
    "devonport": "TAS",
    "spre yton": "TAS",
    "spre yton synthetic": "TAS",
    "longford": "TAS",
}


def infer_state(track):
    """
    Return the state for a recognised Australian racecourse.

    Unknown tracks return None rather than an invented state.
    """
    if not track:
        return None

    name = re.sub(r"\s+", " ", str(track).strip().lower())
    name = re.sub(r"[^a-z0-9 ]", "", name)

    if name in TRACK_STATES:
        return TRACK_STATES[name]

    # Handle common track labels such as 'Flemington VIC'.
    for suffix in ("vic", "nsw", "qld", "sa", "wa", "tas"):
        if name.endswith(" " + suffix):
            base = name[: -(len(suffix) + 1)]
            if TRACK_STATES.get(base) == suffix.upper():
                return suffix.upper()

    return None
