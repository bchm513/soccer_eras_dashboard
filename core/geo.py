"""Country names and coordinates shared by the scraper and the pipeline.

Three naming schemes meet here:
  - international results (martj42): "England", "United States", "Yugoslavia"
  - the dashboard's world map (Natural Earth 110m): "United Kingdom", "United States of America"
  - league codes in leagues.json: "ENG", "USA", "YUG"
"""
from __future__ import annotations

import csv
from pathlib import Path

HERE = Path(__file__).parent

# International-results team name -> map country (historical teams go to their modern successor)
TEAM_TO_MAP = {
    "England": "United Kingdom", "Scotland": "United Kingdom", "Wales": "United Kingdom",
    "Northern Ireland": "United Kingdom", "United States": "United States of America",
    "Ivory Coast": "Côte d'Ivoire", "Republic of Ireland": "Ireland", "DR Congo": "Dem. Rep. Congo",
    "Czechoslovakia": "Czechia", "Czech Republic": "Czechia", "Yugoslavia": "Serbia",
    "North Macedonia": "Macedonia", "German DR": "Germany", "Bosnia and Herzegovina": "Bosnia and Herz.",
    "Eswatini": "eSwatini", "Equatorial Guinea": "Eq. Guinea", "Dominican Republic": "Dominican Rep.",
    "Central African Republic": "Central African Rep.", "South Sudan": "S. Sudan",
    "Solomon Islands": "Solomon Is.", "Falkland Islands": "Falkland Is.", "Northern Cyprus": "N. Cyprus",
    "Vietnam Republic": "Vietnam", "Soviet Union": "Russia", "Zaire": "Dem. Rep. Congo",
}

# Football nations too small for the 110m map, for tournament hosts and labels
SMALL = {
    "Singapore": (1.35, 103.82), "Bahrain": (26.07, 50.55), "Malta": (35.90, 14.51),
    "Hong Kong": (22.32, 114.17), "Macau": (22.20, 113.55), "Barbados": (13.19, -59.54),
    "Mauritius": (-20.35, 57.55), "Cape Verde": (15.12, -23.61), "Tahiti": (-17.65, -149.43),
    "Maldives": (3.20, 73.22), "Seychelles": (-4.68, 55.49), "Curaçao": (12.17, -68.98),
    "Guam": (13.44, 144.79), "Martinique": (14.64, -61.02), "Guadeloupe": (16.27, -61.55),
    "Réunion": (-21.12, 55.54), "Andorra": (42.51, 1.52), "Liechtenstein": (47.17, 9.56),
    "Luxembourg": (49.81, 6.13), "Qatar": (25.35, 51.18), "Trinidad and Tobago": (10.69, -61.22),
    "Grenada": (12.12, -61.68), "Saint Lucia": (13.91, -60.98), "Antigua and Barbuda": (17.06, -61.80),
}

# League code -> international-results team name (for national strength and talent retention)
CODE_TO_TEAM = {
    "ENG": "England", "SCO": "Scotland", "ESP": "Spain", "ITA": "Italy", "GER": "Germany", "FRA": "France",
    "NED": "Netherlands", "POR": "Portugal", "BEL": "Belgium", "TUR": "Turkey", "GRE": "Greece",
    "RUS": "Russia", "URS": "Russia", "UKR": "Ukraine", "YUG": "Yugoslavia", "SRB": "Serbia", "HUN": "Hungary",
    "AUT": "Austria", "SUI": "Switzerland", "SWE": "Sweden", "DEN": "Denmark", "CZE": "Czech Republic",
    "POL": "Poland", "ROU": "Romania", "BRA": "Brazil", "ARG": "Argentina", "URU": "Uruguay",
    "CHI": "Chile", "COL": "Colombia", "PAR": "Paraguay", "MEX": "Mexico", "USA": "United States",
    "JPN": "Japan", "KOR": "South Korea", "CHN": "China", "KSA": "Saudi Arabia", "QAT": "Qatar",
    "IRN": "Iran", "AUS": "Australia", "EGY": "Egypt", "RSA": "South Africa", "MAR": "Morocco",
    "TUN": "Tunisia", "ALG": "Algeria", "NGA": "Nigeria",
}
# Teams whose ratings carry over: a league code -> team used before a given season
TEAM_HISTORY = {"CZE": [(1993, "Czechoslovakia")], "SRB": [(2006, "Yugoslavia")]}


def team_for(code: str, season: int) -> str | None:
    for before, team in TEAM_HISTORY.get(code, []):
        if season < before:
            return team
    return CODE_TO_TEAM.get(code)


def map_name(team: str) -> str:
    return TEAM_TO_MAP.get(team, team)


_centroids: dict | None = None


