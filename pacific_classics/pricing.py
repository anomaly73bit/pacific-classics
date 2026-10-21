"""Customer price ladder (config/business.yaml)."""
from __future__ import annotations

import math
from functools import lru_cache

import yaml

from .knowledge import CONFIG


@lru_cache(maxsize=1)
def config() -> dict:
    return yaml.safe_load((CONFIG / "business.yaml").read_text(encoding="utf-8"))


def _rate(eur: float) -> float:
    for top, rate in config()["tiers"]:
        if top is None or eur <= top:
            return rate
    return config()["tiers"][-1][1]


def _raw(eur: float) -> float:
    return eur + max(config()["minimum_fee"], eur * _rate(eur))


def client_price(eur: int | None) -> int | None:
    """Price shown to customers for a car bought at `eur`."""
    if not eur:
        return None
    floor = 0.0
    for top, _ in config()["tiers"]:
        if top is None or eur <= top:
            break
        floor = _raw(top)
    step = config()["round_to"]
    return int(math.ceil(max(_raw(eur), floor) / step) * step)
