"""Polite HTTP client: robots.txt, per-host rate limiting, retries."""
from __future__ import annotations

import json
import logging
import random
import re
import time
from urllib import robotparser
from urllib.parse import urlparse

import requests

log = logging.getLogger("pacific.http")


class Blocked(Exception):
    """The site refused us (robots.txt, 403, captcha page…)."""


def host_of(url: str) -> str:
    return urlparse(url).netloc


class PoliteClient:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": cfg["user_agent"],
            "Accept-Language": "en-GB,en;q=0.9,de;q=0.8,it;q=0.7,cs;q=0.6",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        })
        self._robots: dict[str, robotparser.RobotFileParser | None] = {}
        self.robots_info: dict[str, str] = {}
        self._last: dict[str, float] = {}

    def _allowed(self, url: str) -> bool:
        if not self.cfg.get("respect_robots_txt", True):
            return True
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = robotparser.RobotFileParser()
            try:
                r = self.s.get(base + "/robots.txt", timeout=self.cfg["timeout_seconds"])
                lines = r.text.splitlines() if r.status_code == 200 else []
                rp.parse(lines)
                star = r.text.find("User-agent: *")
                self.robots_info[base] = f"robots.txt HTTP {r.status_code}; '*' section: " + \
                    (r.text[star:star + 120].replace("\n", " / ") if star >= 0 else "none")
            except requests.RequestException as e:
                rp.parse([])
                self.robots_info[base] = f"robots.txt unreachable: {e}"
            self._robots[base] = rp
        rp = self._robots[base]
        return rp.can_fetch(self.cfg["user_agent"], url) if rp else True

    def _wait(self, host: str):
        lo, hi = self.cfg.get("delay_seconds", [3, 7])
        gap = random.uniform(lo, hi)
        last = self._last.get(host, 0)
        sleep = last + gap - time.monotonic()
        if sleep > 0:
            time.sleep(sleep)
        self._last[host] = time.monotonic()

    def get(self, url: str, *, params=None, headers=None, auth=None) -> requests.Response:
        full = requests.Request("GET", url, params=params).prepare().url
        if not self._allowed(full):
            raise Blocked(f"robots.txt disallows {full[:120]} — {self.robots_info.get(f'{urlparse(url).scheme}://{host_of(url)}', '')}")
        host = urlparse(url).netloc
        err = None
        for attempt in range(self.cfg.get("max_retries", 2) + 1):
            self._wait(host)
            try:
                r = self.s.get(url, params=params, headers=headers, auth=auth,
                               timeout=self.cfg["timeout_seconds"])
            except requests.RequestException as e:
                err = e
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (403, 429) or _looks_like_challenge(r):
                raise Blocked(f"{r.status_code} anti-bot response from {host}")
            if r.status_code >= 500:
                err = Exception(f"HTTP {r.status_code}")
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r
        raise err or Exception("request failed")


def _looks_like_challenge(r: requests.Response) -> bool:
    if "text/html" not in r.headers.get("Content-Type", ""):
        return False
    head = r.text[:4000].lower()
    return any(k in head for k in ("captcha-delivery", "cf-challenge", "px-captcha", "are you a robot", "access denied"))


NEXT_DATA = re.compile(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def next_data(html: str) -> dict | None:
    m = NEXT_DATA.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def dig(obj, *path, default=None):
    for p in path:
        if isinstance(obj, dict):
            obj = obj.get(p)
        elif isinstance(obj, list) and isinstance(p, int) and -len(obj) <= p < len(obj):
            obj = obj[p]
        else:
            return default
        if obj is None:
            return default
    return obj


def to_int(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    digits = re.sub(r"[^\d]", "", str(v))
    return int(digits) if digits else None


def year_from(v) -> int | None:
    if v is None:
        return None
    m = re.search(r"(19[5-9]\d|20[0-3]\d)", str(v))
    return int(m.group(1)) if m else None
