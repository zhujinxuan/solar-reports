"""Cell-layout tables — the ONLY place cell identity exists in the codebase.

Every formula/error node from dag/solar.dag.yaml is mapped here to a
"value source": which domain, which item key, which year index (for
year-series items), which scalar field, or which aggregate reduction.

Static errors (D4/E4 in 损益, row 36 in 财务计划) are documented and
emitted as error strings, not computed by the engine.
"""

from __future__ import annotations

from dataclasses import dataclass

# ── Column alphabet ────────────────────────────────────────────────────────

def _col_idx(col: str) -> int:
    """0-based index for Excel column A=0, ..., Z=25, AA=26, ..., ZZ=701."""
    result = 0
    for ch in col:
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result - 1


def _col_letter(idx: int) -> str:
    """Inverse of _col_idx: 0 -> 'A', 25 -> 'Z', 26 -> 'AA'."""
    result = ""
    n = idx + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(ord("A") + rem) + result
    return result


def _cols_between(start: str, end: str) -> tuple[str, ...]:
    """Inclusive column range, e.g. ('E','F',...,'AC')."""
    si = _col_idx(start)
    ei = _col_idx(end)
    return tuple(_col_letter(i) for i in range(si, ei + 1))


# ── Value-source descriptor ────────────────────────────────────────────────


@dataclass(frozen=True)
class CellSource:
    """Where to find the value for a single dag node.

    Exactly one of `year_idx`, `scalar_field`, `agg`, or `error` is set.
    """

    domain: str  # "pnl", "cost", etc.
    item_key: str  # "sales_revenue"
    year_idx: int | None = None  # 0-based into the domain frame
    scalar_field: str | None = None  # field on the domain scalars dataclass
    agg: str | None = None  # "sum"|"average"|"min"|"max"|"first"|"last"|"echo"
    error: str | None = None  # static error string, e.g. "#REF!"

    def __post_init__(self) -> None:
        sources = sum(
            1
            for x in (self.year_idx, self.scalar_field, self.agg, self.error)
            if x is not None
        )
        if sources != 1:
            raise ValueError(
                f"CellSource {self} must have exactly one value source "
                f"(year_idx={self.year_idx}, scalar={self.scalar_field}, "
                f"agg={self.agg}, error={self.error})"
            )


# ── Sheet-level layout ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class _SheetDef:
    """Defines the column-to-year mapping and item-key-to-row mapping for a sheet.

    `year_cols`: ordered tuple of column letters that correspond to year-index
      values (0, 1, 2, ...). A column letter NOT in year_cols or agg_cols or
      special_cols is treated as NOT covered.

    `agg_cols`: {col_letter: agg_kind}. Aggregate columns (SUM, AVERAGE, etc.).

    `special_cols`: {col_letter: year_idx}. Extra columns that map to specific
      year indices but are NOT part of the ordered year_cols. Used for
      construction-period columns (e.g. 投资计划 D/E→period 0/1).

    `rows`: (item_key, row_number, kind) for each item on this sheet.
      kind: "series" (year-axis), "scalar" (single-cell),
            "period" (construction-period series via special_cols),
            "error" (static error row).

    `static_errors`: dag node ids that are static errors, not computed.

    `row_irregularities`: {(row, col): special handling}. E.g. row 7 frozen at
      column H, row 7 at I+ all = H7 value; salvage cells at Y/AC only.
    """

    sheet: str
    domain: str
    year_cols: tuple[str, ...]
    agg_cols: dict[str, str]  # col -> agg_kind
    special_cols: dict[str, int]  # col -> year_idx (not in year_cols)
    rows: tuple[tuple[str, int, str], ...]  # (key, row, kind)
    static_errors: tuple[str, ...]  # node ids
    # Irregularities: (row, col) -> custom_agg or special mapping
    irregularities: dict[tuple[int, str], str]  # (row, col) -> agg or error
    # Frames that include a construction-year row shift every year index
    # by one; shifted sheet sections (deferred VAT etc.) shift per row.
    frame_offset: int = 0
    row_year_offset: dict[int, int] | None = None

    def resolve(self, row: int, col: str) -> CellSource:
        """Resolve a (row, col) to a CellSource."""
        # Check static errors FIRST (before item-key lookup)
        node_id = f"{self.sheet}!{col}{row}"
        if node_id in self.static_errors:
            return CellSource(
                domain=self.domain,
                item_key="(static_error)",
                error="#REF!",
            )

        # Find the item key for this row
        item_key: str | None = None
        item_kind = "series"
        for key, r, kind in self.rows:
            if r == row:
                item_key = key
                item_kind = kind
                break
        if item_key is None:
            raise KeyError(
                f"No item found for row {row} in sheet {self.sheet}"
            )

        # Check irregularities first
        irr_key = (row, col)
        if irr_key in self.irregularities:
            irr = self.irregularities[irr_key]
            if irr.startswith("error:"):
                return CellSource(
                    domain=self.domain,
                    item_key=item_key,
                    error=irr[6:],
                )
            if irr.startswith("freeze:"):
                # Frozen: use the value from freeze_source_col
                freeze_col = irr[7:]
                return self.resolve(row, freeze_col)
            if irr.startswith("scalar:"):
                # Per-cell scalar override (dual-purpose KPI rows, split IRR cells)
                return CellSource(
                    domain=self.domain,
                    item_key=irr[7:],
                    scalar_field=irr[7:],
                )
            if irr.startswith("yearidx:"):
                # Explicit frame index (shifted section tails)
                return CellSource(
                    domain=self.domain,
                    item_key=item_key,
                    year_idx=int(irr[8:]),
                )
            if irr.startswith("lastof:"):
                # Last value of a different column
                return CellSource(
                    domain=self.domain,
                    item_key=irr[7:],
                    agg="last",
                )
            if irr.startswith("sumof:"):
                # Sum of the full-frame sums of several columns (k1+k2+...)
                return CellSource(
                    domain=self.domain,
                    item_key=irr[6:],
                    agg="sumof",
                )
            if irr.startswith("neg:"):
                # Negated full-frame sum of one column
                return CellSource(
                    domain=self.domain,
                    item_key=irr[4:],
                    agg="neg",
                )
            if irr.startswith("const:"):
                # Constant value (blank aggregate cells summed as 0, etc.)
                return CellSource(
                    domain=self.domain,
                    item_key=irr[6:],
                    agg="const",
                )
            if irr.startswith("axis:"):
                # Year-axis attribute of the model (e.g. construction year)
                return CellSource(
                    domain=self.domain,
                    item_key=irr[5:],
                    agg="axis",
                )
            if irr in ("sum", "sumop", "sum20", "sumf2", "average", "min",
                       "max", "first", "last", "echo"):
                return CellSource(
                    domain=self.domain, item_key=item_key, agg=irr
                )
            # Otherwise treat as agg_kind
            return CellSource(
                domain=self.domain, item_key=item_key, agg=irr
            )

        # Scalar
        if item_kind == "scalar":
            return CellSource(
                domain=self.domain,
                item_key=item_key,
                scalar_field=item_key,
            )

        # Construction-period (special_cols)
        if col in self.special_cols:
            return CellSource(
                domain=self.domain,
                item_key=item_key,
                year_idx=self.special_cols[col],
            )

        # Aggregate column
        if col in self.agg_cols:
            return CellSource(
                domain=self.domain,
                item_key=item_key,
                agg=self.agg_cols[col],
            )

        # Year-series column
        if col in self.year_cols:
            idx = self.year_cols.index(col) + self.frame_offset
            if self.row_year_offset:
                idx += self.row_year_offset.get(row, 0)
            return CellSource(
                domain=self.domain,
                item_key=item_key,
                year_idx=idx,
            )

        raise KeyError(
            f"Column {col} not covered in sheet {self.sheet} (row {row})"
        )


