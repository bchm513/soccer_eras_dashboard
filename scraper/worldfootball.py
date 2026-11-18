"""worldfootball.net top-scorer ("goalgetter") pages: one page per league-season.

URL: https://www.worldfootball.net/goalgetter/<slug>-<season>/
     season is "1955-1956" for split seasons, "1990" for calendar-year leagues.
Table columns: #, Player, Country, Team, Goals (Penalty)

Only these pages are used. The site's detailed player pages are disallowed by its robots.txt,
and its player summaries only carry career totals, so they are not scraped.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

from .http import Blocked, FetchFailed, PoliteSession, RobotsDisallowed

BASE = "https://www.worldfootball.net"
GOALS_RE = re.compile(r"(\d+)\s*\((\d+)\)")
CONFIG = Path(__file__).with_name("leagues.json")


def load_leagues(only: list[str] | None = None, include_disabled: bool = False) -> list[dict]:
    leagues = json.loads(CONFIG.read_text(encoding="utf-8"))["leagues"]
    if only:
        wanted = {c.upper() for c in only}
        return [lg for lg in leagues if lg["code"] in wanted]
    return [lg for lg in leagues if lg["enabled"] or include_disabled]


def season_label(season: int, fmt: str) -> str:
    return f"{season}-{season + 1}" if fmt == "split" else str(season)


def goalgetter_url(slug: str, season: int, fmt: str) -> str:
    return f"{BASE}/goalgetter/{slug}-{season_label(season, fmt)}/"


def _slug_from_href(href: str) -> str:
    """'/player_summary/alfredo-di-stefano/' -> 'alfredo-di-stefano'; '/person/pe123/x/' -> 'pe123'."""
    parts = [p for p in href.split("?")[0].split("/") if p]
    if "person" in parts and len(parts) > parts.index("person") + 1:
        return parts[parts.index("person") + 1]
    for key in ("player_summary", "teams"):
        if key in parts and len(parts) > parts.index(key) + 1:
            nxt = parts[parts.index(key) + 1]
            # newer team URLs look like /teams/te123/real-madrid/
            return nxt
    return parts[-1] if parts else href


def _cell_text(td) -> str:
    t = td.get_text(" ", strip=True)
    if t:
        return t
    img = td.find("img")
    return (img.get("title") or img.get("alt") or "").strip() if img else ""


def parse_goalgetter(html: str) -> list[dict]:
    """Parse the scorer table. Tolerant of layout changes: finds the table by its header text,
    and the player / team cells by their link targets rather than fixed positions."""
    soup = BeautifulSoup(html, "lxml")
    table = None
    for t in soup.find_all("table"):
        head = t.get_text(" ", strip=True)[:300].lower()
        if "player" in head and "goals" in head:
            table = t
            break
    if table is None:
        return []

    # Expand colspans so header positions line up with cell positions
    header = []
    for c in table.find("tr").find_all(["th", "td"]):
        header += [c.get_text(" ", strip=True).lower()] * int(c.get("colspan", 1) or 1)
    col = {name: next((i for i, h in enumerate(header) if name in h), None)
           for name in ("player", "country", "team", "goals")}
    # With a colspan, the name is usually in the last cell of the span (the first holds a flag/logo)
    for name in ("country", "team"):
        i = col[name]
        while i is not None and i + 1 < len(header) and header[i + 1] == header[i]:
            i += 1
        col[name] = i

    rows, last_rank = [], None
    for tr in table.find_all("tr")[1:]:
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        links = tr.find_all("a", href=True)
        p_link = next((a for a in links if "/player_summary/" in a["href"] or "/person/" in a["href"]), None)
        t_links = [a for a in links if "/teams/" in a["href"] and a.get_text(strip=True)]
        if p_link is None:
            continue
        m = None
        if col["goals"] is not None and col["goals"] < len(tds):
            m = GOALS_RE.search(tds[col["goals"]].get_text(" ", strip=True))
        m = m or GOALS_RE.search(tds[-1].get_text(" ", strip=True))
        if not m:
            continue
        rank_txt = tds[0].get_text(strip=True).rstrip(".")
        rank = int(rank_txt) if rank_txt.isdigit() else last_rank   # ties leave the rank blank
        last_rank = rank
        country = _cell_text(tds[col["country"]]) if col["country"] is not None and col["country"] < len(tds) else ""
        # Country/team names can be printed twice (flag/logo text + name)
        country = _dedupe(country)
        team_a = t_links[-1] if t_links else None
        rows.append({
            "rank": rank,
            "player": p_link.get_text(" ", strip=True),
            "player_id": _slug_from_href(p_link["href"]),
            "nationality": country,
            "team": _dedupe(team_a.get_text(" ", strip=True)) if team_a else _dedupe(_cell_text(tds[col["team"]])) if col["team"] is not None else "",
            "team_id": _slug_from_href(team_a["href"]) if team_a else "",
            "goals": int(m.group(1)),
            "penalties": int(m.group(2)),
        })
    return rows


def _dedupe(s: str) -> str:
    """'Real Madrid Real Madrid' -> 'Real Madrid'."""
    w = s.split()
    n = len(w)
    if n % 2 == 0 and w[: n // 2] == w[n // 2:]:
        return " ".join(w[: n // 2])
    return s


def scrape_league(sess: PoliteSession, lg: dict, first: int, last: int, top: int, log=print) -> list[dict]:
    out, slugs = [], list(lg["slugs"])
    start = max(first, lg["first"])
    for season in range(start, last + 1):
        rows = None
        for slug in slugs:
            url = goalgetter_url(slug, season, lg["format"])
            try:
                html = sess.get(url)
            except RobotsDisallowed:
                log(f"  robots.txt disallows {url}; skipping")
                html = None
            except FetchFailed as e:
                log(f"  {lg['code']} {season}: {e}; skipping (re-run later to retry)")
                html = None
            if html:
                rows = parse_goalgetter(html)
                if rows:
                    slugs.remove(slug)
                    slugs.insert(0, slug)   # slugs tend to persist across seasons
                    break
        if not rows:
            log(f"  {lg['code']} {season}: no scorer table found")
            continue
        for r in rows[:top]:
            r.update({"competition": lg["code"], "season": season, "source_url": url})
        out.extend(rows[:top])
        log(f"  {lg['code']} {season}: {min(len(rows), top)} scorers (top: {rows[0]['player']} {rows[0]['goals']})")
    return out


def probe(sess: PoliteSession, leagues: list[dict], log=print) -> None:
    """Check each league's slugs at a few seasons and report which URLs return a scorer table."""
    # One quick request first, so a blocked or unreachable site is reported once, plainly
    test = goalgetter_url(leagues[0]["slugs"][0], 2015, leagues[0]["format"]) if leagues else None
    if test:
        try:
            sess.get(test)
        except Blocked as e:
            log(f"BLOCKED: {e}\nworldfootball.net isn't accepting requests from this script, so the scrape "
                "can't run as is. See the README for alternatives.")
            return
        except FetchFailed as e:
            log(f"CAN'T REACH THE SITE: {e}\nCheck that {BASE} opens in your browser; if it does, "
                "the problem is this network blocking or dropping Python's connections (VPN, firewall, antivirus).")
            return
    for lg in leagues:
        for season in sorted({lg["first"], 1975, 1995, 2015}):
            if season < lg["first"]:
                continue
            hits = []
            for slug in lg["slugs"]:
                url = goalgetter_url(slug, season, lg["format"])
                try:
                    html = sess.get(url)
                    ok = bool(html and parse_goalgetter(html))
                except RobotsDisallowed:
                    ok = "robots"
                except FetchFailed:
                    ok = "network error"
                except Blocked:
                    ok = "blocked"
                hits.append(f"{slug}: {'ok' if ok is True else ok or 'missing'}")
            log(f"{lg['code']} {season}  " + " | ".join(hits))