"""G7 structural convention tests — item computers, type dependencies, coverage.
These tests verify the mechanical contracts declared in DOMAIN.md.
"""

from __future__ import annotations

import inspect
import typing
from collections import defaultdict
from pathlib import Path

import pytest
import yaml
from solar_v2.domains import (
    balance,
    cashflow,
    cost,
    debt,
    finplan,
    invest,
    params,
    pnl,
    valuation,
)
from solar_v2.schema import all_domains

# ── Domain module registry ─────────────────────────────────────────────

_DOMAIN_MODULES: dict[str, object] = {
    "params": params,
    "invest": invest,
    "debt": debt,
    "cost": cost,
    "pnl": pnl,
    "cashflow": cashflow,
    "finplan": finplan,
    "balance": balance,
    "valuation": valuation,
}

# Orchestrator function names that are NOT item computers
_ORCHESTRATORS = frozenset({
    "compute_core",
    "compute_backedges",
    "compute_base",
    "compute_invest_plan",
    "compute_statics",
    "compute_finplan",
    "compute_balance",
    "compute_valuation",
    "compute_cashflow",
    "compute_valuation_aux",
})


def _public_functions(module) -> list[tuple[str, object]]:
    """All public compute_*/assemble functions defined in a module."""
    funcs = []
    for name in dir(module):
        if name.startswith("_"):
            continue
        obj = getattr(module, name)
        if not callable(obj):
            continue
        if not inspect.isfunction(obj):
            continue
        if obj.__module__ != module.__name__:
            continue
        funcs.append((name, obj))
    return funcs


# ── (a) Item computer coverage ─────────────────────────────────────────


def test_computer_coverage():
    """Every SCHEMA item has exactly one computer: compute_<key> or YearSlice field."""
    from solar_v2.mutual import YearSlice

    year_slice_fields = set(YearSlice.__dataclass_fields__.keys())
    errors = []

    for ds in all_domains():
        mod = _DOMAIN_MODULES[ds.key]
        mod_func_names = {
            n for n, _ in _public_functions(mod)
            if n not in _ORCHESTRATORS
        }

        for item in ds.items:
            if item.coupled:
                if item.key not in year_slice_fields:
                    errors.append(
                        f"{ds.key}.{item.key}: coupled but not in YearSlice"
                    )
                if f"compute_{item.key}" in mod_func_names:
                    errors.append(
                        f"{ds.key}.{item.key}: coupled but has compute_ function"
                    )
            else:
                expected = f"compute_{item.key}"
                if item.key in year_slice_fields:
                    errors.append(
                        f"{ds.key}.{item.key}: non-coupled but in YearSlice"
                    )
                if expected not in mod_func_names:
                    errors.append(
                        f"{ds.key}.{item.key}: missing {expected} function"
                    )

    # Extra compute_ functions not in SCHEMA (excluding orchestrators)
    for ds in all_domains():
        mod = _DOMAIN_MODULES[ds.key]
        schema_keys = {item.key for item in ds.items}
        for name, _func in _public_functions(mod):
            if name in _ORCHESTRATORS:
                continue
            if name.startswith("compute_") and len(name) > len("compute_"):
                key = name[len("compute_"):]
                if key not in schema_keys:
                    errors.append(
                        f"{ds.key}: compute_{key} has no matching schema item"
                    )

    assert errors == [], "\n".join(errors)


# ── (b) Cross-domain type dependencies ─────────────────────────────────



# Type name → domain key registry (result dataclasses + engine-level types)
_TYPE_TO_DOMAIN: dict[str, str] = {
    # params domain
    "ParamsCore": "params",
    "ModelInputs": "params",
    "DerivedParams": "params",
    "YearAxis": "params",
    "ParamsScalars": "params",
    # invest
    "InvestResult": "invest",
    # debt
    "DebtBase": "debt",
    "DebtResult": "debt",
    # cost
    "CostStatics": "cost",
    "CostCore": "cost",
    "CostResult": "cost",
    # pnl
    "PnLCore": "pnl",
    "PnLResult": "pnl",
    # cashflow
    "CashFlowResult": "cashflow",
    # finplan
    "FinPlanResult": "finplan",
    # balance
    "BalanceResult": "balance",
    # valuation
    "ValuationResult": "valuation",
    # mutual
    "MutualSolution": "mutual",
    "YearSlice": "mutual",
}


def _extract_type_names(annotation_str: str) -> set[str]:
    """Extract CamelCase identifiers from a stringified type annotation.

    With ``from __future__ import annotations``, annotations are stored as
    strings — even TYPE_CHECKING-only names survive.  We parse the string
    with ``ast`` to find ``Name`` and ``Constant`` (quoted) nodes.
    """
    import ast as _ast

    names: set[str] = set()
    try:
        tree = _ast.parse(annotation_str, mode="eval")
    except SyntaxError:
        return names

    for node in _ast.walk(tree):
        if isinstance(node, _ast.Name):
            names.add(node.id)
        elif isinstance(node, _ast.Constant) and isinstance(node.value, str):
            # "QuotedString" forward refs
            name = node.value.strip()
            # Might be a dotted name like "solar_v2.domains.cost.CostResult"
            # — take only the final component.
            names.add(name.rsplit(".", 1)[-1])

    return names


