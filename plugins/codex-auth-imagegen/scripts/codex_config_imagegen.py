#!/usr/bin/env python3
"""Run Codex's bundled Image Gen CLI with credentials from Codex files.

The adapter does not create, change, or read OPENAI_* environment variables.
It passes the active provider URL and stored API key directly to the OpenAI
client constructors in memory.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from urllib.parse import urlparse


PLUGIN_NAME = "codex-auth-imagegen"


class AdapterError(RuntimeError):
    """A safe, user-facing adapter error."""


@dataclass(frozen=True)
class CodexPaths:
    home: Path
    config: Path
    auth: Path
    imagegen: Path

    @classmethod
    def from_home(cls, explicit_home: Path | None = None) -> "CodexPaths":
        home = (explicit_home or (Path.home() / ".codex")).expanduser().resolve()
        return cls(
            home=home,
            config=home / "config.toml",
            auth=home / "auth.json",
            imagegen=home / "skills" / ".system" / "imagegen" / "scripts" / "image_gen.py",
        )


@dataclass(frozen=True)
class CodexCredentials:
    provider: str
    base_url: str
    api_key: str = field(repr=False)


def _require_nonempty_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AdapterError(f"{label} is missing or empty")
    return value.strip()


def _validate_base_url(raw_url: str) -> str:
    base_url = raw_url.rstrip("/")
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.hostname:
        raise AdapterError("The active provider base_url is not a valid absolute URL")
    is_local = parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme.lower() != "https" and not is_local:
        raise AdapterError("Remote Image Gen providers must use HTTPS")
    if parsed.username or parsed.password:
        raise AdapterError("Credentials must not be embedded in the provider base_url")
    return base_url


def load_codex_credentials(paths: CodexPaths) -> CodexCredentials:
    """Load the active provider and key without consulting environment variables."""
    if not paths.config.is_file():
        raise AdapterError(f"Codex config not found: {paths.config}")
    if not paths.auth.is_file():
        raise AdapterError(f"Codex credential file not found: {paths.auth}")

    try:
        with paths.config.open("rb") as handle:
            config = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise AdapterError(f"Unable to read Codex config: {exc}") from exc

    provider = _require_nonempty_string(config.get("model_provider"), "model_provider")
    providers = config.get("model_providers")
    if not isinstance(providers, dict):
        raise AdapterError("model_providers table is missing from Codex config")
    provider_config = providers.get(provider)
    if not isinstance(provider_config, dict):
        raise AdapterError(f"Active model provider section is missing: {provider}")
    base_url = _validate_base_url(
        _require_nonempty_string(provider_config.get("base_url"), "active provider base_url")
    )

    try:
        with paths.auth.open("r", encoding="utf-8") as handle:
            auth = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError(f"Unable to read Codex credential file: {exc}") from exc
    if not isinstance(auth, dict):
        raise AdapterError("Codex credential file must contain a JSON object")
    api_key = _require_nonempty_string(auth.get("OPENAI_API_KEY"), "OPENAI_API_KEY in auth.json")

    return CodexCredentials(provider=provider, base_url=base_url, api_key=api_key)


def _load_bundled_imagegen(path: Path) -> ModuleType:
    if not path.is_file():
        raise AdapterError(f"Bundled Image Gen CLI not found: {path}")
    spec = importlib.util.spec_from_file_location("_codex_bundled_imagegen", path)
    if spec is None or spec.loader is None:
        raise AdapterError("Unable to load the bundled Image Gen CLI")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _patch_credential_delivery(imagegen: ModuleType, credentials: CodexCredentials) -> None:
    def ensure_codex_credentials(dry_run: bool) -> None:
        mode = "dry-run" if dry_run else "live"
        print(
            f"Codex credential adapter active ({mode}): provider={credentials.provider}; "
            f"base_url={credentials.base_url}; key_source=auth.json (redacted).",
            file=sys.stderr,
        )

    def create_client():
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise AdapterError("The openai Python package is not installed") from exc
        return OpenAI(api_key=credentials.api_key, base_url=credentials.base_url)

    def create_async_client():
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:
            raise AdapterError("The installed openai package does not provide AsyncOpenAI") from exc
        return AsyncOpenAI(api_key=credentials.api_key, base_url=credentials.base_url)

    imagegen._ensure_api_key = ensure_codex_credentials
    imagegen._create_client = create_client
    imagegen._create_async_client = create_async_client


def _diagnose(paths: CodexPaths, credentials: CodexCredentials) -> int:
    parsed = urlparse(credentials.base_url)
    print(f"plugin={PLUGIN_NAME}")
    print(f"codex_home={paths.home}")
    print(f"provider={credentials.provider}")
    print(f"base_url={credentials.base_url}")
    print(f"provider_host={parsed.hostname}")
    print("api_key_source=auth.json")
    print("api_key_present=true")
    print("uses_environment_variables=false")
    print(f"bundled_imagegen_present={str(paths.imagegen.is_file()).lower()}")
    return 0


def _parse_adapter_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--diagnose", action="store_true")
    options, forwarded = parser.parse_known_args(argv)
    if options.diagnose and forwarded:
        raise AdapterError("--diagnose cannot be combined with Image Gen arguments")
    return options, forwarded


def run(argv: list[str] | None = None) -> int:
    options, forwarded = _parse_adapter_args(list(sys.argv[1:] if argv is None else argv))
    paths = CodexPaths.from_home(options.codex_home)
    credentials = load_codex_credentials(paths)
    if options.diagnose:
        return _diagnose(paths, credentials)

    imagegen = _load_bundled_imagegen(paths.imagegen)
    _patch_credential_delivery(imagegen, credentials)
    original_argv = sys.argv
    try:
        sys.argv = [str(paths.imagegen), *forwarded]
        result = imagegen.main()
    finally:
        sys.argv = original_argv
    return int(result or 0)


def main() -> int:
    try:
        return run()
    except AdapterError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
