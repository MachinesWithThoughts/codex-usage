from __future__ import annotations

import argparse
import contextlib
import json
import os
import queue
import re
import select
import sys
import tempfile
import termios
import threading
import tty
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any, Callable

from . import __version__
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
AUTO_REFRESH_SECONDS = 10 * 60
JSON_OUTPUT_DIR_NAME = "codex-usage-dump"
PRIVATE_DIR_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
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
FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._@-]+")


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
        epilog=f"Version: {__version__}",
    )
    parser.add_argument("--add-account", action="store_true", help="Authenticate or re-authenticate an account.")
    parser.add_argument("--show-usage", action="store_true", help="Fetch current usage for all stored accounts.")
    parser.add_argument(
        "--auth-file",
        default="auth.json",
        help=(
            "Path to auth store. Default lookup: ./auth.json, "
            "otherwise ~/.config/codex-usage/auth.json."
        ),
    )
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--dump-json",
        action="store_true",
        help=(
            "Save API output to ./codex-usage-dump "
            "(usage: YYYYMMDD-HH24MMSS--account.json, auth: YYYYMMDD-HH24MMSS--account--auth.json)."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print usage table data as JSON to stdout.",
    )
    parser.add_argument("--tui", action="store_true", help="Interactive TUI mode for --show-usage.")
    parser.add_argument("--no-open", action="store_true", help="Do not auto-open the auth URL in browser.")
    parser.add_argument("--debug", action="store_true", help="Dump raw API response output to stderr.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _resolve_store_path(auth_file: str) -> Path:
    # Backward-compatible default lookup: prefer ./auth.json, then ~/.config/codex-usage/auth.json.
    if auth_file.strip() == "auth.json":
        cwd_candidate = (Path.cwd() / "auth.json").resolve()
        if cwd_candidate.exists():
            return cwd_candidate
        config_candidate = (
            Path(os.path.expanduser("~")) / ".config" / "codex-usage" / "auth.json"
        ).resolve()
        return config_candidate
    return Path(os.path.expanduser(auth_file)).resolve()


def _handle_add_account(
    store_path: Path,
    timeout: float,
    no_open: bool,
    debug: bool,
    *,
    dump_json: bool,
    json_output_dir: Path | None,
) -> int:
    trace: dict[str, Any] = {
        "captured_at": _capture_timestamp(),
        "mode": "add-account",
        "status": "started",
        "store_path": str(store_path),
    }

    def flush_snapshot(account_hint: str | None = None) -> None:
        if not dump_json or json_output_dir is None:
            return
        _write_json_auth_snapshot(trace, json_output_dir, account_hint=account_hint)

    try:
        store = load_store(store_path)
        code_verifier, code_challenge = generate_pkce_pair()
        state = generate_state()
        auth_url = build_authorize_url(state, code_challenge)
        trace["oauth_request"] = {
            "state": state,
            "code_challenge": code_challenge,
            "auth_url": auth_url,
        }

        print("Open this URL to authenticate with OpenAI Codex:")
        print(auth_url)
        print()
        print("After completing login, paste the full redirect URL (or the authorization code).")

        if not no_open:
            _open_browser(auth_url)

        callback_input = input("Callback URL or code: ").strip()
        trace["callback_input"] = callback_input
        code = parse_callback_input(callback_input, state)
        trace["authorization_code"] = code
        tokens = exchange_authorization_code(code, code_verifier, timeout=timeout, debug=debug)
        trace["oauth_exchange_response"] = tokens

        identity = resolve_identity(tokens["access_token"])
        trace["resolved_identity"] = identity
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
                trace["status"] = "cancelled"
                trace["cancel_reason"] = "User declined re-authentication."
                flush_snapshot(account_hint=str(label) if label else None)
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
        trace["status"] = "ok"
        trace["saved_account"] = saved_record
        trace["replaced"] = replaced
        trace["action"] = action
        flush_snapshot(account_hint=str(label))
        print(f"{action} account: {label}")
        print(f"Auth store: {store_path}")
        return 0
    except Exception as exc:
        trace["status"] = "error"
        trace["error"] = str(exc)
        account_hint: str | None = None
        identity = trace.get("resolved_identity")
        if isinstance(identity, dict):
            raw_hint = identity.get("email") or identity.get("account_id")
            if isinstance(raw_hint, str) and raw_hint:
                account_hint = raw_hint
        flush_snapshot(account_hint=account_hint)
        raise


def _ensure_fresh_account_tokens(
    account: dict[str, Any], timeout: float, *, debug: bool = False
) -> tuple[dict[str, Any], bool, dict[str, Any] | None]:
    now = int(time.time())
    expires = iso_to_epoch_seconds(account["expires_at"])
    if expires > now + REFRESH_SKEW_SECONDS:
        return account, False, None

    refreshed = refresh_access_token(account["refresh_token"], timeout=timeout, debug=debug)
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

    return account, True, refreshed


def _format_text_usage(
    results: list[dict[str, Any]],
    *,
    now_ms: int | None = None,
    last_capture_time: str | None = None,
) -> str:
    has_errors = any(str(result.get("status") or "") not in {"ok", "pending"} for result in results)
    headers = ["#", "Account", "Status", "Plan", "Windows"]
    if has_errors:
        headers.append("Error")
    rows: list[list[str]] = []
    for index, result in enumerate(results, start=1):
        line_color = LINE_COLORS[(index - 1) % len(LINE_COLORS)]
        status = str(result.get("status") or "")
        if status == "pending":
            row = [
                _color_line_cell(str(index), line_color),
                _color_line_cell(str(result.get("label") or "<unknown>"), line_color),
                _color_line_cell("pending", line_color),
                _color_line_cell("-", line_color),
                _color_line_cell("refreshing...", line_color),
            ]
            if has_errors:
                row.append(_color_line_cell("-", line_color))
            rows.append(row)
            continue

        if status != "ok":
            row = [
                _color_line_cell(str(index), line_color),
                _color_line_cell(str(result.get("label") or "<unknown>"), line_color),
                _color_line_cell("error", line_color),
                _color_line_cell("-", line_color),
                _color_line_cell("-", line_color),
            ]
            if has_errors:
                row.append(_color_line_cell(str(result.get("error") or "unknown error"), line_color))
            rows.append(row)
            continue

        windows = result.get("windows") or []
        if not windows:
            windows_text = _color_line_cell("none", line_color)
        else:
            windows_text = ", ".join(
                _format_window_entry(window, line_color, now_ms=now_ms)
                for window in windows
            )
        row = [
            _color_line_cell(str(index), line_color),
            _color_line_cell(str(result.get("label") or "<unknown>"), line_color),
            _color_line_cell("ok", line_color),
            _color_line_cell(str(result.get("plan") or "unknown"), line_color),
            windows_text,
        ]
        if has_errors:
            row.append(_color_line_cell("-", line_color))
        rows.append(row)

    widths = [len(h) for h in headers]
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], _visible_len(value))

    def divider() -> str:
        return "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def render_row(values: list[str]) -> str:
        return "| " + " | ".join(_pad_ansi(value, widths[idx]) for idx, value in enumerate(values)) + " |"

    lines: list[str] = []
    if last_capture_time:
        lines.append(f"Last capture: {last_capture_time}")
        lines.append("")
    lines.extend([divider(), render_row(headers), divider()])
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


