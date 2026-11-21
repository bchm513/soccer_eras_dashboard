"""Run the full pipeline and write dashboard/data/eras.json.

Reads the project database (data/football.db, built by `python -m scraper.run assemble`);
with no real data yet it generates the SAMPLE dataset instead.
    python pipeline/build.py            # auto
    python pipeline/build.py --sample   # force sample data
    python pipeline/build.py --input other/raw/player_seasons.csv --output other/eras.json
"""
from __future__ import annotations

import json
import sys
import warnings
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(Path(__file__).parent), str(ROOT)]
import eras as E          # noqa: E402
import hotspots as H      # noqa: E402
from sample_data import generate  # noqa: E402
from tournaments import TOURNAMENTS  # noqa: E402
from core import competitions, db, geo, paths  # noqa: E402

PRIMARY = "goals_adj"
MIN_REGION_ROWS = 150      # club rows a confederation needs before it gets its own stars and eras
CONFED_NAMES = {"UEFA": "Europe", "CONMEBOL": "South America", "CONCACAF": "North & Central America",
                "AFC": "Asia & Australia", "CAF": "Africa", "OFC": "Oceania"}


def _clean(o):
    """Make data strict JSON: numpy -> Python, NaN/inf -> null (browsers reject NaN)."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        o = o.item()
    if isinstance(o, float) and not np.isfinite(o):
        return None
    if isinstance(o, (str, int, float, bool)) or o is None:
        return o
    return str(o)


def r2(a):
    return [[int(x), round(float(y), 2)] for x, y in a]


warnings.filterwarnings("ignore", message="Covariance of the parameters could not be estimated")


# ---------------------------------------------------------------- inputs from the database

def load_player_seasons(raw: Path) -> pd.DataFrame:
    df = db.load("player_seasons", raw)
    if df is None:
        raise SystemExit("No player_seasons table. Run `python -m scraper.run assemble` first.")
    if "tournament_goals" in df and "continental_goals" not in df:
        raise SystemExit("player_seasons was built by an older version. Run `python -m scraper.run assemble` again.")
    return df


def strength_factors(raw: Path, league_codes: set) -> pd.DataFrame | None:
    """Factor per (code, season) vs that season's 4 strongest leagues, as for player output."""
    s = db.load("league_strength_world", raw)
    if s is None:
        return None
    ref = (s[s["code"].isin(league_codes)].groupby("season")["elo"]
           .apply(lambda x: x.nlargest(E.LEAGUE_ELO_REF_TOP).mean()))
    gap = (s["elo"] - s["season"].map(ref)).clip(upper=0)
    s["factor"] = 10 ** (E.LEAGUE_ELO_WEIGHT * gap / 400)
    return s[["code", "season", "factor"]]


def load_finals(raw: Path, factors: pd.DataFrame | None) -> pd.DataFrame | None:
    """Continental finalists (located by `assemble`) with a title weight scaled by league strength."""
    f = db.load("finals", raw)
    if f is None or f.empty:
        return None
    f = f.dropna(subset=["city", "lat", "lon"]).copy()
    fac = {} if factors is None else {(c, s): v for c, s, v in factors.itertuples(index=False)}
    med = {} if factors is None else factors.groupby("season")["factor"].median().to_dict()
    f["season"] = f["season"].astype(int)
    f["factor"] = [fac.get((c, s), med.get(s, 1.0)) for c, s in zip(f["code"], f["season"])]
    cup_w = {c.code: c.title_weight for c in competitions.CLUB_CUPS.values()}
    f["weight"] = f["side"].map(H.TITLE_BONUS).fillna(0) * f["comp"].map(cup_w).fillna(1.0) * f["factor"]
    return f.rename(columns={"side": "kind"})


def all_tournaments(raw: Path | None) -> list:
    out = list(TOURNAMENTS)
    te = db.load("tournament_editions", raw) if raw else None
    if te is not None:
        for r in te.itertuples():
            out.append((r.type, int(r.year), r.host, r.city, float(r.lat), float(r.lon), r.start, r.end))
    return out


