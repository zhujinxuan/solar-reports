"""Unit tests for solar-v1 interpreter: topological order, defined-name resolution,
error-node reproduction, blank-cell semantics, cross-sheet deps.
"""

from __future__ import annotations

import pytest
from solar_v1.interpreter import (
    _build_deps,
    _topological_sort,
    interpret,
)
from xlsx_core.model import (
    DagNode,
    ErrorValue,
    Scalar,
    WorkbookDag,
)
from xlsx_core.settings import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dag(
    nodes: list[DagNode],
    defined_names: dict[str, str] | None = None,
) -> WorkbookDag:
    return WorkbookDag(
        version=1,
        source="test",
        nodes=nodes,
        defined_names=defined_names or {},
    )


def _literal(node_id: str, sheet: str, value: Scalar = 0.0) -> DagNode:
    return DagNode(id=node_id, sheet=sheet, col="A", row=1, type="literal", value=value)


def _formula(node_id: str, sheet: str, col: str, row: int, expr: str) -> DagNode:
    return DagNode(
        id=node_id, sheet=sheet, col=col, row=row,
        type="formula", expression=expr, value=None,
    )


def _error(node_id: str, sheet: str, expr: str) -> DagNode:
    return DagNode(
        id=node_id, sheet=sheet, col="A", row=1,
        type="error", expression=expr,
        value=ErrorValue(error="#REF!"),
    )


# ---------------------------------------------------------------------------
# Topological sort tests
# ---------------------------------------------------------------------------


class TestTopologicalSort:
    def test_linear_chain(self) -> None:
        """A → B → C: order must respect deps."""
        deps = {"C": {"B"}, "B": {"A"}, "A": set()}
        order = _topological_sort(deps)
        assert order.index("A") < order.index("B") < order.index("C")

    def test_diamond(self) -> None:
        """A → B, A → C, B → D, C → D."""
        deps = {"D": {"B", "C"}, "C": {"A"}, "B": {"A"}, "A": set()}
        order = _topological_sort(deps)
        a_idx = order.index("A")
        b_idx = order.index("B")
        c_idx = order.index("C")
        d_idx = order.index("D")
        assert a_idx < b_idx < d_idx
        assert a_idx < c_idx < d_idx

    def test_independent(self) -> None:
        """No deps: all nodes can be in any order."""
        deps = {"A": set(), "B": set(), "C": set()}
        order = _topological_sort(deps)
        assert set(order) == {"A", "B", "C"}
        assert len(order) == 3


# ---------------------------------------------------------------------------
# Dependency graph tests
# ---------------------------------------------------------------------------


class TestBuildDeps:
    def test_literal_no_deps(self) -> None:
        dag = _make_dag([_literal("Sheet1!A1", "Sheet1", 42)])
        deps = _build_deps(dag)
        assert deps["Sheet1!A1"] == set()

    def test_same_sheet_ref(self) -> None:
        dag = _make_dag([
            _literal("Sheet1!A1", "Sheet1", 100),
            _formula("Sheet1!B1", "Sheet1", "B", 1, "A1*2"),
        ])
        deps = _build_deps(dag)
        assert "Sheet1!A1" in deps["Sheet1!B1"]

    def test_cross_sheet_ref(self) -> None:
        dag = _make_dag([
            _literal("Params!C3", "Params", 15),
            _formula("Calc!D5", "Calc", "D", 5, "Params!C3+1"),
        ])
        deps = _build_deps(dag)
        assert "Params!C3" in deps["Calc!D5"]

    def test_defined_name_resolution(self) -> None:
        dag = _make_dag(
            [
                _literal("参数表!C38", "参数表", 0.13),
                _formula("损益!G12", "损益", "G", 12, "增值税率*G11"),
            ],
            defined_names={"增值税率": "参数表!$C$38"},
        )
        deps = _build_deps(dag)
        assert "参数表!C38" in deps["损益!G12"]

    def test_ref_to_missing_cell(self) -> None:
        """Reference to a cell not in the dag → no dependency (it's blank)."""
        dag = _make_dag([
            _formula("Sheet1!B1", "Sheet1", "B", 1, "Z99+1"),
        ])
        deps = _build_deps(dag)
        assert deps["Sheet1!B1"] == set()

    def test_error_ref_in_defined_name(self) -> None:
        """Defined name with #REF! target → no dependency."""
        dag = _make_dag(
            [_formula("Sheet1!A1", "Sheet1", "A", 1, "BadName")],
            defined_names={"BadName": "Sheet1!#REF!"},
        )
        deps = _build_deps(dag)
        assert deps["Sheet1!A1"] == set()

    def test_range_ref(self) -> None:
        dag = _make_dag([
            _literal("Sheet1!A1", "Sheet1", 1),
            _literal("Sheet1!A2", "Sheet1", 2),
            _formula("Sheet1!B1", "Sheet1", "B", 1, "SUM(A1:A2)"),
        ])
        deps = _build_deps(dag)
        assert "Sheet1!A1" in deps["Sheet1!B1"]
        assert "Sheet1!A2" in deps["Sheet1!B1"]


