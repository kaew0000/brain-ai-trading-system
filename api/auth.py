"""
api/auth.py — P1-A Dashboard Authentication
============================================================
Two credential types, one role model.

  API Key    (X-API-Key header)       long-lived, operator-issued, meant
                                       for server-to-server / scripted
                                       clients.
  Bearer JWT (Authorization: Bearer)  short-lived, minted from an API key
                                       via POST /api/auth/token, meant for
                                       the browser dashboard session.
                                       Supports expiration + rotation.

Roles (ascending privilege): VIEWER < OPERATOR < ADMIN.
  VIEWER   read-only access to every GET /api/* route and every read-only
           /ws/* stream.
  OPERATOR VIEWER + may issue commands that change live trading state
           (POST /api/command, /ws/command — pause/resume, paper mode).
  ADMIN    reserved for future privileged actions (key management, config
           writes). Nothing in the current API needs it yet — not
           invented here, just reserved so the role ordering is stable.

Enforcement only runs when settings.API_AUTH_ENABLED is true. See
config/settings.py for why that defaults to False.
"""
from __future__ import annotations

import hmac
import secrets as _secrets
import time
import uuid
from dataclasses import dataclass
from enum import IntEnum

import jwt  # PyJWT
from fastapi import Request, WebSocket

from config.settings import settings
from utils.logger import get_logger

logger = get_logger("api.auth")


class Role(IntEnum):
    VIEWER = 1
    OPERATOR = 2
    ADMIN = 3

    @classmethod
    def from_str(cls, name: str) -> Role:
        try:
            return cls[name.strip().upper()]
        except (KeyError, AttributeError):
            raise ValueError(f"unknown role: {name!r}")


@dataclass
class AuthContext:
    principal: str            # masked API key, or JWT subject
    role: Role
    method: str                # "api_key" | "bearer" | "disabled"
    jti: str | None = None  # bearer tokens only


class AuthError(Exception):
    """Raised on any authentication/authorization failure. Carries the
    HTTP status the caller should respond with (401 vs 403)."""

    def __init__(self, status_code: int, reason: str):
        self.status_code = status_code
        self.reason = reason
        super().__init__(reason)


# ── Startup safety check ────────────────────────────────────────────────
# An empty JWT_SECRET with auth enabled would let anyone forge an ADMIN
# token. Don't silently sign with "" and don't hard-crash the process
# (that would violate "never remove working features" for anyone who
# flips the flag without reading the docs first) — generate a random
# ephemeral secret and make it impossible to miss in the logs instead.
if settings.API_AUTH_ENABLED and not settings.JWT_SECRET:
    settings.JWT_SECRET = _secrets.token_hex(32)
    logger.critical(
        "API_AUTH_ENABLED=true but JWT_SECRET is not set — generated a "
        "random ephemeral secret for THIS PROCESS ONLY. Bearer tokens "
        "will not survive a restart and won't validate against any other "
        "replica. Set JWT_SECRET in .env before running this in production."
    )
def _bootstrap_ephemeral_api_key() -> None:
    """Same failure mode as the JWT_SECRET check above, taken to its
    actual conclusion: logging CRITICAL and leaving API_KEYS empty does
    not "fail safe" — it fails *locked*, for the operator as much as
    anyone else, since bearer tokens can only be minted from an API key.
    Generate one ephemeral OPERATOR-role key so the dashboard stays
    reachable, and log it in full (the one deliberate exception to
    "never log credential values" elsewhere in this file — without it
    there is no other way in at all).

    Split into a function (called once below, at import time) rather
    than left as a bare module-level block so it can also be called
    directly by tests — api/app.py holds direct references to this
    module's exports, which importlib.reload() would desync.
    """
    if not (settings.API_AUTH_ENABLED and not settings.API_KEYS):
        return
    ephemeral_key = _secrets.token_urlsafe(32)
    settings.API_KEYS = {ephemeral_key: "operator"}
    logger.critical(
        f"API_AUTH_ENABLED=true but API_KEYS is empty — generated a random "
        f"ephemeral OPERATOR key for THIS PROCESS ONLY so the dashboard "
        f"isn't fully locked out: {ephemeral_key} | This key is NOT "
        f"persisted and will change on every restart — set API_KEYS in "
        f".env before running this in production."
    )


_bootstrap_ephemeral_api_key()


# ── API key lookup ──────────────────────────────────────────────────────

