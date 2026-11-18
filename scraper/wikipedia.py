"""Wikipedia league-season pages: top-scorer tables (CC BY-SA content).

Reads article pages (https://en.wikipedia.org/wiki/<title>), which Wikipedia's robots.txt allows.
Wikimedia asks scripts to send a descriptive User-Agent with contact info, so set
SOCCER_ERAS_CONTACT (an email or a GitHub/project URL) before running.

Table layout across eras: Rank | Player | Club | Goals. Ties are merged (rowspan) rank and goal
cells or "=" ranks; players carry flag icons; a player can list two clubs ("Sampdoria, Juventus").
Older seasons list ~3-10 scorers, modern ones 10-20.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote, unquote

from bs4 import BeautifulSoup, Tag

from .http import Blocked, FetchFailed, PoliteSession, RobotsDisallowed

BASE = "https://en.wikipedia.org/wiki/"
CONFIG = Path(__file__).with_name("leagues.json")
SCORER_HEADING = re.compile(r"scor|capocannoniere|pichichi|torj|goalgetter|golden boot", re.I)
INT_RE = re.compile(r"\d+")


def load_leagues(only=None, include_disabled=False) -> list[dict]:
    leagues = [lg for lg in json.loads(CONFIG.read_text(encoding="utf-8"))["leagues"] if lg.get("wiki")]
    if only:
        wanted = {c.upper() for c in only}
        return [lg for lg in leagues if lg["code"] in wanted]
    return [lg for lg in leagues if lg["enabled"] or include_disabled]


def season_label(season: int, fmt: str) -> str:
    if fmt == "calendar":
        return str(season)
    nxt = season + 1
    return f"{season}–{nxt}" if nxt % 100 == 0 else f"{season}–{nxt % 100:02d}"   # 1999–2000, 1955–56


def page_url(title: str) -> str:
    return BASE + quote(title.replace(" ", "_"), safe="_()–,'")


# ---------- table parsing ----------

def _grid(table: Tag) -> list[list[Tag | None]]:
    """Expand rowspan/colspan so every row has one entry per column (merged cells repeat)."""
    grid, pending = [], {}   # pending[col] = (cell, rows_left)
    for tr in table.find_all("tr"):
        if tr.find_parent("table") is not table:
            continue
        row, col = [], 0
        cells = tr.find_all(["td", "th"], recursive=False)
        it = iter(cells)
        nxt = next(it, None)
        while nxt is not None or col in pending:
            if col in pending:
                cell, left = pending[col]
                row.append(cell)
                if left <= 1:
                    del pending[col]
                else:
                    pending[col] = (cell, left - 1)
                col += 1
                continue
            cell = nxt
            nxt = next(it, None)
            span = int(re.sub(r"\D", "", cell.get("colspan", "1")) or 1)
            rspan = int(re.sub(r"\D", "", cell.get("rowspan", "1")) or 1)
            for _ in range(span):
                row.append(cell)
                if rspan > 1:
                    pending[col] = (cell, rspan - 1)
                col += 1
        grid.append(row)
    return grid


def _text(cell: Tag | None) -> str:
    if cell is None:
        return ""
    c = BeautifulSoup(str(cell), "lxml")
    for s in c.select("sup, .reference, style, .sortkey"):
        s.decompose()
    return c.get_text(" ", strip=True)


def _player(cell: Tag) -> tuple[str, str, str]:
    """(name, wiki_title_id, nationality) from a player cell with flag icons."""
    flags = cell.select(".flagicon")
    nat = ""
    if flags:
        a = flags[0].find("a")
        img = flags[0].find("img")
        nat = (a.get("title") if a else "") or (img.get("alt") if img else "") or ""
    links = [a for a in cell.find_all("a", href=True)
             if a["href"].startswith("/wiki/") and not a.find_parent(class_="flagicon")
             and ":" not in a["href"][6:] and a.get_text(strip=True)]
    if links:
        a = links[-1]
        title = unquote(a["href"][6:].split("#")[0])
        return a.get_text(" ", strip=True), title, nat
    name = _text(cell)
    return name, "", nat


def _header_index(header: list[str], *names: str) -> int | None:
    for i, h in enumerate(header):
        if any(h == n or h.startswith(n) for n in names):
            return i
    return None


def _scorer_tables(soup: BeautifulSoup):
    """Candidate tables, best first: ones under a 'scorers' heading, then any Player/Club/Goals table."""
    out = []
    for t in soup.find_all("table"):
        if "wikitable" not in (t.get("class") or []):
            continue
        heading = t.find_previous(["h2", "h3", "h4"])
        near = bool(heading and SCORER_HEADING.search(heading.get_text(" ", strip=True)))
        out.append((0 if near else 1, t))
    return [t for _, t in sorted(out, key=lambda x: x[0])]


def _parse_tables(soup: BeautifulSoup) -> list[dict]:
    for table in _scorer_tables(soup):
        grid = _grid(table)
        if len(grid) < 2:
            continue
        header = [_text(c).lower() for c in grid[0]]
        ip = _header_index(header, "player", "name", "scorer", "goalscorer")
        ic = _header_index(header, "club", "team")
        ig = _header_index(header, "goals", "gls")
        if ip is None or ig is None or ic is None:
            continue
        if any(h.startswith(("result", "against", "opponent", "date")) for h in header):
            continue   # hat-trick lists and similar
        ir = _header_index(header, "rank", "pos", "#", "no")
        rows, rank = [], None
        for r in grid[1:]:
            if len(r) <= max(ip, ig, ic) or r[ip] is None:
                continue
            if all(c is not None and c.name == "th" for c in r):
                continue   # repeated header rows
            name, pid, nat = _player(r[ip])
            if not name:
                continue
            m = INT_RE.search(_text(r[ig]))
            if not m:
                continue
            goals = int(m.group())
            rk = INT_RE.match(_text(r[ir])) if ir is not None and r[ir] is not None else None
            rank = int(rk.group()) if rk else rank   # "=" / blank / merged -> same rank as above
            club_txt = _text(r[ic])
            clubs = [c.strip() for c in re.split(r",|/|\s→\s|\s->\s", club_txt) if c.strip()]
            rows.append({"rank": rank, "player": name, "player_id": pid or name, "nationality": nat,
                         "team": clubs[0] if clubs else club_txt, "all_teams": "; ".join(clubs),
                         "goals": goals, "penalties": None, "method": "table"})
        if rows:
            return rows
    return []


GOAL_LINE = re.compile(r"^\s*(\d+)\s+goals?\s*:?\s*$", re.I)


def _own_text(el: Tag) -> str:
    """Text of an element, leaving out nested lists."""
    c = BeautifulSoup(str(el), "lxml")
    for s in c.select("ul, ol, dl, sup, .reference"):
        s.decompose()
    return c.get_text(" ", strip=True)


def _player_club(el: Tag) -> dict | None:
    """'[flag] Klaus Fischer (FC Schalke 04)' -> player, id, nationality, club."""
    flags = el.select(".flagicon")
    nat = ""
    if flags:
        a = flags[0].find("a")
        img = flags[0].find("img")
        nat = (a.get("title") if a else "") or (img.get("alt") if img else "") or ""
    links = [a for a in el.find_all("a", href=True)
             if a["href"].startswith("/wiki/") and not a.find_parent(class_="flagicon")
             and ":" not in a["href"][6:] and a.get_text(strip=True)]
    text = _own_text(el)
    if links:
        p = links[0]
        name, pid = p.get_text(" ", strip=True), unquote(p["href"][6:].split("#")[0])
    else:
        name, pid = re.split(r"\s*\(", text)[0].strip(), ""
    if not name or GOAL_LINE.match(name) or re.search(r"\d+\s+goals?", name, re.I):
        return None
    paren = re.search(r"\(([^()]*)\)", text[text.find(name) + len(name):] if name in text else text)
    club = paren.group(1).strip() if paren else (links[1].get_text(" ", strip=True) if len(links) > 1 else "")
    club = re.sub(r"\s*\d+\s+goals?.*$", "", club, flags=re.I)
    clubs = [c.strip() for c in re.split(r",|/|\s→\s|\s->\s|\s&\s", club) if c.strip()]
    return {"player": name, "player_id": pid or name, "nationality": nat,
            "team": clubs[0] if clubs else "", "all_teams": "; ".join(clubs)}


def _parse_goal_groups(soup: BeautifulSoup) -> list[dict]:
    """Older house style: a '29 goals' line, then the players on that many goals as a list."""
    rows, seen = [], set()
    for el in soup.find_all(["dt", "li", "p", "b"]):
        m = GOAL_LINE.match(_own_text(el))
        if not m:
            continue
        goals = int(m.group(1))
        items = []
        nested = el.find(["ul", "ol"]) if el.name == "li" else None
        if nested:
            items = nested.find_all("li", recursive=False)
        else:
            anchor = el.find_parent("dl") if el.name == "dt" else el.find_parent("p") if el.name == "b" else el
            anchor = anchor or el
            nxt = anchor.find_next_sibling()
            if nxt is not None and nxt.name in ("ul", "ol"):
                items = nxt.find_all("li", recursive=False)
            elif nxt is not None and nxt.name == "dl":
                items = nxt.find_all("dd", recursive=False)
        for li in items:
            r = _player_club(li)
            if r and r["player_id"] not in seen:
                seen.add(r["player_id"])
                rows.append({**r, "goals": goals, "penalties": None, "method": "list"})
    rows.sort(key=lambda r: -r["goals"])
    for i, r in enumerate(rows):          # rank = 1 + players with more goals
        r["rank"] = 1 + sum(x["goals"] > r["goals"] for x in rows)
    return rows


def _parse_infobox(soup: BeautifulSoup) -> list[dict]:
    """Last resort: the season summary box's 'Top goalscorer' row (usually just the leader)."""
    box = soup.find("table", class_=re.compile("infobox"))
    if box is None:
        return []
    for tr in box.find_all("tr"):
        th = tr.find("th")
        if not th or not re.search(r"top\s*(goal)?\s*scorer", th.get_text(" ", strip=True), re.I):
            continue
        td = tr.find("td")
        if td is None:
            continue
        gm = re.search(r"(\d+)\s*goals?", td.get_text(" ", strip=True), re.I)
        if not gm:
            continue
        goals = int(gm.group(1))
        parts = re.split(r"<br\s*/?>", td.decode_contents())
        rows = []
        for part in parts:
            r = _player_club(BeautifulSoup(f"<span>{part}</span>", "lxml").span)
            if r:
                rows.append({**r, "goals": goals, "penalties": None, "rank": 1, "method": "infobox"})
        return rows
    return []


