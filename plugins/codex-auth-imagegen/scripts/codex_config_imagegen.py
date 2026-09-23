#!/usr/bin/env python3
"""Run Codex's bundled Image Gen CLI with the active provider in config.toml.

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
DEFAULT_IMAGE_MODELS = {
    "generate": "gpt-image-2.5-flare",
    "edit": "gpt-image-2.5-sunburst",
}


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
    key_source: str


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
    if parsed.query or parsed.fragment:
        raise AdapterError("The provider base_url must not include query or fragment parameters")
    return base_url


def load_codex_credentials(paths: CodexPaths) -> CodexCredentials:
    """Use the active provider token, falling back to auth.json when absent."""
    if not paths.config.is_file():
        raise AdapterError(f"Codex config not found: {paths.config}")

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

    token = provider_config.get("experimental_bearer_token")
    if token is not None and not (isinstance(token, str) and not token.strip()):
        api_key = _require_nonempty_string(
            token, "active provider experimental_bearer_token in config.toml"
        )
        key_source = "config.toml"
    else:
        if not paths.auth.is_file():
            raise AdapterError(
                "No active provider experimental_bearer_token in config.toml "
                f"and Codex credential file not found: {paths.auth}"
            )
        try:
            with paths.auth.open("r", encoding="utf-8") as handle:
                auth = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise AdapterError(f"Unable to read Codex credential file: {exc}") from exc
        if not isinstance(auth, dict):
            raise AdapterError("Codex credential file must contain a JSON object")
        api_key = _require_nonempty_string(auth.get("OPENAI_API_KEY"), "OPENAI_API_KEY in auth.json")
        key_source = "auth.json"

    return CodexCredentials(
        provider=provider, base_url=base_url, api_key=api_key, key_source=key_source
    )


def _load_bundled_imagegen(path: Path) -> ModuleType:
    if not path.is_file():
        raise AdapterError(f"Bundled Image Gen CLI not found: {path}")
    spec = importlib.util.spec_from_file_location("_codex_bundled_imagegen", path)
    if spec is None or spec.loader is None:
        raise AdapterError("Unable to load the bundled Image Gen CLI")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _patch_credential_delivery(
    imagegen: ModuleType,
    credentials: CodexCredentials,
    *,
    verbose_status: bool = False,
) -> None:
    def ensure_codex_credentials(dry_run: bool) -> None:
        if not verbose_status:
            return
        mode = "dry-run" if dry_run else "live"
        print(
            f"Codex credential adapter active ({mode}): provider={credentials.provider}; "
            f"base_url={credentials.base_url}; key_source={credentials.key_source} (redacted).",
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
    print(f"api_key_source={credentials.key_source}")
    print("api_key_present=true")
    print("uses_environment_variables=false")
    print(f"bundled_imagegen_present={str(paths.imagegen.is_file()).lower()}")
    return 0


def _list_image_models(credentials: CodexCredentials) -> int:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise AdapterError("The openai Python package is not installed") from exc
    with OpenAI(api_key=credentials.api_key, base_url=credentials.base_url) as client:
        models = client.models.list()
    names = sorted(
        model.id for model in models.data
        if isinstance(model.id, str) and model.id.startswith("gpt-image-")
    )
    for name in names:
        print(name)
    if not names:
        print("No gpt-image-* models advertised by the active provider.")
    return 0


def _with_default_model(forwarded: list[str]) -> list[str]:
    if not forwarded or forwarded[0] not in DEFAULT_IMAGE_MODELS:
        return forwarded
    if any(arg == "--model" or arg.startswith("--model=") for arg in forwarded[1:]):
        return forwarded
    return [forwarded[0], "--model", DEFAULT_IMAGE_MODELS[forwarded[0]], *forwarded[1:]]


def _parse_adapter_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--codex-home", type=Path)
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--list-image-models", action="store_true")
    parser.add_argument("--verbose-status", action="store_true")
    parser.add_argument("--verbose-errors", action="store_true")
    options, forwarded = parser.parse_known_args(argv)
    if (options.diagnose or options.list_image_models) and forwarded:
        raise AdapterError("Diagnostic/model listing cannot be combined with Image Gen arguments")
    if options.diagnose and options.list_image_models:
        raise AdapterError("Choose either --diagnose or --list-image-models")
    return options, forwarded


def run(argv: list[str] | None = None) -> int:
    options, forwarded = _parse_adapter_args(list(sys.argv[1:] if argv is None else argv))
    paths = CodexPaths.from_home(options.codex_home)
    credentials = load_codex_credentials(paths)
    if options.diagnose:
        return _diagnose(paths, credentials)
    if options.list_image_models:
        try:
            return _list_image_models(credentials)
        except AdapterError:
            raise
        except Exception as exc:
            if options.verbose_errors:
                raise
            raise AdapterError(
                f"Image model listing failed ({type(exc).__name__}). "
                "Retry with --verbose-errors only when a traceback is needed."
            ) from None

    try:
        imagegen = _load_bundled_imagegen(paths.imagegen)
        _patch_credential_delivery(
            imagegen,
            credentials,
            verbose_status=options.verbose_status,
        )
        original_argv = sys.argv
        try:
            sys.argv = [str(paths.imagegen), *_with_default_model(forwarded)]
            result = imagegen.main()
        finally:
            sys.argv = original_argv
    except AdapterError:
        raise
    except Exception as exc:
        if options.verbose_errors:
            raise
        raise AdapterError(
            f"Image Gen execution failed ({type(exc).__name__}). "
            "Retry with --verbose-errors only when a traceback is needed."
        ) from None
    return int(result or 0)


def main() -> int:
    try:
        return run()
    except AdapterError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
