"""Tests for year series detection."""

from __future__ import annotations

from xlsx_core.parser import parse
from xlsx_core.year_series import detect_year_series


def test_basic_series_detection() -> None:
    """Synthetic sheet with 3 identical formulas across columns."""
    # Simulate: row 8 has G8=G5*G7, H8=H5*H7, I8=I5*I7
    ast_g = parse("G5*G7")
    ast_h = parse("H5*H7")
    ast_i = parse("I5*I7")
    ast_j = parse("J5*J7")

    cells = [
        ("TestSheet", "G", 8, 6, ast_g),
        ("TestSheet", "H", 8, 7, ast_h),
        ("TestSheet", "I", 8, 8, ast_i),
        ("TestSheet", "J", 8, 9, ast_j),
    ]

    report = detect_year_series(cells)  # ty:ignore[invalid-argument-type]
    assert report.total_series() == 1
    assert report.total_nodes_marked() == 4

    series = report.series[0]
    assert series.sheet == "TestSheet"
    assert series.row == 8
    assert len(series.node_ids) == 4


def test_no_series_short_run() -> None:
    """Only 2 columns — not a series."""
    ast_g = parse("G5*G7")
    ast_h = parse("H5*H7")

    cells = [
        ("TestSheet", "G", 8, 6, ast_g),
        ("TestSheet", "H", 8, 7, ast_h),
    ]

    report = detect_year_series(cells)  # ty:ignore[invalid-argument-type]
    assert report.total_series() == 0


def test_mixed_formulas_no_series() -> None:
    """Different formulas — no series."""
    ast1 = parse("A1+1")
    ast2 = parse("B1+2")
    ast3 = parse("C1+3")

    cells = [
        ("Sheet", "A", 5, 0, ast1),
        ("Sheet", "B", 5, 1, ast2),
        ("Sheet", "C", 5, 2, ast3),
    ]

    report = detect_year_series(cells)  # ty:ignore[invalid-argument-type]
    assert report.total_series() == 0


def test_multiple_series_same_sheet() -> None:
    """Two independent series on different rows."""
    ast_col_a = parse("A1")
    ast_col_b = parse("B1")
    ast_col_c = parse("C1")

    ast_row2_a = parse("A2+A3")
    ast_row2_b = parse("B2+B3")
    ast_row2_c = parse("C2+C3")

    cells = [
        ("Sheet", "A", 1, 0, ast_col_a),
        ("Sheet", "B", 1, 1, ast_col_b),
        ("Sheet", "C", 1, 2, ast_col_c),
        ("Sheet", "A", 2, 0, ast_row2_a),
        ("Sheet", "B", 2, 1, ast_row2_b),
        ("Sheet", "C", 2, 2, ast_row2_c),
    ]

    report = detect_year_series(cells)  # ty:ignore[invalid-argument-type]
    assert report.total_series() == 2
    counts = report.count_per_sheet()
    assert counts["Sheet"] == 2


def test_series_key_format() -> None:
    """Series key follows the contract format."""
    ast_g = parse("G5*G7")
    ast_h = parse("H5*H7")
    ast_i = parse("I5*I7")

    cells = [
        ("损益", "G", 8, 6, ast_g),
        ("损益", "H", 8, 7, ast_h),
        ("损益", "I", 8, 8, ast_i),
    ]

    report = detect_year_series(cells)  # ty:ignore[invalid-argument-type]
    series = report.series[0]
    assert series.key.startswith("损益!r8:")
