"""tests/test_knowledge_safety.py — V16 Phase 4C Step 8.

Structural (AST-based, not grep) proof of the safety boundary stated
in knowledge_engine/__init__.py's module docstring: this package can
read from journal.journal_v2 and the standard library, and nothing
else. In particular, it must be structurally impossible for this
package to import anything that could place a trade, modify an order,
touch risk limits, or change execution/lifecycle state.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

KNOWLEDGE_ENGINE_DIR = Path(__file__).resolve().parent.parent / "knowledge_engine"

FORBIDDEN_TOP_LEVEL_MODULES = {
    "execution", "risk", "decision", "agents", "portfolio",
    "commander", "world", "dashboard", "dashboard_src",
    "binance", "binance_futures_connector",
}

ALLOWED_LOCAL_MODULES = {"journal", "knowledge_engine"}


def _imported_top_level_modules(py_file: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:  # ignore relative imports (level > 0)
                modules.add(node.module.split(".")[0])
    return modules


def _all_knowledge_engine_files() -> list[Path]:
    return sorted(KNOWLEDGE_ENGINE_DIR.glob("*.py"))


class TestNoForbiddenImports:
    def test_package_exists_and_has_files(self):
        files = _all_knowledge_engine_files()
        assert len(files) >= 5, "expected knowledge_engine/ to contain multiple modules"

    def test_no_file_imports_a_forbidden_module(self):
        violations = []
        for py_file in _all_knowledge_engine_files():
            modules = _imported_top_level_modules(py_file)
            bad = modules & FORBIDDEN_TOP_LEVEL_MODULES
            if bad:
                violations.append((py_file.name, bad))
        assert violations == [], f"forbidden imports found: {violations}"

    def test_only_journal_and_stdlib_local_imports(self):
        """Every knowledge_engine module's local (non-stdlib) imports
        must be from journal (read-only data access) or knowledge_engine
        itself (internal cross-module use) — nothing else in this
        repository."""
        import sys

        stdlib_modules = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else set()

        # Top-level directories that exist in this repo — anything NOT
        # in stdlib and NOT a known repo package is a third-party lib,
        # which is fine; we only care about *local repo* imports here.
        repo_top_level = {p.name for p in KNOWLEDGE_ENGINE_DIR.parent.iterdir() if p.is_dir() and not p.name.startswith(".")}

        violations = []
        for py_file in _all_knowledge_engine_files():
            modules = _imported_top_level_modules(py_file)
            local_repo_imports = modules & repo_top_level
            disallowed = local_repo_imports - ALLOWED_LOCAL_MODULES
            if disallowed:
                violations.append((py_file.name, disallowed))
        assert violations == [], f"local repo imports outside journal/knowledge_engine: {violations}"


class TestNoWriteMethodsCalled:
    """journal_v2.py has both readers (get_*) and writers (save_*,
    update_*). This package must only ever call readers."""

    FORBIDDEN_CALL_PREFIXES = ("save_", "update_", "delete_")

    def test_no_journal_write_methods_called(self):
        violations = []
        for py_file in _all_knowledge_engine_files():
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.attr, str):
                    if node.attr.startswith(self.FORBIDDEN_CALL_PREFIXES):
                        violations.append((py_file.name, node.attr))
        assert violations == [], (
            f"knowledge_engine/ must never call journal write methods: {violations} "
            "— it is read-only by design (see __init__.py's safety boundary docstring)"
        )


class TestNoNetworkOrExchangeCalls:
    def test_no_requests_or_websocket_imports(self):
        """Extra belt-and-braces: this package should need no network
        access at all — everything it reads comes from the local
        journal database or in-memory Python objects passed in."""
        forbidden = {"requests", "httpx", "websocket", "websockets", "binance"}
        violations = []
        for py_file in _all_knowledge_engine_files():
            modules = _imported_top_level_modules(py_file)
            bad = modules & forbidden
            if bad:
                violations.append((py_file.name, bad))
        assert violations == [], f"unexpected network imports: {violations}"
