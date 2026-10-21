"""Crawl → normalise → match → advise → publish JSON for the website."""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from .advisor import advise, market_stats
from .http import Blocked, PoliteClient
from .knowledge import ROOT, build_queries, load_models, load_sources, match_listing
from .sources import REGISTRY

log = logging.getLogger("pacific")
SITE_DATA = ROOT / "site" / "data"
STATE = ROOT / "data" / "state.json"


def fx_rates(fallback: dict) -> tuple[dict, str]:
    """EUR value of one unit of each currency. Live from the ECB when reachable."""
    try:
        r = requests.get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml", timeout=15)
        rates = {"EUR": 1.0}
        for cur, rate in re.findall(r"currency='([A-Z]{3})' rate='([\d.]+)'", r.text):
            rates[cur] = 1 / float(rate)
        if len(rates) > 10:
            return rates, "ECB"
    except requests.RequestException:
        pass
    return dict(fallback), "fallback"


def crawl(only_sources: list[str] | None = None, only_models: list[str] | None = None) -> dict:
    cfg = load_sources()
    models = load_models()
    if only_models:
        models = [m for m in models if any(k in m.id for k in only_models)]
    by_id = {m.id: m for m in models}
    queries = build_queries(models)
    sources, report = {}, {"sources": {}, "started": _now()}
    for key, scfg in cfg["sources"].items():
        if only_sources and key not in only_sources:
            continue
        if not scfg.get("enabled"):
            report["sources"][key] = {"name": scfg.get("name", key), "status": "skipped", "fetched": 0,
                                      "note": scfg.get("note", "disabled in config"), "errors": [], "queries": {}}
            continue
        # one client per source: each site keeps its own rate limit, sites are crawled in parallel
        ccfg = {**cfg["crawler"], **{k: scfg[k] for k in ("delay_seconds",) if k in scfg}}
        src = REGISTRY[key](PoliteClient(ccfg), scfg, cfg["crawler"])
        ok, why = src.available()
        report["sources"][key] = {"name": scfg.get("name", key), "status": "ok" if ok else "skipped",
                                  "note": why, "fetched": 0, "errors": [], "queries": {}}
        if ok:
            sources[key] = src

    make_ids: dict[str, list[str]] = {}
    make_years: dict[str, list[int]] = {}
    for q in queries:
        make_ids.setdefault(q.make, [])
        make_ids[q.make] += [i for i in q.model_ids if i not in make_ids[q.make]]
        y = make_years.setdefault(q.make, [q.year_from, q.year_to])
        y[0], y[1] = min(y[0], q.year_from), max(y[1], q.year_to)
    for src in sources.values():
        src.context = {"models": by_id, "make_years": make_years}

    def run_source(key, src):
        rep, found = report["sources"][key], []
        for q in queries:
            n = 0
            try:
                ids = make_ids[q.make] if src.match_all else q.model_ids
                for item in src.search(q):
                    found.append((item, ids))
                    n += 1
            except Blocked as e:
                rep["status"], rep["note"] = "blocked", str(e)
                log.warning("%s blocked: %s — skipping it for the rest of this run", key, e)
                break
            except Exception as e:  # noqa: BLE001 — one bad query must not stop the crawl
                rep["errors"].append(f"{q.make}|{q.model}: {type(e).__name__}: {e}"[:300])
                log.warning("%s %s|%s failed: %s", key, q.make, q.model, e)
            rep["queries"][f"{q.make}|{q.model}"] = n
            rep["fetched"] += n
            log.info("%-14s %-28s %4d", key, f"{q.make}|{q.model}", n)
        return found

    raw: list[tuple[dict, list[str]]] = []
    with ThreadPoolExecutor(max_workers=max(1, len(sources))) as ex:
        for found in ex.map(lambda kv: run_source(*kv), sources.items()):
            raw.extend(found)

    report["finished"] = _now()
    return {"raw": raw, "report": report, "models": by_id, "cfg": cfg}


