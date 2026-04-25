from __future__ import annotations

import base64
import hashlib
import json
import secrets
import string
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

OPENAI_AUTH_BASE_URL = "https://auth.openai.com"
OPENAI_CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_REDIRECT_URI = "http://localhost:1455/auth/callback"
OPENAI_SCOPE = "openid profile email offline_access"
OPENAI_ORIGINATOR = "openclaw"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def generate_pkce_verifier(length: int = 96) -> str:
    alphabet = string.ascii_letters + string.digits + "-._~"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_pkce_pair() -> tuple[str, str]:
    verifier = generate_pkce_verifier()
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    challenge = _b64url(digest)
    return verifier, challenge


def generate_state() -> str:
    return _b64url(secrets.token_bytes(24))


def build_authorize_url(state: str, code_challenge: str) -> str:
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": OPENAI_CODEX_CLIENT_ID,
            "redirect_uri": OPENAI_REDIRECT_URI,
            "scope": OPENAI_SCOPE,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "originator": OPENAI_ORIGINATOR,
        }
    )
    return f"{OPENAI_AUTH_BASE_URL}/oauth/authorize?{query}"


def parse_callback_input(user_input: str, expected_state: str) -> str:
    raw = user_input.strip()
    if not raw:
        raise ValueError("No callback value was provided.")

    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urllib.parse.urlparse(raw)
        query = urllib.parse.parse_qs(parsed.query)
        fragment = urllib.parse.parse_qs(parsed.fragment)
        code = (query.get("code") or fragment.get("code") or [None])[0]
        state = (query.get("state") or fragment.get("state") or [None])[0]

        if not code:
            raise ValueError("Callback URL is missing the authorization code.")
        if state and state != expected_state:
            raise ValueError("Callback state mismatch; aborting for safety.")
        return code

    return raw


def parse_json_object(text: str) -> dict[str, Any]:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Expected JSON object in OAuth response.")
    return payload


def sanitize_error_text(value: str) -> str:
    # Strip control chars so accidental terminal escapes from remote responses
    # do not affect copy/paste or rendering.
    cleaned = "".join(ch if (ord(ch) >= 32 and ord(ch) != 127) else " " for ch in value)
    return " ".join(cleaned.split())


def post_form(url: str, body: dict[str, str], timeout: float) -> dict[str, Any]:
    encoded = urllib.parse.urlencode(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        method="POST",
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return parse_json_object(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        safe_detail = sanitize_error_text(detail)
        raise RuntimeError(f"OAuth request failed ({exc.code}): {safe_detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OAuth request failed: {exc.reason}") from exc


def _resolve_token_expiry_epoch_seconds(token_response: dict[str, Any], access_token: str) -> int:
    expires_in = token_response.get("expires_in")
    now = int(datetime.now(tz=timezone.utc).timestamp())
    if isinstance(expires_in, (int, float)) and expires_in > 0:
        return now + int(expires_in)
    if isinstance(expires_in, str) and expires_in.isdigit():
        return now + int(expires_in)
    jwt_expiry = resolve_access_token_expiry_epoch_seconds(access_token)
    return jwt_expiry if jwt_expiry is not None else now


def exchange_authorization_code(code: str, code_verifier: str, timeout: float) -> dict[str, Any]:
    payload = post_form(
        f"{OPENAI_AUTH_BASE_URL}/oauth/token",
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": OPENAI_REDIRECT_URI,
            "client_id": OPENAI_CODEX_CLIENT_ID,
            "code_verifier": code_verifier,
        },
        timeout=timeout,
    )
    access, refresh = _extract_oauth_tokens(payload, require_refresh=True, context="OAuth exchange")
    payload["access_token"] = access
    payload["refresh_token"] = refresh
    payload["expires_epoch_seconds"] = _resolve_token_expiry_epoch_seconds(payload, access)
    return payload


def refresh_access_token(refresh_token: str, timeout: float) -> dict[str, Any]:
    payload = post_form(
        f"{OPENAI_AUTH_BASE_URL}/oauth/token",
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": OPENAI_CODEX_CLIENT_ID,
        },
        timeout=timeout,
    )
    access, returned_refresh = _extract_oauth_tokens(
        payload, require_refresh=False, context="OAuth refresh"
    )
    payload["access_token"] = access
    payload["refresh_token"] = returned_refresh or refresh_token
    payload["expires_epoch_seconds"] = _resolve_token_expiry_epoch_seconds(payload, access)
    return payload


def _extract_oauth_tokens(
    payload: dict[str, Any], *, require_refresh: bool, context: str
) -> tuple[str, str | None]:
    error = payload.get("error")
    if isinstance(error, str) and error.strip():
        description = payload.get("error_description")
        if isinstance(description, str) and description.strip():
            raise RuntimeError(f"{context} failed: {error.strip()} ({sanitize_error_text(description)})")
        raise RuntimeError(f"{context} failed: {error.strip()}")

    access = payload.get("access_token")
    if not isinstance(access, str) or not access.strip():
        access = payload.get("accessToken")
    if not isinstance(access, str) or not access.strip():
        keys = ", ".join(sorted(payload.keys()))
        raise RuntimeError(f"{context} response missing access token (keys: {keys or '<none>'}).")

    refresh: str | None = payload.get("refresh_token") if isinstance(payload.get("refresh_token"), str) else None
    if refresh is None and isinstance(payload.get("refreshToken"), str):
        refresh = payload["refreshToken"]

    if require_refresh and (not isinstance(refresh, str) or not refresh.strip()):
        keys = ", ".join(sorted(payload.keys()))
        raise RuntimeError(
            f"{context} response missing refresh token. "
            "This usually means the authorize scope did not include offline_access. "
            f"Response keys: {keys or '<none>'}."
        )

    return access.strip(), refresh.strip() if isinstance(refresh, str) else None


def decode_jwt_payload(access_token: str) -> dict[str, Any] | None:
    parts = access_token.split(".")
    if len(parts) != 3:
        return None
    body = parts[1]
    body += "=" * (-len(body) % 4)
    try:
        decoded = base64.urlsafe_b64decode(body.encode("ascii")).decode("utf-8")
        parsed = json.loads(decoded)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def resolve_access_token_expiry_epoch_seconds(access_token: str) -> int | None:
    payload = decode_jwt_payload(access_token)
    if not payload:
        return None
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and exp > 0:
        return int(exp)
    if isinstance(exp, str) and exp.isdigit():
        return int(exp)
    return None


def resolve_identity(access_token: str, fallback_email: str | None = None) -> dict[str, str | None]:
    payload = decode_jwt_payload(access_token) or {}
    auth = payload.get("https://api.openai.com/auth")
    profile = payload.get("https://api.openai.com/profile")

    account_id: str | None = None
    if isinstance(auth, dict):
        candidate = auth.get("chatgpt_account_id")
        if isinstance(candidate, str) and candidate.strip():
            account_id = candidate.strip()

    email: str | None = None
    if isinstance(profile, dict):
        profile_email = profile.get("email")
        if isinstance(profile_email, str) and profile_email.strip():
            email = profile_email.strip()
    if email is None and isinstance(fallback_email, str) and fallback_email.strip():
        email = fallback_email.strip()

    subject: str | None = None
    if isinstance(auth, dict):
        for key in ("chatgpt_account_user_id", "chatgpt_user_id", "user_id"):
            val = auth.get(key)
            if isinstance(val, str) and val.strip():
                subject = val.strip()
                break
    if subject is None:
        sub = payload.get("sub")
        if isinstance(sub, str) and sub.strip():
            subject = sub.strip()

    return {
        "account_id": account_id,
        "email": email,
        "subject": subject,
    }