# ── COLUMN DEFINITIONS ─────────────────────────────────────────────────────

# "E..AC" = 25 operating-year columns (E=0, F=1, ..., AC=24)
OP_25 = _cols_between("E", "AC")
# "G..AE" = 25 operating-year columns for 损益 (G=0, ..., AE=24)
PNL_OP_25 = _cols_between("G", "AE")
# "F..AD" = 25 columns for deferred-VAT sections
DEFERRED_25 = _cols_between("F", "AD")
# "D..AB" = 25 operating-year columns for 资产负债 (D=0, ..., AB=24)
BAL_OP_25 = _cols_between("D", "AB")
# 估值结果 income axis B..Z (25yr)
VAL_INCOME_25 = _cols_between("B", "Z")
# 估值结果 market axis B..U (20yr)
VAL_MARKET_20 = _cols_between("B", "U")
# 参数表 year cols C..AB (26 cols, C=construction, D..AB=1..25)
PARAM_26 = _cols_between("C", "AB")


# ── COMMON AGGREGATE COLUMNS ───────────────────────────────────────────────

AD_SUM = {"AD": "sum"}  # Standard AD=SUM for most sheets
AD_AVG = {"AD": "average"}  # AD=AVERAGE for ICR, DSCR
H_SUM = {"H": "sum"}  # 投资计划 H=累计
AF_AGG = {"AF": "sum"}  # 损益 AF=合计 (mostly SUM, row 16=MIN)


# ── SHEET DEFINITIONS ──────────────────────────────────────────────────────


# --- 投资计划 ---
INVEST_DEF = _SheetDef(
    sheet="投资计划",
    domain="invest",
    year_cols=(),  # No standard year axis — construction-period only
    agg_cols={"C": "sum", "H": "sum"},
    special_cols={
        "D": 0,  # 建设期1
        "E": 1,  # 建设期2
        "F": 2,  # 运营期1
        "G": 3,  # 运营期2
        "B": 0,  # Aux block B column (scalar echo)
        "I": 0,  # Row 11 I11 = ratio
        "J": 0,  # Aux block J column
    },
    rows=(
        ("static_investment_ratio", 3, "period"),
        ("equity_ratio_schedule", 4, "period"),
        ("total_investment", 5, "period"),
        ("construction_investment", 6, "period"),
        ("construction_interest", 7, "period"),
        ("working_capital", 8, "period"),
        ("dynamic_investment", 9, "period"),
        ("funding_sources", 10, "period"),
        ("equity_capital", 11, "period"),
        ("equity_for_construction", 12, "period"),
        ("equity_for_working_capital", 13, "period"),
        ("total_loan", 14, "period"),
        ("long_term_loan", 15, "period"),
        ("long_term_loan_principal", 16, "period"),
        ("long_term_loan_interest", 17, "period"),
        ("working_capital_loan", 18, "period"),
        ("short_term_loan", 19, "period"),
        ("other_funding", 20, "period"),
        # Aux block
        ("aux_total_investment", 24, "scalar"),
        ("aux_dynamic_investment", 25, "scalar"),
        ("aux_static_investment", 26, "scalar"),
        ("aux_equity", 27, "scalar"),
        ("aux_loan_balance", 28, "scalar"),
        ("annual_static_split", 29, "period"),
        ("annual_equity", 30, "period"),
        ("annual_loan", 31, "period"),
        ("annual_interest", 32, "period"),
    ),
    static_errors=(),
    irregularities={
        # G6 = 成本!D54 (not a ratio split) — handled by special mapping
        # Row 7 H7 = C32+F32+G32 (explicit sum)
        (7, "H"): "sum",
        # Short-term loan: only H19 exists
        # Row 20: G20 = G7, H20 = sum
        # Aux block given echoes and totals
        (26, "J"): "scalar:aux_construction_rate",
        (27, "J"): "scalar:aux_equity_ratio_echo",
        (29, "J"): "scalar:aux_working_capital_echo",
        (30, "J"): "scalar:aux_static_investment",
        (31, "J"): "scalar:aux_dynamic_investment",
        (32, "J"): "scalar:aux_total_investment",
        (29, "B"): "scalar:static_split_total",
        (30, "B"): "scalar:equity_split_total",
        (31, "B"): "scalar:loan_split_total",
        (32, "B"): "scalar:interest_split_total",
        (29, "C"): "const:0",
        (30, "C"): "const:0",
        (31, "C"): "const:0",
        (32, "C"): "const:0",
        (11, "I"): "scalar:equity_ratio_check",
    },
)


