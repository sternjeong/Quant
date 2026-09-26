"""고전 팩터 공개 전후 감쇠표를 research/factor_decay.md 로 쓴다(Scout·Writer 에이전트가 읽는다).

    python scripts/french_factor_report.py            # 캐시가 7일 넘었으면 Ken French 사이트에서 다시 받는다
    python scripts/french_factor_report.py --stdout   # 파일을 쓰지 않고 화면에만

반년에 한 번 정도면 충분하다(원자료가 월 1회 갱신). 주문·DB 와 무관하다.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import french_factors as ff  # noqa: E402

OUT = ff.PROJECT_ROOT / "research" / "factor_decay.md"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args(argv)
    monthly = ff.monthly_factors()
    if monthly is None:
        print("Ken French 데이터를 받지 못했고 캐시도 없음", file=sys.stderr)
        return 1
    md = ff.render_decay_markdown(ff.decay_table(monthly), date.today().isoformat(),
                                  monthly.dropna(how="all").index[-1].strftime("%Y-%m"))
    if args.stdout:
        print(md)
    else:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(md, encoding="utf-8")
        print(f"wrote {OUT.relative_to(ff.PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
