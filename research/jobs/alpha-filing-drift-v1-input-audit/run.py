"""VM source-eligibility gate; no return calculation."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from research.alpha_discovery.input_audit import main

if __name__ == "__main__":
    raise SystemExit(main("alpha-filing-drift-v1"))
