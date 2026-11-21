"""Transfermarkt open dataset (dcaribou/transfermarkt-datasets): every player-game in the big
leagues from the 2012-13 season, with goals, assists and minutes. Downloaded as published
CSV files; nothing is scraped.

    -> data/raw/scorers_transfermarkt.csv
       player_id, player, nationality, team, competition, season, goals, assists, minutes, apps

The collection pipeline stopped in mid-2026, so the last complete season is 2025-26.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from core.common import season_of
from .environment import _download

BASE = "https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/{}.csv.gz"
NEEDED = {
    "appearances": {"player_id", "player_club_id", "date", "competition_id", "goals", "assists", "minutes_played"},
    "players": {"player_id", "name"},
    "clubs": {"club_id", "name"},
}


def _load(table: str, cache: Path) -> pd.DataFrame:
    f = _download(BASE.format(table), cache / f"tm_{table}.csv.gz")
    df = pd.read_csv(f, low_memory=False)
    missing = NEEDED[table] - set(df.columns)
    if missing:
        raise SystemExit(f"Transfermarkt '{table}' table is missing columns {sorted(missing)}; "
                         "the dataset layout may have changed. Check the repo's README.")
    return df


def build(raw: Path, cache: Path, leagues: list[dict], min_goals: int = 1) -> pd.DataFrame:
    comp_map = {lg["tm"]: lg["code"] for lg in leagues if lg.get("tm")}
    app_all = _load("appearances", cache)
    out = _aggregate(app_all, comp_map, cache, min_goals)
    out.to_csv(raw / "scorers_transfermarkt.csv", index=False)
    print(f"  Transfermarkt leagues: {len(out)} player-seasons with goals, "
          + ", ".join(f"{c} {s.season.min()}-{s.season.max()}" for c, s in out.groupby("competition")))
    cups = _aggregate(app_all, {"CL": "UCL", "EL": "UEL"}, cache, min_goals)
    if len(cups):
        cups.to_csv(raw / "scorers_cups_transfermarkt.csv", index=False)
        print(f"  Transfermarkt Champions League + Europa League: {len(cups)} player-seasons, "
              f"{cups.season.min()}-{cups.season.max()}")
    return out


def _aggregate(app: pd.DataFrame, comp_map: dict, cache: Path, min_goals: int) -> pd.DataFrame:
    app = app[app["competition_id"].isin(comp_map)].copy()
    app["season"] = season_of(app["date"])
    g = (app.groupby(["player_id", "player_club_id", "competition_id", "season"])
         .agg(goals=("goals", "sum"), assists=("assists", "sum"),
              minutes=("minutes_played", "sum"), apps=("date", "size"))
         .reset_index())
    g = g[g["goals"] >= min_goals]

    players = _load("players", cache)
    nat_col = next((c for c in ("country_of_citizenship", "country_of_birth") if c in players), None)
    players = players.rename(columns={"name": "player"})[["player_id", "player"] + ([nat_col] if nat_col else [])]
    players = players.rename(columns={nat_col: "nationality"}) if nat_col else players.assign(nationality="")
    clubs = _load("clubs", cache).rename(columns={"club_id": "player_club_id", "name": "team"})[["player_club_id", "team"]]

    out = (g.merge(players, on="player_id", how="left").merge(clubs, on="player_club_id", how="left"))
    out["competition"] = out["competition_id"].map(comp_map)
    out["player_id"] = "tm:" + out["player_id"].astype(str)
    out["team"] = out["team"].fillna("").map(_clean_club)
    return out[["player_id", "player", "nationality", "team", "competition", "season",
                "goals", "assists", "minutes", "apps"]].sort_values(["competition", "season", "goals"],
                                                                 ascending=[True, True, False])


def _clean_club(name: str) -> str:
    """Transfermarkt uses formal names ('Real Madrid Club de Fútbol'); trim common legal suffixes."""
    for junk in (" Football Club", " Futbol Club", " Club de Fútbol", " Fútbol Club", " S.p.A.", " S.A.D.",
                 " e.V.", " GmbH & Co. KGaA", " Ltd.", " plc"):
        name = name.replace(junk, "")
    return name.strip()
