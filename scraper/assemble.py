"""Join everything into data/raw/player_seasons.csv, the file the pipeline reads.

Club sources, best first for any league-season more than one covers:
    scorers_transfermarkt.csv  (2012-, full league, goals + assists + minutes)
    scorers_wikipedia.csv      (1946-, season pages' top scorers, plus leader lists for gaps)
    scorers_worldfootball.csv  (legacy; only if you have it)
The same player is linked across sources by name, so a career that spans sources stays one player.

Added to each player's main club row that season (the club where he scored most):
    cup_goals        continental club cup goals (Champions League, Libertadores, AFC, CAF, CONCACAF)
    world_cup_goals  World Cup finals goals
    tournament_goals continental championship goals (Euro, Copa América, AFCON, Asian Cup, Gold Cup...)
Tournament goals move off the player's international row so nothing counts twice; unlinked
international scorers keep them on their international row.

Per club row: env_gpm (league goals per team match: engsoccerdata, else the season page's league
table), intl_env_gpm (the international scoring rate that season, for tournament goals),
league_elo (scraper/strength.py), confed, comp_rank.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import db, strength
from .clubs import ClubResolver, norm
from .geo import country_codes
from .wikipedia import NOT_A_PLAYER

CUP_CODES = ["UCL", "UEL", "LIB", "ACL", "CAF", "CCL"]
COLUMNS = ["player_id", "player", "season", "competition", "comp_type", "confed", "team", "nationality",
           "club_city", "lat", "lon", "loc_source", "apps", "minutes", "team_games", "env_gpm", "intl_env_gpm",
           "goals", "penalties", "assists", "cup_goals", *[f"cup_goals_{c}" for c in CUP_CODES],
           "world_cup_goals", "tournament_goals", "other_tournament_goals",
           "comp_rank", "league_elo", "source"]
SOURCES = [("manual_scorers_manual", "manual", "man:"),        # table, label, id prefix (best first)
           ("scorers_transfermarkt", "transfermarkt", ""),
           ("scorers_wikipedia", "wikipedia", "wiki:"),
           ("scorers_worldfootball", "worldfootball.net", "wf:")]


def _is_player(v) -> bool:
    return isinstance(v, str) and v.strip() != "" and not NOT_A_PLAYER.search(v)


def _club_rows(raw: Path) -> tuple[pd.DataFrame, dict]:
    frames, covered = [], set()
    for name, label, prefix in SOURCES:
        df = db.load(name, raw)
        if df is None or df.empty:
            continue
        if label == "manual":                              # your additions: blank template rows skipped
            df = df[df["player"].map(_is_player) & pd.to_numeric(df["goals"], errors="coerce").notna()].copy()
            if df.empty:
                continue
            df["player_id"] = df["player"]
            df["season"] = df["season"].astype(int)
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
    junk = ~club["player"].map(_is_player)
    if junk.any():
        print(f"  dropped {int(junk.sum())} summary or blank rows ('Total:', '22 players', ...)")
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
            best = next((by_src[s][0] for s in ("wiki", "tm", "wf", "man") if s in by_src), ids[0])
            for i in ids:
                canon[i] = best
    club["player_id"] = club["player_id"].map(lambda i: canon.get(i, i))
    return club.drop(columns="_k"), canon


def _linker(club: pd.DataFrame, canon: dict):
    known = set(club["player_id"])
    names = club.drop_duplicates("player_id")[["player_id", "player"]]
    counts = names["player"].map(norm).value_counts()
    by_name = {norm(p): pid for pid, p in names.itertuples(index=False) if counts.get(norm(p), 0) == 1}

    def link(pid, name):
        pid = canon.get(pid, pid)
        return pid if pid in known else by_name.get(norm(name))
    return link


def _cup_goals(raw: Path, club: pd.DataFrame, canon: dict) -> pd.DataFrame:
    """Continental club cup goals per (player_id, season), one column per competition.
    Transfermarkt wins for the Champions League and Europa League from 2012 (complete);
    Wikipedia's season top-scorer tables cover everything else."""
    frames, tm_first = [], {}
    tm = db.load("scorers_cups_transfermarkt", raw)
    if tm is None:
        tm = db.load("scorers_ucl_transfermarkt", raw)
        if tm is not None:
            tm = tm.assign(competition="UCL")
    if tm is not None and len(tm):
        tm["player_id"] = tm["player_id"].astype(str)
        tm_first = tm.groupby("competition")["season"].min().to_dict()
        frames.append(tm)
    wk = db.load("scorers_continental_wikipedia", raw)
    if wk is None:
        wk = db.load("scorers_ucl_wikipedia", raw)
        if wk is not None:
            wk = wk.assign(competition="UCL")
    if wk is not None and len(wk):
        wk["player_id"] = "wiki:" + wk["player_id"].astype(str)
        drop = pd.Series(False, index=wk.index)
        for comp, s0 in tm_first.items():
            drop |= (wk["competition"] == comp) & (wk["season"] >= s0)
        frames.append(wk[~drop])
    cols = [f"cup_goals_{c}" for c in CUP_CODES]
    if not frames:
        return pd.DataFrame(columns=["player_id", "season", *cols])
    u = pd.concat(frames, ignore_index=True)
    u = u[u["player"].map(_is_player)]
    link = _linker(club, canon)
    u["player_id"] = [link(p, n) for p, n in zip(u["player_id"], u["player"])]
    ok = u["player_id"].notna()
    by = u[ok].groupby("competition").size().to_dict()
    print(f"  continental cups: {int(ok.sum())} of {len(u)} scorer-seasons linked to club players "
          f"({', '.join(f'{k} {v}' for k, v in sorted(by.items()))})")
    wide = (u[ok].groupby(["player_id", "season", "competition"])["goals"].sum()
            .unstack(fill_value=0).reindex(columns=CUP_CODES, fill_value=0))
    wide.columns = cols
    return wide.reset_index()


