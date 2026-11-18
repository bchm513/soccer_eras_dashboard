"""Density hubs (centres of gravity) and tournament spikes on a monthly timeline."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

EARTH_KM = 6371.0
HUB_RADIUS_KM = 250      # cities within this chain together into one hub
ROLLING_SEASONS = 3      # club baseline smoothing
TOURNAMENT_CAP = {"World Cup": 1.5, "Euro": 1.1}   # x the largest club hub that month
FADE = [0.55, 0.25, 0.08]  # months after a tournament ends
LEAD_IN = 0.3            # month before it starts


def find_hubs(ps: pd.DataFrame, stars: dict, metric: str) -> tuple[list, pd.DataFrame]:
    """Cluster the cities where stars played; each cluster is a hub."""
    rows = ps[ps["player_id"].isin(stars) & ps["lat"].notna()].copy()
    rows["w"] = rows[metric].clip(lower=0)
    cities = rows.groupby("city").agg(lat=("lat", "first"), lon=("lon", "first"), w=("w", "sum")).reset_index()
    labels = DBSCAN(eps=HUB_RADIUS_KM / EARTH_KM, min_samples=1, metric="haversine").fit_predict(
        np.radians(cities[["lat", "lon"]].to_numpy()))
    cities["hub"] = labels
    hubs = []
    for h, g in cities.groupby("hub"):
        g = g.sort_values("w", ascending=False)
        w = g["w"].clip(lower=1e-6)
        hubs.append({"id": f"hub{h}", "name": "–".join(g["city"].head(2)),
                     "cities": g["city"].tolist(),
                     "lat": round(float(np.average(g["lat"], weights=w)), 3),
                     "lon": round(float(np.average(g["lon"], weights=w)), 3)})
    city_to_hub = {c: f"hub{h}" for c, h in zip(cities["city"], cities["hub"])}
    rows["hub"] = rows["city"].map(city_to_hub)
    return hubs, rows


def month_index(start: str, ym: str) -> int:
    y0, m0 = map(int, start.split("-"))
    y, m = map(int, ym.split("-"))
    return (y - y0) * 12 + (m - m0)


def club_weights(rows: pd.DataFrame, hubs: list, metric: str, first: int, last: int, start: str, n: int) -> dict:
    """Hub weight per season (rolling mean), interpolated to months. A season runs Aug -> May."""
    seasons = np.arange(first, last + 1)
    table = (rows.assign(w=rows[metric].clip(lower=0))
             .pivot_table(index="season", columns="hub", values="w", aggfunc="sum")
             .reindex(seasons).fillna(0))
    table = table.rolling(ROLLING_SEASONS, center=True, min_periods=1).mean()
    season_mid = np.array([month_index(start, f"{s}-12") for s in seasons])  # weight anchored mid-season
    frames = np.arange(n)
    return {h["id"]: np.round(np.interp(frames, season_mid, table.get(h["id"], pd.Series(0, index=seasons)).to_numpy()), 2)
            for h in hubs}


def tournament_weights(tournaments: list, club: dict, start: str, n: int) -> list:
    biggest = np.max(np.vstack(list(club.values())), axis=0) if club else np.zeros(n)
    out = []
    for i, (kind, year, host, city, lat, lon, s, e) in enumerate(tournaments):
        a, b = month_index(start, s), month_index(start, e)
        if b < 0 or a >= n:
            continue
        cap = TOURNAMENT_CAP.get(kind, 1.0)
        series = []
        for f in range(a - 1, b + len(FADE) + 1):
            if not 0 <= f < n:
                continue
            if f < a:
                k = LEAD_IN
            elif f <= b:
                k = 1.0
            else:
                k = FADE[f - b - 1]
            series.append([f, round(float(cap * k * biggest[min(max(f, 0), n - 1)]), 2)])
        out.append({"id": f"t{i}", "type": kind, "year": year, "host": host, "city": city,
                    "lat": lat, "lon": lon, "startFrame": a, "endFrame": b, "weights": series})
    return out