def _lookup_api_key(raw_key: str) -> Role | None:
    if not raw_key:
        return None
    for configured_key, role_name in settings.API_KEYS.items():
        # Constant-time compare to avoid leaking key material via timing.
        if hmac.compare_digest(configured_key, raw_key):
            try:
                return Role.from_str(role_name)
            except ValueError:
                logger.error(f"API_KEYS entry has an unknown role {role_name!r} — ignoring this key")
                return None
    return None


def _mask(raw_key: str) -> str:
    if len(raw_key) <= 8:
        return "***"
    return f"{raw_key[:4]}…{raw_key[-4:]}"


# ── Bearer JWTs ──────────────────────────────────────────────────────────

# jti -> expiry epoch. In-memory by design (same single-process assumption
# already used everywhere else in this file, e.g. _state / ConnectionManager
# in api/app.py) — doesn't survive a restart, which is fine since restart
# also invalidates every in-flight token's usefulness for a live dashboard
# session; the browser just re-authenticates.
_revoked_jti: dict[str, float] = {}


def _cleanup_revoked() -> None:
    now = time.time()
    for j in [j for j, exp in _revoked_jti.items() if exp < now]:
        _revoked_jti.pop(j, None)


def issue_token(role: Role, subject: str = "dashboard") -> dict:
    now = int(time.time())
    exp = now + settings.JWT_EXPIRY_MINUTES * 60
    jti = uuid.uuid4().hex
    # "typ": "access" — V16 Phase 4C. Distinguishes this from a refresh
    # token below (same secret signs both). See _decode_bearer()'s typ
    # check and the refresh-token section's own docstring.
    payload = {"sub": subject, "role": role.name, "typ": "access", "iat": now, "exp": exp, "jti": jti}
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
    return {"token": token, "role": role.name, "expires_at": exp, "jti": jti}


def issue_login_session(raw_key: str) -> dict | None:
    """POST /api/auth/token — exchange an API key for a full login
    session: a short-lived bearer token AND a longer-lived refresh
    token (V16 Phase 4C). Supersedes the old issue_token_for_api_key()
    helper, which did only the bearer half and had exactly one caller
    (api/app.py's auth_token() handler, updated in this phase) — folded
    in here rather than kept alongside it to avoid two near-identical
    "exchange a key for a token" entry points.

    Returns None if raw_key doesn't match any configured API key.
    Otherwise:
        {
          "token": ..., "role": ..., "expires_at": ..., "jti": ...,       # unchanged shape — JSON body, as before this phase
          "refresh_token": ..., "refresh_expires_at": ...,                 # NEW — api/app.py MUST set this as an
        }                                                                  # httpOnly cookie only, never in the JSON body.
    """
    role = _lookup_api_key(raw_key)
    if role is None:
        return None
    access = issue_token(role)
    refresh = issue_refresh_token(role)
    return {**access, "refresh_token": refresh["token"], "refresh_expires_at": refresh["expires_at"]}


def revoke_token(jti: str, exp: float) -> None:
    _revoked_jti[jti] = exp


def _decode_bearer(token: str) -> AuthContext:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise AuthError(401, "token expired")
    except jwt.InvalidTokenError:
        raise AuthError(401, "invalid token")

    # V16 Phase 4C: a refresh token is signed with the same secret as a
    # bearer token but must never work as one — it's meant to live only
    # in the httpOnly cookie, exchanged for a bearer token via POST
    # /api/auth/session, never presented directly as `Authorization:
    # Bearer`. Tokens issued before this phase carry no "typ" claim at
    # all; those are accepted (missing == legacy access token) since
    # they're already short-lived and age out naturally within one
    # JWT_EXPIRY_MINUTES window of this deploy.
    if payload.get("typ") == "refresh":
        raise AuthError(401, "refresh tokens cannot be used as a bearer token")

    _cleanup_revoked()
    jti = payload.get("jti")
    if jti and jti in _revoked_jti:
        raise AuthError(401, "token revoked")

    try:
        role = Role.from_str(payload.get("role", ""))
    except ValueError:
        raise AuthError(401, "token has an invalid role claim")

    return AuthContext(principal=payload.get("sub", "unknown"), role=role, method="bearer", jti=jti)


