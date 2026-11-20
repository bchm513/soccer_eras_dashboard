"""Everything derived from the international results data (martj42), no scraping needed:

  tournament goals   major final-tournament goals split from qualifiers and other matches
  tournament editions every World Cup, Euro, Copa América, AFCON, Asian Cup, Gold Cup...: host,
                      final city, dates
  growth             nations playing, matches per season, and each country's first international
  national Elo       a World Football Elo-style rating for every national team, every season

Seasons run August -> July and are labelled by their first year, as everywhere else.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from . import geo

# Major final tournaments -> tier. Qualifiers and everything else stay "other".
MAJOR = {
    "FIFA World Cup": "world_cup",
    "UEFA Euro": "continental", "Copa América": "continental", "African Cup of Nations": "continental",
    "AFC Asian Cup": "continental", "Gold Cup": "continental", "CONCACAF Championship": "continental",
    "Confederations Cup": "continental", "Oceania Nations Cup": "continental",
}
# Shown on the map (World Cup and Euro hosts come from pipeline/tournaments.py with exact venues)
MAP_TOURNAMENTS = {"Copa América": "Copa América", "African Cup of Nations": "AFCON",
                   "AFC Asian Cup": "Asian Cup", "Gold Cup": "Gold Cup",
                   "CONCACAF Championship": "Gold Cup", "Confederations Cup": "Confederations Cup"}


def season_of(dates: pd.Series) -> pd.Series:
    d = pd.to_datetime(dates, errors="coerce")
    return (d.dt.year - (d.dt.month < 8).astype(int)).astype("Int64")


# ---------------------------------------------------------------- tournament goals

def tournament_goal_columns(gs: pd.DataFrame, res: pd.DataFrame) -> pd.DataFrame:
    """Per (season, team, scorer): world_cup_goals and continental_goals (final tournaments only)."""
    m = gs.merge(res[["date", "home_team", "away_team", "tournament"]],
                 on=["date", "home_team", "away_team"], how="left")
    m["tier"] = m["tournament"].map(MAJOR).fillna("other")
    m["season"] = season_of(m["date"])
    m = m[m["own_goal"].astype(str).str.upper() != "TRUE"]
    out = (m.assign(world_cup_goals=(m["tier"] == "world_cup").astype(int),
                    continental_goals=(m["tier"] == "continental").astype(int))
           .groupby(["season", "team", "scorer"])[["world_cup_goals", "continental_goals"]].sum()
           .reset_index())
    return out


# ---------------------------------------------------------------- tournament editions

def tournament_editions(res: pd.DataFrame, gap_days: int = 60) -> pd.DataFrame:
    """One row per edition of each mapped tournament: host country(ies), final city and dates."""
    rows = []
    r = res[res["tournament"].isin(MAP_TOURNAMENTS)].copy()
    r["date"] = pd.to_datetime(r["date"], errors="coerce")
    r = r.dropna(subset=["date"]).sort_values("date")
    for name, g in r.groupby("tournament"):
        edition = (g["date"].diff().dt.days.fillna(0) > gap_days).cumsum()
        for _, e in g.groupby(edition):
            if len(e) < 4:           # stray fixtures, not a tournament
                continue
            counts = e["country"].value_counts()
            hosts = [c for c, n in counts.items() if n >= 0.25 * len(e)][:3] or [counts.index[0]]
            final = e.iloc[-1]
            coords = geo.country_coords(final["country"]) or geo.country_coords(hosts[0])
            if not coords:
                continue
            rows.append({"type": MAP_TOURNAMENTS[name], "year": int(final["date"].year),
                         "host": " & ".join(hosts), "city": str(final["city"]),
                         "lat": round(coords[0], 2), "lon": round(coords[1], 2),
                         "start": e["date"].min().strftime("%Y-%m"), "end": e["date"].max().strftime("%Y-%m"),
                         "matches": len(e)})
    return pd.DataFrame(rows).sort_values(["year", "type"]) if rows else pd.DataFrame()


# ---------------------------------------------------------------- growth of the game

def growth(res: pd.DataFrame, first: int = 1946) -> tuple[pd.DataFrame, pd.DataFrame]:
    r = res.copy()
    r["season"] = season_of(r["date"])
    r = r.dropna(subset=["season"])
    long = pd.concat([r[["season", "home_team", "tournament"]].rename(columns={"home_team": "team"}),
                      r[["season", "away_team", "tournament"]].rename(columns={"away_team": "team"})])
    first_season = long.groupby("team")["season"].min()
    per = []
    seen: set = set()
    for s in range(int(r["season"].min()), int(r["season"].max()) + 1):
        teams = set(long.loc[long["season"] == s, "team"])
        seen |= teams
        rs = r[r["season"] == s]
        per.append({"season": s, "nations_active": len(teams), "nations_total": len(seen),
                    "matches": len(rs), "competitive_matches": int((rs["tournament"] != "Friendly").sum())})
    g = pd.DataFrame(per)
    g = g[g["season"] >= first]
    # Map countries: earliest first international among the teams that map to them
    cf = (first_season.rename("first_season").reset_index()
          .assign(country=lambda d: d["team"].map(geo.map_name))
          .groupby("country")["first_season"].min().astype(int).reset_index())
    return g, cf


# ---------------------------------------------------------------- national Elo

K_BY_TOURNAMENT = {"FIFA World Cup": 60}


def _k(tournament: str) -> int:
    if tournament in K_BY_TOURNAMENT:
        return K_BY_TOURNAMENT[tournament]
    if tournament in MAJOR:
        return 50
    if "qualification" in tournament or tournament in ("UEFA Nations League", "CONCACAF Nations League"):
        return 40
    if tournament == "Friendly":
        return 20
    return 30


def national_elo(res: pd.DataFrame, first: int = 1946) -> pd.DataFrame:
    """World Football Elo-style ratings (K by match importance, goal-difference multiplier,
    100-point home advantage), snapshotted at the end of each season (31 July)."""
    r = res.dropna(subset=["home_score", "away_score"]).copy()
    r["date"] = pd.to_datetime(r["date"], errors="coerce")
    r = r.dropna(subset=["date"]).sort_values("date")
    r["season"] = (r["date"].dt.year - (r["date"].dt.month < 8).astype(int))
    rating: dict[str, float] = {}
    snaps, current = [], None
    for row in r.itertuples(index=False):
        if current is not None and row.season != current:
            snaps.extend((t, current, v) for t, v in rating.items())
        current = row.season
        h, a = row.home_team, row.away_team
        rh, ra = rating.get(h, 1500.0), rating.get(a, 1500.0)
        adv = 0.0 if str(row.neutral).upper() == "TRUE" else 100.0
        we = 1.0 / (10 ** (-(rh + adv - ra) / 400) + 1)
        gd = abs(row.home_score - row.away_score)
        mult = 1.0 if gd <= 1 else 1.5 if gd == 2 else (11 + gd) / 8
        w = 1.0 if row.home_score > row.away_score else 0.5 if row.home_score == row.away_score else 0.0
        d = _k(str(row.tournament)) * mult * (w - we)
        rating[h], rating[a] = rh + d, ra - d
    if current is not None:
        snaps.extend((t, current, v) for t, v in rating.items())
    out = pd.DataFrame(snaps, columns=["team", "season", "elo"])
    out["elo"] = out["elo"].round(1)
    return out[out["season"] >= first].reset_index(drop=True)


# ---------------------------------------------------------------- build

def build(raw: Path, res: pd.DataFrame, gs: pd.DataFrame, first: int = 1946, log=print) -> None:
    te = tournament_editions(res)
    te = te[te["year"] >= first] if len(te) else te
    te.to_csv(raw / "tournament_editions.csv", index=False)
    log(f"  tournament editions: {len(te)} ({', '.join(f'{t} {n}' for t, n in te['type'].value_counts().items())})")
    g, cf = growth(res, first)
    g.to_csv(raw / "growth.csv", index=False)
    cf.to_csv(raw / "country_first.csv", index=False)
    log(f"  growth: {int(g['nations_active'].iloc[0])} nations active in {int(g['season'].iloc[0])}, "
        f"{int(g['nations_active'].iloc[-2])} in {int(g['season'].iloc[-2])}")
    ne = national_elo(res, first)
    ne.to_csv(raw / "national_elo.csv", index=False)
    log(f"  national Elo: {ne['team'].nunique()} teams, seasons {ne['season'].min()}-{ne['season'].max()}")
