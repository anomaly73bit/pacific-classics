"""Synthetic demo data so the website can be previewed without crawling.

Every demo listing is flagged `demo: true`, titled "[DEMO]" and uses a placeholder image;
links point to the real marketplace search page for that model, never to a fake ad.
"""
from __future__ import annotations

import random

from .knowledge import build_queries, load_models
from .sources.base import new_listing

CITIES = {
    "DE": [("Stuttgart", "70173"), ("München", "80331"), ("Hamburg", "20095"), ("Köln", "50667"), ("Berlin", "10115")],
    "AT": [("Wien", "1010"), ("Graz", "8010"), ("Linz", "4020")],
    "CZ": [("Praha", "11000"), ("Brno", "60200"), ("Plzeň", "30100")],
    "NL": [("Utrecht", "3511"), ("Eindhoven", "5611")],
    "BE": [("Antwerpen", "2000"), ("Liège", "4000")],
    "FR": [("Lyon", "69001"), ("Annecy", "74000")],
    "IT": [("Bolzano", "39100"), ("Milano", "20121")],
}
SRC_BY_COUNTRY = {"DE": ["autoscout24", "kleinanzeigen"], "AT": ["willhaben", "autoscout24"], "CZ": ["sauto"],
                  "NL": ["autoscout24"], "BE": ["autoscout24"], "FR": ["autoscout24"], "IT": ["autoscout24"]}
SEARCH_URL = {
    "autoscout24": "https://www.autoscout24.com/lst/{make}/{model}",
    "kleinanzeigen": "https://www.kleinanzeigen.de/s-autos/{make}-{model}/k0c216",
    "willhaben": "https://www.willhaben.at/iad/gebrauchtwagen/auto/gebrauchtwagenboerse?keyword={make}+{model}",
    "sauto": "https://www.sauto.cz/inzerce/osobni/{make}/{model}",
}
BASE_PRICE = {5: 9000, 4: 7500, 3: 4500}
EXTRAS = ["Scheckheft gepflegt", "1. Hand", "Garagenwagen", "H-Kennzeichen", "leichter Rost am Schweller",
          "TÜV neu", "Unfallfrei", "", "", "", "Motorschaden - Bastlerfahrzeug", "Automatik"]


def make_demo(n_per_model: int = 6, seed: int = 7):
    rnd = random.Random(seed)
    models = load_models()
    q_by_model = {}
    for q in build_queries(models):
        for mid in q.model_ids:
            q_by_model.setdefault(mid, q)
    raw = []
    for m in models:
        q = q_by_model[m.id]
        engines = [e.strip() for e in m.recommended_engines.split(",")]
        for i in range(n_per_model):
            country = rnd.choice(list(CITIES))
            city, zipc = rnd.choice(CITIES[country])
            src = rnd.choice(SRC_BY_COUNTRY[country])
            year = rnd.randint(m.year_from, min(m.year_to, 2005))
            km = rnd.choice([rnd.randint(90_000, 260_000), rnd.randint(250_000, 480_000), rnd.randint(30_000, 90_000)])
            price = int(BASE_PRICE.get(m.reliability, 6000) * rnd.uniform(0.45, 1.8) * (1.4 if "Porsche" in m.make or "SL" in m.model else 1))
            price = round(price, -2)
            extra = rnd.choice(EXTRAS)
            title = f"[DEMO] {m.make} {m.model} {rnd.choice(engines)} {extra}".strip()
            raw.append((new_listing(
                src, f"demo-{m.id}-{i}",
                url=SEARCH_URL[src].format(make=q.make, model=q.model),
                title=title, make=m.make, model_raw=f"{m.model} {m.chassis}",
                price=price if country != "CZ" else int(price * 25), currency="CZK" if country == "CZ" else "EUR",
                year=year, mileage_km=km, fuel=rnd.choice(["Diesel", "Petrol"]),
                gearbox="Automatic" if "Automatik" in extra else rnd.choice(["Manual", "Manual", "Automatic"]),
                country=country, city=city, zip=zipc,
                images=["img/placeholder.svg"] * rnd.randint(1, 6),
                seller_type=rnd.choice(["dealer", "private"]),
                description=f"Demo listing generated for preview. {extra}",
                demo=True,
            ), [m.id]))
    return raw, {m.id: m for m in models}
