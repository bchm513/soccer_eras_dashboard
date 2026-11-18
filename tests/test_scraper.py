"""Run with:  python -m pytest tests   (or: python tests/test_scraper.py)"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.worldfootball import parse_goalgetter, goalgetter_url, _dedupe  # noqa: E402
from scraper.clubs import ClubResolver  # noqa: E402
from scraper import wikipedia as wiki  # noqa: E402

FIX = Path(__file__).parent / "fixtures"


def test_parse_goalgetter():
    rows = parse_goalgetter((FIX / "goalgetter_esp_1955.html").read_text(encoding="utf-8"))
    assert [r["player"] for r in rows] == ["Alfredo Di Stéfano", "Mauro", "Escudero", "Arteche"]
    first = rows[0]
    assert first["player_id"] == "alfredo-di-stefano"
    assert first["team"] == "Real Madrid" and first["team_id"] == "real-madrid"
    assert first["nationality"] == "Argentina"
    assert (first["goals"], first["penalties"]) == (24, 0)
    assert rows[1]["rank"] == 1            # tied rank inherited
    assert rows[3]["player_id"] == "pe41509"  # newer /person/ links
    assert rows[3]["team_id"] == "te123"
    assert (rows[3]["goals"], rows[3]["penalties"]) == (15, 3)


def test_urls_and_dedupe():
    assert goalgetter_url("esp-primera-division", 1955, "split").endswith("/goalgetter/esp-primera-division-1955-1956/")
    assert goalgetter_url("bra-serie-a", 1990, "calendar").endswith("/goalgetter/bra-serie-a-1990/")
    assert _dedupe("Real Madrid Real Madrid") == "Real Madrid"
    assert _dedupe("Atlético Madrid") == "Atlético Madrid"


def test_wiki_seriea_rowspan_ties():
    rows = wiki.parse_scorers((FIX / "wiki_seriea_1960.html").read_text(encoding="utf-8"))
    assert [r["player"] for r in rows] == ["Sergio Brighenti", "Omar Sívori", "Bruno Mora",
                                           "Kurt Hamrin", "Lorenzo Bettini", "Santiago Vernazza"]
    by = {r["player"]: r for r in rows}
    assert by["Omar Sívori"]["player_id"] == "Omar_Sívori"          # wiki title = stable id
    assert by["Omar Sívori"]["nationality"] == "Argentina"           # first flag
    assert by["Kurt Hamrin"]["goals"] == 14 and by["Kurt Hamrin"]["rank"] == 8   # merged cells
    assert by["Lorenzo Bettini"]["goals"] == 14
    assert by["Bruno Mora"]["team"] == "Sampdoria" and "Juventus" in by["Bruno Mora"]["all_teams"]
    assert by["Santiago Vernazza"]["rank"] == 11


def test_wiki_eng_equals_ties():
    rows = wiki.parse_scorers((FIX / "wiki_eng_1975.html").read_text(encoding="utf-8"))
    assert [r["goals"] for r in rows] == [23, 20, 17, 17]
    assert rows[3]["player"] == "John Richards" and rows[3]["rank"] == 4
    assert rows[3]["player_id"] == "John_Richards_(footballer,_born_1950)"
    assert rows[3]["team"] == "Wolverhampton Wanderers"


def test_wiki_titles():
    assert wiki.season_label(1955, "split") == "1955–56"
    assert wiki.season_label(1999, "split") == "1999–2000"
    assert wiki.season_label(1990, "calendar") == "1990"
    assert wiki.page_url("1955–56 La Liga") == "https://en.wikipedia.org/wiki/1955%E2%80%9356_La_Liga" or \
        wiki.page_url("1955–56 La Liga").endswith("1955–56_La_Liga")


def test_club_resolver(tmp_path):
    r = ClubResolver(tmp_path)
    assert r.resolve("Juventus", "ITA")[0] == "Turin"
    assert r.resolve("Sporting Braga", "POR")[0] == "Braga"     # city name beats alias
    assert r.resolve("Hamburger SV", "GER")[0] == "Hamburg"
    assert r.resolve("Nowhere Rovers", "ENG")[3] == "unresolved"
    (tmp_path / "club_locations_manual.csv").write_text("team,city,lat,lon\nNowhere Rovers,Nowhere,50.0,0.0\n")
    assert ClubResolver(tmp_path).resolve("Nowhere Rovers", "ENG")[0] == "Nowhere"


if __name__ == "__main__":
    import tempfile
    test_parse_goalgetter()
    test_urls_and_dedupe()
    test_wiki_seriea_rowspan_ties()
    test_wiki_eng_equals_ties()
    test_wiki_titles()
    with tempfile.TemporaryDirectory() as d:
        test_club_resolver(Path(d))
    print("all scraper tests passed")