# --- 还贷 ---
DEBT_DEF = _SheetDef(
    sheet="还贷",
    domain="debt",
    frame_offset=1,
    year_cols=OP_25,  # E..AC
    agg_cols={
        "AD": "sum",  # Default AD
        **{"AD": "sum"},  # Most rows use SUM
    },
    special_cols={
        "D": -1,  # 建设年 (year_idx -1)
    },
    rows=(
        ("year_numbers", 4, "series"),
        ("long_term_loan_balance", 6, "series"),
        ("long_term_loan_principal_repay", 7, "series"),
        ("construction_interest", 8, "series"),
        ("annual_debt_service", 9, "series"),
        ("long_term_loan_interest_payment", 10, "series"),
        ("long_term_interest_total", 11, "series"),
        ("working_capital_balance", 13, "series"),
        ("working_capital_interest", 16, "series"),
        ("short_term_balance", 18, "series"),
        ("short_term_principal", 20, "series"),
        ("short_term_interest", 21, "series"),
        ("total_balance", 23, "series"),
        ("total_principal", 25, "series"),
        ("total_interest", 26, "series"),
        ("ebit", 27, "series"),
        ("ebit_vat", 28, "series"),
        ("icr", 29, "series"),
        ("ebitda", 30, "series"),
        ("ebitda_tax", 31, "series"),
        ("dscr", 32, "series"),
        ("pmt", 35, "scalar"),
        ("pmt_residual", 36, "series"),
    ),
    static_errors=(),
    irregularities={
        # ICR AD29 = AVERAGE(F:AC) over first 20 cols
        (29, "AD"): "average",
        # DSCR AD32 = AVERAGE(F:AC) over first 15 cols
        (32, "AD"): "average",
    },
)


# ICR/DSCR AD aggregates = windowed averages carried as debt scalars
DEBT_DEF.irregularities[(29, "AD")] = "scalar:icr_average"
DEBT_DEF.irregularities[(32, "AD")] = "scalar:dscr_average"


# --- 成本 ---
COST_DEF = _SheetDef(
    sheet="成本",
    domain="cost",
    row_year_offset={51: -1, 52: -1, 56: -1},
    year_cols=OP_25,  # E..AC for most rows
    agg_cols={},  # Per-row aggregate specs
    special_cols={
        "D": -1,  # 建设年 for top-section rows
    },
    rows=(
        ("year_labels", 4, "series"),
        ("depreciation_echo", 6, "series"),
        ("repair_cost", 7, "series"),
        ("salary_cost", 8, "series"),
        ("insurance_cost", 9, "series"),
        ("material_cost", 10, "series"),
        ("land_tax_cost", 11, "series"),
        ("land_rent_echo", 12, "series"),
        ("interest_expense", 13, "series"),
        ("long_term_loan_interest", 14, "series"),
        ("working_capital_loan_interest", 15, "series"),
        ("short_term_loan_interest", 16, "series"),
        ("surplus_interest", 17, "series"),
        ("other_cost", 18, "series"),
        ("fixed_cost_label", 19, "series"),
        ("variable_cost_label", 20, "series"),
        ("total_operating_cost", 21, "series"),
        ("operating_cost", 22, "series"),
        ("depreciation_year_labels", 26, "series"),
        ("deductible_vat", 28, "scalar"),
        ("fixed_asset_original", 29, "scalar"),
        ("depreciation", 30, "series"),
        ("fixed_asset_net_value", 31, "series"),
        ("deferred_vat_year_labels", 48, "series"),
        ("deferred_original", 50, "scalar"),
        ("deferred_vat_amortization", 51, "series"),
        ("deferred_vat_net", 52, "series"),
        ("land_rent_original", 55, "series"),
        ("land_rent_amortization", 56, "series"),
        ("land_rent_net", 57, "series"),
    ),
    static_errors=(),
    irregularities={
        # Row 4: F..AC (year 1..24 shifted right by 1)
        # Row 26: same as row 4 layout
        # Row 30-31: E..AC (25 cols, year 0..24 from E)
        # Row 48: G..AD (year 1..25 from G)
        # Row 51-52: F..AD (shifted right by 1 vs standard)
        # Row 55: E..AD (26 cols)
        # Row 56: F..AD (shifted)
        # Row 57: E..AD (26 cols)
        # AD columns: SUM for most, but not for all
        # Rows with AD=SUM: 6-16, 18, 21, 22, 30
        # Row 17 AD: sum (surplus_interest)
        # Row 19, 20 AD: label only
    },
)

# Post-process cost AD aggregates: most rows have AD=SUM over the
# 25 operating years (D cells of those rows are blank)
for _row_num in (
    6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 30, 31
):
    COST_DEF.irregularities[(_row_num, "AD")] = "sum"
COST_DEF.irregularities[(19, "AD")] = "scalar:fixed_cost_label"
COST_DEF.irregularities[(20, "AD")] = "scalar:variable_cost_label"
# Section-tail cells: AD is a year column in the shifted sections
COST_DEF.irregularities[(26, "AD")] = "const:0"  # AD26 = blank AD4
COST_DEF.irregularities[(48, "AD")] = "lastof:depreciation_year_labels"
COST_DEF.irregularities[(51, "AD")] = "yearidx:24"
COST_DEF.irregularities[(52, "AD")] = "yearidx:24"
COST_DEF.irregularities[(55, "AD")] = "scalar:land_rent_original_final"
COST_DEF.irregularities[(56, "AD")] = "scalar:land_rent_amortization_final"
COST_DEF.irregularities[(57, "AD")] = "scalar:land_rent_net_final"


