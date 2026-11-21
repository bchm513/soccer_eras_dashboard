"""The project database: data/football.db (SQLite, one file).

  raw tables     one per CSV in data/raw/ (scorers_wikipedia, scorers_transfermarkt, intl_goals, ...)
  manual tables  one per CSV in data/manual/, named manual_<file> (your additions; they always win)
  built tables   written by `assemble`: player_seasons, players, clubs, finals, moments

`refresh` imports only files that changed since the last import, so the routine is:
edit a file in data/manual/ -> `python -m scraper.run assemble` -> `python pipeline/build.py`.
Open the file with any SQLite tool (DB Browser for SQLite, Datasette, pandas) to explore it.
"""
from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pandas as pd

from .paths import db_file, manual_dir

BUILT = {"player_seasons", "players", "clubs", "finals", "moments", "league_strength_world"}   # written by assemble
SKIP_RAW = BUILT | {"unresolved_clubs"}

# Every table, and the scraper step that makes it (so anyone can see what's missing and how to get it)
MADE_BY = {
    "league_environment": "env", "intl_environment": "env", "intl_team_games": "env", "intl_goals": "env",
    "tournament_editions": "env", "growth": "env", "country_first": "env", "national_elo": "env",
    "moments_tournaments": "env",
    "scorers_wikipedia": "scorers", "league_environment_wiki": "scorers",
    "scorers_transfermarkt": "transfermarkt", "scorers_cups_transfermarkt": "transfermarkt",
    "league_strength": "elo",
    "continental_finals": "continental", "scorers_continental_wikipedia": "continental",
    "club_locations_auto": "locate",
    "player_seasons": "assemble", "players": "assemble", "clubs": "assemble", "finals": "assemble",
    "moments": "assemble", "league_strength_world": "assemble",
}
OPTIONAL = {"league_strength", "club_locations_auto"}      # the project runs without these

MANUAL_TEMPLATES = {
    "scorers_manual.csv": "competition,season,rank,player,team,goals,nationality,note\n",
    "club_locations_manual.csv": "team,city,lat,lon\n",
    "moments_manual.csv": "season,date,title,detail,teams,players,lat,lon,weight\n",
    "impact_manual.csv": "season,metric,value\n",
    "reference_goals.csv": "player,competition,season,goals,source\n",
}


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS _imports (name TEXT PRIMARY KEY, path TEXT, mtime REAL, rows INTEGER)")
    return con


def ensure_manual(raw: Path | None = None) -> Path:
    """Create data/manual/ with empty templates; move files older versions kept in data/raw/."""
    manual = manual_dir(raw)
    manual.mkdir(parents=True, exist_ok=True)
    for name, header in MANUAL_TEMPLATES.items():
        p, legacy = manual / name, (Path(raw) / name if raw is not None else None)
        empty = not p.exists() or p.stat().st_size <= len(header.encode())
        if legacy is not None and legacy.exists() and empty:
            shutil.move(str(legacy), p)
            print(f"  moved data/raw/{name} -> data/manual/{name}")
        elif not p.exists():
            p.write_text(header, encoding="utf-8")
    return manual


def refresh(raw: Path, log=print) -> dict:
    """Import every CSV that is new or changed since the last import. Returns {table: rows}."""
    manual = ensure_manual(raw)
    con = connect(db_file(raw))
    seen = dict(con.execute("SELECT name, mtime FROM _imports").fetchall())
    sources = [(p.stem, p) for p in sorted(Path(raw).glob("*.csv")) if p.stem not in SKIP_RAW]
    sources += [(f"manual_{p.stem}", p) for p in sorted(manual.glob("*.csv"))]
    changed = {}
    for name, p in sources:
        mtime = p.stat().st_mtime
        if seen.get(name) == mtime:
            continue
        try:
            df = pd.read_csv(p, low_memory=False)
        except pd.errors.EmptyDataError:
            df = pd.DataFrame()
        df.to_sql(name, con, if_exists="replace", index=False)
        con.execute("INSERT OR REPLACE INTO _imports VALUES (?, ?, ?, ?)", (name, str(p), mtime, len(df)))
        changed[name] = len(df)
    con.commit()
    con.close()
    if changed:
        names = ", ".join(f"{k} {v}" for k, v in list(changed.items())[:8])
        log(f"  database: updated {len(changed)} tables ({names}{', ...' if len(changed) > 8 else ''})")
    else:
        log("  database: up to date")
    return changed


def tables(raw: Path | None = None) -> set:
    path = db_file(raw)
    if not path.exists():
        return set()
    con = sqlite3.connect(path)
    t = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    return t


def load(name: str, raw: Path | None = None) -> pd.DataFrame | None:
    """A table from the database, or None if no scraper step has made it yet.
    The database is the only source: scraper steps write their files and import them at once."""
    if name not in tables(raw):
        return None
    con = sqlite3.connect(db_file(raw))
    df = pd.read_sql(f'SELECT * FROM "{name}"', con)
    con.close()
    return df


def write(name: str, df: pd.DataFrame, raw: Path | None = None) -> None:
    con = connect(db_file(raw))
    df.to_sql(name, con, if_exists="replace", index=False)
    con.commit()
    con.close()


def summary(raw: Path | None = None, log=print) -> list[str]:
    """Every table with its row count and the step that made it; then what's still missing.
    Returns the steps still to run."""
    path = db_file(raw)
    con = connect(path)
    have = {r[0]: con.execute(f'SELECT COUNT(*) FROM "{r[0]}"').fetchone()[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != '_imports' ORDER BY name")}
    con.close()
    log(f"{path} ({path.stat().st_size / 1e6:.1f} MB)")
    for name, n in have.items():
        made = "manual file" if name.startswith("manual_") else f"step: {MADE_BY.get(name, '?')}"
        log(f"  {name:32s} {n:>9,} rows   {made}")
    missing = [t for t in MADE_BY if t not in have and t not in OPTIONAL]
    steps = list(dict.fromkeys(MADE_BY[t] for t in missing))
    if missing:
        log(f"  missing: {', '.join(missing)}")
        log("  run: " + "  ->  ".join(f"python -m scraper.run {s}" for s in steps))
    else:
        log("  every required table is present")
    return steps
