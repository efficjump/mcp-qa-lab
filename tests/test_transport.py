import sys
from pathlib import Path

import pytest

from mcp_qa_lab.models import TargetSpec
from mcp_qa_lab.transport import TargetClient


@pytest.mark.asyncio
async def test_stdio_inspection_and_call() -> None:
    root = Path(__file__).parents[1]
    target = TargetSpec(
        target_id="fixture-123",
        name="Fixture",
        transport="stdio",
        command=sys.executable,
        args=[str(root / "tests" / "fixtures" / "sample_server.py")],
        cwd=str(root),
    )
    client = TargetClient(timeout_seconds=10)

    inspection = await client.inspect(target)
    result = await client.call(target, "echo", {"message": "hello"})

    assert inspection.server["name"] == "QA Fixture"
    assert {tool["name"] for tool in inspection.tools} == {"echo", "mutate"}
    assert inspection.prompts[0]["name"] == "verify_fixture"
    assert inspection.resources[0]["uri"] == "fixture://status"
    assert result["isError"] is False
    assert result["structuredContent"] == {"message": "hello"}


def test_timeout_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        TargetClient(0)
