"""Formulas-package recalculation adapter.

Uses the ``formulas`` Python package to load + calculate a workbook in-process.
Output keys are ``'[BOOK.XLSX]SHEET'!A1`` — sheet name is appended after ``]``.

Expect partial function support (IRR, PMT, SUMIF may be missing) — the
benchmark decides whether it is viable.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from xlsx_core.recalc.base import RecalcResult


class FormulasPkgRecalc:
    """Recalculate a workbook via the ``formulas`` Python package.

    The formulas package evaluates Excel formulas in pure Python.  The model's
    ``.cells`` dict is populated after ``.calculate()`` with Ref objects whose
    ``.value`` attribute holds the computed result.
    """

    name: str = "formulas-pkg"

    def recalc(self, workbook: Path, out_dir: Path) -> RecalcResult:
        t0 = time.perf_counter()
        errors: list[str] = []

        try:
            from formulas import ExcelModel
        except ImportError as exc:
            wall = time.perf_counter() - t0
            return RecalcResult(
                engine=self.name,
                ok=False,
                wall_seconds=wall,
                errors=(f"ImportError: {exc}",),
            )

        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            model = ExcelModel().load(str(workbook))
            model.calculate()  # in-place computation; model.cells updated
        except Exception as exc:
            wall = time.perf_counter() - t0
            return RecalcResult(
                engine=self.name,
                ok=False,
                wall_seconds=wall,
                errors=(f"Calculation failed: {exc}",),
            )

        wall = time.perf_counter() - t0

        # Extract values into a dict keyed by sheet!cell (canonical form)
        lines: list[str] = []
        formula_cells = 0

        if model.cells:
            # Key format: '[BOOK.XLSX]SHEET_NAME'!A1
            # Sheet name is appended directly after the closing bracket
            key_re = re.compile(r"^'\[.+?\](.+?)'!(.+)$")
            for key, ref in model.cells.items():
                m = key_re.match(str(key))
                if m is None:
                    continue
                sheet_name = m.group(1)
                coord = m.group(2)
                val = ref.value if hasattr(ref, "value") else ref
                # Skip sentinel "empty" values (formulas that couldn't be computed)
                if val == "empty":
                    continue

                formula_cells += 1
                lines.append(f"{sheet_name}!{coord}\t{val}")

        output_path = out_dir / f"{workbook.stem}.formulas.values.txt"
        output_path.write_text("\n".join(lines), encoding="utf-8")

        return RecalcResult(
            engine=self.name,
            ok=len(errors) == 0,
            wall_seconds=wall,
            errors=tuple(errors),
            recalced_path=output_path,
        )
