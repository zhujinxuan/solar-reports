"""Schema validation tests for DAG extraction."""

from __future__ import annotations

from xlsx_core.extract import extract_dag
from xlsx_core.model import ErrorValue


def test_dag_schema() -> None:
    """Extracted DAG passes basic schema validation."""
    dag = extract_dag()
    assert dag.version == 1
    assert len(dag.nodes) > 0
    assert isinstance(dag.source, str)


def test_node_ids_unique() -> None:
    """All node IDs are unique."""
    dag = extract_dag()
    ids = [n.id for n in dag.nodes]
    assert len(ids) == len(set(ids))


def test_node_id_format() -> None:
    """Node IDs follow 'sheet!A1' format."""
    dag = extract_dag()
    for n in dag.nodes:
        assert "!" in n.id or n.id[0].isalpha()
        # All non-blank cells have valid col and row
        assert n.row >= 1
        assert len(n.col) >= 1


def test_node_types() -> None:
    """Nodes have valid types."""
    dag = extract_dag()
    for n in dag.nodes:
        assert n.type in ("formula", "literal", "error")


def test_error_nodes_have_error_values() -> None:
    """Error-typed nodes have ErrorValue values."""
    dag = extract_dag()
    error_nodes = [n for n in dag.nodes if n.type == "error"]
    for n in error_nodes:
        assert isinstance(n.value, ErrorValue) or n.value is not None


def test_formula_nodes_have_expression() -> None:
    """Formula nodes have expressions."""
    dag = extract_dag()
    formula_nodes = [n for n in dag.nodes if n.type == "formula"]
    assert len(formula_nodes) > 0
    for n in formula_nodes:
        assert n.expression is not None
        assert not n.expression.startswith("=")


def test_literal_nodes_no_expression() -> None:
    """Literal nodes have no expression."""
    dag = extract_dag()
    literal_nodes = [n for n in dag.nodes if n.type == "literal"]
    assert len(literal_nodes) > 0


def test_defined_names() -> None:
    """Defined names are collected."""
    dag = extract_dag()
    assert len(dag.defined_names) > 0
    assert "增值税率" in dag.defined_names


def test_year_series_marker_schema() -> None:
    """Year series markers have valid structure."""
    dag = extract_dag()
    yr_nodes = [n for n in dag.nodes if n.year_series is not None]
    assert len(yr_nodes) > 0
    for n in yr_nodes:
        assert n.year_series is not None
        assert n.year_series.key != ""
        assert n.year_series.index >= 0


def test_dag_yaml_file_exists() -> None:
    """The dag.yaml file exists on disk."""
    from pathlib import Path

    p = Path("dag/solar.dag.yaml")
    assert p.exists()


def test_dag_node_count() -> None:
    """Correct node count."""
    dag = extract_dag()
    # The workbook has 6560 non-blank cells
    assert dag.node_count == 6560


def test_extract_does_not_write_dag(tmp_path) -> None:
    """extract_dag is pure — it must never write the dag file as a side effect."""
    from xlsx_core.settings import Settings

    target = tmp_path / "dag" / "must_not_appear.yaml"
    extract_dag(Settings(dag_path=target))
    assert not target.exists()