def growth_data(raw: Path, df: pd.DataFrame) -> dict:
    out = {"series": [], "countries": {}, "leagueCoverage": {}, "impact": {}}
    club = df[df["comp_type"] == "club"]
    leagues_per = club.groupby("season")["competition"].nunique().to_dict()
    g = db.load("growth", raw)
    if g is not None:
        last_club = int(club["season"].max()) if len(club) else 9999
        for r in g.itertuples():
            if int(r.season) > last_club:          # the current season is only partly played
                continue
            out["series"].append({"season": int(r.season), "nations": int(r.nations_active),
                                  "nationsTotal": int(r.nations_total), "matches": int(r.matches),
                                  "leagues": int(leagues_per.get(int(r.season), 0))})
    cf = db.load("country_first", raw)
    if cf is not None:
        out["countries"] = {r.country: int(r.first_season) for r in cf.itertuples()}
    cov: dict = {}
    for (code, season), _ in club.groupby(["competition", "season"]):
        team = geo.team_for(code, int(season))
        if team:
            name = geo.map_name(team)
            lo, hi = cov.get(name, (int(season), int(season)))
            cov[name] = (min(lo, int(season)), max(hi, int(season)))
    out["leagueCoverage"] = {k: list(v) for k, v in cov.items()}
    imp = db.load("manual_impact_manual", raw)
    if imp is not None and len(imp):
        imp = imp.dropna(subset=["season", "metric", "value"])
        out["impact"] = {m: [[int(s), float(v)] for s, v in grp[["season", "value"]].itertuples(index=False)]
                         for m, grp in imp.groupby("metric")}
    return out


def moments_data(raw: Path) -> dict:
    """Big moments by season (tournament finals, continental club finals, your own entries)."""
    m = db.load("moments", raw)
    if m is None or m.empty:
        return {}
    out: dict = {}
    m["weight"] = pd.to_numeric(m["weight"], errors="coerce").fillna(1)
    for r in m.sort_values("weight", ascending=False).itertuples():
        lat, lon = pd.to_numeric(r.lat, errors="coerce"), pd.to_numeric(r.lon, errors="coerce")
        out.setdefault(str(int(r.season)), []).append({
            "title": r.title, "detail": r.detail if isinstance(r.detail, str) else "", "kind": r.kind,
            "lat": None if pd.isna(lat) else float(lat), "lon": None if pd.isna(lon) else float(lon),
            "players": r.players if isinstance(r.players, str) else ""})
    return out


def era_table(eras: list, stars: dict, league_at_peak: dict, growth: dict, finals, tours: list) -> list:
    nations = {g["season"]: g["nations"] for g in growth.get("series", [])}
    rows = []
    for e in eras:
        yrs = range(e["start"], e["end"] + 1)
        ps = e["players"]
        att = None
        if finals is not None and "attendance" in finals:
            a = pd.to_numeric(finals[(finals["season"].isin(yrs)) & (finals["kind"] == "winner")]["attendance"], errors="coerce")
            att = round(float(a.mean())) if a.notna().any() else None
        imp = {m: round(float(np.mean([v for s, v in series if s in yrs])), 1)
               for m, series in growth.get("impact", {}).items() if any(s in yrs for s, _ in series)}
        rows.append({"id": e["id"], "start": e["start"], "end": e["end"], "length": e["length"],
                     "peakStrength": e["peakStrength"], "peakCount": e["peakCount"], "stars": len(ps),
                     "leagues": sorted({league_at_peak.get(p) for p in ps if league_at_peak.get(p)}),
                     "nationsActive": round(float(np.mean([nations[y] for y in yrs if y in nations]))) if any(y in nations for y in yrs) else None,
                     "finalAttendance": att,
                     "tournaments": sum(1 for t in tours if e["start"] <= t["year"] - 1 <= e["end"]),
                     "impact": imp, "hub": e.get("hub")})
    return rows


def star_records(stars: dict, ps: pd.DataFrame, star_rows: pd.DataFrame | None) -> tuple[list, dict]:
    league_at_peak = {}
    for pid, s in stars.items():
        r = ps[(ps["player_id"] == pid) & ps["league"].notna()]
        if len(r):
            league_at_peak[pid] = r.iloc[(r["season"] - s["peak"]).abs().argsort()[:1]]["league"].iloc[0]
    hub_by = star_rows.set_index(["player_id", "season"])["hub"].to_dict() if star_rows is not None else {}
    city_by = ps.dropna(subset=["city"]).drop_duplicates(["player_id", "season"]).set_index(["player_id", "season"])["city"].to_dict()
    out = []
    for pid, s in sorted(stars.items(), key=lambda kv: kv[1]["peak"]):
        seasons = [int(y) for y, _ in s["points"]]
        out.append({
            "id": pid, "name": s["player"], "peak": round(s["peak"], 2),
            "window": [round(x, 2) for x in s["window"]], "height": round(s["height"], 2),
            "fit": s["fit"], "curve": r2(s["curve"]), "points": r2(s["points"]),
            "clubs": [[y, city_by.get((pid, y)), hub_by.get((pid, y))] for y in seasons],
            "league": league_at_peak.get(pid),
        })
    return out, league_at_peak


