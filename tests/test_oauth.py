from __future__ import annotations

import base64
import json

import pytest

from codex_usage.oauth import (
    build_authorize_url,
    decode_jwt_payload,
    _extract_oauth_tokens,
    parse_callback_input,
    resolve_access_token_expiry_epoch_seconds,
    resolve_identity,
)


def _jwt(payload: dict[str, object]) -> str:
    header = {"alg": "none", "typ": "JWT"}
    header_raw = base64.urlsafe_b64encode(json.dumps(header).encode("utf-8")).decode("ascii").rstrip("=")
    payload_raw = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
    return f"{header_raw}.{payload_raw}.signature"


def test_parse_callback_input_from_url() -> None:
    code = parse_callback_input(
        "http://localhost:1455/auth/callback?code=abc123&state=xyz",
        "xyz",
    )
    assert code == "abc123"


def test_parse_callback_input_rejects_state_mismatch() -> None:
    with pytest.raises(ValueError):
        parse_callback_input(
            "http://localhost:1455/auth/callback?code=abc123&state=wrong",
            "expected",
        )


def test_parse_callback_input_accepts_raw_code() -> None:
    assert parse_callback_input("plain-code", "expected") == "plain-code"


def test_authorize_url_shape() -> None:
    url = build_authorize_url("state123", "challenge123")
    assert "auth.openai.com/oauth/authorize" in url
    assert "client_id=app_EMoamEEZ73f0CkXaXp7hrann" in url
    assert "state=state123" in url
    assert "code_challenge=challenge123" in url
    assert "scope=openid+profile+email+offline_access" in url


def test_decode_identity_from_jwt() -> None:
    token = _jwt(
        {
            "exp": 1800000000,
            "https://api.openai.com/auth": {
                "chatgpt_account_id": "acct_123",
                "chatgpt_account_user_id": "user_456",
            },
            "https://api.openai.com/profile": {
                "email": "codex@example.com",
            },
        }
    )
    payload = decode_jwt_payload(token)
    assert payload is not None
    assert resolve_access_token_expiry_epoch_seconds(token) == 1800000000
    identity = resolve_identity(token)
    assert identity["account_id"] == "acct_123"
    assert identity["email"] == "codex@example.com"
    assert identity["subject"] == "user_456"


def test_extract_oauth_tokens_accepts_camel_case() -> None:
    access, refresh = _extract_oauth_tokens(
        {
            "accessToken": "a",
            "refreshToken": "r",
        },
        require_refresh=True,
        context="OAuth exchange",
    )
    assert access == "a"
    assert refresh == "r"


def test_extract_oauth_tokens_reports_error_payload() -> None:
    with pytest.raises(RuntimeError, match="invalid_grant"):
        _extract_oauth_tokens(
            {"error": "invalid_grant", "error_description": "bad code"},
            require_refresh=True,
            context="OAuth exchange",
        )
