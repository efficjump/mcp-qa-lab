from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from mcp_qa_lab.models import Inspection, TargetSpec
from mcp_qa_lab.server import _parse_json_object, create_server
from mcp_qa_lab.store import TargetStore


def structured(result: object) -> Any:
    assert isinstance(result, tuple)
    payload = result[1]
    assert isinstance(payload, dict)
    if set(payload) == {"result"}:
        return payload["result"]
    return payload


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def inspect(self, target: TargetSpec) -> Inspection:
        return Inspection(
            target_id=target.target_id,
            server={"name": target.name, "version": "1"},
            capabilities={"tools": {}},
            tools=[
                {
                    "name": "read",
                    "description": "Read reviewed fixture data without changing external state.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                    },
                    "annotations": {"readOnlyHint": True, "destructiveHint": False},
                },
                {
                    "name": "write",
                    "description": "Write reviewed fixture data after explicit user approval.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                    },
                    "annotations": {"readOnlyHint": False, "destructiveHint": True},
                },
            ],
            prompts=[],
            resources=[],
            resource_templates=[],
        )

    async def call(
        self, target: TargetSpec, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append((name, arguments))
        return {"isError": False, "structuredContent": {"value": arguments.get("value")}}


@pytest.mark.asyncio
async def test_server_workflow(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MCP_QA_ALLOWED_ROOTS", str(tmp_path))
    store = TargetStore(tmp_path / "state")
    fake = FakeClient()
    server = create_server(store=store, client=fake)  # type: ignore[arg-type]

    registered = structured(
        await server.call_tool(
            "register_target",
            {
                "name": "Fixture",
                "transport": "stdio",
                "command": "python",
                "cwd": str(tmp_path),
            },
        )
    )
    target_id = registered["target_id"]
    targets = structured(await server.call_tool("list_targets", {}))
    inspected = structured(await server.call_tool("inspect_target", {"target_id": target_id}))
    checked = structured(await server.call_tool("run_static_checks", {"target_id": target_id}))
    cost = structured(await server.call_tool("measure_context_cost", {"target_id": target_id}))
    evidence = structured(
        await server.call_tool(
            "run_target_tool",
            {"target_id": target_id, "tool_name": "read", "arguments": {"value": "ok"}},
        )
    )
    report = structured(await server.call_tool("build_report", {"target_id": target_id}))

    assert targets[0]["target_id"] == target_id
    assert inspected["server"]["name"] == "Fixture"
    assert checked["errors"] == 0
    assert cost["tool_count"] == 2
    assert evidence["result"]["structuredContent"]["value"] == "ok"
    assert Path(report["report_path"]).is_file()


@pytest.mark.asyncio
async def test_server_blocks_unapproved_side_effects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MCP_QA_ALLOWED_ROOTS", str(tmp_path))
    store = TargetStore(tmp_path / "state")
    fake = FakeClient()
    target = store.register(
        name="Fixture",
        transport="stdio",
        command="python",
        cwd=str(tmp_path),
    )
    server = create_server(store=store, client=fake)  # type: ignore[arg-type]

    with pytest.raises(ToolError, match="allow_side_effects"):
        await server.call_tool(
            "run_target_tool",
            {"target_id": target.target_id, "tool_name": "write", "arguments": {}},
        )
    approved = structured(
        await server.call_tool(
            "run_target_tool",
            {
                "target_id": target.target_id,
                "tool_name": "write",
                "arguments": {"value": "approved"},
                "allow_side_effects": True,
            },
        )
    )
    assert approved["is_error"] is False
    assert fake.calls == [("write", {"value": "approved"})]


@pytest.mark.asyncio
async def test_server_scenario_fallback_unknown_tool_and_truncation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MCP_QA_ALLOWED_ROOTS", str(tmp_path))
    monkeypatch.setenv("MCP_QA_MAX_RESULT_CHARS", "10")
    store = TargetStore(tmp_path / "state")
    target = store.register(
        name="Fixture",
        transport="stdio",
        command="python",
        cwd=str(tmp_path),
    )
    server = create_server(store=store, client=FakeClient())  # type: ignore[arg-type]

    scenarios = structured(
        await server.call_tool(
            "generate_scenarios",
            {
                "target_id": target.target_id,
                "objective": "Verify safe reads",
                "maximum_scenarios": 1,
            },
        )
    )
    assert scenarios["source"] == "schema-fallback"

    with pytest.raises(ToolError, match="does not expose"):
        await server.call_tool(
            "run_target_tool",
            {"target_id": target.target_id, "tool_name": "missing", "arguments": {}},
        )
    evidence = structured(
        await server.call_tool(
            "run_target_tool",
            {
                "target_id": target.target_id,
                "tool_name": "read",
                "arguments": {"value": "long result"},
            },
        )
    )
    assert evidence["truncated"] is True
    assert evidence["result"]["truncation_reason"] == "MCP_QA_MAX_RESULT_CHARS"


@pytest.mark.asyncio
async def test_generate_scenarios_uses_sampling(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MCP_QA_ALLOWED_ROOTS", str(tmp_path))
    store = TargetStore(tmp_path / "state")
    target = store.register(name="Fixture", transport="stdio", command="python", cwd=str(tmp_path))
    server = create_server(store=store, client=FakeClient())  # type: ignore[arg-type]
    tool = server._tool_manager.get_tool("generate_scenarios")
    assert tool is not None

    class SamplingSession:
        async def create_message(self, **kwargs: Any) -> Any:
            assert kwargs["temperature"] == 0.1
            return SimpleNamespace(
                content=SimpleNamespace(
                    type="text",
                    text='{"scenarios": [{"name": "sampled"}]}',
                )
            )

    context = SimpleNamespace(session=SamplingSession())
    result = await tool.run(
        {
            "target_id": target.target_id,
            "objective": "Sample",
            "maximum_scenarios": 2,
        },
        context=context,  # type: ignore[arg-type]
        convert_result=False,
    )
    assert result["source"] == "host-sampling"


@pytest.mark.asyncio
async def test_target_resource_and_prompt(tmp_path: Path) -> None:
    store = TargetStore(tmp_path / "state")
    server = create_server(store=store, client=FakeClient())  # type: ignore[arg-type]

    resource = await server.read_resource("qa://targets")
    prompts = await server.list_prompts()

    assert resource[0].content == "[]"
    assert any(prompt.name == "audit_target_prompt" for prompt in prompts)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"b": 2}\n```', {"b": 2}),
        ('prefix {"c": 3} suffix', {"c": 3}),
    ],
)
def test_parse_json_object(value: str, expected: dict[str, int]) -> None:
    assert _parse_json_object(value) == expected


@pytest.mark.parametrize("value", ["[]", "no object"])
def test_parse_json_object_rejects_invalid(value: str) -> None:
    with pytest.raises(ValueError):
        _parse_json_object(value)
