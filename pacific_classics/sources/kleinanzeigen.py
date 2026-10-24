"""Kleinanzeigen.de (ex eBay Kleinanzeigen) — Germany's biggest private classifieds site.

Uses the car category's own make/model/year filters:
  /s-autos/c216+autos.marke_s:mercedes_benz+autos.model_s:190   (year filter is disallowed in robots.txt)
When the site has no model value for a family, falls back to keyword + make + year filters.
Markup checked against the live site on 2026-10-21.
"""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from ..dates import parse_listing_date
from ..http import to_int
from .base import Source, new_listing

BASE = "https://www.kleinanzeigen.de"

# model_s values offered by Kleinanzeigen for each make (scraped from its filter menu, 2026-10-21)
KNOWN = {
    "audi": "80 100 a4", "bmw": "316 318 320 323 325 328 330 520 523 525 528 530 535",
    "citroen": "bx zx xantia c1 berlingo", "daihatsu": "charade feroza_sportrak rocky_fourtrak sirion cuore",
    "fiat": "panda uno tipo doblo", "ford": "sierra escort transit", "honda": "accord civic crx prelude jazz cr_v",
    "lada": "niva", "land_rover": "defender discovery", "lexus": "ls_400 ls_430 is_200", "mazda": "323 626 mx_5 2 3 6",
    "mercedes_benz": "190 200 220 230 250 280 300 320 350 e_klasse s_klasse sl_280 sl_300 sl_320 sl_500",
    "mitsubishi": "galant l200 lancer pajero", "nissan": "200_sx micra patrol sunny terrano",
    "opel": "kadett omega vectra", "peugeot": "205 306 309 405 505 107 406 partner", "porsche": "911 928 944 964",
    "renault": "express r_19 r_4 clio kangoo", "saab": "900 9000", "subaru": "impreza legacy forester",
    "suzuki": "sj_samurai vitara swift ignis wagon_rplus jimny grand",
    "toyota": "4_runner camry carina celica corolla hilux land_cruiser mr_2 previa supra yaris aygo avensis prius rav",
    "volkswagen": "golf jetta passat polo t3 t4 transporter bora", "volvo": "240 245 740 760 850 940 960 v70 s60",
    "skoda": "fabia octavia", "hyundai": "getz", "kia": "picanto", "dacia": "logan sandero",
}
KNOWN = {k: set(v.split()) for k, v in KNOWN.items()}
ALIAS = {"samurai": "sj_samurai", "sj": "sj_samurai", "rocky": "rocky_fourtrak", "feroza": "feroza_sportrak",
         "4": "r_4", "19": "r_19", "ls": "ls_400", "rav-4": "rav", "grand-vitara": "grand", "wagon-r+": "wagon_rplus"}
MAKE_NAMES = {"mercedes-benz": "Mercedes-Benz", "volkswagen": "Volkswagen", "land-rover": "Land Rover", "bmw": "BMW"}


def _filters(make: str, model: str, y1: int, y2: int) -> tuple[str, str | None]:
    mk = make.replace("-", "_")
    md = ALIAS.get(model, model.replace("-", "_"))
    # robots.txt disallows the year filter (autos.ez_i) and pages beyond 5: years are filtered by the matcher
    f = f"c216+autos.marke_s:{mk}"
    if md in KNOWN.get(mk, set()):
        return f + f"+autos.model_s:{md}", None
    return f, f"{make} {model}".replace("-", " ")


def search_path(make, model, y1, y2, page=1) -> str:
    f, kw = _filters(make, model, y1, y2)
    seite = f"seite:{page}/" if page > 1 else ""
    if kw:
        slug = re.sub(r"[^a-z0-9]+", "-", kw.lower()).strip("-")
        return f"/s-autos/{seite}{slug}/k0{f}"
    return f"/s-autos/{seite}{f}"


def _big(u: str) -> str:
    return re.sub(r"rule=\$_\d+\.AUTO", "rule=$_59.AUTO", u)


def parse_page(html: str, make_hint: str | None = None) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for art in soup.select("article[data-adid]"):
        aid = art.get("data-adid")
        href = art.get("data-href")
        ld = {}
        s = art.find("script", type="application/ld+json")
        if s and s.string:
            try:
                ld = json.loads(s.string)
            except json.JSONDecodeError:
                pass
        h = art.select_one("h3 a, h2 a")
        title = h.get_text(" ", strip=True) if h else ld.get("title")
        price_el = next((p for p in art.select("p") if "€" in p.get_text() and "line-through" not in " ".join(p.get("class", []))), None)
        price_txt = price_el.get_text(" ", strip=True) if price_el else ""
        spans = [sp.get_text(" ", strip=True) for sp in art.select("span")]
        loc = next((t for t in spans if re.match(r"^\d{5}\s+\S", t)), "")
        zm = re.match(r"(\d{5})\s+(.+)", loc)
        alltxt = " | ".join(spans)
        listed = next((parse_listing_date(t) for t in spans
                       if re.match(r"^(heute|gestern|\d{1,2}\.\d{1,2}\.\d{4})", t, re.I)), None)
        km = re.search(r"([\d.]+)\s*km\b", alltxt)
        ez = re.search(r"EZ\s*(?:\d{1,2}/)?((?:19|20)\d\d)", alltxt)
        desc_el = art.select_one("p.text-onSurfaceSubdued") or next((p for p in art.select("p") if p is not price_el and "€" not in p.get_text()), None)
        img = art.select_one("img")
        img_url = ld.get("contentUrl") or (img.get("src") if img else None)
        out.append(new_listing(
            "kleinanzeigen", aid,
            url=BASE + href if href and href.startswith("/") else href,
            title=title,
            make=make_hint,
            price=to_int(price_txt) if re.search(r"\d", price_txt) else None,
            currency="EUR",
            year=int(ez.group(1)) if ez else None,
            mileage_km=to_int(km.group(1)) if km else None,
            country="DE",
            listed_at=listed,
            zip=zm.group(1) if zm else None,
            city=zm.group(2) if zm else None,
            images=[_big(img_url)] if img_url and img_url.startswith("http") else [],
            description=(ld.get("description") or (desc_el.get_text(" ", strip=True) if desc_el else ""))[:400] or None,
        ))
    return out


class Kleinanzeigen(Source):
    key = "kleinanzeigen"

    def search(self, q):
        make = MAKE_NAMES.get(q.make, q.make.replace("-", " ").title())
        for page in range(1, min(self.max_pages + 2, 5) + 1):
            items = parse_page(self.client.get(BASE + search_path(q.make, q.model, q.year_from, q.year_to, page)).text, make_hint=make)
            yield from items
            if len(items) < 25:
                break
