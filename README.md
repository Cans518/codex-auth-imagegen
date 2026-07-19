# Codex Auth ImageGen

[中文说明](#中文说明)

`codex-auth-imagegen` is a distributable Codex plugin that runs the bundled Image Gen CLI with the
active provider URL in `~/.codex/config.toml` and the `OPENAI_API_KEY` stored in
`~/.codex/auth.json`.

The adapter passes both values directly to `OpenAI` and `AsyncOpenAI` in memory. It does **not** set,
read, or persist `OPENAI_API_KEY` or `OPENAI_BASE_URL` environment variables, and it does not modify
Codex's bundled `image_gen.py`.

## How it works

```text
config.toml ── active provider URL ─┐
                                   ├─> in-process adapter ─> bundled Image Gen CLI ─> provider
auth.json ─── OPENAI_API_KEY ──────┘
```

The adapter dynamically loads the bundled CLI and replaces only its credential check and client
constructors for the current process. Generation, editing, batching, model validation, prompt
augmentation, and output handling remain owned by the bundled Image Gen CLI.

## Requirements

- Codex with the bundled system `imagegen` skill
- Python 3.11 or newer
- The OpenAI Python package for live calls: `python -m pip install -r requirements.txt`
- An active `model_provider` with `base_url` in `~/.codex/config.toml`
- A top-level `OPENAI_API_KEY` in `~/.codex/auth.json`

Never commit `config.toml`, `auth.json`, API keys, generated credential dumps, or `.env` files.

## Install as a local marketplace

Clone the repository, then run from its root:

```powershell
codex plugin marketplace add .
codex plugin add codex-auth-imagegen@codex-auth-imagegen
```

Start a new Codex thread after installation so the skill is discovered.

To update after pulling a new release:

```powershell
codex plugin marketplace upgrade codex-auth-imagegen
codex plugin add codex-auth-imagegen@codex-auth-imagegen
```

Use `codex plugin marketplace --help` if your Codex build uses different update syntax.

## Diagnose without a network call

From the repository root:

```powershell
python plugins/codex-auth-imagegen/scripts/codex_config_imagegen.py --diagnose
```

For a non-default Codex directory:

```powershell
python plugins/codex-auth-imagegen/scripts/codex_config_imagegen.py `
  --codex-home D:\path\to\.codex `
  --diagnose
```

Diagnosis prints provider metadata and key presence only. It never prints the key.

Do not use diagnosis or `--help` as a preflight for routine generation. The normal adapter path is
quiet and reads the current configuration on every call.

## Direct CLI use

All unrecognized arguments are forwarded to the bundled Image Gen CLI:

```powershell
python plugins/codex-auth-imagegen/scripts/codex_config_imagegen.py generate `
  --prompt "A quiet alpine lake at dawn" `
  --quality high `
  --size 1536x1024 `
  --out output/alpine-lake.png
```

Batch generation and editing use the same arguments as the bundled CLI:

```powershell
python plugins/codex-auth-imagegen/scripts/codex_config_imagegen.py generate-batch `
  --input <system-temp>/codex-imagegen-prompts.jsonl `
  --out-dir output
```

Create batch input files in the operating system's temporary directory and remove the exact files
in a `finally` block after success or failure. Do not create a workspace `tmp/` directory. Unless a
project or user explicitly requires nesting, keep all final images directly under `output/` with
unique semantic filenames.

### Keep Codex output concise

- For normal requests, call the adapter directly without first running `--diagnose`, `--help`, or
  provider probes.
- For a long or multiline prompt, use a unique file in the operating system's temporary directory
  with `--prompt-file`, then delete that file after the call even when the call fails.
- Adapter credential status is silent by default. Put `--verbose-status` before the Image Gen
  subcommand only when you need the redacted provider summary.
- Unexpected execution failures are one-line errors by default. Put `--verbose-errors` before the
  Image Gen subcommand only when debugging requires a Python traceback.
- If Codex already reports that network access needs approval, approve the first live generation
  call instead of making a network probe that is expected to fail.

## Security boundaries

- The plugin validates that remote provider URLs use HTTPS. Plain HTTP is accepted only for
  `localhost`, `127.0.0.1`, and `::1`.
- Credentials embedded in provider URLs are rejected.
- The API key is never added to command-line arguments or environment variables.
- The plugin does not decide whether a configured provider is trustworthy.
- The plugin does not bypass network approvals, sandbox restrictions, tenant policy, or provider
  allowlists. Codex may still require confirmation or block an untrusted destination.

Read [SECURITY.md](SECURITY.md) before using a third-party provider.

## Development

```powershell
python scripts/validate_repository.py
python -m unittest discover -s tests -v
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution rules.

## 中文说明

本仓库把个人 `codex-auth-imagegen` 技能整理成可克隆、可验证、可安装的 Codex Marketplace。
适配器每次运行时直接读取 Codex 当前 provider 的 URL 和 `auth.json` 中的 Key，并在内存中
显式传给 OpenAI 客户端；不创建、读取或修改 `OPENAI_*` 环境变量，也不修改系统
`image_gen.py`。

插件不会绕过 Codex 的联网审批或租户安全策略。第三方 provider 是否可信仍需由使用者和
所在组织单独判断。

## License

[MIT](LICENSE)
