"""Regenerate solar_v2/schedule.py from dag/solar.dag.yaml.

Unit = (sheet, row) over formula/error cells. Edges = cross-sheet and local
refs, with RANGES EXPANDED to every row/cell in the rectangle (SUM(T14:T17)
depends on rows 15/16 too, not just the endpoints).

Year-shifted mutual rows (cell-acyclic but row-cyclic, e.g. 损益 tax block ↔
财务计划 ↔ 还贷 ↔ 成本) form cross-sheet SCCs at row granularity. Their member
rows are split into PER-COLUMN units — cell-level topo is acyclic by
construction (workbook iterate=None) — and scheduled as fine steps
(sheet, row, col). Coarse steps stay (sheet, row); residual intra-sheet SCCs
merge to (sheet, (row, ...)).
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
DAG = REPO / "dag" / "solar.dag.yaml"
OUT = REPO / "packages" / "solar-v2" / "src" / "solar_v2" / "schedule.py"

SHEET_ORDER = [
    "参数表",
    "投资计划",
    "还贷",
    "成本",
    "损益",
    "现金流量",
    "财务计划",
    "资产负债",
    "估值结果",
    "指标汇总",
]

XREF = re.compile(
    r"(?:'([^']+)'|([\u4e00-\u9fffA-Za-z_][\w\u4e00-\u9fff]*))!"
    r"(\$?)([A-Z]{1,3})(\$?)(\d+)(?::(\$?)([A-Z]{1,3})(\$?)(\d+))?"
)
LREF = re.compile(
    r"(?<![\w!])\$?([A-Z]{1,3})\$?(\d+)(?::\$?([A-Z]{1,3})\$?(\d+))?(?![\d(])"
)


def _col_idx(letters: str) -> int:
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _col_name(idx: int) -> str:
    out = ""
    idx += 1
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def _cells(
    sheet: str, c1: str, r1: int, c2: str | None, r2: int | None
) -> Iterator[tuple[str, str, int]]:
    """Every (sheet, col, row) cell touched by a ref or rectangular range."""
    if c2 is None or r2 is None:
        yield sheet, c1, r1
        return
    lo_c, hi_c = sorted((_col_idx(c1), _col_idx(c2)))
    for ci in range(lo_c, hi_c + 1):
        for r in range(min(r1, r2), max(r1, r2) + 1):
            yield sheet, _col_name(ci), r


def _cell_refs(expr: str, home: str, sheets: set[str]) -> set[tuple[str, str, int]]:
    out: set[tuple[str, str, int]] = set()
    for m in XREF.finditer(expr):
        s = m.group(1) or m.group(2)
        if s in sheets:
            c2, r2 = (m.group(8), int(m.group(10))) if m.group(10) else (None, None)
            out |= set(_cells(s, m.group(4), int(m.group(6)), c2, r2))
    for m in LREF.finditer(XREF.sub(" ", expr)):
        c2, r2 = (m.group(3), int(m.group(4))) if m.group(4) else (None, None)
        out |= set(_cells(home, m.group(1), int(m.group(2)), c2, r2))
    return out


def _tarjan(
    units: set, edges: dict,  # type: ignore[type-arg]
) -> list[list]:  # type: ignore[type-arg]
    index: dict = {}
    low: dict = {}
    onst: dict = defaultdict(bool)
    stack: list = []
    counter = [0]
    sccs: list[list] = []

    def strongconnect(v: object) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        onst[v] = True
        for w in edges.get(v, ()):
            if w not in index:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif onst[w]:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            scc: list = []
            while True:
                w = stack.pop()
                onst[w] = False
                scc.append(w)
                if w == v:
                    break
            sccs.append(scc)

    for v in units:
        if v not in index:
            strongconnect(v)
    return sccs


def main() -> None:
    sys.setrecursionlimit(100000)
    with open(DAG, encoding="utf-8") as f:
        dag = yaml.safe_load(f)
    nodes = dag["nodes"]
    sheets = {n["sheet"] for n in nodes}
    calc = [n for n in nodes if n["type"] in ("formula", "error")]

    units = {(n["sheet"], n["row"]) for n in calc}
    row_edges: dict[tuple[str, int], set[tuple[str, int]]] = defaultdict(set)
    for n in calc:
        u = (n["sheet"], n["row"])
        for s, _c, r in _cell_refs(n.get("expression") or "", n["sheet"], sheets):
            if (s, r) in units and (s, r) != u:
                row_edges[u].add((s, r))

    sccs = _tarjan(units, row_edges)
    cross = [s for s in sccs if len({u[0] for u in s}) > 1]
    split_rows = {u for s in cross for u in s}
    if split_rows:
        print(f"cross-sheet SCC: {len(split_rows)} rows split to per-column steps")

    # Mixed graph: fine (sheet,row,col) for split rows, coarse (sheet,row,None)
    cell_owner = {
        (n["sheet"], f"{n['col']}{n['row']}"): (n["sheet"], n["row"]) for n in calc
    }
    fine_units: set[tuple[str, int, str | None]] = set()
    for n in calc:
        u = (n["sheet"], n["row"])
        col: str | None = n["col"] if u in split_rows else None
        fine_units.add((u[0], u[1], col))

    def finify(owner: tuple[str, int], col: str) -> tuple[str, int, str | None]:
        return (
            (owner[0], owner[1], col)
            if owner in split_rows
            else (owner[0], owner[1], None)
        )

    fedges: dict[tuple[str, int, str | None], set[tuple[str, int, str | None]]]
    fedges = defaultdict(set)
    for n in calc:
        u = (n["sheet"], n["row"])
        src = finify(u, n["col"])
        for s, c, r in _cell_refs(n.get("expression") or "", n["sheet"], sheets):
            owner = cell_owner.get((s, f"{c}{r}"))
            if owner is None:
                continue
            tgt = finify(owner, c)
            if tgt != src:
                fedges[src].add(tgt)

    fsccs = _tarjan(fine_units, fedges)
    bad = [
        s
        for s in fsccs
        if len(s) > 1
        and (any(u[2] is not None for u in s) or len({u[0] for u in s}) > 1)
    ]
    if bad:
        raise SystemExit(f"unexpected fine-grained cycle: {bad[:5]}")
    # intra-sheet coarse SCCs are expected; keep them for coalescing below

    # Condense: each fscc (singleton fine units, or intra-sheet coarse groups)
    # is one schedulable node.
    node_of = {u: i for i, s in enumerate(fsccs) for u in s}
    cedges: dict[int, set[int]] = defaultdict(set)
    for src, tgts in fedges.items():
        for t in tgts:
            if node_of[src] != node_of[t]:
                cedges[node_of[src]].add(node_of[t])
    indeg = dict.fromkeys(range(len(fsccs)), 0)
    for src, tgts in cedges.items():
        indeg[src] += len(tgts)
    rank = {s: i for i, s in enumerate(SHEET_ORDER)}

    def key(i: int) -> tuple[int, int, int]:
        return (
            min(rank[u[0]] for u in fsccs[i]),
            min(u[1] for u in fsccs[i]),
            min(_col_idx(u[2]) if u[2] else -1 for u in fsccs[i]),
        )

    ready = sorted((i for i, d in indeg.items() if d == 0), key=key)
    order: list[int] = []
    remaining = {i: set(t) for i, t in cedges.items()}
    while ready:
        i = ready.pop(0)
        order.append(i)
        for src in list(remaining):
            if i in remaining[src]:
                remaining[src].remove(i)
                indeg[src] -= 1
                if indeg[src] == 0:
                    ready.append(src)
        ready.sort(key=key)
    if len(order) != len(fsccs):
        raise SystemExit(f"cycle: {len(order)} of {len(fsccs)} scheduled")

    lines: list[str] = []
    for i in order:
        s = fsccs[i]
        first = s[0]
        if first[2] is not None:
            assert len(s) == 1
            lines.append(f'    ("{first[0]}", {first[1]}, "{first[2]}"),')
        elif len(s) > 1:
            group = sorted(s)
            rows = tuple(u[1] for u in group)
            lines.append(f'    ("{first[0]}", {rows!r}),')
        else:
            lines.append(f'    ("{first[0]}", {first[1]}),')
    n_steps = len(lines)
    header = (
        '"""Static unit schedule — generated from dag/solar.dag.yaml.\n\n'
        "Step shapes: (sheet, row) | (sheet, (row, ...)) intra-sheet groups |\n"
        "(sheet, row, col) fine per-cell steps for year-shifted mutual rows.\n"
        "DO NOT EDIT BY HAND — regenerate via "
        "packages/solar-v2/scripts/gen_schedule.py.\n"
        '"""\n\nfrom __future__ import annotations\n\n'
        "Step = tuple[str, int | tuple[int, ...]] | tuple[str, int, str]\n\n"
        "STEPS: tuple[Step, ...] = (\n"
    )
    OUT.write_text(header + "\n".join(lines) + "\n)\n", encoding="utf-8")
    n_fine = sum(1 for i in order if fsccs[i][0][2] is not None)
    print(f"steps: {n_steps} ({n_fine} fine)")


if __name__ == "__main__":
    main()
