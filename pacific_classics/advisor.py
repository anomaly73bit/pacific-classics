"""The Pacific Classics advisor: alerts, tips and a 0-100 score for every listing.

Alerts are emitted as language-neutral codes + parameters; the website translates them (EN/IT).
Levels: good | info | warn | danger
"""
from __future__ import annotations

import re
import statistics
from datetime import date

from .knowledge import Model

FIVA_AGE = 30
ASI_AGE = 20

KEYWORDS = [
    # (level, code, regex) — matched on title + description
    ("danger", "KW_ACCIDENT", r"unfall(?!frei)|unfallwagen|accident(?![- ]?free)|accidenté|(?<!ne)havarov|(?<!ne)bouran|(?<!non )incidentat|(?<!non )sinistrat"),
    ("good", "KW_NO_ACCIDENT", r"unfallfrei|accident[- ]?free|nehavarov|nebouran|non incidentat|mai incidentat"),
    ("danger", "KW_DEFECT", r"motorschaden|defekt|ohne motor|engine damage|bastler|projekt|project car|nepojízd|non funzionante|guasto|für export"),
    ("warn", "KW_RUST", r"\brost|rust|koroz|ruggine|rouille|durchgerostet"),
    ("warn", "KW_NO_PAPERS", r"ohne papiere|no papers|bez tp|senza documenti|sans papiers|ohne brief"),
    ("good", "KW_HISTORY", r"scheckheft|service ?history|servisní knížk|libretto tagliandi|carnet d.entretien|lückenlos"),
    ("good", "KW_FIRST_OWNER", r"1\.\s?hand|erstbesitz|first owner|1\. majitel|prima mano|unico proprietario|première main"),
    ("good", "KW_HISTORIC_REG", r"h-?kennzeichen|h-?zulassung|historic plate|veterán|\bcrs\b|\basi\b|targa oro|carte grise collection"),
    ("good", "KW_GARAGED", r"garagenwagen|garaged|garážov|sempre in garage|scheunenfund"),
    ("info", "KW_INSPECTION", r"tüv neu|tüv bis|hu neu|stk do|revisionata|pickerl"),
]
KEYWORDS = [(lvl, code, re.compile(rx, re.I)) for lvl, code, rx in KEYWORDS]
AUTO_RX = re.compile(r"auto|automat|automatik|automatic|automatica", re.I)


def historic_status(year: int | None, ref_year: int) -> dict:
    if not year:
        return {"age": None, "fiva": False, "asi": False, "fiva_year": None, "asi_year": None}
    return {
        "age": ref_year - year,
        "fiva": ref_year - year >= FIVA_AGE,
        "asi": ref_year - year >= ASI_AGE,
        "fiva_year": year + FIVA_AGE,
        "asi_year": year + ASI_AGE,
    }


