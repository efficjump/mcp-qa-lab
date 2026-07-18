import json
from pathlib import Path

import pytest

from mcp_qa_lab.store import TargetStore


def test_register_round_trip_is_stable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MCP_QA_ALLOWED_ROOTS", str(tmp_path))
    store = TargetStore(tmp_path / "state")

    first = store.register(
        name="Example Server",
        transport="stdio",
        command="python",
        args=["server.py"],
        cwd=str(tmp_path),
        env_names=["SECOND_TOKEN", "FIRST_TOKEN", "FIRST_TOKEN"],
    )
    second = store.register(
        name="Example Server",
        transport="stdio",
        command="python",
        args=["server.py"],
        cwd=str(tmp_path),
        env_names=["FIRST_TOKEN", "SECOND_TOKEN"],
    )

    assert first.target_id == second.target_id
    assert store.get(first.target_id) == first
    assert store.list() == [first]
    persisted = json.loads((store.targets_dir / f"{first.target_id}.json").read_text())
    assert "secret" not in json.dumps(persisted).lower()


def test_register_http_header_env_without_value(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MCP_QA_ALLOW_REMOTE", "1")
    store = TargetStore(tmp_path / "state")
    target = store.register(
        name="Remote",
        transport="streamable-http",
        url="https://example.com/mcp",
        header_env={"Authorization": "REMOTE_AUTH"},
    )

    assert target.header_env == {"Authorization": "REMOTE_AUTH"}
    assert "REMOTE_AUTH" in (store.targets_dir / f"{target.target_id}.json").read_text()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"name": "", "transport": "stdio", "command": "python"}, "empty"),
        ({"name": "x", "transport": "stdio"}, "require command"),
        (
            {
                "name": "x",
                "transport": "stdio",
                "command": "python\nrm",
            },
            "control character",
        ),
        (
            {
                "name": "x",
                "transport": "stdio",
                "command": "python",
                "env_names": ["bad-name"],
            },
            "environment",
        ),
        (
            {
                "name": "x",
                "transport": "streamable-http",
                "url": "http://localhost/mcp",
                "header_env": {"Bad:Header": "TOKEN"},
            },
            "header",
        ),
    ],
)
def test_rejects_invalid_registrations(
    tmp_path: Path, kwargs: dict[str, object], message: str
) -> None:
    store = TargetStore(tmp_path / "state")
    with pytest.raises(ValueError, match=message):
        store.register(**kwargs)  # type: ignore[arg-type]


def test_get_rejects_traversal_and_unknown_id(tmp_path: Path) -> None:
    store = TargetStore(tmp_path / "state")
    with pytest.raises(ValueError, match="identifier"):
        store.get("../escape")
    with pytest.raises(KeyError, match="unknown"):
        store.get("valid-but-missing")