def regional(df: pd.DataFrame) -> dict:
    """Stars and eras within each confederation, measured against that confederation's own leagues."""
    out = {}
    if "confed" not in df:
        return out
    club = df[df["comp_type"] == "club"]
    for confed, g in club.groupby("confed"):
        if not isinstance(confed, str) or not confed or len(g) < MIN_REGION_ROWS:
            continue
        sub = pd.concat([g, df[(df["comp_type"] != "club") & df["player_id"].isin(set(g["player_id"]))]])
        ps = E.player_season_scores(sub)
        st = E.find_stars(ps, PRIMARY, require_club=True, flag_z=E.FLAG_Z_ENV)
        if not st:
            continue
        lo, hi = int(sub["season"].min()), int(sub["season"].max())
        er, series = E.detect_eras(st, range(lo, hi + 1))
        recs, _ = star_records(st, ps, None)
        out[confed] = {"name": CONFED_NAMES.get(confed, confed), "stars": recs, "eras": er,
                       "series": [{k: v for k, v in r.items() if k != "players"} for r in series]}
    return out


# ---------------------------------------------------------------- main

def main(force_sample: bool = False, src: Path | None = None, out: Path = paths.DASHBOARD_DATA) -> dict:
    raw_dir = src.parent if src else paths.RAW
    is_sample = src is None and (force_sample or db.load("player_seasons", raw_dir) is None)
    scraped = [f.name for f in raw_dir.glob("*.csv")] if raw_dir.exists() else []
    if is_sample and not force_sample and scraped:
        # Scraped files exist but haven't been built into the database: never hide that behind sample data
        raise SystemExit(
            f"Found {len(scraped)} scraped files in data/raw/, but the database has no player_seasons table yet.\n"
            "Load them and build it with:\n\n"
            "    python -m scraper.run assemble\n"
            "    python pipeline/build.py\n\n"
            "(Use --sample to build the sample dashboard anyway.)")
    if is_sample:
        generate(paths.SAMPLE)
        src = paths.SAMPLE
        df = pd.read_csv(src, low_memory=False)
    else:
        src = src or raw_dir / "player_seasons.csv"
        df = load_player_seasons(raw_dir)
    first, last = int(df["season"].min()), int(df["season"].max())

    ps = E.player_season_scores(df)
    metrics = [m for m in E.METRICS if ps[m].notna().any()]
    # A measure "covers" the seasons where club rows have it (international assists exist
    # long before club assists do, which would make the agreement scores misleading)
    coverage = {m: (int(ps.dropna(subset=[m])["season"].min()), last) for m in metrics}
    env_mode = E.uses_environment(df)
    if env_mode and "ga_adj" in coverage:
        club_ast = df[(df["comp_type"] == "club") & pd.to_numeric(df["assists"], errors="coerce").notna()]
        if club_ast.empty:
            metrics.remove("ga_adj"); coverage.pop("ga_adj")
        else:
            start_ = int(club_ast["season"].min())
            coverage["ga_adj"] = (start_, last)
            ps.loc[ps["season"] < start_, "ga_adj"] = np.nan
    flag_z = E.FLAG_Z_ENV if env_mode else E.FLAG_Z
    stars_by = {m: E.find_stars(ps, m, require_club=env_mode, flag_z=flag_z) for m in metrics}
    eras_by, series_by = {}, {}
    for m in metrics:
        eras_by[m], series_by[m] = E.detect_eras(stars_by[m], range(coverage[m][0], last + 1))

    # Map timeline: monthly frames from Aug of the first season to Dec of the season after last
    start = f"{first}-08"
    n = H.month_index(start, f"{last + 1}-12") + 1
    stars = stars_by[PRIMARY]
    hub_min_z = H.HUB_MIN_Z["real" if env_mode else "sample"]
    league_codes = set(df.loc[df["comp_type"] == "club", "competition"])
    factors = strength_factors(raw_dir, league_codes) if env_mode else None
    finals = load_finals(raw_dir, factors) if env_mode else None
    hubs, star_rows = H.find_hubs(ps, stars, PRIMARY, min_z=hub_min_z,
                                  extra_cities=None if finals is None else finals[["city", "lat", "lon"]])
    hub_detail = H.hub_players(star_rows, stars, PRIMARY)
    titles = None
    if finals is not None:
        finals["hub"] = finals["city"].map(star_rows.attrs.get("city_to_hub", {}))
        titles = finals[["season", "hub", "kind", "weight"]]
    club = H.club_weights(star_rows, hubs, PRIMARY, first, last, start, n, titles=titles)
    tours = H.tournament_weights(all_tournaments(raw_dir if env_mode else None), club, start, n)

    for e in eras_by[PRIMARY]:          # era -> dominant hub
        sub = star_rows[(star_rows["season"] >= e["start"]) & (star_rows["season"] <= e["end"])]
        if len(sub):
            e["hub"] = sub.assign(w=sub[PRIMARY].clip(lower=0)).groupby("hub")["w"].sum().idxmax()

    star_out, league_at_peak = star_records(stars, ps, star_rows)
    alt = {m: [{"id": pid, "name": s["player"], "peak": round(s["peak"], 2),
                "window": [round(x, 2) for x in s["window"]]} for pid, s in stars_by[m].items()]
           for m in metrics if m != PRIMARY}
    growth = growth_data(raw_dir, df) if env_mode else {"series": [], "countries": {}, "leagueCoverage": {}, "impact": {}}
    regions = regional(df) if env_mode else {}
    champions: dict = {}
    if finals is not None:
        for (s, comp), g in finals.groupby(["season", "comp"]):
            champions.setdefault(str(int(s)), {})[comp] = {r.kind: [r.team, r.hub] for r in g.itertuples()}

    data = {
        "meta": {
            "sample": is_sample, "source": "data/football.db" if not is_sample else str(src.relative_to(ROOT)),
            "built": date.today().isoformat(),
            "primaryMetric": PRIMARY, "flagZ": flag_z, "minFlagged": E.MIN_FLAGGED,
            "peakFraction": E.PEAK_FRACTION, "minOverlap": E.MIN_OVERLAP,
            "firstSeason": first, "lastSeason": last, "start": start, "frames": n,
            "coverage": coverage, "confedNames": CONFED_NAMES, "competitions": competitions.for_dashboard(),
            "note": ("SAMPLE DATA: fictional players with simulated numbers. Cities and tournament "
                     "hosts/dates are real.") if is_sample else
                    ("Club goals: league top scorers (Wikipedia; Transfermarkt open data from 2012), weighted by "
                     "team games. Big moments weighted up: World Cup x4, continental championships x3, Champions "
                     "League and Europa League x2, other cups and tournaments x1. Internationals: competitive matches with scorer records (martj42). League "
                     "scoring rates: engsoccerdata and Wikipedia league tables. League strength: ClubElo where "
                     "available, else national-team Elo with a talent-exodus correction."),
        },
        "hubs": hubs,
        "clubWeights": {k: v.tolist() for k, v in club.items()},
        "hubPlayers": hub_detail,
        "champions": champions,
        "tournaments": tours,
        "stars": star_out,
        "altStars": alt,
        "eras": eras_by,
        "eraSeries": {m: [{k: v for k, v in row.items() if k != "players"} for row in series_by[m]]
                      for m in metrics},
        "agreement": E.agreement({m: e for m, e in eras_by.items() if e},
                                 {m: c for m, c in coverage.items() if eras_by[m]}),
        "regions": regions,
        "growth": growth,
        "moments": moments_data(raw_dir) if env_mode else {},
        "eraTable": era_table(eras_by[PRIMARY], stars, league_at_peak, growth, finals, tours),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_clean(data), separators=(",", ":"), allow_nan=False), encoding="utf-8")
    return data


