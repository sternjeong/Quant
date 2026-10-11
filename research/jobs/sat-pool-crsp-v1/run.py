"""검증 sat-pool-crsp-v1 (2026-10-11 사전 등록) — 판정 규칙·구현은 research/jobs/sat-selection-lab/lab.py, 고정 규칙 문서는 이 폴더의 SPEC.md."""

import importlib.util
import sys
from pathlib import Path

_LAB = Path(__file__).resolve().parents[1] / "sat-selection-lab" / "lab.py"
_spec = importlib.util.spec_from_file_location("sat_selection_lab", _LAB)
lab = sys.modules.setdefault("sat_selection_lab", importlib.util.module_from_spec(_spec))
if not hasattr(lab, "run_job"):
    _spec.loader.exec_module(lab)

JOB_ID = "sat-pool-crsp-v1"

if __name__ == "__main__":
    raise SystemExit(lab.run_job(JOB_ID))
