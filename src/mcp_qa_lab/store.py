"""Atomic, versioned persistence for target registrations and reports."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from mcp_qa_lab.models import TargetSpec
from mcp_qa_lab.security import validate_cwd, validate_remote_url

_SAFE_NAME = re.compile(r"[^a-z0-9]+")


class TargetStore:
    """Persist target specs without storing credential values."""

    def __init__(self, state_dir: Path | None = None) -> None:
        configured = os.getenv("MCP_QA_STATE_DIR")
        self.state_dir = (state_dir or Path(configured or ".mcp-qa-lab")).expanduser().resolve()
        self.targets_dir = self.state_dir / "targets"
        self.reports_dir = self.state_dir / "reports"
        self.targets_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def register(
        self,
        *,
        name: str,
        transport: str,
        command: str | None = None,
        args: list[str] | None = None,
        url: str | None = None,
        cwd: str | None = None,
        env_names: list[str] | None = None,
        header_env: dict[str, str] | None = None,
    ) -> TargetSpec:
        """Validate and save one target, returning its stable content-derived identifier."""

        clean_name = name.strip()
        if not clean_name:
            raise ValueError("target name cannot be empty")
        if command and ("\x00" in command or "\n" in command):
            raise ValueError("target command contains an invalid control character")
        normalized_env = sorted(set(env_names or []))
        for env_name in normalized_env:
            if not env_name.isidentifier() or env_name.upper() != env_name:
                raise ValueError(f"invalid environment variable name: {env_name}")
        normalized_headers = dict(sorted((header_env or {}).items()))
        for header, env_name in normalized_headers.items():
            if not header or any(character in header for character in "\r\n:"):
                raise ValueError(f"invalid HTTP header name: {header!r}")
            if not env_name.isidentifier() or env_name.upper() != env_name:
                raise ValueError(f"invalid environment variable name: {env_name}")
        normalized_cwd = validate_cwd(cwd)
        if url:
            validate_remote_url(url)

        identity = json.dumps(
            {
                "name": clean_name,
                "transport": transport,
                "command": command,
                "args": args or [],
                "url": url,
                "cwd": normalized_cwd,
                "env_names": normalized_env,
                "header_env": normalized_headers,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        slug = _SAFE_NAME.sub("-", clean_name.lower()).strip("-")[:32] or "target"
        target_id = f"{slug}-{hashlib.sha256(identity.encode()).hexdigest()[:12]}"
        spec = TargetSpec.model_validate(
            {
                "target_id": target_id,
                "name": clean_name,
                "transport": transport,
                "command": command,
                "args": args or [],
                "url": url,
                "cwd": normalized_cwd,
                "env_names": normalized_env,
                "header_env": normalized_headers,
            }
        )
        self._atomic_json(self.targets_dir / f"{target_id}.json", spec.model_dump(mode="json"))
        return spec

    def get(self, target_id: str) -> TargetSpec:
        """Read a target by its validated identifier."""

        if not re.fullmatch(r"[a-z0-9-]{1,80}", target_id):
            raise ValueError("invalid target identifier")
        path = self.targets_dir / f"{target_id}.json"
        if not path.is_file():
            raise KeyError(f"unknown target: {target_id}")
        return TargetSpec.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[TargetSpec]:
        """List registrations in stable order."""

        return [
            TargetSpec.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(self.targets_dir.glob("*.json"))
        ]

    @staticmethod
    def _atomic_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
