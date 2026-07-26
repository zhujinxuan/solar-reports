"""ProjectParameters — typed domain inputs distilled from 参数表.

Literals are read from the extracted dag (type=literal nodes only — these are
the workbook's GIVENS). Formula cells of 参数表 are re-implemented as named
domain computations (constant folding). Deferred back-edge cells (C7 ← 损益,
C50 ← 成本) are NOT here; they are schedule steps in pipeline pass 2.
"""

from __future__ import annotations

from dataclasses import dataclass

from xlsx_core.yamlutil import load_dag_doc

from solar_v2.cols import col_letters


@dataclass(frozen=True)
class Params:
    """All 参数表 scalar inputs + year-axis definition. All values derived in
    code from literal givens; no formula-cell cached values are read."""

    # capacity & generation
    installed_capacity_mw: float  # C2 (=15)
    first_year_full_hours: float  # C3 首年无衰减利用小时数
    years: tuple[int, ...]  # row 4, 2020..2045
    degradation_factor: tuple[float, ...]  # row 5 衰减后功率比例
    load_rate: tuple[float, ...]  # row 6 负荷率 (0 in construction, 0.95 after)
    guaranteed_hours: float  # C14 标杆保障利用小时数
    # tariffs
    base_tariff: float  # C9 无补贴上网电价
    market_tariff: float  # C10 市场化交易电价
    subsidy_per_kwh: float  # C11 度电补贴强度
    feed_in_tariff: float  # C8 = C9 + C11
    # investment (万元)
    construction_cost: float  # C16 建安工程费
    equipment_cost: float  # C17 设备购置费
    farmland_occupation_tax: float  # C20 耕地占用税
    survey_design_fee: float  # C21 勘察设计费
    contingency: float  # C22 基本预备费
    other_cost: float  # C18 = 2281.33 + C20
    land_use_fee: float  # C19 (=180)
    unit_static_investment: float  # C23 = (C16+C17+C18+C22)/C2
    epc_unit_price: float  # C24 = (C16+C17+C21)/C2
    deductible_vat_construction: float  # C25
    vat_rate_construction: float  # C26
    vat_rate_equipment: float  # C27
    vat_rate_survey: float  # C28
    working_capital_total: float  # C29 = C2*30
    # financing
    equity_ratio: float  # C30
    loan_rate_long: float  # C31 长期借款利率
    loan_years: int  # C32 长期借款年限
    working_capital_loan_rate: float  # C33
    short_term_loan_rate: float  # C34 短期贷款利息(利率)
    construction_months: float  # C35 建设周期
    # taxes
    vat_rate: float  # C36 增值税率
    vat_exempt_year: int  # C37 增值税优惠享受年限
    city_maintenance_tax_rate: float  # C38
    education_surcharge_rate: float  # C39
    income_tax_rate: float  # C40 所得税税率
    western_dev_preferential: bool  # C41 是否享受西部大开发
    western_dev_tax_rate: float  # C42
    land_use_tax: float  # C43 = C44*C45/10000
    land_use_tax_rate: float  # C44
    land_taxed_area: float  # C45 征收面积
    surplus_reserve_ratio: float  # C46 法定盈余公积金比率
    # depreciation
    depreciation_years: float  # C48 折旧年限
    salvage_rate: float  # C49 残值率
    depreciation_rate: float  # C47 = (1-C49)/C48
    # operating cost inputs
    repair_rate: float  # D52 年修理费率 (rate row under the year-copy row 51)
    staff_count: float  # C53
    avg_salary: float  # C54 年均工资
    welfare_rate: float  # C55 福利费率
    other_cost_rate: float  # C56 年其他费用费率
    material_cost_rate: float  # C57 年材料费费率
    insurance_rate: float  # C58 年保险费费率
    # land rent
    first_year_land_rent: float  # C59 = C61*C62/10000
    land_per_mw: float  # C60 单位占地面积
    land_area: float  # C61 = C2*C60*10000/(1000*2/3)
    land_rent_per_mu: float  # C62 首年每亩土地租金
    rent_escalation_freq: float  # C63 土地租金上浮频率
    rent_escalation_rate: float  # C64 土地租金上浮率
    rent_payment_freq: float  # C65 土地租金支付频率
    # equity sale / misc
    dividend_ratio: float  # C70 分红比例
    buyer_benchmark_rate: float  # C71 购买方基准收益率
    equity_sale_tax_rate: float  # C72 股权出售所得税税率
    epc_contract_price: float  # C73 = C24
    epc_cost_price: float  # C74 EPC成本价
    mgmt_allocation_ratio: float  # C75 管理费分摊比率
    operating_years: int  # C76 运营年限
    project_income: float  # C77 工程收益
    provisional_sum: float  # C78 暂列金


def _literals(dag_path: str) -> dict[str, object]:
    """Load ONLY literal-node values from the extracted dag (the givens)."""
    dag = load_dag_doc(dag_path)
    out: dict[str, object] = {}
    for n in dag["nodes"]:
        if n["type"] == "literal":
            out[n["id"]] = n["value"]
    return out


