"""Shared fixtures for solar-v2 test suite."""

from __future__ import annotations

import pytest
from solar_v2.engine import compute_model
from solar_v2.inputs import ModelInputs


@pytest.fixture(scope="session")
def default_inputs():
    """Default ModelInputs with workbook literal defaults."""
    return ModelInputs()


@pytest.fixture(scope="module")
def model_results():
    """Compute ModelResults once per test module (~1s)."""
    return compute_model()


@pytest.fixture(scope="module")
def benchmark_values():
    """Compute solar-v1 benchmark values once per test module (~20s).

    Marked as module-scoped so the slow path runs exactly once
    per test file that needs it.
    """
    from solar_v1.api import compute

    return compute().values
