"""Offline machine translation of ad titles/descriptions into Italian.

Uses the free, open-source Argos Translate models (OpenNMT/CTranslate2) without the heavy
argostranslate package: ctranslate2 + sentencepiece only. Other languages go through English
(cs→en→it, de→en→it…). Translations are cached in data/translations.json, so each ad is
translated once. If models can't be downloaded, everything falls back to the original text.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import zipfile
from pathlib import Path

import requests

from .knowledge import ROOT

log = logging.getLogger("pacific.translate")
INDEX = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
MODELS_DIR = Path.home() / ".cache" / "pacific-argos"
CACHE = ROOT / "data" / "translations.json"

STOP = {
    "de": "und der die das mit für ist nicht ein eine sehr guter zustand neu bis tüv kein auto fahrzeug verkaufe",
    "nl": "en de het een met voor van niet zeer goede staat nieuwe apk auto te koop rijdt",
    "cs": "a s na je v se pro po velmi stav nové auto prodám servis bez veterán",
    "sk": "a s na je v sa pre po veľmi stav nové auto predám servis bez",
    "fr": "et le la les un une avec pour est très bon état neuf voiture vends",
    "es": "y el la los un una con para es muy buen estado nuevo coche vendo",
    "en": "and the with for is very good condition new car sale owner",
    "it": "e il la gli un una con per è molto buono stato nuovo auto vendo tagliandi",
    "pl": "i w z na jest bardzo stan nowy auto sprzedam",
    "hu": "és a az egy nagyon jó állapot új autó eladó",
}
STOP = {k: set(v.split()) for k, v in STOP.items()}
DEFAULT_LANG = {"kleinanzeigen": "de", "marktplaats": "nl", "2dehands": "nl"}
COUNTRY_LANG = {"DE": "de", "AT": "de", "LU": "de", "CH": "de", "NL": "nl", "BE": "nl", "FR": "fr", "ES": "es",
                "CZ": "cs", "SK": "sk", "PL": "pl", "HU": "hu", "IT": "it"}


def guess_lang(text: str, source: str | None = None, country: str | None = None) -> str:
    words = re.findall(r"[a-zäöüßčřšžýáíéěůúťďňľĺôàèéìòùç]+", (text or "").lower())
    scores = {k: sum(w in v for w in words) for k, v in STOP.items()}
    best = max(scores, key=scores.get)
    if scores[best] >= 2:
        return best
    if re.search(r"[řěů]", text or ""):
        return "cs"
    if re.search(r"[ľĺô]", text or ""):
        return "sk"
    if re.search(r"[äöüß]", text or ""):
        return "de"
    return DEFAULT_LANG.get(source) or COUNTRY_LANG.get(country or "", "en")


class _Model:
    def __init__(self, path: Path):
        import ctranslate2
        import sentencepiece as spm
        model_bin = next(path.rglob("model.bin"))
        sp_file = next(path.rglob("sentencepiece.model"), None) or next(path.rglob("*.model"))
        self.tr = ctranslate2.Translator(str(model_bin.parent), device="cpu", inter_threads=2, intra_threads=2)
        self.sp = spm.SentencePieceProcessor(model_file=str(sp_file))

    def translate(self, sentences: list[str]) -> list[str]:
        toks = [self.sp.encode(s, out_type=str) for s in sentences]
        res = self.tr.translate_batch(toks, beam_size=1, max_decoding_length=256, max_batch_size=32)
        return [self.sp.decode(r.hypotheses[0]).replace("▁", " ").strip() for r in res]


class Translator:
    def __init__(self, max_new: int = 4000):
        self.cache: dict[str, str] = {}
        self.used: set[str] = set()
        self.models: dict[tuple, _Model | None] = {}
        self.index: list | None = None
        self.max_new = max_new
        self.new = 0
        try:
            self.cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _index(self):
        if self.index is None:
            try:
                self.index = requests.get(INDEX, timeout=30).json()
            except Exception as e:  # noqa: BLE001
                log.warning("translation index unavailable: %s", e)
                self.index = []
        return self.index

    def _model(self, src: str, dst: str) -> _Model | None:
        key = (src, dst)
        if key in self.models:
            return self.models[key]
        target = MODELS_DIR / f"{src}_{dst}"
        try:
            if not any(target.rglob("model.bin")):
                pkg = next((p for p in self._index() if p["from_code"] == src and p["to_code"] == dst), None)
                if not pkg:
                    raise LookupError(f"no model {src}->{dst}")
                log.info("downloading translation model %s->%s", src, dst)
                data = requests.get(pkg["links"][0], timeout=300).content
                target.mkdir(parents=True, exist_ok=True)
                zipfile.ZipFile(io.BytesIO(data)).extractall(target)
            self.models[key] = _Model(target)
        except Exception as e:  # noqa: BLE001
            log.warning("translation model %s->%s unavailable: %s", src, dst, e)
            self.models[key] = None
        return self.models[key]

    def _run(self, text: str, src: str) -> str | None:
        chain = [(src, "it")] if any(p["from_code"] == src and p["to_code"] == "it" for p in self._index()) \
            else [(src, "en"), ("en", "it")] if src != "en" else [("en", "it")]
        sentences = [s for s in re.split(r"(?<=[.!?])\s+|\s+[|•]\s+|\n+", text) if s.strip()][:12]
        for a, b in chain:
            m = self._model(a, b)
            if not m:
                return None
            sentences = m.translate(sentences)
        return " ".join(sentences)

    def to_it(self, text: str | None, src: str) -> str | None:
        if not text or src == "it":
            return None
        k = hashlib.sha1(f"{src}:{text}".encode()).hexdigest()[:16]
        self.used.add(k)
        if k in self.cache:
            return self.cache[k]
        if self.new >= self.max_new:
            return None
        out = self._run(text, src)
        if out:
            self.new += 1
            self.cache[k] = out
        return out

    def save(self):
        keep = {k: v for k, v in self.cache.items() if k in self.used}
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(keep, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def translate_listings(listings: list[dict], max_new: int = 4000) -> dict:
    tr = Translator(max_new)
    done = 0
    for l in listings:
        lang = guess_lang(" ".join(filter(None, [l.get("title"), l.get("description")])), l.get("source"), l.get("country"))
        l["lang"] = lang
        if lang == "it":
            continue
        l["title_it"] = tr.to_it(l.get("title"), lang)
        l["description_it"] = tr.to_it(l.get("description"), lang)
        done += bool(l["title_it"])
    tr.save()
    return {"translated": done, "new_translations": tr.new, "cached": len(tr.cache)}
