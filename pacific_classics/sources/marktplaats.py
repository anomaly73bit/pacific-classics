"""Marktplaats.nl (Netherlands) and 2dehands.be (Belgium) — same Adevinta platform.

Their year filter only exists client-side (the JSON API behind it is disallowed in robots.txt),
so each model family is searched by a specific keyword, usually its chassis code
(e.g. "w124", "e30", "240"), and the matcher keeps only cars in the right production years.
Results are in __NEXT_DATA__: pageProps.searchRequestAndResponse.listings (checked 2026-10-21).
"""
from __future__ import annotations

import re

from ..http import dig, next_data, to_int, year_from
from .base import Source, new_listing

SITES = {
    "marktplaats": {"base": "https://www.marktplaats.nl", "cat": "auto-s", "country": "NL"},
    "2dehands": {"base": "https://www.2dehands.be", "cat": "autos", "country": "BE"},
}
MAKE_SLUG = {"land-rover": "land-rover", "mercedes-benz": "mercedes-benz", "citroen": "citroen", "lada": "lada"}


def keywords_for(model) -> list[str]:
    """Search words for a family: chassis code for Mercedes/BMW (W124, E30…), else each model name."""
    if model.make in ("Mercedes-Benz", "BMW"):
        codes = [c.strip().lower() for c in re.split(r"[/,]", model.chassis) if re.fullmatch(r"\s*[A-Z]\d{2,3}\s*", c)]
        if codes:
            return codes
    names = [re.sub(r"\(.*?\)", "", n).strip().lower() for n in model.model.split("/")]
    names = [re.sub(r"\s+(i{1,3}|iv)$", "", n) for n in names if not re.fullmatch(r"i{1,3}|iv|\d", n)]
    return list(dict.fromkeys(n for n in names if n)) or [model.model.lower()]


def parse_page(html: str, site: str) -> list[dict]:
    cfg = SITES[site]
    data = next_data(html) or {}
    out = []
    for it in dig(data, "props", "pageProps", "searchRequestAndResponse", "listings", default=[]) or []:
        attrs = {a.get("key"): a.get("value") for a in it.get("attributes", []) or []}
        pics = it.get("pictures") or []
        imgs = [p.get("extraExtraLargeUrl") or p.get("largeUrl") for p in pics if p.get("largeUrl")]
        if not imgs:
            imgs = ["https:" + u if u.startswith("//") else u for u in it.get("imageUrls", []) or []]
        loc = it.get("location") or {}
        price = dig(it, "priceInfo", "priceCents")
        verticals = it.get("verticals") or []
        out.append(new_listing(
            site, it.get("itemId"),
            url=cfg["base"] + it["vipUrl"] if it.get("vipUrl") else None,
            title=it.get("title"),
            make=verticals[0].replace("-", " ").title() if verticals else None,
            model_raw=attrs.get("model"),
            price=int(price / 100) if price else None,
            currency="EUR",
            year=year_from(attrs.get("constructionYear")),
            mileage_km=to_int(attrs.get("mileage")),
            fuel=attrs.get("fuel"),
            gearbox=attrs.get("transmission"),
            country="BE" if loc.get("countryName") in ("België", "Belgique", "Belgium") else
                    "NL" if loc.get("countryName") in ("Nederland", "Netherlands") else cfg["country"],
            city=loc.get("cityName"),
            images=imgs,
            seller_type="dealer" if dig(it, "sellerInformation", "sellerLogoUrl") else "private",
            seller_name=dig(it, "sellerInformation", "sellerName"),
            description=(it.get("categorySpecificDescription") or it.get("description") or "")[:400] or None,
        ))
    return out


class _Adevinta(Source):
    site = ""
    match_all = True

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._done: set[str] = set()

    def search(self, q):
        cfg = SITES[self.site]
        for mid in q.model_ids:
            if mid in self._done:
                continue
            self._done.add(mid)
            m = self.context["models"][mid]
            make = MAKE_SLUG.get(q.make, q.make)
            for kw in keywords_for(m):
                kw = re.sub(r"[^a-z0-9]+", "-", kw).strip("-")
                for page in range(1, self.max_pages + 1):
                    path = f"/l/{cfg['cat']}/{make}/q/{kw}/" + (f"p/{page}/" if page > 1 else "")
                    items = parse_page(self.client.get(cfg["base"] + path).text, self.site)
                    yield from items
                    if len(items) < 30:
                        break


class Marktplaats(_Adevinta):
    key = site = "marktplaats"


class Tweedehands(_Adevinta):
    key = site = "2dehands"
