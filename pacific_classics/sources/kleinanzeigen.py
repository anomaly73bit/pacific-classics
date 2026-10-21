"""Kleinanzeigen.de (ex eBay Kleinanzeigen) — Germany's biggest private classifieds site."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ..http import to_int
from .base import Source, new_listing

BASE = "https://www.kleinanzeigen.de"


def parse_page(html: str, make_hint: str | None = None) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for art in soup.select("article.aditem"):
        aid = art.get("data-adid")
        href = art.get("data-href") or (art.select_one("a.ellipsis") or {}).get("href")
        title_el = art.select_one("h2 a, a.ellipsis")
        title = title_el.get_text(" ", strip=True) if title_el else None
        price_el = art.select_one(".aditem-main--middle--price-shipping--price, .aditem-main--middle--price")
        price_txt = price_el.get_text(" ", strip=True) if price_el else ""
        loc_el = art.select_one(".aditem-main--top--left")
        loc = loc_el.get_text(" ", strip=True) if loc_el else ""
        zm = re.match(r"(\d{5})\s+(.+)", loc)
        tags = " ".join(t.get_text(" ", strip=True) for t in art.select(".simpletag, .aditem-main--bottom span"))
        km = re.search(r"([\d.]+)\s*km", tags)
        ez = re.search(r"EZ\s*(?:\d{1,2}/)?(19\d\d|20\d\d)", tags) or re.search(r"\b(19[5-9]\d)\b", tags)
        img = art.select_one(".imagebox img, img")
        img_url = (img.get("src") or img.get("data-src")) if img else None
        desc_el = art.select_one(".aditem-main--middle--description")
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
            zip=zm.group(1) if zm else None,
            city=(zm.group(2) if zm else loc) or None,
            images=[img_url] if img_url and img_url.startswith("http") else [],
            seller_type="dealer" if art.select_one(".badge-hint-pro-small-srp, .text-module-oneline") else "private",
            description=desc_el.get_text(" ", strip=True)[:400] if desc_el else None,
        ))
    return out


MAKE_NAMES = {"mercedes-benz": "Mercedes-Benz", "volkswagen": "Volkswagen", "land-rover": "Land Rover", "bmw": "BMW"}


class Kleinanzeigen(Source):
    key = "kleinanzeigen"

    def search(self, q):
        slug = re.sub(r"[^a-z0-9]+", "-", q.keyword.lower()).strip("-")
        make = MAKE_NAMES.get(q.make, q.make.replace("-", " ").title())
        for page in range(1, self.max_pages + 1):
            path = f"/s-autos/{slug}/k0c216" if page == 1 else f"/s-autos/seite:{page}/{slug}/k0c216"
            items = parse_page(self.client.get(BASE + path).text, make_hint=make)
            yield from items
            if len(items) < 25:
                break
