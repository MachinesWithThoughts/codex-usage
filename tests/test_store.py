from __future__ import annotations

import stat
from pathlib import Path

from codex_usage.store import load_store, save_store, upsert_account


def test_load_missing_store(tmp_path: Path) -> None:
    store = load_store(tmp_path / "auth.json")
    assert store["version"] == 1
    assert store["accounts"] == []


def test_upsert_add_and_replace(tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    store = load_store(path)

    first, replaced = upsert_account(
        store,
        account_id="acct_1",
        email="one@example.com",
        subject="user_1",
        access_token="access-1",
        refresh_token="refresh-1",
        expires_epoch_seconds=2000000000,
    )
    assert replaced is False
    assert first["account_id"] == "acct_1"
    assert len(store["accounts"]) == 1

    second, replaced = upsert_account(
        store,
        account_id="acct_1",
        email="one@example.com",
        subject="user_1",
        access_token="access-2",
        refresh_token="refresh-2",
        expires_epoch_seconds=2000001000,
    )
    assert replaced is True
    assert second["access_token"] == "access-2"
    assert len(store["accounts"]) == 1

    save_store(path, store)
    reloaded = load_store(path)
    assert reloaded["accounts"][0]["refresh_token"] == "refresh-2"


def test_save_store_permissions(tmp_path: Path) -> None:
    path = tmp_path / "auth.json"
    store = load_store(path)
    save_store(path, store)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
