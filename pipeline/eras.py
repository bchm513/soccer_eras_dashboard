"""Era adjustment, career peaks and overlapping-peak era detection.

Input: player_seasons DataFrame (see sample_data.py for columns).
Metrics:
    goals_adj  goals per match, z-scored within each competition-season (era-adjusted)
    goals_raw  goals per match, z-scored against the pooled all-time distribution (no era adjustment)
    ga_adj     (goals + assists) per match, era-adjusted; only seasons where assists exist
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

MIN_APPS = 10          # rows below this don't define the league baseline
FLAG_Z = 2.0           # a player-season is "flagged" at or above this
MIN_FLAGGED = 3        # flagged seasons needed to count as a star
PEAK_FRACTION = 0.7    # peak window: curve >= 70% of its height
MIN_OVERLAP = 2        # stars overlapping to call it an era
MAX_GAP = 2            # merge era runs separated by <= this many seasons
MIN_LENGTH = 2         # shorter overlaps are spikes, not eras
TURNOVER_MAX = 0.3     # split a long run where the stars peaking before/after overlap this little (Jaccard)
TURNOVER_SPAN = 4      # seasons compared on each side of a candidate boundary
TURNOVER_MIN_LEN = 12  # only runs at least this long are checked for a hand-over
SPLIT_RATIO = 0.7      # split a run where strength dips below 70% of the peaks either side

METRICS = ["goals_adj", "goals_raw", "ga_adj"]


MIN_WEIGHT_ENV = {"club": 10, "international": 3}   # reference rows in environment mode
SHRINK_GAMES = 6       # pseudo-games of average output added to every row in environment mode
REF_TOP = 3            # environment mode: each league-season's top 3 scorers are the reference group
FLAG_Z_ENV = 0.75      # environment mode: star seasons sit this many sd above the average top-3 scorer
ERA_WINDOW = 5         # environment mode: compare with top scorers within +/- this many seasons
INTL_WEIGHT = 0.2      # environment mode: international games count this much vs club games
LEAGUE_ELO_WEIGHT = 0.5   # how hard league strength bites: 0 = off; 1 = full Elo odds
# Big moments: each goal counts as this many league goals, added on top of the player's league goals
WORLD_CUP_WEIGHT = 4.0         # World Cup finals
TOURNAMENT_WEIGHT = 3.0        # continental championships: Euro, Copa América, AFCON, Asian Cup, Gold Cup
OTHER_TOURNAMENT_WEIGHT = 1.0  # Confederations Cup, Oceania Nations Cup
CUP_WEIGHTS = {"UCL": 2.0, "UEL": 2.0,                         # Champions League, Europa League
               "LIB": 1.0, "ACL": 1.0, "CAF": 1.0, "CCL": 1.0}  # other continental club cups
CUP_WEIGHT = 2.0               # older data files with a single cup_goals column
UCL_WEIGHT = CUP_WEIGHT
LEAGUE_ELO_REF_TOP = 4    # strength is measured against the mean of that season's 4 strongest leagues


def _window_z(df: pd.DataFrame, value: str) -> np.ndarray:
    """z-score against reference rows from nearby seasons (+/- ERA_WINDOW), per competition type.
    Players are compared with the top scorers of their own time, not of every era at once:
    goals have become more concentrated among leading scorers, which would otherwise make
    every modern striker look greater than every 1950s one."""
    out = np.full(len(df), np.nan)
    ref = df[df["is_ref"] & df[value].notna()]
    for ct, rows in df.groupby("comp_type").groups.items():
        r = ref[ref["comp_type"] == ct]
        if r.empty:
            continue
        agg = r.groupby("season")[value].agg(n="count", s="sum", ss=lambda x: (x ** 2).sum())
        seasons = np.arange(int(df["season"].min()), int(df["season"].max()) + 1)
        agg = agg.reindex(seasons, fill_value=0)
        win = agg.rolling(2 * ERA_WINDOW + 1, center=True, min_periods=1).sum()
        idx = np.asarray(list(rows))
        sub = df.loc[idx, ["player_id", "season", value]].copy()
        sub["season"] = sub["season"].astype(int)
        n = win["n"].reindex(sub["season"]).to_numpy(float)
        s = win["s"].reindex(sub["season"]).to_numpy(float)
        ss = win["ss"].reindex(sub["season"]).to_numpy(float)
        # Leave the player's own seasons out of his reference group, so a dominant player
        # isn't partly compared with himself (Di Stéfano was most of 1950s La Liga's top 3).
        own = r.groupby(["player_id", "season"])[value].agg(n="count", s="sum", ss=lambda x: (x ** 2).sum())
        if not own.empty:
            own = own.reset_index()
            own["season"] = own["season"].astype(int)
            on, os_, oss = np.zeros(len(sub)), np.zeros(len(sub)), np.zeros(len(sub))
            for k in range(-ERA_WINDOW, ERA_WINDOW + 1):
                m = sub[["player_id", "season"]].assign(season=sub["season"] + k).merge(
                    own, on=["player_id", "season"], how="left")
                on += m["n"].fillna(0).to_numpy()
                os_ += m["s"].fillna(0).to_numpy()
                oss += m["ss"].fillna(0).to_numpy()
            n, s, ss = n - on, s - os_, ss - oss
        n = np.where(n > 1, n, np.nan)
        mean = s / n
        sd = np.sqrt(np.clip(ss / n - mean ** 2, 0, None))
        out[df.index.get_indexer(idx)] = (sub[value].to_numpy(float) - mean) / np.where(sd > 0, sd, np.nan)
    return out


def _row_z(df: pd.DataFrame, value: str, by_season: bool) -> pd.Series:
    keys = ["competition", "season"] if by_season else ["comp_type"]
    if "is_ref" in df:
        ref = df[df["is_ref"]]
    else:
        ref = df[df["w"] >= MIN_APPS]
    stats = ref.groupby(keys)[value].agg(["mean", "std"]).reset_index()
    m = df.merge(stats, on=keys, how="left")
    return ((m[value] - m["mean"]) / m["std"].replace(0, np.nan)).to_numpy()


def league_factor(df: pd.DataFrame) -> pd.Series:
    """Scale club output by league strength (ClubElo), relative to that season's strongest leagues.

    factor = 10 ** (LEAGUE_ELO_WEIGHT * (league_elo - reference) / 400), capped at 1 so the top
    leagues are never boosted. A league 100 Elo below the reference, at weight 0.5, keeps ~75%
    of its output. Rows without a rating (internationals, unrated seasons) are left unchanged."""
    if "league_elo" not in df or LEAGUE_ELO_WEIGHT == 0:
        return pd.Series(1.0, index=df.index)
    elo = pd.to_numeric(df["league_elo"], errors="coerce")
    per = df.assign(elo=elo).dropna(subset=["elo"]).drop_duplicates(["competition", "season"])
    if per.empty:
        return pd.Series(1.0, index=df.index)
    ref = per.groupby("season")["elo"].apply(lambda s: s.nlargest(LEAGUE_ELO_REF_TOP).mean())
    gap = (elo - df["season"].map(ref)).clip(upper=0)
    return (10 ** (LEAGUE_ELO_WEIGHT * gap / 400)).fillna(1.0)


def uses_environment(df: pd.DataFrame) -> bool:
    """Real scraped data has no appearances; it carries each league-season's scoring rate instead."""
    return "env_gpm" in df and pd.to_numeric(df.get("apps"), errors="coerce").isna().mean() > 0.5


