"""Autobazar.eu — main Slovak marketplace (also Czech/Hungarian sellers).

Searched per make with the site's year filter (checked against the live site 2026-10-21):
  /vysledky/osobne-vozidla/mercedes-benz/?yearFrom=1971&yearTo=1996&page=2
Listings are embedded in __NEXT_DATA__ (pageProps.searchRecords.data).
"""
from __future__ import annotations

from ..http import dig, next_data, to_int, year_from
from .base import Source, new_listing

BASE = "https://www.autobazar.eu"
COUNTRY = {"Slovensko": "SK", "Česko": "CZ", "Česká republika": "CZ", "Maďarsko": "HU", "Rakúsko": "AT",
           "Poľsko": "PL", "Nemecko": "DE"}


def parse_page(html: str) -> tuple[list[dict], int]:
    data = next_data(html) or {}
    sr = dig(data, "props", "pageProps", "searchRecords", default={}) or {}
    out = []
    for r in sr.get("data", []) or []:
        loc = r.get("location") or {}
        parents = loc.get("parentNames") or []
        country = next((COUNTRY[p] for p in parents if p in COUNTRY), "SK")
        imgs = []
        for im in ([r.get("image")] if r.get("image") else []) + (r.get("images") or []):
            u = dig(im, "previewUrls", "record_premium") or dig(im, "previewUrls", "orig")
            if u and u not in imgs:
                imgs.append(u)
        user = r.get("user") or {}
        out.append(new_listing(
            "autobazar", r.get("id"),
            url=f"{BASE}/detail/{r.get('sefName')}/{r.get('id')}/",
            title=r.get("title"),
            make=r.get("brandValue"),
            model_raw=r.get("carModelValue"),
            price=to_int(r.get("priceCurrent") or r.get("finalPrice") or r.get("price")),
            currency="EUR",
            year=year_from(r.get("yearValue")),
            mileage_km=to_int(r.get("mileage")),
            fuel=r.get("fuelValue"),
            gearbox=r.get("gearboxValue"),
            power_kw=to_int(r.get("enginePower")),
            country=country,
            city=loc.get("name"),
            region=parents[1] if len(parents) > 1 else None,
            images=imgs,
            seller_type="dealer" if user.get("vatId") or dig(user, "authorizedDealer", "isAuthorized") else "private",
            seller_name=user.get("displayName"),
        ))
    return out, to_int(sr.get("total")) or 0


class Autobazar(Source):
    key = "autobazar"
    match_all = True   # make-level search: match against every model family of that make

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._done: set[str] = set()

    def search(self, q):
        if q.make in self._done:
            return
        self._done.add(q.make)
        y1, y2 = self.context["make_years"][q.make]
        for page in range(1, max(self.max_pages, 5) + 1):
            params = {"yearFrom": y1, "yearTo": y2}
            if page > 1:
                params["page"] = page
            items, total = parse_page(self.client.get(f"{BASE}/vysledky/osobne-vozidla/{q.make}/", params=params).text)
            yield from items
            if len(items) < 20 or page * 20 >= total:
                break