def parse_scorers(html: str) -> list[dict]:
    """Best format available on the page: scorer table, then goal-group list, then infobox leader."""
    soup = BeautifulSoup(html, "lxml")
    for parser in (_parse_tables, _parse_goal_groups, _parse_infobox):
        rows = parser(soup)
        if rows:
            return rows
    return []


# ---------- scraping ----------

def scrape_league(sess: PoliteSession, lg: dict, first: int, last: int, log=print) -> list[dict]:
    out, templates = [], list(lg["wiki"])
    for season in range(max(first, lg["first"]), last + 1):
        label = season_label(season, lg["format"])
        rows, url = None, None
        for tpl in templates:
            url = page_url(tpl.format(s=label))
            try:
                html = sess.get(url)
            except (RobotsDisallowed, FetchFailed) as e:
                log(f"  {lg['code']} {season}: {e}")
                html = None
            if html:
                rows = parse_scorers(html)
                if rows:
                    templates.remove(tpl)
                    templates.insert(0, tpl)   # page naming usually persists for years
                    break
        if not rows:
            log(f"  {lg['code']} {season}: no top-scorer table found")
            continue
        for r in rows:
            r.update({"competition": lg["code"], "season": season, "source_url": url})
        out.extend(rows)
        log(f"  {lg['code']} {season}: {len(rows)} scorers (top: {rows[0]['player']} {rows[0]['goals']})")
    return out