def player_season_scores(df: pd.DataFrame) -> pd.DataFrame:
    """One row per player-season with a z-score per metric (club + international combined).

    Two modes:
      full-league data (sample): z-score within each competition-season, weights = apps
      top-scorer data (real):    divide output by the league-season's goals per team match,
                                 then z-score across all seasons; weights = team games
    """
    df = df.copy()
    apps = pd.to_numeric(df["apps"], errors="coerce")
    env_mode = uses_environment(df)
    df["w"] = apps.fillna(pd.to_numeric(df.get("team_games"), errors="coerce")) if env_mode else apps
    num = lambda c: pd.to_numeric(df[c], errors="coerce").fillna(0) if c in df else pd.Series(0.0, index=df.index)
    goals = df["goals"].astype(float)
    per_cup = [c for c in CUP_WEIGHTS if f"cup_goals_{c}" in df]
    if per_cup:
        cup_bonus = sum(CUP_WEIGHTS[c] * num(f"cup_goals_{c}") for c in per_cup)
    else:
        cup_bonus = CUP_WEIGHT * (num("cup_goals") + num("ucl_goals"))
    big_tour = (WORLD_CUP_WEIGHT * num("world_cup_goals") + TOURNAMENT_WEIGHT * num("tournament_goals")
                + OTHER_TOURNAMENT_WEIGHT * num("other_tournament_goals")) if env_mode else 0.0
    club_goals = goals + (cup_bonus if env_mode else 0.0)
    df["g_rate"] = (club_goals + big_tour) / df["w"].clip(lower=1)
    has_ast = pd.to_numeric(df["assists"], errors="coerce")
    df["ga_rate"] = (club_goals + big_tour + has_ast) / df["w"].clip(lower=1)

    if env_mode:
        env = pd.to_numeric(df["env_gpm"], errors="coerce")
        df["min_w"] = df["comp_type"].map(MIN_WEIGHT_ENV).fillna(MIN_APPS)
        # Same reference group in every era: the top REF_TOP scorers of each league-season
        # (sources list 3 to 20+ scorers depending on era), plus all international rows.
        rank = pd.to_numeric(df.get("comp_rank"), errors="coerce")
        is_club = df["comp_type"] == "club"
        df["is_ref"] = (df["w"] >= df["min_w"]) & (~is_club | rank.isna() | (rank <= REF_TOP))
        lf = league_factor(df)
        # Club goals are judged against the league's scoring rate and strength; tournament goals
        # against the international scoring rate (a World Cup is the same stage for everyone).
        intl_env = pd.to_numeric(df["intl_env_gpm"], errors="coerce") if "intl_env_gpm" in df else env
        tour_adj = (big_tour / df["w"].clip(lower=1) / intl_env.where(intl_env > 0)).fillna(0) if env_mode else 0.0
        df["g_adj"] = club_goals / df["w"].clip(lower=1) / env * lf + tour_adj
        df["ga_adj"] = (club_goals + has_ast) / df["w"].clip(lower=1) / env * lf + tour_adj
        # Shrink small samples (a handful of internationals) toward the typical rate for that
        # competition type, so four goals in three games doesn't outrank a 30-goal league season.
        for col in ("g_rate", "g_adj", "ga_adj"):
            prior = df[df["is_ref"]].groupby("comp_type")[col].mean()
            p = df["comp_type"].map(prior)
            df[col] = (df[col] * df["w"] + p * SHRINK_GAMES) / (df["w"] + SHRINK_GAMES)
        df = df.reset_index(drop=True)
        df["z_goals_adj"] = _window_z(df, "g_adj")
        df["z_goals_raw"] = _row_z(df, "g_rate", by_season=False)   # raw: no era adjustment at all
        df["z_ga_adj"] = _window_z(df, "ga_adj")
    else:
        df["z_goals_adj"] = _row_z(df, "g_rate", by_season=True)
        df["z_goals_raw"] = _row_z(df, "g_rate", by_season=False)
        df["z_ga_adj"] = _row_z(df, "ga_rate", by_season=True)

    # Weighted mean of row z-scores per player-season (club + international = overall output)
    keys = ["player_id", "season"]
    df["apps"] = df["w"] * np.where(env_mode & (df["comp_type"] == "international"), INTL_WEIGHT, 1.0)
    df = df.sort_values("goals", ascending=False)   # main club = where they scored most that season
    for m in METRICS:
        z = df[f"z_{m}"]
        df[f"wz_{m}"] = (z * df["apps"]).where(z.notna())
        df[f"wa_{m}"] = df["apps"].where(z.notna())
    sums = df.groupby(keys)[[f"wz_{m}" for m in METRICS] + [f"wa_{m}" for m in METRICS] + ["goals", "apps"]].sum(min_count=1)
    out = pd.DataFrame(index=sums.index)
    for m in METRICS:
        out[m] = sums[f"wz_{m}"] / sums[f"wa_{m}"]
    out["goals"] = sums["goals"]
    out["apps"] = sums["apps"]
    out = out.reset_index()

    club = (df[df["comp_type"] == "club"].drop_duplicates(keys)
            [keys + ["player", "club_city", "lat", "lon", "competition"]]
            .rename(columns={"club_city": "city", "competition": "league"}))
    names = df.drop_duplicates("player_id")[["player_id", "player"]]
    out = out.merge(club.drop(columns="player"), on=keys, how="left").merge(names, on="player_id")
    return out


