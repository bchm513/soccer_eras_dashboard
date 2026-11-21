"""Build the database's analysis tables from everything collected.

    python -m scraper.run assemble

  1. sync data/football.db with data/raw/ and data/manual/ (only changed files)
  2. club rows: best source per league-season, players linked across sources   (linking.py)
  3. league scoring rate, club cup goals, map location for every club row
  4. international rows; tournament goals move to the main club row            (internationals.py)
  5. league strength for every league and season                              (strength.py)
  6. built tables: player_seasons, players, clubs, finals, moments

The main club row of a player-season is the club where he scored most; big-moment goals attach there.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from core import db
from core.competitions import CUP_COLUMNS, TIER_COLUMNS
from core.geo import country_codes
from . import internationals, linking, moments, strength
from .clubs import ClubResolver

COLUMNS = ["player_id", "player", "season", "competition", "comp_type", "confed", "team", "nationality",
           "club_city", "lat", "lon", "loc_source", "apps", "minutes", "team_games", "env_gpm", "intl_env_gpm",
           "goals", "penalties", "assists", "cup_goals", *CUP_COLUMNS, *TIER_COLUMNS,
           "comp_rank", "league_elo", "source"]
UNPLACED = ["unresolved", "no club"]


def assemble(raw: Path, leagues: list[dict], log=print) -> pd.DataFrame:
    db.refresh(raw, log)          # picks up edits to data/manual/ (and any step run outside scraper.run)
    club, canon = linking.club_rows(raw, log)
    enabled = {lg["code"] for lg in leagues if lg["enabled"]}
    off = ~club["competition"].isin(enabled)
    if off.any():
        log(f"  left out {int(off.sum())} rows from leagues not enabled in leagues.json")
    club = club[~off].copy()
    club["confed"] = club["competition"].map({lg["code"]: lg.get("confed", "") for lg in leagues})
    for c in ("team", "competition", "player", "nationality"):      # blank cells arrive as NaN
        club[c] = club[c].map(lambda v: v if isinstance(v, str) else "")

    # Scoring rates: the league's (club goals) and the international game's (tournament goals)
    club = club.merge(linking.scoring_environment(raw, leagues), on=["competition", "season"], how="left")
    club["comp_rank"] = club.groupby(["competition", "season"])["goals"].rank(method="min", ascending=False)
    intl_env = db.load("intl_environment", raw)
    if intl_env is None:
        raise SystemExit("No international data in the database. Run `python -m scraper.run env` first.")
    intl_env = intl_env[["season", "goals_per_team_match"]]
    club = club.merge(intl_env.rename(columns={"goals_per_team_match": "intl_env_gpm"}), on="season", how="left")

    # Main club row per player-season; club cup goals attach there
    club = club.sort_values("goals", ascending=False).reset_index(drop=True)
    main = ~club.duplicated(["player_id", "season"])
    club = club.merge(linking.cup_goals(raw, club, canon, log), on=["player_id", "season"], how="left")
    for c in CUP_COLUMNS:
        club[c] = club[c].fillna(0).where(main.to_numpy(), 0).astype(int)
    club["cup_goals"] = club[CUP_COLUMNS].sum(axis=1)

    resolver = ClubResolver(raw)
    club, placed = _locate(raw, club, resolver)
    club["comp_type"] = "club"
    club["apps"] = pd.NA            # weights use team games for every source, so eras stay comparable
    for c in ("assists", "minutes", "penalties"):
        if c not in club:
            club[c] = pd.NA

    club, ig = internationals.build(raw, club, main, intl_env)

    finals = _finals(raw, resolver)
    extra = sorted(set(finals["code"]) - {""}) if len(finals) else []
    ls = strength.build(raw, club, ig, leagues, extra_codes=extra, log=log)
    club = (club.merge(ls[["code", "season", "elo"]].rename(columns={"code": "competition", "elo": "league_elo"}),
                       on=["competition", "season"], how="left") if len(ls) else club.assign(league_elo=pd.NA))

    out = pd.concat([club.reindex(columns=COLUMNS), ig.reindex(columns=COLUMNS)], ignore_index=True)
    out = out.sort_values(["season", "competition", "player_id"])
    out.to_csv(raw / "player_seasons.csv", index=False)
    _built_tables(raw, out, finals, log)

    log(f"  club rows: {len(club)} in {club['competition'].nunique()} leagues "
        f"({int(club['env_gpm'].isna().sum())} without a league scoring rate)")
    log(f"  big moments on club rows: {int(club['cup_goals'].sum())} continental cup goals, "
        + ", ".join(f"{int(club[c].sum())} {c.replace('_', ' ')}" for c in TIER_COLUMNS))
    log(f"  international rows: {len(ig)} ({ig.attrs.get('linked', 0)} linked to club players)")
    log(f"  map locations: clubs holding {placed:.0%} of club goals are placed; the rest are in "
        "data/raw/unresolved_clubs.csv (most goals first; fixes go in data/manual/club_locations_manual.csv)")
    return out


def _locate(raw: Path, club: pd.DataFrame, resolver: ClubResolver) -> tuple[pd.DataFrame, float]:
    pairs = club[["team", "competition"]].drop_duplicates()
    locs = {(t, c): resolver.resolve(t, c) for t, c in pairs.itertuples(index=False)}
    loc = [locs[(t, c)] for t, c in zip(club["team"], club["competition"])]
    club["club_city"], club["lat"], club["lon"], club["loc_source"] = zip(*loc) if loc else ([], [], [], [])
    un = club[club["loc_source"].isin(UNPLACED) & (club["team"] != "")]
    (un.groupby(["team", "competition"])["goals"].sum().sort_values(ascending=False).reset_index()
       .rename(columns={"competition": "country"}).assign(city="", lat="", lon="")
       .to_csv(raw / "unresolved_clubs.csv", index=False))
    placed = club.loc[~club["loc_source"].isin(UNPLACED), "goals"].sum() / max(club["goals"].sum(), 1)
    return club, placed


def _finals(raw: Path, resolver: ClubResolver) -> pd.DataFrame:
    """Continental club finals, one row per finalist, with the club's country code and location."""
    f = db.load("continental_finals", raw)
    cols = ["comp", "confed", "season", "side", "team", "country", "code", "city", "lat", "lon", "attendance"]
    if f is None or f.empty:
        return pd.DataFrame(columns=cols)
    rows = []
    for r in f.itertuples():
        for side, team, country in (("winner", r.winner, r.winner_country), ("runner_up", r.runner_up, r.runner_up_country)):
            code = country_codes(country)[0]
            city, lat, lon, _ = resolver.resolve(str(team), code)
            rows.append({"comp": r.comp, "confed": getattr(r, "confed", ""), "season": int(r.season), "side": side,
                         "team": team, "country": country, "code": code, "city": city, "lat": lat, "lon": lon,
                         "attendance": getattr(r, "attendance", None)})
    return pd.DataFrame(rows, columns=cols)


