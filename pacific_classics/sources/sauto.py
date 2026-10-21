"""Sauto.cz — the main Czech car marketplace. Uses the JSON API behind its search page."""
from __future__ import annotations

from ..http import dig, to_int, year_from
from .base import Source, new_listing

API = "https://www.sauto.cz/api/v1/items/search"
# Sauto slugs differ from AutoScout24 for a few makes/models
SLUG = {"mercedes-benz": "mercedes-benz", "volkswagen": "volkswagen", "land-rover": "land-rover"}


def _img(u: str) -> str:
    u = u if u.startswith("http") else "https:" + u
    return u if "?" in u else u + "?fl=res,800,600,3"


def parse_results(data: dict) -> list[dict]:
    out = []
    for it in data.get("results", []) or []:
        mk = dig(it, "manufacturer_cb", "seo_name") or ""
        md = dig(it, "model_cb", "seo_name") or ""
        loc = it.get("locality", {}) or {}
        premise = it.get("premise")
        out.append(new_listing(
            "sauto", it.get("id"),
            url=f"https://www.sauto.cz/osobni/detail/{mk}/{md}/{it.get('id')}",
            title=it.get("name"),
            make=dig(it, "manufacturer_cb", "name"),
            model_raw=" ".join(filter(None, [dig(it, "model_cb", "name"), it.get("additional_model_name")])) or None,
            price=to_int(it.get("price")),
            currency="CZK",
            year=year_from(it.get("manufacturing_date") or it.get("in_operation_date")),
            mileage_km=to_int(it.get("tachometer")),
            fuel=dig(it, "fuel_cb", "name"),
            gearbox=dig(it, "gearbox_cb", "name"),
            power_kw=to_int(it.get("engine_power")),
            country="CZ",
            city=loc.get("municipality") or loc.get("district"),
            region=loc.get("region"),
            images=[_img(i["url"]) for i in (it.get("images") or []) if isinstance(i, dict) and i.get("url")],
            seller_type="dealer" if premise else "private",
            seller_name=dig(premise, "name") if isinstance(premise, dict) else None,
        ))
    return out


class Sauto(Source):
    key = "sauto"

    def search(self, q):
        make = SLUG.get(q.make, q.make)
        limit = 50
        for page in range(self.max_pages):
            r = self.client.get(API, params={
                "limit": limit, "offset": page * limit, "category_id": 838,
                "manufacturer_model_seo": f"{make}:{q.model}",
                "manufacturing_date_from": f"{q.year_from}-01-01",
                "manufacturing_date_to": f"{q.year_to}-12-31",
            }, headers={"Accept": "application/json"})
            items = parse_results(r.json())
            yield from items
            if len(items) < limit:
                break
