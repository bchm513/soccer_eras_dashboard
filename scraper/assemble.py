"""Join club scorers + international scorers + scoring environments
into data/raw/player_seasons.csv, the file the pipeline reads.

Club sources, best first for any league-season that more than one covers:
    scorers_transfermarkt.csv  (2012-, full league, goals + assists + minutes)
    scorers_wikipedia.csv      (1946-, top scorers listed on each season's page)
    scorers_worldfootball.csv  (legacy; only if you have it)
The same player is linked across sources by name, so a career that starts in Wikipedia's
years and ends in Transfermarkt's stays one player.

Output per row: goals / team_games = output per team match; / env_gpm = relative to that
league-season's scoring rate. `comp_rank` (rank by goals in the league-season) lets the
pipeline compare everyone against the same reference group in every era: the top 3.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .clubs import ClubResolver, norm

COLUMNS = ["player_id", "player", "season", "competition", "comp_type", "team", "nationality",
           "club_city", "lat", "lon", "loc_source", "apps", "minutes", "team_games", "env_gpm",
           "goals", "penalties", "assists", "comp_rank", "source"]
SOURCES = [("scorers_transfermarkt.csv", "transfermarkt", ""),     # file, label, id prefix
           ("scorers_wikipedia.csv", "wikipedia", "wiki:"),
           ("scorers_worldfootball.csv", "worldfootball.net", "wf:")]


def _club_rows(raw: Path) -> pd.DataFrame:
    frames, covered = [], set()
    for fname, label, prefix in SOURCES:
        p = raw / fname
        if not p.exists():
            continue
        df = pd.read_csv(p)
        df["player_id"] = prefix + df["player_id"].astype(str) if prefix else df["player_id"].astype(str)
        df["source"] = label
        keys = set(zip(df["competition"], df["season"]))
        df = df[[k not in covered for k in zip(df["competition"], df["season"])]]
        covered |= keys
        frames.append(df)
        print(f"  {label}: {len(df)} rows used")
    if not frames:
        raise SystemExit("No club scorer files in data/raw/. Run `python -m scraper.run scorers` first.")
    club = pd.concat(frames, ignore_index=True)

    # Link the same player across sources by name (only when the name is unambiguous)
    club["_k"] = club["player"].astype(str).map(norm)
    ids_per_name = club.groupby("_k")["player_id"].agg(lambda s: sorted(set(s)))
    canon = {}
    for k, ids in ids_per_name.items():
        by_src = {}
        for i in ids:
            by_src.setdefault(i.split(":")[0], []).append(i)
        if all(len(v) == 1 for v in by_src.values()):          # one id per source -> same person
            best = next((by_src[s][0] for s in ("wiki", "tm", "wf") if s in by_src), ids[0])
            for i in ids:
                canon[i] = best
    club["player_id"] = club["player_id"].map(lambda i: canon.get(i, i))
    return club.drop(columns="_k")


def assemble(raw: Path, leagues: list[dict], geocode: bool = False, contact: str | None = None) -> pd.DataFrame:
    env = pd.read_csv(raw / "league_environment.csv")
    env_code = {lg["code"]: lg.get("env") for lg in leagues}
    club = _club_rows(raw)

    club["env_comp"] = club["competition"].map(env_code)
    club = club.merge(env.rename(columns={"competition": "env_comp", "goals_per_team_match": "env_gpm"})[
        ["env_comp", "season", "env_gpm", "team_games"]], on=["env_comp", "season"], how="left")
    club["comp_rank"] = club.groupby(["competition", "season"])["goals"].rank(method="min", ascending=False)

    # Blank cells come through as NaN (pandas 3 keeps them missing); use empty text instead
    for c in ("team", "competition", "player", "nationality"):
        club[c] = club[c].map(lambda v: v if isinstance(v, str) else "")
    resolver = ClubResolver(raw, geocode=geocode, contact=contact)
    pairs = club[["team", "competition"]].drop_duplicates()
    locs = {(t, c): resolver.resolve(t, c) for t, c in pairs.itertuples(index=False)}
    loc = [locs[(t, c)] for t, c in zip(club["team"], club["competition"])]
    club["club_city"], club["lat"], club["lon"], club["loc_source"] = zip(*loc) if loc else ([], [], [], [])
    club["comp_type"] = "club"
    club["apps"] = pd.NA            # weights use team games for every source, so eras stay comparable
    for c in ("assists", "minutes", "penalties"):
        if c not in club:
            club[c] = pd.NA
    n_unresolved = resolver.write_unresolved()

    # ---- international rows (competitive matches with scorer records) ----
    ig = pd.read_csv(raw / "intl_goals.csv")
    ienv = pd.read_csv(raw / "intl_environment.csv")
    itg = pd.read_csv(raw / "intl_team_games.csv")
    ig = ig.merge(ienv[["season", "goals_per_team_match"]], on="season", how="left") \
           .merge(itg, on=["season", "team"], how="left") \
           .rename(columns={"goals_per_team_match": "env_gpm", "scorer": "player", "team": "nationality"})
    ig["team"] = ig["nationality"]

    known = club.drop_duplicates("player_id")[["player_id", "player", "nationality"]]
    by_name_nat = {(norm(str(p)), norm(str(n))): pid for pid, p, n in known.itertuples(index=False)}
    counts = known["player"].astype(str).map(norm).value_counts()
    by_name = {norm(str(p)): pid for pid, p, _ in known.itertuples(index=False) if counts[norm(str(p))] == 1}
    ids = {(p, n): by_name_nat.get((norm(str(p)), norm(str(n)))) or by_name.get(norm(str(p)))
           for p, n in ig[["player", "nationality"]].drop_duplicates().itertuples(index=False)}
    ig["player_id"] = [ids.get((p, n)) or f"intl:{norm(str(p))}:{norm(str(n))}"
                       for p, n in zip(ig["player"], ig["nationality"])]
    linked = (~ig["player_id"].str.startswith("intl:")).sum()
    names = club.drop_duplicates("player_id").set_index("player_id")["player"]
    ig["player"] = [names.get(pid, p) for pid, p in zip(ig["player_id"], ig["player"])]
    ig = ig.assign(competition="INT", comp_type="international", club_city=None, lat=None, lon=None,
                   loc_source=None, apps=pd.NA, minutes=pd.NA, comp_rank=pd.NA,
                   source="martj42/international_results")

    out = pd.concat([club.reindex(columns=COLUMNS), ig.reindex(columns=COLUMNS)], ignore_index=True)
    out = out.sort_values(["season", "competition", "player_id"])
    out.to_csv(raw / "player_seasons.csv", index=False)
    print(f"  club rows: {len(club)} ({club['env_gpm'].isna().sum()} without a league scoring rate)")
    print(f"  international rows: {len(ig)} ({linked} linked to club players)")
    print(f"  unresolved clubs: {n_unresolved} (see data/raw/unresolved_clubs.csv; fixes go in "
          "data/raw/club_locations_manual.csv)")
    return out