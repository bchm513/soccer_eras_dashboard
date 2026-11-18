"""Scoring environments from open GitHub datasets (no scraping needed).

League environment: jalapic/engsoccerdata full league results (top tier only).
    -> data/raw/league_environment.csv: competition, season, teams, matches, goals,
       goals_per_team_match, team_games
International environment and scorers: martj42/international_results.
    Scorer records mainly cover competitive internationals, so all international figures here
    (environment, team games, player goals) are for matches that have scorer records.
    -> data/raw/intl_environment.csv: season, matches, goals, goals_per_team_match
    -> data/raw/intl_team_games.csv: season, team, team_games
    -> data/raw/intl_goals.csv: season, team, scorer, goals, penalties, assists

Seasons are labelled by their starting year (1955 = 1955-56). Calendar dates map to the
season that runs August -> July, so a June 1958 World Cup belongs to season 1957.
"""
from __future__ import annotations

import io
import time
from pathlib import Path

import pandas as pd
import requests

ESD = "https://raw.githubusercontent.com/jalapic/engsoccerdata/master/data/{}.rda"
INTL = "https://raw.githubusercontent.com/martj42/international_results/master/{}.csv"

# engsoccerdata country file -> our competition code
ESD_LEAGUES = {"england": "ENG", "spain": "ESP", "italy": "ITA", "germany": "GER",
               "holland": "NED", "france": "FRA", "portugal": "POR", "scotland": "SCO",
               "belgium": "BEL", "greece": "GRE", "turkey": "TUR"}


class DownloadFailed(SystemExit):
    pass


def _download(url: str, dest: Path, tries: int = 4) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    for attempt in range(1, tries + 1):
        try:
            r = requests.get(url, timeout=120)
            if r.status_code == 404:
                r.raise_for_status()   # caller skips datasets that don't exist
            r.raise_for_status()
            dest.write_bytes(r.content)
            return dest
        except requests.HTTPError:
            raise
        except requests.RequestException as e:
            if attempt == tries:
                raise DownloadFailed(
                    f"\nCouldn't download {url}\n({type(e).__name__}: the connection was dropped or refused)\n\n"
                    "This is a network problem, not a data problem. Common causes: a VPN, a firewall,\n"
                    "or antivirus that inspects web traffic. Try opening the link in a browser, or\n"
                    "switch networks.\n\n"
                    "You can skip this step: data/raw/ already contains the environment files.\n"
                    "Continue with:  python -m scraper.run probe")
            wait = 3 * attempt
            print(f"  connection problem ({type(e).__name__}); retrying in {wait}s...")
            time.sleep(wait)
    return dest


def season_of(dates: pd.Series) -> pd.Series:
    d = pd.to_datetime(dates, errors="coerce")
    return (d.dt.year - (d.dt.month < 8).astype(int)).astype("Int64")


def league_environment(cache: Path, first: int = 1946) -> pd.DataFrame:
    import pyreadr  # reads the .rda files

    out = []
    for name, code in ESD_LEAGUES.items():
        try:
            f = _download(ESD.format(name), cache / f"{name}.rda")
        except requests.HTTPError:
            print(f"  skip {name}: not in engsoccerdata")
            continue
        df = next(iter(pyreadr.read_r(str(f)).values()))
        if "tier" in df:
            df = df[pd.to_numeric(df["tier"], errors="coerce") == 1]
        df = df.dropna(subset=["hgoal", "vgoal"])
        df["Season"] = df["Season"].astype(int)
        df = df[df["Season"] >= first]
        for season, g in df.groupby("Season"):
            teams = pd.unique(pd.concat([g["home"], g["visitor"]])).size
            matches = len(g)
            goals = int(g["hgoal"].sum() + g["vgoal"].sum())
            out.append({"competition": code, "season": int(season), "teams": teams, "matches": matches,
                        "goals": goals, "goals_per_team_match": round(goals / (2 * matches), 4),
                        "team_games": round(2 * matches / teams, 1), "source": "engsoccerdata"})
    return pd.DataFrame(out)


def international(cache: Path, first: int = 1946) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    res = pd.read_csv(_download(INTL.format("results"), cache / "intl_results.csv"))
    gs = pd.read_csv(_download(INTL.format("goalscorers"), cache / "intl_goalscorers.csv"))

    res["season"] = season_of(res["date"])
    res = res[res["season"] >= first].dropna(subset=["home_score", "away_score"])
    # Scorer records mostly cover competitive matches (World Cups, continental cups, qualifiers),
    # not friendlies. Measure the environment over the same matches so the two stay comparable.
    covered = set(zip(gs["date"], gs["home_team"], gs["away_team"]))
    res = res[[k in covered for k in zip(res["date"], res["home_team"], res["away_team"])]]
    env = (res.groupby("season")
           .agg(matches=("date", "size"), goals=("home_score", "sum"), ag=("away_score", "sum"))
           .assign(goals=lambda d: d["goals"] + d["ag"]).drop(columns="ag").reset_index())
    env["goals_per_team_match"] = (env["goals"] / (2 * env["matches"])).round(4)

    team_games = (pd.concat([res[["season", "home_team"]].rename(columns={"home_team": "team"}),
                             res[["season", "away_team"]].rename(columns={"away_team": "team"})])
                  .groupby(["season", "team"]).size().rename("team_games").reset_index())

    gs["season"] = season_of(gs["date"])
    gs = gs[(gs["season"] >= first) & (gs["own_goal"].astype(str).str.upper() != "TRUE")]
    gs["pen"] = gs["penalty"].astype(str).str.upper() == "TRUE"
    goals = (gs.groupby(["season", "team", "scorer"])
             .agg(goals=("date", "size"), penalties=("pen", "sum")).reset_index())
    if "assist" in gs:
        a = gs.dropna(subset=["assist"])
        a = a[a["assist"].astype(str).str.upper() != "NA"]
        ast = a.groupby(["season", "team", "assist"]).size().rename("assists").reset_index() \
               .rename(columns={"assist": "scorer"})
        goals = goals.merge(ast, on=["season", "team", "scorer"], how="outer")
        goals["goals"] = goals["goals"].fillna(0).astype(int)
        goals["penalties"] = goals["penalties"].fillna(0).astype(int)
    return env, team_games, goals


def build(raw: Path, cache: Path, first: int = 1946) -> None:
    raw.mkdir(parents=True, exist_ok=True)
    lg = league_environment(cache, first)
    lg.to_csv(raw / "league_environment.csv", index=False)
    print(f"  league environment: {len(lg)} league-seasons "
          + ", ".join(f"{c} {g.season.min()}-{g.season.max()}" for c, g in lg.groupby("competition")))
    env, tg, goals = international(cache, first)
    env.to_csv(raw / "intl_environment.csv", index=False)
    tg.to_csv(raw / "intl_team_games.csv", index=False)
    goals.to_csv(raw / "intl_goals.csv", index=False)
    print(f"  internationals: {int(env.matches.sum())} matches, {len(goals)} scorer-seasons, "
          f"seasons {env.season.min()}-{env.season.max()}")
