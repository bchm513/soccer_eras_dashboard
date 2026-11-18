"""European Cup / UEFA Champions League: top scorers per season and every final.

    Wikipedia season pages, 1955-56 on: "1959–60 European Cup", "2005–06 UEFA Champions League"
        -> data/raw/scorers_ucl_wikipedia.csv  (same columns as the league scorer files)
    Transfermarkt open data, 2012 on (competition id CL)
        -> data/raw/scorers_ucl_transfermarkt.csv
    "List of European Cup and UEFA Champions League finals"
        -> data/raw/europe_finals.csv: season, winner, winner_country, runner_up, runner_up_country
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from .http import PoliteSession
from . import wikipedia as wiki

UCL = {"code": "UCL", "name": "European Cup / Champions League", "format": "split", "first": 1955,
       "wiki": ["{s} European Cup", "{s} UEFA Champions League"]}
FINALS_PAGE = "List of European Cup and UEFA Champions League finals"

# Country names on the finals page -> codes used by the club resolver's gazetteer
COUNTRY_CODE = {"spain": "ESP", "england": "ENG", "italy": "ITA", "germany": "GER", "west germany": "GER",
                "france": "FRA", "netherlands": "NED", "portugal": "POR", "scotland": "SCO",
                "belgium": "BEL", "romania": "ROU", "yugoslavia": "YUG", "serbia": "YUG", "greece": "GRE",
                "sweden": "SWE", "hungary": "HUN"}


def scrape_scorers(sess: PoliteSession, first: int, last: int, log=print) -> list[dict]:
    return wiki.scrape_league(sess, UCL, first, last, log=log)


def parse_finals(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table"):
        if "wikitable" not in (table.get("class") or []):
            continue
        grid = wiki._grid(table)
        if len(grid) < 2:
            continue
        header = [wiki._text(c).lower().replace("­", "") for c in grid[0]]
        if not ("season" in header and "winners" in header and any(h.startswith("runners") for h in header)):
            continue
        i_s = header.index("season")
        i_w = header.index("winners")
        i_r = next(i for i, h in enumerate(header) if h.startswith("runners"))
        # the country columns sit just outside each club column: Country | Winners ... Runners-up | Country
        i_wc = i_w - 1 if i_w > 0 and header[i_w - 1].startswith("country") else None
        i_rc = i_r + 1 if i_r + 1 < len(header) and header[i_r + 1].startswith("country") else None
        out = []
        for r in grid[1:]:
            if len(r) <= max(i_s, i_w, i_r):
                continue
            m = re.match(r"(\d{4})", wiki._text(r[i_s]))
            if not m:
                continue
            winner, runner = wiki._text(r[i_w]), wiki._text(r[i_r])
            if not winner or winner.lower() in ("winners", "tbd"):
                continue
            out.append({"season": int(m.group(1)), "winner": _strip_marks(winner),
                        "winner_country": wiki._text(r[i_wc]) if i_wc is not None else "",
                        "runner_up": _strip_marks(runner),
                        "runner_up_country": wiki._text(r[i_rc]) if i_rc is not None else ""})
        if out:
            return out
    return []


def _strip_marks(s: str) -> str:
    return re.sub(r"[†*&#^]+|\[.*?\]", "", s).strip()


def build(raw: Path, sess: PoliteSession, first: int, last: int, log=print) -> None:
    # Finals
    html = sess.get(wiki.page_url(FINALS_PAGE))
    finals = pd.DataFrame(parse_finals(html) if html else [])
    if finals.empty:
        log("  finals: table not found")
    else:
        finals = finals[(finals["season"] >= first) & (finals["season"] <= last)]
        finals.to_csv(raw / "europe_finals.csv", index=False)
        log(f"  finals: {len(finals)} seasons ({finals.season.min()}-{finals.season.max()})")
    # Season top scorers (Wikipedia; Transfermarkt covers 2012 on in the transfermarkt step)
    rows = scrape_scorers(sess, max(first, UCL["first"]), last, log=log)
    if rows:
        pd.DataFrame(rows).to_csv(raw / "scorers_ucl_wikipedia.csv", index=False)
        log(f"  -> {raw / 'scorers_ucl_wikipedia.csv'}")
