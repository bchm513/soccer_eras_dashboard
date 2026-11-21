"""Small helpers used everywhere: name normalising, seasons, junk-row detection."""
from __future__ import annotations

import re
import unicodedata

import pandas as pd

# Summary rows that scorer tables mix in with players ("Total:", "22 players", "Own goals")
NOT_A_PLAYER = re.compile(r"^\d+\s+players?$|:\s*$|^(?:total|games|average|own goals?|others?)\b", re.I)


def norm(s) -> str:
    """Lower-case ASCII with punctuation removed: 'Atlético Madrid' -> 'atletico madrid'."""
    if not isinstance(s, str):          # blank cells arrive as NaN
        return ""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9' ]+", " ", s).strip()


def is_player(v) -> bool:
    return isinstance(v, str) and v.strip() != "" and not NOT_A_PLAYER.search(v)


def season_of(dates: pd.Series) -> pd.Series:
    """Seasons run August -> July and are labelled by their first year (Mar 1988 -> 1987)."""
    d = pd.to_datetime(dates, errors="coerce")
    return (d.dt.year - (d.dt.month < 8).astype(int)).astype("Int64")


def season_label(s: int) -> str:
    return f"{s}–{(s + 1) % 100:02d}"
