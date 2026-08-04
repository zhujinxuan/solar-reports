"""v2_benchmark — cell-identity and benchmarking layer.

This is the ONLY package that references cell addresses (e.g. `损益!G8`).
The engine NEVER imports this package.
"""

from v2_benchmark.compare import CellDiff, diff, format_report
from v2_benchmark.layout import (
    CellSource,
    check_layout,
    resolve_cell,
    resolve_node,
)
from v2_benchmark.projection import project

__all__ = [
    "CellDiff",
    "CellSource",
    "check_layout",
    "diff",
    "format_report",
    "project",
    "resolve_cell",
    "resolve_node",
]
