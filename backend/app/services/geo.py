"""Infer the country (or countries) of a job from its free-text location.

Locations look like "Austin, Texas, United States of America", "Seattle, WA, USA", "New York, NY",
"Remote — US", "Bengaluru, Karnataka, India", "London, UK; Remote" or "Remote — Anywhere".
Returns ISO-3166 alpha-2 codes, plus "WW" for worldwide/anywhere remote roles.
"""
from __future__ import annotations

import re
from functools import lru_cache

US_STATES = {
    "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas", "CA": "california", "CO": "colorado",
    "CT": "connecticut", "DE": "delaware", "FL": "florida", "GA": "georgia", "HI": "hawaii", "ID": "idaho",
    "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas", "KY": "kentucky", "LA": "louisiana", "ME": "maine",
    "MD": "maryland", "MA": "massachusetts", "MI": "michigan", "MN": "minnesota", "MS": "mississippi", "MO": "missouri",
    "MT": "montana", "NE": "nebraska", "NV": "nevada", "NH": "new hampshire", "NJ": "new jersey", "NM": "new mexico",
    "NY": "new york", "NC": "north carolina", "ND": "north dakota", "OH": "ohio", "OK": "oklahoma", "OR": "oregon",
    "PA": "pennsylvania", "RI": "rhode island", "SC": "south carolina", "SD": "south dakota", "TN": "tennessee",
    "TX": "texas", "UT": "utah", "VT": "vermont", "VA": "virginia", "WA": "washington", "WV": "west virginia",
    "WI": "wisconsin", "WY": "wyoming", "DC": "district of columbia", "PR": "puerto rico",
}
US_CITIES = {
    "new york city", "nyc", "san francisco", "los angeles", "seattle", "austin", "boston", "chicago", "denver", "atlanta",
    "san jose", "palo alto", "mountain view", "sunnyvale", "menlo park", "redmond", "bellevue", "cupertino", "santa clara",
    "san diego", "dallas", "houston", "miami", "phoenix", "portland", "pittsburgh", "philadelphia", "raleigh", "durham",
    "salt lake city", "nashville", "detroit", "minneapolis", "washington dc", "washington, d.c.", "brooklyn", "jersey city",
    "irvine", "boulder", "cambridge, ma", "arlington, va", "reston", "mclean", "charlotte", "columbus", "st. louis",
    "kansas city", "indianapolis", "baltimore", "tampa", "orlando", "sacramento", "oakland", "berkeley", "plano", "frisco",
    "san mateo", "redwood city", "foster city", "south san francisco", "fremont", "milpitas", "kirkland", "hillsboro",
    "ann arbor", "madison", "omaha", "richmond", "lehi", "scottsdale", "tempe", "chandler", "fort worth", "san antonio",
}
COUNTRIES = {  # code: patterns (lower-case words/phrases)
    "US": ["united states", "united states of america", "usa", "u.s.a", "u.s.", "us", "america"],
    "CA": ["canada", "toronto", "vancouver", "montreal", "ottawa", "calgary", "waterloo", "ontario", "british columbia", "quebec", "alberta"],
    "GB": ["united kingdom", "uk", "u.k.", "england", "scotland", "wales", "london", "manchester", "edinburgh", "cambridge, uk", "great britain"],
    "IE": ["ireland", "dublin", "cork"],
    "IN": ["india", "bengaluru", "bangalore", "hyderabad", "pune", "chennai", "mumbai", "gurgaon", "gurugram", "noida", "new delhi", "delhi", "karnataka", "telangana"],
    "DE": ["germany", "deutschland", "berlin", "munich", "münchen", "hamburg", "frankfurt", "cologne", "köln", "stuttgart"],
    "FR": ["france", "paris", "lyon"],
    "NL": ["netherlands", "amsterdam", "rotterdam", "utrecht", "eindhoven"],
    "ES": ["spain", "madrid", "barcelona"],
    "PT": ["portugal", "lisbon", "porto"],
    "IT": ["italy", "milan", "rome"],
    "PL": ["poland", "warsaw", "krakow", "kraków", "wroclaw"],
    "CH": ["switzerland", "zurich", "zürich", "geneva"],
    "SE": ["sweden", "stockholm"],
    "DK": ["denmark", "copenhagen"],
    "IL": ["israel", "tel aviv", "haifa", "herzliya"],
    "SG": ["singapore"],
    "AU": ["australia", "sydney", "melbourne", "brisbane"],
    "NZ": ["new zealand", "auckland"],
    "JP": ["japan", "tokyo", "osaka"],
    "KR": ["south korea", "korea", "seoul"],
    "CN": ["china", "beijing", "shanghai", "shenzhen"],
    "HK": ["hong kong"],
    "TW": ["taiwan", "taipei"],
    "MX": ["mexico", "méxico", "mexico city", "guadalajara"],
    "BR": ["brazil", "brasil", "são paulo", "sao paulo"],
    "AR": ["argentina", "buenos aires"],
    "CO": ["colombia", "bogota", "bogotá", "medellin"],
    "AE": ["united arab emirates", "uae", "dubai", "abu dhabi"],
    "PH": ["philippines", "manila"],
    "RO": ["romania", "bucharest"],
    "CZ": ["czech", "prague"],
    "GE": ["tbilisi"],
}
WORLDWIDE = re.compile(r"\b(anywhere|worldwide|world ?wide|global(ly)?|international|any location)\b", re.I)
_STATE_ABBR = re.compile(r"(?:,|\s-)\s*(" + "|".join(US_STATES) + r")\b(?!\.?\w)")
_STATE_NAME = re.compile(r"\b(" + "|".join(sorted((v for v in US_STATES.values()), key=len, reverse=True)) + r")\b", re.I)