def market_stats(listings: list[dict]) -> dict[str, dict]:
    """Per model family: median price/mileage plus the peers used to value each car."""
    by_model: dict[str, list[dict]] = {}
    for l in listings:
        if l.get("model_id") and l.get("price_eur") and not l.get("sold"):
            by_model.setdefault(l["model_id"], []).append(l)
    stats = {}
    for mid, ls in by_model.items():
        prices = sorted(l["price_eur"] for l in ls)
        kms = [l["mileage_km"] for l in ls if l.get("mileage_km")]
        stats[mid] = {
            "count": len(ls),
            "median_price": int(statistics.median(prices)),
            "p25": int(prices[len(prices) // 4]),
            "p75": int(prices[(3 * len(prices)) // 4]),
            "median_km": int(statistics.median(kms)) if kms else None,
            "_peers": [(l.get("year"), l.get("mileage_km"), l["price_eur"]) for l in ls],
        }
    return stats


KM_STEP, KM_EFFECT, KM_CAP = 50_000, 0.05, 0.20   # each 50,000 km above/below peers: -/+5% (max ±20%)


def _pool(l: dict, stats: dict | None) -> list[float]:
    """Mileage-adjusted prices of comparable cars (same family, year ±3 when there are enough)."""
    if not stats:
        return []
    peers = stats.get("_peers") or []
    year, km = l.get("year"), l.get("mileage_km")
    near = [p for p in peers if year and p[0] and abs(p[0] - year) <= 3]
    pool = near if len(near) >= 6 else peers
    if len(pool) < 5:
        return []
    out = []
    for py, pk, pp in pool:
        # bring each peer to this car's mileage: each 50,000 km more = -5% (max ±20%)
        if km and pk:
            pp *= 1 - max(-KM_CAP, min(KM_CAP, (km - pk) / KM_STEP * KM_EFFECT))
        out.append(pp)
    return sorted(out)


def fair_price(l: dict, stats: dict | None) -> tuple[int | None, int]:
    """Expected market price of this car (median of comparable cars). Returns (fair_price, n_comparables)."""
    pool = _pool(l, stats)
    return (int(statistics.median(pool)), len(pool)) if pool else (None, 0)


def price_rating(price: int | None, fair: int | None, n: int, danger: bool, pool: list[float] | None = None) -> dict:
    """great / good / fair / high / suspicious / unknown + frame colour.
    Uses both the gap to the fair price and the car's rank among comparable cars, so wide-ranging
    families (cheap projects next to concours cars) don't turn most ads red."""
    if not price or not fair:
        level, pct, rank = "unknown", None, None
    else:
        pct = round((price - fair) / fair * 100)
        rank = (sum(1 for p in pool if p < price) / len(pool)) if pool else 0.5
        if pct <= -50 and rank <= 0.05:
            level = "suspicious"
        elif pct <= -15 and rank <= 0.25:
            level = "great"
        elif pct <= -5:
            level = "good"
        elif pct >= 20 and rank >= 0.75:
            level = "high"
        else:
            level = "fair"
    frame = "red" if danger or level in ("high", "suspicious") else "green" if level in ("great", "good") else None
    return {"level": level, "pct": pct, "fair": fair, "peers": n, "frame": frame}


def advise(l: dict, m: Model, stats: dict | None, ref_year: int | None = None,
           history: dict | None = None) -> dict:
    ref_year = ref_year or date.today().year
    alerts: list[dict] = []

    def add(level, code, **params):
        alerts.append({"level": level, "code": code, "params": params})

    text = " ".join(filter(None, [l.get("title"), l.get("model_raw"), l.get("description")]))

    # --- historic registration
    h = historic_status(l.get("year"), ref_year)
    if h["fiva"]:
        add("good", "HIST_FIVA", year=l["year"])
    elif h["asi"]:
        add("info", "HIST_ASI_ONLY", fiva_year=h["fiva_year"], years=h["fiva_year"] - ref_year)
    elif h["asi_year"]:
        add("info", "HIST_NOT_YET", asi_year=h["asi_year"], fiva_year=h["fiva_year"])

    # --- price vs market
    price = l.get("price_eur")
    pct = None
    if not price:
        add("info", "NO_PRICE")
    elif fair_price(l, stats)[0]:
        med = fair_price(l, stats)[0]
        pct = round((price - med) / med * 100)
        if pct <= -50 and price_rating(price, med, 0, False, _pool(l, stats))["level"] == "suspicious":
            add("danger", "PRICE_SUSPICIOUS", pct=-pct, median=med)
        elif pct <= -20:
            add("good", "PRICE_DEAL", pct=-pct, median=med)
        elif price_rating(price, med, 0, False, _pool(l, stats))["level"] == "high":
            add("warn", "PRICE_HIGH", pct=pct, median=med)
        else:
            add("info", "PRICE_FAIR", pct=pct, median=med)

    # --- price history from previous crawls
    if history and history.get("first_price") and price and price < history["first_price"]:
        drop = round((history["first_price"] - price) / history["first_price"] * 100)
        if drop >= 3:
            add("good", "PRICE_DROP", pct=drop, was=history["first_price"])

    # --- engine
    eng_good = any(rx.search(text) for rx in m.engine_good)
    eng_bad = any(rx.search(text) for rx in m.engine_bad)
    if eng_bad:
        add("warn", "ENGINE_BAD", note=m.engine_bad_note or "")
    elif eng_good:
        add("good", "ENGINE_GOOD", engines=m.recommended_engines)

    # --- mileage
    km = l.get("mileage_km")
    age = h["age"] or 0
    if km is None:
        add("info", "KM_UNKNOWN")
    elif km >= 300_000:
        add("info" if m.high_mileage_ok else "warn", "KM_HIGH_OK" if m.high_mileage_ok else "KM_HIGH", km=km)
    elif age >= 25 and km < 60_000:
        add("warn", "KM_LOW_VERIFY", km=km)

    # --- gearbox
    if m.auto_gearbox_caution and AUTO_RX.search(str(l.get("gearbox") or "") + " " + text):
        add("warn", "AUTO_GEARBOX")

    # --- listing quality / seller
    n_img = len(l.get("images") or [])
    if n_img == 0:
        add("warn", "NO_PHOTOS")
    if l.get("seller_type") == "dealer":
        add("info", "DEALER")
    elif l.get("seller_type") == "private":
        add("info", "PRIVATE")

    # --- keywords in the ad text
    for lvl, code, rx in KEYWORDS:
        if rx.search(text):
            add(lvl, code)

    # --- import to Italy
    if l.get("country") and l["country"] != "IT":
        add("info", "IMPORT_IT", country=l["country"])

    if l.get("match_confidence") == "low":
        add("warn", "MATCH_UNSURE")

    # --- score: reliability baseline, bounded bonus for good signs, penalties for risks, price position
    score = 30 + m.reliability * 6
    goods = sum(1 for a in alerts if a["level"] == "good" and a["code"] != "HIST_FIVA")
    score += min(goods * 4, 16)
    score -= 8 * sum(1 for a in alerts if a["level"] == "warn")
    score -= 20 * sum(1 for a in alerts if a["level"] == "danger")
    if pct is not None and pct > -45:
        score += max(-12, min(12, -pct / 3))
    score = int(max(0, min(100, round(score))))

    fair, n_peers = fair_price(l, stats)
    rating = price_rating(price, fair, n_peers, any(a["level"] == "danger" for a in alerts), _pool(l, stats))
    return {
        "price_rating": rating,
        "alerts": alerts,
        "historic": h,
        "price_vs_median_pct": pct,
        "score": score,
        "tips": {
            "watch_out": m.watch_out,
            "recommended_engines": m.recommended_engines,
            "strengths": m.strengths,
            "engine_bad_note": m.engine_bad_note,
        },
    }