# --- 损益 ---
PNL_DEF = _SheetDef(
    sheet="损益",
    domain="pnl",
    year_cols=PNL_OP_25,  # G..AE (operating years)
    agg_cols={},  # Per-row
    special_cols={
        "D": -3,  # Construction year label (#REF!)
        "E": -2,  # Construction year label 2 (#REF!)
        "F": -1,  # Partial year (pre-operating)
    },
    rows=(
        ("year_labels", 4, "series"),
        ("power_generation", 5, "series"),
        ("on_grid_price_incl_vat", 6, "series"),
        ("on_grid_price_excl_vat", 7, "series"),
        ("sales_revenue", 8, "series"),
        ("vat_surcharge_total", 9, "series"),
        ("city_maintenance_tax", 10, "series"),
        ("education_surcharge", 11, "series"),
        ("vat_refund", 12, "series"),
        ("row13_total", 13, "scalar"),  # AF13 = 0 only
        ("total_cost", 14, "series"),
        ("total_profit", 15, "series"),
        ("cum_profit", 16, "series"),
        ("tax_rate_schedule", 20, "series"),
        ("income_tax", 21, "series"),
        ("loss_compensation", 22, "series"),
        ("loss", 23, "series"),
        ("loss_carry_forward", 24, "series"),
        ("tax_echo", 25, "series"),
        ("net_profit", 26, "series"),
        ("surplus_reserve", 27, "series"),
        ("row28_total", 28, "scalar"),  # AF28 = 0 only
        ("distributable_profit", 29, "series"),
        ("dividend", 32, "series"),
        ("undistributed_profit", 33, "series"),
        ("depreciation_echo", 36, "scalar"),  # G36 single cell = cost deductible VAT
        ("output_vat", 37, "series"),
        ("vat_credit_balance", 38, "series"),
        ("vat_credit_used", 39, "series"),
        ("vat_payable", 40, "series"),
        ("surcharge_base", 41, "series"),
        ("adjusted_profit", 43, "series"),
        ("guaranteed_sales", 47, "series"),
        ("market_sales", 48, "series"),
        ("blended_price", 49, "series"),
    ),
    static_errors=("损益!D4", "损益!E4"),
    irregularities={
        # F4 = construction calendar year label
        (4, "F"): "axis:construction_year",
        # AF column aggregations
        (8, "AF"): "sum",   # sales_revenue
        (9, "AF"): "sum",   # vat_surcharge_total (AF9=SUM)
        (10, "AF"): "sum",  # city_maintenance_tax
        (11, "AF"): "sum",  # education_surcharge
        (12, "AF"): "sum",  # vat_refund
        (13, "AF"): "scalar:row13_total",  # AF13 = 0 (aggregate-only row)
        (14, "AF"): "sum",  # total_cost
        (15, "AF"): "sum",  # total_profit
        (16, "AF"): "min",  # cum_profit (AF16=MIN!)
        (21, "AF"): "sum",  # income_tax
        (26, "AF"): "sum",  # net_profit
        (27, "AF"): "sum",  # surplus_reserve
        (28, "AF"): "scalar:row28_total",  # AF28 = 0 (aggregate-only row)
        (29, "AF"): "sum",  # distributable_profit
        # On-grid price excl VAT: G7 frozen at H7 from year 3+
        (7, "I"): "freeze:H",
        (7, "J"): "freeze:H",
        (7, "K"): "freeze:H",
        (7, "L"): "freeze:H",
        (7, "M"): "freeze:H",
        (7, "N"): "freeze:H",
        (7, "O"): "freeze:H",
        (7, "P"): "freeze:H",
        (7, "Q"): "freeze:H",
        (7, "R"): "freeze:H",
        (7, "S"): "freeze:H",
        (7, "T"): "freeze:H",
        (7, "U"): "freeze:H",
        (7, "V"): "freeze:H",
        (7, "W"): "freeze:H",
        (7, "X"): "freeze:H",
        (7, "Y"): "freeze:H",
        (7, "Z"): "freeze:H",
        (7, "AA"): "freeze:H",
        (7, "AB"): "freeze:H",
        (7, "AC"): "freeze:H",
        (7, "AD"): "freeze:H",
        (7, "AE"): "freeze:H",
    },
)


