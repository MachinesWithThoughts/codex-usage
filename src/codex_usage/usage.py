from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

WHAM_USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
WEEKLY_RESET_GAP_SECONDS = 3 * 24 * 60 * 60


def _clamp_percent(value: Any) -> float:
    if isinstance(value, (int, float)):
        return max(0.0, min(100.0, float(value)))
    if isinstance(value, str):
        try:
            parsed = float(value)
            return max(0.0, min(100.0, parsed))
        except ValueError:
            return 0.0
    return 0.0


def _resolve_secondary_window_label(
    window_hours: int,
    secondary_reset_at: int | None,
    primary_reset_at: int | None,
) -> str:
    if window_hours >= 168:
        return "Week"
    if window_hours < 24:
        return f"{window_hours}h"
    if (
        isinstance(secondary_reset_at, int)
        and isinstance(primary_reset_at, int)
        and secondary_reset_at - primary_reset_at >= WEEKLY_RESET_GAP_SECONDS
    ):
        return "Week"
    return "Day"


def fetch_usage(access_token: str, account_id: str | None, timeout: float) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "User-Agent": "CodexBar",
        "Accept": "application/json",
    }
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id

    req = urllib.request.Request(WHAM_USAGE_URL, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"usage request failed ({exc.code}): {' '.join(body.split())}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"usage request failed: {exc.reason}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid usage JSON response: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("invalid usage response shape")

    primary = (data.get("rate_limit") or {}).get("primary_window") if isinstance(data.get("rate_limit"), dict) else None
    secondary = (data.get("rate_limit") or {}).get("secondary_window") if isinstance(data.get("rate_limit"), dict) else None

    windows: list[dict[str, Any]] = []

    if isinstance(primary, dict):
        window_hours = round(float(primary.get("limit_window_seconds", 10800)) / 3600)
        reset_at = primary.get("reset_at")
        windows.append(
            {
                "label": f"{window_hours}h",
                "used_percent": _clamp_percent(primary.get("used_percent", 0)),
                "reset_at_ms": int(reset_at) * 1000 if isinstance(reset_at, (int, float)) else None,
            }
        )

    if isinstance(secondary, dict):
        window_hours = round(float(secondary.get("limit_window_seconds", 86400)) / 3600)
        secondary_reset = int(secondary["reset_at"]) if isinstance(secondary.get("reset_at"), (int, float)) else None
        primary_reset = int(primary["reset_at"]) if isinstance(primary, dict) and isinstance(primary.get("reset_at"), (int, float)) else None
        label = _resolve_secondary_window_label(window_hours, secondary_reset, primary_reset)
        windows.append(
            {
                "label": label,
                "used_percent": _clamp_percent(secondary.get("used_percent", 0)),
                "reset_at_ms": secondary_reset * 1000 if isinstance(secondary_reset, int) else None,
            }
        )

    plan_type = data.get("plan_type")
    plan = plan_type if isinstance(plan_type, str) and plan_type.strip() else None
    credits = data.get("credits")
    if isinstance(credits, dict) and credits.get("balance") is not None:
        balance_raw = credits.get("balance")
        try:
            balance = float(balance_raw)
            money = f"${balance:.2f}"
            plan = f"{plan} ({money})" if plan else money
        except (TypeError, ValueError):
            pass

    return {
        "windows": windows,
        "plan": plan,
        "raw": data,
    }


def format_reset(reset_at_ms: int | None) -> str:
    if not isinstance(reset_at_ms, int) or reset_at_ms <= 0:
        return "unknown"
    dt = datetime.fromtimestamp(reset_at_ms / 1000, tz=timezone.utc).replace(microsecond=0)
    return dt.isoformat().replace("+00:00", "Z")
