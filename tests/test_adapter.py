from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = (
    REPOSITORY_ROOT
    / "plugins"
    / "codex-auth-imagegen"
    / "scripts"
    / "codex_config_imagegen.py"
)
FIXTURE_CODEX_HOME = REPOSITORY_ROOT / "tests" / "fixture-home"


def load_adapter():
    spec = importlib.util.spec_from_file_location("codex_auth_imagegen_adapter", ADAPTER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load adapter under test")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


adapter = load_adapter()


class AdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.codex_home = FIXTURE_CODEX_HOME
        self.paths = adapter.CodexPaths.from_home(self.codex_home)
        self.write_config("https://provider.example/v1")
        self.write_auth("test-secret-value")

    def write_config(self, base_url: str, provider: str = "custom") -> None:
        self.paths.config.write_text(
            f'model_provider = "{provider}"\n\n'
            f'[model_providers.{provider}]\n'
            f'base_url = "{base_url}"\n',
            encoding="utf-8",
        )

    def write_auth(self, key: str | None) -> None:
        payload = {} if key is None else {"OPENAI_API_KEY": key}
        self.paths.auth.write_text(json.dumps(payload), encoding="utf-8")

    def test_loads_active_provider_and_key(self) -> None:
        credentials = adapter.load_codex_credentials(self.paths)
        self.assertEqual(credentials.provider, "custom")
        self.assertEqual(credentials.base_url, "https://provider.example/v1")
        self.assertEqual(credentials.api_key, "test-secret-value")
        self.assertNotIn("test-secret-value", repr(credentials))

    def test_rejects_plain_http_for_remote_provider(self) -> None:
        self.write_config("http://provider.example/v1")
        with self.assertRaisesRegex(adapter.AdapterError, "must use HTTPS"):
            adapter.load_codex_credentials(self.paths)

    def test_allows_plain_http_for_local_provider(self) -> None:
        self.write_config("http://127.0.0.1:8080/v1")
        credentials = adapter.load_codex_credentials(self.paths)
        self.assertEqual(credentials.base_url, "http://127.0.0.1:8080/v1")

    def test_rejects_credentials_embedded_in_url(self) -> None:
        self.write_config("https://user:password@provider.example/v1")
        with self.assertRaisesRegex(adapter.AdapterError, "must not be embedded"):
            adapter.load_codex_credentials(self.paths)

    def test_rejects_missing_key(self) -> None:
        self.write_auth(None)
        with self.assertRaisesRegex(adapter.AdapterError, "OPENAI_API_KEY"):
            adapter.load_codex_credentials(self.paths)

    def test_patches_clients_with_explicit_arguments_and_redacts_output(self) -> None:
        calls: list[tuple[str, dict[str, str]]] = []

        class FakeOpenAI:
            def __init__(self, **kwargs):
                calls.append(("sync", kwargs))

        class FakeAsyncOpenAI:
            def __init__(self, **kwargs):
                calls.append(("async", kwargs))

        fake_openai = ModuleType("openai")
        fake_openai.OpenAI = FakeOpenAI
        fake_openai.AsyncOpenAI = FakeAsyncOpenAI
        credentials = adapter.load_codex_credentials(self.paths)
        imagegen = SimpleNamespace()

        with patch.dict(sys.modules, {"openai": fake_openai}):
            adapter._patch_credential_delivery(imagegen, credentials)
            imagegen._create_client()
            imagegen._create_async_client()

        self.assertEqual(calls[0][1]["api_key"], "test-secret-value")
        self.assertEqual(calls[0][1]["base_url"], "https://provider.example/v1")
        self.assertEqual(calls[1][1], calls[0][1])

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            imagegen._ensure_api_key(False)
        self.assertIn("key_source=auth.json (redacted)", stderr.getvalue())
        self.assertNotIn("test-secret-value", stderr.getvalue())

    def test_diagnose_is_redacted(self) -> None:
        credentials = adapter.load_codex_credentials(self.paths)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = adapter._diagnose(self.paths, credentials)
        output = stdout.getvalue()
        self.assertEqual(result, 0)
        self.assertIn("uses_environment_variables=false", output)
        self.assertIn("api_key_present=true", output)
        self.assertNotIn("test-secret-value", output)

    def test_adapter_options_are_removed_before_forwarding(self) -> None:
        options, forwarded = adapter._parse_adapter_args(
            ["--codex-home", str(self.codex_home), "generate", "--prompt", "test"]
        )
        self.assertEqual(options.codex_home, self.codex_home)
        self.assertEqual(forwarded, ["generate", "--prompt", "test"])

    def test_diagnose_rejects_forwarded_arguments(self) -> None:
        with self.assertRaisesRegex(adapter.AdapterError, "cannot be combined"):
            adapter._parse_adapter_args(["--diagnose", "generate"])

    def test_dry_run_loads_and_patches_bundled_cli(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = adapter.run(
                ["--codex-home", str(self.codex_home), "generate", "--prompt", "test", "--dry-run"]
            )
        self.assertEqual(result, 0)
        self.assertIn("fake-imagegen-main", stdout.getvalue())
        self.assertNotIn("test-secret-value", stdout.getvalue() + stderr.getvalue())

    def test_source_has_no_environment_variable_access(self) -> None:
        source = ADAPTER_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        self.assertNotIn("os", imported_modules)
        self.assertNotIn("os.environ", source)
        self.assertNotIn("os.getenv", source)


if __name__ == "__main__":
    unittest.main()
