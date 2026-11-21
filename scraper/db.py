"""The project database: data/football.db (SQLite, one file).

Everything the scraper has collected lives here, so nothing needs re-scraping:

  raw tables     one per CSV in data/raw/ (scorers_wikipedia, scorers_transfermarkt, intl_goals, ...)
  manual tables  one per CSV in data/manual/, named manual_<file> (your own additions and fixes;
                 they always win over scraped data)
  derived        written by `assemble`: player_seasons, players, clubs, moments

`assemble` syncs the database from the CSVs first (only files that changed), so the routine is:
edit a file in data/manual/ -> `python -m scraper.run assemble` -> `python pipeline/build.py`.
Open the file with any SQLite tool (DB Browser for SQLite, Datasette, pandas) to explore it.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "football.db"
MANUAL = ROOT / "data" / "manual"
SKIP_RAW = {"player_seasons", "unresolved_clubs", "club_locations_manual"}   # derived or legacy-manual

MANUAL_TEMPLATES = {
    "scorers_manual.csv": "competition,season,rank,player,team,goals,nationality,note\n",
    "club_locations_manual.csv": "team,city,lat,lon\n",
    "moments_manual.csv": "season,date,title,detail,teams,players,lat,lon,weight\n",
    "impact_manual.csv": "season,metric,value\n",
}


def db_path(raw: Path | None) -> Path:
    """The database sits next to the data folder: data/raw -> data/football.db."""
    return DB_PATH if raw is None else Path(raw).parent / "football.db"


def manual_dir(raw: Path | None) -> Path:
    return MANUAL if raw is None else Path(raw).parent / "manual"


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS _imports (name TEXT PRIMARY KEY, path TEXT, mtime REAL, rows INTEGER)")
    return con


def ensure_manual(manual: Path = MANUAL) -> None:
    manual.mkdir(parents=True, exist_ok=True)
    for name, header in MANUAL_TEMPLATES.items():
        p = manual / name
        if not p.exists():
            p.write_text(header, encoding="utf-8")


def _sources(raw: Path, manual: Path) -> list[tuple[str, Path]]:
    out = [(p.stem, p) for p in sorted(raw.glob("*.csv")) if p.stem not in SKIP_RAW]
    out += [(f"manual_{p.stem}", p) for p in sorted(manual.glob("*.csv"))]
    legacy = raw / "club_locations_manual.csv"          # older location fixes kept in data/raw
    if legacy.exists() and not (manual / "club_locations_manual.csv").stat().st_size > len(MANUAL_TEMPLATES["club_locations_manual.csv"]):
        out.append(("manual_club_locations_manual", legacy))
    return out


def refresh(raw: Path, log=print) -> dict:
    """Import every CSV that is new or changed since the last import. Returns {table: rows}."""
    manual, path = manual_dir(raw), db_path(raw)
    ensure_manual(manual)
    con = connect(path)
    seen = dict(con.execute("SELECT name, mtime FROM _imports").fetchall())
    changed = {}
    for name, p in _sources(raw, manual):
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
        log(f"  database: updated {len(changed)} tables ({', '.join(f'{k} {v}' for k, v in list(changed.items())[:8])}"
            f"{', ...' if len(changed) > 8 else ''})")
    else:
        log("  database: up to date")
    return changed


def tables(path: Path = DB_PATH) -> set:
    if not path.exists():
        return set()
    con = sqlite3.connect(path)
    t = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    return t


def load(name: str, raw: Path | None = None) -> pd.DataFrame | None:
    """A table from the database, else the CSV of the same name in data/raw, else None."""
    path = db_path(raw)
    if name in tables(path):
        con = sqlite3.connect(path)
        df = pd.read_sql(f'SELECT * FROM "{name}"', con)
        con.close()
        return df
    if raw is not None and (raw / f"{name}.csv").exists():
        return pd.read_csv(raw / f"{name}.csv", low_memory=False)
    return None


def write(name: str, df: pd.DataFrame, raw: Path | None = None) -> None:
    con = connect(db_path(raw))
    df.to_sql(name, con, if_exists="replace", index=False)
    con.commit()
    con.close()


def summary(path: Path = DB_PATH, log=print) -> None:
    con = connect(path)
    rows = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != '_imports' ORDER BY name").fetchall()
    log(f"{path} ({path.stat().st_size / 1e6:.1f} MB)")
    for (name,) in rows:
        n = con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        log(f"  {name:36s} {n:>8,} rows")
    con.close()
