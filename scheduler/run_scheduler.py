"""독립 실행 스케줄러: 매일 미국 장마감 후 관심 종목 50개를 스캔해 타점 알림을 보내고,
매주 일요일 저녁에는 Threads 추적 티커별 주간 AI 인사이트 리포트를 생성하고,
매일 한국시간 00:00에는 시장 국면/섹터 강도 스냅샷을 미리 계산해두고,
00:05~04:00에는 #3 전략을 서버가 허락하는 만큼 반복 미세튜닝한다.

Streamlit 앱과 완전히 별도의 프로세스로 실행된다 (브라우저를 안 열어도 동작해야 하므로).

실행:
    python scheduler/run_scheduler.py

동작:
    - 미국 동부시간(America/New_York) 기준 평일 16:30 (장마감 16:00 + 30분 버퍼)에
      watchlist_scan_job() 을 실행하도록 APScheduler에 등록한다.
    - watchlist_scan_job() 은 core.watchlist.scan_watchlist() (모듈 C 공용 로직) 를 그대로
      호출한다. 이 함수가 watchlist 테이블의 각 (ticker, strategy_id) 조합에 대해
      core.strategy_engine.evaluate() 로 전략 조건(신규 진입 신호) 충족 여부를 계산하고,
      충족 시 alerts_log 에 기록 + 데스크톱 알림을 보낸다.
      (Streamlit 페이지 app/pages/3_관심종목_모니터링.py 의 "지금 스캔 실행" 버튼도
       동일한 core.watchlist.scan_watchlist() 를 호출하므로 로직이 완전히 일치한다.)
    - 매주 일요일 20:00 (America/New_York, 월요일 개장 전)에 threads_weekly_report_job() 을
      실행한다. core.threads_summary.list_tracked_tickers() 로 추적 중인 모든 티커를 찾아
      각각 core.threads_summary.generate_weekly_report() (모듈 B 공용 로직, 최근 7일)를
      호출하고 결과를 저장한다. (Streamlit 페이지 app/pages/2_Threads_요약.py 의
      "🧠 리포트 생성" 버튼도 동일한 함수를 호출하므로 로직이 완전히 일치한다.)
    - 매일 한국시간(Asia/Seoul) 00:00에 market_snapshot_job() 을 실행한다.
      core.market_regime.get_market_regime_snapshot() (S&P500 전종목 순회) 과
      core.sector_strength.compute_theme_strength() (테마 프록시 ETF 다수 순회)는 둘 다 무거운
      계산이라, 이 잡이 하루 한 번 미리 계산해 DB(MarketRegimeSnapshot/SectorStrengthSnapshot)에
      저장해두면 app/pages/7_시장_진단.py 의 "시장 국면/섹터 강도" 탭이 매번 다시 계산하지
      않고 저장된 최신 스냅샷을 즉시 읽기만 한다. 이 잡은 **선택 사항(proactive 최적화)**이다 —
      페이지 쪽에도 core.market_regime.is_snapshot_stale_for_today_kst() 기반의 자체 폴백이 있어서
      (2026-07-15), 이 스크립트가 아예 안 떠 있어도 한국시간 자정이 지난 뒤 첫 방문자가 그 자리에서
      자동으로 재계산을 트리거한다 — 다만 그 첫 방문자는 계산이 끝날 때까지 기다려야 한다는 차이가
      있다. 이 잡을 상시로 띄워두면 아무도 기다리지 않고 항상 최신 데이터를 바로 볼 수 있다.
    - 매일 한국시간(Asia/Seoul) 00:05~04:00에 strategy_nightly_tuning_job() 을 실행한다
      (2026-07-15 추가). 전략 라이브러리 #3("볼린저 밴드 하단 반전 1:2:6 전략")을 백본으로, 종목
      표본(매 반복 다른 시드)과 탐색 강도(빠름/보통/정밀 순환)를 바꿔가며
      core.strategy_tuning.run_and_save_tuning() 을 04:00까지 반복 실행하고 매번 새
      StrategyTuningRun으로 영구 저장한다. app/pages/1_전략_스튜디오.py("🌙 야간 미세튜닝 리더보드" 탭) 가 지금까지
      쌓인 모든 실행 결과 중 상위 10개(test 구간 초과수익 기준)를 보여준다. 이 잡은 (market_
      snapshot_job과 달리) 페이지 쪽 폴백이 없다 — 결과를 보려면 이 스크립트가 실제로 밤마다
      돌고 있어야 한다(그리고 리더보드 페이지는 이 스크립트와 같은 로컬 DB를 보는 로컬 앱에서만
      의미가 있다 — Streamlit Community Cloud 배포본은 DB가 분리돼 있어 이 잡의 결과를 볼 수 없다).

주의:
    - 이 스크립트는 core.* 를 프로젝트 루트 기준으로 임포트하므로, 아래처럼 sys.path에
      루트를 추가하는 부트스트랩이 필요하다 (app/Home.py 와 동일한 패턴).
    - market_snapshot_job()이 실제로 매일 00:00에 실행되려면 이 스크립트(python
      scheduler/run_scheduler.py)가 프로세스로 계속 떠 있어야 한다. 로컬(자체 서버/VM)에서는
      백그라운드 프로세스나 systemd 서비스로 띄워두면 되지만, Streamlit Community Cloud처럼 앱
      컨테이너 하나만 실행되고 별도 프로세스를 띄울 수 없는 배포 환경에서는 애초에 이 스크립트를
      실행할 수 없다 — 그런 환경에서는 위에서 설명한 페이지 쪽 자체 폴백(첫 방문자 트리거)이
      유일한 갱신 경로가 된다.
"""

