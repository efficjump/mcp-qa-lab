"""Trust-boundary checks and recursive report redaction."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_SENSITIVE_KEY = re.compile(
    r"(?:authorization|cookie|password|passwd|secret|token|api[_-]?key|private[_-]?key)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"(?i)\b(?:bearer|basic)\s+[a-z0-9._~+/=-]{8,}")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY)[A-Z0-9_]*)=([^\s,;]+)"
)


def allowed_roots() -> list[Path]:
    """Return canonical roots in which local targets may run."""

    configured = os.getenv("MCP_QA_ALLOWED_ROOTS")
    candidates = configured.split(os.pathsep) if configured else [str(Path.cwd())]
    return [Path(item).expanduser().resolve() for item in candidates if item]


def validate_cwd(value: str | None) -> str | None:
    """Resolve and constrain a target working directory."""

    if value is None:
        return None
    candidate = Path(value).expanduser().resolve(strict=True)
    if not candidate.is_dir():
        raise ValueError(f"target cwd is not a directory: {candidate}")
    if not any(candidate == root or candidate.is_relative_to(root) for root in allowed_roots()):
        raise ValueError("target cwd is outside MCP_QA_ALLOWED_ROOTS")
    return str(candidate)


def validate_remote_url(value: str) -> None:
    """Reject embedded credentials and remote hosts unless explicitly enabled."""

    parsed = urlsplit(value)
    if parsed.username or parsed.password:
        raise ValueError("credentials must not be embedded in target URLs")
    host = (parsed.hostname or "").lower()
    loopback = host in {"localhost", "127.0.0.1", "::1"}
    if not loopback and os.getenv("MCP_QA_ALLOW_REMOTE") != "1":
        raise ValueError("remote targets require MCP_QA_ALLOW_REMOTE=1")


def redact(value: Any, key: str | None = None) -> Any:
    """Recursively remove likely credentials before data reaches a model or report."""

    if key and _SENSITIVE_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): redact(item_value, str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    if isinstance(value, str):
        without_auth = _BEARER.sub("[REDACTED_AUTH]", value)
        return _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", without_auth)
    return value