# --- 现金流量 ---
CASHFLOW_DEF = _SheetDef(
    sheet="现金流量",
    domain="cashflow",
    frame_offset=1,
    year_cols=OP_25,  # E..AC
    agg_cols={},
    special_cols={
        "D": -1,  # 建设年/Year 0
    },
    rows=(
        # Project cash flow
        ("project_year_labels", 4, "series"),
        ("project_cash_inflow", 5, "series"),
        ("project_power_sales", 6, "series"),
        ("project_vat_refund", 7, "series"),
        ("project_vat_output", 8, "series"),
        ("project_salvage_recovery", 9, "series"),
        ("project_wc_recovery", 10, "series"),
        ("project_row11", 11, "series"),
        ("project_cash_outflow", 12, "series"),
        ("project_fixed_asset_invest", 13, "series"),
        ("project_working_capital", 14, "series"),
        ("project_vat_payable", 15, "series"),
        ("project_land_rent", 16, "series"),
        ("project_operating_cost", 17, "series"),
        ("project_sales_tax", 18, "series"),
        ("project_adjusted_income_tax", 19, "series"),
        ("project_ebit", 20, "series"),
        ("project_row21", 21, "series"),
        ("project_net_cf", 22, "series"),
        ("project_cum_net_cf", 23, "series"),
        ("project_payback", 24, "series"),
        ("project_pre_tax_net_cf", 25, "series"),
        ("project_cum_pre_tax_cf", 26, "series"),
        ("project_payback_pre_tax", 27, "series"),
        ("project_irr", 29, "scalar"),
        ("project_npv", 30, "scalar"),
        ("project_payback_period", 31, "scalar"),
        ("project_20yr_irr", 33, "scalar"),
        # Equity cash flow
        ("equity_year_labels", 40, "series"),
        ("equity_cash_inflow", 42, "series"),
        ("equity_power_sales", 43, "series"),
        ("equity_vat_refund", 44, "series"),
        ("equity_vat_output", 45, "series"),
        ("equity_salvage_recovery", 46, "series"),
        ("equity_wc_recovery", 47, "series"),
        ("equity_row48", 48, "series"),
        ("equity_cash_outflow", 49, "series"),
        ("equity_capital_invest", 50, "series"),
        ("equity_loan_principal_repay", 51, "series"),
        ("equity_loan_interest", 52, "series"),
        ("equity_operating_cost", 53, "series"),
        ("equity_land_rent", 54, "series"),
        ("equity_vat_payable", 55, "series"),
        ("equity_sales_tax", 56, "series"),
        ("equity_income_tax", 57, "series"),
        ("equity_long_term_rent", 58, "series"),
        ("equity_net_cf", 59, "series"),
        ("equity_cum_cf", 60, "series"),
        ("equity_irr", 61, "scalar"),
        ("equity_npv", 62, "scalar"),
        ("equity_20yr_irr", 64, "scalar"),
        ("equity_adjustment", 67, "scalar"),
        ("equity_adjusted_cf", 68, "series"),
        ("equity_adjusted_irr", 69, "scalar"),
        # Investor cash flow
        ("investor_year_labels", 83, "series"),
        ("investor_cash_inflow", 84, "series"),
        ("investor_profit_distribution", 85, "series"),
        ("investor_asset_disposal", 86, "series"),
        ("investor_salvage", 87, "series"),
        ("investor_surplus_fund", 88, "series"),
        ("investor_cash_outflow", 91, "series"),
        ("investor_construction_equity", 92, "series"),
        ("investor_own_wc", 93, "series"),
        ("investor_net_cf", 94, "series"),
        ("investor_cum_cf", 95, "series"),
        ("investor_irr", 97, "scalar"),
        ("investor_npv", 98, "scalar"),
    ),
    static_errors=(),
    irregularities={
        # AD=SUM for most year-series rows
        # Split IRR/NPV/payback cells: I = after-tax, L = pre-tax
        (29, "I"): "scalar:project_irr_after_tax",
        (29, "L"): "scalar:project_irr_pre_tax",
        (30, "I"): "scalar:project_npv_after_tax",
        (30, "L"): "scalar:project_npv_pre_tax",
        (31, "I"): "scalar:project_payback_after_tax",
        (31, "L"): "scalar:project_payback_pre_tax",
        (33, "I"): "scalar:project_20yr_irr_after_tax",
        (33, "L"): "scalar:project_20yr_irr_pre_tax",
        # AD=SUM for most rows
        # Row 57 AE = AD57+AD55+AD56 (tax + VAT + surcharge totals)
        (57, "AE"): "sumof:equity_income_tax+equity_vat_payable+equity_sales_tax",
    },
)

# Add AD=SUM for cashflow year-series rows (op-year range E..AC by default;
# rows 14/49/50/59 sum the full D..AC range, row 21 sums E..Y)
for _rn in range(4, 28):
    CASHFLOW_DEF.irregularities[(_rn, "AD")] = "sumop"
for _rn in range(40, 61):
    CASHFLOW_DEF.irregularities[(_rn, "AD")] = "sumop"
for _rn in range(83, 96):
    CASHFLOW_DEF.irregularities[(_rn, "AD")] = "sumop"
for _rn in (68, 84, 91, 94, 95):
    CASHFLOW_DEF.irregularities[(_rn, "AD")] = "sumop"
for _rn in (14, 49, 50, 59):
    CASHFLOW_DEF.irregularities[(_rn, "AD")] = "sum"
CASHFLOW_DEF.irregularities[(21, "AD")] = "sum20"


# --- 财务计划 ---
FINPLAN_DEF = _SheetDef(
    sheet="财务计划",
    domain="finplan",
    frame_offset=1,
    year_cols=OP_25,  # E..AC
    agg_cols={},
    special_cols={
        "C": -2,  # Construction year (pre-D)
        "D": -1,  # 建设年
    },
    rows=(
        ("year_labels", 4, "series"),
        ("operating_net_cf", 5, "series"),
        ("operating_inflow", 6, "series"),
        ("sales_revenue", 7, "series"),
        ("vat_refund_inflow", 8, "series"),
        ("subsidy_shortfall", 10, "series"),
        ("operating_outflow", 11, "series"),
        ("operating_cost_outflow", 12, "series"),
        ("city_tax", 13, "series"),
        ("large_rent_payment", 14, "series"),
        ("income_tax_outflow", 15, "series"),
        ("vat_payable_outflow", 16, "series"),
        ("invest_finance_net_cf", 17, "series"),
        ("invest_inflow", 18, "series"),
        ("equity_injection", 19, "series"),
        ("construction_loan", 20, "series"),
        ("wc_loan", 21, "series"),
        ("short_term_borrowing", 22, "series"),
        ("invest_outflow", 24, "series"),
        ("construction_investment_outflow", 25, "series"),
        ("working_capital_outflow", 26, "series"),
        ("lt_loan_repay", 27, "series"),
        ("short_term_repayment", 28, "series"),
        ("interest_outflow", 30, "series"),
        ("profit_distribution", 31, "series"),
        ("other_outflow", 32, "series"),
        ("net_cash_flow", 33, "series"),
        ("cumulative_surplus", 34, "series"),
        ("error_checks", 36, "series"),
        ("outflow_excl_distribution", 38, "series"),
        ("net_cf_excl_distribution", 39, "series"),
        ("distributable_profit_pool", 40, "series"),
        ("actual_distribution", 41, "series"),
        ("cumulative_surplus_check", 42, "series"),
    ),
    static_errors=(),
    irregularities={
        # AD=SUM for most year-series rows
        # Row 20: D20 only (construction loan initial)
        # Row 21: E21 only (wc loan)
        # Row 36: error checks — year cells from engine error_checks
        # (U = #DIV/0! live error), AD36 = static #REF! aggregate artifact
    },
)

# AD=SUM for finplan year-series rows: full D..AC range for most,
# F..AC (skip construction + first op year) for rows 31-34, custom
# combinations for rows 11/17/18
for _rn in (
    5, 6, 7, 8, 10, 12, 13, 14, 15, 16, 19, 22, 24, 25,
    26, 27, 28, 30, 38, 39, 40, 41, 42,
):
    FINPLAN_DEF.irregularities[(_rn, "AD")] = "sum"
for _rn in (31, 32, 33, 34):
    FINPLAN_DEF.irregularities[(_rn, "AD")] = "sumf2"
