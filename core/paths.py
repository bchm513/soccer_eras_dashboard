"""Where everything lives. One place, so the scraper, the pipeline and the tests agree.

    data/
      football.db   the project database (every scraped, manual and built table)
      raw/          files the scraper writes (one table each in the database)
      manual/       your own additions and fixes (always win over scraped data)
      cache/        downloaded pages and datasets (safe to delete; refetched when needed)
      sample/       the synthetic dataset used before real data exists
    dashboard/data/eras.json   what the dashboard reads

Functions take the raw folder as their anchor, so a copy of the data folder anywhere
(tests, experiments) keeps its own database and manual files next to it.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
MANUAL = DATA / "manual"
CACHE = DATA / "cache"
SAMPLE = DATA / "sample" / "player_seasons.csv"
DB = DATA / "football.db"
DASHBOARD_DATA = ROOT / "dashboard" / "data" / "eras.json"


def db_file(raw: Path | None = None) -> Path:
    return DB if raw is None else Path(raw).parent / "football.db"


def manual_dir(raw: Path | None = None) -> Path:
    return MANUAL if raw is None else Path(raw).parent / "manual"


def cache_dir(raw: Path | None = None) -> Path:
    return CACHE if raw is None else Path(raw).parent / "cache"
