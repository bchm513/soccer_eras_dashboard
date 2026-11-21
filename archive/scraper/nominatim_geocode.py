"""OpenStreetMap Nominatim geocoding for clubs, formerly ClubResolver._nominatim in scraper/clubs.py
(the `--geocode` option of `assemble`). Retired: the `locate` step (Wikipedia coordinates, then GeoNames)
places clubs better and without a per-request rate limit. Off by default even when it was in use."""
import json
import time

import requests

COUNTRY_NAME = {"ENG": "United Kingdom", "SCO": "United Kingdom", "ESP": "Spain", "ITA": "Italy",
                "GER": "Germany", "FRA": "France", "NED": "Netherlands", "POR": "Portugal",
                "BEL": "Belgium", "HUN": "Hungary", "BRA": "Brazil", "ARG": "Argentina"}


class NominatimMixin:  # was part of ClubResolver; needed self.geo_cache, self.geo_cache_path, self.contact

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
