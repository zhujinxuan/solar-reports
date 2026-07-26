"""Workbook loader — openpyxl adapter, reads formulas AND cached values in two passes.

Produces an immutable snapshot of all cells (CellSnapshot frozen model) plus
defined names. Domain-neutral — sheet names, cell refs, and values are passed
through without interpretation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import openpyxl

from xlsx_core.model import ErrorValue, Scalar

# Error string set for detection
_ERROR_PATTERN = re.compile(r"^#(REF!|DIV/0!|VALUE!|N/A|NAME\?|NULL!|NUM!)$")


@dataclass(frozen=True)
class CellSnapshot:
    """Immutable snapshot of one cell from the workbook."""

    sheet: str
    col: str  # column letters, e.g. "A", "AB"
    row: int  # 1-based
    formula: str | None  # raw formula text WITH leading '=', None for literals
    value: Scalar  # cached value from data_only=True pass


@dataclass(frozen=True)
class WorkbookSnapshot:
    """Immutable snapshot of the entire workbook."""

    sheets: list[str]  # sheet names in order
    cells: list[CellSnapshot]  # ALL non-blank cells
    defined_names: dict[str, str]  # name → sheet!A1 target


def _col_to_letters(col_idx: int) -> str:
    """Convert 1-based column index to letters."""
    result = ""
    n = col_idx - 1
    while True:
        n, rem = divmod(n, 26)
        result = chr(ord("A") + rem) + result
        if n == 0:
            break
        n -= 1
    return result


def _parse_cached_value(raw_value: object) -> Scalar:
    """Convert openpyxl cached value to Scalar, detecting error strings."""
    if raw_value is None:
        return None
    if isinstance(raw_value, (int, float, bool)):
        return raw_value
    if isinstance(raw_value, str):
        if _ERROR_PATTERN.match(raw_value):
            return ErrorValue(error=raw_value)
        # Excel may return string numbers — try to parse
        try:
            return float(raw_value)
        except ValueError:
            return raw_value
    # datetime — openpyxl returns datetime objects; treat as float (Excel serial)
    from datetime import datetime

    if isinstance(raw_value, datetime):
        # We could convert to float, but for the solar workbook there shouldn't be dates
        # in cached values that matter for formula evaluation
        return raw_value  # ty:ignore[invalid-return-type]
    return raw_value  # ty:ignore[invalid-return-type]


def load_workbook(workbook_path: Path) -> WorkbookSnapshot:
    """Load a workbook in two passes: formulas + cached values.

    Returns an immutable WorkbookSnapshot. Handles CJK sheet names and paths.
    """
    wb_path = str(workbook_path)

    # Pass 1: formulas
    wb_f = openpyxl.load_workbook(wb_path, data_only=False)

    # Pass 2: cached values
    wb_v = openpyxl.load_workbook(wb_path, data_only=True)

    sheets: list[str] = []
    cells: list[CellSnapshot] = []

    for sn in wb_f.sheetnames:
        sheets.append(sn)
        ws_f = wb_f[sn]
        ws_v = wb_v[sn]

        for row_idx in range(1, ws_f.max_row + 1):
            for col_idx in range(1, ws_f.max_column + 1):
                cell_f = ws_f.cell(row=row_idx, column=col_idx)
                cell_v = ws_v.cell(row=row_idx, column=col_idx)

                formula_val = cell_f.value
                cached_val = cell_v.value

                if formula_val is None and cached_val is None:
                    continue  # blank cell — skip

                col_letter = _col_to_letters(col_idx)

                # Formula detection
                if isinstance(formula_val, str) and formula_val.startswith("="):
                    formula = formula_val
                else:
                    formula = None

                # Parse cached value
                value = (
                    _parse_cached_value(cached_val) if cached_val is not None else None
                )

                cells.append(
                    CellSnapshot(
                        sheet=sn,
                        col=col_letter,
                        row=row_idx,
                        formula=formula,
                        value=value,
                    )
                )

    # Defined names
    defined_names: dict[str, str] = {}
    for name, desc in wb_f.defined_names.items():
        # desc.attr_text is something like "参数表!$C$36" or "指标汇总!#REF!"
        attr_text = str(desc.attr_text) if hasattr(desc, "attr_text") else str(desc)
        defined_names[name] = attr_text

    wb_f.close()
    wb_v.close()

    return WorkbookSnapshot(
        sheets=sheets,
        cells=cells,
        defined_names=defined_names,
    )