if __name__ == "__main__":
    args = sys.argv[1:]
    src = Path(args[args.index("--input") + 1]).resolve() if "--input" in args else None
    out = Path(args[args.index("--output") + 1]).resolve() if "--output" in args else paths.DASHBOARD_DATA
    d = main(force_sample="--sample" in args, src=src, out=out)
    print(f"{'SAMPLE' if d['meta']['sample'] else 'REAL'} data | stars: {len(d['stars'])} | hubs: {len(d['hubs'])} "
          f"| frames: {d['meta']['frames']} | tournaments: {len(d['tournaments'])}")
    for m, es in d["eras"].items():
        print(f"  {m}: " + ", ".join(f"{e['start']}-{e['end']}" for e in es))
    lg = {}
    for s in d["stars"]:
        lg[s.get("league") or "?"] = lg.get(s.get("league") or "?", 0) + 1
    if "?" not in lg or len(lg) > 1:
        print("  stars by league at peak: " + ", ".join(f"{k} {v}" for k, v in sorted(lg.items(), key=lambda x: -x[1])))
    for a in d["agreement"]:
        print(f"  agreement {a['a']} vs {a['b']} ({a['from']}-{a['to']}): {a['jaccard']}")
    for c, r in d["regions"].items():
        print(f"  region {r['name']}: {len(r['stars'])} stars, eras " + (", ".join(f"{e['start']}-{e['end']}" for e in r["eras"]) or "none"))
    if d["growth"]["series"]:
        g = d["growth"]["series"]
        print(f"  growth: {g[0]['nations']} nations playing in {g[0]['season']} -> {g[-2]['nations']} in {g[-2]['season']}")
    print(f"  -> {out}")
    if out == paths.DASHBOARD_DATA:
        print("Next: python serve.py   (opens http://localhost:8000 in your browser)")
