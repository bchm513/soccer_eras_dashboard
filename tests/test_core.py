"""The shared core: competitions registry, database, moments, era weights.
Run with:  python -m pytest tests   (or: python tests/test_core.py)"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "pipeline")]

import pandas as pd  # noqa: E402

from core import competitions as C, db  # noqa: E402


def test_weights_match_the_brief():
    # World Cup x4, continental championships x3, Champions League / Europa League x2, all others x1
    assert C.TIERS["world_cup"]["weight"] == 4
    assert C.TIERS["continental"]["weight"] == 3
    assert C.TIERS["other"]["weight"] == 1
    assert C.CLUB_CUPS["UCL"].weight == C.CLUB_CUPS["UEL"].weight == 2
    assert all(C.CLUB_CUPS[c].weight == 1 for c in ("LIB", "ACL", "CAF", "CCL"))
    assert C.tier_of("UEFA Euro") == "continental" and C.tier_of("Friendly") == "none"
    assert C.CLUB_CUPS["UCL"].name_in(1985) == "European Cup"


def test_bonus_goals_in_era_scores():
    import eras as E
    base = {"player_id": "a", "player": "A", "season": 2000, "competition": "ESP", "comp_type": "club",
            "apps": None, "team_games": 38, "env_gpm": 1.3, "intl_env_gpm": 1.3, "goals": 20, "assists": None,
            "comp_rank": 1, "club_city": "Madrid", "lat": 40.4, "lon": -3.7}
    rows = [dict(base), dict(base, player_id="b", player="B", world_cup_goals=5),
            dict(base, player_id="c", player="C", cup_goals_UCL=5), dict(base, player_id="d", player="D", cup_goals_LIB=5)]
    df = pd.DataFrame(rows)
    for c in C.TIER_COLUMNS + C.CUP_COLUMNS:
        df[c] = df.get(c, 0)
    df = df.fillna({c: 0 for c in C.TIER_COLUMNS + C.CUP_COLUMNS})
    ps = E.player_season_scores(df).set_index("player_id")["goals_adj"]
    assert ps["b"] > ps["c"] > ps["d"] > ps["a"]      # WC 5x4 > UCL 5x2 > LIB 5x1 > nothing


def test_peak_window_stays_inside_career():
    import numpy as np
    import eras as E
    years = np.arange(2015, 2026)
    z = np.linspace(0.5, 3.0, len(years))                   # still rising: the fit wants a huge window
    ps = pd.DataFrame({"player_id": "x", "player": "X", "season": years, "goals_adj": z, "league": "GER"})
    s = E.find_stars(ps, "goals_adj", require_club=True, flag_z=0.75)["x"]
    assert s["window"][1] <= 2025.5 and s["window"][1] - s["window"][0] <= 2 * E.MAX_PEAK_HALF


def test_database_refresh_and_manual_migration(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    pd.DataFrame({"a": [1, 2]}).to_csv(raw / "thing.csv", index=False)
    (raw / "club_locations_manual.csv").write_text("team,city,lat,lon\nX,Y,1,2\n")    # older location
    assert db.refresh(raw, log=lambda s: None) == {"thing": 2, "manual_club_locations_manual": 1,
                                                   "manual_impact_manual": 0, "manual_moments_manual": 0,
                                                   "manual_reference_goals": 0, "manual_scorers_manual": 0}
    assert not (raw / "club_locations_manual.csv").exists()                      # moved to data/manual
    assert db.refresh(raw, log=lambda s: None) == {}                            # nothing changed
    assert db.load("thing", raw)["a"].tolist() == [1, 2]


def test_club_final_moments():
    from scraper import moments
    f = pd.DataFrame([
        {"comp": "UCL", "season": 1985, "side": "winner", "team": "Steaua", "lat": 44.4, "lon": 26.1, "attendance": 70000},
        {"comp": "UCL", "season": 1985, "side": "runner_up", "team": "Barcelona", "lat": 41.4, "lon": 2.2, "attendance": 70000}])
    m = moments.club_finals(f).iloc[0]
    assert m["title"] == "Steaua win the European Cup 1985"
    assert m["detail"] == "Beat Barcelona in the final. Crowd: 70,000."


if __name__ == "__main__":
    import tempfile
    test_weights_match_the_brief()
    test_bonus_goals_in_era_scores()
    test_peak_window_stays_inside_career()
    with tempfile.TemporaryDirectory() as d:
        test_database_refresh_and_manual_migration(Path(d))
    test_club_final_moments()
    print("all core tests passed")