def _environment(raw: Path, leagues: list[dict]) -> pd.DataFrame:
    """Scoring rate per (league code, season): engsoccerdata first, else the season page's table."""
    frames = []
    esd = db.load("league_environment", raw)
    for lg in leagues:
        if lg.get("env"):
            e = esd[esd["competition"] == lg["env"]].assign(competition=lg["code"])
            frames.append(e[["competition", "season", "goals_per_team_match", "team_games"]].assign(env_source="engsoccerdata"))
    w = db.load("league_environment_wiki", raw)
    if w is not None and len(w):
        w = w[["competition", "season", "goals_per_team_match", "team_games"]].assign(env_source="wikipedia")
        frames.append(w)
    env = pd.concat(frames, ignore_index=True).drop_duplicates(["competition", "season"], keep="first")
    return env.rename(columns={"goals_per_team_match": "env_gpm"})


def assemble(raw: Path, leagues: list[dict], geocode: bool = False, contact: str | None = None) -> pd.DataFrame:
    db.refresh(raw)
    club, canon = _club_rows(raw)
    enabled = {lg["code"] for lg in leagues if lg["enabled"]}
    off = ~club["competition"].isin(enabled)
    if off.any():
        print(f"  left out {int(off.sum())} rows from leagues not enabled in leagues.json")
    club = club[~off].copy()
    club["confed"] = club["competition"].map({lg["code"]: lg.get("confed", "") for lg in leagues})

    env = _environment(raw, leagues)
    club = club.merge(env[["competition", "season", "env_gpm", "team_games"]], on=["competition", "season"], how="left")
    club["comp_rank"] = club.groupby(["competition", "season"])["goals"].rank(method="min", ascending=False)
    ienv = db.load("intl_environment", raw)
    club = club.merge(ienv[["season", "goals_per_team_match"]].rename(columns={"goals_per_team_match": "intl_env_gpm"}),
                      on="season", how="left")

    # Main club row per player-season = where he scored most; big-moment goals attach there
    club = club.sort_values("goals", ascending=False).reset_index(drop=True)
    main = ~club.duplicated(["player_id", "season"])
    cup = _cup_goals(raw, club, canon)
    club = club.merge(cup, on=["player_id", "season"], how="left")
    for c in [f"cup_goals_{x}" for x in CUP_CODES]:
        club[c] = club[c].fillna(0).where(main.to_numpy(), 0).astype(int)
    club["cup_goals"] = club[[f"cup_goals_{x}" for x in CUP_CODES]].sum(axis=1)

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
    # Clubs without a map location, most goals first (copy rows into data/manual/club_locations_manual.csv)
    un = club[club["loc_source"].isin(["unresolved", "no club"]) & (club["team"] != "")]
    un = (un.groupby(["team", "competition"])["goals"].sum().sort_values(ascending=False).reset_index()
          .rename(columns={"competition": "country"}).assign(city="", lat="", lon=""))
    un.to_csv(raw / "unresolved_clubs.csv", index=False)
    n_unresolved = len(un)
    placed = club.loc[~club["loc_source"].isin(["unresolved", "no club"]), "goals"].sum() / max(club["goals"].sum(), 1)

    # ---- international rows (competitive matches with scorer records) ----
    ig = db.load("intl_goals", raw)
    itg = db.load("intl_team_games", raw)
    ig = ig.merge(ienv[["season", "goals_per_team_match"]], on="season", how="left") \
           .merge(itg, on=["season", "team"], how="left") \
           .rename(columns={"goals_per_team_match": "env_gpm", "scorer": "player", "team": "nationality"})
    ig["team"] = ig["nationality"]
    for c in ("world_cup_goals", "continental_goals", "other_tournament_goals"):
        if c not in ig:
            ig[c] = 0

    known = club.drop_duplicates("player_id")[["player_id", "player", "nationality"]]
    by_name_nat = {(norm(str(p)), norm(str(n))): pid for pid, p, n in known.itertuples(index=False)}
    counts = known["player"].astype(str).map(norm).value_counts()
    by_name = {norm(str(p)): pid for pid, p, _ in known.itertuples(index=False) if counts[norm(str(p))] == 1}
    ids = {(p, n): by_name_nat.get((norm(str(p)), norm(str(n)))) or by_name.get(norm(str(p)))
           for p, n in ig[["player", "nationality"]].drop_duplicates().itertuples(index=False)}
    ig["player_id"] = [ids.get((p, n)) or f"intl:{norm(str(p))}:{norm(str(n))}"
                       for p, n in zip(ig["player"], ig["nationality"])]
    linked = ~ig["player_id"].str.startswith("intl:")
    names = club.drop_duplicates("player_id").set_index("player_id")["player"]
    ig["player"] = [names.get(pid, p) for pid, p in zip(ig["player_id"], ig["player"])]

    # Tournament goals of linked players move to their main club row (big moments, counted once)
    has_club = set(zip(club.loc[main.to_numpy(), "player_id"], club.loc[main.to_numpy(), "season"]))
    movable = linked & pd.Series([(p, s) in has_club for p, s in zip(ig["player_id"], ig["season"])], index=ig.index)
    tcols = ["world_cup_goals", "continental_goals", "other_tournament_goals"]
    t = ig[movable].groupby(["player_id", "season"])[tcols].sum() \
        .rename(columns={"continental_goals": "tournament_goals"}).reset_index()
    club = club.merge(t, on=["player_id", "season"], how="left")
    for c in ("world_cup_goals", "tournament_goals", "other_tournament_goals"):
        club[c] = club[c].fillna(0).where(main.to_numpy(), 0).astype(int)
    moved = ig[tcols].sum(axis=1)
    ig.loc[movable, "goals"] = (ig.loc[movable, "goals"] - moved[movable]).clip(lower=0)
    ig["world_cup_goals"] = ig["world_cup_goals"].where(~movable, 0)
    ig["tournament_goals"] = ig["continental_goals"].where(~movable, 0)
    ig["other_tournament_goals"] = ig["other_tournament_goals"].where(~movable, 0)
    ig = ig.assign(competition="INT", comp_type="international", club_city=None, lat=None, lon=None,
                   loc_source=None, apps=pd.NA, minutes=pd.NA, comp_rank=pd.NA, cup_goals=0, confed="",
                   source="martj42/international_results")

    # ---- league strength (ClubElo + national Elo + talent exodus) ----
    finals_codes = []
    f = db.load("continental_finals", raw)
    if f is not None and len(f):
        finals_codes = sorted({country_codes(c)[0] for c in pd.concat([f["winner_country"], f["runner_up_country"]])} - {""})
    ls = strength.build(raw, club, ig, leagues, extra_codes=finals_codes)
    if len(ls):
        club = club.merge(ls[["code", "season", "elo"]].rename(columns={"code": "competition", "elo": "league_elo"}),
                          on=["competition", "season"], how="left")
    else:
        club["league_elo"] = pd.NA

    out = pd.concat([club.reindex(columns=COLUMNS), ig.reindex(columns=COLUMNS)], ignore_index=True)
    out = out.sort_values(["season", "competition", "player_id"])
    out.to_csv(raw / "player_seasons.csv", index=False)
    _derived(raw, out, resolver)
    m = club["comp_type"] == "club"
    print(f"  club rows: {int(m.sum())} in {club['competition'].nunique()} leagues "
          f"({int(club['env_gpm'].isna().sum())} without a league scoring rate)")
    print(f"  big moments on club rows: {int(club['cup_goals'].sum())} continental cup goals, "
          f"{int(club['world_cup_goals'].sum())} World Cup goals, {int(club['tournament_goals'].sum())} continental championship goals")
    print(f"  international rows: {len(ig)} ({int(linked.sum())} linked to club players)")
    print(f"  map locations: clubs holding {placed:.0%} of club goals are placed; {n_unresolved} clubs aren't "
          "(data/raw/unresolved_clubs.csv, most goals first; fixes go in data/manual/club_locations_manual.csv)")
    return out


