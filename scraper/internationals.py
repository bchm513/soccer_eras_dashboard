"""International rows, and the hand-over of tournament goals to club rows.

Each international scorer is linked to a club player by name (and nationality where it helps).
A linked player's tournament goals (World Cup, continental championships, other; see
core/competitions.py) move onto his main club row that season, where they count as big moments;
they leave the international row so nothing counts twice. Unlinked scorers keep everything.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from core import db
from core.common import norm
from core.competitions import TIER_COLUMNS


def link_ids(ig: pd.DataFrame, club: pd.DataFrame) -> pd.Series:
    """Club player id for each international row, else a stable 'intl:<name>:<country>' id."""
    known = club.drop_duplicates("player_id")[["player_id", "player", "nationality"]]
    by_name_nat = {(norm(str(p)), norm(str(n))): pid for pid, p, n in known.itertuples(index=False)}
    counts = known["player"].astype(str).map(norm).value_counts()
    by_name = {norm(str(p)): pid for pid, p, _ in known.itertuples(index=False) if counts[norm(str(p))] == 1}
    ids = {(p, n): by_name_nat.get((norm(str(p)), norm(str(n)))) or by_name.get(norm(str(p)))
           for p, n in ig[["player", "nationality"]].drop_duplicates().itertuples(index=False)}
    return pd.Series([ids.get((p, n)) or f"intl:{norm(str(p))}:{norm(str(n))}"
                      for p, n in zip(ig["player"], ig["nationality"])], index=ig.index)


def build(raw: Path, club: pd.DataFrame, main: pd.Series, intl_env: pd.DataFrame
          ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (club rows with tournament-goal columns, international rows)."""
    ig = db.load("intl_goals", raw)
    itg = db.load("intl_team_games", raw)
    if ig is None or itg is None:
        raise SystemExit("International data missing. Run `python -m scraper.run env`.")
    ig = (ig.merge(intl_env, on="season", how="left").merge(itg, on=["season", "team"], how="left")
          .rename(columns={"goals_per_team_match": "env_gpm", "scorer": "player", "team": "nationality"}))
    ig["team"] = ig["nationality"]
    missing = [c for c in TIER_COLUMNS if c not in ig]
    if missing:
        raise SystemExit(f"intl_goals has no {missing}: re-run `python -m scraper.run env`.")

    ig["player_id"] = link_ids(ig, club)
    linked = ~ig["player_id"].str.startswith("intl:")
    names = club.drop_duplicates("player_id").set_index("player_id")["player"]
    ig["player"] = [names.get(pid, p) for pid, p in zip(ig["player_id"], ig["player"])]

    is_main = main.to_numpy()
    has_club = set(zip(club.loc[is_main, "player_id"], club.loc[is_main, "season"]))
    movable = linked & pd.Series([(p, s) in has_club for p, s in zip(ig["player_id"], ig["season"])], index=ig.index)
    moved = ig[movable].groupby(["player_id", "season"])[TIER_COLUMNS].sum().reset_index()
    club = club.merge(moved, on=["player_id", "season"], how="left")
    for c in TIER_COLUMNS:
        club[c] = club[c].fillna(0).where(is_main, 0).astype(int)
    ig.loc[movable, "goals"] = (ig.loc[movable, "goals"] - ig.loc[movable, TIER_COLUMNS].sum(axis=1)).clip(lower=0)
    for c in TIER_COLUMNS:
        ig[c] = ig[c].where(~movable, 0)
    ig = ig.assign(competition="INT", comp_type="international", club_city=None, lat=None, lon=None,
                   loc_source=None, apps=pd.NA, minutes=pd.NA, comp_rank=pd.NA, confed="",
                   source="martj42/international_results")
    ig.attrs["linked"] = int(linked.sum())
    return club, ig
