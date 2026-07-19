# Contributing

Contributions are welcome when they preserve the plugin's narrow purpose: deliver the active Codex
provider URL and stored key to the bundled Image Gen clients without environment variables.

## Development rules

1. Never add credential values, telemetry, secret logging, or approval bypasses.
2. Never vendor or modify Codex's bundled `image_gen.py`.
3. Keep adapter-specific arguments separate from forwarded Image Gen arguments.
4. Preserve compatibility with Python 3.11 and newer on Windows, macOS, and Linux.
5. Add or update tests for every behavior change.

## Validate a change

```text
python scripts/validate_repository.py
python -m unittest discover -s tests -v
```

For local integration testing, use `--diagnose` and Image Gen `--dry-run` first. Never use a real
third-party provider in automated tests.
