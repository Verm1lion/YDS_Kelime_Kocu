"""Telefondan (aynı Wi-Fi) erişim için PIN koruması."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import socket
import time

from . import db

_tokens: dict[str, float] = {}
_fails: dict[str, list[float]] = {}
TOKEN_TTL = 60 * 60 * 24 * 30
COOKIE = "yds_token"


def is_local(host: str | None) -> bool:
    return host in ("127.0.0.1", "::1", "localhost") or (host or "").startswith("127.")


def set_pin(pin: str) -> None:
    if not pin.isdigit() or not (4 <= len(pin) <= 8):
        raise ValueError("PIN 4-8 haneli rakam olmalı")
    salt = os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 120_000)
    db.set_setting("lan_pin_hash", salt.hex() + ":" + h.hex())
    _tokens.clear()


def has_pin() -> bool:
    return bool(db.get_setting("lan_pin_hash"))


def check_pin(pin: str, client: str) -> str | None:
    now = time.time()
    fl = [t for t in _fails.get(client, []) if now - t < 300]
    if len(fl) >= 5:
        raise PermissionError("Çok fazla hatalı deneme; 5 dakika bekle.")
    stored = db.get_setting("lan_pin_hash")
    if not stored:
        return None
    salt_hex, h_hex = stored.split(":")
    h = hashlib.pbkdf2_hmac("sha256", pin.encode(), bytes.fromhex(salt_hex), 120_000)
    if hmac.compare_digest(h.hex(), h_hex):
        tok = secrets.token_urlsafe(24)
        _tokens[tok] = now + TOKEN_TTL
        _fails.pop(client, None)
        return tok
    fl.append(now)
    _fails[client] = fl
    return None


def valid_token(tok: str | None) -> bool:
    if not tok:
        return False
    exp = _tokens.get(tok)
    if not exp or exp < time.time():
        return False
    return True


def lan_addresses() -> list[str]:
    out = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in out:
                out.append(ip)
    except OSError:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        if ip not in out and not ip.startswith("127."):
            out.insert(0, ip)
    except OSError:
        pass
    return out
