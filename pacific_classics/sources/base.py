"""Common interface for marketplace adapters."""
from __future__ import annotations

from typing import Iterator

from ..http import PoliteClient
from ..knowledge import Query


def new_listing(source: str, sid, **kw) -> dict:
    """Normalised listing record. Every adapter yields these."""
    rec = {
        "id": f"{source}:{sid}",
        "source": source,
        "url": None,
        "title": None,
        "make": None,
        "model_raw": None,
        "price": None,          # in original currency
        "currency": "EUR",
        "year": None,
        "mileage_km": None,
        "fuel": None,
        "gearbox": None,
        "power_kw": None,
        "country": None,        # ISO-3166 alpha-2
        "city": None,
        "zip": None,
        "region": None,
        "images": [],
        "seller_type": None,    # dealer | private
        "seller_name": None,
        "description": None,
    }
    rec.update({k: v for k, v in kw.items() if v is not None})
    return rec


class Source:
    key = "base"

    def __init__(self, client: PoliteClient, cfg: dict, crawler_cfg: dict):
        self.client = client
        self.cfg = cfg
        self.max_pages = crawler_cfg.get("max_pages_per_query", 3)

    def available(self) -> tuple[bool, str]:
        return True, ""

    def search(self, q: Query) -> Iterator[dict]:
        raise NotImplementedError
