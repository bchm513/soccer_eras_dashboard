"""Club scorer rows from every source, one id per player across sources, cup goals per player.

Sources, best first for any league-season more than one covers:
    manual_scorers_manual   your own rows (data/manual/scorers_manual.csv)
    scorers_transfermarkt   2012-, full league, goals + assists + minutes
    scorers_wikipedia       1946-, season pages' top scorers, plus leader lists for gaps
The same player is linked across sources by name when the name is unambiguous in every source.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from core import db
from core.common import is_player, norm
from core.competitions import CUP_CODES, cup_column

SOURCES = [("manual_scorers_manual", "manual", "man:"),        # table, label, id prefix
           ("scorers_transfermarkt", "transfermarkt", ""),     # ids already "tm:<id>"
           ("scorers_wikipedia", "wikipedia", "wiki:")]
CANON_ORDER = ("wiki", "tm", "man")                             # whose id a linked player keeps


def club_rows(raw: Path, log=print) -> tuple[pd.DataFrame, dict]:
    """All club scorer rows (best source per league-season) and the id map used to link them."""
    frames, covered = [], set()
    for name, label, prefix in SOURCES:
        df = db.load(name, raw)
        if df is None or df.empty:
            continue
        if label == "manual":                              # blank template rows are skipped
            df = df[df["player"].map(is_player) & pd.to_numeric(df["goals"], errors="coerce").notna()].copy()
            if df.empty:
                continue
            df["player_id"] = df["player"]
            df["season"] = df["season"].astype(int)
        df["player_id"] = prefix + df["player_id"].astype(str)   # source prefix keeps ids apart
        df["source"] = label
        keys = set(zip(df["competition"], df["season"]))
        df = df[[k not in covered for k in zip(df["competition"], df["season"])]]
        covered |= keys
        frames.append(df)
        log(f"  {label}: {len(df)} rows used")
    if not frames:
        raise SystemExit("No club scorer data yet. Run `python -m scraper.run scorers` first.")
    club = pd.concat(frames, ignore_index=True)
    junk = ~club["player"].map(is_player)
    if junk.any():
        log(f"  dropped {int(junk.sum())} summary or blank rows ('Total:', '22 players', ...)")
    club = club[~junk]

    club["_k"] = club["player"].astype(str).map(norm)
    canon = {}
    for _, ids in club.groupby("_k")["player_id"].agg(lambda s: sorted(set(s))).items():
        by_src: dict[str, list] = {}
        for i in ids:
            by_src.setdefault(i.split(":")[0], []).append(i)
        if all(len(v) == 1 for v in by_src.values()):          # one id per source -> same person
            best = next((by_src[s][0] for s in CANON_ORDER if s in by_src), ids[0])
            canon.update({i: best for i in ids})
    club["player_id"] = club["player_id"].map(lambda i: canon.get(i, i))
    return club.drop(columns="_k"), canon


def linker(club: pd.DataFrame, canon: dict):
    """Function (source id, name) -> club player id, or None when the player can't be linked."""
    known = set(club["player_id"])
    names = club.drop_duplicates("player_id")[["player_id", "player"]]
    counts = names["player"].map(norm).value_counts()
    by_name = {norm(p): pid for pid, p in names.itertuples(index=False) if counts.get(norm(p), 0) == 1}

    def link(pid, name):
        pid = canon.get(pid, pid)
        return pid if pid in known else by_name.get(norm(name))
    return link


def cup_goals(raw: Path, club: pd.DataFrame, canon: dict, log=print) -> pd.DataFrame:
    """Continental club cup goals per (player_id, season), one column per competition.
    Transfermarkt is complete for the Champions League and Europa League from 2012 and wins there;
    Wikipedia's season top-scorer tables cover everything else."""
    frames, tm_first = [], {}
    tm = db.load("scorers_cups_transfermarkt", raw)
    if tm is not None and len(tm):
        tm["player_id"] = tm["player_id"].astype(str)
        tm_first = tm.groupby("competition")["season"].min().to_dict()
        frames.append(tm)
    wk = db.load("scorers_continental_wikipedia", raw)
    if wk is not None and len(wk):
        wk["player_id"] = "wiki:" + wk["player_id"].astype(str)
        drop = pd.Series(False, index=wk.index)
        for comp, s0 in tm_first.items():
            drop |= (wk["competition"] == comp) & (wk["season"] >= s0)
        frames.append(wk[~drop])
    cols = [cup_column(c) for c in CUP_CODES]
    if not frames:
        return pd.DataFrame(columns=["player_id", "season", *cols])
    u = pd.concat(frames, ignore_index=True)
    u = u[u["player"].map(is_player)]
    link = linker(club, canon)
    u["player_id"] = [link(p, n) for p, n in zip(u["player_id"], u["player"])]
    ok = u["player_id"].notna()
    by = u[ok].groupby("competition").size().to_dict()
    log(f"  continental cups: {int(ok.sum())} of {len(u)} scorer-seasons linked to club players "
        f"({', '.join(f'{k} {v}' for k, v in sorted(by.items()))})")
    wide = (u[ok].groupby(["player_id", "season", "competition"])["goals"].sum()
            .unstack(fill_value=0).reindex(columns=CUP_CODES, fill_value=0))
    wide.columns = cols
    return wide.reset_index()


def scoring_environment(raw: Path, leagues: list[dict]) -> pd.DataFrame:
    """League goals per team match per (league code, season): engsoccerdata first, else the
    season page's league table."""
    frames = []
    esd = db.load("league_environment", raw)
    for lg in leagues:
        if lg.get("env") and esd is not None:
            e = esd[esd["competition"] == lg["env"]].assign(competition=lg["code"])
            frames.append(e[["competition", "season", "goals_per_team_match", "team_games"]])
    w = db.load("league_environment_wiki", raw)
    if w is not None and len(w):
        frames.append(w[["competition", "season", "goals_per_team_match", "team_games"]])
    if not frames:
        return pd.DataFrame(columns=["competition", "season", "env_gpm", "team_games"])
    env = pd.concat(frames, ignore_index=True).drop_duplicates(["competition", "season"], keep="first")
    return env.rename(columns={"goals_per_team_match": "env_gpm"})