def _format_usage_json(results: list[dict[str, Any]], *, last_capture_time: str) -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    rows: list[dict[str, Any]] = []
    for index, result in enumerate(results, start=1):
        status = str(result.get("status") or "")
        row: dict[str, Any] = {
            "index": index,
            "account": str(result.get("label") or "<unknown>"),
            "status": status,
            "plan": None,
            "windows": [],
            "error": None,
        }
        if status == "ok":
            row["plan"] = result.get("plan")
            windows_payload: list[dict[str, Any]] = []
            windows = result.get("windows")
            if isinstance(windows, list):
                for window in windows:
                    if not isinstance(window, dict):
                        continue
                    windows_payload.append(
                        {
                            "label": window.get("label"),
                            "available_percent": _resolve_available_percent(window),
                            "left": _format_relative_reset(window.get("reset_at_ms"), now_ms=now_ms),
                        }
                    )
            row["windows"] = windows_payload
        elif status != "pending":
            row["error"] = result.get("error")
        rows.append(row)
    return {
        "last_capture": last_capture_time,
        "rows": rows,
    }


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


def _resolve_left_ms(reset_at_ms: Any, *, now_ms: int | None = None) -> int:
    if not isinstance(reset_at_ms, int) or reset_at_ms <= 0:
        return 2**62
    current_ms = int(time.time() * 1000) if now_ms is None else now_ms
    return max(0, reset_at_ms - current_ms)


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


