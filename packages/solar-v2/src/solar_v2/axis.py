"""YearAxis — the model's time spine.

One construction year followed by `operating_years` operating years. All domain
frames are keyed by calendar year via this axis.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class YearAxis:
    """Construction year + operating-year calendar years."""

    construction_year: int
    operating_years: int

    @property
    def years(self) -> tuple[int, ...]:
        """Operating calendar years, e.g. 2021..2045."""
        start = self.construction_year + 1
        return tuple(range(start, start + self.operating_years))

    @property
    def all_years(self) -> tuple[int, ...]:
        """Construction year followed by all operating years."""
        return (self.construction_year, *self.years)

    @property
    def final_year(self) -> int:
        """Last operating calendar year."""
        return self.construction_year + self.operating_years

    @classmethod
    def of(cls, construction_year: int, operating_years: int) -> YearAxis:
        """Build an axis from explicit givens."""
        return cls(construction_year=construction_year, operating_years=operating_years)
