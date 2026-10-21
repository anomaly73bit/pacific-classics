"""Probe candidate marketplaces from the crawler's real environment (GitHub runner).

For each site: does robots.txt allow our search URL for the crawler's user agent,
does the search page answer, and is there machine-readable data in it?
Writes probe/report.json.  Run: python scripts/probe_sites.py
"""
import json
import re
import sys
import time
from pathlib import Path
from urllib import robotparser
from urllib.parse import urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pacific_classics.knowledge import load_sources  # noqa: E402

UA = load_sources()["crawler"]["user_agent"]
SITES = {
    "autoscout24.com": "https://www.autoscout24.com/lst/mercedes-benz/190?atype=C&fregfrom=1982&fregto=1993",
    "autoscout24.de": "https://www.autoscout24.de/lst/mercedes-benz/190?atype=C&fregfrom=1982&fregto=1993",
    "mobile.de": "https://suchen.mobile.de/fahrzeuge/search.html?ms=17200%3B4%3B%3B&isSearchRequest=true",
    "willhaben.at": "https://www.willhaben.at/iad/gebrauchtwagen/auto/gebrauchtwagenboerse?keyword=mercedes+190",
    "kleinanzeigen.de": "https://www.kleinanzeigen.de/s-autos/c216+autos.ez_i:1982%2C1993+autos.marke_s:mercedes_benz+autos.model_s:190",
    "ebay.de": "https://www.ebay.de/sch/i.html?_nkw=mercedes+w201&_sacat=9801",
    "bazos.cz": "https://auto.bazos.cz/mercedes/?hledat=190",
    "bazos.sk": "https://auto.bazos.sk/mercedes/?hledat=190",
    "autobazar.eu": "https://www.autobazar.eu/vysledky/osobne-vozidla/mercedes-benz/",
    "subito.it": "https://www.subito.it/annunci-italia/vendita/auto/?q=mercedes+190",
    "marktplaats.nl": "https://www.marktplaats.nl/l/auto-s/mercedes-benz/q/190/",
    "2dehands.be": "https://www.2dehands.be/l/auto-s/mercedes-benz/q/190/",
    "otomoto.pl": "https://www.otomoto.pl/osobowe/mercedes-benz/w201",
    "olx.pl": "https://www.olx.pl/motoryzacja/samochody/mercedes-benz/q-190/",
    "autovit.ro": "https://www.autovit.ro/autoturisme/mercedes-benz/190",
    "hasznaltauto.hu": "https://www.hasznaltauto.hu/szemelyauto/mercedes-benz/190",
    "njuskalo.hr": "https://www.njuskalo.hr/auti/mercedes-benz-190",
    "leboncoin.fr": "https://www.leboncoin.fr/recherche?category=2&text=mercedes%20190",
    "lacentrale.fr": "https://www.lacentrale.fr/listing?makesModelsCommercialNames=MERCEDES%3A190",
    "coches.net": "https://www.coches.net/mercedes-benz/190/segunda-mano/",
    "wallapop.com": "https://es.wallapop.com/app/search?keywords=mercedes%20190&category_ids=100",
    "car.gr": "https://www.car.gr/classifieds/cars/?q=mercedes+190",
    "blocket.se": "https://www.blocket.se/annonser/hela_sverige/fordon/bilar?q=mercedes+190",
    "finn.no": "https://www.finn.no/car/used/search.html?q=mercedes+190",
    "tutti.ch": "https://www.tutti.ch/de/q/autos?query=mercedes%20190",
    "autoscout24.ch": "https://www.autoscout24.ch/de/s/mo-190/mercedes-benz",
    "classic-trader.com": "https://www.classic-trader.com/uk/cars/search?q=mercedes+190",
    "carandclassic.com": "https://www.carandclassic.com/search?query=mercedes%20190",
    "classicdriver.com": "https://www.classicdriver.com/en/cars?search=mercedes%20190",
    "donedeal.ie": "https://www.donedeal.ie/cars/Mercedes-Benz/190",
}

s = requests.Session()
s.headers.update({"User-Agent": UA, "Accept-Language": "en,de;q=0.8"})
out = {}
for name, url in SITES.items():
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    rec = {"url": url}
    try:
        r = s.get(base + "/robots.txt", timeout=20)
        rec["robots_status"] = r.status_code
        rp = robotparser.RobotFileParser()
        rp.parse(r.text.splitlines() if r.status_code == 200 else [])
        rec["robots_allows_search"] = rp.can_fetch(UA, url)
        i = r.text.find("User-agent: *")
        rec["robots_star"] = r.text[i:i + 200] if i >= 0 else None
    except Exception as e:  # noqa: BLE001
        rec["robots_error"] = str(e)[:200]
    time.sleep(2)
    try:
        r = s.get(url, timeout=25)
        h = r.text
        rec.update({
            "status": r.status_code, "bytes": len(h), "final_url": r.url[:200],
            "next_data": "__NEXT_DATA__" in h, "json_ld": h.count("application/ld+json"),
            "challenge": bool(re.search(r"captcha|cf-challenge|datadome|px-captcha|are you a robot|access denied", h[:20000], re.I)),
            "title": (re.search(r"<title[^>]*>(.*?)</title>", h, re.S | re.I) or [None, ""])[1].strip()[:100],
        })
    except Exception as e:  # noqa: BLE001
        rec["error"] = str(e)[:200]
    out[name] = rec
    print(name, rec.get("robots_allows_search"), rec.get("status"), rec.get("challenge"), rec.get("bytes"), flush=True)
    time.sleep(2)

Path("probe").mkdir(exist_ok=True)
Path("probe/report.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
