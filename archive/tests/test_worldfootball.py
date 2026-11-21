"""Tests for the retired worldfootball.net scraper (archive/scraper/worldfootball.py).
Not run by default. To run: copy worldfootball.py back into scraper/ and this file into tests/."""
from pathlib import Path

from scraper.worldfootball import parse_goalgetter, goalgetter_url, _dedupe

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
