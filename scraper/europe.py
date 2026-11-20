"""Kept for older commands: the European Cup is now one of the competitions in continental.py."""
from .continental import COMPS, parse_finals  # noqa: F401
from .geo import COUNTRY as _COUNTRY

COUNTRY_CODE = {name: codes[0] for name, codes in _COUNTRY.items()}
