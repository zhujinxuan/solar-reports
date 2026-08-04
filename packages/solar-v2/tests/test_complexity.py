"""Complexity gate — anti-cheating compression & reuse signatures.

Guards against both directions of gaming:
- *chunking* (hiding many cells in one fat function) cannot lower the MDL
  ratio or raise reuse;
- *fragmentation* (one function per cell) lowers reuse and raises item count.

Bounds are measured from the committed engine with headroom; a regression in
compression or reuse structure fails the build. See docs/complexity_report.md
and scripts/complexity_analysis.py for the metric definitions.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys

# Load the analysis script by path (it lives in scripts/, not on the package path).
_SCRIPT = (
    pathlib.Path(__file__).resolve().parents[1] / "scripts" / "complexity_analysis.py"
)
_spec = importlib.util.spec_from_file_location("complexity_analysis", _SCRIPT)
assert _spec and _spec.loader
_ca = importlib.util.module_from_spec(_spec)
sys.modules["complexity_analysis"] = _ca
_spec.loader.exec_module(_ca)


def _metrics():
    return _ca.metrics()


def test_mdl_compression():
    """Engine compute logic is terser than the raw cell formulas (MDL)."""
    m = _metrics()
    assert m.mdl_ratio_vs_tokens < 1.0, (
        f"MDL ratio {m.mdl_ratio_vs_tokens:.3f} >= 1.0: engine logic is not "
        "more compressed than the dag's expression tokens"
    )


def test_reuse_fanout():
    """Distilled concepts are reused (high fan-out), not translated 1:1."""
    m = _metrics()
    assert m.mean_fanout_producers >= 1.5, (
        f"mean fan-out {m.mean_fanout_producers:.3f} < 1.5: "
        "item graph looks like cell-by-cell translation"
    )
    assert m.hubs_fanout_ge3 >= 30, (
        f"only {m.hubs_fanout_ge3} high-fan-out hubs (< 30): "
        "no distilled hub concepts"
    )


def test_cyclomatic_bounds():
    """No stuffed mega-functions: per-function CC is bounded."""
    m = _metrics()
    assert m.cc_max <= 20, f"max cyclomatic complexity {m.cc_max} > 20"
    assert m.cc_median <= 2, f"median cyclomatic complexity {m.cc_median} > 2"


def test_item_count_bounded():
    """Domain item count stays in the ~300s (no runaway fragmentation)."""
    m = _metrics()
    assert m.total_items <= 380, f"item count {m.total_items} > 380"
