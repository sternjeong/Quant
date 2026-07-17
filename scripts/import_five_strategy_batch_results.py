"""data/five_strategy_batch_top10.json (GitHub Actions가 만든 배치 튜닝 결과)을
로컬 전략 라이브러리(Strategy 테이블)에 반영한다. 코드스페이스를 다시 켠 뒤 1회 실행하면 된다
(이미 같은 이름의 전략이 있으면 건너뛴다 - 중복 실행해도 안전).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.db import get_session, init_db  # noqa: E402
from core.models import Strategy  # noqa: E402

JSON_PATH = PROJECT_ROOT / "data" / "five_strategy_batch_top10.json"


def main() -> None:
    if not JSON_PATH.exists():
        print(f"{JSON_PATH} 없음 - GitHub Actions 배치가 아직 안 끝났거나 pull을 안 받았을 수 있습니다.")
        return

    init_db()
    entries = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    with get_session() as session:
        for e in entries:
            existing = session.query(Strategy).filter(Strategy.name == e["name"]).first()
            if existing:
                print(f"이미 존재: {e['name']} (id={existing.id}) - 스킵")
                continue
            obj = Strategy(
                name=e["name"],
                indicator_config=json.dumps(e["indicator_config"], ensure_ascii=False),
                source=e.get("source"),
                description=e.get("description"),
            )
            session.add(obj)
            session.flush()
            print(f"저장 완료: {e['name']} (id={obj.id}, 초과수익 {e['excess_return']:+.2f}%p)")


if __name__ == "__main__":
    main()
