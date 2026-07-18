from typing import Any

import pytest

from mcp_qa_lab import cli


class FakeServer:
    def __init__(self) -> None:
        self.transport: str | None = None

    def run(self, *, transport: str) -> None:
        self.transport = transport


def test_parser_defaults() -> None:
    args = cli.build_parser().parse_args([])
    assert args.transport == "stdio"
    assert args.host == "127.0.0.1"


def test_main_runs_server(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeServer()

    def factory(**kwargs: Any) -> FakeServer:
        assert kwargs == {"host": "127.0.0.1", "port": 9000}
        return fake

    monkeypatch.setattr(cli, "create_server", factory)
    cli.main(["--port", "9000"])
    assert fake.transport == "stdio"


def test_main_rejects_invalid_port_and_public_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit, match="port"):
        cli.main(["--port", "0"])
    with pytest.raises(SystemExit, match="MCP_QA_ALLOW_NETWORK_BIND"):
        cli.main(["--transport", "streamable-http", "--host", "0.0.0.0"])

    fake = FakeServer()
    monkeypatch.setenv("MCP_QA_ALLOW_NETWORK_BIND", "1")
    monkeypatch.setattr(cli, "create_server", lambda **_: fake)
    cli.main(["--transport", "streamable-http", "--host", "0.0.0.0"])
    assert fake.transport == "streamable-http"