CUP_NAMES = {"UCL": "European Cup", "UEL": "UEFA Cup", "LIB": "Copa Libertadores", "ACL": "AFC Champions League",
             "CAF": "CAF Champions League", "CCL": "CONCACAF Champions Cup"}


def _derived(raw: Path, ps: pd.DataFrame, resolver: ClubResolver) -> None:
    """players, clubs and moments tables: the base for detail pages on players, clubs and big moments."""
    club = ps[ps["comp_type"] == "club"]
    big = ["cup_goals", "world_cup_goals", "tournament_goals", "other_tournament_goals"]
    agg = club.groupby("player_id").agg(
        name=("player", "first"), nationality=("nationality", lambda s: next((x for x in s if isinstance(x, str) and x), "")),
        first_season=("season", "min"), last_season=("season", "max"), league_goals=("goals", "sum"),
        **{c: (c, "sum") for c in big},
        leagues=("competition", lambda s: "; ".join(sorted(set(s)))),
        clubs=("team", lambda s: "; ".join(dict.fromkeys(x for x in s if x))))
    intl = ps[ps["comp_type"] != "club"].groupby("player_id")["goals"].sum().rename("international_goals")
    players = agg.join(intl, how="left").fillna({"international_goals": 0}).reset_index()
    db.write("players", players, raw)
    clubs = (club.groupby(["team", "competition"])
             .agg(city=("club_city", "first"), lat=("lat", "first"), lon=("lon", "first"),
                  located_by=("loc_source", "first"), first_season=("season", "min"),
                  last_season=("season", "max"), goals=("goals", "sum"))
             .reset_index())
    db.write("clubs", clubs, raw)
    db.write("player_seasons", ps, raw)

    moments = []
    t = db.load("moments_tournaments", raw)
    if t is not None:
        moments.append(t)
    f = db.load("continental_finals", raw)
    if f is not None and len(f):
        rows = []
        for r in f.itertuples():
            code = country_codes(r.winner_country)[0]
            city, lat, lon, _ = resolver.resolve(str(r.winner), code)
            att = getattr(r, "attendance", None)
            rows.append({"season": int(r.season), "date": "", "kind": "club_final",
                         "title": f"{r.winner} win the {CUP_NAMES.get(r.comp, r.comp)} {int(r.season)}",
                         "detail": f"Beat {r.runner_up} in the final." + (f" Crowd: {int(att):,}." if pd.notna(att) else ""),
                         "teams": f"{r.winner}; {r.runner_up}", "players": "", "lat": lat, "lon": lon,
                         "weight": 2 if r.comp in ("UCL", "LIB") else 1, "source": "Wikipedia"})
        moments.append(pd.DataFrame(rows))
    m = db.load("manual_moments_manual", raw)
    if m is not None and len(m):
        m = m[m["title"].map(lambda v: isinstance(v, str) and v.strip() != "")]
        moments.append(m.assign(kind="manual", source="manual"))
    if moments:
        allm = pd.concat(moments, ignore_index=True).sort_values(["season", "date"])
        allm.to_csv(raw / "moments.csv", index=False)
        db.write("moments", allm, raw)
        print(f"  moments: {len(allm)} ({', '.join(f'{k} {v}' for k, v in allm['kind'].value_counts().items())})")
