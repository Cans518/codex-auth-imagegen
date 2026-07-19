---
name: codex-auth-imagegen
description: Run Codex's bundled Image Gen CLI with the active provider URL from config.toml and OPENAI_API_KEY from auth.json, passed directly to OpenAI clients without environment variables. Use when the user requests image generation, editing, or batch generation through their configured Codex provider; requests a non-environment-variable Image Gen credential adapter; or needs a redacted diagnosis of that adapter.
---

# Codex Auth ImageGen

Use this plugin only to change how the bundled Image Gen CLI receives credentials. Preserve the
system `imagegen` skill's prompt, model, transparency, output, and validation rules.

## Quiet fast path

1. Read the system `imagegen` skill before making an Image Gen call.
2. For an ordinary opaque generation or edit, stop reading there. Do not load the system skill's
   sample prompts, CLI reference, API reference, or network guide merely because this adapter wraps
   the bundled CLI. Read a referenced file only when the chosen workflow needs details absent from
   `SKILL.md` or the user explicitly asks about those details.
3. Resolve the plugin root as two directories above this `SKILL.md` file.
4. Run `<plugin-root>/scripts/codex_config_imagegen.py` with Python 3.11 or newer and forward the
   required Image Gen arguments.
5. Inspect each finished image once and run at most one combined local metadata check after all
   requested outputs exist.

For the normal path, do not preflight with `--diagnose`, `--help`, `--dry-run`, provider probes,
dependency probes, or output-directory listings. Use `--diagnose` only when the user requests a
diagnosis or after a local adapter/configuration error. Use `--help` only when a required forwarded
argument cannot be determined from the system skill.

If the environment already states that outbound network access needs approval, request approval on
the first live call. Do not make a network probe that is expected to fail. If approval is denied or
the provider is blocked, report that result briefly and do not retry through a workaround.

Keep tool and chat output small:

- Give one short security note before the first live call; do not repeat credential details at each
  phase.
- Do not print whole reference files, CLI help, configuration files, or raw tracebacks into the
  conversation.
- Use inline `--prompt` by default. If a long or multiline prompt needs `--prompt-file` to keep the
  live command compact, create a unique file in the operating system's temporary directory outside
  the workspace and delete that exact file in a `finally` block after success or failure.
- Do not paste the full final prompt into the handoff unless the user asks for it; report a concise
  prompt summary and the saved paths.
- Run one adapter call per requested asset unless the system skill and the user's request select the
  CLI batch workflow.

Keep the workspace flat and clean:

- Do not create a workspace `tmp/` directory. Keep required scratch prompt or batch input files in
  the operating system's temporary directory and guarantee cleanup in the controlling command.
- Delete only scratch files created for the current request. Never delete pre-existing user files or
  directories while cleaning up.
- Save final assets directly as `output/<semantic-filename>.<ext>` by default. Keep all requested
  outputs in that single directory, including batch results.
- Do not create task, date, model, `imagegen`, or `batch` subdirectories under `output/` unless the
  user explicitly requests a nested layout or the consuming project already requires one.
- Before finishing, verify that no scratch file or agent-created temporary directory remains.

The adapter is quiet by default. Add `--verbose-status` before the Image Gen subcommand only when
adapter status is useful. Add `--verbose-errors` only for an explicit diagnostic request; otherwise
failures stay concise and do not emit a Python traceback.

## Run the adapter

Example:

```text
python <plugin-root>/scripts/codex_config_imagegen.py generate \
  --prompt "A quiet alpine lake at dawn" \
  --out output/alpine-lake.png
```

For a non-default Codex directory, put the adapter-only option before the Image Gen arguments:

```text
python <plugin-root>/scripts/codex_config_imagegen.py \
  --codex-home <path-to-codex-home> \
  generate --prompt "A quiet alpine lake" --out output/lake.png
```

Run `--diagnose` for a local, redacted check. Do not make a network call during diagnosis.

Diagnostic verbosity is adapter-only and must precede the Image Gen arguments:

```text
python <plugin-root>/scripts/codex_config_imagegen.py \
  --verbose-status --verbose-errors \
  generate --prompt-file <system-temp>/codex-imagegen-prompt.txt --out output/image.png
```

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
- Keep final assets directly under the current workspace's `output/` directory unless the user
  specifies another destination or an established consuming project requires a nested path.

## Credential mapping

- URL: `<codex-home>/config.toml` -> `model_provider` ->
  `model_providers.<active-provider>.base_url`
- Key: `<codex-home>/auth.json` -> `OPENAI_API_KEY`

Re-read both files for every adapter process so configuration changes apply on the next call.
