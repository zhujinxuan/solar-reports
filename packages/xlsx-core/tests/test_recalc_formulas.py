"""Tests for formulas-package recalculation adapter (non-winner).

Construction-level tests only.
"""

from __future__ import annotations


def test_formulas_pkg_import() -> None:
    """Construction smoke test — import and instantiate."""
    from xlsx_core.recalc.formulas_pkg import FormulasPkgRecalc

    assert FormulasPkgRecalc.name == "formulas-pkg"
