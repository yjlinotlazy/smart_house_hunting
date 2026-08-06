from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

SUFFIXES = {
    "STREET": "ST",
    "ST": "ST",
    "ROAD": "RD",
    "RD": "RD",
    "AVENUE": "AVE",
    "AVE": "AVE",
    "LANE": "LN",
    "LN": "LN",
    "DRIVE": "DR",
    "DR": "DR",
    "COURT": "CT",
    "CT": "CT",
    "PLACE": "PL",
    "PL": "PL",
    "BOULEVARD": "BLVD",
    "BLVD": "BLVD",
    "PARKWAY": "PKWY",
    "PKWY": "PKWY",
    "TERRACE": "TER",
    "TER": "TER",
    "CIRCLE": "CIR",
    "CIR": "CIR",
}
DIRECTIONS = {
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
    "NORTHEAST": "NE",
    "NORTHWEST": "NW",
    "SOUTHEAST": "SE",
    "SOUTHWEST": "SW",
}
UNIT_PATTERN = re.compile(r"(?:\s+|,)(?:UNIT|APT|APARTMENT|#)\s*([A-Z0-9-]+)\s*$", re.I)


@dataclass(frozen=True)
class NormalizedAddress:
    street_display: str
    street_key: str
    unit: str | None


def _clean(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(ascii_value.strip().split())


def normalize_municipality(raw: str, configured: list[str]) -> str:
    cleaned = _clean(raw)
    key = cleaned.casefold()
    for prefix in ("city of ", "town of "):
        if key.startswith(prefix):
            key = key[len(prefix) :]
            break
    canonical = {" ".join(value.strip().split()).casefold(): value for value in configured}
    if key not in canonical:
        raise ValueError(f"Municipality is outside the configured search area: {cleaned}")
    return canonical[key]


def normalize_unit(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = _clean(raw).upper()
    value = re.sub(r"^(?:UNIT|APT|APARTMENT|#)\s*", "", value).strip()
    if not value:
        return None
    if value.isdigit():
        return str(int(value))
    return value


def normalize_address(street_address: str, unit_number: str | None = None) -> NormalizedAddress:
    street = _clean(street_address)
    extracted_unit = None
    match = UNIT_PATTERN.search(street)
    if match:
        extracted_unit = match.group(1)
        street = street[: match.start()].strip(" ,")
    unit = normalize_unit(unit_number or extracted_unit)
    tokens = re.findall(r"[A-Z0-9-]+", street.upper())
    normalized_tokens = [DIRECTIONS.get(token, SUFFIXES.get(token, token)) for token in tokens]
    street_key = " ".join(normalized_tokens)
    if not street_key:
        raise ValueError("Street address is empty after normalization")
    street_display = " ".join(word.capitalize() for word in street_key.split())
    return NormalizedAddress(street_display=street_display, street_key=street_key, unit=unit)
