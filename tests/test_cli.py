from __future__ import annotations

import json
import re
import stat
from pathlib import Path

import codex_usage.cli as cli_module
import pytest
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


def test_format_text_usage_hides_error_column_when_no_errors() -> None:
    now_ms = 1_700_000_000_000
    output = _format_text_usage(
        [
            {
                "label": "one@example.com",
                "status": "ok",
                "plan": "free",
                "windows": [{"label": "168h", "used_percent": 25.0, "reset_at_ms": now_ms + 60_000}],
            },
            {
                "label": "two@example.com",
                "status": "pending",
            },
        ],
        now_ms=now_ms,
    )

    plain = re.sub(r"\x1b\[[0-9;]*m", "", output)
    assert "Error" not in plain
    assert "| # | Account" in plain
    assert "| 1 | one@example.com | ok" in plain
    assert "| 2 | two@example.com | pending" in plain


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
        dump_json=False,
        print_json=True,
        debug=True,
        json_output_dir=None,
    )

    assert rc == 0
    assert called["threaded"] is True
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["rows"][0]["account"] == "one@example.com"
    assert payload["rows"][0]["status"] == "ok"
    assert captured.err == ""


def test_handle_show_usage_json_writes_per_account_api_snapshots(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    store_path = tmp_path / "auth.json"
    output_dir = tmp_path / "json"
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
    upsert_account(
        store,
        account_id="acct_2",
        email="two/weird@example.com",
        subject="user_2",
        access_token="access-2",
        refresh_token="refresh-2",
        expires_epoch_seconds=2_000_000_000,
    )
    save_store(store_path, store)

    def fake_threaded(accounts, *, timeout: float, debug: bool, on_update=None):
        assert len(accounts) == 2
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
                    "usage_raw": {"plan_type": "free"},
                    "oauth_refresh_raw": None,
                },
                {
                    "label": "two/weird@example.com",
                    "account_id": "acct_2",
                    "email": "two/weird@example.com",
                    "status": "error",
                    "error": "boom",
                    "oauth_refresh_raw": {"token_type": "bearer"},
                },
            ],
            False,
        )

    monkeypatch.setattr(cli_module, "_refresh_accounts_threaded", fake_threaded)
    monkeypatch.setattr(cli_module, "_json_filename_timestamp", lambda: "20260425-031500")

    rc = cli_module._handle_show_usage(
        store_path,
        timeout=5.0,
        dump_json=True,
        print_json=False,
        debug=False,
        json_output_dir=output_dir,
    )

    assert rc == 0
    first = output_dir / "20260425-031500--one@example.com.json"
    second = output_dir / "20260425-031500--two_weird@example.com.json"
    assert first.exists()
    assert second.exists()
    assert stat.S_IMODE(first.stat().st_mode) == 0o600
    assert stat.S_IMODE(second.stat().st_mode) == 0o600

    payload_one = json.loads(first.read_text(encoding="utf-8"))
    assert payload_one["status"] == "ok"
    assert payload_one["api_output"]["usage"] == {"plan_type": "free"}

    payload_two = json.loads(second.read_text(encoding="utf-8"))
    assert payload_two["status"] == "error"
    assert payload_two["api_output"]["oauth_refresh"] == {"token_type": "bearer"}

    captured = capsys.readouterr()
    assert "one@example.com" in captured.out
    assert "Saved 2 JSON snapshot files to" in captured.err
    assert str(output_dir) in captured.err


def test_main_allows_tui_with_dump_json(monkeypatch, tmp_path: Path) -> None:
    auth_path = tmp_path / "auth.json"
    called: dict[str, object] = {}

    def fake_tui(
        store_path, timeout: float, debug: bool, *, dump_json: bool, print_json: bool, json_output_dir
    ):
        called["store_path"] = store_path
        called["timeout"] = timeout
        called["debug"] = debug
        called["dump_json"] = dump_json
        called["print_json"] = print_json
        called["json_output_dir"] = json_output_dir
        return 0

    monkeypatch.setattr(cli_module, "_handle_show_usage_tui", fake_tui)

    rc = cli_module.main(
        [
            "--tui",
            "--dump-json",
            "--auth-file",
            str(auth_path),
            "--timeout",
            "9",
            "--debug",
        ]
    )

    assert rc == 0
    assert called["store_path"] == auth_path.resolve()
    assert called["timeout"] == 9.0
    assert called["debug"] is True
    assert called["dump_json"] is True
    assert called["print_json"] is False
    assert isinstance(called["json_output_dir"], Path)
    assert called["json_output_dir"] == Path("codex-usage-dump")