def centroids() -> dict:
    global _centroids
    if _centroids is None:
        with (HERE / "country_centroids.csv").open(encoding="utf-8") as f:
            _centroids = {r["name"]: (float(r["lat"]), float(r["lon"])) for r in csv.DictReader(f)}
    return _centroids


def country_coords(team_or_country: str) -> tuple[float, float] | None:
    """Coordinates for a country or team name: map centroid, else the small-nations table."""
    c = centroids()
    name = map_name(team_or_country)
    return c.get(name) or SMALL.get(team_or_country) or SMALL.get(name)


# Country names as written on Wikipedia finals lists -> (league/resolver code, ISO 3166 alpha-2)
COUNTRY = {
    "england": ("ENG", "GB"), "scotland": ("SCO", "GB"), "wales": ("WAL", "GB"), "northern ireland": ("NIR", "GB"),
    "spain": ("ESP", "ES"), "italy": ("ITA", "IT"), "germany": ("GER", "DE"), "west germany": ("GER", "DE"),
    "east germany": ("GDR", "DE"), "france": ("FRA", "FR"), "netherlands": ("NED", "NL"), "portugal": ("POR", "PT"),
    "belgium": ("BEL", "BE"), "turkey": ("TUR", "TR"), "greece": ("GRE", "GR"), "russia": ("RUS", "RU"),
    "soviet union": ("URS", "RU"), "ukraine": ("UKR", "UA"), "yugoslavia": ("YUG", "RS"), "serbia": ("SRB", "RS"),
    "croatia": ("CRO", "HR"), "hungary": ("HUN", "HU"), "austria": ("AUT", "AT"), "switzerland": ("SUI", "CH"),
    "sweden": ("SWE", "SE"), "denmark": ("DEN", "DK"), "norway": ("NOR", "NO"), "czechoslovakia": ("CZE", "CZ"),
    "czech republic": ("CZE", "CZ"), "poland": ("POL", "PL"), "romania": ("ROU", "RO"), "bulgaria": ("BUL", "BG"),
    "brazil": ("BRA", "BR"), "argentina": ("ARG", "AR"), "uruguay": ("URU", "UY"), "paraguay": ("PAR", "PY"),
    "chile": ("CHI", "CL"), "colombia": ("COL", "CO"), "ecuador": ("ECU", "EC"), "peru": ("PER", "PE"),
    "bolivia": ("BOL", "BO"), "venezuela": ("VEN", "VE"),
    "mexico": ("MEX", "MX"), "united states": ("USA", "US"), "usa": ("USA", "US"), "canada": ("CAN", "CA"),
    "costa rica": ("CRC", "CR"), "honduras": ("HON", "HN"), "el salvador": ("SLV", "SV"), "guatemala": ("GUA", "GT"),
    "trinidad and tobago": ("TRI", "TT"), "jamaica": ("JAM", "JM"), "suriname": ("SUR", "SR"), "haiti": ("HAI", "HT"),
    "japan": ("JPN", "JP"), "south korea": ("KOR", "KR"), "korea republic": ("KOR", "KR"), "china": ("CHN", "CN"),
    "china pr": ("CHN", "CN"), "saudi arabia": ("KSA", "SA"), "iran": ("IRN", "IR"), "qatar": ("QAT", "QA"),
    "united arab emirates": ("UAE", "AE"), "uae": ("UAE", "AE"), "iraq": ("IRQ", "IQ"), "israel": ("ISR", "IL"),
    "thailand": ("THA", "TH"), "australia": ("AUS", "AU"), "uzbekistan": ("UZB", "UZ"),
    "egypt": ("EGY", "EG"), "morocco": ("MAR", "MA"), "tunisia": ("TUN", "TN"), "algeria": ("ALG", "DZ"),
    "south africa": ("RSA", "ZA"), "nigeria": ("NGA", "NG"), "cameroon": ("CMR", "CM"), "ghana": ("GHA", "GH"),
    "zaire": ("COD", "CD"), "dr congo": ("COD", "CD"), "congo dr": ("COD", "CD"), "guinea": ("GUI", "GN"),
    "ivory coast": ("CIV", "CI"), "côte d'ivoire": ("CIV", "CI"), "senegal": ("SEN", "SN"), "mali": ("MLI", "ML"),
    "congo": ("CGO", "CG"), "sudan": ("SUD", "SD"), "zambia": ("ZAM", "ZM"), "kenya": ("KEN", "KE"),
}


def country_codes(name: str) -> tuple[str, str]:
    """('ENG', 'GB') from 'England'; ('', '') if unknown."""
    return COUNTRY.get(str(name).strip().lower(), ("", ""))


def iso2_for_code(code: str) -> str:
    for c, iso in COUNTRY.values():
        if c == code:
            return iso
    return ""