def process(raw: list[tuple[dict, list[str]]], models: dict, cfg: dict, report: dict,
            ref_year: int | None = None, demo: bool = False) -> list[dict]:
    rates, fx_src = fx_rates(cfg.get("fx_fallback", {}))
    report["fx_source"] = fx_src
    excl = [re.compile(p, re.I) for p in cfg.get("exclude_patterns", [])]
    state = _load_state() if not demo else {}
    today = date.today().isoformat()

    seen: dict[str, dict] = {}
    dropped = {"excluded": 0, "no_match": 0, "price_bounds": 0, "duplicate": 0}
    for item, model_ids in raw:
        if item["id"] in seen:
            dropped["duplicate"] += 1
            continue
        text = " ".join(filter(None, [item.get("title"), item.get("description")]))
        if any(rx.search(text) for rx in excl):
            dropped["excluded"] += 1
            continue
        rate = rates.get(item.get("currency") or "EUR")
        item["price_eur"] = int(round(item["price"] * rate)) if item.get("price") and rate else None
        if item["price_eur"] and not (cfg.get("min_price_eur", 0) <= item["price_eur"] <= cfg.get("max_price_eur", 10**7)):
            dropped["price_bounds"] += 1
            continue
        if not item.get("year"):
            item["year"] = guess_year(text)
            item["year_estimated"] = bool(item["year"])
        model, conf = match_listing(item, [models[i] for i in model_ids if i in models])
        if not model:
            dropped["no_match"] += 1
            continue
        item["model_id"], item["match_confidence"] = model.id, conf
        st = state.get(item["id"]) or {"first_seen": today, "first_price": item["price_eur"]}
        st["last_seen"] = today
        state[item["id"]] = st
        item["first_seen"] = st["first_seen"]
        item["_hist"] = st
        seen[item["id"]] = item

    listings = list(seen.values())
    for l in listings:
        l["fuel"], l["gearbox"] = _it(l.get("fuel"), FUEL_IT), _it(l.get("gearbox"), GEAR_IT)
    _mark_cross_site_duplicates(listings)
    dropped["duplicate"] += sum(1 for l in listings if l.get("duplicate_of"))
    listings = [l for l in listings if not l.get("duplicate_of")]   # publish each car once
    stats = market_stats([l for l in listings if not l.get("duplicate_of")])
    for l in listings:
        l.update(advise(l, models[l["model_id"]], stats.get(l["model_id"]), ref_year, l.pop("_hist", None)))
        if l.get("description"):
            l["description"] = l["description"][:400]
    listings.sort(key=lambda l: -l["score"])

    report["dropped"] = dropped
    report["published"] = len(listings)
    report["market"] = stats
    if not demo:
        _save_state(state)
    return listings


YEAR_HINT = re.compile(r"(?:\bEZ|Baujahr|\bBj\.?|Erstzulassung|rok v\w+|r\.\s?v\.|\banno|immatricolat\w*|\bannée)\s*:?\s*(?:\d{1,2}[./]\s?)?((?:19|20)\d\d)", re.I)


def guess_year(text: str) -> int | None:
    m = YEAR_HINT.search(text or "")
    return int(m.group(1)) if m else None


FUEL_IT = [(r"diesel|nafta|tdi|\btd\b", "Diesel"), (r"lpg|gpl|autogas", "GPL"), (r"cng|metano|erdgas", "Metano"),
           (r"hybrid|ibrid", "Ibrida"), (r"elektr|electric", "Elettrica"),
           (r"benz|petrol|gasoline|essence|gasolina|super|otto|\bb\b", "Benzina")]
GEAR_IT = [(r"auto|automat|tiptronic", "Automatico"), (r"man|schalt|hand|ruční|manu", "Manuale")]


def _it(value, table):
    if not value:
        return value
    for rx, it in table:
        if re.search(rx, str(value), re.I):
            return it
    return value


def _words(t: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{2,}", (t or "").lower()))


def _same_car(a: dict, b: dict) -> bool:
    if a.get("year") != b.get("year") or not a.get("price_eur") or not b.get("price_eur"):
        return False
    if abs(a["price_eur"] - b["price_eur"]) > max(a["price_eur"], b["price_eur"]) * 0.03:
        return False
    if a.get("mileage_km") and b.get("mileage_km"):
        return abs(a["mileage_km"] - b["mileage_km"]) <= max(a["mileage_km"], b["mileage_km"]) * 0.01
    wa, wb = _words(a.get("title")), _words(b.get("title"))
    same_place = a.get("zip") and a.get("zip") == b.get("zip")
    return bool(wa and wb) and (len(wa & wb) / len(wa | wb) >= 0.6 or (same_place and len(wa & wb) >= 2))


def _mark_cross_site_duplicates(listings: list[dict]):
    """The same car is often listed on several sites (or twice on one): keep one, link the others."""
    keyed: dict[tuple, list[dict]] = {}
    for l in listings:
        if l.get("year") and l.get("price_eur"):
            keyed.setdefault((l["model_id"], l["year"]), []).append(l)
    for group in keyed.values():
        # keep the copy with most photos and most data
        group.sort(key=lambda l: (-len(l.get("images") or []), l.get("mileage_km") is None))
        for i, a in enumerate(group):
            if a.get("duplicate_of"):
                continue
            for b in group[i + 1:]:
                if not b.get("duplicate_of") and _same_car(a, b):
                    b["duplicate_of"] = a["id"]
                    a.setdefault("also_on", []).append({"source": b["source"], "url": b["url"]})


def publish(listings: list[dict], models: dict, report: dict, demo: bool = False):
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    out = SITE_DATA / "listings.json"
    if not listings and not demo and out.exists():
        # every source failed: keep yesterday's cars online instead of publishing an empty site
        log.warning("crawl returned nothing — keeping previous listings, updating the report only")
        report["kept_previous"] = True
        (SITE_DATA / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        return
    meta = {"generated": _now(), "demo": demo, "count": len(listings)}
    (SITE_DATA / "listings.json").write_text(json.dumps({"meta": meta, "listings": listings}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (SITE_DATA / "models.json").write_text(json.dumps([m.to_public() for m in models.values()], ensure_ascii=False, indent=1), encoding="utf-8")
    (SITE_DATA / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("published %d listings → %s", len(listings), SITE_DATA)


def _load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict):
    cutoff = time.time() - 120 * 86400  # forget cars not seen for 120 days
    state = {k: v for k, v in state.items()
             if datetime.fromisoformat(v["last_seen"]).timestamp() > cutoff}
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
