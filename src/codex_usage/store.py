from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STORE_VERSION = 1


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def epoch_seconds_to_iso(epoch_seconds: int) -> str:
    dt = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).replace(microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")


def iso_to_epoch_seconds(value: str) -> int:
    normalized = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def default_store() -> dict[str, Any]:
    return {"version": STORE_VERSION, "accounts": []}


def _validate_account(account: dict[str, Any], index: int) -> None:
    required_string_fields = [
        "account_id",
        "access_token",
        "refresh_token",
        "expires_at",
        "created_at",
        "updated_at",
    ]
    for field in required_string_fields:
        value = account.get(field)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"Invalid account record {index}: missing/invalid '{field}'.")

    for optional_field in ("email", "display_name", "subject"):
        value = account.get(optional_field)
        if value is not None and not isinstance(value, str):
            raise RuntimeError(f"Invalid account record {index}: '{optional_field}' must be string/null.")


def _validate_store(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimeError("auth.json must contain a JSON object.")
    version = payload.get("version")
    if version != STORE_VERSION:
        raise RuntimeError(
            f"Unsupported auth.json version: {version!r}. Expected version {STORE_VERSION}."
        )
    accounts = payload.get("accounts")
    if not isinstance(accounts, list):
        raise RuntimeError("auth.json must contain an 'accounts' array.")
    for idx, account in enumerate(accounts):
        if not isinstance(account, dict):
            raise RuntimeError(f"Invalid account record at index {idx}: expected object.")
        _validate_account(account, idx)
    return payload


def load_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return default_store()
    try:
        raw = path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse {path}: {exc}") from exc
    return _validate_store(parsed)


def save_store(path: Path, store: dict[str, Any]) -> None:
    _validate_store(store)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp_fd, tmp_path = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            json.dump(store, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _find_account_index_by_identity(
    store: dict[str, Any],
    account_id: str | None,
    email: str | None,
    subject: str | None,
) -> int | None:
    accounts = store["accounts"]
    if account_id:
        for idx, account in enumerate(accounts):
            if account.get("account_id") == account_id:
                return idx
    if email:
        for idx, account in enumerate(accounts):
            if account.get("email") == email:
                return idx
    if subject:
        for idx, account in enumerate(accounts):
            if account.get("subject") == subject:
                return idx
    return None


def make_local_account_id(account_id: str | None, email: str | None, subject: str | None) -> str:
    if account_id:
        return account_id
    if email:
        return f"email:{email}"
    if subject:
        return f"id:{subject}"
    raise RuntimeError("Unable to derive account identity from OAuth token.")


def upsert_account(
    store: dict[str, Any],
    *,
    account_id: str | None,
    email: str | None,
    subject: str | None,
    access_token: str,
    refresh_token: str,
    expires_epoch_seconds: int,
) -> tuple[dict[str, Any], bool]:
    now = utc_now_iso()
    local_account_id = make_local_account_id(account_id, email, subject)

    record = {
        "account_id": local_account_id,
        "email": email,
        "display_name": email,
        "subject": subject,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": epoch_seconds_to_iso(expires_epoch_seconds),
        "updated_at": now,
    }

    idx = _find_account_index_by_identity(store, account_id, email, subject)
    if idx is None:
        record["created_at"] = now
        store["accounts"].append(record)
        return record, False

    existing = store["accounts"][idx]
    record["created_at"] = existing.get("created_at") if isinstance(existing.get("created_at"), str) else now
    store["accounts"][idx] = record
    return record, True
