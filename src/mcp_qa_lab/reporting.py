"""Durable Markdown reports built only from redacted evidence."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from mcp_qa_lab.models import CheckSummary, ContextCost, Inspection
from mcp_qa_lab.security import redact


def build_markdown(
    inspection: Inspection,
    checks: CheckSummary,
    cost: ContextCost,
) -> str:
    """Render a stable report suitable for review and version control."""

    safe_inspection = redact(inspection.model_dump(mode="json"))
    generated = datetime.now(UTC).isoformat()
    lines = [
        f"# MCP QA report: {safe_inspection['server'].get('name', inspection.target_id)}",
        "",
        f"- Generated: `{generated}`",
        f"- Target ID: `{inspection.target_id}`",
        f"- Tools: `{len(inspection.tools)}`",
        f"- Prompts: `{len(inspection.prompts)}`",
        f"- Resources: `{len(inspection.resources)}`",
        f"- Findings: `{checks.finding_count}` "
        f"({checks.errors} errors, {checks.warnings} warnings, {checks.infos} infos)",
        f"- Approximate tool-contract tokens: `{cost.approximate_tokens}`",
        "",
        "## Findings",
        "",
    ]
    if not checks.findings:
        lines.append("No deterministic contract findings were detected.")
    for finding in checks.findings:
        lines.extend(
            [
                f"### {finding.severity.upper()} · `{finding.code}`",
                "",
                finding.message,
                "",
                f"Location: `{finding.location}`",
            ]
        )
        if finding.evidence:
            lines.extend(
                [
                    "",
                    "```json",
                    json.dumps(
                        redact(finding.evidence), ensure_ascii=False, indent=2, sort_keys=True
                    ),
                    "```",
                ]
            )
        if finding.recommendation:
            lines.extend(["", f"Recommendation: {finding.recommendation}"])
        lines.append("")
    lines.extend(
        [
            "## Largest tool contracts",
            "",
            "| Tool | Characters |",
            "|---|---:|",
            *[f"| `{item['name']}` | {item['characters']} |" for item in cost.largest_tools],
            "",
            "## Captured server contract",
            "",
            "<details>",
            "<summary>Redacted protocol metadata</summary>",
            "",
            "```json",
            json.dumps(safe_inspection, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "</details>",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(directory: Path, target_id: str, markdown: str) -> Path:
    """Write a report using a collision-resistant UTC timestamp."""

    safe_target = re.sub(r"[^a-z0-9-]", "-", target_id.lower()).strip("-") or "target"
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{safe_target}-{stamp}.md"
    path.write_text(markdown, encoding="utf-8")
    return path
