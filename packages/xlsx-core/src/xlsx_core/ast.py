"""AST for Excel formulas — frozen dataclasses, no mutation.

All nodes are immutable. The parser produces these from formula text
(without leading '=').
The evaluator walks the AST with a resolver to compute values.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# AST node types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Expr:
    """Base for all expression nodes."""

    pass


# --- Literals ---


@dataclass(frozen=True)
class NumberLiteral(Expr):
    value: float


@dataclass(frozen=True)
class StringLiteral(Expr):
    value: str


@dataclass(frozen=True)
class BoolLiteral(Expr):
    value: bool  # True / False


@dataclass(frozen=True)
class ErrorLiteral(Expr):
    error: str  # "#REF!", "#DIV/0!", etc.


@dataclass(frozen=True)
class EmptyArg(Expr):
    """Represents a missing argument in a function call, e.g. IF(A1,,B1)."""

    pass


# --- References ---


@dataclass(frozen=True)
class CellRef(Expr):
    """A cell reference like A1, $A$1, $A1, A$1."""

    col: int  # 0-based column index
    row: int  # 0-based row index
    col_abs: bool  # True if $col
    row_abs: bool  # True if $row
    sheet: str | None = None  # None = same sheet, otherwise qualified sheet name

    @property
    def a1(self) -> str:
        """Render back to A1-style (without sheet prefix)."""
        col_str = _col_to_letters(self.col)
        prefix = "$" if self.col_abs else ""
        col_part = f"{prefix}{col_str}"
        prefix_r = "$" if self.row_abs else ""
        row_part = f"{prefix_r}{self.row + 1}"
        return f"{col_part}{row_part}"

    def to_r1c1(self, anchor_col: int, anchor_row: int) -> str:
        """Render to R1C1 relative to (anchor_col, anchor_row) — 0-based anchor."""
        sheet_prefix = f"{self.sheet}!" if self.sheet else ""
        if self.col_abs:
            col_part = f"C{self.col + 1}"
        else:
            dr = self.col - anchor_col
            col_part = f"C[{dr}]" if dr != 0 else "C"
        if self.row_abs:
            row_part = f"R{self.row + 1}"
        else:
            dr = self.row - anchor_row
            row_part = f"R[{dr}]" if dr != 0 else "R"
        return f"{sheet_prefix}{row_part}{col_part}"


@dataclass(frozen=True)
class RangeRef(Expr):
    """A cell range like A1:B2."""

    start: CellRef
    end: CellRef

    @property
    def a1(self) -> str:  # type: ignore[override]
        return f"{self.start.a1}:{self.end.a1}"


@dataclass(frozen=True)
class DefinedName(Expr):
    """A workbook-scoped defined name."""

    name: str


# --- Operators ---


@dataclass(frozen=True)
class UnaryOp(Expr):
    op: str  # '+', '-'
    operand: Expr


@dataclass(frozen=True)
class BinaryOp(Expr):
    op: str  # '+', '-', '*', '/', '^', '&', '=', '<>', '<', '>', '<=', '>='
    left: Expr
    right: Expr


# --- Function calls ---


@dataclass(frozen=True)
class FuncCall(Expr):
    name: str  # e.g. "SUM", "IF", uppercased
    args: list[Expr] = field(default_factory=list)


# --- Helpers ---


def _col_to_letters(col: int) -> str:
    """Convert 0-based column index to Excel column letters (A, B, ..., Z, AA, ...)."""
    result = ""
    n = col
    while True:
        n, rem = divmod(n, 26)
        result = chr(ord("A") + rem) + result
        if n == 0:
            break
        n -= 1
    return result


def _col_from_letters(letters: str) -> int:
    """Convert Excel column letters to 0-based column index."""
    result = 0
    for ch in letters:
        result = result * 26 + (ord(ch.upper()) - ord("A") + 1)
    return result - 1