import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from core.db import get_session, init_db
from core.kostolany_cycle import (
    compute_theme_cycle_phases,
    get_market_cycle_phase,
    save_kostolany_cycle_snapshot,
)
from core.market_regime import get_market_regime_snapshot, save_market_regime_snapshot
from core.models import Strategy
from core.notify import send_desktop_notification
from core.screener import get_universe
from core.sector_strength import compute_theme_strength, save_theme_strength_snapshot
from core.strategy_tuning import _SWING_MAX_HOLDING_DAYS, run_and_save_tuning, sample_universe
from core.threads_summary import generate_weekly_report, list_tracked_tickers, save_weekly_report
from core.watchlist import scan_watchlist


def watchlist_scan_job() -> None:
    """관심 종목 전체를 스캔해서 저장된 전략 조건 충족 여부를 확인하는 잡.

    실제 스캔/알림 로직은 core.watchlist.scan_watchlist() 에 있다 (모듈 C 공용 로직,
    Streamlit UI의 수동 스캔 버튼과 동일한 함수를 재사용).
    """
    print(f"[{datetime.now()}] watchlist_scan_job 시작")

    results = scan_watchlist(notify_fn=send_desktop_notification)
    if not results:
        print("watchlist가 비어있습니다. (app에서 관심 종목을 등록하세요)")
    else:
        for r in results:
            print(f"  - {r.message}")

    print(f"[{datetime.now()}] watchlist_scan_job 종료")


