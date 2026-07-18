from mcp_qa_lab.analysis import ContractAnalyzer
from mcp_qa_lab.models import Inspection


def inspection_with(tools: list[dict[str, object]]) -> Inspection:
    return Inspection(
        target_id="target-123",
        server={"name": "fixture", "version": "1"},
        capabilities={},
        tools=tools,
        prompts=[],
        resources=[],
        resource_templates=[],
    )


def test_clean_contract_has_only_missing_annotation_info() -> None:
    inspection = inspection_with(
        [
            {
                "name": "echo",
                "description": "Return the reviewed input without changing external state.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            }
        ]
    )

    result = ContractAnalyzer().analyze(inspection)

    assert result.errors == 0
    assert result.warnings == 0
    assert result.finding_count == 0


def test_analyzer_reports_ambiguous_and_invalid_contract() -> None:
    duplicate = {
        "name": "1 awkward name",
        "description": "tiny",
        "inputSchema": {
            "type": "array",
            "properties": {
                "value": {"type": "string"},
                "broken": "not-a-schema",
            },
            "required": ["missing"],
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": True},
    }
    result = ContractAnalyzer().analyze(inspection_with([duplicate, duplicate]))
    codes = {finding.code for finding in result.findings}

    assert result.errors >= 5
    assert "tool.name.portability" in codes
    assert "tool.name.duplicate" in codes
    assert "tool.description.duplicate" in codes
    assert "tool.schema.root-type" in codes
    assert "tool.schema.required-unknown" in codes
    assert "tool.schema.parameter-invalid" in codes
    assert "tool.annotation.conflict" in codes


def test_analyzer_handles_missing_and_malformed_schema() -> None:
    result = ContractAnalyzer().analyze(
        inspection_with(
            [
                {"name": "a", "description": "", "inputSchema": None},
                {
                    "name": "b",
                    "description": "A sufficiently descriptive tool for malformed properties.",
                    "inputSchema": {"type": "object", "properties": [], "required": []},
                },
                {
                    "name": "c",
                    "description": "A sufficiently descriptive tool for malformed required data.",
                    "inputSchema": {"type": "object", "properties": {}, "required": "x"},
                },
            ]
        )
    )
    codes = {finding.code for finding in result.findings}

    assert "tool.description.missing" in codes
    assert "tool.schema.invalid" in codes
    assert "tool.schema.properties" in codes
    assert "tool.schema.required" in codes
    assert "tool.annotation.read-only-unknown" in codes


def test_context_cost_finds_duplicates_and_sorts_largest() -> None:
    tools = [
        {
            "name": "small",
            "description": "Same Description",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "large",
            "description": " same   description ",
            "inputSchema": {
                "type": "object",
                "properties": {"payload": {"type": "string", "description": "x" * 100}},
            },
        },
    ]
    cost = ContractAnalyzer().context_cost(inspection_with(tools))

    assert cost.tool_count == 2
    assert cost.largest_tools[0]["name"] == "large"
    assert cost.exact_duplicate_descriptions == [["large", "small"]]
    assert cost.utf8_bytes >= cost.characters


def test_configured_contract_limit_and_large_description(
    monkeypatch,
) -> None:  # type annotation would add noise to this configuration-focused test
    monkeypatch.setenv("MCP_QA_MAX_CONTRACT_CHARS", "10")
    monkeypatch.setenv("MCP_QA_MAX_DESCRIPTION", "30")
    result = ContractAnalyzer().analyze(
        inspection_with(
            [
                {
                    "name": "large",
                    "description": (
                        "This deliberately long description exceeds the configured limit."
                    ),
                    "inputSchema": {"type": "object", "properties": {}},
                    "annotations": {"readOnlyHint": True},
                }
            ]
        )
    )

    codes = {finding.code for finding in result.findings}
    assert "tool.description.large" in codes
    assert "contract.context.large" in codes
