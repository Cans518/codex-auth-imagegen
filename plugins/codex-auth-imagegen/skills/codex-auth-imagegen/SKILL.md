---
name: codex-auth-imagegen
description: Run Codex's bundled Image Gen CLI with the active provider URL from config.toml and OPENAI_API_KEY from auth.json, passed directly to OpenAI clients without environment variables. Use when the user requests image generation, editing, or batch generation through their configured Codex provider; requests a non-environment-variable Image Gen credential adapter; or needs a redacted diagnosis of that adapter.
---

# Codex Auth ImageGen

Use this plugin only to change how the bundled Image Gen CLI receives credentials. Preserve the
system `imagegen` skill's prompt, model, transparency, output, and validation rules.

## Run the adapter

1. Read the system `imagegen` skill before making an Image Gen call.
2. Resolve the plugin root as two directories above this `SKILL.md` file.
3. Run `<plugin-root>/scripts/codex_config_imagegen.py` with Python 3.11 or newer and forward the
   normal bundled Image Gen arguments.

Example:

```text
python <plugin-root>/scripts/codex_config_imagegen.py generate \
  --prompt "A quiet alpine lake at dawn" \
  --out output/imagegen/alpine-lake.png
```

For a non-default Codex directory, put the adapter-only option before the Image Gen arguments:

```text
python <plugin-root>/scripts/codex_config_imagegen.py \
  --codex-home <path-to-codex-home> \
  generate --prompt "A quiet alpine lake" --out output/imagegen/lake.png
```

Run `--diagnose` for a local, redacted check. Do not make a network call during diagnosis.

## Guardrails

- Never set, export, persist, echo, or print `OPENAI_API_KEY` or `OPENAI_BASE_URL`.
- Never place credentials in command arguments, prompts, JSONL files, logs, or generated assets.
- Never modify the bundled system `image_gen.py`. Let the adapter patch only its credential-check
  and client-construction functions in the current process.
- Read only the active `model_provider`, its `base_url`, and `OPENAI_API_KEY` from the standard Codex
  files. Reject missing providers, missing keys, embedded URL credentials, and unsafe non-HTTPS
  remote URLs.
- Treat every configured provider as a separate trust decision. This plugin does not suppress Codex
  network approvals or tenant policy. If a call is blocked, report it and do not work around it.
- Keep final assets in the current workspace under `output/imagegen/` unless the user specifies
  another destination.

## Credential mapping

- URL: `<codex-home>/config.toml` -> `model_provider` ->
  `model_providers.<active-provider>.base_url`
- Key: `<codex-home>/auth.json` -> `OPENAI_API_KEY`

Re-read both files for every adapter process so configuration changes apply on the next call.
