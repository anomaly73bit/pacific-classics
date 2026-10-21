"""Polite HTTP client: robots.txt, per-host rate limiting, retries."""
from __future__ import annotations

import json
import logging
import random
import re
import time
from urllib.parse import urlparse

import requests

log = logging.getLogger("pacific.http")


class Robots:
    """robots.txt per RFC 9309: groups by user-agent, '*' and '$' patterns, longest match wins, Allow wins ties."""

    def __init__(self, text: str):
        self.groups: list[tuple[list[str], list[tuple[bool, str]]]] = []
        agents, rules, last_was_agent = [], [], False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if not last_was_agent and (agents or rules):
                    self.groups.append((agents, rules))
                    agents, rules = [], []
                agents.append(v.lower())
                last_was_agent = True
            elif k in ("allow", "disallow"):
                last_was_agent = False
                if agents:
                    rules.append((k == "allow", v))
        if agents:
            self.groups.append((agents, rules))

    def _rules_for(self, ua: str):
        token = re.sub(r"[^a-z0-9_-].*$", "", ua.lower().split("compatible;")[-1].strip()) or ua.lower()
        best, best_len = None, -1
        for agents, rules in self.groups:
            for a in agents:
                if a != "*" and a in token and len(a) > best_len:
                    best, best_len = rules, len(a)
        if best is not None:
            return best
        merged = [r for agents, rules in self.groups if "*" in agents for r in rules]
        return merged

    @staticmethod
    def _match(pattern: str, path: str) -> bool:
        if not pattern:
            return False
        rx = "^" + re.escape(pattern).replace(r"\*", ".*")
        rx = rx[:-2] + "$" if rx.endswith(r"\$") else rx
        return re.match(rx, path) is not None

    def allowed(self, ua: str, url: str) -> bool:
        p = urlparse(url)
        path = (p.path or "/") + (("?" + p.query) if p.query else "")
        verdict, length = True, -1
        for allow, pat in self._rules_for(ua):
            if self._match(pat, path) and (len(pat) > length or (len(pat) == length and allow)):
                verdict, length = allow, len(pat)
        return verdict


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
        self._robots: dict[str, Robots] = {}
        self.robots_info: dict[str, str] = {}
        self._last: dict[str, float] = {}

    def _allowed(self, url: str) -> bool:
        if not self.cfg.get("respect_robots_txt", True):
            return True
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self._robots:
            rp = Robots("")
            try:
                r = self.s.get(base + "/robots.txt", timeout=self.cfg["timeout_seconds"])
                lines = r.text.splitlines() if r.status_code == 200 else []
                rp = Robots("\n".join(lines))
                star = r.text.find("User-agent: *")
                self.robots_info[base] = f"robots.txt HTTP {r.status_code}; '*' section: " + \
                    (r.text[star:star + 120].replace("\n", " / ") if star >= 0 else "none")
            except requests.RequestException as e:
                self.robots_info[base] = f"robots.txt unreachable: {e}"
            self._robots[base] = rp
        rp = self._robots[base]
        return rp.allowed(self.cfg["user_agent"], url)

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
            if r.status_code == 404:
                return r          # unknown model page: the parser simply finds nothing
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
