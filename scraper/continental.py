"""Continental club competitions in every confederation: finals and season top scorers.

    UCL  European Cup / UEFA Champions League (UEFA)        1955-
    UEL  UEFA Cup / Europa League (UEFA)                     1971-
    LIB  Copa Libertadores (CONMEBOL)                       1960-
    ACL  Asian Club Championship / AFC Champions League      1985-
    CAF  African Cup of Champions Clubs / CAF Champions League 1964-
    CCL  CONCACAF Champions' Cup / Champions League / Cup    1962-

Sources: each competition's Wikipedia season pages (top scorers) and its list-of-finals page.
Transfermarkt's open data adds complete Champions League scorers from 2012 (transfermarkt step).

    -> data/raw/continental_finals.csv: comp, confed, season, winner, winner_country,
       runner_up, runner_up_country, attendance
    -> data/raw/scorers_continental_wikipedia.csv
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

from .http import FetchFailed, PoliteSession, RobotsDisallowed
from . import wikipedia as wiki

COMPS = [
    {"code": "UCL", "confed": "UEFA", "name": "European Cup / Champions League", "first": 1955, "format": "split",
     "wiki": ["{s} European Cup", "{s} UEFA Champions League"],
     "finals": ["List of European Cup and UEFA Champions League finals"]},
    {"code": "UEL", "confed": "UEFA", "name": "UEFA Cup / Europa League", "first": 1971, "format": "split",
     "wiki": ["{s} UEFA Cup", "{s} UEFA Europa League"],
     "finals": ["List of UEFA Cup and Europa League finals", "List of UEFA Europa League finals"]},
    {"code": "LIB", "confed": "CONMEBOL", "name": "Copa Libertadores", "first": 1960, "format": "calendar",
     "wiki": ["{s} Copa Libertadores"], "finals": ["List of Copa Libertadores finals"]},
    {"code": "ACL", "confed": "AFC", "name": "AFC Champions League", "first": 1985, "format": "split",
     "formats": [[2004, "calendar"], [2023, "split"]],
     "wiki": ["{s} Asian Club Championship", "{s} AFC Champions League", "{s} AFC Champions League Elite"],
     "finals": ["List of AFC Champions League finals", "List of Asian Club Championship and AFC Champions League finals"]},
    {"code": "CAF", "confed": "CAF", "name": "CAF Champions League", "first": 1964, "format": "calendar",
     "formats": [[2019, "split"]],
     "wiki": ["{s} African Cup of Champions Clubs", "{s} CAF Champions League"],
     "finals": ["List of CAF Champions League finals", "List of African Cup of Champions Clubs and CAF Champions League finals"]},
    {"code": "CCL", "confed": "CONCACAF", "name": "CONCACAF Champions Cup", "first": 1962, "format": "calendar",
     "formats": [[2008, "split"], [2018, "calendar"]],
     "wiki": ["{s} CONCACAF Champions' Cup", "{s} CONCACAF Champions League", "{s} CONCACAF Champions Cup"],
     "finals": ["List of CONCACAF Champions Cup finals", "List of CONCACAF Champions' Cup and Champions League finals"]},
]
COMP_BY_CODE = {c["code"]: c for c in COMPS}


def _strip_marks(s: str) -> str:
    return re.sub(r"[†*&#^‡§]+|\[.*?\]|\(.*?\)", "", s).strip()


def parse_finals(html: str, comp: dict | None = None) -> list[dict]:
    """List-of-finals table: Season/Year | Country | Winner(s) | Score | Runner(s)-up | Country | ...

    Countries come from the neighbouring Country column, or from a flag in the club cell.
    Continuation rows of two-legged finals (score/venue only) are skipped."""
    soup = BeautifulSoup(html, "lxml")
    for table in soup.find_all("table"):
        if "wikitable" not in (table.get("class") or []):
            continue
        grid = wiki._grid(table)
        if len(grid) < 2:
            continue
        header = [wiki._text(c).lower().replace("­", "") for c in grid[0]]
        i_s = wiki._header_index(header, "season", "year", "edition")
        i_w = wiki._header_index(header, "winners", "winner", "champions", "champion")
        i_r = next((i for i, h in enumerate(header) if h.startswith(("runners", "runner", "finalist"))), None)
        if None in (i_s, i_w, i_r):
            continue
        i_wc = i_w - 1 if i_w > 0 and header[i_w - 1].startswith(("country", "nation")) else None
        i_rc = i_r + 1 if i_r + 1 < len(header) and header[i_r + 1].startswith(("country", "nation")) else None
        i_att = next((i for i, h in enumerate(header) if h.startswith("attend")), None)
        fmt = (lambda y: wiki.season_format(comp, y)) if comp else (lambda y: "split")
        out = []
        for r in grid[1:]:
            if len(r) <= max(i_s, i_w, i_r):
                continue
            stxt = wiki._text(r[i_s])
            m = re.match(r"\s*(\d{4})", stxt)
            if not m or r[i_s] is r[i_w]:
                continue
            winner, runner = _strip_marks(wiki._text(r[i_w])), _strip_marks(wiki._text(r[i_r]))
            if not winner or winner.lower() in ("winners", "winner", "tbd", "cancelled", "not held"):
                continue

            def country(col, cell):
                if col is not None and col < len(r) and r[col] is not cell:
                    t = wiki._text(r[col])
                    if t:
                        return t
                f = cell.select_one(".flagicon a") if cell is not None else None
                return f.get("title", "") if f is not None else ""
            att = None
            if i_att is not None and i_att < len(r):
                a = re.sub(r"[^\d]", "", wiki._text(r[i_att]).split("(")[0])
                att = int(a) if a else None
            out.append({"season": int(m.group(1)), "winner": winner, "winner_country": country(i_wc, r[i_w]),
                        "runner_up": runner, "runner_up_country": country(i_rc, r[i_r]), "attendance": att})
        if out:
            return out
    return []


def build(raw: Path, sess: PoliteSession, first: int, last: int, comps: list[str] | None = None, log=print) -> None:
    finals_all, scorers_all = [], []
    for comp in COMPS:
        if comps and comp["code"] not in comps:
            continue
        log(f"{comp['name']}:")
        got = []
        for title in comp["finals"]:
            try:
                html = sess.get(wiki.page_url(title))
            except (FetchFailed, RobotsDisallowed) as e:
                log(f"  finals page '{title}': {e}")
                html = None
            got = parse_finals(html, comp) if html else []
            if got:
                break
        got = [dict(g, comp=comp["code"], confed=comp["confed"]) for g in got if first <= g["season"] <= last]
        finals_all += got
        log(f"  finals: {len(got)} seasons" if got else "  finals: list not found (check the page names in continental.py)")
        rows, _ = wiki.scrape_league(sess, {**comp, "leaders": []}, first, last, log=lambda s: None)
        scorers_all += rows
        seasons = sorted({r["season"] for r in rows})
        log(f"  top scorers: {len(seasons)} seasons" + (f" ({seasons[0]}-{seasons[-1]})" if seasons else ""))
    if finals_all:
        pd.DataFrame(finals_all).to_csv(raw / "continental_finals.csv", index=False)
        log(f"  -> {raw / 'continental_finals.csv'}")
    if scorers_all:
        pd.DataFrame(scorers_all).to_csv(raw / "scorers_continental_wikipedia.csv", index=False)
        log(f"  -> {raw / 'scorers_continental_wikipedia.csv'}")
