"""ModelResults — the engine's typed output contract.

One field per bounded context (its domain result dataclass) plus headline
scalars exposed as read-only properties. Zero I/O, zero cell identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
    from solar_v2.inputs import ModelInputs


@dataclass(frozen=True)
class ModelResults:
    """Per-domain results of one model evaluation."""

    inputs: ModelInputs
    params: params.ParamsCore
    invest: invest.InvestResult
    debt: debt.DebtResult
    cost: cost.CostResult
    pnl: pnl.PnLResult
    cashflow: cashflow.CashFlowResult
    finplan: finplan.FinPlanResult
    balance: balance.BalanceResult
    valuation: valuation.ValuationResult

    @property
    def project_irr_after_tax(self) -> float:
        """项目投资内部收益率(税后), percent (6.13 = 6.13%)."""
        return self.cashflow.scalars.project_irr_after_tax

    @property
    def equity_irr(self) -> float:
        """资本金内部收益率, fraction (0.0956 = 9.56%)."""
        return self.cashflow.scalars.equity_irr

    @property
    def project_npv_after_tax(self) -> float:
        """项目投资净现值(税后), 万元."""
        return self.cashflow.scalars.project_npv_after_tax

    @property
    def equity_npv(self) -> float:
        """资本金净现值, 万元."""
        return self.cashflow.scalars.equity_npv

    @property
    def equity_sale_price(self) -> float:
        """股权估值(收益法卖出价格), 万元 — first operating year (收益法头条)."""
        frame = self.valuation.income
        return float(frame["val_sale_price_inc"][0])
