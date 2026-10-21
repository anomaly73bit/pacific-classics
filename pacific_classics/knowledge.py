"""Model knowledge base: loading models.yaml and matching listings to model families."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"


@dataclass
class Model:
    id: str
    make: str
    model: str
    chassis: str
    category: str
    year_from: int
    year_to: int
    recommended_engines: str
    strengths: str
    watch_out: str
    reliability: int
    queries: list[str]
    engine_good: list[re.Pattern] = field(default_factory=list)
    engine_bad: list[re.Pattern] = field(default_factory=list)
    engine_bad_note: str | None = None
    auto_gearbox_caution: bool = False
    high_mileage_ok: bool = False
    match_any: list[re.Pattern] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.make} {self.model} ({self.chassis})"

    def to_public(self) -> dict:
        return {
            "id": self.id, "make": self.make, "model": self.model, "chassis": self.chassis,
            "category": self.category, "years": [self.year_from, self.year_to],
            "recommended_engines": self.recommended_engines, "strengths": self.strengths,
            "watch_out": self.watch_out, "reliability": self.reliability,
            "engine_bad_note": self.engine_bad_note,
            "high_mileage_ok": self.high_mileage_ok,
        }


def _rx(items):
    return [re.compile(p, re.I) for p in (items or [])]


def norm_make(s: str | None) -> str:
    s = (s or "").lower().replace("ë", "e").replace("é", "e")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return {"mercedes": "mercedes-benz", "vw": "volkswagen", "landrover": "land-rover"}.get(s, s)


def load_models(path: Path | None = None) -> list[Model]:
    data = yaml.safe_load((path or CONFIG / "models.yaml").read_text(encoding="utf-8"))
    out = []
    for m in data["models"]:
        out.append(Model(
            id=m["id"], make=m["make"], model=str(m["model"]), chassis=m["chassis"],
            category=m["category"], year_from=m["years"][0], year_to=m["years"][1],
            recommended_engines=m["recommended_engines"], strengths=m["strengths"],
            watch_out=m["watch_out"], reliability=m["reliability"], queries=m["queries"],
            engine_good=_rx(m.get("engine_good")), engine_bad=_rx(m.get("engine_bad")),
            engine_bad_note=m.get("engine_bad_note"),
            auto_gearbox_caution=bool(m.get("auto_gearbox_caution")),
            high_mileage_ok=bool(m.get("high_mileage_ok")),
            match_any=_rx(m.get("match_any")),
        ))
    return out


@dataclass
class Query:
    """One marketplace search, shared by every model family that uses the same make|model slug."""
    make: str
    model: str
    year_from: int
    year_to: int
    model_ids: list[str]

    @property
    def keyword(self) -> str:
        return f"{self.make} {self.model}".replace("-", " ")


def build_queries(models: list[Model]) -> list[Query]:
    by_key: dict[str, Query] = {}
    for m in models:
        for q in m.queries:
            make, model = q.split("|", 1)
            if q not in by_key:
                by_key[q] = Query(make, model, m.year_from, m.year_to, [m.id])
            else:
                k = by_key[q]
                k.year_from = min(k.year_from, m.year_from)
                k.year_to = max(k.year_to, m.year_to)
                k.model_ids.append(m.id)
    return list(by_key.values())


# Modern models that share a make/number with our families (e.g. "C 250 D" vs W124 "250 D")
GLOBAL_EXCLUDE = re.compile(r"\b(cdi|crdi|tdci|dci|hdi|jtd|multijet|common.?rail|hybrid|elektro|electric|e-tron|plug-in)\b", re.I)
EXCLUDE_BY_MAKE = {k: re.compile(v, re.I) for k, v in {
    "mercedes-benz": r"\b(c|a|b|v|m|r|glk?|gla|glc|gle|gls|cla|cls|clk|slk|ml)-?\s?klasse\b|\bw(20[2-6]|21[0-3]|16[3-9]|22[0-3])\b|\b(clk|slk|cla|cls|gla|glc|gle|glk|ml|sprinter|vito|viano|citan|vaneo)\b|\b[abcv]\s?\d{3}\b",
    "volkswagen": r"golf\s?(4|iv|5|v|6|vi|7|vii|8)\b|passat\s?(b[5-9]|3c|cc)\b|polo\s?(9n|6r|aw)\b|\bt[5-7]\b|\b(tiguan|touran|sharan|amarok|caddy|up!?)\b",
    "bmw": r"\b(e4[6-9]|e[6-9]\d|f\d\d|g\d\d)\b|\b(x[1-7]|z4|i3|i8)\b",
    "volvo": r"\b(s40|s60|s80|v40|v50|v60|v90|xc\d\d|c30|c70)\b",
    "toyota": r"\b(yaris|auris|prius|aygo|rav ?4|verso|avensis)\b",
    "audi": r"\b(a[1-8]|q[2-8]|tt)\b",
}.items()}


def match_listing(listing: dict, candidates: list[Model]) -> tuple[Model | None, str]:
    """Pick the model family a listing belongs to.

    Returns (model, confidence) where confidence is 'high' | 'medium' | 'low'.
    A listing must have the right make and a production year inside the family's range.
    """
    text = " ".join(filter(None, [listing.get("make"), listing.get("model_raw"), listing.get("title")])).lower()
    year = listing.get("year")
    make = norm_make(listing.get("make"))
    if GLOBAL_EXCLUDE.search(text) or (make in EXCLUDE_BY_MAKE and EXCLUDE_BY_MAKE[make].search(text)):
        return None, "none"
    scored = []
    for m in candidates:
        if make and norm_make(m.make) != make:
            continue
        if not year or not (m.year_from <= year <= m.year_to):
            continue
        score = 0
        if m.chassis and any(c.strip().lower() in text for c in m.chassis.split("/") if len(c.strip()) >= 3):
            score += 3
        hits = sum(1 for rx in m.match_any if rx.search(text))
        score += min(hits, 2) * 2
        if score == 0:
            continue
        # tighter production windows are more specific
        score += max(0, 15 - (m.year_to - m.year_from)) / 15
        scored.append((score, m))
    if not scored:
        return None, "none"
    scored.sort(key=lambda t: t[0], reverse=True)
    best, top = scored[0][1], scored[0][0]
    ambiguous = len(scored) > 1 and scored[1][0] >= top - 0.5
    conf = "high" if top >= 4 and not ambiguous else "medium" if not ambiguous else "low"
    return best, conf


def load_sources() -> dict:
    return yaml.safe_load((CONFIG / "sources.yaml").read_text(encoding="utf-8"))
