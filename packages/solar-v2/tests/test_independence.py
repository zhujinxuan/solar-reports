"""G5/G6 independence tests — no forbidden imports, no cell addresses,
pure-code benchmark match, cold compute timing.
"""

from __future__ import annotations

import ast
import math
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

# ── Benchmark headline truth (from solar_v1, batch context) ────────────

BENCHMARK_TRUTH = {
    "equity_irr": 0.0955885535344374,
    "project_irr_after_tax": 6.129232495094272,
    "equity_npv": 1908.709312658254,
    "project_npv_after_tax": 5520.727082388389,
}


# ── Forbidden imports ──────────────────────────────────────────────────

FORBIDDEN_MODULES = {"xlsx_core", "solar_v1", "yaml", "dag"}

# Regex for cell addresses like 损益!G8, 参数表!C20
CELL_ADDRESS_RE = re.compile(r"![A-Z]+\d+")


def _python_files(root: Path) -> list[Path]:
    """All .py files under root, excluding __pycache__."""
    return sorted(
        p for p in root.rglob("*.py")
        if "__pycache__" not in str(p)
    )


def _ast_imports(filepath: Path) -> list[tuple[str, int]]:
    """Parse AST imports from a Python file. Returns [(module_name, lineno), ...]."""
    tree = ast.parse(filepath.read_text(encoding="utf-8"))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            imports.append((mod, node.lineno))
    return imports


def test_no_forbidden_imports():
    """No xlsx_core, solar_v1, yaml, or dag imports in src/solar_v2.

    Uses AST parsing, not regex, to reliably detect all import forms.
    """
    src_root = Path("packages/solar-v2/src/solar_v2")
    violations = []

    for py_file in _python_files(src_root):
        for mod_name, lineno in _ast_imports(py_file):
            # Check if the top-level package matches a forbidden module
            top = mod_name.split(".")[0]
            if top in FORBIDDEN_MODULES:
                violations.append(
                    f"{py_file}:{lineno}: imports '{mod_name}'"
                )

    assert violations == [], (
        "Forbidden imports in src/solar_v2:\n  " + "\n  ".join(violations)
    )


def test_no_cell_addresses():
    r"""No cell-address strings like ``!<LETTERS><DIGITS>`` in src/solar_v2."""
    src_root = Path("packages/solar-v2/src/solar_v2")
    violations = []

    for py_file in _python_files(src_root):
        text = py_file.read_text(encoding="utf-8")
        for match in CELL_ADDRESS_RE.finditer(text):
            # Get line number
            lineno = text[:match.start()].count("\n") + 1
            violations.append(
                f"{py_file}:{lineno}: '{match.group()}'"
            )

    assert violations == [], (
        "Cell addresses in src/solar_v2:\n  " + "\n  ".join(violations)
    )


# ── (b) Pure-code benchmark match ──────────────────────────────────────


def test_pure_code_benchmark_match():
    """ModelInputs() built purely in code matches benchmark truth.

    No TOML, no files — just default constructor.
    """
    from solar_v2.engine import compute_model
    from solar_v2.inputs import ModelInputs

    result = compute_model(ModelInputs())

    for name, expected in BENCHMARK_TRUTH.items():
        actual = getattr(result, name)
        assert math.isclose(actual, expected, rel_tol=1e-6), (
            f"{name}: got {actual}, expected {expected}"
        )


# ── (c) Cold compute timing ────────────────────────────────────────────


def test_cold_compute_under_5s():
    """Cold compute_model(ModelInputs()) < 5 seconds.

    Fresh import in a subprocess to ensure cold start (no cached imports).
    """
    script = """
import time
from solar_v2.inputs import ModelInputs
from solar_v2.engine import compute_model

t0 = time.perf_counter()
result = compute_model(ModelInputs())
elapsed = time.perf_counter() - t0
print(f"{elapsed:.3f}")
print(f"{result.equity_irr:.6f}")
"""

    t0 = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=".",
    )
    _elapsed = time.perf_counter() - t0

    if proc.returncode != 0:
        pytest.fail(
            f"Cold compute failed (rc={proc.returncode}):\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )

    lines = proc.stdout.strip().split("\n")
    compute_time = float(lines[0])

    assert compute_time < 5.0, (
        f"Cold compute took {compute_time:.3f}s (limit 5s)"
    )
