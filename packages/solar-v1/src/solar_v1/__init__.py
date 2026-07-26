"""solar-v1 — dag.yaml interpreter: the permanent executable specification."""

from solar_v1.api import compute, verify
from solar_v1.dag_loader import load_dag
from solar_v1.golden import GoldenReport, Mismatch, golden_check
from solar_v1.interpreter import interpret

__all__ = [
    "GoldenReport",
    "Mismatch",
    "compute",
    "golden_check",
    "interpret",
    "load_dag",
    "verify",
]
