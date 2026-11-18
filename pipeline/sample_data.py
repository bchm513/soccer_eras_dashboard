"""Generate a SAMPLE dataset so the pipeline and dashboard can run before real data exists.

Everything here is synthetic. Player names are fictional codes ("Player A1"), and their
numbers are simulated. Cities and their coordinates are real. Replace the output with
real data (same columns) in data/raw/player_seasons.csv.

Output columns (one row per player, season, competition):
    player_id, player, season, competition, comp_type, club_city, lat, lon,
    apps, goals, assists, is_star_seed
`season` is the starting year (1987 = 1987-88). `assists` is blank before 1990.
`comp_type` is "club" or "international"; international rows have no city.
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

RNG = np.random.default_rng(1946)
FIRST, LAST = 1946, 2025  # seasons 1946-47 .. 2025-26

CITIES = {
    "Madrid": (40.42, -3.70, "ESP"), "Barcelona": (41.39, 2.17, "ESP"),
    "Valencia": (39.47, -0.38, "ESP"), "Bilbao": (43.26, -2.94, "ESP"),
    "London": (51.51, -0.13, "ENG"), "Manchester": (53.48, -2.24, "ENG"),
    "Liverpool": (53.41, -2.99, "ENG"),
    "Milan": (45.46, 9.19, "ITA"), "Turin": (45.07, 7.69, "ITA"),
    "Rome": (41.90, 12.50, "ITA"), "Naples": (40.85, 14.27, "ITA"),
    "Munich": (48.14, 11.58, "GER"), "Dortmund": (51.51, 7.47, "GER"),
    "Hamburg": (53.55, 9.99, "GER"),
    "Amsterdam": (52.37, 4.90, "NED"), "Eindhoven": (51.44, 5.47, "NED"),
    "Lisbon": (38.72, -9.14, "POR"), "Porto": (41.16, -8.63, "POR"),
    "Budapest": (47.50, 19.04, "HUN"),
    "Rio de Janeiro": (-22.91, -43.17, "BRA"), "São Paulo": (-23.55, -46.63, "BRA"),
    "Santos": (-23.96, -46.33, "BRA"),
    "Buenos Aires": (-34.60, -58.38, "ARG"),
    "Paris": (48.86, 2.35, "FRA"), "Marseille": (43.30, 5.37, "FRA"),
    "Glasgow": (55.86, -4.25, "SCO"),
    "New York": (40.71, -74.01, "USA"), "Los Angeles": (34.05, -118.24, "USA"),
}
LEAGUE_OFFSET = {"ESP": 1.0, "ENG": 1.05, "ITA": 0.85, "GER": 1.1, "NED": 1.2, "POR": 1.0,
                 "HUN": 1.15, "BRA": 1.05, "ARG": 1.0, "FRA": 0.95, "SCO": 1.1, "USA": 1.05}
LEAGUE_ACTIVE = {"USA": [(1968, 1984), (1996, LAST)]}


def baseline_rate(year: float, league: str) -> float:
    """Simulated scoring environment: high 1950s, defensive dip ~1990, modern rise."""
    r = (0.32 + 0.14 * np.exp(-((year - 1952) / 12) ** 2)
         - 0.07 * np.exp(-((year - 1990) / 9) ** 2)
         + 0.06 / (1 + np.exp(-(year - 2013) / 3)))
    return float(r * LEAGUE_OFFSET.get(league, 1.0))


INTL_BASE = lambda y: 0.30 + 0.10 * np.exp(-((y - 1954) / 10) ** 2) - 0.05 * np.exp(-((y - 1990) / 10) ** 2)


def league_active(league: str, year: int) -> bool:
    spans = LEAGUE_ACTIVE.get(league)
    return spans is None or any(a <= year <= b for a, b in spans)


# Seeded star groups: (code, peak season, peak z, spread, [(from_season, city), ...])
# Groups are built to produce overlapping peaks (eras), plus a few lone stars (spikes).
STARS = [
    # Post-war: Budapest, then Madrid
    ("A1", 1953, 4.2, 3.5, [(1945, "Budapest"), (1958, "Madrid")]),
    ("A2", 1955, 4.6, 3.8, [(1946, "Buenos Aires"), (1953, "Madrid")]),
    ("A3", 1952, 3.6, 3.0, [(1945, "Budapest")]),
    ("A4", 1958, 3.4, 3.0, [(1948, "Lisbon"), (1954, "Madrid")]),
    # Brazilian 1960s
    ("B1", 1962, 4.8, 3.5, [(1956, "Santos")]),
    ("B2", 1961, 3.5, 3.0, [(1953, "Rio de Janeiro")]),
    ("B3", 1965, 3.8, 3.0, [(1958, "Lisbon")]),
    # 1970s total football
    ("C1", 1972, 4.4, 3.2, [(1964, "Amsterdam"), (1973, "Barcelona")]),
    ("C2", 1971, 4.7, 3.4, [(1963, "Munich")]),
    ("C3", 1974, 3.4, 3.0, [(1966, "Munich")]),
    # Lone stars between eras (spikes, not plateaus)
    ("L1", 1981, 3.9, 2.6, [(1974, "Buenos Aires"), (1979, "Glasgow")]),
    ("L2", 1966, 3.3, 2.4, [(1959, "Manchester")]),
    # Serie A golden age
    ("D1", 1987, 4.5, 3.4, [(1978, "Buenos Aires"), (1984, "Naples")]),
    ("D2", 1989, 3.9, 3.2, [(1981, "Amsterdam"), (1987, "Milan")]),
    ("D3", 1991, 3.7, 3.0, [(1983, "Eindhoven"), (1987, "Milan")]),
    ("D4", 1994, 3.6, 3.2, [(1986, "Turin"), (1990, "Turin")]),
    # Turn of the century
    ("E1", 1998, 4.4, 3.0, [(1993, "Eindhoven"), (1996, "Milan"), (2002, "Madrid")]),
    ("E2", 2002, 3.9, 3.2, [(1993, "Marseille"), (1996, "Turin"), (2001, "Madrid")]),
    ("E3", 2005, 3.8, 2.8, [(1999, "Paris"), (2003, "Barcelona"), (2008, "Milan")]),
    # The duopoly
    ("F1", 2012, 5.4, 4.6, [(2004, "Barcelona"), (2021, "Paris"), (2023, "New York")]),
    ("F2", 2013, 5.0, 4.4, [(2003, "Lisbon"), (2004, "Manchester"), (2009, "Madrid"), (2018, "Turin")]),
    # Present day
    ("G1", 2021, 4.4, 3.4, [(2013, "Dortmund"), (2016, "Munich"), (2023, "London")]),
    ("G2", 2023, 4.9, 2.8, [(2018, "Dortmund"), (2022, "Manchester")]),
    ("G3", 2023, 4.2, 3.0, [(2016, "Paris"), (2024, "Madrid")]),
    ("G4", 2019, 3.6, 3.2, [(2011, "Lisbon"), (2017, "Liverpool")]),
]


def city_for(clubs, season):
    city = clubs[0][1]
    for start, c in clubs:
        if season >= start:
            city = c
    return city


def generate(out_path: Path) -> int:
    rows = []
    # Background players: define each league-season's scoring environment.
    leagues = sorted(set(v[2] for v in CITIES.values()))
    league_cities = {lg: [c for c, v in CITIES.items() if v[2] == lg] for lg in leagues}
    for season in range(FIRST, LAST + 1):
        for lg in leagues:
            if not league_active(lg, season):
                continue
            base = baseline_rate(season, lg)
            for i in range(45):
                city = league_cities[lg][i % len(league_cities[lg])]
                lat, lon, _ = CITIES[city]
                apps = int(RNG.integers(14, 38))
                rate = base * RNG.lognormal(-0.12, 0.5)
                goals = int(RNG.poisson(rate * apps))
                assists = int(RNG.poisson(apps * 0.12)) if season >= 1990 else ""
                rows.append([f"bg-{lg}-{season}-{i}", "background", season, lg, "club", city,
                             lat, lon, apps, goals, assists, 0])
        # Background internationals
        ib = INTL_BASE(season)
        for i in range(60):
            apps = int(RNG.integers(3, 10))
            goals = int(RNG.poisson(ib * RNG.lognormal(-0.12, 0.5) * apps))
            assists = int(RNG.poisson(apps * 0.1)) if season >= 1990 else ""
            rows.append([f"bgi-{season}-{i}", "background", season, "INT", "international", "",
                         "", "", apps, goals, assists, 0])

    # Seeded stars
    for code, peak, height, spread, clubs in STARS:
        start, end = peak - 9, min(peak + 8, LAST)
        if code in ("F1", "F2"):
            end = LAST  # still active
        for season in range(max(start, FIRST), end + 1):
            city = city_for(clubs, season)
            lat, lon, lg = CITIES[city]
            if not league_active(lg, season):
                continue
            # Skewed career: faster rise, slower fade
            s = spread * (0.75 if season < peak else 1.15)
            z = height * np.exp(-((season - peak) ** 2) / (2 * s ** 2)) + RNG.normal(0, 0.45)
            base = baseline_rate(season, lg)
            sd = base * 0.62
            apps = int(RNG.integers(26, 38))
            rate = max(base + z * sd, 0.02)
            goals = int(RNG.poisson(rate * apps))
            assists = int(RNG.poisson(apps * (0.12 + 0.05 * max(z, 0)))) if season >= 1990 else ""
            rows.append([f"star-{code}", f"Player {code}", season, lg, "club", city, lat, lon,
                         apps, goals, assists, 1])
            # International duty
            ib = INTL_BASE(season)
            iapps = int(RNG.integers(4, 11))
            igoals = int(RNG.poisson(max(ib + 0.8 * z * ib * 0.55, 0.02) * iapps))
            iassists = int(RNG.poisson(iapps * 0.15)) if season >= 1990 else ""
            rows.append([f"star-{code}", f"Player {code}", season, "INT", "international", "",
                         "", "", iapps, igoals, iassists, 1])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["player_id", "player", "season", "competition", "comp_type", "club_city",
                    "lat", "lon", "apps", "goals", "assists", "is_star_seed"])
        w.writerows(rows)
    return len(rows)


if __name__ == "__main__":
    p = Path(__file__).resolve().parents[1] / "data" / "sample" / "player_seasons.csv"
    print(f"wrote {generate(p)} rows -> {p}")
