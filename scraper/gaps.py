"""Find league-seasons with fewer than 3 known scorers and prepare rows to fill in by hand.

    -> data/manual/gaps.csv: every gap (league, season, scorers found, who is known)
    -> data/manual/scorers_manual.csv: for gap seasons not already there, up to 5 rows per season,
       pre-filled with whatever is already known (usually the league's top scorer) and blank
       rows to complete. Fill in player, team, goals; leave unused rows blank (they're ignored).

Manual rows replace every other source for that league-season, so keep the known rows.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import db
from .assemble import _is_player

ROWS_PER_SEASON = 5
MIN_SCORERS = 3


def build(raw: Path, leagues: list[dict], first: int, last: int, log=print, only: list[str] | None = None) -> pd.DataFrame:
    """Rows to fill are added only for leagues that already have some data (or the codes in `only`);
    leagues with nothing at all are listed in gaps.csv as 'no data' instead of flooding the file."""
    db.refresh(raw, log=lambda s: None)
    frames = [f for f in (db.load(n, raw) for n in ("scorers_wikipedia", "scorers_transfermarkt")) if f is not None]
    have = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["competition", "season", "player", "team", "goals"])
    have = have[have["player"].map(_is_player)]
    manual_p = db.manual_dir(raw) / "scorers_manual.csv"
    manual = pd.read_csv(manual_p) if manual_p.exists() else pd.DataFrame(columns=db.MANUAL_TEMPLATES["scorers_manual.csv"].strip().split(","))
    in_manual = set(zip(manual["competition"], manual["season"].astype("Int64")))
    from .wikipedia import active
    gaps, new_rows = [], []
    covered = set(have["competition"].unique())
    for lg in leagues:
        template = (lg["code"] in only) if only else (lg["code"] in covered)
        for s in range(max(first, lg.get("first", first)), min(last, lg.get("last", last)) + 1):
            if not active(lg, s):
                continue
            rows = have[(have["competition"] == lg["code"]) & (have["season"] == s)].sort_values("goals", ascending=False)
            filled = manual[(manual["competition"] == lg["code"]) & (manual["season"] == s) & manual["player"].map(_is_player)]
            n = max(rows["player"].nunique(), len(filled))
            if n >= MIN_SCORERS:
                continue
            gaps.append({"competition": lg["code"], "league": lg["name"], "season": s, "scorers_found": n,
                         "status": "to fill" if template else "no data for this league",
                         "known": "; ".join(f"{r.player} ({r.team}) {int(r.goals)}" for r in rows.head(3).itertuples())})
            if not template or (lg["code"], s) in in_manual:
                continue
            known = list(rows.head(ROWS_PER_SEASON).itertuples())
            for k in range(ROWS_PER_SEASON):
                r = known[k] if k < len(known) else None
                new_rows.append({"competition": lg["code"], "season": s, "rank": k + 1,
                                 "player": r.player if r else "", "team": r.team if r else "",
                                 "goals": int(r.goals) if r else "", "nationality": "",
                                 "note": "already known" if r else ""})
    g = pd.DataFrame(gaps)
    out_dir = db.manual_dir(raw)
    out_dir.mkdir(parents=True, exist_ok=True)
    g.to_csv(out_dir / "gaps.csv", index=False)
    if new_rows:
        pd.concat([manual, pd.DataFrame(new_rows)], ignore_index=True).to_csv(manual_p, index=False)
    by = g.groupby("competition").size().sort_values(ascending=False) if len(g) else pd.Series(dtype=int)
    empty = sorted(g.loc[g["status"] != "to fill", "competition"].unique()) if len(g) else []
    if empty:
        log(f"  {len(empty)} leagues have no scorer data at all ({', '.join(empty)}); listed in gaps.csv, "
            f"no rows added (use --leagues CODE to add rows for one)")
    log(f"  {len(g)} league-seasons with fewer than {MIN_SCORERS} scorers: "
        + ", ".join(f"{k} {v}" for k, v in by.head(12).items()))
    log(f"  -> {out_dir / 'gaps.csv'}\n  -> {manual_p} ({len(new_rows)} rows added to fill in)")
    return g
