"""Year series detector — identifies column-shifted identical formulas.

Algorithm:
  Per sheet, per row, scan columns left-to-right.
  Group formula cells whose to_r1c1() output is identical across ≥3 contiguous columns.
  Output: series with key f"{sheet}!r{row}:{concept_hint}" and per-column index.

The concept hint is a truncated R1C1 string — deterministic, used for readability.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field

from xlsx_core.ast import Expr
from xlsx_core.parser import to_r1c1

_MIN_SERIES_WIDTH = 3  # minimum number of contiguous columns to form a series
_MAX_HINT_LENGTH = 60  # max characters for the concept hint


@dataclass(frozen=True)
class DetectedSeries:
    """One detected year series."""

    key: str  # e.g. "损益!row8:G5*G7"
    sheet: str
    row: int
    start_col: int  # 0-based column index of first column
    end_col: int  # 0-based column index of last column (inclusive)
    col_indices: list[int]  # 0-based column indices in order
    r1c1_expression: str  # the shared R1C1 expression
    node_ids: list[str]  # the node ids in this series, column order


@dataclass(frozen=True)
class SeriesReport:
    """Report of all detected year series."""

    series: list[DetectedSeries] = field(default_factory=list)

    def count_per_sheet(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self.series:
            counts[s.sheet] = counts.get(s.sheet, 0) + 1
        return counts

    def total_series(self) -> int:
        return len(self.series)

    def total_nodes_marked(self) -> int:
        return sum(len(s.node_ids) for s in self.series)


def detect_year_series(
    cells: list[tuple[str, str, int, int, Expr | None]],
) -> SeriesReport:
    """Detect year series from a list of formula cells.

    Args:
        cells: list of (sheet_name, col_letters, row_1based, col_0based, ast_or_None)
               where ast_or_None is the parsed formula AST (None for literal cells)

    Returns:
        SeriesReport with all detected series.
    """
    # Group cells by (sheet, row)
    from collections import defaultdict

    by_row: dict[tuple[str, int], list[tuple[int, str, Expr | None]]] = defaultdict(
        list
    )
    for sheet, col_str, row, col_idx, ast in cells:
        if ast is not None:
            by_row[(sheet, row)].append((col_idx, col_str, ast))

    all_series: list[DetectedSeries] = []

    for (sheet, row), col_cells in sorted(by_row.items()):
        # Sort by column index
        col_cells.sort(key=lambda x: x[0])

        # Map each cell to its R1C1 expression
        r1c1_map: list[tuple[int, str, str, Expr]] = []  # (col_idx, col_str, r1c1, ast)
        for col_idx, col_str, ast in col_cells:
            r1c1_str = to_r1c1(ast, col_idx, row - 1) if ast is not None else ""
            r1c1_map.append((col_idx, col_str, r1c1_str, ast))  # ty:ignore[invalid-argument-type]

        # Find runs of ≥3 cells with the same R1C1
        i = 0
        while i < len(r1c1_map):
            j = i
            while j < len(r1c1_map) and r1c1_map[j][2] == r1c1_map[i][2]:
                j += 1
            run_len = j - i
            if run_len >= _MIN_SERIES_WIDTH:
                _col_idx, _col_str, r1c1_str, _ = r1c1_map[i]
                # Build key and hint
                hint = _make_concept_hint(r1c1_str)
                key = f"{sheet}!r{row}:{hint}"

                col_indices = [c[0] for c in r1c1_map[i:j]]
                node_ids = [f"{sheet}!{c[1]}{row}" for c in r1c1_map[i:j]]

                all_series.append(
                    DetectedSeries(
                        key=key,
                        sheet=sheet,
                        row=row,
                        start_col=col_indices[0],
                        end_col=col_indices[-1],
                        col_indices=col_indices,
                        r1c1_expression=r1c1_str,
                        node_ids=node_ids,
                    )
                )
            i = j

    return SeriesReport(series=all_series)


def _make_concept_hint(r1c1_str: str) -> str:
    """Create a short, deterministic concept hint from an R1C1 expression.

    If the expression fits within the max length, use it as-is.
    Otherwise, truncate and add a hash of the full expression.
    """
    # Remove outer parentheses if it's a single binary expression
    cleaned = r1c1_str
    if cleaned.startswith("(") and cleaned.endswith(")") and cleaned.count("(") == 1:
        cleaned = cleaned[1:-1]

    if len(cleaned) <= _MAX_HINT_LENGTH:
        return cleaned

    # Truncate and hash
    h = zlib.crc32(r1c1_str.encode("utf-8")) % 10000
    return f"{cleaned[: _MAX_HINT_LENGTH - 6]}..{h:04d}"
