"""Find coordinates for clubs the hand-made city list can't place, anywhere in the world.

For each unresolved club (from the scorer files and the continental finals):
  1. Wikipedia: the club's article coordinates, else its ground/stadium article's coordinates
     (the scorer tables link each club's article). The city is the nearest GeoNames city.
  2. GeoNames (cities with 15,000+ people, CC BY 4.0): a city name inside the club name,
     within the club's country ("Club Atlético Tucumán" -> San Miguel de Tucumán? no: Tucumán).
Results go to data/raw/club_locations_auto.csv, which the resolver reads after your manual
fixes and the built-in city list. Re-running only looks up clubs still missing.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

from core import db, geo
from core.common import norm
from . import wikipedia as wiki
from .clubs import ClubResolver
from .http import FetchFailed, PoliteSession, RobotsDisallowed

GEONAMES_URL = "https://download.geonames.org/export/dump/cities15000.zip"
STOP = {"real", "club", "city", "united", "sport", "sports", "sporting", "athletic", "atletico", "deportivo",
        "union", "nacional", "national", "central", "olympic", "olimpia", "racing", "royal", "inter", "dynamo",
        "dinamo", "lokomotiv", "spartak", "torpedo", "star", "stars", "rovers", "wanderers", "fc", "cf", "sc",
        "ac", "as", "cd", "ca", "fk", "sk", "nk", "us", "rc", "estudiantes", "independiente", "universidad",
        "san", "santa", "santo", "saint", "st", "de", "del", "la", "el", "los", "las", "al", "the", "and"}


# ---------------------------------------------------------------- GeoNames

class GeoNames:
    def __init__(self, cache: Path):
        cache.mkdir(parents=True, exist_ok=True)
        txt = cache / "cities15000.txt"
        if not txt.exists():
            r = requests.get(GEONAMES_URL, timeout=120)
            r.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                txt.write_bytes(z.read("cities15000.txt"))
        df = pd.read_csv(txt, sep="\t", header=None, quoting=3, dtype=str, keep_default_na=False,
                         usecols=[1, 2, 4, 5, 8, 14], names=["name", "ascii", "lat", "lon", "cc", "pop"])
        df["lat"], df["lon"] = df["lat"].astype(float), df["lon"].astype(float)
        df["pop"] = pd.to_numeric(df["pop"], errors="coerce").fillna(0)
        self.df = df
        self.by_cc: dict[str, dict[str, tuple]] = {}
        for r in df.sort_values("pop").itertuples(index=False):      # larger cities overwrite smaller
            d = self.by_cc.setdefault(r.cc, {})
            for n in {norm(r.name), norm(r.ascii)}:
                if len(n) >= 4 and n not in STOP:
                    d[n] = (r.name, r.lat, r.lon, r.pop)

    def match_name(self, team: str, iso2: str):
        d = self.by_cc.get(iso2)
        if not d:
            return None
        words = norm(team).split()
        best = None
        for n in (3, 2, 1):
            for i in range(len(words) - n + 1):
                gram = " ".join(words[i:i + n])
                if gram in d and (best is None or len(gram) > len(best[0]) or
                                  (len(gram) == len(best[0]) and d[gram][3] > d[best[0]][3])):
                    best = (gram, d[gram])
        return best[1][:3] if best else None

    def nearest(self, lat: float, lon: float, iso2: str = "", max_km: float = 40):
        df = self.df[self.df["cc"] == iso2] if iso2 else self.df
        if df.empty:
            df = self.df
        la, lo = np.radians(df["lat"].to_numpy()), np.radians(df["lon"].to_numpy())
        d = 2 * 6371 * np.arcsin(np.sqrt(np.sin((la - np.radians(lat)) / 2) ** 2 +
                                         np.cos(la) * np.cos(np.radians(lat)) * np.sin((lo - np.radians(lon)) / 2) ** 2))
        i = int(np.argmin(d))
        return df.iloc[i]["name"] if d[i] <= max_km else None


# ---------------------------------------------------------------- Wikipedia coordinates

GEO_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*;\s*(-?\d+(?:\.\d+)?)")


def page_coords(html: str) -> tuple[float, float] | None:
    soup = BeautifulSoup(html, "lxml")
    g = soup.select_one("span.geo")
    if g:
        m = GEO_RE.search(g.get_text(" ", strip=True))
        if m:
            return float(m.group(1)), float(m.group(2))
    return None


def ground_title(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")
    box = soup.find("table", class_=re.compile("infobox"))
    if not box:
        return None
    for tr in box.find_all("tr"):
        th = tr.find("th")
        if th and re.search(r"ground|stadium|venue|arena", th.get_text(" ", strip=True), re.I):
            links = wiki._links(tr.find("td"))
            if links:
                return wiki._title(links[0])
    return None


def wiki_coords(sess: PoliteSession, title: str) -> tuple[float, float] | None:
    try:
        html = sess.get(wiki.page_url(title.replace("_", " ")))
    except (FetchFailed, RobotsDisallowed):
        return None
    if not html:
        return None
    c = page_coords(html)
    if c:
        return c
    g = ground_title(html)
    if g:
        try:
            gh = sess.get(wiki.page_url(g.replace("_", " ")))
        except (FetchFailed, RobotsDisallowed):
            gh = None
        if gh:
            return page_coords(gh)
    return None


# ---------------------------------------------------------------- step

def clubs_to_locate(raw: Path) -> pd.DataFrame:
    frames = []
    for name in ("scorers_wikipedia", "scorers_transfermarkt", "manual_scorers_manual"):
        d = db.load(name, raw)
        if d is not None and len(d):
            if "team_title" not in d:
                d["team_title"] = ""
            d["goals"] = pd.to_numeric(d["goals"], errors="coerce").fillna(0)
            frames.append(d[["team", "competition", "team_title", "goals"]].rename(columns={"competition": "code"}))
    f = db.load("continental_finals", raw)
    if f is not None and len(f):
        for side in ("winner", "runner_up"):
            frames.append(pd.DataFrame({"team": f[side], "code": f[f"{side}_country"].map(lambda c: geo.country_codes(c)[0]),
                                        "team_title": "", "goals": 50}))     # finalists matter for the map
    if not frames:
        return pd.DataFrame(columns=["team", "code", "team_title"])
    c = pd.concat(frames, ignore_index=True)
    c = c[c["team"].map(lambda v: isinstance(v, str) and v.strip() != "")]
    c["team_title"] = c["team_title"].fillna("").astype(str)
    goals = c.groupby(["team", "code"])["goals"].sum()
    c = c.sort_values("team_title", ascending=False).drop_duplicates(["team", "code"]).set_index(["team", "code"])
    c["goals"] = goals
    return c.reset_index().sort_values("goals", ascending=False)      # most goals first


def title_guesses(team: str) -> list[str]:
    """Article titles to try when the scorer table didn't link the club."""
    t = team.strip()
    return [t, f"{t} F.C.", f"{t} FC"] if t else []


