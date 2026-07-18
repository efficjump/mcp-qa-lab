"""Short-lived MCP client sessions for registered targets."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import timedelta
from typing import Any, TypeVar

import httpx
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, get_default_environment, stdio_client
from mcp.client.streamable_http import streamable_http_client

from mcp_qa_lab.models import Inspection, TargetSpec

T = TypeVar("T")


class TargetClient:
    """Connect to one target and capture a complete, paginated MCP contract."""

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout = timedelta(seconds=timeout_seconds)

    @asynccontextmanager
    async def session(self, target: TargetSpec) -> AsyncIterator[ClientSession]:
        """Create and initialize a target session, closing every resource on exit."""

        async with AsyncExitStack() as stack:
            if target.transport == "stdio":
                environment = get_default_environment()
                missing = [name for name in target.env_names if name not in os.environ]
                if missing:
                    raise ValueError(f"missing target environment variables: {', '.join(missing)}")
                environment.update({name: os.environ[name] for name in target.env_names})
                parameters = StdioServerParameters(
                    command=target.command or "",
                    args=target.args,
                    env=environment,
                    cwd=target.cwd,
                )
                read_stream, write_stream = await stack.enter_async_context(
                    stdio_client(parameters)
                )
            else:
                missing = [name for name in target.header_env.values() if name not in os.environ]
                if missing:
                    raise ValueError(
                        f"missing HTTP header environment variables: {', '.join(missing)}"
                    )
                headers = {
                    header: os.environ[env_name] for header, env_name in target.header_env.items()
                }
                http_client = await stack.enter_async_context(
                    httpx.AsyncClient(headers=headers, timeout=self.timeout.total_seconds())
                )
                read_stream, write_stream, _ = await stack.enter_async_context(
                    streamable_http_client(str(target.url), http_client=http_client)
                )
            session = await stack.enter_async_context(
                ClientSession(read_stream, write_stream, read_timeout_seconds=self.timeout)
            )
            yield session

    async def inspect(self, target: TargetSpec) -> Inspection:
        """Capture server metadata and every paginated model-facing primitive."""

        async with self.session(target) as session:
            initialized = await session.initialize()
            tools = await self._collect(session.list_tools, "tools")
            prompts = await self._collect(session.list_prompts, "prompts")
            resources = await self._collect(session.list_resources, "resources")
            templates = await self._collect(
                session.list_resource_templates,
                "resourceTemplates",
            )
        return Inspection(
            target_id=target.target_id,
            server=initialized.serverInfo.model_dump(mode="json", by_alias=True),
            capabilities=initialized.capabilities.model_dump(mode="json", by_alias=True),
            tools=tools,
            prompts=prompts,
            resources=resources,
            resource_templates=templates,
        )

    async def call(
        self, target: TargetSpec, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Call one explicitly approved target tool and serialize the protocol result."""

        async with self.session(target) as session:
            await session.initialize()
            result = await session.call_tool(name, arguments)
        return result.model_dump(mode="json", by_alias=True)

    @staticmethod
    async def _collect(
        operation: Callable[..., Coroutine[Any, Any, T]],
        collection_field: str,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            page = await operation(cursor=cursor)
            raw_items = getattr(page, collection_field)
            items.extend(item.model_dump(mode="json", by_alias=True) for item in raw_items)
            cursor = getattr(page, "nextCursor", None)
            if not cursor:
                return items
