"""Resolve a club name to a city and coordinates.

Order of attempts, all restricted to the league's country:
  1. data/manual/club_locations_manual.csv (team,city,lat,lon) — your fixes always win
  2. a city name inside the team name ("Atlético Madrid" -> Madrid), longest match first
  3. a known alias inside the team name ("Juventus" -> Turin, "Arsenal" -> London)
  4. data/raw/club_locations_auto.csv, found by `python -m scraper.run locate`
`assemble` lists clubs still unplaced in data/raw/unresolved_clubs.csv, most goals first.
"""
from __future__ import annotations

import csv
from pathlib import Path

from core.common import norm
from core.paths import manual_dir

CITIES = Path(__file__).with_name("cities.csv")


class ClubResolver:
    def __init__(self, raw: Path, use_auto: bool = True):
        self.raw = raw
        self.by_country: dict[str, list[tuple[str, str, float, float, bool]]] = {}
        for r in csv.DictReader(CITIES.open(encoding="utf-8")):
            lat, lon = float(r["lat"]), float(r["lon"])
            entries = [(norm(r["city"]), r["city"], lat, lon, False)]
            entries += [(norm(a), r["city"], lat, lon, True) for a in r["aliases"].split("|") if a]
            self.by_country.setdefault(r["country"], []).extend(entries)
        # Locations found by `python -m scraper.run locate` (Wikipedia / GeoNames), used after the city list
        self.auto: dict = {}
        af = raw / "club_locations_auto.csv"
        if use_auto and af.exists():
            for r in csv.DictReader(af.open(encoding="utf-8")):
                try:
                    v = (r["city"], float(r["lat"]), float(r["lon"]), r.get("method") or "auto")
                except (TypeError, ValueError):
                    continue
                self.auto[(norm(r["team"]), r.get("country") or "")] = v
                self.auto.setdefault((norm(r["team"]), ""), v)
        self.manual = {}
        mf = manual_dir(raw) / "club_locations_manual.csv"
        if mf.exists():
            for r in csv.DictReader(mf.open(encoding="utf-8")):
                try:
                    self.manual[norm(r["team"])] = (r["city"], float(r["lat"]), float(r["lon"]), "manual")
                except (TypeError, ValueError, KeyError):
                    continue

    def resolve(self, team: str, country: str) -> tuple[str | None, float | None, float | None, str]:
        t = norm(team)
        if not t:
            return None, None, None, "no club"
        if t in self.manual:
            return self.manual[t]
        padded = f" {t} "
        cands = self.by_country.get(country, [])
        for want_alias in (False, True):
            hits = [c for c in cands if c[4] == want_alias and f" {c[0]} " in padded]
            if hits:
                best = max(hits, key=lambda c: len(c[0]))
                return best[1], best[2], best[3], "alias" if want_alias else "name"
        if (t, country) in self.auto:
            return self.auto[(t, country)]
        if (t, "") in self.auto:
            return self.auto[(t, "")]
        return None, None, None, "unresolved"
