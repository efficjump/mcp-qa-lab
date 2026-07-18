from pathlib import Path

from mcp_qa_lab.analysis import ContractAnalyzer
from mcp_qa_lab.models import Inspection
from mcp_qa_lab.reporting import build_markdown, write_report


def test_report_is_redacted_and_written(tmp_path: Path) -> None:
    inspection = Inspection(
        target_id="target-123",
        server={"name": "Fixture", "version": "1", "token": "do-not-leak"},
        capabilities={},
        tools=[],
        prompts=[],
        resources=[],
        resource_templates=[],
    )
    analyzer = ContractAnalyzer()
    checks = analyzer.analyze(inspection)
    cost = analyzer.context_cost(inspection)

    markdown = build_markdown(inspection, checks, cost)
    path = write_report(tmp_path, inspection.target_id, markdown)

    assert "[REDACTED]" in markdown
    assert "do-not-leak" not in markdown
    assert path.is_file()
    assert path.read_text() == markdown


def test_report_renders_findings_and_evidence(tmp_path: Path) -> None:
    inspection = Inspection(
        target_id="Target With Spaces",
        server={"name": "Broken", "version": "1"},
        capabilities={},
        tools=[{"name": "bad", "description": "", "inputSchema": None}],
        prompts=[],
        resources=[],
        resource_templates=[],
    )
    analyzer = ContractAnalyzer()
    checks = analyzer.analyze(inspection)
    cost = analyzer.context_cost(inspection)

    markdown = build_markdown(inspection, checks, cost)
    path = write_report(tmp_path, inspection.target_id, markdown)

    assert "ERROR" in markdown
    assert "tool.description.missing" in markdown
    assert path.name.startswith("target-with-spaces-")
