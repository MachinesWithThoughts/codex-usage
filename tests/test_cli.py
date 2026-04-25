from __future__ import annotations

import re

from codex_usage.cli import _format_text_usage


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