# AD11 = AD12+AD13+AD15+AD16 (operating outflow excl. land rent)
FINPLAN_DEF.irregularities[(11, "AD")] = (
    "sumof:operating_cost_outflow+city_tax+income_tax_outflow+vat_payable_outflow"
)
# AD17 = AD18 - AD24; AD18 sums blank aggregate cells = 0
FINPLAN_DEF.irregularities[(17, "AD")] = "neg:invest_outflow"
FINPLAN_DEF.irregularities[(18, "AD")] = "const:0"
# C22 = MAX(F22:AC22) — max short-term borrowing
FINPLAN_DEF.irregularities[(22, "C")] = "max"

# Row 36 error_checks: AD36 is aggregate echo (error value)
FINPLAN_DEF.irregularities[(36, "AD")] = "error:#REF!"


# --- 资产负债 ---
BALANCE_DEF = _SheetDef(
    sheet="资产负债",
    domain="balance",
    frame_offset=1,
    year_cols=BAL_OP_25,  # D..AB (25 operating years, NO AD column)
    agg_cols={},  # No AD column on balance sheet
    special_cols={
        "C": -1,  # 建设年
    },
    rows=(
        ("year_labels", 4, "series"),
        ("total_assets", 5, "series"),
        ("current_assets_total", 6, "series"),
        ("current_assets", 7, "series"),
        ("accumulated_surplus_cash", 8, "series"),
        ("accounts_receivable", 9, "series"),
        ("construction_in_progress", 10, "series"),
        ("fixed_assets_net", 11, "series"),
        ("intangible_assets_net", 12, "series"),
        ("total_liabilities_equity", 13, "series"),
        ("current_liabilities", 14, "series"),
        ("long_term_loan_balance", 15, "series"),
        ("short_term_loan_balance", 16, "series"),
        ("total_liabilities", 17, "series"),
        ("total_equity", 18, "series"),
        ("registered_capital", 19, "series"),
        ("accumulated_surplus_reserves", 20, "series"),
        ("accumulated_retained_earnings", 21, "series"),
        ("asset_liability_ratio", 23, "series"),
        ("balance_check", 25, "series"),
        ("balance_check_diff", 26, "series"),
        ("max_asset_liability_ratio", 28, "scalar"),
    ),
    static_errors=(),
    irregularities={
        # Row 10: C10 only (construction in progress)
        # Row 28: D28 only (max asset-liability ratio, scalar)
    },
)


# --- 估值结果 ---
VALUATION_DEF = _SheetDef(
    sheet="估值结果",
    domain="valuation",
    year_cols=VAL_INCOME_25,  # B..Z (25yr income axis)
    agg_cols={},
    special_cols={},
    rows=(
        ("benchmark_rate", 1, "scalar"),  # B1 only
        ("val_net_cashflow", 5, "series"),
        ("val_terminal_value", 6, "series"),
        ("val_sale_price_inc", 7, "series"),
        ("val_full_equity_price", 8, "series"),
        ("val_income_tax", 9, "series"),
        ("val_stamp_duty", 10, "series"),
        ("val_after_tax_return", 11, "series"),
        ("val_premium_rate", 12, "series"),
        ("val_capital", 14, "series"),
        ("val_undistributed_profit", 15, "series"),
        ("val_equity_plus_profit", 16, "series"),
        ("val_premium_rate2", 17, "series"),
        ("val_capex", 20, "series"),
        ("val_fcf_in", 21, "series"),
        ("val_fcf_out", 22, "series"),
        ("val_fcf_terminal", 23, "series"),
        ("val_fcf_sale_price", 24, "series"),
        ("val_owners_equity", 26, "series"),
        ("val_net_profit", 27, "series"),
        ("val_discounted_cf", 28, "series"),
    ),
    static_errors=(),
    irregularities={
        # Row 1: only B1 has a value (scalar benchmark_rate)
        # Rows 17, 20-24: 20-year axis (B..U only), not full 25
        # This is handled as: cols > U for those rows → not covered (skip)
        # Market approach uses B..U (20yr)
    },
)


