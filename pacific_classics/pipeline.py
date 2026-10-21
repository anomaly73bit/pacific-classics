"""Crawl → normalise → match → advise → publish JSON for the website."""
from __future__ import annotations

import json
import logging
import re
import hashlib
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

import requests

from .advisor import advise, market_stats
from .http import Blocked, PoliteClient
from .translate import translate_listings
from .highlights import extract as extract_highlights
from .crypto import decrypt_bundle, encrypt_bundle
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

    prev = _load_prev()
    verify: dict[str, str] = {}
    max_checks = cfg["crawler"].get("verify_per_source", 150)

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
        if rep["status"] == "ok" and not only_models:
            # ads published last time but not found now: open them to see if they are really gone
            got = {it["id"] for it, _ in found}
            missing = [l for l in prev.values() if l["source"] == key and l["id"] not in got and not l.get("sold")]
            checked = 0
            for l in missing[:max_checks]:
                verify[l["id"]] = check_gone(src.client, l["url"])
                checked += 1
            rep["verified_missing"] = {"missing": len(missing), "checked": checked,
                                       "sold": sum(1 for l in missing if verify.get(l["id"]) == "sold")}
        return found

    raw: list[tuple[dict, list[str]]] = []
    with ThreadPoolExecutor(max_workers=max(1, len(sources))) as ex:
        for found in ex.map(lambda kv: run_source(*kv), sources.items()):
            raw.extend(found)

    report["finished"] = _now()
    return {"raw": raw, "report": report, "models": by_id, "cfg": cfg, "verify": verify}


GONE = re.compile(r"nicht mehr verfügbar|nicht mehr online|wurde (bereits )?verkauft|anzeige (ist )?(gelöscht|deaktiviert|abgelaufen)|"
                  r"no longer available|has been sold|niet meer beschikbaar|is verkocht|inzerát (již |už )?(není|neexistuje)|"
                  r"inzerát bol (zmazaný|odstránený)|predan[éeý]|n'est plus disponible|annonce (supprimée|expirée)|"
                  r"ya no está disponible|vendid[oa]\b|non è più disponibile|venduta\b", re.I)


def check_gone(client, url: str | None) -> str:
    """'sold' if the ad page is gone (404/410, redirect away from the ad, 'no longer available' text), else 'alive'."""
    if not url:
        return "unknown"
    try:
        r = client.get(url)
    except Blocked:
        return "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"
    if r.status_code in (404, 410):
        return "sold"
    from urllib.parse import urlparse
    a, b = urlparse(url).path.rstrip("/"), urlparse(r.url).path.rstrip("/")
    if a != b and not b.startswith(a):
        return "sold"
    return "sold" if GONE.search(r.text[:300000]) else "alive"


def process(raw: list[tuple[dict, list[str]]], models: dict, cfg: dict, report: dict,
            ref_year: int | None = None, demo: bool = False, verify: dict | None = None) -> list[dict]:
    rates, fx_src = fx_rates(cfg.get("fx_fallback", {}))
    report["fx_source"] = fx_src
    excl = [re.compile(p, re.I) for p in cfg.get("exclude_patterns", [])]
    state = _load_state() if not demo else {}
    today = date.today().isoformat()

    seen: dict[str, dict] = {}
    dropped = {"excluded": 0, "no_match": 0, "price_bounds": 0, "duplicate": 0, "no_photo": 0}
    for item, model_ids in raw:
        if item["id"] in seen:
            dropped["duplicate"] += 1
            continue
        if not [u for u in item.get("images") or [] if u and not u.endswith("placeholder.svg")] and not item.get("demo"):
            dropped["no_photo"] += 1          # an ad without at least one photo is never published
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
        st = state.get(ref_of(item["id"])) or {"first_seen": today, "first_price": item["price_eur"]}
        st["last_seen"] = today
        state[ref_of(item["id"])] = st
        item["first_seen"] = st["first_seen"]
        item["_hist"] = st
        seen[item["id"]] = item

    listings = list(seen.values())
    found_ids = set(seen)
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
    for l in listings:
        l["variant"] = variant_of(l, models[l["model_id"]])
        l["highlights"] = extract_highlights(" ".join(filter(None, [l.get("title"), l.get("description")])))
    listings.sort(key=lambda l: -l["score"])
    if not demo and os.environ.get("PACIFIC_TRANSLATE", "1") == "1":
        try:
            report["translation"] = translate_listings(listings)
        except Exception as e:  # noqa: BLE001 — translation must never break publishing
            log.warning("translation skipped: %s", e)
            report["translation"] = {"error": str(e)[:200]}

    if not demo:
        listings += _carry_over(found_ids, state, verify or {}, today, models)
    report["dropped"] = dropped
    report["published"] = len(listings)
    report["sold_shown"] = sum(1 for l in listings if l.get("sold"))
    report["market"] = stats
    if not demo:
        _save_state(state)
    return listings