def _gauss(t, a, mu, s, b):
    return a * np.exp(-((t - mu) ** 2) / (2 * s ** 2)) + b


def fit_peak(years: np.ndarray, z: np.ndarray) -> dict:
    """Fit a Gaussian career curve; fall back to a smoothed rolling mean if the fit fails."""
    span = np.arange(years.min(), years.max() + 1)
    try:
        p0 = [max(z.max() - z.min(), 0.5), years[np.argmax(z)], 3.0, z.min()]
        bounds = ([0, years.min(), 1.0, -3], [12, years.max(), 12, 3])   # peak inside the career
        (a, mu, s, b), _ = curve_fit(_gauss, years, z, p0=p0, bounds=bounds, maxfev=5000)
        curve = _gauss(span, a, mu, s, b)
        half = s * np.sqrt(2 * np.log(1 / PEAK_FRACTION))
        return {"peak": float(mu), "height": float(a + b), "window": [float(mu - half), float(mu + half)],
                "curve": np.column_stack([span, curve]), "fit": "gaussian"}
    except (RuntimeError, ValueError):
        s = pd.Series(z, index=years).reindex(span).interpolate().rolling(3, center=True, min_periods=1).mean()
        lo, hi = s.min(), s.max()
        inside = s[s >= lo + PEAK_FRACTION * (hi - lo)].index
        return {"peak": float(s.idxmax()), "height": float(hi), "window": [float(inside.min()), float(inside.max())],
                "curve": np.column_stack([span, s.to_numpy()]), "fit": "smoothed"}


