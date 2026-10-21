"""Offline tests: parsers on minimal fixtures, model matching, advisor rules.

Run: python -m pytest -q
"""
import json

from pacific_classics.advisor import advise, historic_status
from pacific_classics.knowledge import build_queries, load_models, match_listing
from pacific_classics.sources import autoscout24, kleinanzeigen, sauto, willhaben

MODELS = {m.id: m for m in load_models()}


def nd(obj):
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(obj)}</script></html>'


def test_knowledge_base_loads():
    assert len(MODELS) == 50
    qs = build_queries(list(MODELS.values()))
    shared = next(q for q in qs if q.make == "mercedes-benz" and q.model == "300")
    assert len(shared.model_ids) >= 3  # W123, W124, W126 share this query


def test_autoscout24_parser():
    html = nd({"props": {"pageProps": {"listings": [{
        "id": "abc", "url": "/offers/mercedes-benz-190-abc",
        "images": ["https://prod.pictures.autoscout24.net/listing-images/x.jpg/250x188.webp"],
        "price": {"priceFormatted": "€ 7,990"},
        "vehicle": {"make": "Mercedes-Benz", "model": "190", "modelVersionInput": "D 2.5", "transmission": "Manual"},
        "tracking": {"price": "7990", "mileage": "312000", "firstRegistration": "05-1989"},
        "location": {"countryCode": "de", "zip": "70173", "city": "Stuttgart"},
        "seller": {"type": "Dealer", "companyName": "Classic GmbH"}}]}}})
    [l] = autoscout24.parse_page(html)
    assert l["price"] == 7990 and l["year"] == 1989 and l["mileage_km"] == 312000
    assert l["country"] == "DE" and l["seller_type"] == "dealer"
    assert l["url"].startswith("https://www.autoscout24.com/offers/")
    assert l["images"][0].endswith("/720x540.webp")


def test_sauto_parser():
    data = {"results": [{"id": 123, "name": "Volvo 240 2.3", "price": 89000, "tachometer": 410000,
                         "manufacturing_date": "1988-01-01", "manufacturer_cb": {"seo_name": "volvo", "name": "Volvo"},
                         "model_cb": {"seo_name": "240", "name": "240"}, "locality": {"municipality": "Brno", "region": "Jihomoravský"},
                         "images": [{"url": "//d46-a.sdn.cz/img.jpg"}], "premise": None}]}
    [l] = sauto.parse_results(data)
    assert l["currency"] == "CZK" and l["year"] == 1988 and l["country"] == "CZ"
    assert l["images"][0].startswith("https://") and l["seller_type"] == "private"


def test_willhaben_parser():
    html = nd({"props": {"pageProps": {"searchResult": {"advertSummaryList": {"advertSummary": [{
        "id": "999", "description": "Mercedes 300D W124",
        "attributes": {"attribute": [
            {"name": "PRICE", "values": ["6500"]}, {"name": "YEAR_MODEL", "values": ["1991"]},
            {"name": "MILEAGE", "values": ["380000"]}, {"name": "LOCATION", "values": ["Graz"]},
            {"name": "POSTCODE", "values": ["8010"]}, {"name": "SEO_URL", "values": ["gebrauchtwagen/d/auto/x-999"]},
            {"name": "CAR_MODEL/MAKE", "values": ["Mercedes-Benz"]}, {"name": "ISPRIVATE", "values": ["1"]}]},
        "advertImageList": {"advertImage": [{"mainImageUrl": "https://cache.willhaben.at/mmo/1.jpg"}]}}]}}}}})
    [l] = willhaben.parse_page(html)
    assert l["price"] == 6500 and l["year"] == 1991 and l["city"] == "Graz"
    assert l["url"] == "https://www.willhaben.at/iad/gebrauchtwagen/d/auto/x-999"


