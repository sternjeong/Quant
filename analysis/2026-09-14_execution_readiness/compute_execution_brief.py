"""리서치 에이전트 E(실행 준비가) — 오늘(2026-09-14) 기준 실행 브리핑 데이터 산출.

`research_agents/agent_e_execution_readiness.md` 지시대로:
  - `analysis/LATEST_STRATEGY_CANDIDATE.md`가 없어(에이전트 D 산출물 미존재/오늘 미갱신) 폴백 규칙에
    따라 이미 라이브로 도는 `core/champion_strategy.py`의 현재 기본 설정(코어+새틀라이트)을
    "오늘의 후보"로 삼는다.
  - 새 계산 로직을 만들지 않는다 — 전부 core/champion_strategy.py, core/portfolio.py 함수를
    그대로 호출한다.
  - 비중은 항상 "포트폴리오 대비 %"로 표현한다. 이 실행은 격리된 git worktree 안에서 돌아가고
    있어 로컬 data/quant.db가 비어 있다(테이블 없음) — 즉 사용자의 실제 보유 종목/현금 잔고를 이
    실행에서는 알 수 없다. 이는 정상적인 실행 환경(사용자의 실제 Codespace/서버)에서는 해소되는
    이 실행만의 제약이다 — 아래 EXECUTION_BRIEF.md에서 명시한다.

이 스크립트를 실행하면 report_data.json이 갱신된다(멱등 — 같은 날 다시 돌리면 그날 시장 데이터
기준으로 값이 갱신될 뿐 로직은 동일).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = OUT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))  # analysis/<날짜>_<주제>/에서 core/를 임포트하기 위한 관례(다른 analysis 스크립트와 동일)

import pandas as pd

from core import champion_strategy as cs
from core.portfolio import get_cash_balance, get_portfolio_pnl

REPORT_JSON = OUT_DIR / "report_data.json"


def _df_to_records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records"))


def main() -> None:
    t0 = time.time()

    # 1) 코어 — 오늘 기준 17자산 모멘텀 랭킹 + 시장필터 (core/champion_strategy.py 그대로 호출)
    core_result = cs.compute_core_recommendation()

    # 2) 새틀라이트 — 두 가지 라이브 계산 경로를 모두 실행해서 비교한다(구현 격차 확인 목적):
    #    (a) point-in-time: 백테스트가 실제로 검증한 방법론(반기 리밸런싱, point-in-time 40종목
    #        풀, 12개월 모멘텀 상위 3개) — final_config가 채택한 것과 동일한 로직.
    #    (b) naive scan: app/pages/11_챔피언_전략.py의 "내 포트폴리오와 비교" 리밸런싱 diff가
    #        실제로 사용하는 함수(S&P500 전체 스캔, 3개월 모멘�/ 상위 5개) — 백테스트 방법론과
    #        다르다는 걸 그 페이지 자신도 캡션으로 경고하고 있음(engine_architecture 관례 확인용).
    satellite_pit = cs.compute_satellite_recommendation_point_in_time()
    satellite_naive = cs.compute_satellite_recommendation()

    # 3) 실제 보유/현금 — core.portfolio 함수를 그대로 호출(새 로직 없음). 이 worktree는 격리된
    #    빈 SQLite라 결과는 항상 "없음"이지만, 함수 자체는 정상 실행 환경에서 그대로 재사용 가능함을
    #    보이기 위해 호출한다(실패해도 예외를 던지지 않도록 try/except로 감싸 이 실행이 멈추지
    #    않게 한다 — 테이블 자체가 없는 극단 케이스라 core 함수 내부 가정을 벗어남).
    try:
        holdings_pnl = get_portfolio_pnl()
    except Exception as e:
        holdings_pnl = pd.DataFrame()
        holdings_error = str(e)
    else:
        holdings_error = None

    try:
        cash_balance = get_cash_balance()
    except Exception as e:
        cash_balance = None
        cash_error = str(e)
    else:
        cash_error = None

    # 4) 리밸런싱 diff — 실제 보유가 있을 때만 의미가 있다(총 계좌가치 0이면 compute_rebalance_diff가
    #    빈 DataFrame을 반환하도록 이미 core에 가드가 있음). point-in-time 새틀라이트 기준으로 시도.
    diff_df = pd.DataFrame()
    diff_note = None
    if holdings_error is None and cash_error is None:
        try:
            diff_df = cs.compute_rebalance_diff(
                core_result, satellite_result=satellite_pit, holdings_pnl=holdings_pnl, cash_balance=cash_balance
            )
            if diff_df.empty:
                diff_note = (
                    "보유 종목/현금 잔고가 모두 0(이 worktree의 data/quant.db가 비어 있음)이라 "
                    "compute_rebalance_diff가 빈 DataFrame을 반환했습니다 — 목표비중 표를 그대로 "
                    "실행 기준으로 삼으세요."
                )
        except Exception as e:
            diff_note = f"compute_rebalance_diff 호출 실패: {e}"
    else:
        diff_note = (
            f"holdings 조회 실패({holdings_error}) 또는 cash_balance 조회 실패({cash_error}) — "
            "이 worktree는 격리된 빈 SQLite(data/quant.db, 0바이트)라 portfolio_holdings/"
            "portfolio_cash_balance 테이블 자체가 없습니다. 정상 실행 환경(사용자의 실제 Codespace, "
            "init_db()가 이미 호출된 앱)에서는 이 문제가 없습니다."
        )

    # 5) 목표 비중 통합 테이블(현금 성분 포함) — 사람이 바로 읽을 수 있는 "오늘의 목표 배분"
    target_rows = []
    for t in core_result["top4"]:
        target_rows.append({
            "ticker": t, "sleeve": "코어", "target_weight_pct": round(core_result["per_ticker_weight"] * 100, 2),
            "momentum_pct": float(core_result["ranked"].set_index("ticker").loc[t, "momentum_pct"]),
        })
    for t, w in satellite_pit["per_ticker_weights"].items():
        row = satellite_pit["picks"][satellite_pit["picks"]["ticker"] == t]
        target_rows.append({
            "ticker": t, "sleeve": "새틀라이트(point-in-time)", "target_weight_pct": round(w * 100, 2),
            "return_since_rebal_pct": float(row["return_since_rebal_pct"].iloc[0]) if not row.empty else None,
        })
    cash_pct = core_result["cash_weight_from_filter"] * 100 + satellite_pit["unallocated_weight"] * 100
    if cash_pct > 1e-9:
        target_rows.append({"ticker": "CASH", "sleeve": "현금(미배정)", "target_weight_pct": round(cash_pct, 2)})

    naive_vs_pit_overlap = sorted(set(satellite_naive["selected"]) & set(satellite_pit["selected"]))
    naive_only = sorted(set(satellite_naive["selected"]) - set(satellite_pit["selected"]))
    pit_only = sorted(set(satellite_pit["selected"]) - set(satellite_naive["selected"]))

    report = {
        "generated_at": pd.Timestamp.today().isoformat(),
        "as_of": core_result["as_of"],
        "candidate_source": (
            "폴백: analysis/LATEST_STRATEGY_CANDIDATE.md 없음(에이전트 D 미실행/오늘 미갱신) — "
            "core/champion_strategy.py 현재 기본 설정(코어 85% top4 모멘텀 + 새틀라이트 15% "
            "point-in-time 돈치안 브레이크아웃, final_config 그대로)을 오늘의 후보로 사용"
        ),
        "core": {
            "as_of": core_result["as_of"],
            "ranked": _df_to_records(core_result["ranked"]),
            "top4": core_result["top4"],
            "above_200dma": core_result["above_200dma"],
            "spy_price": core_result["spy_price"],
            "spy_sma200": core_result["spy_sma200"],
            "exposure_multiplier": core_result["exposure_multiplier"],
            "per_ticker_weight_pct": round(core_result["per_ticker_weight"] * 100, 2),
            "cash_weight_from_filter_pct": round(core_result["cash_weight_from_filter"] * 100, 2),
            "next_rebalance_note": "매월 첫 거래일(달력 근사) — 다음 코어 리밸런싱은 2026-10-01 전후",
        },
        "satellite_point_in_time": {
            "as_of": satellite_pit["as_of"],
            "rebal_date": satellite_pit["rebal_date"],
            "trading_days_to_next_rebal_approx": satellite_pit["trading_days_to_next_rebal"],
            "pool_size": satellite_pit["pool_size"],
            "n_active_trend": satellite_pit["n_active_trend"],
            "selected": satellite_pit["selected"],
            "sizing_method": satellite_pit["sizing_method"],
            "per_ticker_weights_pct": {t: round(w * 100, 2) for t, w in satellite_pit["per_ticker_weights"].items()},
            "picks": _df_to_records(satellite_pit["picks"]),
            "unallocated_weight_pct": round(satellite_pit["unallocated_weight"] * 100, 2),
            "methodology_note": (
                "final_config가 채택한 정적 반기 보유 방법론 그대로(_pick_satellite_at_date 재사용) "
                "— 반기 중간에 트레일링스탑이 이론상 발동해도 다음 리밸런싱(2027-01)까지 그대로 "
                "보유하는 게 연구 프로그램의 명시적 결론(기댓값 기준 정적보유가 모든 동적 방어보다 "
                "우위, H33/H35). 즉 CAT/GEV의 리밸런싱 이후 하락은 '버그'가 아니라 채택된 설계다."
            ),
        },
        "satellite_naive_scan": {
            "as_of": satellite_naive["as_of"],
            "scanned_count": satellite_naive["scanned_count"],
            "n_candidates": int(len(satellite_naive["candidates"])),
            "selected": satellite_naive["selected"],
            "per_ticker_weights_pct": {t: round(w * 100, 2) for t, w in satellite_naive["per_ticker_weights"].items()},
            "methodology_note": (
                "app/pages/11_챔피언_전략.py의 '내 포트폴리오와 비교' 리밸런싱 diff 섹션이 실제로 "
                "쓰는 함수 — S&P500 전체 매번 스캔, 3개월 모멘텀 상위 5개, 반기 리밸런싱 개념 없음. "
                "백테스트가 검증한 방법론과 다르다(구현 격차, 아래 gaps 참고)."
            ),
        },
        "satellite_pit_vs_naive_overlap": {
            "both": naive_vs_pit_overlap, "naive_only": naive_only, "point_in_time_only": pit_only,
        },
        "target_allocation_table": target_rows,
        "portfolio_link": {
            "holdings_available": holdings_error is None,
            "holdings_error": holdings_error,
            "cash_balance_available": cash_error is None,
            "cash_error": cash_error,
            "cash_balance": cash_balance,
            "rebalance_diff": _df_to_records(diff_df) if not diff_df.empty else [],
            "rebalance_diff_note": diff_note,
        },
        "implementation_gaps": [
            {
                "id": "satellite_diff_uses_unvalidated_method",
                "severity": "medium",
                "finding": (
                    "app/pages/11_챔피언_전략.py의 '5. 내 포트폴리오와 비교' 섹션(compute_rebalance_diff "
                    "호출부, 라인 555 부근)은 satellite_result 변수를 쓰는데, 이 변수는 '🔍 빠른 근사 "
                    "스캔' 탭(compute_satellite_recommendation, S&P500 전체 스캔+3개월 모멘텀 상위5)에서 "
                    "채워진다 — 정작 백테스트가 검증하고 final_config가 채택한 방법론인 "
                    "'✅ 반기 point-in-time' 탭(compute_satellite_recommendation_point_in_time)의 "
                    "결과(satellite_pit_result)는 diff 계산에 전혀 연결돼 있지 않다."
                ),
                "consequence": (
                    "오늘 실측 기준: point-in-time 방법(백테스트와 동일 방법론)은 {CAT, GEV, JNJ}를 "
                    "추천하는데, naive 스캔(현재 페이지가 실제 diff에 쓰는 방법)은 서로 다른 종목 집합을 "
                    "내놓는다(둘 다 실행해 report_data.json::satellite_pit_vs_naive_overlap 참고) — 사용자가 "
                    "페이지의 '사고팔아야 할 것' 표를 그대로 따르면, 실제로는 백테스트 성과가 검증한 적 "
                    "없는 종목을 매매하게 된다."
                ),
                "proposed_spec": (
                    "app/pages/11_챔피언_전략.py 라인 555의 compute_rebalance_diff(...) 호출에서 "
                    "satellite_result 인자를 satellite_pit_result(세션 상태 'champion_satellite_pit_result')로 "
                    "바꾼다. UI 문구도 '아직 스캔하지 않았습니다' 조건을 champion_satellite_pit_result 유무로 "
                    "바꿔야 한다. 하위호환을 위해 naive 스캔 결과도 참고용으로 별도 노출은 유지 가능하나, "
                    "실제 매매 diff의 기본값은 반드시 point-in-time이어야 한다. core/champion_strategy.py "
                    "자체는 수정할 필요 없음(compute_rebalance_diff는 이미 두 결과 형식 모두를 받을 수 있는 "
                    "인터페이스 — satellite_result 딕셔너리에 selected/per_ticker_weights/unallocated_weight "
                    "키만 있으면 됨). 사람이 확인 후 반영 권장(이 에이전트는 app/*.py를 직접 고치지 않음)."
                ),
            },
            {
                "id": "empty_local_portfolio_db_in_isolated_worktree",
                "severity": "low_operational",
                "finding": (
                    "이 실행은 격리된 git worktree에서 돌았고, 그 worktree의 data/quant.db는 0바이트(테이블 "
                    "없음)라 core.portfolio.get_portfolio_pnl()/get_cash_balance()가 각각 "
                    "'no such table: portfolio_holdings'/'no such table: portfolio_cash_balance' "
                    "OperationalError를 던졌다 — E 페르소나 지침대로 예외를 삼키고(try/except) '모르면 "
                    "%로만' 원칙에 따라 목표비중 표만 산출했다."
                ),
                "consequence": (
                    "이번 실행에서는 실제 보유 대비 매수/매도 방향(diff)을 계산하지 못했다 — 아래 "
                    "EXECUTION_BRIEF.md의 표는 '목표 배분'이며 '오늘 실제로 몇 주를 사고팔아야 하는지'가 "
                    "아니다."
                ),
                "proposed_spec": (
                    "새 코드 불필요 — 사용자의 실제 Codespace/서버 환경(메인 체크아웃, data/quant.db에 "
                    "실제 보유 종목이 8_포트폴리오_관리 페이지로 입력되어 있는 곳)에서 이 스크립트나 "
                    "app/pages/11_챔피언_전략.py를 그대로 돌리면 init_db()가 이미 호출돼 있고 실제 데이터가 "
                    "있으므로 정상적으로 diff가 나온다. 격리 worktree에서 R&D 에이전트를 돌리는 현재 아키텍처 "
                    "(PROGRESS.md 작업67)의 의도된 트레이드오프 — 안전(다른 세션과 충돌 없음) 대신 실제 "
                    "포트폴리오 데이터 접근을 포기함. 매일 밤 진짜 diff까지 원하면 이 E 에이전트를 "
                    "worktree가 아니라 메인 체크아웃에서(또는 실제 DB를 마운트해) 돌리는 방안을 사용자와 "
                    "논의해야 한다(이 에이전트가 스스로 결정할 사안 아님)."
                ),
            },
        ],
        "confidence_citations": {
            "core_market_filter": next(
                (r for r in cs.load_confidence_table() if "시장필터" in r.get("component", "") or "market_filter" in r.get("component", "").lower()),
                None,
            ),
            "satellite_exit_mechanism": "정적 반기 보유 채택 근거는 final_config.satellite.exit_mechanism 그대로 인용(위 satellite_point_in_time.methodology_note)",
        },
        "elapsed_seconds": round(time.time() - t0, 1),
    }

    with open(REPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"wrote {REPORT_JSON} in {report['elapsed_seconds']}s")
    print("core top4:", core_result["top4"])
    print("satellite (point-in-time):", satellite_pit["selected"])
    print("satellite (naive scan):", satellite_naive["selected"])


if __name__ == "__main__":
    main()