def find_stars(ps: pd.DataFrame, metric: str, require_club: bool = False, flag_z: float | None = None) -> dict:
    """Stars: players with >= MIN_FLAGGED seasons at or above FLAG_Z.
    With require_club, a star needs club seasons; international goals then add to a club
    player's seasons but can't make someone a star on their own."""
    stars = {}
    club_ids = set(ps.loc[ps["league"].notna(), "player_id"]) if require_club else None
    for pid, g in ps.dropna(subset=[metric]).groupby("player_id"):
        if club_ids is not None and pid not in club_ids:
            continue
        flagged = g[metric] >= (FLAG_Z if flag_z is None else flag_z)
        if club_ids is not None:
            flagged &= g["league"].notna()      # a star season needs club form
        if flagged.sum() < MIN_FLAGGED:
            continue
        g = g.sort_values("season")
        if club_ids is not None:
            g = g[g["league"].notna()]          # career curve from club seasons
        fit = fit_peak(g["season"].to_numpy(float), g[metric].to_numpy(float))
        fit.update({"player": g["player"].iloc[0],
                    "points": np.column_stack([g["season"], g[metric]])})
        stars[pid] = fit
    return stars


def detect_eras(stars: dict, years: range) -> tuple[list, list]:
    """Count stars inside their peak window each season; runs with >= MIN_OVERLAP are eras."""
    series = []
    for y in years:
        inside = [pid for pid, s in stars.items() if s["window"][0] <= y + 0.5 and y - 0.5 <= s["window"][1]]
        strength = 0.0
        for pid in inside:
            c = stars[pid]["curve"]
            strength += float(np.interp(y, c[:, 0], c[:, 1]))
        series.append({"year": y, "count": len(inside), "strength": round(strength, 2), "players": inside})

    runs, cur = [], None
    for row in series:
        if row["count"] >= MIN_OVERLAP:
            if cur and row["year"] - cur["end"] <= MAX_GAP + 1:
                cur["end"] = row["year"]
                cur["rows"].append(row)
            else:
                cur = {"start": row["year"], "end": row["year"], "rows": [row]}
                runs.append(cur)
    by_year = {row["year"]: row for row in series}
    pieces = []
    for r in runs:
        span = [by_year[y] for y in range(r["start"], r["end"] + 1)]
        for piece in _split_at_valleys(span):
            pieces.extend(_split_at_turnover(piece))

    eras = []
    for rows in pieces:
        rows = [x for x in rows if x["count"] >= MIN_OVERLAP] or rows
        start, end = rows[0]["year"], rows[-1]["year"]
        if end - start + 1 < MIN_LENGTH:
            continue
        top = max(rows, key=lambda x: x["strength"])
        players = sorted({p for x in rows for p in x["players"]}, key=lambda p: -stars[p]["height"])
        eras.append({"id": f"era{len(eras) + 1}", "start": start, "end": end,
                     "length": end - start + 1, "peakYear": top["year"],
                     "peakStrength": top["strength"], "peakCount": top["count"], "players": players})
    return eras, series


