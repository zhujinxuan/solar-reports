"""Formula evaluator — walks the AST with a Resolver protocol.

Semantics match Excel:
  - Blank cell → 0 in numeric context, "" in string context
  - Excel truthiness: 0, "", FALSE are falsy; everything else truthy
  - Bool → 1/0 in arithmetic; numbers → truthy in bool context
  - IF lazy: only evaluate the selected branch
  - Error propagation: any op on ErrorValue → that error
  - SUM/AVERAGE/MIN/MAX over ranges: ignore text/blank, error propagates
  - INT = floor toward -inf (not truncation)
  - AND/OR: boolean semantics, short-circuit
  - SUMIF(range, criteria, [sum_range]) with criteria parsing
  - NPV(rate, values...) = Σ v_i / (1+r)^i for i=1..n
  - IRR(values, guess=0.1): Newton + bisection fallback, first cashflow at t=0
  - PMT(rate, nper, pv, fv=0, type=0)
  - Comparison ops: numbers compared as numbers, strings as strings
  - & string concatenation: numbers/booleans converted to string representation
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Protocol

from xlsx_core.ast import (
    BinaryOp,
    BoolLiteral,
    CellRef,
    DefinedName,
    EmptyArg,
    ErrorLiteral,
    Expr,
    FuncCall,
    NumberLiteral,
    RangeRef,
    StringLiteral,
    UnaryOp,
)
from xlsx_core.model import ErrorValue, Scalar

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Resolver protocol
# ---------------------------------------------------------------------------


class CellResolver(Protocol):
    """Resolves cell references and defined names during evaluation."""

    def resolve_cell(self, sheet: str | None, col: int, row: int) -> Scalar: ...

    def resolve_range(
        self,
        sheet: str | None,
        start_col: int,
        start_row: int,
        end_col: int,
        end_row: int,
    ) -> list[Scalar]: ...

    def resolve_name(self, name: str) -> Scalar: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXCEL_ERRORS: set[str] = {
    "#REF!",
    "#DIV/0!",
    "#VALUE!",
    "#N/A",
    "#NAME?",
    "#NULL!",
    "#NUM!",
}


def _is_error(v: Scalar) -> bool:
    return isinstance(v, ErrorValue)


def _error_if_error(v: Scalar) -> Scalar:
    """Return the error if v is an error, else return None signal."""
    return v if isinstance(v, ErrorValue) else None


def _to_number(v: Scalar) -> Scalar:
    """Convert a scalar to number for arithmetic, or return error."""
    if v is None:
        return 0.0
    if isinstance(v, ErrorValue):
        return v
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        # Try to parse
        try:
            return float(v)
        except ValueError:
            return ErrorValue(error="#VALUE!")
    return ErrorValue(error="#VALUE!")


def _to_bool(v: Scalar) -> Scalar:
    """Excel truthiness test. Returns a bool or ErrorValue."""
    if v is None:
        return False
    if isinstance(v, ErrorValue):
        return v
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0.0
    if isinstance(v, str):
        return v != ""
    return False


def _is_truthy(v: Scalar) -> bool:
    """Excel truthiness: 0, "", FALSE → false."""
    if v is None:
        return False
    if isinstance(v, ErrorValue):
        return False  # caller should check _is_error first
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0.0
    if isinstance(v, str):
        return v != ""
    return bool(v)


def _numbers_equal(
    a: float, b: float, rel_tol: float = 1e-6, abs_tol: float = 1e-9
) -> bool:
    """Check if two floats match within tolerances."""
    return abs(a - b) <= max(rel_tol * abs(b), abs_tol)


def _parse_criteria(criteria_str: str | float) -> tuple[str, float | str]:
    """Parse a SUMIF criteria string like '>0', '<=5', '<>x', or plain value.

    Returns (op, operand) where op is one of '=', '<>', '>', '>=', '<', '<='.
    """
    if isinstance(criteria_str, (int, float)):
        return "=", float(criteria_str)
    s = str(criteria_str)
    if not s or s[0] not in "><=":
        return "=", s
    if s.startswith("<>"):
        rest = s[2:]
        try:
            return "<>", float(rest)
        except ValueError:
            return "<>", rest
    if s.startswith("<="):
        rest = s[2:]
        try:
            return "<=", float(rest)
        except ValueError:
            return "<=", rest
    if s.startswith(">="):
        rest = s[2:]
        try:
            return ">=", float(rest)
        except ValueError:
            return ">=", rest
    if s.startswith("<"):
        rest = s[1:]
        try:
            return "<", float(rest)
        except ValueError:
            return "<", rest
    if s.startswith(">"):
        rest = s[1:]
        try:
            return ">", float(rest)
        except ValueError:
            return ">", rest
    if s.startswith("="):
        rest = s[1:]
        try:
            return "=", float(rest)
        except ValueError:
            return "=", rest
    try:
        return "=", float(s)
    except ValueError:
        return "=", s


def _meets_criteria(val: Scalar, op: str, operand: str | float) -> bool:
    """Check if val meets the SUMIF criteria."""
    # Blank cells → 0 for numeric comparison, "" for string
    nv = _to_number(val)
    if _is_error(nv):
        return False
    nv_f = float(nv)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
    if isinstance(operand, (int, float)):
        op_f = float(operand)
        _cmp = {"=": nv_f == op_f, "<>": nv_f != op_f, ">": nv_f > op_f,
                ">=": nv_f >= op_f, "<": nv_f < op_f, "<=": nv_f <= op_f}
        return _cmp.get(op, False)
    else:
        # String comparison
        sv = str(val) if val is not None else ""
        os_str = str(operand)
        if op == "=":
            return sv == os_str
        elif op == "<>":
            return sv != os_str
        return False
    return False


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------


class Evaluator:
    """Evaluates formula ASTs with a CellResolver."""

    def __init__(self, resolver: CellResolver) -> None:
        self._resolver = resolver

    def evaluate(self, ast: Expr) -> Scalar:
        """Evaluate an AST to a Scalar."""
        return self._eval(ast)

    def _eval(self, node: Expr) -> Scalar:
        if isinstance(node, NumberLiteral):
            return node.value
        if isinstance(node, StringLiteral):
            return node.value
        if isinstance(node, BoolLiteral):
            return node.value
        if isinstance(node, ErrorLiteral):
            return ErrorValue(error=node.error)
        if isinstance(node, EmptyArg):
            return None  # treated as blank/omitted

        if isinstance(node, CellRef):
            sheet = node.sheet
            col = node.col
            row = node.row
            result = self._resolver.resolve_cell(sheet, col, row)
            # Excel: blank cell reference returns 0 in bare formula context
            if result is None:
                return 0.0
            return result

        if isinstance(node, RangeRef):
            # Ranges are resolved in context (by functions that consume them)
            # If standalone, return first cell
            sheet = node.start.sheet
            vals = self._resolver.resolve_range(
                sheet,
                node.start.col,
                node.start.row,
                node.end.col,
                node.end.row,
            )
            if vals:
                return vals[0] if vals[0] is not None else 0.0
            return 0.0

        if isinstance(node, DefinedName):
            return self._resolver.resolve_name(node.name)

        if isinstance(node, UnaryOp):
            val = self._eval(node.operand)
            if _is_error(val):
                return val
            n = _to_number(val)
            if _is_error(n):
                return n
            n_f = float(n)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
            if node.op == "-":
                return -n_f
            return n_f

        if isinstance(node, BinaryOp):
            return self._eval_binary(node)

        if isinstance(node, FuncCall):
            return self._eval_func(node)

        return ErrorValue(error="#VALUE!")

    def _eval_binary(self, node: BinaryOp) -> Scalar:
        op = node.op

        # String concatenation
        if op == "&":
            left = self._eval(node.left)
            right = self._eval(node.right)
            if _is_error(left):
                return left
            if _is_error(right):
                return right

            # Excel &: convert to string representation
            def _to_str(v: Scalar) -> str:
                if v is None:
                    return ""
                if isinstance(v, bool):
                    return "TRUE" if v else "FALSE"
                if isinstance(v, float):
                    if v == int(v) and abs(v) < 1e15:
                        return str(int(v))
                    return f"{v:.15g}"
                return str(v)

            return _to_str(left) + _to_str(right)

        # Comparison operators
        if op in ("=", "<>", "<", ">", "<=", ">="):
            left = self._eval(node.left)
            right = self._eval(node.right)
            if _is_error(left):
                return left
            if _is_error(right):
                return right
            # Excel comparison: numbers compared numerically, strings lexicographically
            # If either is a number or can be parsed as a number, do numeric comparison
            l_num = _to_number(left)
            r_num = _to_number(right)

            if not _is_error(l_num) and not _is_error(r_num):
                lf = float(l_num)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
                rf = float(r_num)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
            elif isinstance(left, str) and isinstance(right, str):
                lf = left
                rf = right
            elif isinstance(left, str) and not _is_error(r_num):
                # String vs number — excel compares string as > any number
                return op in ("<>", ">", ">=")
            elif not _is_error(l_num) and isinstance(right, str):
                return op not in ("<>", "<", "<=")
            else:
                lf = str(left) if left is not None else ""
                rf = str(right) if right is not None else ""

            _cmp: dict[str, object] = {
                "=": lf == rf, "<>": lf != rf, "<": lf < rf,  # ty:ignore[unsupported-operator]
                ">": lf > rf, "<=": lf <= rf, ">=": lf >= rf,  # ty:ignore[unsupported-operator]
            }
            return _cmp.get(op, False)  # type: ignore[return-value]  # ty:ignore[invalid-return-type]

        # Arithmetic operators
        left = self._eval(node.left)
        if _is_error(left):
            return left
        left_n = _to_number(left)
        if _is_error(left_n):
            return left_n

        right = self._eval(node.right)
        if _is_error(right):
            return right
        right_n = _to_number(right)
        if _is_error(right_n):
            return right_n

        lf = float(left_n)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
        rf = float(right_n)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]

        if op == "+":
            return lf + rf
        elif op == "-":
            return lf - rf
        elif op == "*":
            return lf * rf
        elif op == "/":
            if rf == 0.0:
                return ErrorValue(error="#DIV/0!")
            return lf / rf
        elif op == "^":
            try:
                return lf**rf
            except (ValueError, OverflowError):
                return ErrorValue(error="#NUM!")

        return ErrorValue(error="#VALUE!")

    def _eval_func(self, node: FuncCall) -> Scalar:
        name = node.name.upper()
        args = node.args

        if name == "IF":
            return self._eval_if(args)
        elif name == "SUM":
            return self._eval_aggregate(args, "sum")
        elif name == "AVERAGE":
            return self._eval_aggregate(args, "average")
        elif name == "MIN":
            return self._eval_aggregate(args, "min")
        elif name == "MAX":
            return self._eval_aggregate(args, "max")
        elif name == "INT":
            return self._eval_int(args)
        elif name == "AND":
            return self._eval_and(args)
        elif name == "OR":
            return self._eval_or(args)
        elif name == "SUMIF":
            return self._eval_sumif(args)
        elif name == "NPV":
            return self._eval_npv(args)
        elif name == "IRR":
            return self._eval_irr(args)
        elif name == "PMT":
            return self._eval_pmt(args)

        # Unknown function — return error
        return ErrorValue(error="#NAME?")

    # --- IF ---

    def _eval_if(self, args: list[Expr]) -> Scalar:
        if len(args) < 2:
            return ErrorValue(error="#VALUE!")
        cond = self._eval(args[0])
        if _is_error(cond):
            return cond
        if _is_truthy(cond):
            return self._eval(args[1])
        if len(args) >= 3:
            return self._eval(args[2])
        return False  # Excel default for missing else

    # --- Aggregate functions ---

    def _eval_aggregate(self, args: list[Expr], func: str) -> Scalar:
        """SUM/AVERAGE/MIN/MAX over args — ignore text/blank, propagate errors."""
        values: list[float] = []
        for arg in args:
            if isinstance(arg, RangeRef):
                sheet = arg.start.sheet
                vals = self._resolver.resolve_range(
                    sheet,
                    arg.start.col,
                    arg.start.row,
                    arg.end.col,
                    arg.end.row,
                )
                for v in vals:
                    if v is None:
                        continue
                    if isinstance(v, ErrorValue):
                        return v
                    n = _to_number(v)
                    if isinstance(n, ErrorValue):
                        continue  # text/blank ignored
                    values.append(float(n))  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
            else:
                v = self._eval(arg)
                if v is None:
                    continue
                if isinstance(v, ErrorValue):
                    return v
                n = _to_number(v)
                if isinstance(n, ErrorValue):
                    continue
                values.append(float(n))  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]

        if not values:
            if func == "sum":
                return 0.0
            if func == "average":
                return ErrorValue(error="#DIV/0!")
            if func == "min":
                return 0.0
            if func == "max":
                return 0.0

        if func == "sum":
            return sum(values)
        if func == "average":
            return sum(values) / len(values)
        if func == "min":
            return min(values)
        if func == "max":
            return max(values)
        return ErrorValue(error="#VALUE!")

    # --- INT ---

    def _eval_int(self, args: list[Expr]) -> Scalar:
        if len(args) < 1:
            return ErrorValue(error="#VALUE!")
        v = self._eval(args[0])
        if _is_error(v):
            return v
        n = _to_number(v)
        if _is_error(n):
            return n
        return float(math.floor(float(n)))  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]

    # --- AND / OR ---

    def _eval_and(self, args: list[Expr]) -> Scalar:
        if not args:
            return ErrorValue(error="#VALUE!")
        for arg in args:
            if isinstance(arg, RangeRef):
                vals = self._resolver.resolve_range(
                    arg.start.sheet,
                    arg.start.col,
                    arg.start.row,
                    arg.end.col,
                    arg.end.row,
                )
                for v in vals:
                    if isinstance(v, ErrorValue):
                        return v
                    if not _is_truthy(v):
                        return False
            else:
                v = self._eval(arg)
                if isinstance(v, ErrorValue):
                    return v
                if not _is_truthy(v):
                    return False
        return True

    def _eval_or(self, args: list[Expr]) -> Scalar:
        if not args:
            return ErrorValue(error="#VALUE!")
        for arg in args:
            if isinstance(arg, RangeRef):
                vals = self._resolver.resolve_range(
                    arg.start.sheet,
                    arg.start.col,
                    arg.start.row,
                    arg.end.col,
                    arg.end.row,
                )
                for v in vals:
                    if isinstance(v, ErrorValue):
                        return v
                    if _is_truthy(v):
                        return True
            else:
                v = self._eval(arg)
                if isinstance(v, ErrorValue):
                    return v
                if _is_truthy(v):
                    return True
        return False

    # --- SUMIF ---

    def _eval_sumif(self, args: list[Expr]) -> Scalar:
        """SUMIF(range, criteria, [sum_range]).

        If sum_range is omitted, range is summed.
        """
        if len(args) < 2:
            return ErrorValue(error="#VALUE!")

        # Evaluate criteria
        criteria_val = self._eval(args[1])
        if _is_error(criteria_val):
            return criteria_val
        if criteria_val is None:
            criteria_val = 0.0
        op, operand = _parse_criteria(criteria_val)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]

        # Get range values
        range_arg = args[0]
        range_vals: list[Scalar] = []
        if isinstance(range_arg, RangeRef):
            range_vals = self._resolver.resolve_range(
                range_arg.start.sheet,
                range_arg.start.col,
                range_arg.start.row,
                range_arg.end.col,
                range_arg.end.row,
            )
        else:
            v = self._eval(range_arg)
            if _is_error(v):
                return v
            range_vals = [v]

        # Get sum range values (or use range itself)
        if len(args) >= 3:
            sum_arg = args[2]
            if isinstance(sum_arg, RangeRef):
                sum_vals = self._resolver.resolve_range(
                    sum_arg.start.sheet,
                    sum_arg.start.col,
                    sum_arg.start.row,
                    sum_arg.end.col,
                    sum_arg.end.row,
                )
            else:
                v = self._eval(sum_arg)
                if _is_error(v):
                    return v
                sum_vals = [v]
        else:
            sum_vals = range_vals

        # Sum matching values
        total = 0.0
        for i, rv in enumerate(range_vals):
            if _is_error(rv):
                return rv
            if _meets_criteria(rv, op, operand) and i < len(sum_vals):
                sv = sum_vals[i]
                if _is_error(sv):
                    return sv
                n = _to_number(sv)
                if not _is_error(n):
                        total += float(n)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]

        return total

    # --- NPV ---

    def _eval_npv(self, args: list[Expr]) -> Scalar:
        """NPV(rate, value1, [value2], ...) = Σ v_i / (1+r)^i for i=1..n."""
        if len(args) < 2:
            return ErrorValue(error="#VALUE!")

        rate_v = self._eval(args[0])
        if _is_error(rate_v):
            return rate_v
        rate_n = _to_number(rate_v)
        if _is_error(rate_n):
            return rate_n
        r = float(rate_n)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]

        npv = 0.0
        period = 1
        for arg in args[1:]:
            if isinstance(arg, RangeRef):
                vals = self._resolver.resolve_range(
                    arg.start.sheet,
                    arg.start.col,
                    arg.start.row,
                    arg.end.col,
                    arg.end.row,
                )
                for v in vals:
                    n = _to_number(v)
                    if _is_error(n):
                        continue
                    npv += float(n) / ((1.0 + r) ** period)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
                    period += 1
            else:
                v = self._eval(arg)
                if _is_error(v):
                    return v
                n = _to_number(v)
                if _is_error(n):
                    continue
                npv += float(n) / ((1.0 + r) ** period)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
                period += 1

        return npv

    # --- IRR ---

    def _eval_irr(self, args: list[Expr]) -> Scalar:
        """IRR(values, guess=0.1): internal rate of return using Newton + bisection.

        Excel convention: first cashflow at t=0, so NPV formula is
        Σ CF_i / (1+irr)^i = 0  for i=0..n-1
        """
        if len(args) < 1:
            return ErrorValue(error="#VALUE!")

        # Collect cash flows
        cfs: list[float] = []
        for arg in args:
            if isinstance(arg, RangeRef):
                vals = self._resolver.resolve_range(
                    arg.start.sheet,
                    arg.start.col,
                    arg.start.row,
                    arg.end.col,
                    arg.end.row,
                )
                for v in vals:
                    n = _to_number(v)
                    if _is_error(n):
                        continue
                    cfs.append(float(n))  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
            else:
                v = self._eval(arg)
                if _is_error(v):
                    return v
                n = _to_number(v)
                if _is_error(n):
                    continue
                cfs.append(float(n))  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]

        if len(cfs) < 2:
            return ErrorValue(error="#NUM!")

        # Extract guess (first element is guess if we have args with number)
        guess = 0.1
        if len(args) >= 2 and not isinstance(args[0], RangeRef):
            # First arg already in cfs[0]; guess comes from second arg
            # The guess should be from the second argument
            pass  # cfs already includes all values; guess is separate in Excel
        # Actually, in Excel, IRR takes values as first arg and guess as second.
        # In our AST, if args[0] is a range, cfs has all range values.
        # The second arg (if present) is the guess.
        if len(args) >= 2 and not isinstance(args[1], RangeRef):
            gv = self._eval(args[1])
            gn = _to_number(gv)
            if not _is_error(gn):
                guess = float(gn)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]

        return self._compute_irr(cfs, guess)

    @staticmethod
    def _compute_irr(cfs: list[float], guess: float) -> Scalar:
        """Compute IRR using Newton's method with bisection fallback."""

        # NPV at rate r: Σ CF_i / (1+r)^i for i=0..n-1 (Excel convention)
        def npv(r: float) -> float:
            total = 0.0
            for i, cf in enumerate(cfs):
                denom = (1.0 + r) ** i
                if abs(denom) > 1e100:
                    return total if total != 0.0 else (1e100 if denom > 0 else -1e100)
                total += cf / denom
            return total

        # Derivative: Σ -i * CF_i / (1+r)^(i+1)
        def dnpv(r: float) -> float:
            total = 0.0
            for i, cf in enumerate(cfs):
                if i == 0:
                    continue
                denom = (1.0 + r) ** (i + 1)
                if abs(denom) > 1e100:
                    continue
                total += -i * cf / denom
            return total

        rate = guess
        max_iter = 100
        tol = 1e-10

        for _ in range(max_iter):
            f = npv(rate)
            if abs(f) < tol:
                return rate
            d = dnpv(rate)
            if d == 0.0:
                break
            new_rate = rate - f / d

            # Newton went wild — fall back to bisection
            if new_rate <= -1.0 or abs(new_rate - rate) > 2.0:
                return Evaluator._irr_bisection(cfs, guess)

            rate = new_rate

        # If Newton didn't converge, try bisection
        return Evaluator._irr_bisection(cfs, guess)

    @staticmethod
    def _irr_bisection(cfs: list[float], guess: float) -> Scalar:
        """Bisection fallback for IRR."""

        def npv(r: float) -> float:
            total = 0.0
            for i, cf in enumerate(cfs):
                denom = (1.0 + r) ** i
                if abs(denom) > 1e100:
                    return total if total != 0.0 else (1e100 if denom > 0 else -1e100)
                total += cf / denom
            return total

        # Try to bracket the root
        lo = -0.99
        hi = 2.0

        # Expand brackets if needed
        for _ in range(50):
            f_lo = npv(lo)
            f_hi = npv(hi)
            if f_lo * f_hi <= 0:
                break
            if abs(f_lo) < abs(f_hi):
                lo = max(-0.9999, lo - (hi - lo))
            else:
                hi += hi - lo
        else:
            # Couldn't bracket — try scanning from guess
            for delta in [0.1, 0.5, 1.0, -0.1, -0.5]:
                lo2 = guess + delta
                if npv(guess) * npv(lo2) <= 0:
                    lo = guess
                    hi = lo2
                    break

        # Bisection
        for _ in range(100):
            mid = (lo + hi) / 2.0
            f_mid = npv(mid)
            if abs(f_mid) < 1e-8:
                return mid
            f_lo = npv(lo)
            if f_lo * f_mid <= 0:
                hi = mid
            else:
                lo = mid

        return ErrorValue(error="#NUM!")

    # --- PMT ---

    def _eval_pmt(self, args: list[Expr]) -> Scalar:
        """PMT(rate, nper, pv, [fv=0], [type=0]).

        type=0: payments at end of period; type=1: payments at beginning.
        """
        if len(args) < 3:
            return ErrorValue(error="#VALUE!")

        rate_v = self._eval(args[0])
        if _is_error(rate_v):
            return rate_v
        rate_n = _to_number(rate_v)
        if _is_error(rate_n):
            return rate_n
        r = float(rate_n)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]

        nper_v = self._eval(args[1])
        if _is_error(nper_v):
            return nper_v
        nper_n = _to_number(nper_v)
        if _is_error(nper_n):
            return nper_n
        nper = int(float(nper_n))  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]

        pv_v = self._eval(args[2])
        if _is_error(pv_v):
            return pv_v
        pv_n = _to_number(pv_v)
        if _is_error(pv_n):
            return pv_n
        pv = float(pv_n)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]

        fv = 0.0
        if len(args) >= 4:
            fv_v = self._eval(args[3])
            if _is_error(fv_v):
                return fv_v
            fv_n = _to_number(fv_v)
            if _is_error(fv_n):
                return fv_n
            fv = float(fv_n)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]

        pmt_type = 0
        if len(args) >= 5:
            type_v = self._eval(args[4])
            if _is_error(type_v):
                return type_v
            type_n = _to_number(type_v)
            if not _is_error(type_n):
                pmt_type = int(float(type_n))  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]

        if r == 0:
            return -(pv + fv) / nper

        # PMT formula
        factor = (1.0 + r) ** nper
        if pmt_type == 0:
            pmt_val = -(pv * factor + fv) * r / (factor - 1)
        else:
            pmt_val = -(pv * factor + fv) * r / ((factor - 1) * (1.0 + r))

        return pmt_val


