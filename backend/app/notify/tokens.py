"""Notifications - one signed, single-purpose token: the phone's "it arrived" receipt.

A service worker cannot read the app's login, so the push payload carries a token that lets it say, for ONE notification and ONE purpose, "this
reached the phone". base64url('nid|ack|exp') . base64url(HMAC-SHA256[:16]) - about 55 bytes, good for 24 hours. The key is derived from the
session secret with its own purpose string, so a My Day action token can never be replayed here (or the reverse).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

from .. import auth

_PURPOSE = b"notify-ack-v1"


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _ub64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _key() -> bytes:
    return hmac.new(auth._SECRET.encode(), _PURPOSE, hashlib.sha256).digest()


def make_ack(nid: int, ttl: int = 24 * 3600, now: float | None = None) -> str:
    body = f"{int(nid)}|ack|{int((now if now is not None else time.time()) + ttl)}".encode()
    return _b64(body) + "." + _b64(hmac.new(_key(), body, hashlib.sha256).digest()[:16])


def read_ack(token, now: float | None = None) -> int | None:
    """The notification id if the token is genuine, unexpired and an ack token; otherwise None. Constant-time compare; never raises."""
    try:
        b, sig = str(token).split(".", 1)
        body = _ub64(b)
        if not hmac.compare_digest(_b64(hmac.new(_key(), body, hashlib.sha256).digest()[:16]), sig):
            return None
        nid, purpose, exp = body.decode().split("|")
        if purpose != "ack" or int(exp) < (now if now is not None else time.time()):
            return None
        return int(nid)
    except Exception:
        return None
