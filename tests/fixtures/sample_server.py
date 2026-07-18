from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

mcp = FastMCP("QA Fixture", instructions="A deterministic integration-test target.")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def echo(message: str) -> dict[str, str]:
    """Return the supplied message unchanged for transport verification."""

    return {"message": message}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True))
def mutate(value: str) -> dict[str, str]:
    """Pretend to mutate state so approval behavior can be verified safely."""

    return {"value": value}


@mcp.resource("fixture://status")
def status() -> str:
    return "ready"


@mcp.prompt()
def verify_fixture() -> str:
    return "Call echo with a reviewed value."


if __name__ == "__main__":
    mcp.run(transport="stdio")
