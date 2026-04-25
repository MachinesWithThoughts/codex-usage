from __future__ import annotations

import argparse
import json
import os
import re
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

from .oauth import (
    build_authorize_url,
    exchange_authorization_code,
    generate_pkce_pair,
    generate_state,
    parse_callback_input,
    refresh_access_token,
    resolve_identity,
)
from .store import iso_to_epoch_seconds, load_store, save_store, upsert_account
from .usage import fetch_usage

REFRESH_SKEW_SECONDS = 60
ANSI_RESET = "\033[0m"
ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_ORANGE = "\033[38;5;208m"
LINE_COLORS = [
    "\033[36m",  # cyan
    "\033[35m",  # magenta
    "\033[34m",  # blue
    "\033[94m",  # bright blue
    "\033[96m",  # bright cyan
]
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _eprint(message: str) -> None:
    print(message, file=sys.stderr)


def _confirm(prompt: str) -> bool:
    answer = input(prompt).strip().lower()
    return answer in {"y", "yes"}


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:
        pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="codex-usage.py",
        description="OpenClaw-aligned Codex OAuth account manager and usage viewer.",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--add-account", action="store_true", help="Authenticate or re-authenticate an account.")
    action.add_argument("--show-usage", action="store_true", help="Fetch current usage for all stored accounts.")
    parser.add_argument("--auth-file", default="auth.json", help="Path to auth store (default: auth.json).")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds.")
    parser.add_argument("--json", action="store_true", help="Print --show-usage output as JSON.")
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open the auth URL in browser.")
    return parser


def _handle_add_account(store_path: Path, timeout: float, no_open: bool) -> int:
    store = load_store(store_path)
    code_verifier, code_challenge = generate_pkce_pair()
    state = generate_state()
    auth_url = build_authorize_url(state, code_challenge)

    print("Open this URL to authenticate with OpenAI Codex:")
    print(auth_url)
    print()
    print("After completing login, paste the full redirect URL (or the authorization code).")

    if not no_open:
        _open_browser(auth_url)

    callback_input = input("Callback URL or code: ").strip()
    code = parse_callback_input(callback_input, state)
    tokens = exchange_authorization_code(code, code_verifier, timeout=timeout)

    identity = resolve_identity(tokens["access_token"])
    account_id = identity.get("account_id")
    email = identity.get("email")
    subject = identity.get("subject")

    existing_record = None
    for account in store["accounts"]:
        if account_id and account.get("account_id") == account_id:
            existing_record = account
            break
        if email and account.get("email") == email:
            existing_record = account
            break
        if subject and account.get("subject") == subject:
            existing_record = account
            break

    if existing_record is not None:
        label = existing_record.get("email") or existing_record.get("account_id")
        if not _confirm(f"Account '{label}' already exists. Re-authenticate? [y/N]: "):
            print("Cancelled.")
            return 0

    saved_record, replaced = upsert_account(
        store,
        account_id=account_id if isinstance(account_id, str) else None,
        email=email if isinstance(email, str) else None,
        subject=subject if isinstance(subject, str) else None,
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_epoch_seconds=int(tokens["expires_epoch_seconds"]),
    )
    save_store(store_path, store)

    label = saved_record.get("email") or saved_record["account_id"]
    action = "Re-authenticated" if replaced else "Added"
    print(f"{action} account: {label}")
    print(f"Auth store: {store_path}")
    return 0


def _ensure_fresh_account_tokens(account: dict[str, Any], timeout: float) -> tuple[dict[str, Any], bool]:
    now = int(time.time())
    expires = iso_to_epoch_seconds(account["expires_at"])
    if expires > now + REFRESH_SKEW_SECONDS:
        return account, False

    refreshed = refresh_access_token(account["refresh_token"], timeout=timeout)
    identity = resolve_identity(refreshed["access_token"], fallback_email=account.get("email"))

    account["access_token"] = refreshed["access_token"]
    account["refresh_token"] = refreshed["refresh_token"]
    account["expires_at"] = (
        datetime.fromtimestamp(int(refreshed["expires_epoch_seconds"]), tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    account["updated_at"] = (
        datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )
    if isinstance(identity.get("email"), str) and identity["email"]:
        account["email"] = identity["email"]
        account["display_name"] = identity["email"]
    if isinstance(identity.get("account_id"), str) and identity["account_id"]:
        account["account_id"] = identity["account_id"]
    if isinstance(identity.get("subject"), str) and identity["subject"]:
        account["subject"] = identity["subject"]

    return account, True


def _format_text_usage(results: list[dict[str, Any]], *, now_ms: int | None = None) -> str:
    headers = ["#", "Account", "Status", "Plan", "Windows", "Error"]
    rows: list[list[str]] = []
    for index, result in enumerate(results, start=1):
        line_color = LINE_COLORS[(index - 1) % len(LINE_COLORS)]
        if result["status"] != "ok":
            rows.append(
                [
                    _color_line_cell(str(index), line_color),
                    _color_line_cell(str(result.get("label") or "<unknown>"), line_color),
                    _color_line_cell("error", line_color),
                    _color_line_cell("-", line_color),
                    _color_line_cell("-", line_color),
                    _color_line_cell(str(result.get("error") or "unknown error"), line_color),
                ]
            )
            continue

        windows = result.get("windows") or []
        if not windows:
            windows_text = _color_line_cell("none", line_color)
        else:
            windows_text = ", ".join(
                _format_window_entry(window, line_color, now_ms=now_ms)
                for window in windows
            )
        rows.append(
            [
                _color_line_cell(str(index), line_color),
                _color_line_cell(str(result.get("label") or "<unknown>"), line_color),
                _color_line_cell("ok", line_color),
                _color_line_cell(str(result.get("plan") or "unknown"), line_color),
                windows_text,
                _color_line_cell("-", line_color),
            ]
        )

    widths = [len(h) for h in headers]
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], _visible_len(value))

    def divider() -> str:
        return "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def render_row(values: list[str]) -> str:
        return "| " + " | ".join(_pad_ansi(value, widths[idx]) for idx, value in enumerate(values)) + " |"

    lines = [divider(), render_row(headers), divider()]
    lines.extend(render_row(row) for row in rows)
    lines.append(divider())
    return "\n".join(lines)


