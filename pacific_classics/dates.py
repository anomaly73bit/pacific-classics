"""Parse the publication dates marketplaces show on their result cards ("Heute, 11:32", "17 okt 26"…)."""
from __future__ import annotations

import re
from datetime import date, timedelta

MONTHS = {  # first three letters, DE / NL / EN / FR / IT / CS
    "jan": 1, "mrt": 3, "feb": 2, "fév": 2, "fev": 2, "mär": 3, "maa": 3, "mar": 3, "apr": 4, "avr": 4, "mai": 5, "mei": 5,
    "may": 5, "mag": 5, "jun": 6, "jui": 6, "giu": 6, "jul": 7, "lug": 7, "aug": 8, "aoû": 8, "ago": 8, "sep": 9,
    "set": 9, "okt": 10, "oct": 10, "ott": 10, "nov": 11, "dez": 12, "dec": 12, "déc": 12, "dic": 12, "gen": 1,
}
TODAY = re.compile(r"\b(heute|vandaag|today|aujourd|oggi|dnes)\b", re.I)
YESTERDAY = re.compile(r"\b(gestern|gisteren|yesterday|hier|ieri|včera)\b", re.I)


def parse_listing_date(text: str | None, today: date | None = None) -> str | None:
    """ISO date of a card date like 'Heute, 11:32', 'Gestern', '23.12.2025', '17 okt 26', '2026-10-21T09:50'."""
    if not text:
        return None
    today = today or date.today()
    t = text.strip().lower()
    if TODAY.search(t):
        return today.isoformat()
    if YESTERDAY.search(t):
        return (today - timedelta(days=1)).isoformat()
    m = re.search(r"(20\d\d)-(\d\d)-(\d\d)", t)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](\d{2,4})\b", t)
    if m:
        y = int(m.group(3)); y += 2000 if y < 100 else 0
        try:
            return date(y, int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})\.?\s+([a-zäéûè]{3})[a-zäéûè.]*\s*(\d{2,4})?\b", t)
    if m and m.group(2)[:3] in MONTHS:
        y = int(m.group(3)) if m.group(3) else today.year
        y += 2000 if y < 100 else 0
        try:
            d = date(y, MONTHS[m.group(2)[:3]], int(m.group(1)))
        except ValueError:
            return None
        if d > today:                       # "3 dec" without a year in January means last December
            d = d.replace(year=d.year - 1)
        return d.isoformat()
    return None
