"""Resolve a club name to a city and coordinates.

Order of attempts, all restricted to the league's country:
  1. data/raw/club_locations_manual.csv (team,city,lat,lon) — your fixes always win
  2. a city name inside the team name ("Atlético Madrid" -> Madrid), longest match first
  3. a known alias inside the team name ("Juventus" -> Turin, "Arsenal" -> London)
  4. optional OpenStreetMap Nominatim lookup (--geocode), cached, 1 request/second
Anything still unresolved is written to data/raw/unresolved_clubs.csv to fill in by hand.
"""
from __future__ import annotations

import csv
import json
import re
import time
import unicodedata
from pathlib import Path

import requests

CITIES = Path(__file__).with_name("cities.csv")
COUNTRY_NAME = {"ENG": "United Kingdom", "SCO": "United Kingdom", "ESP": "Spain", "ITA": "Italy",
                "GER": "Germany", "FRA": "France", "NED": "Netherlands", "POR": "Portugal",
                "BEL": "Belgium", "HUN": "Hungary", "BRA": "Brazil", "ARG": "Argentina"}


def norm(s) -> str:
    if not isinstance(s, str):          # blank cells arrive as NaN
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9' ]+", " ", s).strip()


class ClubResolver:
    def __init__(self, raw: Path, geocode: bool = False, contact: str | None = None):
        self.raw = raw
        self.geocode = geocode
        self.contact = contact
        self.by_country: dict[str, list[tuple[str, str, float, float, bool]]] = {}
        for r in csv.DictReader(CITIES.open(encoding="utf-8")):
            lat, lon = float(r["lat"]), float(r["lon"])
            entries = [(norm(r["city"]), r["city"], lat, lon, False)]
            entries += [(norm(a), r["city"], lat, lon, True) for a in r["aliases"].split("|") if a]
            self.by_country.setdefault(r["country"], []).extend(entries)
        self.manual = {}
        mf = raw / "club_locations_manual.csv"
        if mf.exists():
            for r in csv.DictReader(mf.open(encoding="utf-8")):
                self.manual[norm(r["team"])] = (r["city"], float(r["lat"]), float(r["lon"]), "manual")
        self.geo_cache_path = raw.parent / "cache" / "geocode.json"
        self.geo_cache = json.loads(self.geo_cache_path.read_text(encoding="utf-8")) if self.geo_cache_path.exists() else {}
        self.unresolved: set[tuple[str, str]] = set()

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
        if self.geocode:
            g = self._nominatim(team, country)
            if g:
                return (*g, "geocoded")
        self.unresolved.add((team, country))
        return None, None, None, "unresolved"

    def _nominatim(self, team: str, country: str):
        key = f"{team}|{country}"
        if key not in self.geo_cache:
            q = f"{team} football club, {COUNTRY_NAME.get(country, '')}"
            ua = f"soccer-eras-research/0.1 ({self.contact or 'no contact set'})"
            try:
                r = requests.get("https://nominatim.openstreetmap.org/search",
                                 params={"q": q, "format": "json", "limit": 1, "addressdetails": 1},
                                 headers={"User-Agent": ua}, timeout=30)
                time.sleep(1.1)   # Nominatim usage policy: max 1 request per second
                hit = r.json()[0] if r.ok and r.json() else None
            except (requests.RequestException, ValueError):
                hit = None
            if hit:
                a = hit.get("address", {})
                city = a.get("city") or a.get("town") or a.get("village") or a.get("municipality") or team
                self.geo_cache[key] = [city, round(float(hit["lat"]), 3), round(float(hit["lon"]), 3)]
            else:
                self.geo_cache[key] = None
            self.geo_cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.geo_cache_path.write_text(json.dumps(self.geo_cache, ensure_ascii=False, indent=0), encoding="utf-8")
        v = self.geo_cache[key]
        return tuple(v) if v else None

    def write_unresolved(self) -> int:
        p = self.raw / "unresolved_clubs.csv"
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["team", "country", "city", "lat", "lon"])
            for team, country in sorted(self.unresolved):
                w.writerow([team, country, "", "", ""])
        return len(self.unresolved)