def load_params(dag_path: str) -> Params:
    """Build Params from dag literals + domain computations (constant folding)."""
    lit = _literals(dag_path)

    def num(node_id: str) -> float:
        v = lit[node_id]
        if not isinstance(v, (int, float)):
            raise TypeError(f"{node_id} is not numeric: {v!r}")
        return float(v)

    def series_nums(sheet: str, row: int, cols: list[str]) -> tuple[float, ...]:
        return tuple(num(f"{sheet}!{c}{row}") for c in cols)

    op_cols = col_letters("C", 26)  # C..AB (26 year columns)
    years = tuple(int(v) for v in series_nums("参数表", 4, op_cols))
    degradation = series_nums("参数表", 5, op_cols)
    # 负荷率: C6 literal 0, D6 = 100%*0.95, E6:AB6 literals 1
    load = tuple([0.0, 1.0 * 0.95] + [1.0] * 24)
    capacity = 15.0  # C2: formula '=15' — a constant by construction
    farmland_tax = num("参数表!C20")
    other_cost = 2281.33 + farmland_tax
    construction = num("参数表!C16")
    equipment = num("参数表!C17")
    survey = num("参数表!C21")
    contingency = num("参数表!C22")
    land_use_fee = 180.0  # C19: formula '=180'
    land_area = capacity * num("参数表!C60") * 10000 / (1000 * 2 / 3)
    first_year_land_rent = land_area * num("参数表!C62") / 10000
    vat_c, vat_e, vat_s = (
        num("参数表!C26"),
        num("参数表!C27"),
        num("参数表!C28"),
    )
    deductible_vat = (
        construction / (1 + vat_c) * vat_c
        + equipment / (1 + vat_e) * vat_e
        + survey / (1 + vat_s) * vat_s
    )
    dep_years = num("参数表!C48")
    salvage = num("参数表!C49")
    epc_unit = (construction + equipment + survey) / capacity

    return Params(
        installed_capacity_mw=capacity,
        first_year_full_hours=num("参数表!C3"),
        years=years,
        degradation_factor=degradation,
        load_rate=load,
        guaranteed_hours=num("参数表!C14"),
        base_tariff=num("参数表!C9"),
        market_tariff=num("参数表!C10"),
        subsidy_per_kwh=num("参数表!C11"),
        feed_in_tariff=num("参数表!C9") + num("参数表!C11"),
        construction_cost=construction,
        equipment_cost=equipment,
        farmland_occupation_tax=farmland_tax,
        survey_design_fee=survey,
        contingency=contingency,
        other_cost=other_cost,
        land_use_fee=land_use_fee,
        unit_static_investment=(construction + equipment + other_cost + contingency)
        / capacity,
        epc_unit_price=epc_unit,
        deductible_vat_construction=deductible_vat,
        vat_rate_construction=vat_c,
        vat_rate_equipment=vat_e,
        vat_rate_survey=vat_s,
        working_capital_total=capacity * 30,
        equity_ratio=num("参数表!C30"),
        loan_rate_long=num("参数表!C31"),
        loan_years=int(num("参数表!C32")),
        working_capital_loan_rate=num("参数表!C33"),
        short_term_loan_rate=num("参数表!C34"),
        construction_months=num("参数表!C35"),
        vat_rate=num("参数表!C36"),
        vat_exempt_year=int(num("参数表!C37")),
        city_maintenance_tax_rate=num("参数表!C38"),
        education_surcharge_rate=num("参数表!C39"),
        income_tax_rate=num("参数表!C40"),
        western_dev_preferential=str(lit["参数表!C41"]) == "是",
        western_dev_tax_rate=num("参数表!C42"),
        land_use_tax=num("参数表!C44") * num("参数表!C45") / 10000,
        land_use_tax_rate=num("参数表!C44"),
        land_taxed_area=num("参数表!C45"),
        surplus_reserve_ratio=num("参数表!C46"),
        depreciation_years=dep_years,
        salvage_rate=salvage,
        depreciation_rate=(1 - salvage) / dep_years,
        repair_rate=num("参数表!D52"),
        staff_count=num("参数表!C53"),
        avg_salary=num("参数表!C54"),
        welfare_rate=num("参数表!C55"),
        other_cost_rate=num("参数表!C56"),
        material_cost_rate=num("参数表!C57"),
        insurance_rate=num("参数表!C58"),
        first_year_land_rent=first_year_land_rent,
        land_per_mw=num("参数表!C60"),
        land_area=land_area,
        land_rent_per_mu=num("参数表!C62"),
        rent_escalation_freq=num("参数表!C63"),
        rent_escalation_rate=num("参数表!C64"),
        rent_payment_freq=num("参数表!C65"),
        dividend_ratio=num("参数表!C70"),
        buyer_benchmark_rate=num("参数表!C71"),
        equity_sale_tax_rate=num("参数表!C72"),
        epc_contract_price=epc_unit,
        epc_cost_price=num("参数表!C74"),
        mgmt_allocation_ratio=num("参数表!C75"),
        operating_years=int(num("参数表!C76")),
        project_income=num("参数表!C77"),
        provisional_sum=num("参数表!C78"),
    )
