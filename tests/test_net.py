from __future__ import annotations

from pathlib import Path

import pytest

import codex_usage.net as net_module


def test_build_ssl_context_uses_env_ca_bundle(monkeypatch, tmp_path: Path) -> None:
    bundle = tmp_path / "ca.pem"
    bundle.write_text("-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_USAGE_CA_BUNDLE", str(bundle))

    calls: dict[str, str] = {}

    def fake_create_default_context(*, cafile=None):
        calls["cafile"] = cafile
        return "ctx"

    monkeypatch.setattr(net_module.ssl, "create_default_context", fake_create_default_context)

    context = net_module.build_ssl_context()
    assert context == "ctx"
    assert calls["cafile"] == str(bundle)


def test_build_ssl_context_rejects_missing_bundle(monkeypatch) -> None:
    monkeypatch.setenv("CODEX_USAGE_CA_BUNDLE", "/no/such/cert.pem")
    with pytest.raises(RuntimeError, match="Configured CA bundle"):
        net_module.build_ssl_context()


def test_build_ssl_context_uses_default_when_no_bundle(monkeypatch) -> None:
    monkeypatch.delenv("CODEX_USAGE_CA_BUNDLE", raising=False)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(net_module, "_certifi_ca_bundle", lambda: None)

    calls: dict[str, object] = {}

    def fake_create_default_context(*, cafile=None):
        calls["cafile"] = cafile
        return "ctx"

    monkeypatch.setattr(net_module.ssl, "create_default_context", fake_create_default_context)

    context = net_module.build_ssl_context()
    assert context == "ctx"
    assert calls["cafile"] is None
