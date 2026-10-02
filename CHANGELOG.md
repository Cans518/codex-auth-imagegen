# Changelog

All notable changes to this project are documented here.

## Unreleased

- Support fixed Image 2.5 dimensions by reusing the bundled Image 2 size validator in memory.
- Preserve explicit dimensions and model IDs for generation, editing, and per-job batch validation;
  keep `auto` as the default and retain existing validation for other models.
- Add size-validation and argument-forwarding regression tests.

- Add a quiet fast path that avoids unnecessary reference, help, diagnosis, and provider probes.
- Keep adapter credential status silent unless `--verbose-status` is requested.
- Collapse unexpected execution failures to a safe one-line error unless `--verbose-errors` is
  requested.
- Recommend `--prompt-file` for long prompts so live commands stay compact.
- Keep scratch inputs outside the workspace and require cleanup after both success and failure.
- Store final images directly under a single `output/` directory unless nesting is explicitly
  requested.

## 1.0.0 - 2026-07-19

- Convert the personal skill into a distributable local Marketplace repository.
- Remove user-specific paths from the skill and adapter.
- Add explicit `--codex-home` support without environment variables.
- Pass provider URL and API key directly to synchronous and asynchronous OpenAI clients.
- Add redacted diagnosis, URL safety validation, tests, CI, and repository validation.
- Document security boundaries and third-party provider trust requirements.