def _has(low: str, term: str) -> bool:
    return re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", low) is not None


@lru_cache(maxsize=20000)
def countries_of(location: str) -> frozenset:
    loc = location or ""
    low = loc.lower()
    out = set()
    if WORLDWIDE.search(low):
        out.add("WW")
    for code, terms in COUNTRIES.items():
        for t in terms:
            if code == "US" and t in ("us", "america"):
                # "US" only as its own token (e.g. "Remote - US", "US-NY"); avoid "us" in prose
                if re.search(r"(?<![A-Za-z])US(?![A-Za-z])", loc) or re.search(r"\bnorth america\b|\bamericas\b", low):
                    out.add("US")
                continue
            if code == "GB" and t == "uk" and not re.search(r"(?<![A-Za-z])UK(?![A-Za-z])", loc):
                continue
            if _has(low, t):
                out.add(code)
                break
    # Georgia/Washington are US states unless the country is named
    if _STATE_ABBR.search(loc) or any(_has(low, c) for c in US_CITIES):
        out.add("US")
    elif _STATE_NAME.search(low) and not (out - {"WW", "US"}):
        out.add("US")
    if "CA" in out and _STATE_ABBR.search(loc) and not re.search(r"canada|ontario|toronto|vancouver|montreal|british columbia", low):
        out.discard("CA")  # ", CA" is California
    return frozenset(out)


def in_country(location: str, remote_type: str, code: str, include_worldwide: bool = True, url: str = "") -> bool:
    cs = countries_of(location or "")
    if not cs and url:  # e.g. Workday "2 Locations": the job URL names the main one (/job/Austin-Texas-United-States-of-America/…)
        m = re.search(r"/job/([^/]+)/", url)
        if m:
            cs = countries_of(m.group(1).replace("-", " "))
    if code in cs:
        return True
    if include_worldwide and "WW" in cs and not (cs - {"WW"}):
        return True
    # bare "Remote" with no country at all: keep it only for worldwide-friendly searches
    return include_worldwide and not cs and remote_type == "remote" and bool(re.search(r"remote", location or "", re.I))