def _split_at_turnover(rows: list) -> list:
    """Cut a long run where one group of stars hands over to the next.

    For each candidate boundary, compare the stars peaking in the TURNOVER_SPAN seasons before
    with those in the TURNOVER_SPAN seasons after; split at the lowest overlap if it is at most
    TURNOVER_MAX, then check both halves again."""
    if len(rows) < TURNOVER_MIN_LEN:
        return [rows]
    best, best_j = None, 2.0
    k = TURNOVER_SPAN
    for i in range(k, len(rows) - k + 1):
        before = set().union(*(set(r["players"]) for r in rows[i - k:i]))
        after = set().union(*(set(r["players"]) for r in rows[i:i + k]))
        if not before or not after:
            continue
        j = len(before & after) / len(before | after)
        if j < best_j:
            best, best_j = i, j
    if best is None or best_j > TURNOVER_MAX:
        return [rows]
    return _split_at_turnover(rows[:best]) + _split_at_turnover(rows[best:])


def _split_at_valleys(rows: list) -> list:
    """Cut a run where strength falls to a valley well below the peaks on both sides.

    That valley is where one group of peaks fades before the next takes over; the valley
    season itself is treated as a transition and belongs to neither era.
    """
    s = pd.Series([x["strength"] for x in rows]).rolling(3, center=True, min_periods=1).mean().to_numpy()
    peaks = [i for i in range(len(s)) if (i == 0 or s[i] >= s[i - 1]) and (i == len(s) - 1 or s[i] > s[i + 1])]
    cuts = []
    for a, b in zip(peaks, peaks[1:]):
        v = a + int(np.argmin(s[a:b + 1]))
        if s[v] <= SPLIT_RATIO * min(s[a], s[b]):
            cuts.append(v)
    out, lo = [], 0
    for v in cuts:
        if v > lo:
            out.append(rows[lo:v])
        lo = v + 1
    out.append(rows[lo:])
    return [p for p in out if p]


def era_years(eras: list, lo: int, hi: int) -> set:
    return {y for e in eras for y in range(e["start"], e["end"] + 1) if lo <= y <= hi}


def agreement(eras_by_metric: dict, coverage: dict) -> list:
    """Jaccard overlap of era years between metrics, over the seasons both metrics cover."""
    out, names = [], list(eras_by_metric)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            lo = max(coverage[a][0], coverage[b][0])
            hi = min(coverage[a][1], coverage[b][1])
            A, B = era_years(eras_by_metric[a], lo, hi), era_years(eras_by_metric[b], lo, hi)
            j = len(A & B) / len(A | B) if (A | B) else 1.0
            out.append({"a": a, "b": b, "from": lo, "to": hi, "jaccard": round(j, 3)})
    return out