def test_handle_add_account_json_writes_auth_snapshot(monkeypatch, tmp_path: Path) -> None:
    store_path = tmp_path / "auth.json"
    output_dir = tmp_path / "json"
    prompts = iter(["http://localhost:1455/auth/callback?code=ac_123&state=state_123"])

    monkeypatch.setattr(cli_module, "generate_pkce_pair", lambda: ("verifier_123", "challenge_123"))
    monkeypatch.setattr(cli_module, "generate_state", lambda: "state_123")
    monkeypatch.setattr(
        cli_module,
        "build_authorize_url",
        lambda state, challenge: f"https://auth.example/authorize?state={state}&code_challenge={challenge}",
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(prompts))
    monkeypatch.setattr(cli_module, "_open_browser", lambda _url: None)
    monkeypatch.setattr(cli_module, "parse_callback_input", lambda _raw, _state: "ac_123")
    monkeypatch.setattr(
        cli_module,
        "exchange_authorization_code",
        lambda _code, _verifier, timeout, debug: {
            "access_token": "at_123",
            "refresh_token": "rt_123",
            "expires_epoch_seconds": 2_000_000_000,
            "token_type": "Bearer",
            "scope": "openid profile email offline_access",
        },
    )
    monkeypatch.setattr(
        cli_module,
        "resolve_identity",
        lambda _access_token: {
            "account_id": "acct_1",
            "email": "one@example.com",
            "subject": "user_1",
        },
    )
    monkeypatch.setattr(cli_module, "_json_filename_timestamp", lambda: "20260425-131500")

    rc = cli_module._handle_add_account(
        store_path,
        timeout=10.0,
        no_open=True,
        debug=False,
        dump_json=True,
        json_output_dir=output_dir,
    )

    assert rc == 0
    snapshot = output_dir / "20260425-131500--one@example.com--auth.json"
    assert snapshot.exists()
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o600
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    assert payload["status"] == "ok"
    assert payload["oauth_exchange_response"]["token_type"] == "Bearer"
    assert payload["resolved_identity"]["email"] == "one@example.com"
    assert payload["saved_account"]["account_id"] == "acct_1"


def test_handle_add_account_json_writes_error_snapshot(monkeypatch, tmp_path: Path) -> None:
    store_path = tmp_path / "auth.json"
    output_dir = tmp_path / "json"
    prompts = iter(["not-a-valid-callback"])

    monkeypatch.setattr(cli_module, "generate_pkce_pair", lambda: ("verifier_123", "challenge_123"))
    monkeypatch.setattr(cli_module, "generate_state", lambda: "state_123")
    monkeypatch.setattr(
        cli_module,
        "build_authorize_url",
        lambda _state, _challenge: "https://auth.example/authorize",
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(prompts))
    monkeypatch.setattr(cli_module, "_open_browser", lambda _url: None)
    monkeypatch.setattr(
        cli_module,
        "parse_callback_input",
        lambda _raw, _state: (_ for _ in ()).throw(ValueError("bad callback")),
    )
    monkeypatch.setattr(cli_module, "_json_filename_timestamp", lambda: "20260425-131501")

    with pytest.raises(ValueError, match="bad callback"):
        cli_module._handle_add_account(
            store_path,
            timeout=10.0,
            no_open=True,
            debug=False,
            dump_json=True,
            json_output_dir=output_dir,
        )

    snapshot = output_dir / "20260425-131501--unknown--auth.json"
    assert snapshot.exists()
    assert stat.S_IMODE(snapshot.stat().st_mode) == 0o600
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    assert payload["status"] == "error"
    assert payload["error"] == "bad callback"
    assert payload["callback_input"] == "not-a-valid-callback"


