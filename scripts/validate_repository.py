#!/usr/bin/env python3
"""Validate the distributable marketplace repository with the standard library."""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "codex-auth-imagegen"
MANIFEST = PLUGIN / ".codex-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
SKILL = PLUGIN / "skills" / "codex-auth-imagegen" / "SKILL.md"
OPENAI_YAML = PLUGIN / "skills" / "codex-auth-imagegen" / "agents" / "openai.yaml"
ADAPTER = PLUGIN / "scripts" / "codex_config_imagegen.py"
REQUIRED = [MANIFEST, MARKETPLACE, SKILL, OPENAI_YAML, ADAPTER, ROOT / "LICENSE", ROOT / "README.md"]
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def fail(message: str) -> None:
    raise ValueError(message)


def main() -> int:
    for path in REQUIRED:
        if not path.is_file():
            fail(f"Required file is missing: {path.relative_to(ROOT)}")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("name") != "codex-auth-imagegen":
        fail("Plugin manifest name does not match its folder")
    if not SEMVER.fullmatch(str(manifest.get("version", ""))):
        fail("Plugin version is not valid semantic versioning")
    if manifest.get("skills") != "./skills/":
        fail("Plugin manifest must expose ./skills/")

    marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))
    entries = [item for item in marketplace.get("plugins", []) if item.get("name") == manifest["name"]]
    if len(entries) != 1:
        fail("Marketplace must contain exactly one codex-auth-imagegen entry")
    entry = entries[0]
    if entry.get("source", {}).get("path") != "./plugins/codex-auth-imagegen":
        fail("Marketplace source path is invalid")
    policy = entry.get("policy", {})
    if policy.get("installation") != "AVAILABLE" or policy.get("authentication") != "ON_INSTALL":
        fail("Marketplace policy is incomplete")
    if not entry.get("category"):
        fail("Marketplace category is required")

    skill_text = SKILL.read_text(encoding="utf-8")
    if not skill_text.startswith("---\n"):
        fail("SKILL.md frontmatter is missing")
    if "name: codex-auth-imagegen" not in skill_text.split("---", 2)[1]:
        fail("SKILL.md name is invalid")
    readme_text = (ROOT / "README.md").read_text(encoding="utf-8")
    for legacy_workspace_path in ("tmp/imagegen/", "output/imagegen/"):
        if legacy_workspace_path in skill_text or legacy_workspace_path in readme_text:
            fail(f"Legacy nested workspace path found: {legacy_workspace_path}")

    yaml_text = OPENAI_YAML.read_text(encoding="utf-8")
    if "$codex-auth-imagegen" not in yaml_text:
        fail("openai.yaml default prompt must mention $codex-auth-imagegen")

    for python_file in ROOT.rglob("*.py"):
        ast.parse(python_file.read_text(encoding="utf-8"), filename=str(python_file))

    adapter_text = ADAPTER.read_text(encoding="utf-8")
    adapter_tree = ast.parse(adapter_text)
    imported_modules = {
        alias.name
        for node in ast.walk(adapter_tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    if "os" in imported_modules or "os.environ" in adapter_text or "os.getenv" in adapter_text:
        fail("Adapter must not access environment variables")

    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or ".test-tmp" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if "[" + "TODO:" in text:
            fail(f"Placeholder found in {path.relative_to(ROOT)}")
        if re.search(r"C:\\Users\\[^\\]+", text, re.IGNORECASE):
            fail(f"User-specific Windows path found in {path.relative_to(ROOT)}")
        if re.search(r"\bsk-[A-Za-z0-9_-]{16,}\b", text):
            fail(f"Possible API key found in {path.relative_to(ROOT)}")

    print("Repository validation passed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, SyntaxError) as exc:
        print(f"Repository validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
