"""Classic Trader — pan-European classic car marketplace (dealers and private sellers).

Model pages: /uk/cars/search/<make>/<model-slug>?page=N, results as schema.org Car items in JSON-LD
(checked against the live site 2026-10-21).
"""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup

from ..http import dig, to_int
from .base import Source, new_listing

BASE = "https://www.classic-trader.com"
SLUG = {
    ("mercedes-benz", "190"): "190er", ("mercedes-benz", "w123"): "123er", ("mercedes-benz", "e-klasse"): "e-class",
    ("mercedes-benz", "s-klasse"): "s-class", ("mercedes-benz", "sl"): "sl-class", ("mercedes-benz", "g-klasse"): "g-class",
    ("volkswagen", "t3"): "t3", ("volkswagen", "t4"): "t4", ("mazda", "mx-5"): "mx-5",
}


def parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except json.JSONDecodeError:
            continue
        for ent in data.get("mainEntity", []) if isinstance(data, dict) else []:
            for li in ent.get("itemListElement", []) or []:
                car = li.get("item") or {}
                if car.get("@type") != "Car":
                    continue
                url = car.get("url") or ""
                sid = url.rstrip("/").rsplit("/", 1)[-1]
                ym = re.match(r"(\d{4})\s*\|", car.get("name") or "")
                price = to_int(dig(car, "offers", "price"))
                out.append(new_listing(
                    "classictrader", sid,
                    url=url,
                    title=(car.get("name") or "").split("|", 1)[-1].strip() or None,
                    make=car.get("brand"),
                    model_raw=car.get("model"),
                    price=price if price and price > 1 else None,
                    currency=dig(car, "offers", "priceCurrency", default="EUR"),
                    year=int(ym.group(1)) if ym else to_int(car.get("vehicleModelDate")),
                    mileage_km=to_int(dig(car, "mileageFromOdometer", "value")),
                    images=[car["image"]] if car.get("image") else [],
                    description=car.get("description"),
                ))
    return out


class ClassicTrader(Source):
    key = "classictrader"

    def search(self, q):
        slug = SLUG.get((q.make, q.model), q.model)
        for page in range(1, self.max_pages + 2):
            params = {"page": page} if page > 1 else None
            r = self.client.get(f"{BASE}/uk/cars/search/{q.make}/{slug}", params=params)
            items = parse_page(r.text)
            yield from items
            if len(items) < 15:
                break