def _format_window_entry(window: dict[str, Any], line_color: str, *, now_ms: int | None = None) -> str:
    label_text = _color_line_cell(str(window["label"]), line_color)
    available_percent = _resolve_available_percent(window)
    percent_text = _colorize_percent(available_percent, continue_color=line_color)
    reset_value = _format_relative_reset(window.get("reset_at_ms"), now_ms=now_ms)
    reset_text = _color_line_cell(f"left={reset_value}", line_color)
    return f"{label_text} available={percent_text} {reset_text}"


def _format_relative_reset(reset_at_ms: Any, *, now_ms: int | None = None) -> str:
    if not isinstance(reset_at_ms, int) or reset_at_ms <= 0:
        return "unknown"
    current_ms = int(time.time() * 1000) if now_ms is None else now_ms
    remaining_ms = max(0, reset_at_ms - current_ms)
    total_minutes = remaining_ms // 60_000
    days = total_minutes // (24 * 60)
    hours = (total_minutes % (24 * 60)) // 60
    minutes = total_minutes % 60
    return f"{days}-days {hours}-hrs {minutes}-minutes"


def _resolve_available_percent(window: dict[str, Any]) -> float:
    raw = window.get("used_percent")
    used = 0.0
    if isinstance(raw, (int, float)):
        used = float(raw)
    else:
        try:
            used = float(raw)
        except (TypeError, ValueError):
            used = 0.0
    available = 100.0 - used
    if available < 0:
        return 0.0
    if available > 100:
        return 100.0
    return available


def _colorize_percent(value: float, *, continue_color: str = "") -> str:
    text = f"{value:.1f}%"
    if value <= 0:
        color = ANSI_RED
    elif value >= 100:
        color = ANSI_GREEN
    elif value >= 50:
        color = ANSI_YELLOW
    else:
        color = ANSI_ORANGE
    return f"{color}{text}{ANSI_RESET}{continue_color}"


def _color_line_cell(value: str, line_color: str) -> str:
    return f"{line_color}{value}{ANSI_RESET}"


def _visible_len(value: str) -> int:
    return len(ANSI_RE.sub("", value))


def _pad_ansi(value: str, width: int) -> str:
    pad = width - _visible_len(value)
    if pad <= 0:
        return value
    return f"{value}{' ' * pad}"


def _handle_show_usage(store_path: Path, timeout: float, as_json: bool) -> int:
    store = load_store(store_path)
    accounts = store.get("accounts", [])
    if not accounts:
        _eprint(f"No accounts found in {store_path}. Add one with --add-account.")
        return 1

    updated = False
    results: list[dict[str, Any]] = []

    for account in accounts:
        label = account.get("email") or account.get("account_id") or "<unknown>"
        try:
            _, was_updated = _ensure_fresh_account_tokens(account, timeout)
            updated = updated or was_updated
            usage = fetch_usage(account["access_token"], account.get("account_id"), timeout)
            results.append(
                {
                    "label": label,
                    "account_id": account.get("account_id"),
                    "email": account.get("email"),
                    "status": "ok",
                    "plan": usage.get("plan"),
                    "windows": usage.get("windows", []),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "label": label,
                    "account_id": account.get("account_id"),
                    "email": account.get("email"),
                    "status": "error",
                    "error": str(exc),
                }
            )

    if updated:
        save_store(store_path, store)

    if as_json:
        print(json.dumps({"accounts": results}, indent=2))
    else:
        print(_format_text_usage(results))

    has_success = any(item["status"] == "ok" for item in results)
    return 0 if has_success else 1


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    store_path = Path(os.path.expanduser(args.auth_file)).resolve()

    try:
        if args.add_account:
            return _handle_add_account(store_path, timeout=float(args.timeout), no_open=args.no_open)
        return _handle_show_usage(store_path, timeout=float(args.timeout), as_json=args.json)
    except KeyboardInterrupt:
        _eprint("Interrupted.")
        return 130
    except Exception as exc:
        _eprint(str(exc))
        return 1