def build(raw: Path, cache: Path, sess: PoliteSession | None, iso2_of: dict, log=print,
          guess_titles: bool = True) -> pd.DataFrame:
    db.refresh(raw, log=lambda s: None)
    clubs = clubs_to_locate(raw)
    res = ClubResolver(raw, use_auto=False)
    out_path = raw / "club_locations_auto.csv"
    done = pd.read_csv(out_path) if out_path.exists() else pd.DataFrame(columns=["team", "country", "city", "lat", "lon", "method"])
    have = set(zip(done["team"], done["country"].fillna("")))
    todo = [r for r in clubs.itertuples(index=False)
            if res.resolve(r.team, r.code)[3] == "unresolved" and (r.team, r.code) not in have]
    log(f"  {len(clubs)} clubs, {len(todo)} need a location")
    try:
        gn = GeoNames(cache / "geonames")
    except (requests.RequestException, OSError, zipfile.BadZipFile) as e:
        gn = None
        log(f"  GeoNames unavailable ({type(e).__name__}); using Wikipedia only")
    rows, wiki_fails = [], 0
    for k, r in enumerate(todo, 1):
        iso2 = iso2_of.get(r.code) or geo.iso2_for_code(r.code)
        found = None
        titles = [r.team_title] if r.team_title else (title_guesses(r.team) if guess_titles else [])
        c = None
        for title in titles if sess is not None else []:
            c = wiki_coords(sess, title)
            if c:
                break
        if sess is not None and titles:
            if r.team_title:                      # guessed titles miss often; only linked ones count
                wiki_fails = 0 if c else wiki_fails + 1
            if wiki_fails >= 15:
                log("  Wikipedia isn't giving coordinates (15 misses in a row); continuing with GeoNames only")
                sess = None
            if c:
                city = (gn.nearest(c[0], c[1], iso2) if gn else None) or r.team
                found = (city, round(c[0], 3), round(c[1], 3), "wikipedia")
        if found is None and gn is not None:
            m = gn.match_name(r.team, iso2)
            if m:
                found = (m[0], round(m[1], 3), round(m[2], 3), "geonames")
        if found:
            rows.append({"team": r.team, "country": r.code, "city": found[0], "lat": found[1], "lon": found[2],
                         "method": found[3]})
        if k % 50 == 0:
            log(f"  ... {k}/{len(todo)}")
            _save(done, rows, out_path)
    df = _save(done, rows, out_path)
    total = clubs["goals"].sum() or 1
    left = {(r.team, r.code) for r in todo} - {(x["team"], x["country"]) for x in rows}
    missing_goals = clubs.set_index(["team", "code"]).loc[list(left), "goals"].sum() if left else 0
    log(f"  located {len(rows)} of {len(todo)} -> {out_path}")
    log(f"  clubs holding {1 - missing_goals / total:.0%} of all scorer goals now have a location; "
        f"the rest are listed by goals in data/raw/unresolved_clubs.csv after `assemble`")
    return df


def _save(done: pd.DataFrame, rows: list, path: Path) -> pd.DataFrame:
    df = pd.concat([done, pd.DataFrame(rows)], ignore_index=True).drop_duplicates(["team", "country"], keep="last")
    df.to_csv(path, index=False)
    return df
