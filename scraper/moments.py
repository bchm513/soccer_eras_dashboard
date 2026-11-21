"""Major moments: the stories behind the numbers, shown as diamonds on the map and in the
description panel, and the base for moment pages later.

    tournament finals   every World Cup, Euro, Copa América, AFCON... final: winner, score (penalties
                        included), city, top scorer(s)       <- international results data (`env` step)
    club finals         every continental club final: winner, runner-up, crowd  <- `continental` step
    your own            data/manual/moments_manual.csv (season,date,title,detail,teams,players,lat,lon,weight)

`assemble` combines them into the `moments` table (and data/raw/moments.csv).
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd

from core import db, geo
from core.common import norm
from core.competitions import CLUB_CUPS, TOURNAMENTS
from .clubs import CITIES

COLUMNS = ["season", "date", "kind", "title", "detail", "teams", "players", "lat", "lon", "weight", "source"]


class CityFinder:
    """Coordinates for a city name: the project's city list, then GeoNames (downloaded by `locate`)."""

    def __init__(self, cache: Path | None):
        self.coords: dict[str, tuple[float, float]] = {}
        gn = cache / "geonames" / "cities15000.txt" if cache else None
        if gn is not None and gn.exists():
            df = pd.read_csv(gn, sep="\t", header=None, quoting=3, dtype=str, keep_default_na=False,
                             usecols=[1, 2, 4, 5, 14], names=["name", "ascii", "lat", "lon", "pop"])
            df["pop"] = pd.to_numeric(df["pop"], errors="coerce").fillna(0)
            for r in df.sort_values("pop").itertuples(index=False):      # bigger cities win a shared name
                for n in {norm(r.name), norm(r.ascii)}:
                    self.coords[n] = (float(r.lat), float(r.lon))
        for r in csv.DictReader(CITIES.open(encoding="utf-8")):
            self.coords[norm(r["city"])] = (float(r["lat"]), float(r["lon"]))

    def __call__(self, city: str, country: str) -> tuple:
        return self.coords.get(norm(city)) or geo.country_coords(country) or (None, None)


def tournament_finals(res: pd.DataFrame, gs: pd.DataFrame, shootouts: pd.DataFrame | None,
                      cache: Path | None = None, gap_days: int = 60) -> pd.DataFrame:
    """One moment per tournament edition with a final."""
    find = CityFinder(cache)
    r = res[res["tournament"].isin(TOURNAMENTS)].dropna(subset=["home_score", "away_score"]).copy()
    r["date"] = pd.to_datetime(r["date"], errors="coerce")
    r = r.dropna(subset=["date"]).sort_values("date")
    pens = {} if shootouts is None else {
        (d, h, a): w for d, h, a, w in shootouts[["date", "home_team", "away_team", "winner"]].itertuples(index=False)}
    g = gs.copy()
    g["date"] = pd.to_datetime(g["date"], errors="coerce")
    g = g[g["own_goal"].astype(str).str.upper() != "TRUE"]
    rows = []
    for name, tg in r.groupby("tournament"):
        t = TOURNAMENTS[name]
        edition = (tg["date"].diff().dt.days.fillna(0) > gap_days).cumsum()
        for _, e in tg.groupby(edition):
            if len(e) < 4:                # stray fixtures, not a tournament
                continue
            f = e.iloc[-1]
            hs, as_ = int(f["home_score"]), int(f["away_score"])
            key = (f["date"].strftime("%Y-%m-%d"), f["home_team"], f["away_team"])
            if hs != as_:
                winner, loser = (f["home_team"], f["away_team"]) if hs > as_ else (f["away_team"], f["home_team"])
                beat = f"Beat {loser} {max(hs, as_)}–{min(hs, as_)}"
            elif key in pens:
                winner = pens[key]
                loser = f["away_team"] if winner == f["home_team"] else f["home_team"]
                beat = f"Beat {loser} on penalties after a {hs}–{as_} draw"
            else:
                continue                  # round-robin finish: no single final to report
            matches = set(zip(e["date"], e["home_team"], e["away_team"]))
            ed = g[[k in matches for k in zip(g["date"], g["home_team"], g["away_team"])]]
            top = ed.groupby("scorer").size().sort_values(ascending=False)
            best = top[top == top.max()].index.tolist()[:3] if len(top) else []
            lat, lon = find(f["city"], f["country"])
            year = int(f["date"].year)
            rows.append({"season": year - (f["date"].month < 8), "date": key[0], "kind": "tournament",
                         "title": f"{winner} win the {t.name} {year}",
                         "detail": f"{beat} in {f['city']}." +
                                   (f" Top scorer: {', '.join(best)} ({int(top.max())})." if best else ""),
                         "teams": f"{winner}; {loser}", "players": "; ".join(best),
                         "lat": lat, "lon": lon, "weight": t.moment_weight,
                         "source": "martj42/international_results"})
    return pd.DataFrame(rows, columns=COLUMNS)


def club_finals(finals: pd.DataFrame) -> pd.DataFrame:
    """One moment per continental club final, at the winner's city (from the `finals` table)."""
    w = finals[finals["side"] == "winner"].merge(
        finals[finals["side"] == "runner_up"][["comp", "season", "team"]].rename(columns={"team": "runner_up"}),
        on=["comp", "season"], how="left")
    rows = []
    for r in w.itertuples():
        cup = CLUB_CUPS.get(r.comp)
        att = pd.to_numeric(r.attendance, errors="coerce")
        rows.append({"season": int(r.season), "date": "", "kind": "club_final",
                     "title": f"{r.team} win the {cup.name_in(int(r.season)) if cup else r.comp} {int(r.season)}",
                     "detail": (f"Beat {r.runner_up} in the final." if isinstance(r.runner_up, str) else "Won the final.")
                               + (f" Crowd: {int(att):,}." if pd.notna(att) else ""),
                     "teams": "; ".join(x for x in (r.team, r.runner_up) if isinstance(x, str)), "players": "",
                     "lat": r.lat, "lon": r.lon, "weight": cup.moment_weight if cup else 1, "source": "Wikipedia"})
    return pd.DataFrame(rows, columns=COLUMNS)


def build(raw: Path, finals: pd.DataFrame | None, log=print) -> pd.DataFrame:
    parts = []
    t = db.load("moments_tournaments", raw)
    if t is not None and len(t):
        parts.append(t)
    if finals is not None and len(finals):
        parts.append(club_finals(finals))
    m = db.load("manual_moments_manual", raw)
    if m is not None and len(m):
        m = m[m["title"].map(lambda v: isinstance(v, str) and v.strip() != "")]
        parts.append(m.assign(kind="manual", source="manual"))
    parts = [p for p in parts if len(p)]
    if not parts:
        return pd.DataFrame(columns=COLUMNS)
    allm = pd.concat(parts, ignore_index=True).reindex(columns=COLUMNS).sort_values(["season", "date"])
    allm.to_csv(raw / "moments.csv", index=False)
    db.write("moments", allm, raw)
    log(f"  moments: {len(allm)} ({', '.join(f'{k} {v}' for k, v in allm['kind'].value_counts().items())})")
    return allm
