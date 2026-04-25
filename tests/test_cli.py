from __future__ import annotations

import json
import re
from pathlib import Path

import codex_usage.cli as cli_module
from codex_usage.cli import _format_text_usage, _result_sort_key
from codex_usage.store import load_store, save_store, upsert_account


def test_format_text_usage_renders_table_rows() -> None:
    now_ms = 1_700_000_000_000
    output = _format_text_usage(
        [
            {
                "label": "one@example.com",
                "status": "ok",
                "plan": "pro",
                "windows": [
                    {"label": "0h", "used_percent": 100.0, "reset_at_ms": now_ms + 5 * 60_000},
                    {"label": "3h", "used_percent": 60.0, "reset_at_ms": now_ms + (3 * 60 + 2) * 60_000},
                    {"label": "6h", "used_percent": 50.0, "reset_at_ms": now_ms + (24 * 60 + 61) * 60_000},
                    {"label": "9h", "used_percent": 0.0, "reset_at_ms": now_ms + (2 * 24 * 60 + 7 * 60 + 59) * 60_000},
                ],
            },
            {
                "label": "two@example.com",
                "status": "error",
                "error": "token expired",
            },
        ],
        now_ms=now_ms,
    )

    plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
    assert "Account" in plain
    assert "Status" in plain
    assert "Windows" in plain
    assert "| 1 | one@example.com | ok" in plain
    assert "0h available=0.0% left=0-days 0-hrs 5-minutes" in plain
    assert "3h available=40.0% left=0-days 3-hrs 2-minutes" in plain
    assert "6h available=50.0% left=1-days 1-hrs 1-minutes" in plain
    assert "9h available=100.0% left=2-days 7-hrs 59-minutes" in plain
    assert "| 2 | two@example.com | error" in plain
    assert "token expired" in plain

    assert "\x1b[31m0.0%\x1b[0m" in output
    assert "\x1b[38;5;208m40.0%\x1b[0m" in output
    assert "\x1b[33m50.0%\x1b[0m" in output
    assert "\x1b[32m100.0%\x1b[0m" in output
    assert output.count("\n") >= 5


def test_result_sort_key_orders_available_desc_left_asc() -> None:
    now_ms = 1_700_000_000_000
    results = [
        {
            "label": "bottom@example.com",
            "status": "ok",
            "windows": [{"used_percent": 100.0, "reset_at_ms": now_ms + 10 * 60_000}],  # 0% available
        },
        {
            "label": "later@example.com",
            "status": "ok",
            "windows": [{"used_percent": 0.0, "reset_at_ms": now_ms + 8 * 60_000}],  # 100% available, later
        },
        {
            "label": "sooner@example.com",
            "status": "ok",
            "windows": [{"used_percent": 0.0, "reset_at_ms": now_ms + 5 * 60_000}],  # 100% available, sooner
        },
        {
            "label": "middle@example.com",
            "status": "ok",
            "windows": [{"used_percent": 30.0, "reset_at_ms": now_ms + 1 * 60_000}],  # 70% available
        },
    ]

    sorted_results = sorted(results, key=lambda item: _result_sort_key(item, now_ms=now_ms))
    assert [item["label"] for item in sorted_results] == [
        "sooner@example.com",
        "later@example.com",
        "middle@example.com",
        "bottom@example.com",
    ]


def test_handle_show_usage_uses_threaded_refresh(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    store_path = tmp_path / "auth.json"
    store = load_store(store_path)
    upsert_account(
        store,
        account_id="acct_1",
        email="one@example.com",
        subject="user_1",
        access_token="access-1",
        refresh_token="refresh-1",
        expires_epoch_seconds=2_000_000_000,
    )
    save_store(store_path, store)

    called = {"threaded": False}

    def fake_single(*_args, **_kwargs):
        raise AssertionError("_refresh_single_account should not be called for --show-usage")

    def fake_threaded(accounts, *, timeout: float, debug: bool, on_update=None):
        called["threaded"] = True
        assert len(accounts) == 1
        assert timeout == 12.0
        assert debug is True
        assert on_update is None
        return (
            accounts,
            [
                {
                    "label": "one@example.com",
                    "account_id": "acct_1",
                    "email": "one@example.com",
                    "status": "ok",
                    "plan": "free",
                    "windows": [],
                }
            ],
            False,
        )

    monkeypatch.setattr(cli_module, "_refresh_single_account", fake_single)
    monkeypatch.setattr(cli_module, "_refresh_accounts_threaded", fake_threaded)

    rc = cli_module._handle_show_usage(
        store_path,
        timeout=12.0,
        as_json=True,
        debug=True,
    )

    assert rc == 0
    assert called["threaded"] is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["accounts"][0]["label"] == "one@example.com"