def _built_tables(raw: Path, ps: pd.DataFrame, finals: pd.DataFrame, log=print) -> None:
    """player_seasons, players, clubs, finals, moments: the base for player, club and moment pages."""
    club = ps[ps["comp_type"] == "club"]
    big = ["cup_goals", *TIER_COLUMNS]
    players = club.groupby("player_id").agg(
        name=("player", "first"),
        nationality=("nationality", lambda s: next((x for x in s if isinstance(x, str) and x), "")),
        first_season=("season", "min"), last_season=("season", "max"), league_goals=("goals", "sum"),
        **{c: (c, "sum") for c in big},
        leagues=("competition", lambda s: "; ".join(sorted(set(s)))),
        clubs=("team", lambda s: "; ".join(dict.fromkeys(x for x in s if x))))
    intl = ps[ps["comp_type"] != "club"].groupby("player_id")["goals"].sum().rename("international_goals")
    players = players.join(intl, how="left").fillna({"international_goals": 0}).reset_index()
    clubs = (club.groupby(["team", "competition"])
             .agg(city=("club_city", "first"), lat=("lat", "first"), lon=("lon", "first"),
                  located_by=("loc_source", "first"), first_season=("season", "min"),
                  last_season=("season", "max"), goals=("goals", "sum"))
             .reset_index())
    for name, df in (("player_seasons", ps), ("players", players), ("clubs", clubs), ("finals", finals)):
        db.write(name, df, raw)
    moments.build(raw, finals, log)
