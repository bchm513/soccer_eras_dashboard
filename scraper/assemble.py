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
from .wikipedia import NOT_A_PLAYER

COLUMNS = ["player_id", "player", "season", "competition", "comp_type", "team", "nationality",
           "club_city", "lat", "lon", "loc_source", "apps", "minutes", "team_games", "env_gpm",
           "goals", "penalties", "assists", "ucl_goals", "comp_rank", "league_elo", "source"]
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
    junk = club["player"].map(lambda v: isinstance(v, str) and bool(NOT_A_PLAYER.search(v)))
    if junk.any():
        print(f"  dropped {int(junk.sum())} summary rows ('Total:', '22 players', ...)")
    club = club[~junk]

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
    return club.drop(columns="_k"), canon


def _ucl_goals(raw: Path, club: pd.DataFrame, canon: dict) -> pd.DataFrame:
    """European Cup / Champions League goals per (player_id, season), linked to club players.
    Transfermarkt wins from 2012 (complete); Wikipedia's season top-scorer tables before that."""
    frames = []
    tm_p, wk_p = raw / "scorers_ucl_transfermarkt.csv", raw / "scorers_ucl_wikipedia.csv"
    tm_first = None
    if tm_p.exists():
        tm = pd.read_csv(tm_p)
        tm["player_id"] = tm["player_id"].astype(str)
        tm_first = int(tm["season"].min())
        frames.append(tm)
    if wk_p.exists():
        wk = pd.read_csv(wk_p)
        wk["player_id"] = "wiki:" + wk["player_id"].astype(str)
        if tm_first is not None:
            wk = wk[wk["season"] < tm_first]
        frames.append(wk)
    if not frames:
        return pd.DataFrame(columns=["player_id", "season", "ucl_goals"])
    u = pd.concat(frames, ignore_index=True)
    u = u[u["player"].map(lambda v: isinstance(v, str) and not NOT_A_PLAYER.search(v))]
    # Same player ids as the league rows where possible, else match by (unambiguous) name
    known = set(club["player_id"])
    names = club.drop_duplicates("player_id")[["player_id", "player"]]
    counts = names["player"].map(norm).value_counts()
    by_name = {norm(p): pid for pid, p in names.itertuples(index=False) if counts.get(norm(p), 0) == 1}
    def link(pid, name):
        pid = canon.get(pid, pid)
        return pid if pid in known else by_name.get(norm(name))
    u["player_id"] = [link(p, n) for p, n in zip(u["player_id"], u["player"])]
    matched = u["player_id"].notna()
    print(f"  Champions League: {int(matched.sum())} of {len(u)} scorer-seasons linked to club players")
    return (u[matched].groupby(["player_id", "season"])["goals"].sum()
            .rename("ucl_goals").reset_index())


def assemble(raw: Path, leagues: list[dict], geocode: bool = False, contact: str | None = None) -> pd.DataFrame:
    env = pd.read_csv(raw / "league_environment.csv")
    env_code = {lg["code"]: lg.get("env") for lg in leagues}
    club, canon = _club_rows(raw)
    enabled = {lg["code"] for lg in leagues if lg["enabled"]}
    off = ~club["competition"].isin(enabled)
    if off.any():
        print(f"  left out {int(off.sum())} rows from leagues not enabled in leagues.json")
    club = club[~off]

    club["env_comp"] = club["competition"].map(env_code)
    club = club.merge(env.rename(columns={"competition": "env_comp", "goals_per_team_match": "env_gpm"})[
        ["env_comp", "season", "env_gpm", "team_games"]], on=["env_comp", "season"], how="left")
    club["comp_rank"] = club.groupby(["competition", "season"])["goals"].rank(method="min", ascending=False)
    # Champions League goals go on the player's main club row that season (most league goals)
    ucl = _ucl_goals(raw, club, canon)
    club = club.sort_values("goals", ascending=False)
    first_row = ~club.duplicated(["player_id", "season"])
    club = club.merge(ucl, on=["player_id", "season"], how="left")
    club["ucl_goals"] = club["ucl_goals"].fillna(0).where(first_row.to_numpy(), 0).astype(int)
    ls = raw / "league_strength.csv"
    if ls.exists():
        strength = pd.read_csv(ls)[["competition", "season", "elo_mean"]].rename(columns={"elo_mean": "league_elo"})
        club = club.merge(strength, on=["competition", "season"], how="left")
        print(f"  league strength: {club['league_elo'].notna().mean():.0%} of club rows rated")
    else:
        club["league_elo"] = pd.NA
        print("  league strength: none yet (run `python -m scraper.run elo` to weight leagues)")

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