def threads_weekly_report_job() -> None:
    """추적 중인 모든 티커에 대해 최근 7일간 저장된 글을 종합한 주간 인사이트 리포트를 생성한다.

    실제 생성 로직은 core.threads_summary.generate_weekly_report() (모듈 B 공용 로직)를 그대로
    호출한다. 글이 하나도 없는 티커는 건너뛴다(빈 리포트를 저장하지 않음).
    """
    print(f"[{datetime.now()}] threads_weekly_report_job 시작")

    tickers = list_tracked_tickers()
    if not tickers:
        print("추적 중인 티커가 없습니다. (Threads 요약 페이지에서 먼저 글을 저장하세요)")
        print(f"[{datetime.now()}] threads_weekly_report_job 종료")
        return

    generated = 0
    for ticker in tickers:
        result = generate_weekly_report(ticker, days=7)
        if result["post_count"] == 0:
            continue
        save_weekly_report(
            result["ticker"], result["period_start"], result["period_end"],
            result["post_count"], result["report"],
        )
        generated += 1
        print(f"  - {ticker}: 글 {result['post_count']}건으로 리포트 생성")

    send_desktop_notification(
        "주간 Threads 인사이트 리포트 생성 완료",
        f"추적 중인 {len(tickers)}개 티커 중 {generated}개에 대해 리포트를 생성했습니다.",
    )
    print(f"[{datetime.now()}] threads_weekly_report_job 종료 (총 {generated}개 리포트 생성)")


def market_snapshot_job() -> None:
    """S&P500 유니버스 기반 시장 국면 + 섹터/테마 강도를 계산해 스냅샷으로 저장한다.

    두 계산 모두 유니버스 전종목/테마 프록시 ETF 다수를 yfinance로 순회하는 무거운 작업이라
    (core.market_regime.get_market_regime_snapshot, core.sector_strength.compute_theme_strength),
    Streamlit 페이지 로드마다 실시간으로 돌리는 대신 하루 한 번 여기서 미리 계산해 저장해두고
    app/pages/7_시장_진단.py 는 저장된 최신 스냅샷을 읽기만 한다.
    """
    print(f"[{datetime.now()}] market_snapshot_job 시작")

    tickers = get_universe()["Symbol"].tolist()
    if not tickers:
        print("S&P500 유니버스를 가져오지 못했습니다. 스냅샷 계산을 건너뜁니다.")
        print(f"[{datetime.now()}] market_snapshot_job 종료")
        return

    regime_snapshot = get_market_regime_snapshot(tickers)
    save_market_regime_snapshot(regime_snapshot)
    print(f"  - 시장 국면: {regime_snapshot['regime']} (종합 {regime_snapshot['total_score']:+.0f}점)")

    theme_df = compute_theme_strength()
    save_theme_strength_snapshot(theme_df)
    print(f"  - 섹터/테마 강도: {len(theme_df)}개 테마 계산 완료")

    market_cycle_phase = get_market_cycle_phase()
    theme_cycle_df = compute_theme_cycle_phases()
    save_kostolany_cycle_snapshot(market_cycle_phase, theme_cycle_df)
    cycle_label = market_cycle_phase["phase"] if market_cycle_phase else "N/A"
    print(f"  - 코스톨라니 달걀 국면: 시장={cycle_label}, {len(theme_cycle_df)}개 테마 계산 완료")

    send_desktop_notification(
        "시장 국면 / 섹터 강도 스냅샷 갱신 완료",
        f"{regime_snapshot['regime']} (종합 {regime_snapshot['total_score']:+.0f}점), "
        f"{len(theme_df)}개 테마 RS 점수 갱신, 코스톨라니 국면(시장)={cycle_label}.",
    )
    print(f"[{datetime.now()}] market_snapshot_job 종료")


