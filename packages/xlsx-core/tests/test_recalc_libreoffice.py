"""Tests for LibreOffice recalculation adapter (non-winner).

Construction-level tests only — LO scored 2 mismatches vs Excel COM's 0.
"""

from __future__ import annotations


def test_libreoffice_import() -> None:
    """Construction smoke test — import and instantiate."""
    from xlsx_core.recalc.libreoffice import LibreOfficeRecalc

    assert LibreOfficeRecalc.name == "libreoffice"
