"""ModelInputs — frozen pydantic model for all 参数表 givens.

Every field is a domain-constant given with a workbook literal default.
Derived scalars (unit_static_investment, deductible_vat, …) live in
domains/params.py:DerivedParams, NOT here.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field

_DEGRADATION_DEFAULT: tuple[float, ...] = (
    0.0, 0.975, 0.97, 0.965, 0.96, 0.955, 0.95,
    0.945, 0.94, 0.935, 0.93, 0.925, 0.92, 0.915,
    0.91, 0.905, 0.9, 0.895, 0.89, 0.885, 0.88,
    0.875, 0.87, 0.865, 0.86, 0.855,
)

_LOAD_RATE_DEFAULT: tuple[float, ...] = (0.0, 0.95, *(1.0 for _ in range(24)))

_REPAIR_RATE_DEFAULT: tuple[float, ...] = (
    0.002, 0.002, 0.002,
    0.004, 0.004, 0.004, 0.004, 0.004,
    0.006, 0.006, 0.006, 0.006, 0.006, 0.006,
    0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01,
)


class ModelInputs(BaseModel, frozen=True):
    """All 参数表 givens with workbook literal defaults.

    Derived scalars (feed_in_tariff, unit_static_investment, …) are NOT here;
    they are computed in domains.params.DerivedParams.
    """

    # --- capacity & generation ---
    installed_capacity_mw: float = Field(
        default=15.0, description="装机容量（直流侧），万kW"
    )
    construction_year: int = Field(
        default=2020, description="建设起始年份"
    )
    operating_years: int = Field(
        default=25, description="运营年限"
    )
    construction_months: int = Field(
        default=6, description="建设周期，月"
    )
    first_year_full_hours: float = Field(
        default=1145.0, description="首年无衰减利用小时数"
    )
    guaranteed_hours: float = Field(
        default=1100.0, description="标杆上网电价-保障利用小时数"
    )

    # --- tariffs ---
    base_tariff: float = Field(
        default=0.401, description="无补贴上网电价，元/kW·h"
    )
    market_tariff: float = Field(
        default=0.39, description="市场化交易电价，元/kW·h"
    )
    subsidy_per_kwh: float = Field(
        default=0.0, description="度电补贴强度，元/kW·h"
    )

    # --- investment (万元) ---
    construction_cost: float = Field(
        default=10046.37, description="建安工程费，万元"
    )
    equipment_cost: float = Field(
        default=40042.42, description="设备购置费，万元"
    )
    survey_design_fee: float = Field(
        default=600.0, description="勘察设计费，万元"
    )
    contingency: float = Field(
        default=631.8, description="基本预备费，万元"
    )
    other_cost_base: float = Field(
        default=2281.33, description="其他费用基数，万元"
    )
    farmland_occupation_tax: float = Field(
        default=3000.0, description="耕地占用税，万元"
    )
    land_use_fee: float = Field(
        default=180.0, description="建设用地费，万元"
    )

    # --- VAT rates ---
    vat_rate_construction: float = Field(
        default=0.09, description="建安工程费增值税税率"
    )
    vat_rate_equipment: float = Field(
        default=0.13, description="设备购置费增值税税率"
    )
    vat_rate_survey: float = Field(
        default=0.06, description="勘察设计费增值税税率"
    )

    # --- financing ---
    equity_ratio: float = Field(
        default=0.2, description="资本金比例"
    )
    loan_rate_long: float = Field(
        default=0.0465, description="长期借款利率"
    )
    loan_years: int = Field(
        default=15, description="长期借款年限（不含建设期）"
    )
    working_capital_loan_rate: float = Field(
        default=0.0435, description="流动资金贷款利率"
    )
    short_term_loan_rate: float = Field(
        default=0.0435, description="短期贷款利息（利率）"
    )
    working_capital_per_kw: float = Field(
        default=30.0,
        description="铺底流动资金标准，元/kW（流动资金总额 = 装机容量 × 标准）",
    )

    # --- taxes ---
    vat_rate: float = Field(
        default=0.13, description="增值税率"
    )
    vat_exempt_year: int = Field(
        default=2020, description="增值税优惠享受年限"
    )
    city_maintenance_tax_rate: float = Field(
        default=0.05, description="城市建设维护税率"
    )
    education_surcharge_rate: float = Field(
        default=0.05, description="教育费附加费率"
    )
    income_tax_rate: float = Field(
        default=0.25, description="所得税税率"
    )
    western_dev_preferential: bool = Field(
        default=False, description="是否享受西部大开发优惠税率"
    )
    western_dev_tax_rate: float = Field(
        default=0.15, description="西部大开发优惠所得税税率"
    )
    land_use_tax_rate: float = Field(
        default=0.0, description="城镇土地使用税税率，元/亩"
    )
    land_taxed_area: float = Field(
        default=0.0, description="征收面积，亩"
    )
    surplus_reserve_ratio: float = Field(
        default=0.1, description="法定盈余公积金比率"
    )

    # --- depreciation ---
    depreciation_years: int = Field(
        default=20, description="折旧年限"
    )
    salvage_rate: float = Field(
        default=0.05, description="残值率"
    )

    # --- operating cost inputs ---
    staff_count: int = Field(
        default=8, description="员工人数"
    )
    avg_salary: float = Field(
        default=9.0, description="年均工资，万元"
    )
    welfare_rate: float = Field(
        default=0.5, description="福利费率"
    )
    other_cost_rate: float = Field(
        default=25.0, description="年其他费用费率，元/kW"
    )
    material_cost_rate: float = Field(
        default=10.0, description="年材料费费率，元/kW"
    )
    insurance_rate: float = Field(
        default=0.0005, description="年保险费费率"
    )

    # --- land rent ---
    land_per_mw: float = Field(
        default=11.623, description="单位占地面积，hm²/10MW"
    )
    land_rent_per_mu: float = Field(
        default=600.0, description="首年每亩土地租金，元/亩"
    )
    rent_escalation_freq: int = Field(
        default=3, description="土地租金上浮频率，年/次"
    )
    rent_escalation_rate: float = Field(
        default=0.05, description="土地租金上浮率"
    )
    rent_payment_freq: int = Field(
        default=2, description="土地租金支付频率，年/次"
    )

    # --- equity sale / misc ---
    dividend_ratio: float = Field(
        default=0.8, description="分红比例"
    )
    buyer_benchmark_rate: float = Field(
        default=0.085, description="购买方基准收益率（资本金）"
    )
    equity_sale_tax_rate: float = Field(
        default=0.15, description="股权出售所得税税率"
    )
    epc_cost_price: float = Field(
        default=3200.0, description="EPC成本价，元/kW"
    )
    mgmt_allocation_ratio: float = Field(
        default=0.0, description="管理费分摊比率"
    )
    project_income: float = Field(
        default=300.0, description="工程收益"
    )
    provisional_sum: float = Field(
        default=3000.0, description="暂列金"
    )
    # --- year-series givens ---
    degradation_factor: tuple[float, ...] = Field(
        default=_DEGRADATION_DEFAULT,
        description="衰减后功率比例，26个值（建设年+25运营年）",
    )
    load_rate: tuple[float, ...] = Field(
        default=_LOAD_RATE_DEFAULT,
        description="负荷率，26个值（建设年=0，首年=0.95，其余=1.0）",
    )
    repair_rate_series: tuple[float, ...] = Field(
        default=_REPAIR_RATE_DEFAULT,
        description="年修理费率，25个值（运营年D52..AB52）",
    )

    # --- aux investment ratios (投资计划 辅助测算表) ---
    aux_static_ratio_build1: float = Field(
        default=0.0, description="静态投资建设期1完成比例（aa/J28）"
    )
    aux_static_ratio_build2: float = Field(
        default=0.0, description="静态投资建设期2完成比例（ab/K28）"
    )
    aux_static_ratio_operate: float = Field(
        default=1.0, description="静态投资运营期完成比例（ac/L28）"
    )
    initial_cum_profit: float = Field(
        default=-0.001,
        description="期初累计利润（运营前年度损益累计利润插值, 损益表手工填列值）",
    )

    _FLOAT_FIELDS: ClassVar[frozenset[str]] = frozenset({
        "installed_capacity_mw", "first_year_full_hours", "guaranteed_hours",
        "base_tariff", "market_tariff", "subsidy_per_kwh",
        "construction_cost", "equipment_cost", "survey_design_fee",
        "contingency", "other_cost_base", "farmland_occupation_tax",
        "land_use_fee", "vat_rate_construction", "vat_rate_equipment",
        "vat_rate_survey", "equity_ratio", "loan_rate_long",
        "working_capital_loan_rate", "short_term_loan_rate",
        "working_capital_per_kw",
        "vat_rate", "city_maintenance_tax_rate", "education_surcharge_rate",
        "income_tax_rate", "western_dev_tax_rate", "land_use_tax_rate",
        "land_taxed_area", "surplus_reserve_ratio", "salvage_rate",
        "avg_salary", "welfare_rate", "other_cost_rate", "material_cost_rate",
        "insurance_rate", "land_per_mw", "land_rent_per_mu",
        "rent_escalation_rate", "dividend_ratio", "buyer_benchmark_rate",
        "equity_sale_tax_rate", "epc_cost_price", "mgmt_allocation_ratio",
        "project_income", "provisional_sum", "aux_static_ratio_build1",
        "aux_static_ratio_build2", "aux_static_ratio_operate",
    })

    @classmethod
    def from_toml(cls, path: str | Path) -> ModelInputs:
        """Load ModelInputs from a TOML file.

        Supports both flat keys at top level and a ``[inputs]`` nested table.
        Unknown keys are rejected with a listing of valid keys.  Numeric types
        (int→float for float fields, ``"是"/"否"`` → bool) are coerced.
        """
        import tomllib

        path = Path(path)
        raw = tomllib.loads(path.read_text(encoding="utf-8"))

        # Support [inputs] nesting
        if "inputs" in raw:
            if len(raw) > 1:
                others = sorted(k for k in raw if k != "inputs")
                raise ValueError(
                    f"TOML file contains both [inputs] and other top-level "
                    f"keys {others} — ambiguous"
                )
            raw = raw["inputs"]

        valid_keys = set(cls.model_fields.keys())
        unknown = sorted(set(raw.keys()) - valid_keys)
        if unknown:
            raise ValueError(
                f"Unknown keys: {unknown}. "
                f"Valid keys: {sorted(valid_keys)}"
            )

        # Coerce types
        coerced: dict[str, float | int | bool | tuple[float, ...] | str] = {}
        for key, val in raw.items():
            if key == "western_dev_preferential" and isinstance(val, str):
                coerced[key] = _parse_western_dev(val)
            elif key in cls._FLOAT_FIELDS and isinstance(val, int):
                coerced[key] = float(val)
            elif key in ("degradation_factor", "load_rate",
                         "repair_rate_series") and isinstance(val, list):
                coerced[key] = tuple(float(v) for v in val)
            else:
                coerced[key] = val

        return cls.model_validate(coerced)


def _parse_western_dev(raw: str) -> bool:
    """Parse 西部大开发 string literal to bool."""
    s = raw.strip()
    if s == "是":
        return True
    if s == "否":
        return False
    raise ValueError(
        f"western_dev_preferential must be '是' or '否', got {raw!r}"
    )
