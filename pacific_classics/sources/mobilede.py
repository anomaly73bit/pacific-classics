"""mobile.de — via the official Search API (requires a mobile.de dealer/API account).

mobile.de actively blocks scrapers, so this adapter only runs when
MOBILEDE_API_USER and MOBILEDE_API_PASSWORD are set in the environment.
Docs: https://services.mobile.de/manual/search-api.html
"""
from __future__ import annotations

import os
import re

from ..http import dig, to_int, year_from
from .base import Source, new_listing

API = "https://services.mobile.de"
JSON = {"Accept": "application/vnd.de.mobile.api+json"}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def parse_ads(data: dict) -> list[dict]:
    out = []
    for ad in data.get("ads", []) or []:
        addr = dig(ad, "seller", "address", default={}) or {}
        imgs = []
        for im in ad.get("images", []) or []:
            u = im.get("uri") or dig(im, "representations", -1, "url")
            if u:
                imgs.append(u if u.startswith("http") else "https://" + u.lstrip("/") + "_27.jpg")
        out.append(new_listing(
            "mobilede", ad.get("mobileAdId"),
            url=ad.get("detailPageUrl"),
            title=" ".join(filter(None, [ad.get("make"), ad.get("model"), ad.get("modelDescription")])),
            make=ad.get("make"),
            model_raw=" ".join(filter(None, [ad.get("model"), ad.get("modelDescription")])),
            price=to_int(dig(ad, "price", "consumerPriceGross")),
            currency=dig(ad, "price", "currency", default="EUR"),
            year=year_from(ad.get("firstRegistration")),
            mileage_km=to_int(ad.get("mileage")),
            fuel=ad.get("fuel"),
            gearbox=ad.get("gearbox"),
            power_kw=to_int(ad.get("power")),
            country=(addr.get("countryCode") or "DE").upper(),
            city=addr.get("city"),
            zip=addr.get("zipcode"),
            images=imgs,
            seller_type="dealer" if dig(ad, "seller", "type") == "DEALER" else "private",
            seller_name=dig(ad, "seller", "companyName"),
        ))
    return out


class MobileDe(Source):
    key = "mobilede"

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.auth = (os.environ.get("MOBILEDE_API_USER"), os.environ.get("MOBILEDE_API_PASSWORD"))
        self._makes = None

    def available(self):
        if not all(self.auth):
            return False, "no MOBILEDE_API_USER / MOBILEDE_API_PASSWORD set (official API only)"
        return True, ""

    def _ref(self, path):
        r = self.client.get(API + path, headers=JSON, auth=self.auth)
        return {_slug(v.get("description") or v.get("name")): v.get("key") for v in r.json().get("values", [])}

    def search(self, q):
        if self._makes is None:
            self._makes = self._ref("/refdata/classes/Car/makes")
        mk = self._makes.get(q.make)
        if not mk:
            return
        md = self._ref(f"/refdata/classes/Car/makes/{mk}/models").get(q.model)
        cls = f"refdata/classes/Car/makes/{mk}" + (f"/models/{md}" if md else "")
        for page in range(1, self.max_pages + 1):
            r = self.client.get(f"{API}/search-api/search", headers=JSON, auth=self.auth, params={
                "classification": cls, "firstRegistrationDate.min": f"{q.year_from}-01",
                "firstRegistrationDate.max": f"{q.year_to}-12", "page.number": page, "page.size": 100,
            })
            items = parse_ads(r.json())
            yield from items
            if len(items) < 100:
                break