def test_kleinanzeigen_parser():
    # structure of the live search page (2026-10-21), trimmed
    html = """<article class="flex justify-between p-medium" data-adid="42" data-href="/s-anzeige/mercedes-benz-190/42-216-8068">
      <div><script type="application/ld+json">{"title":"Mercedes-Benz 190 1-Hand","description":"Rentnerfahrzeug, Scheckheft","contentUrl":"https://img.kleinanzeigen.de/api/v1/prod-ads/images/f9/x?rule=$_59.AUTO"}</script>
      <a href="/s-anzeige/mercedes-benz-190/42-216-8068"><img src="https://img.kleinanzeigen.de/api/v1/prod-ads/images/f9/x?rule=$_2.AUTO"><div>20</div></a></div>
      <div><div><div><span>69181 Leimen</span></div><div><span>Heute, 11:32</span></div></div>
      <div class="flex flex-col"><h3><a href="/s-anzeige/mercedes-benz-190/42-216-8068">Mercedes-Benz 190 Rentnerfahrzeug 1-Hand</a></h3>
      <p class="mb-xsmall text-bodyRegular text-onSurfaceSubdued">Irrtümer vorbehalten</p>
      <div class="flex"><p class="my-xsmall text-title3 font-strong text-secondary">4.900 €</p><p class="line-through">5.500 €</p></div></div>
      <div><p class="flex"><span>79.400 km</span><span>EZ 02/1993</span></p></div></div></article>"""
    [l] = kleinanzeigen.parse_page(html, make_hint="Mercedes-Benz")
    assert l["price"] == 4900 and l["year"] == 1993 and l["mileage_km"] == 79400
    assert l["zip"] == "69181" and l["city"] == "Leimen" and "rule=$_59" in l["images"][0]
    assert l["url"] == "https://www.kleinanzeigen.de/s-anzeige/mercedes-benz-190/42-216-8068"


def test_kleinanzeigen_urls():
    assert kleinanzeigen.search_path("mercedes-benz", "190", 1982, 1993) == \
        "/s-autos/c216+autos.ez_i:1982%2C1993+autos.marke_s:mercedes_benz+autos.model_s:190"
    assert "k0c216" in kleinanzeigen.search_path("mercedes-benz", "g-klasse", 1979, 1996)


def test_modern_models_rejected():
    cands = [MODELS[i] for i in MODELS if i.startswith("mercedes-benz")]
    assert match_listing({"make": "Mercedes-Benz", "title": "Mercedes-Benz C-Klasse 250D", "year": 1995}, cands)[0] is None


def test_matching_disambiguates_shared_queries():
    cands = [MODELS[i] for i in MODELS if i.startswith("mercedes-benz")]
    m, _ = match_listing({"make": "Mercedes-Benz", "title": "Mercedes-Benz 300 D W124 Limousine", "year": 1990}, cands)
    assert m.id == "mercedes-benz-e-class-w124"
    m, _ = match_listing({"make": "Mercedes-Benz", "title": "Mercedes 300 SE W126", "year": 1988}, cands)
    assert m.id == "mercedes-benz-s-class-w126"
    m, _ = match_listing({"make": "Mercedes-Benz", "title": "Mercedes 190 E", "year": 2005}, cands)
    assert m is None  # outside production years


def test_historic_status():
    h = historic_status(1999, 2026)
    assert h["asi"] and not h["fiva"] and h["fiva_year"] == 2029
    h = historic_status(1990, 2026)
    assert h["fiva"]


def test_advisor_flags():
    m = MODELS["mercedes-benz-e-class-w124"]
    stats = {"count": 10, "median_price": 8000}
    base = {"title": "Mercedes 300D W124 Unfallfrei Scheckheft", "year": 1990, "mileage_km": 420000,
            "price_eur": 5000, "images": ["x"], "country": "DE", "seller_type": "private", "gearbox": "Manual"}
    codes = {a["code"] for a in advise(base, m, stats, 2026)["alerts"]}
    assert {"HIST_FIVA", "PRICE_DEAL", "ENGINE_GOOD", "KM_HIGH_OK", "KW_NO_ACCIDENT", "KW_HISTORY", "IMPORT_IT"} <= codes
    assert "KW_ACCIDENT" not in codes

    scam = dict(base, price_eur=2500, title="Mercedes E 300 W124 Motorschaden", gearbox="Automatik")
    codes = {a["code"] for a in advise(scam, m, stats, 2026)["alerts"]}
    assert {"PRICE_SUSPICIOUS", "KW_DEFECT", "AUTO_GEARBOX"} <= codes