def _annotation_domains(func) -> set[str]:
    """Extract foreign domain keys from a function's parameter annotations."""
    domains: set[str] = set()
    annotations = getattr(func, "__annotations__", {})
    for param_name, ann_str in annotations.items():
        if param_name == "return":
            continue
        if not isinstance(ann_str, str):
            continue
        for name in _extract_type_names(ann_str):
            if name in _TYPE_TO_DOMAIN:
                domains.add(_TYPE_TO_DOMAIN[name])
    return domains


def _schema_input_domains(ds) -> set[str]:
    """Extract foreign domain keys from SCHEMA item `inputs` tuples."""
    domains: set[str] = set()
    for item in ds.items:
        for inp in item.inputs:
            if ":" in inp:
                dom = inp.split(":", 1)[0]
                domains.add(dom)
    return domains


def test_cross_domain_types():
    """Cross-domain dependencies extracted from code = SCHEMA.depends_on.

    For each domain the union of:
      (i)  domains referenced by TYPE ANNOTATIONS on public functions
           (compute_*/assemble) — extracted from the stringified annotations
           so TYPE_CHECKING imports don't block resolution;
      (ii) domains referenced in SCHEMA item ``inputs`` as ``"domain:key"``
    must equal the domain's SCHEMA.depends_on (self-references filtered out).
    """
    gaps: list[str] = []

    for ds in all_domains():
        mod = _DOMAIN_MODULES[ds.key]
        module_key = ds.key

        # (i) Annotation domains
        annotation_doms: set[str] = set()
        for _name, func in _public_functions(mod):
            annotation_doms |= _annotation_domains(func)

        # (ii) Schema-input domains
        input_doms: set[str] = _schema_input_domains(ds)

        # Union, remove self
        code_union = (annotation_doms | input_doms) - {module_key}
        expected = set(ds.depends_on)

        if code_union != expected:
            gaps.append(
                f"{module_key}: code-union {sorted(code_union)} "
                f"!= SCHEMA.depends_on {sorted(expected)} "
                f"(annotations={sorted(annotation_doms)}, "
                f"inputs={sorted(input_doms)})"
            )

    assert gaps == [], "\n".join(gaps)



# ── (c) No series compute returns float ────────────────────────────────


def test_no_series_returns_float():
    """No compute_<key> for a series-kind item returns a bare float/int."""
    errors = []

    for ds in all_domains():
        mod = _DOMAIN_MODULES[ds.key]
        series_keys = {item.key for item in ds.items if item.kind == "series"}

        for name, func in _public_functions(mod):
            if name in _ORCHESTRATORS:
                continue
            if not name.startswith("compute_"):
                continue
            key = name[len("compute_"):]
            if key not in series_keys:
                continue

            try:
                hints = typing.get_type_hints(func)
            except Exception:
                continue
            ret = hints.get("return")
            if ret is None:
                continue
            if ret is float:
                errors.append(
                    f"{ds.key}.{key} (series): compute returns float"
                )
            if ret is int:
                errors.append(
                    f"{ds.key}.{key} (series): compute returns int"
                )

    assert errors == [], "\n".join(errors)


# ── (d) Item count and dag row coverage ────────────────────────────────


def test_item_count():
    """Total items across all domains <= 370 (advisory cap)."""
    total = sum(len(ds.items) for ds in all_domains())
    assert total <= 370, f"Total items {total} exceeds 370 cap"


def test_dag_row_coverage():
    """Every dag formula/error node row is covered by at least one SCHEMA item.

    Known gaps (G7Fixer expected to resolve):
    - 指标汇总 rows: KPI scalars share rows with 估值结果 sheet items
      (two DAG sheets mapped to one valuation SCHEMA).
    - 成本 rows 19/20: AD-column-only scalar items.

    This is an advisory test; the layout check (test_golden_benchmark)
    provides the authoritative coverage validation.
    """
    dag_path = Path("dag/solar.dag.yaml")
    if not dag_path.exists():
        pytest.skip("dag/solar.dag.yaml not found")

    dag = yaml.safe_load(dag_path.read_text(encoding="utf-8"))

    dag_rows: dict[str, set[int]] = defaultdict(set)
    for node in dag["nodes"]:
        if node.get("type") in ("formula", "error"):
            dag_rows[node["sheet"]].add(node["row"])

    schema_coverage: dict[str, dict[int, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for ds in all_domains():
        sheet = ds.sheet
        for item in ds.items:
            for row in item.rows:
                schema_coverage[sheet][row].append(item.key)

    uncovered = 0
    multi = 0

    for sheet, rows in dag_rows.items():
        sheet_cov = schema_coverage.get(sheet, {})
        for row in sorted(rows):
            covered_by = sheet_cov.get(row, [])
            if len(covered_by) == 0:
                uncovered += 1
            elif len(covered_by) > 1:
                multi += 1

    total_fe_rows = sum(len(v) for v in dag_rows.values())
    print(f"\nDAG formula/error rows: {total_fe_rows}")
    print(f"  Uncovered: {uncovered} (G7Fixer expected to resolve)")
    print(f"  Multi-covered: {multi} (KPI/valuation row sharing)")
