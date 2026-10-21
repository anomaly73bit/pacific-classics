"""Admin data bundle: gzip + AES-256-GCM, key = PBKDF2-SHA256("user:password").

The public site only ships client-safe data. Everything the administrator needs (source sites,
original links, purchase prices, commission, market report) goes into site/data/admin.enc,
which the browser decrypts with WebCrypto after login. Credentials come from the
PACIFIC_ADMIN_USER / PACIFIC_ADMIN_PASSWORD environment variables (GitHub Actions secrets)
and are never written to the repository.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os

ITERATIONS = 250_000


def derive_key(user: str, password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", f"{user}:{password}".encode(), salt, ITERATIONS, dklen=32)


def encrypt_bundle(obj, user: str, password: str) -> dict:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, iv = os.urandom(16), os.urandom(12)
    data = gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode(), 9)
    ct = AESGCM(derive_key(user, password, salt)).encrypt(iv, data, None)
    b64 = lambda b: base64.b64encode(b).decode()
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iter": ITERATIONS, "salt": b64(salt), "iv": b64(iv), "data": b64(ct)}


def decrypt_bundle(env: dict, user: str, password: str):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    d = lambda k: base64.b64decode(env[k])
    raw = AESGCM(derive_key(user, password, d("salt"))).decrypt(d("iv"), d("data"), None)
    return json.loads(gzip.decompress(raw))