# 사용자가 "매일 0시~4시 동안 #3 전략을 여러 차원에서 미세튜닝해서 최적의 전략을 찾아달라, 상위
# 10개를 웹사이트에서 볼 수 있게 해달라"고 요청 (2026-07-15). #3 = 전략 라이브러리의 "볼린저 밴드
# 하단 반전 1:2:6 전략". 배포된 Streamlit Community Cloud 사이트는 이 스케줄러가 아예 뜰 수 없는
# 환경(별도 프로세스 불가, 위 market_snapshot_job 설명 참고)이라 "웹사이트"는 이 스케줄러와 같은
# 로컬 DB를 읽는 로컬 앱(`streamlit run app/Home.py`)으로 확정(AskUserQuestion으로 확인).
# "여러 차원"은 종목 표본(매 반복 다른 시드로 재추출)과 탐색 강도(빠름/보통/정밀 순환)로 확정 —
# 분석 기간/Train-Test 비율은 이번 범위에 포함하지 않음(고정).
#
# 2026-07-21 추가: 사용자가 스스로를 스윙 트레이더로 확정(SPEC 15.1절)하고 "백테스팅/미세튜닝/야간
# 자동 미세튜닝에도 적용되는지" 물어 확인한 결과, 전략 스튜디오 페이지의 수동 튜닝에는 이미
# max_holding_days(SPEC 15절, 보유기간 상한) 체크박스가 있었지만 이 야간 배치는 여태 반영이 안 돼
# 있었다(SPEC 15.7절 "남은 후속 작업"). 이제 매 반복을 항상 스윙 제약(_SWING_MAX_HOLDING_DAYS=
# 126거래일≈6개월) 하에서 탐색하도록 고정 — 장기 보유가 최적으로 뽑히는 파라미터를 걸러내고 실제로
# 감당 가능한 보유기간 안에서 나온 결과만 리더보드에 쌓이게 한다. 기존에 쌓인(제약 없이 나온) 이력은
# 그대로 남아있고 StrategyTuningResult.max_holding_days로 구분 가능(리더보드 "스윙모드" 컬럼).
_NIGHTLY_TUNING_STRATEGY_ID = 3
_NIGHTLY_TUNING_UNIVERSE_N = 100
_NIGHTLY_TUNING_LOOKBACK_YEARS = 5
_NIGHTLY_TUNING_INTENSITIES = ["빠름", "보통", "정밀"]
_NIGHTLY_TUNING_WINDOW_END_KST = time(4, 0)  # 이 시각이 지나면 새 반복을 시작하지 않음


def strategy_nightly_tuning_job() -> None:
    """매일 한국시간 00:00~04:00 사이, 서버가 허락하는 만큼 #3 전략을 반복적으로 미세튜닝한다.

    반복마다 종목 표본(core.strategy_tuning.sample_universe를 매번 다른 시드로 호출)과 탐색 강도
    (빠름/보통/정밀을 순환)를 바꿔가며 core.strategy_tuning.run_and_save_tuning()을 실행하고, 매
    실행을 새 StrategyTuningRun으로 영구 저장한다(기존 "반년마다 재실행, 절대 덮어쓰지 않음" 설계
    원칙 그대로 재사용 — 다만 이제 야간마다 자동으로 여러 번 누적된다). 04:00 KST가 지나면 다음
    반복을 시작하지 않고 멈춘다(이미 시작된 반복은 끝까지 실행되므로 실제 종료 시각은 조금 넘어갈
    수 있음). app/pages/1_전략_스튜디오.py("🌙 야간 미세튜닝 리더보드" 탭) 가 지금까지 쌓인 모든 실행 결과 중 test 구간
    초과수익(excess_return) 상위 10개를 보여준다(core.strategy_tuning.get_top_tuning_results).
    매 반복 max_holding_days=_SWING_MAX_HOLDING_DAYS를 항상 넘겨 스윙 트레이딩 보유기간 상한
    (SPEC 15절) 하에서 탐색/검증한다(2026-07-21부터).

    반복 하나가 실패해도(네트워크 오류 등) 그 반복만 건너뛰고 다음 반복을 계속 시도한다.
    """
    print(f"[{datetime.now()}] strategy_nightly_tuning_job 시작")

    with get_session() as session:
        strategy = session.get(Strategy, _NIGHTLY_TUNING_STRATEGY_ID)
        if strategy is None:
            print(f"  전략 id={_NIGHTLY_TUNING_STRATEGY_ID}를 찾을 수 없어 건너뜁니다.")
            print(f"[{datetime.now()}] strategy_nightly_tuning_job 종료")
            return
        base_config = json.loads(strategy.indicator_config)
        strategy_name = strategy.name

    kst = ZoneInfo("Asia/Seoul")
    end_date = date.today()
    start_date = end_date - timedelta(days=365 * _NIGHTLY_TUNING_LOOKBACK_YEARS)
    seed_base = int(datetime.now(kst).strftime("%Y%m%d")) * 100  # 오늘 밤 안에서는 반복마다 다르지만 재현 가능

    iteration = 0
    while datetime.now(kst).time() < _NIGHTLY_TUNING_WINDOW_END_KST:
        intensity = _NIGHTLY_TUNING_INTENSITIES[iteration % len(_NIGHTLY_TUNING_INTENSITIES)]
        seed = seed_base + iteration
        print(f"  - 반복 {iteration + 1}: 탐색 강도={intensity}, 종목 표본 시드={seed}")
        try:
            tickers_df = sample_universe(_NIGHTLY_TUNING_UNIVERSE_N, random_seed=seed)
            run_id = run_and_save_tuning(
                base_config, _NIGHTLY_TUNING_UNIVERSE_N, start_date.isoformat(), end_date.isoformat(),
                intensity=intensity, base_strategy_id=_NIGHTLY_TUNING_STRATEGY_ID, tickers_df=tickers_df,
                max_holding_days=_SWING_MAX_HOLDING_DAYS,
            )
            print(f"    -> run_id={run_id} 저장 완료")
        except Exception as e:  # noqa: BLE001 - 반복 하나의 실패가 나머지 반복을 막지 않게 함
            print(f"    -> 반복 {iteration + 1} 실패: {e}")
        iteration += 1

    send_desktop_notification(
        "야간 미세튜닝 완료",
        f"'{strategy_name}' 전략을 밤새 {iteration}회 반복 미세튜닝했습니다. "
        "리더보드 페이지에서 상위 결과를 확인하세요.",
    )
    print(f"[{datetime.now()}] strategy_nightly_tuning_job 종료 (총 {iteration}회 반복)")


