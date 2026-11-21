"""Every competition the project knows about, in one place: names, tiers, weights, map size.

Change a weight here and the whole project follows (era scores, the map, moments, the dashboard).

Weights are "league goals per goal": a World Cup goal counts as 4 league goals, added on top
of the player's league goals that season. Tournament goals are judged against the international
scoring rate, club cup goals against the player's league.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ClubCup:
    code: str
    name: str            # shown in the dashboard and in moments
    confed: str
    weight: float        # league goals per goal
    moment_weight: int   # ordering of moments within a season (higher first)
    title_weight: float  # map: winning the final adds this x the season's biggest hub (runner-up 40%)
    history: tuple = ()  # ((first season, name), ...) for moments: "European Cup 1985", "Champions League 2016"

    def name_in(self, season: int) -> str:
        out = self.name
        for start, n in self.history:
            if season >= start:
                out = n
        return out


@dataclass(frozen=True)
class Tournament:
    key: str             # name in the international results data (martj42)
    short: str           # shown on the map and in moments
    tier: str            # world_cup | continental | other (see TIERS)
    map_cap: float       # map circle: x the largest club hub that month (0 = not drawn)
    moment_weight: int
    full_name: str = ""  # used in moments when it differs from short ("CONCACAF Championship")

    @property
    def name(self) -> str:
        return self.full_name or self.short


CLUB_CUPS = {c.code: c for c in [
    #       code   name                               confed      weight moment title
    ClubCup("UCL", "Champions League",       "UEFA",     2.0,   2,     1.0,
            ((1955, "European Cup"), (1992, "Champions League"))),
    ClubCup("UEL", "Europa League",          "UEFA",     2.0,   1,     0.5,
            ((1971, "UEFA Cup"), (2009, "Europa League"))),
    ClubCup("LIB", "Copa Libertadores",      "CONMEBOL", 1.0,   2,     1.0),
    ClubCup("ACL", "AFC Champions League",   "AFC",      1.0,   1,     1.0,
            ((1985, "Asian Club Championship"), (2002, "AFC Champions League"))),
    ClubCup("CAF", "CAF Champions League",   "CAF",      1.0,   1,     1.0,
            ((1964, "African Cup of Champions Clubs"), (1996, "CAF Champions League"))),
    ClubCup("CCL", "CONCACAF Champions Cup", "CONCACAF", 1.0,   1,     1.0,
            ((1962, "CONCACAF Champions' Cup"), (2008, "CONCACAF Champions League"), (2024, "CONCACAF Champions Cup"))),
]}
CUP_CODES = list(CLUB_CUPS)

# Goal tiers for national-team tournaments: weight and the player_seasons column that holds them
TIERS = {
    "world_cup":   {"weight": 4.0, "column": "world_cup_goals"},
    "continental": {"weight": 3.0, "column": "continental_goals"},
    "other":       {"weight": 1.0, "column": "other_tournament_goals"},
}
TIER_COLUMNS = [t["column"] for t in TIERS.values()]

TOURNAMENTS = {t.key: t for t in [
    Tournament("FIFA World Cup", "World Cup", "world_cup", 1.5, 3),
    Tournament("UEFA Euro", "Euro", "continental", 1.1, 2),
    Tournament("Copa América", "Copa América", "continental", 1.0, 2),
    Tournament("African Cup of Nations", "AFCON", "continental", 0.7, 2),
    Tournament("AFC Asian Cup", "Asian Cup", "continental", 0.7, 2),
    Tournament("Gold Cup", "Gold Cup", "continental", 0.6, 2),
    Tournament("CONCACAF Championship", "Gold Cup", "continental", 0.6, 2, "CONCACAF Championship"),
    Tournament("Confederations Cup", "Confederations Cup", "other", 0.5, 1),
    Tournament("Oceania Nations Cup", "Oceania Nations Cup", "other", 0.0, 1),
]}
# World Cup and Euro hosts come from pipeline/tournaments.py (exact final venues); the rest from the results data
MAPPED_FROM_RESULTS = {k: t.short for k, t in TOURNAMENTS.items()
                       if t.map_cap > 0 and t.short not in ("World Cup", "Euro")}
MAP_CAP = {t.short: t.map_cap for t in TOURNAMENTS.values()}


def tier_of(tournament: str) -> str:
    t = TOURNAMENTS.get(tournament)
    return t.tier if t else "none"


def cup_column(code: str) -> str:
    return f"cup_goals_{code}"


CUP_COLUMNS = [cup_column(c) for c in CUP_CODES]


def for_dashboard() -> dict:
    """The names and weights the dashboard shows (so it never hard-codes them)."""
    return {"cups": {c.code: c.name for c in CLUB_CUPS.values()},
            "weights": {**{c.name: c.weight for c in CLUB_CUPS.values()},
                        **{"World Cup": TIERS["world_cup"]["weight"],
                           "Continental championships": TIERS["continental"]["weight"],
                           "Other tournaments": TIERS["other"]["weight"]}}}
