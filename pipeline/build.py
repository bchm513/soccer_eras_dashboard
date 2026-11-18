"""Run the full pipeline and write dashboard/data/eras.json.

Uses data/raw/player_seasons.csv when it exists; otherwise generates the SAMPLE dataset.
    python pipeline/build.py            # auto
    python pipeline/build.py --sample   # force sample data
"""
from __future__ import annotations

import json
import sys
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


def r2(a):
    return [[int(x), round(float(y), 2)] for x, y in a]


def main(force_sample: bool = False) -> dict:
    is_sample = force_sample or not RAW.exists()
    src = SAMPLE if is_sample else RAW
    if is_sample:
        generate(SAMPLE)
    df = pd.read_csv(src)
    first, last = int(df["season"].min()), int(df["season"].max())

    ps = E.player_season_scores(df)
    stars_by = {m: E.find_stars(ps, m) for m in E.METRICS}
    years = range(first, last + 1)
    coverage = {m: (int(ps.dropna(subset=[m])["season"].min()), last) for m in E.METRICS}
    eras_by, series_by = {}, {}
    for m in E.METRICS:
        lo = coverage[m][0]
        eras_by[m], series_by[m] = E.detect_eras(stars_by[m], range(lo, last + 1))

    # Map timeline: monthly frames from Aug of the first season to Dec of the season after last
    start = f"{first}-08"
    n = H.month_index(start, f"{last + 1}-12") + 1
    stars = stars_by[PRIMARY]
    hubs, star_rows = H.find_hubs(ps, stars, PRIMARY)
    club = H.club_weights(star_rows, hubs, PRIMARY, first, last, start, n)
    tours = H.tournament_weights(TOURNAMENTS, club, start, n)

    # Era -> dominant hub
    for e in eras_by[PRIMARY]:
        sub = star_rows[(star_rows["season"] >= e["start"]) & (star_rows["season"] <= e["end"])]
        if len(sub):
            e["hub"] = sub.assign(w=sub[PRIMARY].clip(lower=0)).groupby("hub")["w"].sum().idxmax()

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
        })

    alt = {m: [{"id": pid, "name": s["player"], "peak": round(s["peak"], 2),
                "window": [round(x, 2) for x in s["window"]]} for pid, s in stars_by[m].items()]
           for m in E.METRICS if m != PRIMARY}

    data = {
        "meta": {
            "sample": is_sample, "source": str(src.relative_to(ROOT)), "built": date.today().isoformat(),
            "primaryMetric": PRIMARY, "flagZ": E.FLAG_Z, "minFlagged": E.MIN_FLAGGED,
            "peakFraction": E.PEAK_FRACTION, "minOverlap": E.MIN_OVERLAP,
            "firstSeason": first, "lastSeason": last, "start": start, "frames": n,
            "coverage": coverage,
            "note": ("SAMPLE DATA: fictional players with simulated numbers. Cities and tournament "
                     "hosts/dates are real.") if is_sample else "",
        },
        "hubs": hubs,
        "clubWeights": {k: v.tolist() for k, v in club.items()},
        "tournaments": tours,
        "stars": star_out,
        "altStars": alt,
        "eras": eras_by,
        "eraSeries": {m: [{k: v for k, v in row.items() if k != "players"} for row in series_by[m]]
                      for m in E.METRICS},
        "agreement": E.agreement(eras_by, coverage),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":"), default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    return data


if __name__ == "__main__":
    d = main(force_sample="--sample" in sys.argv)
    print(f"{'SAMPLE' if d['meta']['sample'] else 'REAL'} data | stars: {len(d['stars'])} | hubs: {len(d['hubs'])} "
          f"| frames: {d['meta']['frames']} | tournaments: {len(d['tournaments'])}")
    for m, es in d["eras"].items():
        print(f"  {m}: " + ", ".join(f"{e['start']}-{e['end']}" for e in es))
    for a in d["agreement"]:
        print(f"  agreement {a['a']} vs {a['b']} ({a['from']}-{a['to']}): {a['jaccard']}")
    print(f"  -> {OUT}")
