# Contributing

Use Python 3.11 or newer and `uv`. Keep protocol I/O in `transport.py`, model-facing analysis in
`analysis.py`, persistence in `store.py`, and MCP registration in `server.py`.

Every behavior change needs tests for the successful path and its relevant trust-boundary failure.
Run the complete quality gate documented in the README before opening a pull request. Tool names and
descriptions are compatibility surfaces; include a migration note when changing them.