# --- 指标汇总 ---
# All KPI items are scalars, located in columns D, G, H, I
KPI_DEF = _SheetDef(
    sheet="指标汇总",
    domain="valuation",  # valuation domain includes both sheets
    year_cols=(),  # No year axis
    agg_cols={},
    special_cols={
        "D": 0,   # Primary scalar column
        "G": 0,   # Secondary
        "H": 0,   # Secondary
        "I": 0,   # Secondary
    },
    rows=(
        ("kpi_capacity", 5, "scalar"),
        ("kpi_unit_investment", 6, "scalar"),
        ("kpi_equity_ratio_dynamic", 7, "scalar"),
        ("kpi_feed_in_tariff", 8, "scalar"),
        ("kpi_annual_hours_irr", 9, "scalar"),
        ("kpi_epc_unit_equity_irr", 10, "scalar"),
        ("kpi_adjusted_equity_irr", 11, "scalar"),
        ("kpi_annual_operating_cost", 12, "scalar"),
        ("kpi_operating_cost_per_kwh", 13, "scalar"),
        ("kpi_operating_cost_per_kw", 14, "scalar"),
        ("kpi_loan_years", 15, "scalar"),
        ("kpi_summary_capacity", 21, "scalar"),
        ("kpi_annual_generation_payback", 22, "scalar"),
        ("kpi_total_investment_irr", 23, "scalar"),
        ("kpi_construction_interest_npv", 24, "scalar"),
        ("kpi_working_capital", 25, "scalar"),
        ("kpi_project_irr_after_tax", 26, "scalar"),
        ("kpi_tariff_excl_vat_equity_irr", 27, "scalar"),
        ("kpi_feed_in_tariff_investor_irr", 28, "scalar"),
        ("kpi_sales_revenue_npv", 30, "scalar"),
        ("kpi_total_cost_equity_npv", 31, "scalar"),
        ("kpi_sales_tax_investor_npv", 32, "scalar"),
        ("kpi_total_profit_summary", 33, "scalar"),
        ("kpi_investment_profit_rate", 34, "scalar"),
        ("kpi_operating_cost_per_kwh_summary", 35, "scalar"),
        ("kpi_operating_cost_per_kw_summary", 36, "scalar"),
        ("kpi_full_hours_max_leverage", 38, "scalar"),
        ("kpi_unit_invest_per_kwh_max_loss", 39, "scalar"),
        ("kpi_unit_static_max_short_term", 40, "scalar"),
        ("kpi_equity_ratio_loan_years", 41, "scalar"),
        ("kpi_all_loan_years", 42, "scalar"),
        ("kpi_equity_amount_icr", 43, "scalar"),
        ("kpi_transfer_profit_dscr", 44, "scalar"),
        ("kpi_engineering_profit_roi", 45, "scalar"),
        ("kpi_total_return", 46, "scalar"),
        ("kpi_scc_repair_maintenance", 50, "scalar"),
        ("kpi_depreciation_income_tax", 51, "scalar"),
        ("kpi_scc_other_amort", 52, "scalar"),
        ("kpi_total_profit_raw", 53, "scalar"),
        ("kpi_interest_subsidy", 54, "scalar"),
        ("kpi_cash_cost", 55, "scalar"),
        ("kpi_investment_95pct", 56, "scalar"),
        ("kpi_coverage_ratio", 57, "scalar"),
        ("kpi_epc_check", 58, "scalar"),
        ("kpi_total_epc_cost", 60, "scalar"),
        ("kpi_20yr_project_irr_pre_tax", 64, "scalar"),
        ("kpi_20yr_equity_irr_after_tax", 65, "scalar"),
    ),
    static_errors=(),
    irregularities={
        # Dual-purpose KPI rows: D/G/H cells hold DIFFERENT concepts —
        # per-cell scalar overrides (values confirmed vs dag ground truth)
        (5, "H"): "scalar:kpi_annual_generation",
        (6, "D"): "scalar:kpi_unit_static_investment",
        (6, "H"): "scalar:kpi_static_investment",
        (7, "D"): "scalar:kpi_equity_ratio_pct",
        (7, "H"): "scalar:kpi_dynamic_investment",
        (9, "D"): "scalar:kpi_annual_full_hours",
        (9, "H"): "scalar:kpi_project_irr_pre_tax",
        (10, "D"): "scalar:kpi_epc_unit_cost",
        (10, "H"): "scalar:kpi_equity_irr_after_tax",
        (13, "D"): "scalar:kpi_operating_cost_per_kwh",
        (13, "H"): "scalar:kpi_max_leverage_ratio_pct",
        (14, "D"): "scalar:kpi_operating_cost_per_kw",
        (14, "H"): "scalar:kpi_max_short_term_borrowing",
        (22, "D"): "scalar:kpi_annual_generation_raw",
        (22, "H"): "scalar:kpi_project_payback_period",
        (23, "D"): "scalar:kpi_total_investment",
        (23, "H"): "scalar:kpi_project_irr_pre_tax_dup",
        (24, "D"): "scalar:kpi_construction_interest",
        (24, "H"): "scalar:kpi_project_npv_pre_tax",
        (27, "D"): "scalar:kpi_tariff_excl_vat",
        (27, "H"): "scalar:kpi_equity_irr_after_tax_dup",
        (28, "D"): "scalar:kpi_tariff_incl_vat",
        (28, "H"): "scalar:kpi_investor_irr",
        (30, "D"): "scalar:kpi_sales_revenue_total",
        (30, "H"): "scalar:kpi_project_npv_after_tax",
        (31, "D"): "scalar:kpi_total_operating_cost_total",
        (31, "H"): "scalar:kpi_equity_npv",
        (32, "D"): "scalar:kpi_vat_surcharge_total",
        (32, "H"): "scalar:kpi_investor_npv",
        (33, "D"): "scalar:kpi_total_profit_total",
        (33, "H"): "scalar:kpi_epc_unit_cost_dup",
        (34, "D"): "scalar:kpi_annual_operating_cost_dup",
        (34, "H"): "scalar:kpi_investment_profit_rate",
        (35, "D"): "scalar:kpi_operating_cost_per_kwh_dup",
        (35, "H"): "scalar:kpi_equity_net_profit_rate",
        (36, "D"): "scalar:kpi_operating_cost_per_kw_dup",
        (36, "H"): "scalar:kpi_equity_net_profit_rate_dup",
        (38, "D"): "scalar:kpi_annual_full_hours_dup",
        (38, "H"): "scalar:kpi_max_leverage_ratio_pct_dup",
        (39, "D"): "scalar:kpi_unit_invest_per_kwh",
        (39, "H"): "scalar:kpi_max_cumulative_loss",
        (40, "D"): "scalar:kpi_unit_static_investment_dup",
        (40, "H"): "scalar:kpi_max_short_term_borrowing_dup",
        (41, "D"): "scalar:kpi_equity_ratio_pct_dup",
        (41, "H"): "scalar:kpi_long_term_loan_years",
        (43, "D"): "scalar:kpi_equity_capital_total",
        (43, "H"): "scalar:kpi_icr_average",
        (44, "D"): "scalar:kpi_transfer_net_profit",
        (44, "H"): "scalar:kpi_dscr",
        (45, "D"): "scalar:kpi_engineering_profit",
        (45, "H"): "scalar:kpi_roi",
        (50, "D"): "scalar:kpi_scc_repair",
        (50, "G"): "scalar:kpi_scc_label",
        (50, "H"): "scalar:kpi_scc_amort",
        (50, "I"): "scalar:kpi_scc_unit_label",
        (51, "D"): "scalar:kpi_depreciation_total",
        (51, "H"): "scalar:kpi_income_tax_total",
        (52, "D"): "scalar:kpi_scc_amort_dup",
        (52, "H"): "scalar:kpi_scc_amort_plus_tax",
        (53, "D"): "scalar:kpi_total_profit_dup",
        (54, "D"): "scalar:kpi_interest_expense_total",
        (54, "H"): "scalar:kpi_subsidy_per_kwh",
        (55, "D"): "scalar:kpi_cash_cost_total",
        (55, "H"): "scalar:kpi_cash_cost_per_kwh",
        (56, "D"): "scalar:kpi_investment_95pct",
        (56, "H"): "scalar:kpi_coverage_numerator",
    },
)


