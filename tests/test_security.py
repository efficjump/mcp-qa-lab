from pathlib import Path

import pytest

from mcp_qa_lab.security import redact, validate_cwd, validate_remote_url


def test_recursive_redaction_hides_keys_headers_and_assignments() -> None:
    value = {
        "Authorization": "Bearer abcdefghijklmnop",
        "nested": ["API_TOKEN=visible-no-more", {"password": "secret"}],
        "safe": "hello",
    }

    result = redact(value)

    assert result["Authorization"] == "[REDACTED]"
    assert result["nested"][0] == "API_TOKEN=[REDACTED]"
    assert result["nested"][1]["password"] == "[REDACTED]"
    assert result["safe"] == "hello"

    assert redact(("safe", "Bearer abcdefgh")) == ["safe", "[REDACTED_AUTH]"]
    assert redact(42) == 42


def test_validate_cwd_constrains_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    monkeypatch.setenv("MCP_QA_ALLOWED_ROOTS", str(allowed))

    assert validate_cwd(str(allowed)) == str(allowed.resolve())
    with pytest.raises(ValueError, match="outside"):
        validate_cwd(str(outside))
    assert validate_cwd(None) is None


def test_remote_url_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    validate_remote_url("http://127.0.0.1:8000/mcp")
    with pytest.raises(ValueError, match="credentials"):
        validate_remote_url("https://user:secret@example.com/mcp")
    with pytest.raises(ValueError, match="MCP_QA_ALLOW_REMOTE"):
        validate_remote_url("https://example.com/mcp")
    monkeypatch.setenv("MCP_QA_ALLOW_REMOTE", "1")
    validate_remote_url("https://example.com/mcp")
