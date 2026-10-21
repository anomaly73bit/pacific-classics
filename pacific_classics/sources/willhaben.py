"""willhaben.at — Austria's largest classifieds site (private sellers + dealers)."""
from __future__ import annotations

from ..http import dig, next_data, to_int, year_from
from .base import Source, new_listing

SEARCH = "https://www.willhaben.at/iad/gebrauchtwagen/auto/gebrauchtwagenboerse"
IMG = "https://cache.willhaben.at/mmo/"


def _attrs(ad: dict) -> dict:
    out = {}
    for a in dig(ad, "attributes", "attribute", default=[]) or []:
        vals = a.get("values") or []
        out[a.get("name")] = vals if len(vals) > 1 else (vals[0] if vals else None)
    return out


def parse_page(html: str) -> list[dict]:
    data = next_data(html) or {}
    ads = dig(data, "props", "pageProps", "searchResult", "advertSummaryList", "advertSummary", default=[]) or []
    out = []
    for ad in ads:
        a = _attrs(ad)
        imgs = [i.get("mainImageUrl") for i in dig(ad, "advertImageList", "advertImage", default=[]) or [] if i.get("mainImageUrl")]
        if not imgs and a.get("ALL_IMAGE_URLS"):
            imgs = [IMG + p for p in str(a["ALL_IMAGE_URLS"]).split(";") if p]
        seo = a.get("SEO_URL")
        out.append(new_listing(
            "willhaben", ad.get("id"),
            url=f"https://www.willhaben.at/iad/{seo}" if seo else None,
            title=ad.get("description") or a.get("HEADING"),
            make=a.get("CAR_MODEL/MAKE"),
            model_raw=a.get("CAR_MODEL/MODEL"),
            price=to_int(a.get("PRICE")),
            currency="EUR",
            year=year_from(a.get("YEAR_MODEL")),
            mileage_km=to_int(a.get("MILEAGE")),
            fuel=a.get("ENGINE/FUEL_RESOLVED") or a.get("ENGINE/FUEL"),
            gearbox=a.get("TRANSMISSION_RESOLVED") or a.get("TRANSMISSION"),
            power_kw=to_int(a.get("ENGINE/EFFECT")),
            country="AT",
            city=a.get("LOCATION"),
            zip=a.get("POSTCODE"),
            region=a.get("STATE"),
            images=imgs,
            seller_type="dealer" if str(a.get("ISPRIVATE", "1")) == "0" else "private",
        ))
    return out


class Willhaben(Source):
    key = "willhaben"

    def search(self, q):
        for page in range(1, self.max_pages + 1):
            r = self.client.get(SEARCH, params={
                "keyword": q.keyword, "YEAR_MODEL_FROM": q.year_from, "YEAR_MODEL_TO": q.year_to,
                "rows": 90, "page": page, "sort": 3,
            })
            items = parse_page(r.text)
            yield from items
            if len(items) < 90:
                break
