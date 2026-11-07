#!/usr/bin/env python3
"""Identify Australian states/territories from historical thoroughbred track names.

Track names are matched exactly after punctuation/whitespace normalization.
Unknown or foreign tracks remain unresolved; no geographic guessing.
"""

import re

TRACK_STATES = {
    # VIC
    'ararat': 'VIC',
    'avoca': 'VIC',
    'ballarat': 'VIC',
    'ballarat synthetic': 'VIC',
    'benalla': 'VIC',
    'bendigo': 'VIC',
    'burrumbeet': 'VIC',
    'camperdown': 'VIC',
    'casterton': 'VIC',
    'caulfield': 'VIC',
    'caulfield heath': 'VIC',
    'colac': 'VIC',
    'coleraine': 'VIC',
    'cranbourne': 'VIC',
    'donald': 'VIC',
    'echuca': 'VIC',
    'flemington': 'VIC',
    'geelong': 'VIC',
    'great western': 'VIC',
    'hamilton': 'VIC',
    'horsham': 'VIC',
    'kerang': 'VIC',
    'kilmore': 'VIC',
    'kyneton': 'VIC',
    'manangatang': 'VIC',
    'mildura': 'VIC',
    'moe': 'VIC',
    'moonee valley': 'VIC',
    'mornington': 'VIC',
    'mortlake': 'VIC',
    'murtoa': 'VIC',
    'pakenham': 'VIC',
    'pakenham synthetic': 'VIC',
    'penshurst': 'VIC',
    'sale': 'VIC',
    'sandown': 'VIC',
    'sandown hillside': 'VIC',
    'sandown lakeside': 'VIC',
    'seymour': 'VIC',
    'st arnaud': 'VIC',
    'stawell': 'VIC',
    'stony creek': 'VIC',
    'swan hill': 'VIC',
    'tatura': 'VIC',
    'terang': 'VIC',
    'wangaratta': 'VIC',
    'warracknabeal': 'VIC',
    'warrnambool': 'VIC',
    'werribee': 'VIC',

    # NSW
    'adaminaby': 'NSW',
    'albury': 'NSW',
    'armidale': 'NSW',
    'ballina': 'NSW',
    'bathurst': 'NSW',
    'bowraville': 'NSW',
    'brewarrina': 'NSW',
    'bundarra': 'NSW',
    'canterbury': 'NSW',
    'carinda': 'NSW',
    'cobar': 'NSW',
    'coffs harbour': 'NSW',
    'collarenebri': 'NSW',
    'come by chance': 'NSW',
    'coonabarabran': 'NSW',
    'coonamble': 'NSW',
    'cootamundra': 'NSW',
    'cowra': 'NSW',
    'dubbo': 'NSW',
    'enngonia': 'NSW',
    'forbes': 'NSW',
    'geurie': 'NSW',
    'gilgandra': 'NSW',
    'gosford': 'NSW',
    'grafton': 'NSW',
    'grenfell': 'NSW',
    'gulargambone': 'NSW',
    'gunnedah': 'NSW',
    'harden': 'NSW',
    'hawkesbury': 'NSW',
    'inverell': 'NSW',
    'kembla grange': 'NSW',
    'kempsey': 'NSW',
    'kensington': 'NSW',
    'leeton': 'NSW',
    'lismore': 'NSW',
    'louth': 'NSW',
    'mallawa': 'NSW',
    'mendooran': 'NSW',
    'moree': 'NSW',
    'moruya': 'NSW',
    'mudgee': 'NSW',
    'muswellbrook': 'NSW',
    'narromine': 'NSW',
    'newcastle': 'NSW',
    'nowra': 'NSW',
    'orange': 'NSW',
    'parkes': 'NSW',
    'port macquarie': 'NSW',
    'queanbeyan': 'NSW',
    'quirindi': 'NSW',
    'randwick': 'NSW',
    'randwick kensington': 'NSW',
    'rosehill': 'NSW',
    'rosehill gardens': 'NSW',
    'royal randwick': 'NSW',
    'sapphire coast': 'NSW',
    'scone': 'NSW',
    'talmoi': 'NSW',
    'tamworth': 'NSW',
    'taree': 'NSW',
    'tuncurry': 'NSW',
    'wagga': 'NSW',
    'wagga wagga': 'NSW',
    'warren': 'NSW',
    'warwick farm': 'NSW',
    'wean': 'NSW',
    'wellington': 'NSW',
    'wyong': 'NSW',
    'young': 'NSW',

    # QLD
    'beaudesert': 'QLD',
    'bundaberg': 'QLD',
    'cairns': 'QLD',
    'dalby': 'QLD',
    'deagon': 'QLD',
    'doomben': 'QLD',
    'eagle farm': 'QLD',
    'emerald': 'QLD',
    'gatton': 'QLD',
    'gold coast': 'QLD',
    'goondiwindi': 'QLD',
    'gympie': 'QLD',
    'ipswich': 'QLD',
    'kilcoy': 'QLD',
    'mackay': 'QLD',
    'rockhampton': 'QLD',
    'sunshine coast': 'QLD',
    'sunshine coast poly': 'QLD',
    'toowoomba': 'QLD',
    'townsville': 'QLD',
    'warwick': 'QLD',

    # SA
    'balaklava': 'SA',
    'bordertown': 'SA',
    'clare': 'SA',
    'gawler': 'SA',
    'morphettville': 'SA',
    'morphettville parks': 'SA',
    'mount gambier': 'SA',
    'murray bridge': 'SA',
    'murray bridge races': 'SA',
    'naracoorte': 'SA',
    'oakbank': 'SA',
    'port augusta': 'SA',
    'port lincoln': 'SA',
    'port pirie': 'SA',
    'strathalbyn': 'SA',

    # WA
    'albany': 'WA',
    'ascot': 'WA',
    'belmont': 'WA',
    'belmont park': 'WA',
    'broome': 'WA',
    'bunbury': 'WA',
    'carnarvon': 'WA',
    'esperance': 'WA',
    'geraldton': 'WA',
    'kalgoorlie': 'WA',
    'mount barker': 'WA',
    'narrogin': 'WA',
    'northam': 'WA',
    'pinjarra': 'WA',
    'pinjarra scarpside': 'WA',
    'roebourne': 'WA',
    'york': 'WA',

    # TAS
    'devonport': 'TAS',
    'devonport synthetic': 'TAS',
    'elwick': 'TAS',
    'hobart': 'TAS',
    'launceston': 'TAS',
    'longford': 'TAS',
    'mowbray': 'TAS',
    'spreyton': 'TAS',
    'spreyton synthetic': 'TAS',

    # ACT
    'canberra': 'ACT',

    # NT
    'alice springs': 'NT',
    'darwin': 'NT',

}

def infer_state(track):
    """Return the known Australian state/territory code, or None."""
    if not track:
        return None
    name = re.sub(r"[^a-z0-9]+", " ", str(track).casefold())
    name = re.sub(r"\s+", " ", name).strip()
    if name in TRACK_STATES:
        return TRACK_STATES[name]
    # Accept a state suffix only when it agrees with the verified track mapping.
    for suffix in ("vic", "nsw", "qld", "sa", "wa", "tas", "act", "nt"):
        ending = " " + suffix
        if name.endswith(ending):
            base = name[:-len(ending)].strip()
            if TRACK_STATES.get(base) == suffix.upper():
                return suffix.upper()
    return None

if __name__ == "__main__":
    assert infer_state("Sandown-Hillside") == "VIC"
    assert infer_state("Pakenham Synthetic") == "VIC"
    assert infer_state("Canberra") == "ACT"
    assert infer_state("Ellerslie") is None
    assert infer_state("Unknown Course") is None
    print(f"Track-state lookup checks passed ({len(TRACK_STATES)} names).")
