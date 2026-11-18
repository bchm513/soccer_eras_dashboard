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
SPLIT_RATIO = 0.7      # split a run where strength dips below 70% of the peaks either side

METRICS = ["goals_adj", "goals_raw", "ga_adj"]


def _row_z(df: pd.DataFrame, value: str, by_season: bool) -> pd.Series:
    keys = ["competition", "season"] if by_season else ["comp_type"]
    ref = df[df["apps"] >= MIN_APPS]
    stats = ref.groupby(keys)[value].agg(["mean", "std"]).reset_index()
    m = df.merge(stats, on=keys, how="left")
    return ((m[value] - m["mean"]) / m["std"].replace(0, np.nan)).to_numpy()


def player_season_scores(df: pd.DataFrame) -> pd.DataFrame:
    """One row per player-season with a z-score per metric (club + international combined)."""
    df = df.copy()
    df["apps"] = df["apps"].astype(float)
    df["g_rate"] = df["goals"] / df["apps"].clip(lower=1)
    has_ast = pd.to_numeric(df["assists"], errors="coerce")
    df["ga_rate"] = (df["goals"] + has_ast) / df["apps"].clip(lower=1)

    df["z_goals_adj"] = _row_z(df, "g_rate", by_season=True)
    df["z_goals_raw"] = _row_z(df, "g_rate", by_season=False)
    df["z_ga_adj"] = _row_z(df, "ga_rate", by_season=True)

    # Apps-weighted mean of row z-scores per player-season (club + international = overall output)
    keys = ["player_id", "season"]
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
        bounds = ([0, years.min() - 2, 1.0, -3], [12, years.max() + 2, 12, 3])
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


def find_stars(ps: pd.DataFrame, metric: str) -> dict:
    stars = {}
    for pid, g in ps.dropna(subset=[metric]).groupby("player_id"):
        if (g[metric] >= FLAG_Z).sum() < MIN_FLAGGED:
            continue
        g = g.sort_values("season")
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
        pieces.extend(_split_at_valleys(span))

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
