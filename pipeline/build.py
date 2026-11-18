"""Run the full pipeline and write dashboard/data/eras.json.

Uses data/raw/player_seasons.csv when it exists; otherwise generates the SAMPLE dataset.
    python pipeline/build.py            # auto
    python pipeline/build.py --sample   # force sample data
"""
from __future__ import annotations

import json
import sys
import warnings
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import eras as E          # noqa: E402
import hotspots as H      # noqa: E402
from sample_data import generate  # noqa: E402
from tournaments import TOURNAMENTS  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "player_seasons.csv"
SAMPLE = ROOT / "data" / "sample" / "player_seasons.csv"
OUT = ROOT / "dashboard" / "data" / "eras.json"
PRIMARY = "goals_adj"


def load_finals(raw_dir: Path) -> pd.DataFrame | None:
    """European Cup / Champions League finalists with their cities (data/raw/europe_finals.csv)."""
    p = raw_dir / "europe_finals.csv"
    if not p.exists():
        return None
    sys.path.insert(0, str(ROOT))
    from scraper.clubs import ClubResolver
    from scraper.europe import COUNTRY_CODE
    f = pd.read_csv(p)
    res = ClubResolver(raw_dir)
    rows = []
    for r in f.itertuples():
        for kind, team, country in (("winner", r.winner, r.winner_country), ("runner_up", r.runner_up, r.runner_up_country)):
            code = COUNTRY_CODE.get(str(country).strip().lower(), "")
            city, lat, lon, _ = res.resolve(str(team), code)
            if city:
                rows.append({"season": int(r.season), "kind": kind, "team": team, "city": city, "lat": lat, "lon": lon})
    return pd.DataFrame(rows) if rows else None


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


