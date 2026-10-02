from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch


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
        self.write_auth("fallback-secret-value")

    def write_config(
        self, base_url: str, provider: str = "custom", key: str | None = "test-secret-value"
    ) -> None:
        token_line = "" if key is None else f'experimental_bearer_token = "{key}"\n'
        self.paths.config.write_text(
            f'model_provider = "{provider}"\n\n'
            f'[model_providers.{provider}]\n'
            f'base_url = "{base_url}"\n'
            f'{token_line}',
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
        self.assertEqual(credentials.key_source, "config.toml")
        self.assertNotIn("test-secret-value", repr(credentials))
        self.assertNotIn("fallback-secret-value", repr(credentials))

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

    def test_rejects_url_query_that_may_expose_key(self) -> None:
        self.write_config("https://provider.example/v1?key=secret")
        with self.assertRaisesRegex(adapter.AdapterError, "query or fragment"):
            adapter.load_codex_credentials(self.paths)

    def test_falls_back_to_auth_json_when_config_token_missing(self) -> None:
        self.write_config("https://provider.example/v1", key=None)
        credentials = adapter.load_codex_credentials(self.paths)
        self.assertEqual(credentials.api_key, "fallback-secret-value")
        self.assertEqual(credentials.key_source, "auth.json")

    def test_falls_back_to_auth_json_when_config_token_blank(self) -> None:
        self.write_config("https://provider.example/v1", key="   ")
        credentials = adapter.load_codex_credentials(self.paths)
        self.assertEqual(credentials.api_key, "fallback-secret-value")
        self.assertEqual(credentials.key_source, "auth.json")

    def test_rejects_missing_both_keys(self) -> None:
        self.write_config("https://provider.example/v1", key=None)
        self.write_auth(None)
        with self.assertRaisesRegex(adapter.AdapterError, "OPENAI_API_KEY in auth.json"):
            adapter.load_codex_credentials(self.paths)

    def test_missing_auth_file_is_ignored_when_config_token_is_set(self) -> None:
        missing_auth = replace(self.paths, auth=self.codex_home / "missing-auth.json")
        credentials = adapter.load_codex_credentials(missing_auth)
        self.assertEqual(credentials.key_source, "config.toml")

    def test_missing_auth_file_is_reported_when_config_token_is_absent(self) -> None:
        self.write_config("https://provider.example/v1", key=None)
        missing_auth = replace(self.paths, auth=self.codex_home / "missing-auth.json")
        with self.assertRaisesRegex(adapter.AdapterError, "Codex credential file not found"):
            adapter.load_codex_credentials(missing_auth)

    def test_malformed_auth_file_is_ignored_when_config_token_is_set(self) -> None:
        self.paths.auth.write_text("not json", encoding="utf-8")
        credentials = adapter.load_codex_credentials(self.paths)
        self.assertEqual(credentials.key_source, "config.toml")

    def test_malformed_auth_file_is_reported_for_fallback(self) -> None:
        self.write_config("https://provider.example/v1", key=None)
        self.paths.auth.write_text("not json", encoding="utf-8")
        with self.assertRaisesRegex(adapter.AdapterError, "Unable to read Codex credential file"):
            adapter.load_codex_credentials(self.paths)

    def test_rejects_invalid_config_token_without_fallback(self) -> None:
        self.write_config("https://provider.example/v1")
        self.paths.config.write_text(
            self.paths.config.read_text(encoding="utf-8").replace(
                'experimental_bearer_token = "test-secret-value"',
                "experimental_bearer_token = 123",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(adapter.AdapterError, "experimental_bearer_token"):
            adapter.load_codex_credentials(self.paths)

    def test_does_not_read_auth_json_when_config_token_present(self) -> None:
        self.paths.auth.write_text("not json", encoding="utf-8")
        self.assertEqual(adapter.load_codex_credentials(self.paths).api_key, "test-secret-value")

    def test_patches_clients_with_explicit_arguments_and_is_quiet_by_default(self) -> None:
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
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn("test-secret-value", stderr.getvalue())

    def test_verbose_status_is_redacted(self) -> None:
        credentials = adapter.load_codex_credentials(self.paths)
        imagegen = SimpleNamespace()
        adapter._patch_credential_delivery(imagegen, credentials, verbose_status=True)

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            imagegen._ensure_api_key(False)
        output = stderr.getvalue()
        self.assertIn("key_source=config.toml (redacted)", output)
        self.assertNotIn("test-secret-value", output)

    def test_diagnose_is_redacted(self) -> None:
        credentials = adapter.load_codex_credentials(self.paths)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = adapter._diagnose(self.paths, credentials)
        output = stdout.getvalue()
        self.assertEqual(result, 0)
        self.assertIn("uses_environment_variables=false", output)
        self.assertIn("api_key_present=true", output)
        self.assertIn("api_key_source=config.toml", output)
        self.assertNotIn("test-secret-value", output)
        self.assertNotIn("fallback-secret-value", output)

    def test_fallback_diagnostics_redact_auth_key(self) -> None:
        self.write_config("https://provider.example/v1", key=None)
        credentials = adapter.load_codex_credentials(self.paths)
        imagegen = SimpleNamespace()
        adapter._patch_credential_delivery(imagegen, credentials, verbose_status=True)
        stderr = io.StringIO()
        stdout = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            imagegen._ensure_api_key(False)
            adapter._diagnose(self.paths, credentials)
        self.assertIn("key_source=auth.json (redacted)", stderr.getvalue())
        self.assertIn("api_key_source=auth.json", stdout.getvalue())
        self.assertNotIn("fallback-secret-value", stderr.getvalue() + stdout.getvalue())

    def test_lists_only_image_models_without_exposing_key(self) -> None:
        captured = {}

        class FakeClient:
            def __init__(self, **kwargs):
                captured.update(kwargs)

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            class models:
                @staticmethod
                def list():
                    return SimpleNamespace(data=[
                        SimpleNamespace(id="gpt-image-2.5-sunburst"),
                        SimpleNamespace(id="text-model"),
                        SimpleNamespace(id="gpt-image-2.5-flare"),
                    ])

        fake_openai = ModuleType("openai")
        fake_openai.OpenAI = FakeClient
        stdout = io.StringIO()
        with patch.dict(sys.modules, {"openai": fake_openai}), contextlib.redirect_stdout(stdout):
            result = adapter._list_image_models(adapter.load_codex_credentials(self.paths))
        self.assertEqual(result, 0)
        self.assertEqual(stdout.getvalue().splitlines(), [
            "gpt-image-2.5-flare", "gpt-image-2.5-sunburst",
        ])
        self.assertNotIn(captured["api_key"], stdout.getvalue())

    def test_image_25_defaults_respect_explicit_model(self) -> None:
        self.assertEqual(
            adapter._with_default_model(["generate", "--prompt", "test"]),
            ["generate", "--model", "gpt-image-2.5-flare", "--prompt", "test"],
        )
        self.assertEqual(
            adapter._with_default_model(["edit", "--image", "robot.png"]),
            ["edit", "--model", "gpt-image-2.5-sunburst", "--image", "robot.png"],
        )
        self.assertEqual(
            adapter._with_default_model(["generate", "--model", "gpt-image-2", "--prompt", "test"]),
            ["generate", "--model", "gpt-image-2", "--prompt", "test"],
        )
        self.assertEqual(
            adapter._with_default_model(["generate-batch", "--input", "jobs.jsonl"]),
            ["generate-batch", "--input", "jobs.jsonl"],
        )

    def test_adapter_options_are_removed_before_forwarding(self) -> None:
        options, forwarded = adapter._parse_adapter_args(
            [
                "--codex-home",
                str(self.codex_home),
                "--verbose-status",
                "--verbose-errors",
                "generate",
                "--prompt",
                "test",
            ]
        )
        self.assertEqual(options.codex_home, self.codex_home)
        self.assertTrue(options.verbose_status)
        self.assertTrue(options.verbose_errors)
        self.assertEqual(forwarded, ["generate", "--prompt", "test"])

    def test_image_25_reuses_bundled_image_2_size_validation(self) -> None:
        for model in adapter.DEFAULT_IMAGE_MODELS.values():
            with self.subTest(model=model):
                validate = Mock()
                imagegen = SimpleNamespace(_validate_size=validate)
                adapter._patch_image_25_size_validation(imagegen)
                imagegen._validate_size("1536x864", model)
                validate.assert_called_once_with("1536x864", "gpt-image-2")

    def test_other_models_keep_original_size_validation(self) -> None:
        for model in ("gpt-image-2", "gpt-image-1", "gpt-image-1.5", "gpt-image-1-mini"):
            with self.subTest(model=model):
                validate = Mock()
                imagegen = SimpleNamespace(_validate_size=validate)
                adapter._patch_image_25_size_validation(imagegen)
                imagegen._validate_size("1024x1024", model)
                validate.assert_called_once_with("1024x1024", model)

    def test_image_25_propagates_invalid_size_errors(self) -> None:
        for model in adapter.DEFAULT_IMAGE_MODELS.values():
            with self.subTest(model=model):
                validate = Mock(side_effect=SystemExit(1))
                imagegen = SimpleNamespace(_validate_size=validate)
                adapter._patch_image_25_size_validation(imagegen)
                with self.assertRaises(SystemExit):
                    imagegen._validate_size("1920x1080", model)
                validate.assert_called_once_with("1920x1080", "gpt-image-2")

    def test_fixed_size_and_model_are_forwarded_unchanged(self) -> None:
        cases = [
            ("generate", [], [], "gpt-image-2.5-flare", "1536x864"),
            ("edit", ["--image", "fixture.png"], [], "gpt-image-2.5-sunburst", "2048x1152"),
            ("generate", [], ["--model=gpt-image-2.5-sunburst"],
             "gpt-image-2.5-sunburst", "1536x864"),
        ]
        for command, inputs, model_args, model, size in cases:
            with self.subTest(command=command, model=model):
                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    result = adapter.run([
                        "--codex-home", str(self.codex_home), command,
                        *inputs, *model_args, "--prompt", "test",
                        f"--size={size}", "--dry-run",
                    ])
                payload = json.loads(stdout.getvalue().splitlines()[0])
                self.assertEqual(result, 0)
                self.assertEqual(payload["model"], model)
                self.assertEqual(payload["size"], size)
                self.assertEqual(payload["validations"], [[size, "gpt-image-2"]])

    def test_default_size_remains_auto(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            adapter.run([
                "--codex-home", str(self.codex_home),
                "generate", "--prompt", "test", "--dry-run",
            ])
        payload = json.loads(stdout.getvalue().splitlines()[0])
        self.assertEqual(payload["size"], "auto")
        self.assertEqual(payload["model"], "gpt-image-2.5-flare")

    def test_mixed_models_validate_without_changing_payloads(self) -> None:
        validate = Mock()
        imagegen = SimpleNamespace(_validate_size=validate)
        adapter._patch_image_25_size_validation(imagegen)
        jobs = [
            {"model": "gpt-image-2.5-flare", "size": "1536x864"},
            {"model": "gpt-image-2.5-sunburst", "size": "2048x1152"},
            {"model": "gpt-image-1", "size": "1024x1024"},
        ]
        original_jobs = [job.copy() for job in jobs]
        for job in jobs:
            imagegen._validate_size(job["size"], job["model"])
        self.assertEqual(jobs, original_jobs)
        self.assertEqual(
            [call.args for call in validate.call_args_list],
            [("1536x864", "gpt-image-2"), ("2048x1152", "gpt-image-2"),
             ("1024x1024", "gpt-image-1")],
        )

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

    def test_execution_error_is_concise_by_default(self) -> None:
        fake_imagegen = SimpleNamespace(
            _validate_size=Mock(), main=Mock(side_effect=RuntimeError("details"))
        )
        with patch.object(adapter, "_load_bundled_imagegen", return_value=fake_imagegen):
            with self.assertRaisesRegex(
                adapter.AdapterError,
                r"Image Gen execution failed \(RuntimeError\)",
            ) as caught:
                adapter.run(["--codex-home", str(self.codex_home), "generate", "--prompt", "test"])
        self.assertNotIn("details", str(caught.exception))

    def test_main_prints_one_safe_error_line_without_traceback(self) -> None:
        fake_imagegen = SimpleNamespace(
            _validate_size=Mock(), main=Mock(side_effect=RuntimeError("details"))
        )
        stderr = io.StringIO()
        argv = [
            str(ADAPTER_PATH),
            "--codex-home",
            str(self.codex_home),
            "generate",
            "--prompt",
            "test",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(adapter, "_load_bundled_imagegen", return_value=fake_imagegen),
            contextlib.redirect_stderr(stderr),
        ):
            result = adapter.main()

        lines = stderr.getvalue().splitlines()
        self.assertEqual(result, 2)
        self.assertEqual(len(lines), 1)
        self.assertIn("Image Gen execution failed (RuntimeError)", lines[0])
        self.assertNotIn("details", lines[0])
        self.assertNotIn("Traceback", lines[0])

    def test_verbose_errors_preserves_original_exception(self) -> None:
        fake_imagegen = SimpleNamespace(
            _validate_size=Mock(), main=Mock(side_effect=RuntimeError("details"))
        )
        with patch.object(adapter, "_load_bundled_imagegen", return_value=fake_imagegen):
            with self.assertRaisesRegex(RuntimeError, "details"):
                adapter.run(
                    [
                        "--codex-home",
                        str(self.codex_home),
                        "--verbose-errors",
                        "generate",
                        "--prompt",
                        "test",
                    ]
                )

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
