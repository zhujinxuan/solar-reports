"""LibreOffice headless recalculation adapter.

Strategy (proven by perturbation test):
  - LO's xlsx export writes empty <v/> for formula cells after recalculation.
  - The workaround: convert xlsx → ods (LO recalculates on load; ODS preserves
    computed values), then convert ods → xlsx (ODS values carry through).
  - A temporary user profile with Calc/Formula/Load/OOXMLRecalcMode=0 ensures
    full recalculation on import.
  - fullCalcOnLoad=True in the workbook itself is also respected.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from xlsx_core.recalc.base import RecalcResult


class LibreOfficeRecalc:
    """Recalculate a workbook via LibreOffice headless.

    Uses a two-step ODS intermediate approach because LO's direct xlsx export
    does not include cached formula results after recalculation.
    """

    name: str = "libreoffice"

    def __init__(self, libreoffice_path: Path) -> None:
        self._soffice = libreoffice_path

    def recalc(self, workbook: Path, out_dir: Path) -> RecalcResult:
        t0 = time.perf_counter()
        errors: list[str] = []
        out_dir.mkdir(parents=True, exist_ok=True)

        # Create a temp user profile with forced recalc
        tmp_profile = Path(tempfile.mkdtemp(prefix="lo_recalc_"))
        try:
            self._write_recalc_profile(tmp_profile)

            # Step 1: convert xlsx → ods (triggers recalc)
            src_copy = out_dir / workbook.name
            shutil.copy2(workbook, src_copy)

            if not self._convert(tmp_profile, src_copy, "ods", out_dir, errors):
                wall = time.perf_counter() - t0
                return RecalcResult(
                    engine=self.name,
                    ok=False,
                    wall_seconds=wall,
                    errors=tuple(errors),
                )

            # The convert-to may name the output workbook_stem.ods
            expected_ods = out_dir / (workbook.stem + ".ods")
            if not expected_ods.exists():
                errors.append(f"ODS intermediate not found at {expected_ods}")
                wall = time.perf_counter() - t0
                return RecalcResult(
                    engine=self.name,
                    ok=False,
                    wall_seconds=wall,
                    errors=tuple(errors),
                )

            # Step 2: convert ods → xlsx (computed values carry through)
            xlsx_output = out_dir / ("recalc_" + workbook.name)
            if not self._convert(tmp_profile, expected_ods, "xlsx", out_dir, errors):
                wall = time.perf_counter() - t0
                return RecalcResult(
                    engine=self.name,
                    ok=False,
                    wall_seconds=wall,
                    errors=tuple(errors),
                )

            # The convert-to output is workbook_stem.xlsx
            intermediate_xlsx = out_dir / (workbook.stem + ".xlsx")
            if intermediate_xlsx.exists() and intermediate_xlsx != xlsx_output:
                shutil.move(str(intermediate_xlsx), str(xlsx_output))

            # Clean up
            src_copy.unlink(missing_ok=True)
            expected_ods.unlink(missing_ok=True)

            if not xlsx_output.exists():
                errors.append(f"Final xlsx not found at {xlsx_output}")
                wall = time.perf_counter() - t0
                return RecalcResult(
                    engine=self.name,
                    ok=False,
                    wall_seconds=wall,
                    errors=tuple(errors),
                )

            wall = time.perf_counter() - t0
            return RecalcResult(
                engine=self.name,
                ok=len(errors) == 0,
                wall_seconds=wall,
                errors=tuple(errors),
                recalced_path=xlsx_output,
            )
        finally:
            shutil.rmtree(tmp_profile, ignore_errors=True)

    @staticmethod
    def _write_recalc_profile(profile_dir: Path) -> None:
        """Write registrymodifications.xcu to force OOXMLRecalcMode=0."""
        user_dir = profile_dir / "user"
        user_dir.mkdir(parents=True, exist_ok=True)
        regmod = user_dir / "registrymodifications.xcu"
        regmod.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<oor:items xmlns:oor="http://openoffice.org/2001/registry">\n'
            '  <item oor:path="/org.openoffice.Office.Calc/Formula/Load">\n'
            '    <prop oor:name="OOXMLRecalcMode" oor:op="fuse">\n'
            "      <value>0</value>\n"
            "    </prop>\n"
            "  </item>\n"
            "</oor:items>\n",
            encoding="utf-8",
        )

    def _convert(
        self,
        profile_dir: Path,
        src: Path,
        fmt: str,
        out_dir: Path,
        errors: list[str],
    ) -> bool:
        """Run soffice --convert-to and return True on success."""
        cmd: list[str] = [
            str(self._soffice),
            "--headless",
            f"-env:UserInstallation=file:///{profile_dir.as_posix()}",
            "--convert-to",
            fmt,
            "--outdir",
            str(out_dir),
            str(src),
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min per conversion step
        )
        if proc.returncode != 0:
            errors.append(
                f"soffice --convert-to {fmt} exit {proc.returncode}: "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
            return False
        return True
