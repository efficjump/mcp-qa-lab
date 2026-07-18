"""Typed model-facing contracts used by MCP QA Lab."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

Transport = Literal["stdio", "streamable-http"]
Severity = Literal["error", "warning", "info"]


class TargetSpec(BaseModel):
    """A versioned, secret-free target registration."""

    schema_version: int = 1
    target_id: str
    name: str
    transport: Transport
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    url: HttpUrl | None = None
    cwd: str | None = None
    env_names: list[str] = Field(default_factory=list)
    header_env: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_transport_fields(self) -> TargetSpec:
        if self.transport == "stdio":
            if not self.command:
                raise ValueError("stdio targets require command")
            if self.url is not None:
                raise ValueError("stdio targets cannot define url")
        else:
            if self.url is None:
                raise ValueError("streamable-http targets require url")
            if self.command or self.args or self.cwd or self.env_names:
                raise ValueError("streamable-http targets cannot define stdio process fields")
        if self.transport == "stdio" and self.header_env:
            raise ValueError("stdio targets cannot define HTTP header environment mappings")
        return self


class Finding(BaseModel):
    """One reproducible quality observation."""

    severity: Severity
    code: str
    message: str
    location: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    recommendation: str | None = None


class Inspection(BaseModel):
    """Live target contract captured from one MCP session."""

    target_id: str
    server: dict[str, Any]
    capabilities: dict[str, Any]
    tools: list[dict[str, Any]]
    prompts: list[dict[str, Any]]
    resources: list[dict[str, Any]]
    resource_templates: list[dict[str, Any]]


class CheckSummary(BaseModel):
    """Static contract analysis result."""

    target_id: str
    finding_count: int
    errors: int
    warnings: int
    infos: int
    findings: list[Finding]


class CallEvidence(BaseModel):
    """Redacted evidence from an explicitly approved target tool call."""

    target_id: str
    tool_name: str
    is_error: bool
    elapsed_ms: float
    truncated: bool
    result: dict[str, Any]


class ContextCost(BaseModel):
    """Deterministic size measurements for the model-facing contract."""

    target_id: str
    utf8_bytes: int
    characters: int
    approximate_tokens: int
    tool_count: int
    largest_tools: list[dict[str, int | str]]
    exact_duplicate_descriptions: list[list[str]]
