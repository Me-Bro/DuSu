"""My Day - Web Push: VAPID keys, the sender, subscription checks, and the signed one-action tokens (DUSU_GOALS_PLAN.md §6.3, §7).

Push is OPT-IN and best-effort: the in-app reminder card is the guaranteed channel. If `pywebpush` cannot be imported the module reports
"unavailable" and everything else keeps working (the import gate stays green). A push service accepting a message is recorded as exactly
that - "accepted" - never as "seen".
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlparse

from .. import auth, db

try:                                            # optional dependency: without it the planner runs in-app only
    from pywebpush import WebPushException, webpush
    from py_vapid import Vapid
    AVAILABLE = True
except Exception:                               # pragma: no cover - exercised only where the packages are missing
    WebPushException = Exception                # type: ignore[assignment,misc]
    webpush = None                              # type: ignore[assignment]
    Vapid = None                                # type: ignore[assignment]
    AVAILABLE = False

SUBJECT = "mailto:support@ranabrothers.online"
TTL = 2 * 3600
TIMEOUT = 8
# A subscription endpoint is a URL the SERVER will POST to: only the real push services are accepted (no SSRF through a crafted endpoint).
PUSH_HOSTS = ("fcm.googleapis.com", "push.services.mozilla.com", "push.apple.com", "notify.windows.com", "push.api.chrome.google.com")

_keys: tuple[str, str] | None = None            # (public, private-raw), both base64url


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _ub64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# ----------------------------------------------------------------------------- VAPID keys
def _generate() -> tuple[str, str]:
    from cryptography.hazmat.primitives import serialization
    v = Vapid()
    v.generate_keys()
    priv = v.private_key.private_numbers().private_value.to_bytes(32, "big")
    pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _b64(pub), _b64(priv)


async def vapid_keys() -> tuple[str, str] | None:
    """(public, private) - from the environment if set, else generated ONCE and kept in the settings table (a P-256 key fits its 255-char
    column), so a container rebuild never invalidates the learners' subscriptions. None when push is unavailable."""
    global _keys
    if not AVAILABLE:
        return None
    if _keys:
        return _keys
    pub, priv = os.environ.get("VAPID_PUBLIC_KEY", ""), os.environ.get("VAPID_PRIVATE_KEY", "")
    if not (pub and priv):
        pub, priv = await db.get_setting("vapid_pub", ""), await db.get_setting("vapid_priv", "")
        if not (pub and priv):
            pub, priv = await asyncio.to_thread(_generate)
            again = await db.get_setting("vapid_pub", "")            # another process may have won the race: keep the stored one
            if again:
                pub, priv = again, await db.get_setting("vapid_priv", "")
            else:
                await db.set_setting("vapid_pub", pub)
                await db.set_setting("vapid_priv", priv)
    _keys = (pub, priv) if (pub and priv) else None
    return _keys


# ----------------------------------------------------------------------------- subscriptions
def valid_endpoint(url) -> bool:
    if not isinstance(url, str) or not (20 <= len(url) <= 700):
        return False
    u = urlparse(url)
    host = (u.hostname or "").lower()
    return u.scheme == "https" and not u.username and not u.password and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


def clean_subscription(body) -> dict | None:
    """{endpoint, keys:{p256dh, auth}} from the browser's PushSubscription JSON -> a checked dict, or None."""
    if not isinstance(body, dict):
        return None
    ks = body.get("keys") if isinstance(body.get("keys"), dict) else {}
    ep, p256, au = body.get("endpoint"), ks.get("p256dh"), ks.get("auth")
    if not valid_endpoint(ep) or not isinstance(p256, str) or not isinstance(au, str):
        return None
    try:
        if len(_ub64(p256)) != 65 or not (8 <= len(_ub64(au)) <= 32):
            return None
    except Exception:
        return None
    return {"endpoint": ep, "p256dh": p256, "auth": au}


# ----------------------------------------------------------------------------- the payload
LABELS = {"en": {"done": "Done", "later": "Later", "skip": "Skip", "hidden": "You have a reminder"},
          "hi": {"done": "हो गया", "later": "बाद में", "skip": "छोड़ो", "hidden": "तुम्हारा एक reminder है"}}


def build_payload(rid: int, title: str, body: str, lang: str, hide: bool, tokens: dict | None) -> bytes:
    """The encrypted message (well under the 4 KB limit). `tokens` = {done, later, skip}: single-purpose signed tokens, because a service
    worker cannot read the app's login."""
    lb = LABELS["hi" if lang == "hi" else "en"]
    p = {"title": "DuSu", "body": lb["hidden"] if hide else (title if not body else f"{title} - {body}"[:200]), "tag": f"pl{rid}",
         "data": {"rid": rid, "url": f"/my-day?r={rid}", "act": tokens or {}},
         "actions": [{"action": a, "title": lb[a]} for a in ("done", "later", "skip")] if tokens else []}
    return json.dumps(p, ensure_ascii=False).encode("utf-8")


# ----------------------------------------------------------------------------- sending
def _send_sync(sub: dict, payload: bytes, keys: tuple[str, str]) -> tuple[str, int]:
    try:
        v = Vapid.from_raw(keys[1].encode())
        webpush(subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}}, data=payload,
                vapid_private_key=v, vapid_claims={"sub": SUBJECT}, ttl=TTL, timeout=TIMEOUT, headers={"Urgency": "high"})
        return "ok", 201
    except WebPushException as e:                                            # the push service answered
        code = getattr(getattr(e, "response", None), "status_code", 0) or 0
        if code in (404, 410):
            return "gone", code                                              # the subscription is dead - prune it
        if code in (401, 403):
            return "error", code
        return "transient", code                                             # 429 / 5xx / unknown: retry later
    except Exception:                                                        # timeout, DNS, TLS ... - never raise out of the loop
        return "transient", 0


async def send(sub: dict, payload: bytes) -> tuple[str, int]:
    """('ok' | 'gone' | 'transient' | 'error', http status). The blocking library call runs in a worker thread."""
    keys = await vapid_keys()
    if not (AVAILABLE and keys):
        return "unavailable", 0
    return await asyncio.to_thread(_send_sync, sub, payload, keys)


# ----------------------------------------------------------------------------- one-action tokens
_PURPOSE = b"planner-action-v1"


def _key() -> bytes:
    return hmac.new(auth._SECRET.encode(), _PURPOSE, hashlib.sha256).digest()


def make_token(rid: int, action: str, ttl: int = 24 * 3600, now: float | None = None) -> str:
    """base64url('rid|action|exp') . base64url(HMAC[:16]) - ~60 bytes, good for one reminder and one action, 24 hours."""
    body = f"{int(rid)}|{action}|{int((now if now is not None else time.time()) + ttl)}".encode()
    return _b64(body) + "." + _b64(hmac.new(_key(), body, hashlib.sha256).digest()[:16])


def read_token(token, now: float | None = None) -> tuple[int, str] | None:
    """(rid, action) if the token is genuine and unexpired, else None. Constant-time compare; malformed input never raises."""
    try:
        b, sig = str(token).split(".", 1)
        body = _ub64(b)
        if not hmac.compare_digest(_b64(hmac.new(_key(), body, hashlib.sha256).digest()[:16]), sig):
            return None
        rid, action, exp = body.decode().split("|")
        if action not in ("done", "later", "skip") or int(exp) < (now if now is not None else time.time()):
            return None
        return int(rid), action
    except Exception:
        return None
