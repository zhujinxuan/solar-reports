"""Coverage + validation tests for DomainSchema declarations."""

from __future__ import annotations

import os
from collections import defaultdict
from typing import get_type_hints

import yaml
from solar_v2.params import Params
from solar_v2.schema import all_domains

# ── helpers ──────────────────────────────────────────────────────────────────


def _dag_formula_rows(dag_path: str) -> dict[str, set[int]]:
    """Return {sheet: set(row)} for formula/error nodes."""
    with open(dag_path) as f:
        dag = yaml.safe_load(f)
    out: dict[str, set[int]] = defaultdict(set)
    for node in dag["nodes"]:
        if node["type"] in ("formula", "error"):
            out[node["sheet"]].add(node["row"])
    return dict(out)


def _schema_rows() -> dict[str, set[int]]:
    """Return {sheet: set(row)} from schema items.

    No duplicate rows within a single physical sheet, except valuation
    which spans TWO sheets (估值结果 + 指标汇总).
    """
    out: dict[str, set[int]] = defaultdict(set)
    for dom in all_domains():
        if dom.key == "valuation":
            # Valuation items span two sheets — track under both keys
            # for coverage comparison. Duplicates ARE allowed here
            # because row 5 appears in both 估值结果 and 指标汇总.
            continue
        acc: set[int] = set()
        for item in dom.items:
            for r in item.rows:
                if r in acc:
                    raise AssertionError(
                        f"Duplicate row {r} in sheet '{dom.sheet}' "
                        f"(domain: {dom.key})"
                    )
                acc.add(r)
        out[dom.sheet] = acc
    # Add valuation rows manually (no duplicate check between sheets)
    for dom in all_domains():
        if dom.key == "valuation":
            for item in dom.items:
                for r in item.rows:
                    out[dom.sheet].add(r)
    return dict(out)


# ── test: count and order ────────────────────────────────────────────────────


def test_all_domains_count():
    """all_domains() returns exactly 9 schemas in pipeline order."""
    schemas = all_domains()
    assert len(schemas) == 9
    order = tuple(s.key for s in schemas)
    assert order == (
        "params",
        "invest",
        "debt",
        "cost",
        "pnl",
        "cashflow",
        "finplan",
        "balance",
        "valuation",
    )


# ── test: coverage ───────────────────────────────────────────────────────────


def test_coverage():
    """Every formula/error row appears in exactly one item's rows per sheet.

    valuation is special: it covers BOTH 估值结果 and 指标汇总.
    """
    dag_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "dag", "solar.dag.yaml"
    )
    dag_rows = _dag_formula_rows(dag_path)
    schema_rows = _schema_rows()

    for dom in all_domains():
        sheet = dom.sheet
        dag_set = dag_rows.get(sheet, set())

        # Special: valuation covers both 估值结果 and 指标汇总
        if dom.key == "valuation":
            dag_set = dag_rows.get("估值结果", set()) | dag_rows.get(
                "指标汇总", set()
            )

        schema_set = schema_rows.get(sheet, set())

        missing = dag_set - schema_set
        extra = schema_set - dag_set

        assert not missing, (
            f"Sheet '{sheet}' ({dom.key}): "
            f"DAG formula rows not covered by schema: {sorted(missing)}"
        )
        assert not extra, (
            f"Sheet '{sheet}' ({dom.key}): "
            f"Schema rows not in DAG: {sorted(extra)}"
        )


# ── test: input resolution ───────────────────────────────────────────────────


def test_inputs_resolve():
    """Every item's inputs resolve to a known item key or a Params field.

    For 'params:X' refs: X must be either a Params dataclass field name
    or a param_steps schema item key (both share the 'params' domain key).
    """
    params_fields = set(get_type_hints(Params))

    # Build registry of all known items: "domain:item_key"
    known_items: dict[str, set[str]] = {}
    for dom in all_domains():
        known_items[dom.key] = {item.key for item in dom.items}

    for dom in all_domains():
        own_items = known_items[dom.key]
        for item in dom.items:
            for inp in item.inputs:
                if ":" in inp:
                    domain, ref = inp.split(":", 1)
                    if domain == "params":
                        # params:X can be a Params field OR a params schema item
                        params_items = known_items.get("params", set())
                        ok_field = ref in params_fields
                        ok_item = ref in params_items
                        assert ok_field or ok_item, (
                            f"{dom.key}:{item.key} → params:{ref}: "
                            f"not a Params field and not a params domain item"
                        )
                    else:
                        assert domain in known_items, (
                            f"{dom.key}:{item.key} → {inp}: "
                            f"unknown domain '{domain}'"
                        )
                        assert ref in known_items[domain], (
                            f"{dom.key}:{item.key} → {inp}: "
                            f"unknown item '{ref}' in domain '{domain}'"
                        )
                else:
                    # Unqualified — must be own domain
                    assert inp in own_items, (
                        f"{dom.key}:{item.key} → {inp}: "
                        f"unknown item in own domain"
                    )


# ── test: formula strings ────────────────────────────────────────────────────


def test_formulas_non_empty():
    """Every item has a non-empty formula string."""
    for dom in all_domains():
        for item in dom.items:
            assert item.formula.strip(), (
                f"{dom.key}:{item.key} has empty formula"
            )


# ── test: valuation covers both sheets ───────────────────────────────────────


def test_valuation_coverage():
    """Valuation schema covers rows from BOTH 估值结果 and 指标汇总."""
    dag_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "..", "dag", "solar.dag.yaml"
    )
    dag_rows = _dag_formula_rows(dag_path)
    val_rows = dag_rows.get("估值结果", set())
    kpi_rows = dag_rows.get("指标汇总", set())

    schema_set = _schema_rows().get("估值结果", set())
    both_dag = val_rows | kpi_rows

    assert val_rows, "Expected formula rows in 估值结果"
    assert kpi_rows, "Expected formula rows in 指标汇总"

    missing = both_dag - schema_set
    assert not missing, (
        f"Valuation schema missing rows: 估值结果={sorted(val_rows - schema_set)}, "
        f"指标汇总={sorted(kpi_rows - schema_set)}"
    )

    # Verify all valuation rows are from known sheets
    val_dom = next(d for d in all_domains() if d.key == "valuation")
    schema_rows_list = {r for item in val_dom.items for r in item.rows}
    assert schema_rows_list == both_dag, (
        f"Valuation schema rows ({sorted(schema_rows_list)}) != "
        f"DAG rows ({sorted(both_dag)})"
    )
