"""AutoScout24 — pan-European marketplace (DE, AT, BE, NL, LU, FR, ES, IT).

Search pages embed their results as JSON in the Next.js `__NEXT_DATA__` script tag.
"""
from __future__ import annotations

import re

from ..http import dig, next_data, to_int, year_from
from .base import Source, new_listing

BASE = "https://www.autoscout24.com"
CY = {"D": "DE", "A": "AT", "I": "IT", "F": "FR", "B": "BE", "NL": "NL", "E": "ES", "L": "LU"}


def _big_image(u: str) -> str:
    return re.sub(r"/\d+x\d+\.(webp|jpg)$", r"/720x540.\1", u)


def parse_page(html: str) -> list[dict]:
    data = next_data(html) or {}
    out = []
    for it in dig(data, "props", "pageProps", "listings", default=[]) or []:
        v = it.get("vehicle", {}) or {}
        tr = it.get("tracking", {}) or {}
        loc = it.get("location", {}) or {}
        seller = it.get("seller", {}) or {}
        title = " ".join(filter(None, [v.get("make"), v.get("model"), v.get("modelVersionInput")]))
        url = it.get("url")
        out.append(new_listing(
            "autoscout24", it.get("id"),
            url=(BASE + url) if url and url.startswith("/") else url,
            title=title or None,
            make=v.get("make"),
            model_raw=" ".join(filter(None, [v.get("model"), v.get("modelVersionInput")])) or None,
            price=to_int(tr.get("price")) or to_int(dig(it, "price", "priceFormatted")),
            currency="EUR",
            year=year_from(tr.get("firstRegistration")),
            mileage_km=to_int(tr.get("mileage")) or to_int(v.get("mileageInKm")),
            fuel=v.get("fuel"),
            gearbox=v.get("transmission"),
            power_kw=to_int(v.get("powerInKw")) if v.get("powerInKw") else None,
            country=(loc.get("countryCode") or "").upper() or None,
            city=loc.get("city"),
            zip=loc.get("zip"),
            images=[_big_image(u) for u in (it.get("images") or []) if isinstance(u, str)],
            seller_type="dealer" if str(seller.get("type", "")).lower() == "dealer" else "private" if seller.get("type") else None,
            seller_name=seller.get("companyName") or seller.get("contactName"),
        ))
    return out


class AutoScout24(Source):
    key = "autoscout24"

    def search(self, q):
        cy = ",".join(c for c in self.cfg.get("countries", CY.keys()) if c in CY)
        for page in range(1, self.max_pages + 1):
            r = self.client.get(f"{BASE}/lst/{q.make}/{q.model}", params={
                "atype": "C", "cy": cy, "fregfrom": q.year_from, "fregto": q.year_to,
                "sort": "price", "desc": 0, "ustate": "N,U", "page": page,
            })
            items = parse_page(r.text)
            yield from items
            if len(items) < 19:
                break
