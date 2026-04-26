from __future__ import annotations

import os
import ssl
from pathlib import Path


def _certifi_ca_bundle() -> str | None:
    try:
        import certifi
    except Exception:
        return None
    return certifi.where()


def _configured_ca_bundle() -> tuple[str | None, str | None]:
    for env_name in ("CODEX_USAGE_CA_BUNDLE", "SSL_CERT_FILE"):
        value = os.getenv(env_name)
        if isinstance(value, str) and value.strip():
            return value.strip(), env_name
    certifi_bundle = _certifi_ca_bundle()
    if certifi_bundle:
        return certifi_bundle, "certifi"
    return None, None


def build_ssl_context() -> ssl.SSLContext:
    ca_bundle, source = _configured_ca_bundle()
    if ca_bundle is None:
        return ssl.create_default_context()

    bundle_path = Path(ca_bundle).expanduser()
    if not bundle_path.exists() or not bundle_path.is_file():
        raise RuntimeError(f"Configured CA bundle from {source} was not found: {bundle_path}")

    return ssl.create_default_context(cafile=str(bundle_path))
