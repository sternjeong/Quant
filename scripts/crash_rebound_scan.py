"""급락장 반등 신호 포착기 (읽기 전용).

SPY 와 빅테크 14종목의 지금 급락 상태와 crash-rebound-signal-v1 의 반등 신호 7개를 한국어로 보여 준다.
신호 계산은 연구 스크립트(research/jobs/crash-rebound-signal-v1/run.py)의 함수를 그대로 쓴다.
엔진·아침 메시지·주문·스케줄러는 건드리지 않는다. 연구 판정이 나오기 전의 신호는 참고값이다.

    python scripts/crash_rebound_scan.py            # 최신 yfinance 종가로 요약
    python scripts/crash_rebound_scan.py --json     # 같은 내용을 JSON 으로
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

JOB_ID = "crash-rebound-signal-v1"
RESULTS = PROJECT_ROOT / "research" / "results" / JOB_ID / "results.json"
MARKET = ("SPY",)


def study():
    """연구 스크립트를 모듈로 불러온다(폴더 이름에 '-' 가 있어 import 문을 못 쓴다)."""
    name = "crash_rebound_signal_v1"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / "research" / "jobs" / JOB_ID / "run.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def scan(prices: dict[str, pd.Series], epu: Optional[pd.Series] = None) -> dict[str, dict]:
    """종목별 최신 상태. SPY 는 시장 기준(−15%/−5%), 나머지는 종목 기준(−30%/−10%)."""
    m = study()
    out = {}
    for tk, s in prices.items():
        crash, end = (m.MKT_CRASH, m.MKT_END) if tk in MARKET else (m.STK_CRASH, m.STK_END)
        out[tk] = m.latest_state(m.state_frame(s, crash, end, epu))
    return out


def load_verdicts(path: Path = RESULTS) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("verdicts")
    except (OSError, ValueError):
        return None


def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x * 100:+.1f}%"


def render(states: dict[str, dict], verdicts: Optional[dict]) -> str:
    m = study()
    L = ["급락장 반등 신호 포착기 (읽기 전용 · 주문·엔진과 연결 안 됨)"]
    if not verdicts:
        L.append(f"연구 판정: 아직 없음({JOB_ID} VM 실행 대기). 아래 신호는 검증 전 참고값이다.")
    else:
        helps = [s for s, v in verdicts.items() if v == "SIGNAL_HELPS"]
        L.append("연구 판정: " + ", ".join(f"{s} {v}" for s, v in verdicts.items()))
        L.append("→ 통과한 신호: " + ", ".join(helps) if helps else
                 "→ 통과한 신호 없음: 기본값은 신호를 기다리지 않고 원래 계획대로 사는 것(아래는 참고만).")
    L.append("신호 뜻: " + " · ".join(f"{s}={m.LABELS[s]}" for s in m.SIGNALS))
    L.append("")
    in_crash = [tk for tk, d in states.items() if d.get("available") and d["in_crash"]]
    stocks = [tk for tk in states if tk not in MARKET]
    L.append(f"급락 상태: 시장(SPY) {'예' if any(t in MARKET for t in in_crash) else '아니오'} · "
             f"빅테크 {sum(1 for t in in_crash if t not in MARKET)}/{len(stocks)} 종목")
    for tk, d in states.items():
        if not d.get("available"):
            L.append(f"- {tk}: 자료 없음")
            continue
        base = (f"- {tk} ({d['date']}): 고점 대비 {_pct(d['dd'])}, RSI {'—' if d['rsi'] is None else f'{d['rsi']:.0f}'}, "
                f"20일선 {'위' if d['above_ma20'] else '아래'}")
        if not d["in_crash"]:
            L.append(base + f" · 급락 상태 아님(기준 {_pct(d['crash_th'])})")
            continue
        today = ", ".join(s for s, on in d["signals_today"].items() if on) or "없음"
        fired = ", ".join(f"{s} {dt}" for s, dt in d["first_fired"].items() if dt) or "없음"
        extra = []
        if d.get("vol_ratio") is not None:
            extra.append(f"변동성/사건 최고 {d['vol_ratio']:.2f}")
        if d.get("news_ratio") is not None:
            extra.append(f"EPU/사건 최고 {d['news_ratio']:.2f}")
        L.append(base + f" · 급락 상태(시작 {d['episode_start']}, {d['days_in_episode']}거래일째, 최저일 뒤 {d['days_since_low']}일"
                 + (", " + ", ".join(extra) if extra else "") + ")")
        L.append(f"    오늘 켜진 신호: {today} | 사건 중 처음 켜진 날: {fired}")
    L.append("")
    L.append("주의: 빅테크는 살아남은 종목 표본이다. 뉴스 지수(EPU)는 월별이고 한 달 늦게 반영한다. 매수 결정은 사용자 몫이다.")
    return "\n".join(L)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="급락장 반등 신호 포착기(읽기 전용)")
    p.add_argument("--json", action="store_true", help="JSON 으로 출력")
    p.add_argument("--start", default="2005-01-01", help="가격 조회 시작일")
    a = p.parse_args(argv)
    m = study()
    prices = m.fetch_prices(MARKET + tuple(m.BIGTECH), start=a.start)
    states = scan(prices, m.load_news())
    verdicts = load_verdicts()
    if a.json:
        print(json.dumps({"states": states, "verdicts": verdicts}, ensure_ascii=False, indent=1, default=str))
    else:
        print(render(states, verdicts))
    return 0 if prices else 1


if __name__ == "__main__":
    raise SystemExit(main())
