"""Settings for xlsx-core — pydantic-settings, env/CLI overridable."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """xlsx-core settings. All fields env-overridable with XLSX_ prefix."""

    model_config = SettingsConfigDict(env_prefix="XLSX_")

    workbook_path: Path = Path(
        "data/附件4：平价上网光伏发电项目经济评价模型（第7.1版）.xlsx"
    )
    dag_path: Path = Path("dag/solar.dag.yaml")
    dag_v2_path: Path = Path("dag/solar.v2.annotated.yaml")
    rel_tol: float = 1e-6
    abs_tol: float = 1e-9
    # Empirical winner of dag/recalc_benchmark.json (2026-07-25): excel-com
    # (0/5059 mismatches, 9.6s) over libreoffice (2/5059, 77s) and
    # formulas-pkg (cannot evaluate this workbook). Env XLSX_RECALC_ENGINE overrides.
    recalc_engine: str = "excel-com"
    libreoffice_path: Path = Path("C:/Program Files/LibreOffice/program/soffice.exe")
    inputs_toml: str | None = None
