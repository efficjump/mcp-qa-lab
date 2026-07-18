"""Command-line entrypoint for MCP QA Lab."""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence

from mcp_qa_lab.server import create_server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MCP QA Lab")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")
    if args.transport == "streamable-http":
        loopback = args.host in {"127.0.0.1", "::1", "localhost"}
        if not loopback and os.getenv("MCP_QA_ALLOW_NETWORK_BIND") != "1":
            raise SystemExit("non-loopback binding requires MCP_QA_ALLOW_NETWORK_BIND=1")
    server = create_server(host=args.host, port=args.port)
    server.run(transport=args.transport)


if __name__ == "__main__":
    main()