def variant_of(l: dict, m) -> int:
    """Which model of a family the ad is (e.g. 'Golf III' in 'Passat B3/B4 / Golf III / Polo'): its index."""
    names = re.split(r"\s+/\s+", m.model)
    if len(names) < 2:
        return 0
    text = " ".join(filter(None, [l.get("title"), l.get("model_raw")])).lower()
    for i, n in enumerate(names):
        head = re.sub(r"\(.*?\)", "", n).strip().lower().split()[0]
        if re.search(rf"\b{re.escape(head)}", text):
            return i
    return 0


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


COMMISSION = 0.05
ROUND_TO = 50
PUBLIC_FIELDS = ("model_id", "variant", "title", "title_it", "year", "year_estimated", "mileage_km", "fuel", "gearbox",
                 "power_kw", "country", "city", "zip", "region", "images", "seller_type", "highlights", "alerts", "historic",
                 "score", "first_seen", "sold", "sold_at", "match_confidence", "lang", "price_vs_median_pct", "demo")


def ref_of(lid: str) -> str:
    """Public reference of an ad (no source site in it), e.g. PC-7F3A2C."""
    return "PC-" + hashlib.sha1(lid.encode()).hexdigest()[:6].upper()


def client_price(eur: int | None) -> int | None:
    """Price shown to customers: car price + Pacific Classics commission, rounded up."""
    return int(math.ceil(eur * (1 + COMMISSION) / ROUND_TO) * ROUND_TO) if eur else None


def public_view(l: dict) -> dict:
    """Customer-safe copy: final price, no source site, link, seller name or purchase price."""
    out = {k: l[k] for k in PUBLIC_FIELDS if k in l}
    out["ref"] = l["ref"]
    out["price"] = client_price(l.get("price_eur"))
    alerts = []
    for a in l.get("alerts", []):
        p = dict(a.get("params") or {})
        for k in ("median", "was"):
            if p.get(k):
                p[k] = client_price(p[k])
        alerts.append({**a, "params": p})
    out["alerts"] = alerts
    return out


def publish(listings: list[dict], models: dict, report: dict, demo: bool = False):
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    out = SITE_DATA / "listings.json"
    if not listings and not demo and out.exists():
        # every source failed: keep the previous cars online instead of publishing an empty site
        log.warning("crawl returned nothing — keeping previous listings")
        return
    for l in listings:
        l["ref"] = ref_of(l["id"])
    meta = {"generated": _now(), "demo": demo, "count": len(listings), "commission": COMMISSION}
    public = [public_view(l) for l in listings]
    out.write_text(json.dumps({"meta": meta, "listings": public}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (SITE_DATA / "models.json").write_text(json.dumps([m.to_public() for m in models.values()], ensure_ascii=False, indent=1), encoding="utf-8")
    (SITE_DATA / "report.json").unlink(missing_ok=True)          # the report names the sources: admin bundle only
    user, pwd = os.environ.get("PACIFIC_ADMIN_USER"), os.environ.get("PACIFIC_ADMIN_PASSWORD")
    if user and pwd:
        admin = [{k: v for k, v in l.items() if k != "description"} for l in listings]
        bundle = encrypt_bundle({"meta": meta, "listings": admin, "report": report}, user, pwd)
        (SITE_DATA / "admin.enc").write_text(json.dumps(bundle), encoding="utf-8")
    elif not demo:
        log.warning("PACIFIC_ADMIN_USER/PASSWORD not set: admin bundle not written")
    log.info("published %d listings → %s", len(listings), SITE_DATA)


SOLD_DAYS = 7      # a sold car stays on the site, greyed out, for this many days
UNSEEN_DAYS = 3    # an ad we couldn't re-check is kept this long before being dropped


def _load_prev() -> dict[str, dict]:
    """Previous run's full listings, from the encrypted admin bundle (the public file has no ids/links)."""
    user, pwd = os.environ.get("PACIFIC_ADMIN_USER"), os.environ.get("PACIFIC_ADMIN_PASSWORD")
    try:
        env = json.loads((SITE_DATA / "admin.enc").read_text(encoding="utf-8"))
        data = decrypt_bundle(env, user, pwd) if user and pwd else {}
        if data.get("meta", {}).get("demo"):
            return {}
        return {l["id"]: l for l in data.get("listings", []) if "id" in l}
    except Exception:  # noqa: BLE001 — missing file, no credentials or changed password: start fresh
        return {}


def _carry_over(found_ids: set, state: dict, verify: dict, today: str, models: dict) -> list[dict]:
    """Ads from the previous run that this crawl didn't find: sold, still alive (kept), or dropped."""
    now = date.fromisoformat(today)
    out = []
    for lid, l in _load_prev().items():
        if lid in found_ids or l.get("model_id") not in models or not l.get("images"):
            continue
        st = state.setdefault(ref_of(lid), {"first_seen": l.get("first_seen", today), "last_seen": today})
        if l.get("sold"):
            if (now - date.fromisoformat(l["sold_at"])).days <= SOLD_DAYS:
                out.append(l)
            continue
        v = verify.get(lid)
        if v == "sold":
            l["sold"], l["sold_at"] = True, today
            out.append(l)
        elif v == "alive":
            st["last_seen"] = today
            out.append(l)
        elif (now - date.fromisoformat(st.get("last_seen", today))).days <= UNSEEN_DAYS:
            out.append(l)
    return out


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
