
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
    "kilmore": "VIC",
    "seymour": "VIC",
    "werribee": "VIC",
    "hamilton": "VIC",
    "ararat": "VIC",
    "echuca": "VIC",
    "swan hill": "VIC",
    "benalla": "VIC",
    "terang": "VIC",
    "stony creek": "VIC",

    # New South Wales
    "randwick": "NSW",
    "royal randwick": "NSW",
    "rosehill": "NSW",
    "rosehill gardens": "NSW",
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
    "grafton": "NSW",
    "port macquarie": "NSW",
    "coffs harbour": "NSW",
    "ballina": "NSW",
    "lismore": "NSW",
    "bathurst": "NSW",
    "orange": "NSW",
    "mudgee": "NSW",
    "wagga": "NSW",
    "wagga wagga": "NSW",
    "albury": "NSW",
    "muswellbrook": "NSW",
    "armidale": "NSW",
    "queanbeyan": "NSW",
    "nowra": "NSW",
    "moruya": "NSW",

    # Queensland
    "eagle farm": "QLD",
    "doomben": "QLD",
    "gold coast": "QLD",
    "sunshine coast": "QLD",
    "sunshine coast poly": "QLD",
    "ipswich": "QLD",
    "toowoomba": "QLD",
    "rockhampton": "QLD",
    "townsville": "QLD",
    "cairns": "QLD",
    "mackay": "QLD",
    "bundaberg": "QLD",
    "dalby": "QLD",
    "warwick": "QLD",
    "gatton": "QLD",
    "beaudesert": "QLD",
    "kilcoy": "QLD",
    "gympie": "QLD",
    "emerald": "QLD",

    # South Australia
    "morphettville": "SA",
    "morphettville parks": "SA",
    "murray bridge": "SA",
    "murray bridge races": "SA",
    "gawler": "SA",
    "balaklava": "SA",
    "oakbank": "SA",
    "strathalbyn": "SA",
    "port lincoln": "SA",
    "mount gambier": "SA",
    "naracoorte": "SA",
    "bordertown": "SA",
    "clare": "SA",
    "port augusta": "SA",
    "port pirie": "SA",

    # Western Australia
    "ascot": "WA",
    "belmont": "WA",
    "belmont park": "WA",
    "pinjarra": "WA",
    "pinjarra scarpside": "WA",
    "bunbury": "WA",
    "northam": "WA",
    "geraldton": "WA",
    "albany": "WA",
    "kalgoorlie": "WA",
    "esperance": "WA",
    "narrogin": "WA",
    "york": "WA",
    "broome": "WA",
    "carnarvon": "WA",
    "mount barker": "WA",
    "roebourne": "WA",

    # Tasmania
    "hobart": "TAS",
    "elwick": "TAS",
    "launceston": "TAS",
    "mowbray": "TAS",
    "devonport": "TAS",
    "devonport synthetic": "TAS",
    "spreyton": "TAS",
    "spreyton synthetic": "TAS",
    "longford": "TAS",
}


def infer_state(track):
    """
    Identify the state of a historical Australian racecourse.

    Returns:
        VIC, NSW, QLD, SA, WA or TAS for recognised tracks.
        None when the racecourse cannot be identified.

    Unknown tracks are never assigned a guessed state.
    """
    if not track:
        return None

    name = re.sub(
        r"\s+",
        " ",
        str(track).strip().lower()
    )

    name = re.sub(
        r"[^a-z0-9 ]",
        "",
        name
    )

    # Exact racecourse match.
    if name in TRACK_STATES:
        return TRACK_STATES[name]

    # Allow state suffixes such as 'Flemington VIC'.
    for suffix in ("vic", "nsw", "qld", "sa", "wa", "tas"):
        ending = " " + suffix

        if name.endswith(ending):
            base = name[:-len(ending)].strip()

            if TRACK_STATES.get(base) == suffix.upper():
                return suffix.upper()

    # Unknown racecourse: do not invent a state.
    return None
