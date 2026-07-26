"""G1 golden test: interpret the full solar DAG and verify 0 mismatches."""

from __future__ import annotations

from solar_v1.api import verify


def test_g1_golden_check() -> None:
    """G1: interpret dag/solar.dag.yaml and compare against cached values.

    Expected: 5059 formula+error nodes (5054 formula + 5 error),
    0 mismatches at rel_tol 1e-6 / abs_tol 1e-9.
    """
    report = verify()

    assert report.total_formula_nodes == 5059, (
        f"Expected 5059 formula+error nodes, got {report.total_formula_nodes}"
    )
    assert report.mismatch_count == 0, (
        f"G1 golden check failed: {report.mismatch_count} mismatches\n"
        + "\n".join(
            f"  {m.node_id}: expected={m.expected!r}, got={m.got!r}"
            for m in report.mismatches[:20]
        )
    )