# --- 参数表 ---
PARAMS_DEF = _SheetDef(
    sheet="参数表",
    domain="params",
    year_cols=PARAM_26,  # C..AB (C=construction, D..AB=1..25)
    agg_cols={},
    special_cols={},
    rows=(
        ("installed_capacity_mw", 2, "scalar"),
        ("load_rate", 6, "series"),
        ("annual_full_hours", 7, "scalar"),
        ("feed_in_tariff", 8, "scalar"),
        ("subsidy_arrival_rate", 12, "series"),
        ("static_investment", 15, "scalar"),
        ("other_cost", 18, "scalar"),
        ("land_use_fee", 19, "scalar"),
        ("unit_static_investment", 23, "scalar"),
        ("epc_unit_price", 24, "scalar"),
        ("deductible_vat_construction", 25, "scalar"),
        ("working_capital_total", 29, "scalar"),
        ("land_use_tax", 43, "scalar"),
        ("depreciation_rate", 47, "scalar"),
        ("first_year_om_rate", 50, "scalar"),
        ("repair_rate", 51, "series"),
        ("first_year_land_rent", 59, "scalar"),
        ("land_area", 61, "scalar"),
        ("year_labels", 66, "series"),
        ("rent_payment_period", 67, "series"),
        ("land_rent_payment", 68, "series"),
        ("land_rent_amortization", 69, "series"),
        ("epc_contract_price", 73, "scalar"),
    ),
    static_errors=(),
    irregularities={
        # Row 2: only C2 is scalar
        # Row 6: D6 only (load_rate)
        # Row 7: C7 only (annual_full_hours scalar)
        # Row 8: C8 only (feed_in_tariff)
        # Row 12: C..AB (year series, subsidy arrival rate)
        # Row 51: C..AB (repair rate series)
        # Row 66-69: C..AB (year series)
    },
)


# ── MASTER REGISTRY ────────────────────────────────────────────────────────

ALL_SHEETS: tuple[_SheetDef, ...] = (
    INVEST_DEF,
    DEBT_DEF,
    COST_DEF,
    PNL_DEF,
    CASHFLOW_DEF,
    FINPLAN_DEF,
    BALANCE_DEF,
    VALUATION_DEF,
    KPI_DEF,
    PARAMS_DEF,
)

# Lookup by sheet name
_SHEET_BY_NAME: dict[str, _SheetDef] = {s.sheet: s for s in ALL_SHEETS}


# ── Public API ──────────────────────────────────────────────────────────────


def resolve_cell(sheet: str, row: int, col: str) -> CellSource:
    """Resolve a (sheet, row, col) triple to a CellSource."""
    sd = _SHEET_BY_NAME.get(sheet)
    if sd is None:
        raise KeyError(f"Unknown sheet: {sheet}")
    return sd.resolve(row, col)


def resolve_node(node_id: str) -> CellSource:
    """Resolve a dag node id like '损益!G8' to a CellSource."""
    if "!" not in node_id:
        raise ValueError(f"Invalid node id format: {node_id}")
    sheet, rest = node_id.split("!", 1)
    # Parse column letters and row number
    col = ""
    row_str = ""
    for ch in rest:
        if ch.isalpha():
            col += ch
        else:
            row_str += ch
    if not col or not row_str:
        raise ValueError(f"Cannot parse node id: {node_id}")
    return resolve_cell(sheet, int(row_str), col)


def check_layout(dag_yaml_path: str = "dag/solar.dag.yaml") -> list[str]:
    """Validate layout coverage against the dag node set.

    Returns list of issues (empty list = clean).
    """

    import yaml

    issues: list[str] = []

    with open(dag_yaml_path, encoding="utf-8") as f:
        dag = yaml.safe_load(f)

    fe_nodes: set[str] = set()
    fe_nodes_by_sheet: dict[str, set[str]] = {}
    for n in dag["nodes"]:
        if n.get("type") in ("formula", "error"):
            nid = n["id"]
            fe_nodes.add(nid)
            fe_nodes_by_sheet.setdefault(n["sheet"], set()).add(nid)

    # Track which dag nodes we can resolve
    resolved: set[str] = set()
    unresolvable: list[str] = []

    for nid in sorted(fe_nodes):
        try:
            resolve_node(nid)
            resolved.add(nid)
        except (KeyError, ValueError) as e:
            unresolvable.append(f"{nid}: {e}")

    # Check coverage: every dag formula/error node must be resolved
    missing = fe_nodes - resolved
    for nid in sorted(missing):
        issues.append(f"MISSING coverage for dag node: {nid}")

    # Check: every layout row references a real dag node
    # Build set of (sheet, row) from dag
    dag_rows: dict[str, set[int]] = {}
    for n in dag["nodes"]:
        if n.get("type") in ("formula", "error"):
            dag_rows.setdefault(n["sheet"], set()).add(n["row"])

    for sd in ALL_SHEETS:
        for _key, row, _kind in sd.rows:
            if row not in dag_rows.get(sd.sheet, set()):
                issues.append(
                    f"Layout row {sd.sheet}!{row} has no matching "
                    f"dag formula/error node (item={_key})"
                )

    # Per-sheet coverage counts
    for sheet_name in sorted(fe_nodes_by_sheet):
        sheet_fe = fe_nodes_by_sheet[sheet_name]
        sheet_resolved = {n for n in sheet_fe if n in resolved}
        if sheet_fe != sheet_resolved:
            issues.append(
                f"{sheet_name}: {len(sheet_resolved)}/{len(sheet_fe)} "
                f"formula/error nodes covered"
            )

    if not issues:
        # All good: report counts
        for sheet_name in sorted(fe_nodes_by_sheet):
            sheet_fe = fe_nodes_by_sheet[sheet_name]
            sheet_resolved = {n for n in sheet_fe if n in resolved}
            issues.append(
                f"{sheet_name}: {len(sheet_resolved)}/{len(sheet_fe)} "
                f"formula/error nodes covered (OK)"
            )

    return issues
