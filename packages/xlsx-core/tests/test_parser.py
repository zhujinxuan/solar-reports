"""Unit tests for the formula parser."""

from __future__ import annotations

from xlsx_core.ast import (
    BinaryOp,
    BoolLiteral,
    CellRef,
    DefinedName,
    ErrorLiteral,
    FuncCall,
    NumberLiteral,
    RangeRef,
    StringLiteral,
    UnaryOp,
)
from xlsx_core.parser import parse, to_r1c1


def test_number_literal() -> None:
    ast = parse("42")
    assert isinstance(ast, NumberLiteral)
    assert ast.value == 42.0


def test_string_literal() -> None:
    ast = parse('"hello"')
    assert isinstance(ast, StringLiteral)
    assert ast.value == "hello"


def test_bool_literal() -> None:
    assert isinstance(parse("TRUE"), BoolLiteral)
    assert parse("TRUE").value is True  # type: ignore[union-attr]  # ty:ignore[unresolved-attribute]
    assert parse("FALSE").value is False  # type: ignore[union-attr]  # ty:ignore[unresolved-attribute]


def test_error_literal() -> None:
    for err in ("#REF!", "#DIV/0!", "#VALUE!", "#N/A", "#NAME?", "#NULL!", "#NUM!"):
        ast = parse(err)
        assert isinstance(ast, ErrorLiteral)
        assert ast.error == err


def test_cell_ref_absolute() -> None:
    ast = parse("$A$1")
    assert isinstance(ast, CellRef)
    assert ast.col == 0
    assert ast.row == 0
    assert ast.col_abs is True
    assert ast.row_abs is True


def test_cell_ref_relative() -> None:
    ast = parse("B2")
    assert isinstance(ast, CellRef)
    assert ast.col == 1
    assert ast.row == 1
    assert ast.col_abs is False
    assert ast.row_abs is False


def test_cell_ref_mixed() -> None:
    ast = parse("$C3")
    assert isinstance(ast, CellRef)
    assert ast.col == 2
    assert ast.row == 2
    assert ast.col_abs is True
    assert ast.row_abs is False


def test_range_ref() -> None:
    ast = parse("A1:B2")
    assert isinstance(ast, RangeRef)
    assert ast.start.col == 0
    assert ast.start.row == 0
    assert ast.end.col == 1
    assert ast.end.row == 1


def test_sheet_qualified_ref() -> None:
    ast = parse("Sheet1!A1")
    assert isinstance(ast, CellRef)
    assert ast.sheet == "Sheet1"
    assert ast.col == 0
    assert ast.row == 0


def test_sheet_qualified_cjk() -> None:
    ast = parse("损益!G8")
    assert isinstance(ast, CellRef)
    assert ast.sheet == "损益"
    assert ast.col == 6
    assert ast.row == 7


def test_sheet_qualified_range() -> None:
    ast = parse("损益!G5:AE5")
    assert isinstance(ast, RangeRef)
    assert ast.start.sheet == "损益"
    assert ast.end.sheet == "损益"


def test_defined_name() -> None:
    ast = parse("增值税率")
    assert isinstance(ast, DefinedName)
    assert ast.name.upper() == "增值税率".upper()


def test_simple_binary_op() -> None:
    ast = parse("1+2")
    assert isinstance(ast, BinaryOp)
    assert ast.op == "+"
    assert isinstance(ast.left, NumberLiteral)
    assert isinstance(ast.right, NumberLiteral)


def test_precedence() -> None:
    ast = parse("1+2*3")
    assert isinstance(ast, BinaryOp)
    assert ast.op == "+"
    assert isinstance(ast.right, BinaryOp)
    assert ast.right.op == "*"  # type: ignore[union-attr]


def test_parentheses() -> None:
    ast = parse("(1+2)*3")
    assert isinstance(ast, BinaryOp)
    assert ast.op == "*"


def test_unary_minus() -> None:
    ast = parse("-A1")
    assert isinstance(ast, UnaryOp)
    assert ast.op == "-"
    assert isinstance(ast.operand, CellRef)


def test_percent() -> None:
    ast = parse("100%")
    assert isinstance(ast, BinaryOp)
    assert ast.op == "/"
    assert isinstance(ast.right, NumberLiteral)
    assert ast.right.value == 100.0


def test_function_call() -> None:
    ast = parse("SUM(A1,B2)")
    assert isinstance(ast, FuncCall)
    assert ast.name == "SUM"
    assert len(ast.args) == 2


def test_comparison_ops() -> None:
    for op in ("=", "<>", "<", ">", "<=", ">="):
        ast = parse(f"A1{op}B2")
        assert isinstance(ast, BinaryOp)
        assert ast.op == op


def test_concatenation() -> None:
    ast = parse('"a"&"b"')
    assert isinstance(ast, BinaryOp)
    assert ast.op == "&"


def test_r1c1_canonical() -> None:
    """R1C1 rendering for year-series detection."""
    # Absolute ref
    ast = parse("$C$66")
    r1c1 = to_r1c1(ast, 5, 65)  # anchor at col=5, row=65
    assert r1c1 == "R66C3"

    # Relative ref from different anchor
    ast2 = parse("C66")
    # Anchor at column 3, row 65: C66 relative to D66 = C[-1]
    r1c1_2 = to_r1c1(ast2, 3, 65)
    assert r1c1_2 == "RC[-1]"

    # Anchor at column 2, row 66: C66 relative to C67 = R[-1]C
    r1c1_3 = to_r1c1(ast2, 2, 66)
    assert r1c1_3 == "R[-1]C"


def test_empty_args() -> None:
    ast = parse("IF(A1,,B1)")
    assert isinstance(ast, FuncCall)
    assert len(ast.args) == 3


def test_quoted_sheet() -> None:
    ast = parse("'My Sheet'!A1")
    assert isinstance(ast, CellRef)
    assert ast.sheet == "My Sheet"


def test_float_notation() -> None:
    ast = parse("1e10")
    assert isinstance(ast, NumberLiteral)
    assert ast.value == 1e10
