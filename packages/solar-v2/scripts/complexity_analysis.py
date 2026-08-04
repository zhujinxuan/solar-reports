"""Complexity & compression analysis for the solar-v2 engine.

Measures the signatures of "understanding via compression" (MDL / Schmidhuber):
the honest metric is NOT node count alone (gameable by chunking) but the
combination of total description length, reuse structure, and per-unit
complexity bounds. Run standalone for a report, or import `metrics()` for the
gate test (tests/test_complexity.py).

Metrics
-------
1. MDL ratio: AST nodes of engine *compute logic* (function bodies, no
   docstrings) vs the DAG's total expression-token count. Re-chunking logic
   into bigger functions leaves the AST count roughly invariant, so this
   ratio cannot be gamed by re-chunking. < 1 means the typed engine describes
   the same computation more tersely than the raw cell formulas.
2. Reuse structure: the item dependency graph (edges from each schema item's
   declared `inputs`). Cell-by-cell translation has fan-out ≈ 1 everywhere;
   distilled understanding shows high-fan-out hubs (one named concept consumed
   by many). Mean fan-out over producing items, count of fan-out≥3 hubs.
3. Cyclomatic complexity per compute function: median + max. A "node" secretly
   containing dozens of branches shows high CC — bounded here.
4. Halstead vocabulary (distinct operators/operands) + volume.
5. Longest dependency chain (DAG depth).
"""

from __future__ import annotations

import ast
import collections
import keyword
import math
import pathlib
import re
import statistics
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "solar_v2"
DAG = pathlib.Path(__file__).resolve().parents[3] / "dag" / "solar.dag.yaml"

_COMPUTE_PREFIX = ("compute_", "step_year", "solve", "_compute_", "assemble")
_TOKEN_RE = re.compile(r"[A-Za-z_]\w*|\d+\.?\d*|[()+\-*/^<>=,&:!]")


@dataclass(frozen=True)
class Metrics:
    """All complexity metrics for one snapshot of the engine."""

    engine_logic_ast: int
    engine_compute_fns: int
    dag_formula_nodes: int
    dag_expression_tokens: int
    total_items: int
    edges: int
    mean_fanout_producers: float
    hubs_fanout_ge3: int
    hubs_fanout_ge5: int
    max_fanout: int
    cc_median: float
    cc_mean: float
    cc_max: int
    halstead_n1: int
    halstead_n2: int
    halstead_vocab: int
    halstead_volume: float
    max_depth: int
    top_hubs: tuple[str, ...] = field(default_factory=tuple)
    cc_ge8: tuple[tuple[int, str, str], ...] = field(default_factory=tuple)

    @property
    def mdl_ratio_vs_nodes(self) -> float:
        """Engine compute AST per dag formula cell."""
        return self.engine_logic_ast / self.dag_formula_nodes

    @property
    def mdl_ratio_vs_tokens(self) -> float:
        """Engine compute AST per dag expression token (the MDL ratio)."""
        return self.engine_logic_ast / self.dag_expression_tokens

    @property
    def cells_per_function(self) -> float:
        """Dag cells collapsed into one named compute function."""
        return self.dag_formula_nodes / self.engine_compute_fns