def main() -> None:
    init_db()

    scheduler = BlockingScheduler(timezone="America/New_York")
    scheduler.add_job(
        watchlist_scan_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone="America/New_York"),
        id="daily_watchlist_scan",
        name="매일 미국 장마감 후 관심 종목 타점 스캔",
        replace_existing=True,
    )
    scheduler.add_job(
        threads_weekly_report_job,
        trigger=CronTrigger(day_of_week="sun", hour=20, minute=0, timezone="America/New_York"),
        id="weekly_threads_report",
        name="매주 일요일 Threads 주간 인사이트 리포트 생성",
        replace_existing=True,
    )
    scheduler.add_job(
        market_snapshot_job,
        trigger=CronTrigger(hour=0, minute=0, timezone="Asia/Seoul"),
        id="daily_market_snapshot",
        name="매일 한국시간 00:00 시장 국면/섹터 강도 스냅샷 갱신",
        replace_existing=True,
    )
    scheduler.add_job(
        strategy_nightly_tuning_job,
        # market_snapshot_job과 정확히 같은 00:00에 동시 시작하지 않도록 5분 뒤로 offset.
        trigger=CronTrigger(hour=0, minute=5, timezone="Asia/Seoul"),
        id="nightly_strategy_tuning",
        name="매일 한국시간 00:05~04:00 #3 전략 반복 미세튜닝",
        replace_existing=True,
    )

    print("스케줄러 시작. 평일 16:30 에 관심 종목을 스캔하고, 매주 일요일 20:00 에 Threads 주간")
    print("인사이트 리포트를 생성합니다 (모두 America/New_York 기준). 매일 한국시간(Asia/Seoul)")
    print("00:00 에는 시장 국면/섹터 강도 스냅샷을 미리 계산해두고, 00:05~04:00 에는 #3 전략을")
    print("서버가 허락하는 만큼 반복 미세튜닝합니다.")
    print("Ctrl+C 로 종료할 수 있습니다.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("스케줄러 종료.")


if __name__ == "__main__":
    main()
