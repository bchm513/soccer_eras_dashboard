"""Density hubs (centres of gravity) and tournament spikes on a monthly timeline."""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering

EARTH_KM = 6371.0
HUB_DIAMETER_KM = 250    # every city in a hub is within this distance of every other
ROLLING_SEASONS = 3      # club baseline smoothing
HUB_MIN_Z = {"real": 0.0, "sample": 1.0}   # map pool: club seasons at/above this z also feed hubs
TITLE_BONUS = {"winner": 1.0, "runner_up": 0.4}   # European final: x the season's biggest hub weight
TOURNAMENT_CAP = {"World Cup": 1.5, "Euro": 1.1, "Copa América": 1.0, "AFCON": 0.7, "Asian Cup": 0.7,
                  "Gold Cup": 0.6, "Confederations Cup": 0.5}   # x the largest club hub that month
FADE = [0.55, 0.25, 0.08]  # months after a tournament ends
LEAD_IN = 0.3            # month before it starts


def _haversine_km(a: np.ndarray) -> np.ndarray:
    lat, lon = np.radians(a[:, 0])[:, None], np.radians(a[:, 1])[:, None]
    d = np.sin((lat - lat.T) / 2) ** 2 + np.cos(lat) * np.cos(lat.T) * np.sin((lon - lon.T) / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(d, 0, 1)))


def _cluster(coords: np.ndarray) -> np.ndarray:
    """Complete-linkage clustering: no chaining city to city across a country
    (single-link joined Milan to Marseille via the Riviera clubs)."""
    if len(coords) < 2:
        return np.zeros(len(coords), dtype=int)
    return AgglomerativeClustering(n_clusters=None, metric="precomputed", linkage="complete",
                                   distance_threshold=HUB_DIAMETER_KM).fit_predict(_haversine_km(coords))


def find_hubs(ps: pd.DataFrame, stars: dict, metric: str, min_z: float | None = None,
              extra_cities: pd.DataFrame | None = None) -> tuple[list, pd.DataFrame]:
    """Cluster the cities where strong scoring seasons happened; each cluster is a hub.

    The pool is every star season plus, when min_z is set, every club season at or above
    min_z. Stars alone light up only one or two cities in many years; the wider pool shows
    everywhere goals were being scored at a high level, while eras stay star-defined."""
    keep = ps["player_id"].isin(stars)
    if min_z is not None:
        keep |= ps[metric] >= min_z
    rows = ps[keep & ps["lat"].notna()].copy()
    rows["w"] = rows[metric].clip(lower=0)
    cities = rows.groupby("city").agg(lat=("lat", "first"), lon=("lon", "first"), w=("w", "sum")).reset_index()
    if extra_cities is not None and len(extra_cities):        # e.g. European finalists' cities
        extra = extra_cities.drop_duplicates("city")
        extra = extra[~extra["city"].isin(cities["city"])].assign(w=0.0)[["city", "lat", "lon", "w"]]
        cities = pd.concat([cities, extra], ignore_index=True)
    labels = _cluster(cities[["lat", "lon"]].to_numpy())
    cities["hub"] = labels
    hubs = []
    for h, g in cities.groupby("hub"):
        g = g.sort_values("w", ascending=False)
        w = g["w"].clip(lower=1e-6)
        # Second city in the name only if it carries at least a third of the leader's weight
        top = g["city"].head(2).tolist()
        if len(top) == 2 and g["w"].iloc[1] < g["w"].iloc[0] / 3:
            top = top[:1]
        hubs.append({"id": f"hub{h}", "name": "–".join(top),
                     "cities": g["city"].tolist(),
                     "lat": round(float(np.average(g["lat"], weights=w)), 3),
                     "lon": round(float(np.average(g["lon"], weights=w)), 3)})
    city_to_hub = {c: f"hub{h}" for c, h in zip(cities["city"], cities["hub"])}
    rows["hub"] = rows["city"].map(city_to_hub)
    rows.attrs["city_to_hub"] = city_to_hub
    return hubs, rows


def month_index(start: str, ym: str) -> int:
    y0, m0 = map(int, start.split("-"))
    y, m = map(int, ym.split("-"))
    return (y - y0) * 12 + (m - m0)


def club_weights(rows: pd.DataFrame, hubs: list, metric: str, first: int, last: int, start: str, n: int,
                 titles: pd.DataFrame | None = None) -> dict:
    """Hub weight per season (rolling mean), interpolated to months. A season runs Aug -> May.

    titles (season, hub, kind): European Cup / Champions League finalists. The winner's hub gets
    TITLE_BONUS['winner'] x that season's biggest hub weight, the runner-up's a smaller share,
    so a club's European dominance shows on the map even when its league scoring doesn't."""
    seasons = np.arange(first, last + 1)
    table = (rows.assign(w=rows[metric].clip(lower=0))
             .pivot_table(index="season", columns="hub", values="w", aggfunc="sum")
             .reindex(seasons).fillna(0))
    if titles is not None and len(titles):
        biggest = table.max(axis=1)
        for t in titles.dropna(subset=["hub"]).itertuples():
            if t.season in table.index:
                if t.hub not in table.columns:
                    table[t.hub] = 0.0
                w = getattr(t, "weight", None)
                w = TITLE_BONUS.get(t.kind, 0) if w is None or pd.isna(w) else w
                table.loc[t.season, t.hub] += w * biggest.get(t.season, 0)
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
        cap = TOURNAMENT_CAP.get(kind, 0.6)
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


def hub_players(rows: pd.DataFrame, stars: dict, metric: str, top: int = 4) -> dict:
    """Top scorers per hub per season, for the dashboard's hub detail panel."""
    out: dict = {}
    r = rows.dropna(subset=["hub", metric]).sort_values(metric, ascending=False)
    for (hub, season), g in r.groupby(["hub", "season"]):
        out.setdefault(hub, {})[str(int(season))] = [
            [str(x.player), x.city, int(x.goals), round(float(getattr(x, metric)), 2), x.player_id in stars]
            for x in g.head(top).itertuples()]
    return out