def main(force_sample: bool = False, src: Path | None = None, out: Path = OUT) -> dict:
    is_sample = src is None and (force_sample or not RAW.exists())
    src = src or (SAMPLE if is_sample else RAW)
    if is_sample:
        generate(SAMPLE)
    df = pd.read_csv(src)
    first, last = int(df["season"].min()), int(df["season"].max())

    ps = E.player_season_scores(df)
    metrics = [m for m in E.METRICS if ps[m].notna().any()]
    # A measure "covers" the seasons where club rows have it (international assists exist
    # long before club assists do, which would make the agreement scores misleading)
    coverage = {m: (int(ps.dropna(subset=[m])["season"].min()), last) for m in metrics}
    if E.uses_environment(df) and "ga_adj" in coverage:
        club_ast = df[(df["comp_type"] == "club") & pd.to_numeric(df["assists"], errors="coerce").notna()]
        if club_ast.empty:
            metrics.remove("ga_adj"); coverage.pop("ga_adj")
        else:
            start = int(club_ast["season"].min())
            coverage["ga_adj"] = (start, last)
            ps.loc[ps["season"] < start, "ga_adj"] = np.nan
    env_mode = E.uses_environment(df)
    flag_z = E.FLAG_Z_ENV if env_mode else E.FLAG_Z
    stars_by = {m: E.find_stars(ps, m, require_club=env_mode, flag_z=flag_z) for m in metrics}
    eras_by, series_by = {}, {}
    for m in metrics:
        lo = coverage[m][0]
        eras_by[m], series_by[m] = E.detect_eras(stars_by[m], range(lo, last + 1))

    # Map timeline: monthly frames from Aug of the first season to Dec of the season after last
    start = f"{first}-08"
    n = H.month_index(start, f"{last + 1}-12") + 1
    stars = stars_by[PRIMARY]
    hub_min_z = H.HUB_MIN_Z["real" if env_mode else "sample"]
    finals = load_finals(src.parent) if env_mode else None
    hubs, star_rows = H.find_hubs(ps, stars, PRIMARY, min_z=hub_min_z,
                                  extra_cities=None if finals is None else finals[["city", "lat", "lon"]])
    hub_detail = H.hub_players(star_rows, stars, PRIMARY)
    titles = None
    if finals is not None:
        finals["hub"] = finals["city"].map(star_rows.attrs.get("city_to_hub", {}))
        titles = finals[["season", "hub", "kind"]]
    club = H.club_weights(star_rows, hubs, PRIMARY, first, last, start, n, titles=titles)
    tours = H.tournament_weights(TOURNAMENTS, club, start, n)

    # Era -> dominant hub
    for e in eras_by[PRIMARY]:
        sub = star_rows[(star_rows["season"] >= e["start"]) & (star_rows["season"] <= e["end"])]
        if len(sub):
            e["hub"] = sub.assign(w=sub[PRIMARY].clip(lower=0)).groupby("hub")["w"].sum().idxmax()

    league_at_peak = {}
    for pid, s in stars.items():
        r = ps[(ps["player_id"] == pid) & ps["league"].notna()]
        if len(r):
            league_at_peak[pid] = r.iloc[(r["season"] - s["peak"]).abs().argsort()[:1]]["league"].iloc[0]
    hub_by = star_rows.set_index(["player_id", "season"])["hub"].to_dict()
    city_by = star_rows.set_index(["player_id", "season"])["city"].to_dict()
    star_out = []
    for pid, s in sorted(stars.items(), key=lambda kv: kv[1]["peak"]):
        seasons = [int(y) for y, _ in s["points"]]
        star_out.append({
            "id": pid, "name": s["player"], "peak": round(s["peak"], 2),
            "window": [round(x, 2) for x in s["window"]], "height": round(s["height"], 2),
            "fit": s["fit"], "curve": r2(s["curve"]), "points": r2(s["points"]),
            "clubs": [[y, city_by.get((pid, y)), hub_by.get((pid, y))] for y in seasons],
            "league": league_at_peak.get(pid),
        })

    alt = {m: [{"id": pid, "name": s["player"], "peak": round(s["peak"], 2),
                "window": [round(x, 2) for x in s["window"]]} for pid, s in stars_by[m].items()]
           for m in metrics if m != PRIMARY}

    data = {
        "meta": {
            "sample": is_sample, "source": str(src.relative_to(ROOT)) if src.is_relative_to(ROOT) else str(src), "built": date.today().isoformat(),
            "primaryMetric": PRIMARY, "flagZ": flag_z, "minFlagged": E.MIN_FLAGGED,
            "peakFraction": E.PEAK_FRACTION, "minOverlap": E.MIN_OVERLAP,
            "firstSeason": first, "lastSeason": last, "start": start, "frames": n,
            "coverage": coverage,
            "note": ("SAMPLE DATA: fictional players with simulated numbers. Cities and tournament "
                     "hosts/dates are real.") if is_sample else
                    ("Club goals: league top scorers (worldfootball.net), weighted by team games since "
                     "appearances aren't available. International goals: competitive matches with scorer "
                     "records (martj42/international_results). League scoring rates: engsoccerdata."),
        },
        "hubs": hubs,
        "clubWeights": {k: v.tolist() for k, v in club.items()},
        "hubPlayers": hub_detail,
        "europe": {} if finals is None else {
            str(int(s)): {r.kind: [r.team, r.hub] for r in g.itertuples()}
            for s, g in finals.groupby("season")},
        "tournaments": tours,
        "stars": star_out,
        "altStars": alt,
        "eras": eras_by,
        "eraSeries": {m: [{k: v for k, v in row.items() if k != "players"} for row in series_by[m]]
                      for m in metrics},
        "agreement": E.agreement({m: e for m, e in eras_by.items() if e},
                                 {m: c for m, c in coverage.items() if eras_by[m]}),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_clean(data), separators=(",", ":"), allow_nan=False), encoding="utf-8")
    return data


if __name__ == "__main__":
    args = sys.argv[1:]
    src = Path(args[args.index("--input") + 1]).resolve() if "--input" in args else None
    out = Path(args[args.index("--output") + 1]).resolve() if "--output" in args else OUT
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
    print(f"  -> {out}")
