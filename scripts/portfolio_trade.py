"""매수·매도 기록 CLI — 대화 중 사용자가 알려준 체결을 Claude/사람이 VM 에서 반영할 때 쓴다(core/portfolio_trades.py).

    sudo -u quant /opt/quant/.venv/bin/python scripts/portfolio_trade.py "XLK 3 매도 210.5" "매수 SPY 2 650 11/19"
    ... --dry-run   # 읽은 내용·바뀔 수량만 보기
    ... --list      # 최근 기록
    ... --undo      # 마지막 한 건 되돌리기
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="매수·매도 기록")
    ap.add_argument("lines", nargs="*", help="한 건씩: 'XLK 3 매도 210.5' (날짜 M/D·YYYY-MM-DD, '수수료 1.2', '전량' 가능)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--undo", action="store_true")
    ap.add_argument("--note", default=None, help="매매근거(매수 기록에 남김)")
    a = ap.parse_args(argv)

    from core import portfolio_trades as pt
    from core.db import init_db

    init_db()
    try:
        if a.undo:
            r = pt.undo_last_trade()
            print(f"되돌림: #{r['id']} {r['trade_date']} {r['ticker']} {r['quantity']:g}주 {'매수' if r['side'] == 'BUY' else '매도'}")
            for m in r["messages"]:
                print(f"  ⚠ {m}")
            return 0
        if a.list:
            for r in pt.list_trades(20):
                print(f"#{r['id']} {r['trade_date']} {r['ticker']} {r['quantity']:g}주 {'매수' if r['side'] == 'BUY' else '매도'} "
                      f"@ ${r['price_usd']:,.2f}" + (f" · 실현 ${r['realized_usd']:,.2f}" if r["realized_usd"] is not None else ""))
            return 0
        trades = pt.parse_trade_text("\n".join(a.lines))
        if not trades:
            ap.error("기록할 매매가 없습니다")
        if a.dry_run:
            for r in pt.preview(trades):
                print(f"{r['trade_date']} {r['ticker']} {'매수' if r['side'] == 'BUY' else '매도'} {r['quantity']:g}주 @ ${r['price']:,.2f}"
                      f" · 보유 {r['before']:g} → {r['after']:g}주")
            return 0
        for r in pt.record_trades(trades, note=a.note):
            print(pt.format_result(r))
        return 0
    except ValueError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