def _result_sort_key(result: dict[str, Any], *, now_ms: int | None = None) -> tuple[Any, ...]:
    status = str(result.get("status") or "")
    if status != "ok":
        label = str(result.get("label") or "")
        return (1, 1_000.0, 2**62, label)

    windows = result.get("windows") or []
    if isinstance(windows, list) and windows:
        first_window = windows[0]
        if isinstance(first_window, dict):
            available = _resolve_available_percent(first_window)
            left_ms = _resolve_left_ms(first_window.get("reset_at_ms"), now_ms=now_ms)
            label = str(result.get("label") or "")
            return (0, -available, left_ms, label)

    label = str(result.get("label") or "")
    return (0, 1_000.0, 2**62, label)


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


def _capture_timestamp() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _json_filename_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _safe_account_filename(result: dict[str, Any]) -> str:
    raw = (
        str(result.get("email") or "")
        or str(result.get("label") or "")
        or str(result.get("account_id") or "")
        or "unknown"
    )
    value = FILENAME_SAFE_RE.sub("_", raw).strip("._-")
    return value or "unknown"


def _next_snapshot_path(output_dir: Path, stamp: str, account: str) -> Path:
    path = output_dir / f"{stamp}--{account}.json"
    suffix = 2
    while path.exists():
        path = output_dir / f"{stamp}--{account}-{suffix}.json"
        suffix += 1
    return path


def _write_json_auth_snapshot(
    trace: dict[str, Any], output_dir: Path, *, account_hint: str | None = None
) -> Path:
    _ensure_private_dir(output_dir)
    stamp = _json_filename_timestamp()
    account = _safe_account_filename({"email": account_hint or "unknown"})
    path = output_dir / f"{stamp}--{account}--auth.json"
    suffix = 2
    while path.exists():
        path = output_dir / f"{stamp}--{account}-{suffix}--auth.json"
        suffix += 1
    _write_private_json(path, trace)
    return path


