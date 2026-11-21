"""League strength for every league and season, on one Elo scale.

  1. ClubElo (Europe), when `python -m scraper.run elo` has run: the mean rating of the league's
     top-division clubs. Used as is.
  2. Everywhere else: the country's national-team Elo (scraper/world.py), mapped onto the ClubElo
     scale with a line fitted on the league-seasons that have both. With no ClubElo at all, the
     national rating is used directly for every league.
  3. Talent exodus: a national team's strength overstates its league when its best players are
     abroad. Retention = share of the country's competitive international goals scored by players
     at home-league clubs that season (smoothed over 7 seasons). Strength drops by
     EXODUS_ELO x (1 - retention). Brazil kept Zico in the 1980s; it didn't keep Neymar.

    -> data/raw/league_strength_world.csv: code, season, elo, source, national_elo, retention
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from core import db, geo

EXODUS_ELO = 150        # Elo lost by a league whose national-team scorers all play abroad
RETENTION_WINDOW = 3    # seasons either side for the retention average
MIN_RETENTION_GOALS = 8 # goals needed in the window before retention is trusted


def national_for(codes: list[str], ne: pd.DataFrame, first: int, last: int) -> pd.DataFrame:
    idx = ne.set_index(["team", "season"])["elo"]
    rows = []
    for code in codes:
        for s in range(first, last + 1):
            team = geo.team_for(code, s)
            v = idx.get((team, s)) if team else None
            if v is not None and not pd.isna(v):
                rows.append({"code": code, "season": s, "national_elo": float(v)})
    return pd.DataFrame(rows)


def retention(club: pd.DataFrame, ig: pd.DataFrame, codes: list[str]) -> pd.DataFrame:
    """Share of each country's (linked) international goals scored by home-league players."""
    team_of = {}
    for c in codes:
        t = geo.CODE_TO_TEAM.get(c)
        if t:
            team_of.setdefault(t, c)
    home = club.groupby(["player_id", "season"])["competition"].agg(lambda s: set(s)).to_dict()
    rows = []
    linked = ig[~ig["player_id"].astype(str).str.startswith("intl:")]
    for r in linked.itertuples(index=False):
        code = team_of.get(r.nationality)
        comps = home.get((r.player_id, r.season))
        if not code or comps is None:
            continue
        rows.append({"code": code, "season": int(r.season), "goals": r.goals, "home": r.goals * (code in comps)})
    if not rows:
        return pd.DataFrame(columns=["code", "season", "retention"])
    d = pd.DataFrame(rows).groupby(["code", "season"])[["goals", "home"]].sum()
    out = []
    for code, g in d.groupby(level=0):
        g = g.droplevel(0)
        seasons = np.arange(g.index.min(), g.index.max() + 1)
        g = g.reindex(seasons, fill_value=0)
        w = g.rolling(2 * RETENTION_WINDOW + 1, center=True, min_periods=1).sum()
        r = (w["home"] / w["goals"]).where(w["goals"] >= MIN_RETENTION_GOALS)
        out += [{"code": code, "season": int(s), "retention": round(float(v), 3)} for s, v in r.dropna().items()]
    return pd.DataFrame(out)


def build(raw: Path, club: pd.DataFrame, ig: pd.DataFrame, leagues: list[dict], extra_codes: list[str] = (),
          log=print) -> pd.DataFrame:
    """Strength per (code, season) for every league in the registry plus extra country codes."""
    codes = sorted({lg["code"] for lg in leagues} | set(extra_codes))
    first, last = 1946, int(max(club["season"].max(), 2025))
    ne = db.load("national_elo", raw)
    if ne is None:
        log("  league strength: national_elo missing (run `python -m scraper.run env`); skipping")
        return pd.DataFrame()
    nat = national_for(codes, ne, first, last)
    ce = db.load("league_strength", raw)          # ClubElo, from the optional `elo` step
    ce = (ce.rename(columns={"competition": "code", "elo_mean": "clubelo"}) if ce is not None
          else pd.DataFrame(columns=["code", "season", "clubelo"]))
    df = nat.merge(ce[["code", "season", "clubelo"]], on=["code", "season"], how="outer")

    both = df.dropna(subset=["national_elo", "clubelo"])
    if len(both) >= 30:
        b, a = np.polyfit(both["national_elo"], both["clubelo"], 1)
        how = f"fitted on {len(both)} ClubElo league-seasons: club Elo = {a:.0f} + {b:.2f} x national Elo"
    else:
        a, b = 0.0, 1.0
        how = "no ClubElo yet: national Elo used directly"
    ret = retention(club, ig, codes)
    df = df.merge(ret, on=["code", "season"], how="left")
    conf = {lg["code"]: lg.get("confed", "") for lg in leagues}
    df["confed"] = df["code"].map(conf).fillna("")
    # Missing retention: the confederation's median that season, else no correction
    med = df.groupby(["confed", "season"])["retention"].transform("median")
    df["retention"] = df["retention"].fillna(med).fillna(1.0)
    mapped = a + b * df["national_elo"] - EXODUS_ELO * (1 - df["retention"])
    df["elo"] = df["clubelo"].where(df["clubelo"].notna(), mapped).round(1)
    df["source"] = np.where(df["clubelo"].notna(), "clubelo", "national")
    df = df.dropna(subset=["elo"]).sort_values(["season", "code"])
    out = df[["code", "season", "elo", "source", "national_elo", "clubelo", "retention"]]
    out.to_csv(raw / "league_strength_world.csv", index=False)
    db.write("league_strength_world", out, raw)
    log(f"  league strength: {df['code'].nunique()} countries, {how}; "
        f"exodus correction {EXODUS_ELO} Elo x (1 - retention)")
    return df
