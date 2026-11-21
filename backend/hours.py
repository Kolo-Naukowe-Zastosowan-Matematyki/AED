"""Uproszczony parser formatu opening_hours (OSM), wystarczający dla danych o AED.

Obsługiwane: "24/7", reguły rozdzielone ";", dni (Mo-Fr, Sa,Su, Mo-We,Fr),
zakresy godzin (08:00-16:00, kilka po przecinku), "off"/"closed", reguła "PH off"
(pomijana, bo nie znamy kalendarza świąt). Wszystko inne -> None (nieznane).
"""
from __future__ import annotations

import re
from datetime import datetime

DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
_TIME = re.compile(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$")


def _parse_days(token: str) -> set[int] | None:
    result: set[int] = set()
    for part in token.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            if a not in DAYS or b not in DAYS:
                return None
            i, j = DAYS.index(a), DAYS.index(b)
            rng = range(i, j + 1) if i <= j else list(range(i, 7)) + list(range(0, j + 1))
            result.update(rng)
        elif part in DAYS:
            result.add(DAYS.index(part))
        else:
            return None
    return result


def _parse_times(token: str) -> list[tuple[int, int]] | None:
    spans = []
    for part in token.split(","):
        m = _TIME.match(part.strip())
        if not m:
            return None
        h1, m1, h2, m2 = map(int, m.groups())
        start, end = h1 * 60 + m1, h2 * 60 + m2
        if end == 0:
            end = 24 * 60
        spans.append((start, end))
    return spans


def is_open(spec: str | None, now: datetime | None = None) -> bool | None:
    """True/False gdy da się ustalić, None gdy brak danych lub format nieobsługiwany."""
    if not spec:
        return None
    spec = spec.strip()
    if spec == "24/7":
        return True
    now = now or datetime.now()
    weekday, minute = now.weekday(), now.hour * 60 + now.minute
    state: bool | None = None
    matched_any = False
    for rule in spec.split(";"):
        rule = rule.strip()
        if not rule:
            continue
        if rule.startswith("PH"):
            continue  # święta: brak kalendarza, pomijamy
        tokens = rule.split()
        days: set[int] | None = set(range(7))
        rest = tokens
        if tokens and re.match(r"^(Mo|Tu|We|Th|Fr|Sa|Su)", tokens[0]):
            parts = tokens[0].split(",")
            # "Sa-Su,PH" -> odrzuć PH
            parts = [p for p in parts if p != "PH"]
            days = _parse_days(",".join(parts))
            rest = tokens[1:]
        if days is None:
            return None
        matched_any = True
        if weekday not in days:
            continue
        if not rest or rest[0] in ("off", "closed"):
            if rest and rest[0] in ("off", "closed"):
                state = False
            else:
                state = True
            continue
        spans = _parse_times(" ".join(rest).replace(" ", ""))
        if spans is None:
            return None
        state = any(s <= minute < e for s, e in spans)
    if not matched_any:
        return None
    return False if state is None else state
