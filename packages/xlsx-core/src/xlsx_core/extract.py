"""DAG extraction — builds WorkbookDag from the OpenpyxlLoader snapshot.

One-pass extraction for the SOLAR workbook: parse every formula, detect year series,
classify nodes. Writing the YAML is a separate, explicit step (write_dag_yaml).

Exposes `extract_dag(settings) -> WorkbookDag` for reuse by other packages.
"""

from __future__ import annotations

from pathlib import Path

from xlsx_core.ast import Expr
from xlsx_core.loader import WorkbookSnapshot, load_workbook
from xlsx_core.model import (
    DagNode,
    ErrorValue,
    Scalar,
    WorkbookDag,
    YearSeriesMarker,
)
from xlsx_core.parser import ParseError, parse
from xlsx_core.settings import Settings
from xlsx_core.yamlutil import dump_doc
from xlsx_core.year_series import SeriesReport, detect_year_series


def _cell_id(sheet: str, col: str, row: int) -> str:
    """Canonical node id: 'sheet!A1'."""
    return f"{sheet}!{col}{row}"


def _classify_node(
    formula: str | None, cached: Scalar, ast: Expr | None
) -> tuple[str, Scalar, str | None]:
    """Determine type, value, and expression for a node.

    Returns (type, value, expression).
    """
    # Error from cached value
    if isinstance(cached, ErrorValue):
        if formula is not None and ast is not None:
            # Try to extract expression text from formula
            expr_text = formula[1:]  # strip '='
            return ("error", cached, expr_text)
        else:
            return ("error", cached, None)

    # NOTE: an error LITERAL inside the expression (e.g. #REF! in a dead IF
    # branch) does NOT make the node error-typed — classification follows the
    # cached value. Lazy evaluation never touches the dead branch; the live
    # value is what the workbook cached (e.g. 财务计划!E36 caches 0).

    if formula is not None and ast is not None:
        return ("formula", cached, formula[1:])

    return ("literal", cached, None)


def extract_dag(settings: Settings | None = None) -> WorkbookDag:
    """Extract the WorkbookDag from the SOLAR workbook.

    Args:
        settings: Optional Settings object. If None, uses defaults.

    Returns:
        WorkbookDag with all nodes, classified and annotated.
    """
    if settings is None:
        settings = Settings()

    # Load workbook
    snapshot: WorkbookSnapshot = load_workbook(settings.workbook_path)

    # Parse all formula cells and collect ASTs
    # We need (sheet, col_str, row, col_idx, ast) for year series detection
    formula_cells: list[tuple[str, str, int, int, Expr]] = []
    parse_errors: list[str] = []

    for cell in snapshot.cells:
        if cell.formula is not None:
            col_idx = _col_letters_to_index(cell.col)
            try:
                ast = parse(cell.formula[1:])  # strip '='
            except ParseError as e:
                parse_errors.append(f"{_cell_id(cell.sheet, cell.col, cell.row)}: {e}")
                # Create a fallback AST with an error literal
                from xlsx_core.ast import ErrorLiteral

                ast = ErrorLiteral(error="#REF!")
            formula_cells.append((cell.sheet, cell.col, cell.row, col_idx, ast))

    # Detect year series
    series_report: SeriesReport = detect_year_series(formula_cells)  # ty:ignore[invalid-argument-type]

    # Build series lookup: node_id → YearSeriesMarker
    series_by_node: dict[str, tuple[str, int]] = {}
    for s in series_report.series:
        for idx, node_id in enumerate(s.node_ids):
            series_by_node[node_id] = (s.key, idx)

    # Build nodes
    nodes: list[DagNode] = []

    # Pre-build a set of node IDs from formula cells for quick lookup
    formula_cell_asts: dict[str, Expr] = {}
    for sheet, col_str, row, _col_idx, ast in formula_cells:
        formula_cell_asts[_cell_id(sheet, col_str, row)] = ast

    for cell in snapshot.cells:
        node_id = _cell_id(cell.sheet, cell.col, cell.row)
        ast = formula_cell_asts.get(node_id)
        typ, value, expr = _classify_node(cell.formula, cell.value, ast)

        # Year series marker
        yr = None
        if node_id in series_by_node:
            key, idx = series_by_node[node_id]
            yr = YearSeriesMarker(key=key, index=idx)

        nodes.append(
            DagNode(
                id=node_id,
                sheet=cell.sheet,
                col=cell.col,
                row=cell.row,
                type=typ,  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
                expression=expr,
                value=value,
                year_series=yr,
            )
        )

    # Collect defined names
    defined_names = snapshot.defined_names

    dag = WorkbookDag(
        version=1,
        source=str(settings.workbook_path),
        nodes=nodes,
        defined_names=defined_names,
    )


    if parse_errors:
        print(f"Warning: {len(parse_errors)} parse errors found:")
        for pe in parse_errors[:10]:
            print(f"  {pe}")

    return dag


def _col_letters_to_index(letters: str) -> int:
    """Convert column letters to 0-based index."""
    result = 0
    for ch in letters:
        result = result * 26 + (ord(ch.upper()) - ord("A") + 1)
    return result - 1


def _dag_to_yaml_dict(dag: WorkbookDag) -> dict:
    """Convert WorkbookDag to a YAML-serializable dict."""
    nodes_list = []
    for node in dag.nodes:
        n_dict: dict = {
            "id": node.id,
            "sheet": node.sheet,
            "col": node.col,
            "row": node.row,
            "type": node.type,
        }
        if node.expression is not None:
            n_dict["expression"] = node.expression
        # Serialize value
        if isinstance(node.value, ErrorValue):
            n_dict["value"] = node.value.error
        elif isinstance(node.value, bool):
            n_dict["value"] = node.value
        elif node.value is None:
            n_dict["value"] = None
        else:
            n_dict["value"] = node.value

        if node.year_series is not None:
            n_dict["year_series"] = {
                "key": node.year_series.key,
                "index": node.year_series.index,
            }

        nodes_list.append(n_dict)

    return {
        "version": dag.version,
        "source": dag.source,
        "defined_names": dict(dag.defined_names),
        "nodes": nodes_list,
    }


def write_dag_yaml(dag: WorkbookDag, path: Path) -> None:
    """Write a WorkbookDag to a YAML file (explicit; extract_dag never writes)."""
    dag_dict = _dag_to_yaml_dict(dag)

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    dump_doc(dag_dict, path)

    print(f"Written {len(dag.nodes)} nodes to {path}")