def probe(sess: PoliteSession, leagues: list[dict], log=print) -> bool:
    try:
        sess.get(page_url("1955–56 La Liga"))
    except Blocked as e:
        log(f"BLOCKED: {e}\nWikimedia blocks scripts without a descriptive User-Agent. Set SOCCER_ERAS_CONTACT "
            "to an email or a GitHub/project URL and try again.")
        return False
    except FetchFailed as e:
        log(f"CAN'T REACH WIKIPEDIA: {e}\nIf en.wikipedia.org opens in your browser, this network is "
            "interfering with Python's connections (VPN, firewall, antivirus).")
        return False
    for lg in leagues:
        for season in sorted({lg["first"], 1960, 1975, 1990, 2005}):
            if season < lg["first"]:
                continue
            label = season_label(season, lg["format"])
            found = "—"
            for tpl in lg["wiki"]:
                try:
                    html = sess.get(page_url(tpl.format(s=label)))
                except (FetchFailed, RobotsDisallowed):
                    html = None
                if html:
                    rows = parse_scorers(html)
                    n = len(rows)
                    how = rows[0]["method"] if rows else ""
                    found = (f"{n} scorers ({how}) via '{tpl.format(s=label)}'" if n
                             else f"page found, no scorers: '{tpl.format(s=label)}'")
                    if n:
                        break
            log(f"{lg['code']} {season}: {found}")
    return True