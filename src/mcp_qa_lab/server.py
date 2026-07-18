"""FastMCP surface for MCP QA Lab."""

from __future__ import annotations

import json
import os
import time
from typing import Annotated, Any, cast

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession
from mcp.types import SamplingMessage, TextContent, ToolAnnotations
from pydantic import Field

from mcp_qa_lab.analysis import ContractAnalyzer
from mcp_qa_lab.models import CallEvidence
from mcp_qa_lab.reporting import build_markdown, write_report
from mcp_qa_lab.security import redact
from mcp_qa_lab.store import TargetStore
from mcp_qa_lab.transport import TargetClient

INSTRUCTIONS = """
Inspect MCP servers before executing their tools. Registrations never contain secret values.
Use inspect_target and run_static_checks first. Call run_target_tool only after reviewing the
target tool annotations and arguments; side-effecting tools require explicit approval.
""".strip()

TargetId = Annotated[
    str, Field(min_length=1, description="Identifier returned by register_target.")
]
TargetName = Annotated[
    str,
    Field(min_length=1, description="Human-readable name used to identify the target in reports."),
]
TransportName = Annotated[
    str,
    Field(
        pattern="^(stdio|streamable-http)$",
        description="Connection transport: stdio or streamable-http.",
    ),
]
Command = Annotated[
    str | None,
    Field(description="Executable for a stdio target; passed directly without a shell."),
]
CommandArguments = Annotated[
    list[str] | None,
    Field(description="Argument vector for the stdio executable, without shell expansion."),
]
TargetUrl = Annotated[
    str | None,
    Field(description="Streamable HTTP MCP endpoint; remote hosts require explicit opt-in."),
]
WorkingDirectory = Annotated[
    str | None,
    Field(description="Existing stdio working directory inside MCP_QA_ALLOWED_ROOTS."),
]
EnvironmentNames = Annotated[
    list[str] | None,
    Field(description="Environment variable names to inherit; values are never stored."),
]
HeaderEnvironment = Annotated[
    dict[str, str] | None,
    Field(description="Map HTTP header names to inherited environment variable names."),
]
Objective = Annotated[
    str,
    Field(min_length=1, description="Behavior or user outcome that generated scenarios must test."),
]
ScenarioLimit = Annotated[
    int,
    Field(ge=1, le=20, description="Maximum number of scenarios to generate."),
]
TargetToolName = Annotated[
    str,
    Field(min_length=1, description="Exact tool name from the target's live tool list."),
]
TargetArguments = Annotated[
    dict[str, Any],
    Field(description="Reviewed JSON arguments passed unchanged to the target tool."),
]
SideEffectApproval = Annotated[
    bool,
    Field(description="Explicit approval for tools not annotated read-only."),
]


