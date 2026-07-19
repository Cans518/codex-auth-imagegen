# Security policy

## Credential handling

This repository must never contain real credentials. Do not commit:

- `auth.json` or `config.toml`
- API keys, bearer tokens, cookies, or authorization headers
- `.env` files or diagnostic output containing secrets
- generated images that unintentionally contain private source material

The adapter reads credentials from the local Codex files and passes them directly to OpenAI client
constructors. The API key is excluded from dataclass representations, command arguments, environment
variables, and normal diagnostics.

## Provider trust

An HTTPS URL is not automatically trustworthy. Before using a custom provider, verify its operator,
privacy policy, retention behavior, TLS configuration, and authorization to receive your key.

This plugin does not bypass Codex approvals, sandboxing, tenant policy, or domain allowlists. Do not
modify the plugin to evade those controls.

## Reporting a vulnerability

Use a private security advisory in the repository hosting service when available. Do not include a
working API key or private `auth.json` content in a report. Provide a minimal redacted reproduction,
affected version, expected behavior, and observed behavior.