def _write_json_api_snapshots(results: list[dict[str, Any]], output_dir: Path) -> list[Path]:
    _ensure_private_dir(output_dir)
    stamp = _json_filename_timestamp()
    written: list[Path] = []
    for result in results:
        account = _safe_account_filename(result)
        path = _next_snapshot_path(output_dir, stamp, account)

        payload = {
            "captured_at": result.get("captured_at"),
            "label": result.get("label"),
            "email": result.get("email"),
            "account_id": result.get("account_id"),
            "status": result.get("status"),
            "error": result.get("error"),
            "plan": result.get("plan"),
            "windows": result.get("windows"),
            "api_output": {
                "usage": result.get("usage_raw"),
                "oauth_refresh": result.get("oauth_refresh_raw"),
            },
        }
        _write_private_json(path, payload)
        written.append(path)
    return written


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, PRIVATE_DIR_MODE)
    except OSError:
        pass


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(tmp_path, PRIVATE_FILE_MODE)
        os.replace(tmp_path, path)
        os.chmod(path, PRIVATE_FILE_MODE)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _refresh_single_account(
    account: dict[str, Any], *, timeout: float, debug: bool
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    working = dict(account)
    label = working.get("email") or working.get("account_id") or "<unknown>"
    was_updated = False
    oauth_refresh_raw: dict[str, Any] | None = None
    captured_at = _capture_timestamp()
    try:
        _, was_updated, oauth_refresh_raw = _ensure_fresh_account_tokens(
            working,
            timeout,
            debug=debug,
        )
        usage = fetch_usage(
            working["access_token"],
            working.get("account_id"),
            timeout,
            debug=debug,
        )
        result = {
            "label": label,
            "account_id": working.get("account_id"),
            "email": working.get("email"),
            "status": "ok",
            "captured_at": captured_at,
            "plan": usage.get("plan"),
            "windows": usage.get("windows", []),
            "usage_raw": usage.get("raw"),
            "oauth_refresh_raw": oauth_refresh_raw,
        }
    except Exception as exc:
        result = {
            "label": label,
            "account_id": working.get("account_id"),
            "email": working.get("email"),
            "status": "error",
            "captured_at": captured_at,
            "error": str(exc),
            "oauth_refresh_raw": oauth_refresh_raw,
        }
    return working, result, was_updated


def _refresh_accounts_threaded(
    accounts: list[dict[str, Any]],
    *,
    timeout: float,
    debug: bool,
    on_update: Callable[[list[dict[str, Any]], int, int], None] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    total = len(accounts)
    refreshed_accounts = [dict(account) for account in accounts]
    results: list[dict[str, Any]] = []
    for account in accounts:
        label = account.get("email") or account.get("account_id") or "<unknown>"
        results.append(
            {
                "label": label,
                "account_id": account.get("account_id"),
                "email": account.get("email"),
                "status": "pending",
                "captured_at": "-",
            }
        )

    updates: "queue.Queue[tuple[int, dict[str, Any], dict[str, Any], bool]]" = queue.Queue()

    def worker(index: int, account: dict[str, Any]) -> None:
        updated_account, result, was_updated = _refresh_single_account(
            account,
            timeout=timeout,
            debug=debug,
        )
        updates.put((index, updated_account, result, was_updated))

    threads: list[threading.Thread] = []
    for idx, account in enumerate(accounts):
        thread = threading.Thread(target=worker, args=(idx, dict(account)), daemon=True)
        threads.append(thread)
        thread.start()

    updated_any = False
    completed = 0
    while completed < total:
        idx, updated_account, result, was_updated = updates.get()
        refreshed_accounts[idx] = updated_account
        results[idx] = result
        updated_any = updated_any or was_updated
        completed += 1
        if on_update is not None:
            on_update(list(results), completed, total)

    for thread in threads:
        thread.join()

    return refreshed_accounts, results, updated_any


def _clear_screen() -> None:
    print("\033[2J\033[H", end="", flush=True)


def _render_tui(
    results: list[dict[str, Any]],
    *,
    completed: int,
    total: int,
    refreshing: bool,
    auto_refresh: bool,
    next_refresh_at: float | None,
    last_capture_time: str | None,
) -> None:
    sorted_results = sorted(results, key=lambda item: _result_sort_key(item))
    status = f"Refreshing {completed}/{total}..." if refreshing else "Idle"
    auto_state = "OFF"
    if auto_refresh and next_refresh_at is not None:
        remaining = max(0, int(next_refresh_at - time.time()))
        mins = remaining // 60
        secs = remaining % 60
        auto_state = f"ON (next in {mins:02d}:{secs:02d})"
    _clear_screen()
    print("codex-usage TUI")
    print("Press SPACE to refresh all accounts, w to toggle auto-refresh (10m), q to quit.")
    print(f"Status: {status}")
    print(f"Auto-refresh: {auto_state}")
    print(f"Last capture: {last_capture_time or '-'}")
    print()
    print(_format_text_usage(sorted_results))
    sys.stdout.flush()


@contextlib.contextmanager
def _raw_stdin():
    if not sys.stdin.isatty():
        yield False
        return
    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield True
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)


def _poll_keypress(timeout_seconds: float) -> str | None:
    if not sys.stdin.isatty():
        return None
    readable, _, _ = select.select([sys.stdin], [], [], timeout_seconds)
    if not readable:
        return None
    data = os.read(sys.stdin.fileno(), 1)
    if not data:
        return None
    try:
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return None


def _handle_show_usage_tui(
    store_path: Path,
    timeout: float,
    debug: bool,
    *,
    dump_json: bool,
    print_json: bool,
    json_output_dir: Path | None,
) -> int:
    store = load_store(store_path)
    accounts = store.get("accounts", [])
    if not accounts:
        _eprint(f"No accounts found in {store_path}. Add one with --add-account.")
        return 1
    if not sys.stdout.isatty() or not sys.stdin.isatty():
        _eprint("TUI requires an interactive terminal; falling back to regular --show-usage output.")
        return _handle_show_usage(
            store_path,
            timeout=timeout,
            dump_json=dump_json,
            print_json=print_json,
            debug=debug,
            json_output_dir=json_output_dir,
        )

    with _raw_stdin() as raw_ok:
        if not raw_ok:
            _eprint("Failed to enable terminal raw mode; falling back to regular --show-usage output.")
            return _handle_show_usage(
                store_path,
                timeout=timeout,
                dump_json=dump_json,
                print_json=print_json,
                debug=debug,
                json_output_dir=json_output_dir,
            )
        if print_json:
            _eprint("--json is ignored in interactive --tui mode.")

        pending_results = []
        for account in accounts:
            label = account.get("email") or account.get("account_id") or "<unknown>"
            pending_results.append(
                {
                    "label": label,
                    "account_id": account.get("account_id"),
                    "email": account.get("email"),
                    "status": "pending",
                    "captured_at": "-",
                }
            )

        results = pending_results
        auto_refresh = False
        next_refresh_at: float | None = None
        last_capture_time: str | None = None
        while True:
            _render_tui(
                results,
                completed=0,
                total=len(accounts),
                refreshing=True,
                auto_refresh=auto_refresh,
                next_refresh_at=next_refresh_at,
                last_capture_time=last_capture_time,
            )

            def on_update(snapshot: list[dict[str, Any]], completed: int, total: int) -> None:
                nonlocal results
                results = snapshot
                _render_tui(
                    results,
                    completed=completed,
                    total=total,
                    refreshing=True,
                    auto_refresh=auto_refresh,
                    next_refresh_at=next_refresh_at,
                    last_capture_time=last_capture_time,
                )

            refreshed_accounts, results, updated_any = _refresh_accounts_threaded(
                accounts,
                timeout=timeout,
                debug=debug,
                on_update=on_update,
            )
            accounts = refreshed_accounts
            if updated_any:
                store["accounts"] = accounts
                save_store(store_path, store)
            last_capture_time = _capture_timestamp()
            if dump_json and json_output_dir is not None:
                _write_json_api_snapshots(results, json_output_dir)
            if auto_refresh:
                next_refresh_at = time.time() + AUTO_REFRESH_SECONDS

            _render_tui(
                results,
                completed=len(accounts),
                total=len(accounts),
                refreshing=False,
                auto_refresh=auto_refresh,
                next_refresh_at=next_refresh_at,
                last_capture_time=last_capture_time,
            )

            while True:
                wait_seconds = 0.2
                if auto_refresh and next_refresh_at is not None:
                    now = time.time()
                    if now >= next_refresh_at:
                        break
                    wait_seconds = max(0.0, min(0.2, next_refresh_at - now))
                key = _poll_keypress(wait_seconds)
                if key is None:
                    if auto_refresh:
                        _render_tui(
                            results,
                            completed=len(accounts),
                            total=len(accounts),
                            refreshing=False,
                            auto_refresh=auto_refresh,
                            next_refresh_at=next_refresh_at,
                            last_capture_time=last_capture_time,
                        )
                    continue
                if key == "q":
                    has_success = any(item.get("status") == "ok" for item in results)
                    return 0 if has_success else 1
                if key == " ":
                    if auto_refresh:
                        next_refresh_at = time.time() + AUTO_REFRESH_SECONDS
                    break
                if key.lower() == "w":
                    auto_refresh = not auto_refresh
                    next_refresh_at = (
                        time.time() + AUTO_REFRESH_SECONDS if auto_refresh else None
                    )
                    _render_tui(
                        results,
                        completed=len(accounts),
                        total=len(accounts),
                        refreshing=False,
                        auto_refresh=auto_refresh,
                        next_refresh_at=next_refresh_at,
                        last_capture_time=last_capture_time,
                    )

def _handle_show_usage(
    store_path: Path,
    timeout: float,
    dump_json: bool,
    print_json: bool,
    debug: bool,
    *,
    json_output_dir: Path | None,
) -> int:
    store = load_store(store_path)
    accounts = store.get("accounts", [])
    if not accounts:
        _eprint(f"No accounts found in {store_path}. Add one with --add-account.")
        return 1

    refreshed_accounts, results, updated = _refresh_accounts_threaded(
        accounts,
        timeout=timeout,
        debug=debug,
    )

    if updated:
        store["accounts"] = refreshed_accounts
        save_store(store_path, store)

    written_paths: list[Path] = []
    if dump_json and json_output_dir is not None:
        written_paths = _write_json_api_snapshots(results, json_output_dir)

    sorted_results = sorted(results, key=lambda item: _result_sort_key(item))
    capture_time = _capture_timestamp()
    if print_json:
        print(
            json.dumps(
                _format_usage_json(sorted_results, last_capture_time=capture_time),
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(_format_text_usage(sorted_results, last_capture_time=capture_time))
    if written_paths:
        _eprint(f"Saved {len(written_paths)} JSON snapshot files to {json_output_dir}.")

    has_success = any(item["status"] == "ok" for item in results)
    return 0 if has_success else 1


def main(argv: list[str] | None = None) -> int:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    parser = _build_parser()
    args = parser.parse_args(argv_list)
    store_path = _resolve_store_path(args.auth_file)
    json_output_dir = Path(JSON_OUTPUT_DIR_NAME) if args.dump_json else None

    try:
        if not argv_list:
            args.show_usage = True
        if not args.add_account and not args.show_usage and not args.tui:
            _eprint("Choose one mode: --add-account, --show-usage, or --tui.")
            return 2
        if args.add_account and (args.show_usage or args.tui):
            _eprint("--add-account cannot be combined with --show-usage/--tui.")
            return 2

        if args.add_account:
            return _handle_add_account(
                store_path,
                timeout=float(args.timeout),
                no_open=args.no_open,
                debug=args.debug,
                dump_json=args.dump_json,
                json_output_dir=json_output_dir,
            )
        if args.tui:
            return _handle_show_usage_tui(
                store_path,
                timeout=float(args.timeout),
                debug=args.debug,
                dump_json=args.dump_json,
                print_json=args.json,
                json_output_dir=json_output_dir,
            )
        return _handle_show_usage(
            store_path,
            timeout=float(args.timeout),
            dump_json=args.dump_json,
            print_json=args.json,
            debug=args.debug,
            json_output_dir=json_output_dir,
        )
    except KeyboardInterrupt:
        _eprint("Interrupted.")
        return 130
    except Exception as exc:
        _eprint(str(exc))
        return 1
