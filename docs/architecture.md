# Architecture

MCP QA Lab deliberately separates four concerns:

1. `TargetStore` validates and persists versioned target registrations.
2. `TargetClient` owns short-lived stdio or Streamable HTTP sessions.
3. `ContractAnalyzer` performs deterministic checks over live MCP metadata.
4. `server.py` exposes small, structured MCP tools and optional host-model sampling.

Target sessions are short-lived so a failed or hostile server cannot poison later inspections. Static
checks operate on serialized protocol models, which also makes reports reproducible. Scenario
generation uses MCP sampling when the host supports it and falls back to a schema-derived scenario
without pretending that a model was consulted.

The project is local-first. The state directory defaults to `.mcp-qa-lab` and can be changed with
`MCP_QA_STATE_DIR`. No telemetry is emitted.