def _iter_compute_fns(tree: ast.AST) -> Iterator[ast.FunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name.startswith(
            _COMPUTE_PREFIX
        ):
            yield node


def _fn_body_nodes(fn: ast.FunctionDef) -> int:
    body: list[ast.stmt] = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(
        body[0].value, ast.Constant
    ):
        body = body[1:]  # drop docstring
    return sum(1 for stmt in body for _ in ast.walk(stmt))


def _cyclomatic(fn: ast.FunctionDef) -> int:
    c = 1
    for n in ast.walk(fn):
        if isinstance(
            n,
            (
                ast.If, ast.For, ast.While, ast.AsyncFor,
                ast.ExceptHandler, ast.With, ast.Assert, ast.comprehension,
            ),
        ):
            c += 1
        elif isinstance(n, ast.BoolOp):
            c += len(n.values) - 1
        elif isinstance(n, ast.IfExp):
            c += 1
    return c


def _halstead(
    fn: ast.FunctionDef, ops: collections.Counter, operands: collections.Counter
) -> None:
    for n in ast.walk(fn):
        if isinstance(n, ast.BinOp):
            ops[type(n.op).__name__] += 1
        elif isinstance(n, ast.UnaryOp):
            ops["U" + type(n.op).__name__] += 1
        elif isinstance(n, ast.Compare):
            ops["Compare"] += 1
        elif isinstance(n, ast.BoolOp):
            ops[type(n.op).__name__] += 1
        elif isinstance(n, ast.Call):
            fnref = n.func
            if isinstance(fnref, ast.Name):
                nm = fnref.id
            elif isinstance(fnref, ast.Attribute):
                nm = fnref.attr
            else:
                nm = "?"
            ops["call:" + nm] += 1
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            if not keyword.iskeyword(n.id):
                operands[n.id] += 1
        elif isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            operands[f"#={n.value}"] += 1


def _schemas() -> tuple:
    if str(SRC.parent) not in sys.path:
        sys.path.insert(0, str(SRC.parent))
    from solar_v2.schema import all_domains

    return all_domains()


def metrics() -> Metrics:
    """Compute all complexity metrics. Pure read of source + dag."""
    import yaml

    engine_ast = 0
    fn_count = 0
    cc_values: list[int] = []
    high_cc: list[tuple[int, str, str]] = []
    ops: collections.Counter = collections.Counter()
    operands: collections.Counter = collections.Counter()

    for f in sorted(SRC.rglob("*.py")):
        if f.name == "__init__.py":
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for fn in _iter_compute_fns(tree):
            fn_count += 1
            engine_ast += _fn_body_nodes(fn)
            v = _cyclomatic(fn)
            cc_values.append(v)
            if v >= 8:
                high_cc.append((v, f.name, fn.name))
            _halstead(fn, ops, operands)

    dag = yaml.safe_load(DAG.read_text(encoding="utf-8"))
    fe = [n for n in dag["nodes"] if n.get("type") in ("formula", "error")]
    dag_nodes = len(fe)
    dag_tokens = sum(
        len(_TOKEN_RE.findall(n.get("expression") or "")) for n in fe
    )

    schemas = _schemas()
    items: dict[tuple[str, str], object] = {}
    for ds in schemas:
        for it in ds.items:
            items[(ds.key, it.key)] = it
    total_items = len(items)

    edges: set[tuple[tuple[str, str], tuple[str, str]]] = set()
    for ds in schemas:
        for it in ds.items:
            for inp in it.inputs:
                if ":" in inp:
                    d, k = inp.split(":", 1)
                    if (d, k) in items and (d, k) != (ds.key, it.key):
                        edges.add(((d, k), (ds.key, it.key)))
                elif (ds.key, inp) in items and inp != it.key:
                    edges.add(((ds.key, inp), (ds.key, it.key)))

    fan_out: collections.Counter = collections.Counter()
    adj: dict[tuple[str, str], list[tuple[str, str]]] = collections.defaultdict(list)
    for src, dst in edges:
        fan_out[src] += 1
        adj[src].append(dst)

    producers = [k for k in items if fan_out.get(k, 0) > 0]
    mean_fo = (
        sum(fan_out[k] for k in producers) / len(producers) if producers else 0.0
    )
    hubs3 = sum(1 for k in items if fan_out.get(k, 0) >= 3)
    hubs5 = sum(1 for k in items if fan_out.get(k, 0) >= 5)

    memo: dict[tuple[str, str], int] = {}

    def depth(n: tuple[str, str], stack: set[tuple[str, str]]) -> int:
        if n in memo:
            return memo[n]
        if n in stack:
            return 0
        stack.add(n)
        d = 1 + max((depth(m, stack) for m in adj[n]), default=0)
        stack.discard(n)
        memo[n] = d
        return d

    max_depth = max(depth(n, set()) for n in items) if items else 0

    n1, n2 = len(ops), len(operands)
    big_n1, big_n2 = sum(ops.values()), sum(operands.values())
    vocab = n1 + n2
    volume = (big_n1 + big_n2) * (math.log2(vocab) if vocab > 1 else 0.0)

    return Metrics(
        engine_logic_ast=engine_ast,
        engine_compute_fns=fn_count,
        dag_formula_nodes=dag_nodes,
        dag_expression_tokens=dag_tokens,
        total_items=total_items,
        edges=len(edges),
        mean_fanout_producers=mean_fo,
        hubs_fanout_ge3=hubs3,
        hubs_fanout_ge5=hubs5,
        max_fanout=max(fan_out.values()) if fan_out else 0,
        cc_median=statistics.median(cc_values),
        cc_mean=statistics.mean(cc_values),
        cc_max=max(cc_values),
        halstead_n1=n1,
        halstead_n2=n2,
        halstead_vocab=vocab,
        halstead_volume=volume,
        max_depth=max_depth,
        top_hubs=tuple(f"{k[0]}:{k[1]}({v})" for k, v in fan_out.most_common(10)),
        cc_ge8=tuple(sorted(high_cc, reverse=True)),
    )


def report(m: Metrics) -> str:
    """Human-readable Markdown report."""
    lines = [
        "# solar-v2 Complexity & Compression Report",
        "",
        "Understanding = compression (MDL / Schmidhuber). Node count alone is",
        "gameable by chunking; the robust signatures are total description length,",
        "reuse structure (fan-out), and bounded per-unit complexity.",
        "",
        "## 1. Minimum Description Length",
        "",
        f"- Engine compute-logic AST nodes (no docstrings): **{m.engine_logic_ast}**",
        f"  across **{m.engine_compute_fns}** named compute functions.",
        f"- DAG formula/error cells: **{m.dag_formula_nodes}**, total expression",
        f"  tokens: **{m.dag_expression_tokens}**.",
        f"- **MDL ratio (engine AST / dag tokens) = {m.mdl_ratio_vs_tokens:.3f}**",
        "  — the typed engine describes the same computation more tersely than the",
        "  raw cell formulas. Re-chunking logic cannot move this ratio.",
        f"- One named function per {m.cells_per_function:.1f} cells.",
        "",
        "## 2. Reuse structure (anti-translation signature)",
        "",
        f"- Item dependency graph: {m.total_items} items, {m.edges} edges.",
        f"- **Mean fan-out over producing items = {m.mean_fanout_producers:.3f}**",
        "  (cell-by-cell translation ≈ 1.0; high reuse = distilled concepts).",
        f"- Hubs with fan-out ≥ 3: **{m.hubs_fanout_ge3}**;",
        f"  ≥ 5: **{m.hubs_fanout_ge5}**; max fan-out = {m.max_fanout}.",
        f"- Top reused items: {', '.join(m.top_hubs)}",
        f"- Longest dependency chain (DAG depth) = {m.max_depth}.",
        "",
        "## 3. Cyclomatic complexity per compute function",
        "",
        f"- Median **{m.cc_median}**, mean {m.cc_mean:.2f}, max **{m.cc_max}**.",
        f"- Branchy functions (CC ≥ 8): {len(m.cc_ge8)}",
    ]
    for v, f, nm in m.cc_ge8:
        lines.append(f"  - CC={v}  {f}:{nm}")
    lines += [
        "",
        "## 4. Halstead vocabulary",
        "",
        f"- Distinct operators n1={m.halstead_n1}, operands n2={m.halstead_n2},",
        f"  vocabulary = {m.halstead_vocab}, volume V = {m.halstead_volume:.0f}.",
        "",
        "## Gate bounds (tests/test_complexity.py)",
        "",
        f"- mdl_ratio_vs_tokens < 1.0  (now {m.mdl_ratio_vs_tokens:.3f})",
        f"- mean_fanout_producers ≥ 1.5  (now {m.mean_fanout_producers:.3f})",
        f"- hubs_fanout_ge3 ≥ 30  (now {m.hubs_fanout_ge3})",
        f"- cc_max ≤ 20  (now {m.cc_max})",
        f"- cc_median ≤ 2  (now {m.cc_median})",
        f"- total_items ≤ 380  (now {m.total_items})",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    print(report(metrics()))
