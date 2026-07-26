"""DAG interpreter — topological evaluation of the workbook DAG at cell resolution.

Builds a dependency graph from formula ASTs (including cross-sheet refs
and defined-name expansion), topologically sorts nodes, then evaluates
each formula through xlsx-core's evaluator. Literal nodes resolve to their
cached value; error nodes evaluate to their ErrorValue. Blank referenced
cells → 0.0 (Excel semantics).

Internal mutation of the values dict is allowed during evaluation;
the public return is always frozen NodeValues.
"""

from __future__ import annotations

import re
from collections import deque

from xlsx_core.ast import (
    BinaryOp,
    CellRef,
    DefinedName,
    FuncCall,
    RangeRef,
    UnaryOp,
    _col_to_letters,
)
from xlsx_core.evaluator import Evaluator
from xlsx_core.model import (
    DagNode,
    ErrorValue,
    NodeValues,
    Scalar,
    WorkbookDag,
)
from xlsx_core.parser import ParseError, parse
from xlsx_core.settings import Settings

# ---------------------------------------------------------------------------
# Dependency graph
# ---------------------------------------------------------------------------


def _build_deps(dag: WorkbookDag) -> dict[str, set[str]]:
    """Build dependency map: node_id → set of node_ids it depends on.

    Walks each formula node's AST to find cell/ranges/defined-name refs,
    resolving them to canonical node_ids in the dag.
    """
    node_map: dict[str, DagNode] = {n.id: n for n in dag.nodes}
    deps: dict[str, set[str]] = {}

    for n in dag.nodes:
        if n.expression is None:
            deps[n.id] = set()
            continue

        try:
            ast = parse(n.expression)
        except ParseError:
            deps[n.id] = set()
            continue

        deps[n.id] = _collect_refs(ast, n.sheet, node_map, dag.defined_names)

    return deps


def _resolve_cell_ref(
    sheet: str | None,
    col: int,
    row_0based: int,
    current_sheet: str,
    node_map: dict[str, DagNode],
) -> str | None:
    """Resolve a cell/range coordinate to a canonical node_id if in the dag."""
    col_str = _col_to_letters(col)
    actual_sheet = sheet if sheet else current_sheet
    node_id = f"{actual_sheet}!{col_str}{row_0based + 1}"
    return node_id if node_id in node_map else None


def _resolve_defined_name(
    name: str,
    defined_names: dict[str, str],
    node_map: dict[str, DagNode],
) -> str | None:
    """Resolve a defined name to a canonical node_id.

    Defined names in this workbook target "sheet!$col$row" or "sheet!#REF!".
    """
    target = defined_names.get(name, "")
    if not target:
        return None
    # Error refs produce no dependency
    if "#REF!" in target:
        return None
    m = re.match(r"^(.+?)!\$?([A-Za-z]+)\$?(\d+)$", target)
    if m:
        node_id = f"{m.group(1)}!{m.group(2)}{m.group(3)}"
        return node_id if node_id in node_map else None
    return None


def _collect_refs(
    ast: object,
    current_sheet: str,
    node_map: dict[str, DagNode],
    defined_names: dict[str, str],
) -> set[str]:
    """Collect all cell references from an AST, resolved to canonical node_ids."""
    refs: set[str] = set()

    def _walk(node: object) -> None:
        if isinstance(node, CellRef):
            rid = _resolve_cell_ref(
                node.sheet, node.col, node.row, current_sheet, node_map
            )
            if rid:
                refs.add(rid)
        elif isinstance(node, RangeRef):
            sheet = node.start.sheet
            for r in range(node.start.row, node.end.row + 1):
                for c in range(node.start.col, node.end.col + 1):
                    rid = _resolve_cell_ref(sheet, c, r, current_sheet, node_map)
                    if rid:
                        refs.add(rid)
        elif isinstance(node, DefinedName):
            rid = _resolve_defined_name(node.name, defined_names, node_map)
            if rid:
                refs.add(rid)
        elif isinstance(node, BinaryOp):
            _walk(node.left)
            _walk(node.right)
        elif isinstance(node, UnaryOp):
            _walk(node.operand)
        elif isinstance(node, FuncCall):
            for a in node.args:
                _walk(a)

    _walk(ast)
    return refs


# ---------------------------------------------------------------------------
# Topological sort (Kahn's algorithm)
# ---------------------------------------------------------------------------


