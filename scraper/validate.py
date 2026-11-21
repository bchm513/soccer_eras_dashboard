"""Check the database's league goals against figures you look up (Wikipedia, RSSSF, league sites).

    python -m scraper.run validate

Add rows to data/manual/reference_goals.csv:

    player,competition,season,goals,source
    Gerd Müller,GER,,365,bundesliga.com          <- blank season: a career total in that league
    Lionel Messi,ESP,2011,50,Wikipedia           <- a season (starting year: 2011 = 2011-12)

A season row is a direct check: the numbers should match.
A career row can't match exactly before 2012, because the scraper only has each season's top
scorers: seasons where the player wasn't near the top are missing. The report lists the seasons
it has, the gaps in the player's span, and how many goals those gaps must hold.

    -> data/raw/validation.csv, and a summary in the terminal
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from core import db
from core.common import norm, season_label
from core.paths import manual_dir

TEMPLATE = "player,competition,season,goals,source\n"


def build(raw: Path, log=print) -> pd.DataFrame:
    ref_path = manual_dir(raw) / "reference_goals.csv"
    if not ref_path.exists():
        ref_path.write_text(TEMPLATE, encoding="utf-8")
    ref = pd.read_csv(ref_path)
    if ref.empty:
        log(f"  No reference figures yet. Add rows to {ref_path} (see scraper/validate.py for the format).")
        return pd.DataFrame()
    ps = db.load("player_seasons", raw)
    if ps is None:
        raise SystemExit("No player_seasons table. Run `python -m scraper.run assemble` first.")
    club = ps[ps["comp_type"] == "club"].assign(_k=lambda d: d["player"].map(norm))

    rows = []
    for r in ref.itertuples():
        mine = club[(club["_k"] == norm(r.player)) & (club["competition"] == r.competition)]
        expected = int(r.goals)
        if pd.notna(r.season):
            s = int(r.season)
            got = int(mine.loc[mine["season"] == s, "goals"].sum()) if (mine["season"] == s).any() else None
            status = "not in data" if got is None else "match" if got == expected else "MISMATCH"
            rows.append({"player": r.player, "competition": r.competition, "check": season_label(s),
                         "reference": expected, "database": got, "difference": None if got is None else got - expected,
                         "status": status, "detail": "", "source": r.source})
            continue
        if mine.empty:
            rows.append({"player": r.player, "competition": r.competition, "check": "career",
                         "reference": expected, "database": None, "difference": None,
                         "status": "not in data", "detail": "no club seasons under this name and league", "source": r.source})
            continue
        seasons = sorted(mine["season"].astype(int).unique())
        got = int(mine["goals"].sum())
        gaps = [s for s in range(seasons[0], seasons[-1] + 1) if s not in seasons]
        short = expected - got
        if short == 0:
            status = "match"
        elif short > 0:
            status = "missing seasons"         # expected before 2012: only top scorers are listed
        else:
            status = "MORE than reference"     # worth a look: duplicate rows or a name clash
        detail = (f"{len(seasons)} seasons {seasons[0]}-{seasons[-1]}"
                  + (f"; gaps: {', '.join(season_label(s) for s in gaps)}" if gaps else "")
                  + (f"; {short} goals in seasons not captured (gaps, or before {season_label(seasons[0])} / after {season_label(seasons[-1])})" if short > 0 else ""))
        rows.append({"player": r.player, "competition": r.competition, "check": "career",
                     "reference": expected, "database": got, "difference": got - expected,
                     "status": status, "detail": detail, "source": r.source})

    out = pd.DataFrame(rows)
    out.to_csv(raw / "validation.csv", index=False)
    for x in out.itertuples():
        db_txt = "—" if x.database is None or pd.isna(x.database) else int(x.database)
        log(f"  {x.status:20s} {x.player} {x.competition} {x.check}: database {db_txt}, reference {x.reference}"
            + (f"  ({x.detail})" if x.detail else ""))
    bad = out["status"].isin(["MISMATCH", "MORE than reference"]).sum()
    log(f"  {len(out)} checks: {int((out['status'] == 'match').sum())} match, {int(bad)} to look at -> {raw / 'validation.csv'}")
    return out