def create_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    store: TargetStore | None = None,
    client: TargetClient | None = None,
) -> FastMCP:
    """Build an isolated server instance for production or tests."""

    target_store = store or TargetStore()
    target_client = client or TargetClient(float(os.getenv("MCP_QA_TIMEOUT_SECONDS", "30")))
    analyzer = ContractAnalyzer()
    mcp = FastMCP(
        "MCP QA Lab",
        instructions=INSTRUCTIONS,
        host=host,
        port=port,
        json_response=True,
        stateless_http=True,
    )

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False))
    def register_target(
        name: TargetName,
        transport: TransportName,
        command: Command = None,
        args: CommandArguments = None,
        url: TargetUrl = None,
        cwd: WorkingDirectory = None,
        env_names: EnvironmentNames = None,
        header_env: HeaderEnvironment = None,
    ) -> dict[str, Any]:
        """Register a secret-free stdio or Streamable HTTP target after boundary validation."""

        return target_store.register(
            name=name,
            transport=transport,
            command=command,
            args=args,
            url=url,
            cwd=cwd,
            env_names=env_names,
            header_env=header_env,
        ).model_dump(mode="json")

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    def list_targets() -> list[dict[str, Any]]:
        """List registered targets without resolving or exposing environment values."""

        return [target.model_dump(mode="json") for target in target_store.list()]

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
    )
    async def inspect_target(target_id: TargetId) -> dict[str, Any]:
        """Connect to a target and capture its complete paginated model-facing MCP contract."""

        target = target_store.get(target_id)
        inspection = await target_client.inspect(target)
        return cast(dict[str, Any], redact(inspection.model_dump(mode="json")))

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
    )
    async def run_static_checks(target_id: TargetId) -> dict[str, Any]:
        """Analyze live schemas, descriptions, annotations, and size without tool calls."""

        inspection = await target_client.inspect(target_store.get(target_id))
        return analyzer.analyze(inspection).model_dump(mode="json")

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
    )
    async def measure_context_cost(target_id: TargetId) -> dict[str, Any]:
        """Measure serialized model-facing tool metadata and exact duplicate descriptions."""

        inspection = await target_client.inspect(target_store.get(target_id))
        return analyzer.context_cost(inspection).model_dump(mode="json")

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
    )
    async def generate_scenarios(
        target_id: TargetId,
        objective: Objective,
        ctx: Context[ServerSession, None],
        maximum_scenarios: ScenarioLimit = 5,
    ) -> dict[str, Any]:
        """Generate task-oriented multi-tool journeys using sampling, with an explicit fallback."""

        if not 1 <= maximum_scenarios <= 20:
            raise ValueError("maximum_scenarios must be between 1 and 20")
        inspection = await target_client.inspect(target_store.get(target_id))
        compact_tools = [
            {
                "name": tool.get("name"),
                "description": tool.get("description"),
                "inputSchema": tool.get("inputSchema"),
                "annotations": tool.get("annotations"),
            }
            for tool in inspection.tools
        ]
        request = {
            "objective": objective,
            "maximum_scenarios": maximum_scenarios,
            "tools": compact_tools,
            "required_output": {
                "scenarios": [
                    {
                        "name": "string",
                        "purpose": "string",
                        "steps": [{"tool": "exact tool name", "arguments": "object"}],
                        "expected_evidence": ["observable outcome"],
                        "risk_notes": ["side effect or trust concern"],
                    }
                ]
            },
        }
        try:
            sampled = await ctx.session.create_message(
                messages=[
                    SamplingMessage(
                        role="user",
                        content=TextContent(
                            type="text",
                            text=(
                                "Design realistic MCP QA scenarios from this live contract. "
                                "Use only supplied tool names, do not execute anything, and return "
                                "JSON only.\n" + json.dumps(request, ensure_ascii=False)
                            ),
                        ),
                    )
                ],
                max_tokens=2400,
                temperature=0.1,
                include_context="thisServer",
            )
            content = sampled.content
            text = content.text if getattr(content, "type", None) == "text" else str(content)
            payload = _parse_json_object(text)
            return {"source": "host-sampling", "result": payload}
        except (
            Exception
        ) as exc:  # sampling support and model output are outside this server's control
            fallback = [
                {
                    "name": f"Review {tool.get('name', '<unnamed>')}",
                    "purpose": objective,
                    "steps": [
                        {
                            "tool": tool.get("name"),
                            "required_parameters": (tool.get("inputSchema") or {}).get(
                                "required", []
                            ),
                            "arguments": "REQUIRES_REVIEW",
                        }
                    ],
                    "expected_evidence": ["Protocol result and error status"],
                    "risk_notes": ["Fallback did not infer executable arguments"],
                }
                for tool in inspection.tools[:maximum_scenarios]
            ]
            return {
                "source": "schema-fallback",
                "sampling_error": type(exc).__name__,
                "result": {"scenarios": fallback},
            }

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)
    )
    async def run_target_tool(
        target_id: TargetId,
        tool_name: TargetToolName,
        arguments: TargetArguments,
        allow_side_effects: SideEffectApproval = False,
    ) -> dict[str, Any]:
        """Execute one call; non-read-only tools require explicit side-effect approval."""

        target = target_store.get(target_id)
        inspection = await target_client.inspect(target)
        matching = [tool for tool in inspection.tools if tool.get("name") == tool_name]
        if not matching:
            raise KeyError(f"target does not expose tool: {tool_name}")
        annotations = matching[0].get("annotations") or {}
        if annotations.get("readOnlyHint") is not True and not allow_side_effects:
            raise PermissionError(
                "target tool is not explicitly read-only; set allow_side_effects=true after review"
            )
        started = time.perf_counter()
        raw = await target_client.call(target, tool_name, arguments)
        elapsed_ms = (time.perf_counter() - started) * 1000
        safe = redact(raw)
        maximum = int(os.getenv("MCP_QA_MAX_RESULT_CHARS", "50000"))
        encoded = json.dumps(safe, ensure_ascii=False)
        truncated = len(encoded) > maximum
        if truncated:
            safe = {
                "content_preview": encoded[:maximum],
                "original_characters": len(encoded),
                "truncation_reason": "MCP_QA_MAX_RESULT_CHARS",
            }
        evidence = CallEvidence(
            target_id=target_id,
            tool_name=tool_name,
            is_error=bool(raw.get("isError", False)),
            elapsed_ms=round(elapsed_ms, 3),
            truncated=truncated,
            result=safe,
        )
        return evidence.model_dump(mode="json")

    @mcp.tool(
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
    )
    async def build_report(target_id: TargetId) -> dict[str, Any]:
        """Create a redacted Markdown report from a new live inspection and deterministic checks."""

        inspection = await target_client.inspect(target_store.get(target_id))
        checks = analyzer.analyze(inspection)
        cost = analyzer.context_cost(inspection)
        markdown = build_markdown(inspection, checks, cost)
        path = write_report(target_store.reports_dir, target_id, markdown)
        return {
            "target_id": target_id,
            "report_path": str(path),
            "findings": checks.finding_count,
            "errors": checks.errors,
            "warnings": checks.warnings,
        }

    @mcp.resource("qa://targets", mime_type="application/json")
    def targets_resource() -> str:
        """Return the current secret-free target registry."""

        return json.dumps(
            [target.model_dump(mode="json") for target in target_store.list()],
            ensure_ascii=False,
            indent=2,
        )

    @mcp.prompt(title="Audit an MCP target")
    def audit_target_prompt(target_id: str) -> str:
        return (
            f"Audit target {target_id}. Inspect it, run static checks, measure context cost, "
            "generate realistic scenarios, and report gaps. Do not execute target tools unless the "
            "user separately approves the exact call and any side effects."
        )

    return mcp


def _parse_json_object(text: str) -> dict[str, Any]:
    """Extract one JSON object from plain or fenced model output."""

    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1]).strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("sampling response did not contain a JSON object") from None
        value = json.loads(stripped[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("sampling response must be a JSON object")
    return value
