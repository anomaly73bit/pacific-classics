"""Pacific Classics command line.

    python -m pacific_classics crawl                 # crawl every enabled source, publish site/data
    python -m pacific_classics crawl --sources sauto --models w124 w201
    python -m pacific_classics demo                  # publish synthetic demo data
    python -m pacific_classics serve                 # preview the website on http://localhost:8000
"""
from __future__ import annotations

import argparse
import functools
import http.server
import logging

from .knowledge import ROOT, load_sources
from .pipeline import crawl, process, publish


def main():
    ap = argparse.ArgumentParser(prog="pacific_classics")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crawl", help="crawl marketplaces and publish site data")
    c.add_argument("--sources", nargs="*", help="only these sources (autoscout24 sauto willhaben kleinanzeigen mobilede)")
    c.add_argument("--models", nargs="*", help="only models whose id contains any of these strings, e.g. w124 volvo-240")
    c.add_argument("--ref-year", type=int, help="year used for historic-eligibility (default: current year)")
    sub.add_parser("demo", help="publish synthetic demo data")
    s = sub.add_parser("serve", help="preview the website locally")
    s.add_argument("--port", type=int, default=8000)
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if a.cmd == "crawl":
        res = crawl(a.sources, a.models)
        listings = process(res["raw"], res["models"], res["cfg"], res["report"], a.ref_year, verify=res.get("verify"))
        publish(listings, res["models"], res["report"])
    elif a.cmd == "demo":
        from .demo import make_demo
        raw, models = make_demo()
        report = {"sources": {}, "note": "demo data"}
        listings = process(raw, models, load_sources(), report, demo=True)
        publish(listings, models, report, demo=True)
    elif a.cmd == "serve":
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "site"))
        print(f"Pacific Classics → http://localhost:{a.port}")
        http.server.ThreadingHTTPServer(("", a.port), handler).serve_forever()


if __name__ == "__main__":
    main()
