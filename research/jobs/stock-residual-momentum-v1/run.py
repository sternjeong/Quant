"""Pre-registered return-upgrade job: stock-residual-momentum-v1"""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from research.return_upgrade.runner import main

if __name__ == '__main__':
    raise SystemExit(main("stock-residual-momentum-v1"))
