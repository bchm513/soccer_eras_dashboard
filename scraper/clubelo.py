"""League strength from ClubElo ratings (clubelo.com), one snapshot per season.

    http://api.clubelo.com/YYYY-MM-DD  ->  CSV: Rank, Club, Country, Level, Elo, From, To
    (every rated European club on that date; Level 1 = top division)

A league's strength in a season = the mean Elo of its top-division clubs in mid-January of
that season. Elo is built from every result, European cups included, so it captures how good
a league is (not just how many goals it produces) and moves over time: Portugal in Benfica's
1960s, the Netherlands in the 1970s, Scotland in Celtic's Lisbon Lions years.

    -> data/raw/league_strength.csv: competition, season, elo_mean, n_clubs
"""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd

from .http import Blocked, FetchFailed, PoliteSession

API = "http://api.clubelo.com/{}"


def parse_snapshot(text: str) -> pd.DataFrame:
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip().lower() for c in df.columns]
    need = {"club", "country", "elo"}
    if not need <= set(df.columns):
        raise ValueError(f"unexpected ClubElo columns: {list(df.columns)}")
    df["level"] = pd.to_numeric(df.get("level"), errors="coerce")
    df["elo"] = pd.to_numeric(df["elo"], errors="coerce")
    return df.dropna(subset=["elo"])


def league_strength(snapshot: pd.DataFrame, country: str, teams: int | None) -> tuple[float, int] | None:
    c = snapshot[snapshot["country"] == country]
    top = c[c["level"] == 1]
    if top.empty:                      # very old snapshots can lack division info
        top = c.nlargest(teams or 16, "elo")
    if teams and len(top) > teams:     # guard against stray clubs tagged level 1
        top = top.nlargest(teams, "elo")
    return (float(top["elo"].mean()), int(len(top))) if len(top) else None


def build(raw: Path, sess: PoliteSession, leagues: list[dict], first: int, last: int, log=print) -> pd.DataFrame:
    env = pd.read_csv(raw / "league_environment.csv") if (raw / "league_environment.csv").exists() else None
    teams = {} if env is None else {(r.competition, int(r.season)): int(r.teams) for r in env.itertuples()}
    out = []
    for season in range(first, last + 1):
        url = API.format(f"{season + 1}-01-15")          # mid-season snapshot
        try:
            text = sess.get(url)
        except Blocked as e:
            raise SystemExit(f"BLOCKED: {e}")
        except FetchFailed as e:
            log(f"  {season}: {e}; skipping (re-run later to retry)")
            continue
        if not text:
            log(f"  {season}: no snapshot")
            continue
        snap = parse_snapshot(text)
        got = []
        for lg in leagues:
            r = league_strength(snap, lg["code"], teams.get((lg["code"], season)))
            if r:
                out.append({"competition": lg["code"], "season": season, "elo_mean": round(r[0], 1), "n_clubs": r[1]})
                got.append(f"{lg['code']} {r[0]:.0f}")
        log(f"  {season}: " + ", ".join(got))
    df = pd.DataFrame(out)
    df.to_csv(raw / "league_strength.csv", index=False)
    return df
