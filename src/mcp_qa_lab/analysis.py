"""Deterministic analysis of a live MCP model-facing contract."""

from __future__ import annotations

import json
import math
import os
import re
from collections import defaultdict
from typing import Any

from mcp_qa_lab.models import CheckSummary, ContextCost, Finding, Inspection


class ContractAnalyzer:
    """Find structural and agent-usability risks without invoking target tools."""

    def __init__(self) -> None:
        self.minimum_description = int(os.getenv("MCP_QA_MIN_DESCRIPTION", "24"))
        self.maximum_description = int(os.getenv("MCP_QA_MAX_DESCRIPTION", "1200"))
        self.maximum_contract_chars = int(os.getenv("MCP_QA_MAX_CONTRACT_CHARS", "60000"))

    def analyze(self, inspection: Inspection) -> CheckSummary:
        """Return evidence-linked findings in stable order."""

        findings: list[Finding] = []
        names: set[str] = set()
        for index, tool in enumerate(inspection.tools):
            location = f"tools[{index}]"
            name = str(tool.get("name", ""))
            description = str(tool.get("description") or "").strip()
            schema = tool.get("inputSchema")

            if not name:
                findings.append(self._error("tool.name.missing", "Tool name is missing.", location))
            elif name in names:
                findings.append(
                    self._error(
                        "tool.name.duplicate",
                        f"Tool name {name!r} is duplicated.",
                        location,
                        {"name": name},
                    )
                )
            else:
                names.add(name)
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}", name):
                    findings.append(
                        self._warning(
                            "tool.name.portability",
                            f"Tool name {name!r} may be rejected or awkward in some clients.",
                            location,
                            {"name": name},
                            "Prefer a concise ASCII identifier beginning with a letter.",
                        )
                    )

            if not description:
                findings.append(
                    self._error(
                        "tool.description.missing",
                        f"Tool {name!r} has no model-facing description.",
                        location,
                        recommendation=(
                            "Describe when to call the tool, its outcome, and important "
                            "constraints."
                        ),
                    )
                )
            elif len(description) < self.minimum_description:
                findings.append(
                    self._warning(
                        "tool.description.short",
                        f"Tool {name!r} has a very short description.",
                        location,
                        {"characters": len(description)},
                        "Add decision-relevant constraints rather than generic marketing text.",
                    )
                )
            elif len(description) > self.maximum_description:
                findings.append(
                    self._warning(
                        "tool.description.large",
                        f"Tool {name!r} has an unusually large description.",
                        location,
                        {"characters": len(description)},
                        (
                            "Move long procedures to a prompt or resource and keep tool routing "
                            "concise."
                        ),
                    )
                )

            findings.extend(self._analyze_schema(name, schema, location))
            annotations = tool.get("annotations") or {}
            if annotations.get("readOnlyHint") is None:
                findings.append(
                    self._info(
                        "tool.annotation.read-only-unknown",
                        f"Tool {name!r} does not declare readOnlyHint.",
                        location,
                        recommendation=(
                            "Declare side-effect intent so clients can build safer approval flows."
                        ),
                    )
                )
            if annotations.get("destructiveHint") and annotations.get("readOnlyHint"):
                findings.append(
                    self._error(
                        "tool.annotation.conflict",
                        f"Tool {name!r} is marked both read-only and destructive.",
                        location,
                        {"annotations": annotations},
                    )
                )

        findings.extend(self._duplicate_description_findings(inspection.tools))
        cost = self.context_cost(inspection)
        if cost.characters > self.maximum_contract_chars:
            findings.append(
                self._warning(
                    "contract.context.large",
                    "The complete tool contract is large enough to reduce routing efficiency.",
                    "tools",
                    {
                        "characters": cost.characters,
                        "approximate_tokens": cost.approximate_tokens,
                        "configured_limit": self.maximum_contract_chars,
                    },
                    "Split optional capability groups or add dynamic tool discovery.",
                )
            )

        order = {"error": 0, "warning": 1, "info": 2}
        findings.sort(key=lambda item: (order[item.severity], item.code, item.location))
        return CheckSummary(
            target_id=inspection.target_id,
            finding_count=len(findings),
            errors=sum(item.severity == "error" for item in findings),
            warnings=sum(item.severity == "warning" for item in findings),
            infos=sum(item.severity == "info" for item in findings),
            findings=findings,
        )

    def context_cost(self, inspection: Inspection) -> ContextCost:
        """Measure serialized tool metadata without claiming exact tokenizer equivalence."""

        encoded = json.dumps(
            inspection.tools,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        per_tool: list[dict[str, int | str]] = []
        descriptions: defaultdict[str, list[str]] = defaultdict(list)
        for tool in inspection.tools:
            serialized = json.dumps(tool, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            name = str(tool.get("name", "<unnamed>"))
            per_tool.append({"name": name, "characters": len(serialized)})
            normalized = " ".join(str(tool.get("description") or "").lower().split())
            if normalized:
                descriptions[normalized].append(name)
        duplicates = sorted(
            (sorted(group) for group in descriptions.values() if len(group) > 1),
            key=lambda group: group[0],
        )
        return ContextCost(
            target_id=inspection.target_id,
            utf8_bytes=len(encoded.encode("utf-8")),
            characters=len(encoded),
            approximate_tokens=math.ceil(len(encoded) / 4),
            tool_count=len(inspection.tools),
            largest_tools=sorted(per_tool, key=lambda item: int(item["characters"]), reverse=True)[
                :10
            ],
            exact_duplicate_descriptions=duplicates,
        )

    def _analyze_schema(self, name: str, schema: Any, location: str) -> list[Finding]:
        if not isinstance(schema, dict):
            return [
                self._error(
                    "tool.schema.invalid",
                    f"Tool {name!r} inputSchema is not a JSON object.",
                    location,
                )
            ]
        findings: list[Finding] = []
        if schema.get("type") != "object":
            findings.append(
                self._error(
                    "tool.schema.root-type",
                    f"Tool {name!r} inputSchema root type is not object.",
                    location,
                    {"type": schema.get("type")},
                )
            )
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(properties, dict):
            findings.append(
                self._error(
                    "tool.schema.properties",
                    f"Tool {name!r} properties must be an object.",
                    location,
                )
            )
            return findings
        if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
            findings.append(
                self._error(
                    "tool.schema.required",
                    f"Tool {name!r} required must be a string array.",
                    location,
                )
            )
            return findings
        unknown_required = sorted(set(required) - set(properties))
        if unknown_required:
            findings.append(
                self._error(
                    "tool.schema.required-unknown",
                    f"Tool {name!r} requires parameters that are not declared.",
                    location,
                    {"parameters": unknown_required},
                )
            )
        for parameter, definition in properties.items():
            if not isinstance(definition, dict):
                findings.append(
                    self._error(
                        "tool.schema.parameter-invalid",
                        f"Parameter {parameter!r} of tool {name!r} is not a schema object.",
                        f"{location}.inputSchema.properties.{parameter}",
                    )
                )
                continue
            if not definition.get("description") and len(properties) > 1:
                findings.append(
                    self._info(
                        "tool.schema.parameter-undocumented",
                        f"Parameter {parameter!r} of tool {name!r} has no description.",
                        f"{location}.inputSchema.properties.{parameter}",
                    )
                )
        return findings

    def _duplicate_description_findings(self, tools: list[dict[str, Any]]) -> list[Finding]:
        groups: defaultdict[str, list[str]] = defaultdict(list)
        for tool in tools:
            description = " ".join(str(tool.get("description") or "").lower().split())
            if description:
                groups[description].append(str(tool.get("name", "<unnamed>")))
        return [
            self._warning(
                "tool.description.duplicate",
                "Multiple tools use an identical description, making routing ambiguous.",
                "tools",
                {"tools": sorted(names)},
                "Give each tool a distinct purpose and decision boundary.",
            )
            for names in groups.values()
            if len(names) > 1
        ]

    @staticmethod
    def _error(
        code: str,
        message: str,
        location: str,
        evidence: dict[str, Any] | None = None,
        recommendation: str | None = None,
    ) -> Finding:
        return Finding(
            severity="error",
            code=code,
            message=message,
            location=location,
            evidence=evidence or {},
            recommendation=recommendation,
        )

    @staticmethod
    def _warning(
        code: str,
        message: str,
        location: str,
        evidence: dict[str, Any] | None = None,
        recommendation: str | None = None,
    ) -> Finding:
        return Finding(
            severity="warning",
            code=code,
            message=message,
            location=location,
            evidence=evidence or {},
            recommendation=recommendation,
        )

    @staticmethod
    def _info(
        code: str,
        message: str,
        location: str,
        evidence: dict[str, Any] | None = None,
        recommendation: str | None = None,
    ) -> Finding:
        return Finding(
            severity="info",
            code=code,
            message=message,
            location=location,
            evidence=evidence or {},
            recommendation=recommendation,
        )
