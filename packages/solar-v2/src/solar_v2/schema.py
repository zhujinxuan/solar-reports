"""Domain calculation schemas — how each context's items are computed.

Every domain module under `solar_v2.domains` declares `SCHEMA: DomainSchema`.
Items name the domain concept, give a human-readable formula (referencing other
item keys), and list the sheet rows backing them. `kind` distinguishes
year-series items (frame columns) from scalar items (result dataclass fields);
`coupled` marks items computed by `solar_v2.mutual.step_year`.

Structural contract (checked by tests/test_structure.py):
- every item key maps to exactly ONE computer: `compute_<key>` in the domain
  module (non-coupled) or a `YearSlice` field (coupled);
- a module's cross-domain type references equal its SCHEMA `depends_on`.
"""

from __future__ import annotations

from pydantic import BaseModel


class ItemSchema(BaseModel, frozen=True):
    """One computed domain item (a year-series or scalar concept)."""

    key: str  # "sales_revenue"
    label: str  # "销售收入"
    unit: str  # "万元" | "MWh" | "%" | "-"
    formula: str  # "power_generation × on_grid_price_excl_vat"
    inputs: tuple[str, ...]  # item keys this derives from ("cost:total_cost" ok)
    rows: tuple[int, ...]  # sheet rows backing this item
    kind: str = "series"  # "series" (year-keyed frame column) | "scalar"
    coupled: bool = False  # computed by solar_v2.mutual.step_year


class DomainSchema(BaseModel, frozen=True):
    """One bounded context's calculation schema."""

    key: str  # "pnl"
    sheet: str  # "损益"
    label: str  # "损益表 (PnL)"
    depends_on: tuple[str, ...]  # domain keys consumed upstream
    items: tuple[ItemSchema, ...]


def all_domains() -> tuple[DomainSchema, ...]:
    """Schemas from every domain module, in engine dataflow order."""
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

    return (
        params.SCHEMA,
        invest.SCHEMA,
        debt.SCHEMA,
        cost.SCHEMA,
        pnl.SCHEMA,
        cashflow.SCHEMA,
        finplan.SCHEMA,
        balance.SCHEMA,
        valuation.SCHEMA,
    )
