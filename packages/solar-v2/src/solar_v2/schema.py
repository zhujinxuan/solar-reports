"""Domain calculation schemas — how each context's items are computed.

Every context module declares `SCHEMA: DomainSchema`; items name the domain
concept, give a human-readable formula (referencing other item keys), and
list the sheet rows backing them. Node ids resolve from the dag via rows, so
coverage is mechanically checkable: every formula/error node of a sheet must
be covered by exactly one item of that sheet's schema.
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


class DomainSchema(BaseModel, frozen=True):
    """One bounded context's calculation schema."""

    key: str  # "pnl"
    sheet: str  # "损益"
    label: str  # "损益表 (PnL)"
    depends_on: tuple[str, ...]  # domain keys consumed upstream
    items: tuple[ItemSchema, ...]


def all_domains() -> tuple[DomainSchema, ...]:
    """Schemas from every context module, in pipeline order."""
    from solar_v2 import (
        balance,
        cashflow,
        cost,
        debt,
        finplan,
        invest,
        param_steps,
        pnl,
        valuation,
    )

    return (
        param_steps.SCHEMA,
        invest.SCHEMA,
        debt.SCHEMA,
        cost.SCHEMA,
        pnl.SCHEMA,
        cashflow.SCHEMA,
        finplan.SCHEMA,
        balance.SCHEMA,
        valuation.SCHEMA,
    )
