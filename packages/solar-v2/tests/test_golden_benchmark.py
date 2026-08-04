"""Golden-benchmark tests — completeness and accuracy vs solar-v1.

Module-scoped fixtures amortize the ~20s solar-v1 compute.
"""

from __future__ import annotations

from v2_benchmark.compare import diff, format_report
from v2_benchmark.layout import check_layout
from v2_benchmark.projection import project


def test_layout_completeness():
    """Check_layout covers every dag formula+error node exactly once."""
    issues = check_layout()
    assert issues, "check_layout must return a list (empty = clean)"
    for issue in issues:
        assert "(OK)" in issue, f"Layout gap: {issue}"


def test_accuracy(model_results, benchmark_values):
    """Zero diffs vs solar-v1 benchmark at rel_tol=1e-6."""
    projected = project(model_results)
    diffs = diff(projected, benchmark_values, rel_tol=1e-6)
    assert diffs == [], (
        f"Benchmark mismatch: {len(diffs)} cells differ\n\n"
        f"{format_report(diffs)}"
    )