# ---------------------------------------------------------------------------
# Interpretation tests
# ---------------------------------------------------------------------------


class TestInterpret:
    def test_literal_passthrough(self) -> None:
        dag = _make_dag([_literal("X!A1", "X", 42)])
        result = interpret(dag, Settings())
        assert result.values["X!A1"] == 42

    def test_simple_arithmetic(self) -> None:
        dag = _make_dag([
            _literal("S!A1", "S", 10),
            _literal("S!A2", "S", 3),
            _formula("S!B1", "S", "B", 1, "A1+A2*2"),
        ])
        result = interpret(dag, Settings())
        assert result.values["S!B1"] == pytest.approx(16.0)

    def test_blank_ref_is_zero(self) -> None:
        """A cell ref to a blank (not in dag) → 0.0."""
        dag = _make_dag([
            _formula("S!B1", "S", "B", 1, "Z99*5"),
        ])
        result = interpret(dag, Settings())
        assert result.values["S!B1"] == pytest.approx(0.0)

    def test_error_node_reproduces_ref(self) -> None:
        """损益!D4 = 成本!#REF! should evaluate to ErrorValue('#REF!')."""
        dag = _make_dag([
            _error("损益!D4", "损益", "成本!#REF!"),
        ])
        result = interpret(dag, Settings())
        got = result.values["损益!D4"]
        assert isinstance(got, ErrorValue)
        assert got.error == "#REF!"

    def test_cross_sheet_computation(self) -> None:
        dag = _make_dag([
            _literal("Params!C2", "Params", 15),
            _formula("Calc!D5", "Calc", "D", 5, "Params!C2*1000"),
        ])
        result = interpret(dag, Settings())
        assert result.values["Calc!D5"] == pytest.approx(15000.0)

    def test_defined_name_evaluation(self) -> None:
        dag = _make_dag(
            [
                _literal("参数表!C38", "参数表", 0.13),
                _literal("损益!G11", "损益", 1000),
                _formula("损益!G12", "损益", "G", 12, "增值税率*G11"),
            ],
            defined_names={"增值税率": "参数表!$C$38"},
        )
        result = interpret(dag, Settings())
        assert result.values["损益!G12"] == pytest.approx(130.0)

    def test_nested_deps_cascade(self) -> None:
        dag = _make_dag([
            _literal("S!A1", "S", 5),
            _formula("S!B1", "S", "B", 1, "A1*2"),    # 10
            _formula("S!C1", "S", "C", 1, "B1+3"),    # 13
            _formula("S!D1", "S", "D", 1, "C1*C1"),   # 169
        ])
        result = interpret(dag, Settings())
        assert result.values["S!D1"] == pytest.approx(169.0)
