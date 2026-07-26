"""Unit tests for the formula evaluator — function semantics and error propagation."""

from __future__ import annotations

from xlsx_core.evaluator import Evaluator
from xlsx_core.model import ErrorValue, Scalar
from xlsx_core.parser import parse


class _SimpleResolver:
    """Minimal resolver for testing."""

    def __init__(self, values: dict[str, Scalar] | None = None):
        self._values = values or {}

    def resolve_cell(self, sheet: str | None, col: int, row: int) -> Scalar:
        from xlsx_core.ast import _col_to_letters

        key = f"{_col_to_letters(col)}{row + 1}"
        if sheet:
            key = f"{sheet}!{key}"
        return self._values.get(key)

    def resolve_range(
        self,
        sheet: str | None,
        start_col: int,
        start_row: int,
        end_col: int,
        end_row: int,
    ) -> list[Scalar]:
        result: list[Scalar] = []
        for r in range(start_row, end_row + 1):
            for c in range(start_col, end_col + 1):
                result.append(self.resolve_cell(sheet, c, r))
        return result

    def resolve_name(self, name: str) -> Scalar:
        return self._values.get(name)


def _eval_expr(expr: str, values: dict[str, Scalar] | None = None) -> Scalar:
    resolver = _SimpleResolver(values)
    evaluator = Evaluator(resolver)
    ast = parse(expr)
    return evaluator.evaluate(ast)


def test_sum_basic() -> None:
    result = _eval_expr("SUM(1,2,3)")
    assert result == 6.0


def test_sum_range() -> None:
    result = _eval_expr("SUM(A1:A3)", {"A1": 1, "A2": 2, "A3": 3})
    assert result == 6.0


def test_sum_ignore_text() -> None:
    result = _eval_expr("SUM(A1:A3)", {"A1": 1, "A2": "hello", "A3": 3})
    assert result == 4.0


def test_sum_ignore_blank() -> None:
    result = _eval_expr("SUM(A1:A3)", {"A1": 1, "A3": 3})
    assert result == 4.0


def test_sum_error_propagates() -> None:
    result = _eval_expr("SUM(A1:A3)", {"A1": 1, "A2": ErrorValue(error="#REF!")})
    assert isinstance(result, ErrorValue)
    assert result.error == "#REF!"


def test_if_true_branch() -> None:
    result = _eval_expr("IF(1, 42, 0)")
    assert result == 42.0


def test_if_false_branch() -> None:
    result = _eval_expr("IF(0, 42, 99)")
    assert result == 99.0


def test_if_lazy_false() -> None:
    result = _eval_expr("IF(0, #REF!, 99)")
    assert result == 99.0


def test_if_lazy_true() -> None:
    result = _eval_expr("IF(1, 42, #REF!)")
    assert result == 42.0


def test_int_floor() -> None:
    result = _eval_expr("INT(-3.5)")
    assert result == -4.0


def test_int_positive() -> None:
    result = _eval_expr("INT(3.5)")
    assert result == 3.0


def test_min() -> None:
    result = _eval_expr("MIN(3,1,2)")
    assert result == 1.0


def test_max() -> None:
    result = _eval_expr("MAX(3,1,2)")
    assert result == 3.0


def test_average() -> None:
    result = _eval_expr('AVERAGE(1, "text", 3)')
    assert result == 2.0


def test_average_empty() -> None:
    result = _eval_expr('AVERAGE("x")')
    assert isinstance(result, ErrorValue)
    assert result.error == "#DIV/0!"


def test_and() -> None:
    assert _eval_expr("AND(1,2)") is True
    assert _eval_expr("AND(1,0)") is False


def test_or() -> None:
    assert _eval_expr("OR(0,0)") is False
    assert _eval_expr("OR(0,1)") is True


def test_comparison_numeric() -> None:
    assert _eval_expr("1=1") is True
    assert _eval_expr("1=2") is False
    assert _eval_expr("1<2") is True


def test_concat() -> None:
    result = _eval_expr('"hello"&" world"')
    assert result == "hello world"


def test_division_by_zero() -> None:
    result = _eval_expr("1/0")
    assert isinstance(result, ErrorValue)
    assert result.error == "#DIV/0!"


def test_error_propagation_arithmetic() -> None:
    result = _eval_expr("1+#REF!")
    assert isinstance(result, ErrorValue)
    assert result.error == "#REF!"


def test_error_propagation_function() -> None:
    result = _eval_expr("SUM(1,#REF!,3)")
    assert isinstance(result, ErrorValue)
    assert result.error == "#REF!"


def test_npv() -> None:
    result = _eval_expr("NPV(0.1, 1, 1, 1)")
    expected = 1 / 1.1 + 1 / 1.21 + 1 / 1.331
    assert abs(float(result) - expected) < 1e-10  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]


def test_pmt_end() -> None:
    result = _eval_expr("PMT(0.08/12, 360, 200000)")
    expected = -1467.53
    assert abs(float(result) - expected) < 0.1  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]


def test_pmt_begin() -> None:
    result = _eval_expr("PMT(0.08/12, 360, 200000, 0, 1)")
    expected = -1457.81  # type=1 shifts by (1+r)
    assert abs(float(result) - expected) < 0.1  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]


def test_sumif_numeric() -> None:
    result = _eval_expr("SUMIF(A1:A4, 1, A1:A4)", {"A1": 1, "A2": 2, "A3": 1, "A4": 3})
    assert result == 2.0


def test_sumif_criteria_gt() -> None:
    result = _eval_expr(
        'SUMIF(A1:A4, ">1", A1:A4)',
        {"A1": 1, "A2": 2, "A3": 1, "A4": 3},
    )
    assert result == 5.0


def test_irr_simple() -> None:
    result = _eval_expr("IRR(A1:A4)", {"A1": -1000, "A2": 100, "A3": 200, "A4": 800})
    assert isinstance(result, (int, float))
    assert abs(float(result)) < 1.0  # type: ignore[arg-type]


def test_boolean_arithmetic() -> None:
    result = _eval_expr("TRUE+1")
    assert result == 2.0


def test_percent_postfix() -> None:
    result = _eval_expr("100%+1")
    assert result == 2.0