# ---------------------------------------------------------------------------
# Convenience: build a resolver backed by a dict
# ---------------------------------------------------------------------------


class DictResolver:
    """Resolver backed by a dict mapping "sheet!A1" → Scalar.

    Supports cell resolution (by id), range resolution (by scanning),
    and name resolution (by lookup in a names dict).
    """

    def __init__(
        self,
        values: dict[str, Scalar],
        defined_names: dict[str, str] | None = None,
    ) -> None:
        self._values = values
        self._names = defined_names or {}

    def resolve_cell(self, sheet: str | None, col: int, row: int) -> Scalar:
        from xlsx_core.ast import _col_to_letters

        col_str = _col_to_letters(col)
        key = f"{sheet}!{col_str}{row + 1}" if sheet else f"{col_str}{row + 1}"
        return self._values.get(key)

    def resolve_range(
        self,
        sheet: str | None,
        start_col: int,
        start_row: int,
        end_col: int,
        end_row: int,
    ) -> list[Scalar]:
        from xlsx_core.ast import _col_to_letters

        result: list[Scalar] = []
        for r in range(start_row, end_row + 1):
            for c in range(start_col, end_col + 1):
                col_str = _col_to_letters(c)
                key = f"{sheet}!{col_str}{r + 1}" if sheet else f"{col_str}{r + 1}"
                result.append(self._values.get(key))
        return result

    def resolve_name(self, name: str) -> Scalar:
        target = self._names.get(name, "")
        if not target:
            return ErrorValue(error="#NAME?")
        # defined name target is "sheet!A1" or "sheet!#REF!"
        if "#REF!" in target:
            return ErrorValue(error="#REF!")
        return self._values.get(target)