def rotate_token(bearer_token: str) -> dict:
    """POST /api/auth/rotate — revoke the presented token, issue a fresh one
    with the same role. Raises AuthError if the presented token isn't
    currently valid (expired/revoked/malformed tokens can't be rotated —
    get a new one from /api/auth/token instead)."""
    ctx = _decode_bearer(bearer_token)  # raises AuthError on any problem
    if ctx.jti:
        try:
            payload = jwt.decode(bearer_token, settings.JWT_SECRET, algorithms=["HS256"])
            revoke_token(ctx.jti, payload.get("exp", time.time() + 1))
        except jwt.InvalidTokenError:
            pass
    return issue_token(ctx.role, subject=ctx.principal)


# ── Refresh tokens (V16 Phase 4C — Dashboard Session Persistence) ────────
#
# Root cause this section fixes: the bearer JWT above is deliberately
# held in browser memory only (see dashboard_src/src/lib/api.ts's own
# docstring) — never localStorage/sessionStorage, so an XSS bug can't
# exfiltrate a long-lived stolen session. That's correct and unchanged.
# But it also means a page refresh wipes the token, forcing the
# operator to re-enter their API key every time — the dashboard was
# never actually meant to require that.
#
# A refresh token is a separate, longer-lived credential, delivered
# ONLY as an httpOnly cookie (api/app.py sets/reads it — this module
# never touches Request/Response/cookies directly, it only ever
# receives or returns raw token strings). httpOnly means page JS
# cannot read it under any circumstances, XSS included — so it doesn't
# reintroduce the exact risk the in-memory-only design was avoiding.
# POST /api/auth/session exchanges a valid refresh cookie for a fresh
# bearer token with no API key re-entry; the dashboard calls this once
# on load, silently, before falling back to showing the LOGIN button.
#
# Same in-memory revocation-registry pattern as _revoked_jti above —
# doesn't survive a process restart. That's an accepted characteristic
# of this whole file already (JWT_SECRET itself is ephemeral-per-process
# when left unset), not a new trade-off introduced here.

REFRESH_COOKIE_NAME = "brainbot_refresh"

_revoked_refresh_jti: dict[str, float] = {}


def _cleanup_revoked_refresh() -> None:
    now = time.time()
    for j in [j for j, exp in _revoked_refresh_jti.items() if exp < now]:
        _revoked_refresh_jti.pop(j, None)


def issue_refresh_token(role: Role, subject: str = "dashboard") -> dict:
    now = int(time.time())
    exp = now + settings.JWT_REFRESH_EXPIRY_DAYS * 86400
    jti = uuid.uuid4().hex
    payload = {"sub": subject, "role": role.name, "typ": "refresh", "iat": now, "exp": exp, "jti": jti}
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")
    return {"token": token, "expires_at": exp, "jti": jti}


def revoke_refresh_token(jti: str, exp: float) -> None:
    _revoked_refresh_jti[jti] = exp


def _decode_refresh(token: str) -> AuthContext:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise AuthError(401, "refresh token expired")
    except jwt.InvalidTokenError:
        raise AuthError(401, "invalid refresh token")

    if payload.get("typ") != "refresh":
        # Mirror image of _decode_bearer's own check — a bearer token
        # must not work here either. Unlike that check, this one is
        # strict with no legacy exemption: nothing issued before this
        # phase could ever have typ == "refresh".
        raise AuthError(401, "not a refresh token")

    _cleanup_revoked_refresh()
    jti = payload.get("jti")
    if jti and jti in _revoked_refresh_jti:
        raise AuthError(401, "refresh token revoked")

    try:
        role = Role.from_str(payload.get("role", ""))
    except ValueError:
        raise AuthError(401, "refresh token has an invalid role claim")

    return AuthContext(principal=payload.get("sub", "unknown"), role=role, method="refresh", jti=jti)


def refresh_session(refresh_token: str) -> dict:
    """POST /api/auth/session — exchange a valid refresh-token cookie for
    a fresh bearer token, no API key re-entry. Raises AuthError if the
    refresh token is missing/expired/revoked/malformed — the caller
    (api/app.py) turns that into a 401, which the frontend treats
    exactly like "never logged in" (show the LOGIN button).

    Rotates the refresh token on every use: the presented one is
    revoked and a new one issued alongside the new bearer token, so a
    given refresh-token cookie value is only ever valid for a single
    silent re-auth. This limits how long a leaked/stolen cookie value
    stays useful without requiring full reuse-detection/breach
    alerting (out of scope for this phase — see PATCH_NOTES.md).

    Returns the same shape as issue_login_session() above.
    """
    ctx = _decode_refresh(refresh_token)  # raises AuthError on any problem
    if ctx.jti:
        revoke_refresh_token(ctx.jti, time.time() + 1)
    access = issue_token(ctx.role, subject=ctx.principal)
    new_refresh = issue_refresh_token(ctx.role, subject=ctx.principal)
    return {**access, "refresh_token": new_refresh["token"], "refresh_expires_at": new_refresh["expires_at"]}


