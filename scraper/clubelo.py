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

APIS = ["http://api.clubelo.com/{}", "https://api.clubelo.com/{}"]
GIVE_UP_AFTER = 3   # consecutive failed seasons before stopping (the site is probably down)


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
    out, fails = [], 0
    quick = PoliteSession(sess.cache_dir, delay=sess.delay, jitter=sess.jitter, max_retries=1)
    quick.s.headers.update(sess.s.headers)
    for season in range(first, last + 1):
        text, err = None, None
        for api in APIS:                                    # plain, then secure address
            try:
                text = quick.get(api.format(f"{season + 1}-01-15"))   # mid-season snapshot
                if text:
                    break
            except Blocked as e:
                raise SystemExit(f"BLOCKED: {e}")
            except FetchFailed as e:
                err = e
        if not text:
            fails += 1
            log(f"  {season}: {err or 'no snapshot'}")
            if fails >= GIVE_UP_AFTER:
                log(f"\nClubElo failed {fails} seasons in a row, so it's probably down right now. Stopping.\n"
                    "Check http://api.clubelo.com/2017-01-15 in a browser: if it shows a table, the site is up\n"
                    "and something on this network is interfering; if it errors, try again later.\n"
                    "Seasons already fetched are saved and cached. Everything else works without this step.")
                break
            continue
        fails = 0
        snap = parse_snapshot(text)
        got = []
        for lg in leagues:
            r = league_strength(snap, lg["code"], teams.get((lg["code"], season)))
            if r:
                out.append({"competition": lg["code"], "season": season, "elo_mean": round(r[0], 1), "n_clubs": r[1]})
                got.append(f"{lg['code']} {r[0]:.0f}")
        log(f"  {season}: " + ", ".join(got))
    df = pd.DataFrame(out)
    path = raw / "league_strength.csv"
    if path.exists():                       # keep seasons fetched on earlier runs
        old = pd.read_csv(path)
        df = pd.concat([old, df]).drop_duplicates(["competition", "season"], keep="last") if len(old) else df
    if len(df):
        df.sort_values(["season", "competition"]).to_csv(path, index=False)
    return df
