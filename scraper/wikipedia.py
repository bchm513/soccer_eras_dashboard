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

import numpy as np
from bs4 import BeautifulSoup, Tag

import pandas as pd

from core.common import NOT_A_PLAYER
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


def season_format(lg: dict, season: int) -> str:
    """A league's season format can change over time: 'formats': [[1946, "calendar"], [2012, "split"]]."""
    fmt = lg.get("format", "split")
    for start, f in lg.get("formats", []):
        if season >= start:
            fmt = f
    return fmt


def season_label(season: int, fmt: str) -> str:
    if fmt == "calendar":
        return str(season)
    nxt = season + 1
    return f"{season}–{nxt}" if nxt % 100 == 0 else f"{season}–{nxt % 100:02d}"   # 1999–2000, 1955–56


def active(lg: dict, season: int) -> bool:
    return lg.get("first", 1946) <= season <= lg.get("last", 9999) and not any(
        a <= season <= b for a, b in lg.get("gaps", []))


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


def _links(cell: Tag | None) -> list[Tag]:
    """Article links in a cell, leaving out flag icons, files and references."""
    if cell is None:
        return []
    return [a for a in cell.find_all("a", href=True)
            if a["href"].startswith("/wiki/") and not a.find_parent(class_="flagicon")
            and ":" not in a["href"][6:] and a.get_text(strip=True) and not a.find_parent("sup")]