def revoke_refresh_cookie(raw_token: str | None) -> None:
    """POST /api/auth/logout — best-effort revoke of a refresh-token
    cookie value. Always safe to call, including with None/garbage: a
    missing or already-invalid cookie is a no-op, never an error —
    logout must never fail because the cookie was already gone."""
    if not raw_token:
        return
    try:
        payload = jwt.decode(
            raw_token, settings.JWT_SECRET, algorithms=["HS256"],
            options={"verify_exp": False},
        )
    except jwt.InvalidTokenError:
        return
    jti = payload.get("jti")
    if jti:
        revoke_refresh_token(jti, payload.get("exp", time.time() + 1))


def revoke_bearer_from_header(auth_header: str | None) -> None:
    """POST /api/auth/logout — same idea as revoke_refresh_cookie() for
    the caller's current bearer token (if any), so logout actually ends
    that token's validity too instead of just discarding the
    frontend's in-memory copy of a token that otherwise remains valid
    until its own (short) expiry either way."""
    token = _extract_bearer(auth_header)
    if not token:
        return
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=["HS256"],
            options={"verify_exp": False},
        )
    except jwt.InvalidTokenError:
        return
    jti = payload.get("jti")
    if jti:
        revoke_token(jti, payload.get("exp", time.time() + 1))


# ── Shared resolution (HTTP + WS) ────────────────────────────────────────

def _extract_bearer(header_value: str | None) -> str | None:
    if not header_value:
        return None
    parts = header_value.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def _resolve(api_key: str | None, bearer: str | None) -> AuthContext:
    if api_key:
        role = _lookup_api_key(api_key)
        if role is None:
            raise AuthError(401, "invalid API key")
        return AuthContext(principal=_mask(api_key), role=role, method="api_key")
    if bearer:
        return _decode_bearer(bearer)
    raise AuthError(401, "missing credentials (X-API-Key or Authorization: Bearer)")


def authenticate_request(request: Request) -> AuthContext:
    """Used by the HTTP auth middleware in api/app.py."""
    api_key = request.headers.get("x-api-key")
    bearer = _extract_bearer(request.headers.get("authorization"))
    return _resolve(api_key, bearer)


def _ws_credentials(ws: WebSocket) -> tuple[str | None, str | None]:
    api_key = ws.headers.get("x-api-key")
    # Browsers can't set custom headers on the native WebSocket handshake,
    # so a bearer token may also arrive as ?token=... on the connect URL.
    # Only bearer tokens fall back to the query string (short-lived) —
    # never API keys (long-lived, shouldn't end up in proxy/access logs).
    bearer = _extract_bearer(ws.headers.get("authorization")) or ws.query_params.get("token")
    return api_key, bearer


async def enforce_ws_role(ws: WebSocket, min_role: Role) -> AuthContext | None:
    """Call BEFORE accepting the connection (i.e. before manager.connect()).
    Returns the AuthContext on success. On failure, closes the handshake
    and returns None — the caller must return immediately without
    registering the connection with its ConnectionManager."""
    if not settings.API_AUTH_ENABLED:
        return AuthContext(principal="auth-disabled", role=Role.ADMIN, method="disabled")

    client = ws.client.host if ws.client else "?"
    path = ws.url.path
    try:
        api_key, bearer = _ws_credentials(ws)
        ctx = _resolve(api_key, bearer)
    except AuthError as exc:
        log_unauthorized(path, "WS", client, exc.reason)
        await ws.close(code=4401)
        return None

    if ctx.role < min_role:
        log_unauthorized(path, "WS", client, f"role {ctx.role.name} < required {min_role.name}")
        await ws.close(code=4403)
        return None
    return ctx


def log_unauthorized(path: str, method: str, client: str, reason: str) -> None:
    """Every rejected request is logged — never the credential value itself."""
    logger.warning(f"UNAUTHORIZED {method} {path} from {client}: {reason}")