def _topological_sort(deps: dict[str, set[str]]) -> list[str]:
    """Sort nodes in dependency order. Returns ordered list of node_ids."""
    in_degree: dict[str, int] = {nid: len(ds) for nid, ds in deps.items()}
    queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
    result: list[str] = []

    while queue:
        nid = queue.popleft()
        result.append(nid)
        for other, ds in deps.items():
            if nid in ds:
                in_degree[other] -= 1
                if in_degree[other] == 0:
                    queue.append(other)

    return result


# ---------------------------------------------------------------------------
# Sheet-aware resolver (evaluator bridge)
# ---------------------------------------------------------------------------


class _SheetAwareResolver:
    """Resolver that tracks the current sheet for same-sheet cell references.

    The DictResolver from xlsx-core resolves cells by exact key but does not
    handle sheet=None (same-sheet) references — the evaluator passes sheet=None
    to resolve_cell for bare cell refs like 'G5'. This wrapper maintains
    the current sheet context.
    """

    def __init__(
        self,
        values: dict[str, Scalar],
        defined_names: dict[str, str],
    ) -> None:
        self._values = values
        self._names = defined_names
        self._sheet: str = ""

    def set_sheet(self, sheet: str) -> None:
        """Set the current sheet for same-sheet reference resolution."""
        self._sheet = sheet

    def resolve_cell(self, sheet: str | None, col: int, row: int) -> Scalar:
        """Resolve a cell reference. sheet=None means same sheet."""
        actual_sheet = sheet if sheet else self._sheet
        col_str = _col_to_letters(col)
        key = f"{actual_sheet}!{col_str}{row + 1}"
        return self._values.get(key)

    def resolve_range(
        self,
        sheet: str | None,
        start_col: int,
        start_row: int,
        end_col: int,
        end_row: int,
    ) -> list[Scalar]:
        """Resolve a cell range to a flat list of scalars (row-major)."""
        actual_sheet = sheet if sheet else self._sheet
        result: list[Scalar] = []
        for r in range(start_row, end_row + 1):
            for c in range(start_col, end_col + 1):
                col_str = _col_to_letters(c)
                key = f"{actual_sheet}!{col_str}{r + 1}"
                result.append(self._values.get(key))
        return result

    def resolve_name(self, name: str) -> Scalar:
        """Resolve a defined name to its scalar value."""
        target = self._names.get(name, "")
        if not target:
            return ErrorValue(error="#NAME?")
        if "#REF!" in target:
            return ErrorValue(error="#REF!")
        m = re.match(r"^(.+?)!\$?([A-Za-z]+)\$?(\d+)$", target)
        if m:
            key = f"{m.group(1)}!{m.group(2)}{m.group(3)}"
            return self._values.get(key)
        return ErrorValue(error="#NAME?")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def interpret(dag: WorkbookDag, settings: Settings) -> NodeValues:
    """Evaluate every node in the DAG in topological order.

    Literal nodes resolve to their cached value. Error-typed nodes reproduce
    their cached ErrorValue (per contract — their expression may contain
    deleted refs or semantics that diverge from re-evaluation). Formula
    nodes are parsed and evaluated through xlsx-core's evaluator. Blank
    referenced cells → 0.0 (Excel semantics). Errors propagate naturally.

    Args:
        dag: The workbook DAG with all nodes and defined names.
        settings: Evaluation settings (tolerances, paths).

    Returns:
        Frozen NodeValues mapping every node_id to its computed Scalar.
    """
    # Build node lookup
    node_map: dict[str, DagNode] = {n.id: n for n in dag.nodes}

    # Build dependency graph and topologically sort
    deps = _build_deps(dag)
    order = _topological_sort(deps)

    # Seed values dict with literal nodes and all error nodes.
    # Error-typed nodes reproduce their cached ErrorValue per contract —
    # their expression may have been mangled by deleted refs or blank-cell
    # semantics that diverge from re-evaluation.
    values: dict[str, Scalar] = {}
    for n in dag.nodes:
        if n.type == "literal" or n.type == "error":
            values[n.id] = n.value
    # Create the sheet-aware resolver
    resolver = _SheetAwareResolver(values, dag.defined_names)
    evaluator = Evaluator(resolver)

    # Evaluate formula nodes in topological order.
    # Error and literal nodes already seeded above.
    for nid in order:
        node = node_map.get(nid)
        if node is None:
            continue
        if node.type not in ("formula",):
            continue
        if node.expression is None:
            continue

        resolver.set_sheet(node.sheet)

        try:
            ast = parse(node.expression)
        except ParseError:
            values[nid] = ErrorValue(error="#REF!")
            continue

        result = evaluator.evaluate(ast)
        values[nid] = result

    return NodeValues(values=values)
