"""Compare projected values against benchmark (oracle) values.

Produces node-localized diff reports grouped by sheet.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class CellDiff:
    """One cell that differs between projection and benchmark."""

    node_id: str  # "损益!G8"
    sheet: str
    projected: object
    benchmark: object
    abs_diff: float | None = None
    rel_diff: float | None = None


def diff(
    projected: Mapping[str, object],
    benchmark: Mapping[str, object],
    rel_tol: float = 1e-6,
) -> list[CellDiff]:
    """Compare projected and benchmark values cell-for-cell.

    Numbers: relative-tolerance comparison (guards zero denominators).
    Error strings: exact equality.
    Missing/extra nodes are reported as diffs.
    """
    diffs: list[CellDiff] = []

    # The comparison universe is the projected (formula+error) node set;
    # literal benchmark nodes (labels, givens) are not compared.
    all_nodes = set(projected.keys())

    for node_id in sorted(all_nodes):
        sheet = node_id.split("!")[0] if "!" in node_id else "?"
        pv = projected.get(node_id)
        bv = benchmark.get(node_id)

        # Normalize error wrappers (ErrorValue from solar-v1) to strings
        if pv is not None and not isinstance(pv, (int, float, str, bool)):
            pv = getattr(pv, "value", str(pv))
        if bv is not None and not isinstance(bv, (int, float, str, bool)):
            bv = getattr(bv, "value", str(bv))

        # Missing in projection
        if pv is None:
            diffs.append(
                CellDiff(
                    node_id=node_id,
                    sheet=sheet,
                    projected=None,
                    benchmark=bv,
                )
            )
            continue

        # Missing in benchmark
        if bv is None:
            diffs.append(
                CellDiff(
                    node_id=node_id,
                    sheet=sheet,
                    projected=pv,
                    benchmark=None,
                )
            )
            continue

        # Both are error strings
        if isinstance(pv, str) and isinstance(bv, str):
            if pv != bv:
                diffs.append(
                    CellDiff(
                        node_id=node_id,
                        sheet=sheet,
                        projected=pv,
                        benchmark=bv,
                    )
                )
            continue

        # One is string, other is number
        if isinstance(pv, str) or isinstance(bv, str):
            diffs.append(
                CellDiff(
                    node_id=node_id,
                    sheet=sheet,
                    projected=pv,
                    benchmark=bv,
                )
            )
            continue

        # Both are numbers
        try:
            pvf = float(pv)
            bvf = float(bv)
        except (ValueError, TypeError):
            diffs.append(
                CellDiff(
                    node_id=node_id,
                    sheet=sheet,
                    projected=pv,
                    benchmark=bv,
                )
            )
            continue

        abs_diff = abs(pvf - bvf)

        # Relative comparison with an absolute floor for float noise
        if abs(bvf) > 1e-9:
            rel_diff = abs_diff / abs(bvf)
            if rel_diff > rel_tol:
                diffs.append(
                    CellDiff(
                        node_id=node_id,
                        sheet=sheet,
                        projected=pvf,
                        benchmark=bvf,
                        abs_diff=abs_diff,
                        rel_diff=rel_diff,
                    )
                )
        elif abs_diff > 1e-9:
            # Near-zero benchmark: absolute comparison at float-noise floor
            diffs.append(
                CellDiff(
                    node_id=node_id,
                    sheet=sheet,
                    projected=pvf,
                    benchmark=bvf,
                    abs_diff=abs_diff,
                    rel_diff=None,
                )
            )

    return diffs


def format_report(diffs: list[CellDiff]) -> str:
    """Format diffs as a node-localized summary grouped by sheet."""
    if not diffs:
        return "No differences found."

    from collections import defaultdict

    by_sheet: dict[str, list[CellDiff]] = defaultdict(list)
    for d in diffs:
        by_sheet[d.sheet].append(d)

    lines: list[str] = []
    lines.append(
        f"CellDiff report: {len(diffs)} differences across {len(by_sheet)} sheets"
    )
    lines.append("=" * 72)

    for sheet in sorted(by_sheet):
        sheet_diffs = by_sheet[sheet]
        lines.append(f"\n## {sheet} ({len(sheet_diffs)} diffs)")

        # Group by kind
        missing_p = [d for d in sheet_diffs if d.projected is None]
        missing_b = [d for d in sheet_diffs if d.benchmark is None]
        errors = [
            d
            for d in sheet_diffs
            if isinstance(d.projected, str) or isinstance(d.benchmark, str)
        ]
        numeric = [
            d
            for d in sheet_diffs
            if d not in missing_p and d not in missing_b and d not in errors
        ]

        if missing_p:
            lines.append(f"  Missing from projection ({len(missing_p)}):")
            for d in sorted(missing_p[:5], key=lambda x: x.node_id):
                lines.append(f"    {d.node_id}: benchmark={d.benchmark}")
            if len(missing_p) > 5:
                lines.append(f"    ... and {len(missing_p) - 5} more")

        if missing_b:
            lines.append(f"  Missing from benchmark ({len(missing_b)}):")
            for d in sorted(missing_b[:5], key=lambda x: x.node_id):
                lines.append(f"    {d.node_id}: projected={d.projected}")
            if len(missing_b) > 5:
                lines.append(f"    ... and {len(missing_b) - 5} more")

        if errors:
            lines.append(f"  Error mismatches ({len(errors)}):")
            for d in sorted(errors[:5], key=lambda x: x.node_id):
                lines.append(
                    f"    {d.node_id}: proj={d.projected!r} "
                    f"vs bench={d.benchmark!r}"
                )
            if len(errors) > 5:
                lines.append(f"    ... and {len(errors) - 5} more")

        if numeric:
            max_abs = max(d.abs_diff or 0 for d in numeric)
            max_rel = max(d.rel_diff or 0 for d in numeric)
            lines.append(
                f"  Numeric ({len(numeric)}): max_abs_diff={max_abs:.6e}, "
                f"max_rel_diff={max_rel:.6e}"
            )
            for d in sorted(numeric[:10], key=lambda x: -(x.abs_diff or 0)):
                lines.append(
                    f"    {d.node_id}: {d.projected} vs {d.benchmark} "
                    f"(abs={d.abs_diff:.6e}, rel={d.rel_diff})"
                )
            if len(numeric) > 10:
                lines.append(f"    ... and {len(numeric) - 10} more")

    return "\n".join(lines)