def test_main_passes_dump_json_dir_to_add_account(monkeypatch, tmp_path: Path) -> None:
    auth_path = tmp_path / "nested" / "auth.json"
    called: dict[str, object] = {}

    def fake_add_account(
        store_path,
        timeout: float,
        no_open: bool,
        debug: bool,
        *,
        dump_json: bool,
        json_output_dir,
    ):
        called["store_path"] = store_path
        called["timeout"] = timeout
        called["no_open"] = no_open
        called["debug"] = debug
        called["dump_json"] = dump_json
        called["json_output_dir"] = json_output_dir
        return 0

    monkeypatch.setattr(cli_module, "_handle_add_account", fake_add_account)

    rc = cli_module.main(
        [
            "--add-account",
            "--dump-json",
            "--auth-file",
            str(auth_path),
            "--timeout",
            "7",
            "--no-open",
            "--debug",
        ]
    )

    assert rc == 0
    assert called["store_path"] == auth_path.resolve()
    assert called["timeout"] == 7.0
    assert called["no_open"] is True
    assert called["debug"] is True
    assert called["dump_json"] is True
    assert called["json_output_dir"] == Path("codex-usage-dump")


def test_resolve_store_path_prefers_cwd_auth_json(monkeypatch, tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    (cwd / "auth.json").write_text("{}", encoding="utf-8")

    monkeypatch.chdir(cwd)

    original_expanduser = cli_module.os.path.expanduser

    def fake_expanduser(value: str) -> str:
        if value == "~":
            return str(home)
        return original_expanduser(value)

    monkeypatch.setattr(cli_module.os.path, "expanduser", fake_expanduser)

    resolved = cli_module._resolve_store_path("auth.json")
    assert resolved == (cwd / "auth.json").resolve()


def test_resolve_store_path_falls_back_to_home_config(monkeypatch, tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    home = tmp_path / "home"
    cwd.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(cwd)

    original_expanduser = cli_module.os.path.expanduser

    def fake_expanduser(value: str) -> str:
        if value == "~":
            return str(home)
        return original_expanduser(value)

    monkeypatch.setattr(cli_module.os.path, "expanduser", fake_expanduser)

    resolved = cli_module._resolve_store_path("auth.json")
    expected = (home / ".config" / "codex-usage" / "auth.json").resolve()
    assert resolved == expected


def test_main_defaults_to_show_usage_when_no_args(monkeypatch) -> None:
    called: dict[str, object] = {}

    def fake_show_usage(
        store_path,
        timeout: float,
        dump_json: bool,
        print_json: bool,
        debug: bool,
        *,
        json_output_dir,
    ):
        called["store_path"] = store_path
        called["timeout"] = timeout
        called["dump_json"] = dump_json
        called["print_json"] = print_json
        called["debug"] = debug
        called["json_output_dir"] = json_output_dir
        return 0

    monkeypatch.setattr(cli_module, "_handle_show_usage", fake_show_usage)
    rc = cli_module.main([])

    assert rc == 0
    assert called["dump_json"] is False
    assert called["print_json"] is False
    assert called["debug"] is False
    assert called["timeout"] == 20.0


def test_main_passes_json_stdout_mode_to_show_usage(monkeypatch, tmp_path: Path) -> None:
    auth_path = tmp_path / "auth.json"
    called: dict[str, object] = {}

    def fake_show_usage(
        store_path,
        timeout: float,
        dump_json: bool,
        print_json: bool,
        debug: bool,
        *,
        json_output_dir,
    ):
        called["store_path"] = store_path
        called["timeout"] = timeout
        called["dump_json"] = dump_json
        called["print_json"] = print_json
        called["debug"] = debug
        called["json_output_dir"] = json_output_dir
        return 0

    monkeypatch.setattr(cli_module, "_handle_show_usage", fake_show_usage)

    rc = cli_module.main(
        [
            "--show-usage",
            "--json",
            "--auth-file",
            str(auth_path),
        ]
    )

    assert rc == 0
    assert called["store_path"] == auth_path.resolve()
    assert called["timeout"] == 20.0
    assert called["dump_json"] is False
    assert called["print_json"] is True
    assert called["debug"] is False
    assert called["json_output_dir"] is None
