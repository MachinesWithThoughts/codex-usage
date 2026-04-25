from __future__ import annotations

from codex_usage.cli import _format_text_usage


def test_format_text_usage_renders_table_rows() -> None:
    output = _format_text_usage(
        [
            {
                "label": "one@example.com",
                "status": "ok",
                "plan": "pro",
                "windows": [
                    {"label": "3h", "used_percent": 42.5, "reset_at_ms": 0},
                ],
            },
            {
                "label": "two@example.com",
                "status": "error",
                "error": "token expired",
            },
        ]
    )

    assert "Account" in output
    assert "Status" in output
    assert "Windows" in output
    assert "one@example.com" in output
    assert "3h 42.5% reset=unknown" in output
    assert "two@example.com" in output
    assert "token expired" in output
    assert output.count("\n") >= 5
