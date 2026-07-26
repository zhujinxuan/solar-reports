"""Thin stable facade for apps — compute and verify against the workbook DAG."""

from __future__ import annotations

from xlsx_core.model import NodeValues
from xlsx_core.settings import Settings

from solar_v1.dag_loader import load_dag
from solar_v1.golden import GoldenReport, golden_check
from solar_v1.interpreter import interpret


def compute(settings: Settings | None = None) -> NodeValues:
    """Load the DAG and evaluate every node.

    Args:
        settings: xlsx-core Settings (paths, tolerances). Uses defaults if None.

    Returns:
        Frozen NodeValues with computed scalars for every node id.
    """
    if settings is None:
        settings = Settings()
    dag = load_dag(settings.dag_path, settings.workbook_path)
    return interpret(dag, settings)


def verify(settings: Settings | None = None) -> GoldenReport:
    """Load the DAG, evaluate, and golden-check against cached values.

    Args:
        settings: xlsx-core Settings (paths, tolerances). Uses defaults if None.

    Returns:
        GoldenReport with mismatch count and details.
    """
    if settings is None:
        settings = Settings()
    dag = load_dag(settings.dag_path, settings.workbook_path)
    values = interpret(dag, settings)
    return golden_check(values, dag, settings)