def _title(a: Tag | None) -> str:
    return unquote(a["href"][6:].split("#")[0]) if a is not None else ""


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
            if not name or NOT_A_PLAYER.search(name):
                continue
            m = INT_RE.search(_text(r[ig]))
            if not m:
                continue
            goals = int(m.group())
            rk = INT_RE.match(_text(r[ir])) if ir is not None and r[ir] is not None else None
            rank = int(rk.group()) if rk else rank   # "=" / blank / merged -> same rank as above
            club_txt = _text(r[ic])
            clubs = [c.strip() for c in re.split(r",|/|\s→\s|\s->\s", club_txt) if c.strip()]
            club_links = _links(r[ic])
            rows.append({"rank": rank, "player": name, "player_id": pid or name, "nationality": nat,
                         "team": clubs[0] if clubs else club_txt, "all_teams": "; ".join(clubs),
                         "team_title": _title(club_links[0]) if club_links else "",
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
    if not name or GOAL_LINE.match(name) or re.search(r"\d+\s+goals?", name, re.I) or NOT_A_PLAYER.search(name):
        return None
    paren = re.search(r"\(([^()]*)\)", text[text.find(name) + len(name):] if name in text else text)
    club = paren.group(1).strip() if paren else (links[1].get_text(" ", strip=True) if len(links) > 1 else "")
    club = re.sub(r"\s*\d+\s+goals?.*$", "", club, flags=re.I)
    clubs = [c.strip() for c in re.split(r",|/|\s→\s|\s->\s|\s&\s", club) if c.strip()]
    club_link = links[1] if len(links) > 1 else None
    return {"player": name, "player_id": pid or name, "nationality": nat,
            "team": clubs[0] if clubs else "", "all_teams": "; ".join(clubs),
            "team_title": _title(club_link)}


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

# ---------- league tables -> scoring environment ----------

def _num(cell) -> int | None:
    m = re.search(r"-?\d+", _text(cell).replace("−", "-"))
    return int(m.group()) if m else None


def parse_standings(html: str) -> dict | None:
    """Goals per team-match from the season's league table (Pld / GF / GA columns).

    Uses the largest table whose goals for and against balance (a proper league table, not a
    results matrix or a group with outside games). Returns teams, matches, goals, rate, games."""
    soup = BeautifulSoup(html, "lxml") if isinstance(html, str) else html
    best = None
    for table in soup.find_all("table"):
        if "wikitable" not in (table.get("class") or []):
            continue
        grid = _grid(table)
        if len(grid) < 5:
            continue
        header = [_text(c).lower().replace(".", "") for c in grid[0]]
        ip = next((i for i, h in enumerate(header) if h in ("pld", "p", "gp", "mp", "pj", "played", "games")), None)
        igf = next((i for i, h in enumerate(header) if h in ("gf", "f", "goals for", "gs")), None)
        iga = next((i for i, h in enumerate(header) if h in ("ga", "a", "goals against", "gc")), None)
        if None in (ip, igf, iga):
            continue
        pld = gf = ga = n = 0
        games = []
        for r in grid[1:]:
            if len(r) <= max(ip, igf, iga) or r[ip] is r[igf]:
                continue
            p, f, g = _num(r[ip]), _num(r[igf]), _num(r[iga])
            if p is None or f is None or g is None or p <= 0 or p > 80:
                continue
            pld, gf, ga, n = pld + p, gf + f, ga + g, n + 1
            games.append(p)
        if n < 4 or gf == 0 or abs(gf - ga) > 0.1 * gf:
            continue
        if best is None or n > best["teams"]:
            best = {"teams": n, "matches": pld // 2, "goals": gf, "goals_per_team_match": round(gf / pld, 4),
                    "team_games": round(float(np.median(games)), 1)}
    return best


# ---------- "List of ... top scorers" pages (one leader per season) ----------

STAGE_LATE = re.compile(r"\b(cl|clausura|fi|final|tr|transición|2nd|second)\b", re.I)


def leaders_season(text: str, fmt_of_year) -> int | None:
    """'1955–56' -> 1955; '1991 Ap' -> 1991; '1992 Cl' -> 1991 (Clausura closes the season)."""
    m = re.match(r"\s*(\d{4})", text)
    if not m:
        return None
    year = int(m.group(1))
    if re.match(r"\s*\d{4}\s*[–-]\s*\d{2,4}", text):
        return year
    if STAGE_LATE.search(text) and fmt_of_year(year - 1) != "calendar":
        return year - 1
    return year


def parse_leaders(html: str) -> list[dict]:
    """Season | Player | Club | Goals tables; ties listed in one cell are paired up in order."""
    soup = BeautifulSoup(html, "lxml")
    out = []
    for table in soup.find_all("table"):
        if "wikitable" not in (table.get("class") or []):
            continue
        grid = _grid(table)
        if len(grid) < 5:
            continue
        header = [_text(c).lower() for c in grid[0]]
        i_s = _header_index(header, "season", "year", "edition")
        i_p = _header_index(header, "player", "top scorer", "topscorer", "scorer", "name")
        i_c = _header_index(header, "club", "team")
        i_g = _header_index(header, "goals", "gls")
        if None in (i_s, i_p, i_g):
            continue
        for r in grid[1:]:
            if len(r) <= max(i_s, i_p, i_g) or r[i_s] is r[i_p]:
                continue
            season_txt = _text(r[i_s])
            if not re.match(r"\s*\d{4}", season_txt):
                continue
            players = _links(r[i_p])
            clubs = _links(r[i_c]) if i_c is not None and i_c < len(r) else []
            goals = [int(x) for x in re.findall(r"\d+", _text(r[i_g]))]
            if not goals:
                continue
            flags = [f.find("a").get("title") if f.find("a") else "" for f in r[i_p].select(".flagicon")]
            if not players:
                players_txt = [_text(r[i_p])]
                ids = players_txt
            else:
                players_txt = [a.get_text(" ", strip=True) for a in players]
                ids = [_title(a) for a in players]
            for k, (name, pid) in enumerate(zip(players_txt, ids)):
                club = clubs[k] if k < len(clubs) else (clubs[-1] if clubs else None)
                out.append({"season_text": season_txt, "player": name, "player_id": pid or name,
                            "nationality": flags[k] if k < len(flags) else "",
                            "team": club.get_text(" ", strip=True) if club is not None else
                            (_text(r[i_c]) if i_c is not None and i_c < len(r) else ""),
                            "team_title": _title(club), "goals": goals[k] if k < len(goals) else goals[0],
                            "penalties": None, "rank": 1, "method": "leaders"})
        if out:
            return out
    return out


# ---------- scraping ----------

def scrape_league(sess: PoliteSession, lg: dict, first: int, last: int, log=print,
                  skip: set | None = None) -> tuple[list[dict], list[dict]]:
    """Season pages for top scorers and the league table; leader-list page fills empty seasons.
    Seasons in `skip` (already collected) aren't fetched again."""
    out, env, templates = [], [], list(lg["wiki"])
    covered = set(skip or ())
    for season in range(max(first, lg.get("first", first)), min(last, lg.get("last", last)) + 1):
        if not active(lg, season) or season in covered:
            continue
        label = season_label(season, season_format(lg, season))
        rows, url, html_ok = None, None, None
        for tpl in templates:
            url = page_url(tpl.format(s=label))
            try:
                html = sess.get(url)
            except (RobotsDisallowed, FetchFailed) as e:
                log(f"  {lg['code']} {season}: {e}")
                html = None
            if html:
                html_ok = html
                rows = parse_scorers(html)
                if rows:
                    templates.remove(tpl)
                    templates.insert(0, tpl)   # page naming usually persists for years
                    break
        if html_ok:
            st = parse_standings(html_ok)
            if st:
                env.append({"competition": lg["code"], "season": season, **st, "source": "wikipedia"})
        if not rows:
            log(f"  {lg['code']} {season}: no top-scorer table on the season page")
            continue
        covered.add(season)
        for r in rows:
            r.update({"competition": lg["code"], "season": season, "source_url": url})
        out.extend(rows)
        log(f"  {lg['code']} {season}: {len(rows)} scorers (top: {rows[0]['player']} {rows[0]['goals']})")

    # Leader lists fill seasons the season pages couldn't (e.g. England before 1960)
    for title in lg.get("leaders", []):
        url = page_url(title)
        try:
            html = sess.get(url)
        except (RobotsDisallowed, FetchFailed):
            html = None
        if not html:
            continue
        added = 0
        for r in parse_leaders(html):
            s = leaders_season(r.pop("season_text"), lambda y: season_format(lg, y))
            if s is None or s in covered or not (first <= s <= last) or not active(lg, s):
                continue
            out.append({**r, "competition": lg["code"], "season": s, "source_url": url})
            added += 1
        if added:
            log(f"  {lg['code']}: {added} leader rows from '{title}' for seasons without a scorer table")
            break
    return out, env


def _merge(old: pd.DataFrame, new_rows: list[dict], code: str) -> pd.DataFrame:
    """Replace one league's rows for the seasons just scraped; keep everything else."""
    new = pd.DataFrame(new_rows)
    if len(old):
        old = old[~((old["competition"] == code) & old["season"].isin(new["season"]))]
    return pd.concat([old, new], ignore_index=True)


def collect(raw: Path, sess: PoliteSession, leagues: list[dict], first: int, last: int,
            refresh: bool = False, log=print) -> None:
    """The `scorers` step: every league's season pages -> scorers_wikipedia.csv (top scorers) and
    league_environment_wiki.csv (league tables). Saved after each league, so it can be stopped
    and restarted; seasons already collected are skipped unless refresh=True."""
    out_path, env_path = raw / "scorers_wikipedia.csv", raw / "league_environment_wiki.csv"
    df = pd.read_csv(out_path) if out_path.exists() else pd.DataFrame()
    envdf = pd.read_csv(env_path) if env_path.exists() else pd.DataFrame()
    for lg in leagues:
        log(f"Wikipedia: {lg['name']} {max(first, lg.get('first', first))}-{min(last, lg.get('last', last))}...")
        have = set() if refresh or not len(df) else set(df.loc[df["competition"] == lg["code"], "season"].astype(int))
        if have:
            log(f"  {len(have)} seasons already collected; skipping them (add --refresh to re-fetch)")
        rows, env = scrape_league(sess, lg, first, last, log=log, skip=have)
        if rows:
            df = _merge(df, rows, lg["code"])
            df.to_csv(out_path, index=False)
        if env:
            envdf = _merge(envdf, env, lg["code"])
            envdf.to_csv(env_path, index=False)
        log(f"  {lg['code']}: {len(rows)} scorer rows, {len(env)} league tables")
    log(f"  -> {out_path}\n  -> {env_path}")


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
        for season in sorted({lg.get("first", 1946), 1960, 1975, 1990, 2005, 2020}):
            if not active(lg, season):
                continue
            label = season_label(season, season_format(lg, season))
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
                    st = parse_standings(html)
                    tab = f" | league table: {st['teams']} teams" if st else " | no league table"
                    found = (f"{n} scorers ({how}) via '{tpl.format(s=label)}'{tab}" if n
                             else f"page found, no scorers: '{tpl.format(s=label)}'{tab}")
                    if n:
                        break
            log(f"{lg['code']} {season}: {found}")
        for title in lg.get("leaders", []):
            try:
                html = sess.get(page_url(title))
            except (FetchFailed, RobotsDisallowed):
                html = None
            n = len(parse_leaders(html)) if html else 0
            log(f"{lg['code']} leader list '{title}': " + (f"{n} rows" if n else "not found / no table"))
            if n:
                break
    return True
