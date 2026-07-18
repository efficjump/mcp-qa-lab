# Security policy

## Trust boundary

MCP QA Lab launches or connects to software supplied by the user. A target server can execute code,
emit hostile model-facing text, return secrets, or mutate external systems. Run the lab in a sandbox
when testing untrusted servers.

The lab does not use a shell to launch stdio targets. Command and argument arrays are passed directly
to the official MCP client transport. Remote connections default to loopback hosts. Tool execution is
separate from inspection and requires explicit approval for tools that are not annotated read-only.

## Credential handling

Target registrations contain environment variable names, never values. Values are resolved from the
lab process only while a target is running. Reports pass through recursive redaction before writing.
Do not embed credentials in URLs or command arguments.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub private vulnerability reporting
after the repository is published. Until then, contact the maintainer privately with reproduction
steps, affected versions, and expected impact.
