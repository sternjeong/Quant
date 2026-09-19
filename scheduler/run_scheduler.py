"""독립 실행 스케줄러: 매일 미국 장마감 후 관심 종목 50개를 스캔해 타점 알림을 보내고,
매주 일요일 저녁에는 Threads 추적 티커별 주간 AI 인사이트 리포트를 생성하고,
매일 한국시간 00:00에는 시장 국면/섹터 강도 스냅샷을 미리 계산해두고,
00:05~04:00에는 #3 전략을 서버가 허락하는 만큼 반복 미세튜닝하며,
00:10에는 챔피언 전략(코어/새틀라이트) 신호 변경을 텔레그램으로 알리고,
00:11에는 챔피언 전략 보유종목 상관관계 스냅샷을 저장하고,
00:15에는 챔피언 전략 리밸런싱 예정일을 미리 텔레그램으로 알리고,
00:16에는 챔피언 전략 새틀라이트 실적 발표 예정을 미리 텔레그램으로 알리며,
00:20에는 FRED 거시지표(원/달러 환율 등) 캐시를 미리 강제로 새로 받아와 데워두고,
00:22에는 가격/FRED 캐시/뉴스 다이제스트 데이터 무결성을 체크해 이상 감지 시 텔레그램으로 알리며,
매주 일요일 20:20(America/New_York)에는 챔피언 전략 주간 HTML 보고를 텔레그램으로 전송한다.

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
    - 매일 한국시간(Asia/Seoul) 00:10에 champion_signal_alert_job() 을 실행한다(2026-09-14 추가).
      core.champion_strategy.check_and_notify_signal_changes() 가 코어 top4/시장필터/새틀라이트
      보유종목을 어제 저장된 상태(data/cache/champion_signal_state.json)와 비교해, 달라졌을 때만
      core.telegram_notify 로 알린다. .env에 TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID가 없으면 조용히
      알림만 생략되고(예외 없음) 상태 저장은 계속된다.
    - 매일 한국시간(Asia/Seoul) 00:15에 champion_rebalance_reminder_job() 을 실행한다(2026-09-14
      추가). champion_signal_alert_job(00:10, 사후 알림)과 짝을 이루는 사전 알림 — 내일(기본
      1거래일 이내) 코어(매월 첫 거래일) 또는 새틀라이트(1월/7월 첫 거래일) 리밸런싱일이 다가오면
      core.champion_strategy.check_and_notify_upcoming_rebalance() 가 텔레그램으로 미리 알린다.
      "내일이 리밸런싱일인지"는 달력 요일 기준 근사치로 판정한다(주말 제외 + 전날이 다른 달이면
      그 달의 첫 거래일로 봄) — 과거 가격 데이터로는 미래의 실제 거래소 휴장일(신정/추수감사절 등)을
      알 수 없어서다. 그래서 휴장일이 월초에 낀 해에는 최대 며칠 오차가 날 수 있다(예: 신정이
      평일이면 실제 첫 거래일은 그 다음날이지만 이 근사치는 신정 당일을 첫 거래일로 오판할 수 있음).
      같은 리밸런싱 날짜에 대해서는 한 번만 알린다(data/cache/champion_rebalance_reminder_state.json
      으로 dedupe). 텔레그램 설정이 없으면 champion_signal_alert_job과 마찬가지로 조용히 알림만
      생략된다.
    - 매일 한국시간(Asia/Seoul) 00:11에 champion_correlation_snapshot_job() 을 실행한다(2026-09-18
      추가). champion_signal_alert_job(00:10)이 그날 갱신한 신호 캐시(코어 top4+새틀라이트)를 읽어
      core.champion_strategy.compute_champion_correlation() 으로 보유종목 간 상관관계를 계산하고
      save_champion_correlation_snapshot() 으로 이력에 저장한다 — 새로 스캔하지 않고 캐시만 읽으므로
      가볍다. core.portfolio/core.backtest_engine이 이미 쓰는 "매번 새 스냅샷을 쌓아 추이를 보라"는
      원칙을 챔피언 전략 보유종목에도 적용한다(app/pages/11_챔피언_전략.py 상관관계 섹션에서 확인).
    - 매일 한국시간(Asia/Seoul) 00:16에 champion_earnings_reminder_job() 을 실행한다(2026-09-18
      추가). 챔피언 전략 새틀라이트(개별 종목) 보유종목 중 향후 5거래일 이내 실적 발표가 있으면
      core.champion_strategy.check_and_notify_upcoming_earnings() 가 텔레그램으로 미리 알린다.
      코어는 전부 ETF라 개별 기업 실적이 없어 대상에서 자연히 제외된다. 같은 (종목, 실적일)
      조합에는 한 번만 알린다(dedupe, champion_rebalance_reminder_job과 동일 원칙).
    - 매주 일요일 20:20(America/New_York)에 champion_weekly_report_job() 을 실행한다(2026-09-18
      추가). core.champion_strategy.send_weekly_report() 가 코어/새틀라이트 현황과 최근 상관관계를
      담은 HTML을 만들어 core.telegram_notify.send_document로 전송한다 — deploy/experiment_supervisor.py의
      "정기 HTML 보고서" 패턴과 같은 발상이다. threads_weekly_report_job(같은 요일 20:00)과 겹치지
      않도록 20분 뒤로 offset했다.
    - 매일 한국시간(Asia/Seoul) 00:20에 fred_indicator_prewarm_job() 을 실행한다(2026-09-14 추가).
      core.fred_data.get_series() 는 파일 캐시(TTL 24시간)가 만료되면 그날 처음 방문한 사용자가
      실시간 FRED API 호출을 그 자리에서 떠안는 구조라(원/달러 환율 DEXKOUS 포함),
      app/pages/7_시장_진단.py 의 경제지표/경기 사이클 섹션과 core.market_regime.
      get_advisory_risk_signals() 가 쓰는 지표(core.fred_data.DEFAULT_INDICATORS 8종 +
      BAMLH0A0HYM2/T10Y3M)를 이 잡이 cache_ttl=0으로 강제로 미리 새로 받아 캐시를 데워둔다 —
      새 계산 로직은 없고 기존 get_series()를 그대로 재사용. 지표 하나가 실패해도(FRED_API_KEY
      없음/일시적 오류) 나머지는 계속 갱신한다.
    - 매일 한국시간(Asia/Seoul) 00:22에 data_integrity_check_job() 을 실행한다(2026-09-19 추가).
      fred_indicator_prewarm_job(00:20)이 FRED 캐시를 막 갱신한 직후라, 그 갱신이 조용히 실패했을
      경우(예외 없이 빈 값/stale 캐시만 남는 경우)를 바로 그날 밤 잡아낼 수 있는 슬롯이다.
      core.data_integrity.run_integrity_checks() 가 (1) 챔피언 전략 코어+새틀라이트+시장필터(SPY)
      최근 가격의 종가<=0/이상 일간수익률/중복 인덱스/stale 여부, (2) data/cache/fred_*.csv 캐시의
      비어있음/파싱 오류/발표주기 대비 stale 여부, (3) 최근 24시간 NewsTickerDigest 행의 빈 요약/
      깨진 source_links JSON 여부를 검사해 findings를 반환한다 — 새 계산 로직 없이 기존에 저장된
      캐시/DB를 읽기만 하는 읽기 전용 체크다. anomalies가 하나라도 있으면 core.telegram_notify로
      심각도별(critical/warning)로 묶어 알리고, 없으면(정상) 다른 champion_* 잡과 같은 원칙대로
      알림을 생략한다(매일 밤 "이상 없음" 스팸 방지).

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
import time as time_module  # `time`(아래)은 datetime.time 클래스라 모듈은 별칭으로 가져온다.
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from core.db import get_session, init_db
from core.champion_strategy import (
    check_and_notify_signal_changes,
    check_and_notify_upcoming_earnings,
    check_and_notify_upcoming_rebalance,
    compute_champion_correlation,
    save_champion_correlation_snapshot,
    send_weekly_report,
)
from core.resource_guard import has_headroom
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
from core.news_digest import render_daily_telegram_summary, run_news_pipeline, write_daily_html_report
from core.telegram_notify import send_document, send_message
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


def champion_signal_alert_job() -> None:
    """챔피언 전략(app/pages/11_챔피언_전략.py)의 코어 top4/시장필터/새틀라이트 보유종목이
    어제 저장된 상태와 달라졌으면 텔레그램으로 알린다 (2026-09-14 추가).

    core.champion_strategy.check_and_notify_signal_changes()가 실제 계산/비교/알림/저장을 전부
    담당한다 — 이 잡은 그냥 호출만 한다. include_satellite=True라 새틀라이트 스캔(S&P500 500종목
    순차 조회, 수 분 소요)까지 매번 수행한다 — market_snapshot_job과 마찬가지로 무거운 전체
    스캔이라 야간 시간대에 배치한다. 텔레그램 설정(TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID)이 없으면
    core.telegram_notify.send_message가 조용히 False를 반환할 뿐 예외는 나지 않는다.
    """
    print(f"[{datetime.now()}] champion_signal_alert_job 시작")
    result = check_and_notify_signal_changes(include_satellite=True)
    if result["changed"]:
        print(f"  - 신호 변경 감지, 텔레그램 알림 전송 시도:\n{result['message']}")
    else:
        print("  - 신호 변경 없음 (알림 생략)")
    print(f"[{datetime.now()}] champion_signal_alert_job 종료")


def champion_rebalance_reminder_job() -> None:
    """내일(기본 1거래일 이내) 챔피언 전략 코어/새틀라이트 리밸런싱일이 다가오면 텔레그램으로
    미리 알린다 (2026-09-14 추가). champion_signal_alert_job(00:10, 사후 알림 — 리밸런싱이 이미
    반영된 신호와 어제 상태를 비교)과 짝을 이루는 사전 알림이다.

    core.champion_strategy.check_and_notify_upcoming_rebalance()가 실제 판정/알림/저장을 전부
    담당한다 — 이 잡은 그냥 호출만 한다. "내일이 리밸런싱일인지"는 달력 요일 기준 근사치로
    판정한다(실제 거래소 휴장일은 반영하지 못함 — 예: 신정이 평일이면 그 날을 리밸런싱일로
    오판할 수 있음, check_and_notify_upcoming_rebalance 문서 참고). 같은 리밸런싱 날짜에 대해서는
    한 번만 알린다(data/cache/champion_rebalance_reminder_state.json으로 dedupe). 텔레그램 설정이
    없으면 champion_signal_alert_job과 마찬가지로 조용히 알림만 생략된다.
    """
    print(f"[{datetime.now()}] champion_rebalance_reminder_job 시작")
    result = check_and_notify_upcoming_rebalance()
    if result["notified"]:
        print(f"  - 리밸런싱 예정 감지, 텔레그램 알림 전송 시도:\n{result['message']}")
    else:
        print(
            f"  - 알림 없음 (core={result['core_rebalance_date']}, "
            f"satellite={result['satellite_rebalance_date']})"
        )
    print(f"[{datetime.now()}] champion_rebalance_reminder_job 종료")


def champion_correlation_snapshot_job() -> None:
    """챔피언 전략(코어+새틀라이트) 보유종목 간 상관관계를 계산해 이력으로 저장한다 (2026-09-18
    추가). champion_signal_alert_job(00:10) 다음에 배치해, 그날 새로 갱신된 신호 캐시를 그대로
    읽는다(core.champion_strategy.get_current_holdings 참고 — 새로 스캔하지 않고 캐시만 읽으므로
    빠르다). "이번 한 번만 보고 판단하지 말고 이력을 쌓아 보라"는 원칙(core.portfolio/
    core.backtest_engine의 기존 상관관계 스냅샷과 동일)을 챔피언 전략에도 적용한다.
    """
    print(f"[{datetime.now()}] champion_correlation_snapshot_job 시작")
    result = compute_champion_correlation()
    if result["correlation"].empty:
        print(f"  - 종목이 2개 미만이라 건너뜀 (tickers={result['tickers']})")
    else:
        snap_id = save_champion_correlation_snapshot(result["correlation"])
        print(f"  - 스냅샷 저장 완료 (id={snap_id}, 종목={result['tickers']})")
    print(f"[{datetime.now()}] champion_correlation_snapshot_job 종료")


def champion_earnings_reminder_job() -> None:
    """챔피언 전략 새틀라이트 보유종목 중 향후 5거래일 이내 실적 발표가 있으면 텔레그램으로
    미리 알린다 (2026-09-18 추가). 코어는 전부 ETF라 개별 기업 실적이 없으므로 새틀라이트만
    대상이다 — core.champion_strategy.check_and_notify_upcoming_earnings 참고.
    """
    print(f"[{datetime.now()}] champion_earnings_reminder_job 시작")
    result = check_and_notify_upcoming_earnings()
    if result["notified"]:
        print(f"  - 실적 발표 예정 감지, 텔레그램 알림 전송 시도:\n{result['message']}")
    else:
        print(f"  - 알림 없음 (upcoming={result['upcoming']})")
    print(f"[{datetime.now()}] champion_earnings_reminder_job 종료")


def champion_weekly_report_job() -> None:
    """챔피언 전략의 이번 주 상태를 HTML 보고서로 만들어 텔레그램 문서로 전송한다 (2026-09-18
    추가). core.champion_strategy.send_weekly_report가 실제 조립/전송을 담당한다.
    """
    print(f"[{datetime.now()}] champion_weekly_report_job 시작")
    result = send_weekly_report()
    print(f"  - 보고서 저장: {result['path']} (전송 {'성공' if result['sent'] else '실패/미설정'})")
    print(f"[{datetime.now()}] champion_weekly_report_job 종료")


def fred_indicator_prewarm_job() -> None:
    """FRED 거시지표(환율 등)를 새벽에 미리 강제로 새로 받아와 캐시를 데워둔다 (2026-09-14 추가).

    배경: `core.fred_data.get_series()`는 파일 캐시(TTL 24시간)를 쓰는데, 캐시가 만료된 뒤 그날
    처음 이 지표를 보는 사용자가 실시간 FRED API 호출(+실패 시 재시도)을 그 자리에서 그대로
    떠안는 구조였다 — `app/pages/7_시장_진단.py`의 "경제지표"/"경기 사이클" 섹션(원/달러 환율
    DEXKOUS 포함)과 `core.market_regime.get_advisory_risk_signals()`가 전부 이 방식이라, 새벽에
    아무도 안 미리 데워두면 사용자가 접속할 때마다 느려질 수 있다. 새 계산 로직을 만들지 않고
    이미 있는 `get_series()`를 그대로 재사용하되, `cache_ttl=0`을 줘서 "캐시가 있어도 무조건
    새로 받아와서 저장"하도록만 강제한다(파일에는 정상적으로 저장됨 — use_cache=True는 그대로
    유지, cache_ttl만 0이라 나이 체크가 항상 실패해 라이브 호출로 빠짐).

    `core.fred_data.DEFAULT_INDICATORS`(대시보드 카드 8종 — 원/달러 환율 DEXKOUS 포함)에
    `core.market_regime.get_advisory_risk_signals()`가 추가로 쓰는 BAMLH0A0HYM2(하이일드
    스프레드)/T10Y3M(장단기금리차)까지 더해 전부 갱신한다. 개별 지표 하나가 실패해도(FRED_API_KEY
    없음/일시적 API 오류) 나머지는 계속 진행한다."""
    from core.fred_data import DEFAULT_INDICATORS, get_series

    print(f"[{datetime.now()}] fred_indicator_prewarm_job 시작")
    series_ids = list(DEFAULT_INDICATORS.keys()) + ["BAMLH0A0HYM2", "T10Y3M"]
    refreshed = 0
    for series_id in series_ids:
        try:
            series = get_series(series_id, cache_ttl=0)
            if not series.empty:
                refreshed += 1
                print(f"  - {series_id}: 갱신 완료 (최신값 {series.dropna().iloc[-1] if not series.dropna().empty else 'N/A'})")
            else:
                print(f"  - {series_id}: 빈 결과(FRED_API_KEY 미설정 또는 API 오류)")
        except Exception as e:  # noqa: BLE001 - 지표 하나 실패가 나머지를 막지 않게 함
            print(f"  - {series_id}: 갱신 실패: {e}")
    print(f"[{datetime.now()}] fred_indicator_prewarm_job 종료 ({refreshed}/{len(series_ids)}개 갱신)")


def data_integrity_check_job() -> None:
    """야간 데이터 무결성 체크 (2026-09-19 추가).

    core.data_integrity.run_integrity_checks()가 실제 검사(가격 이상치/FRED 캐시 stale/뉴스
    다이제스트 파싱 오류)를 전부 담당한다 — 이 잡은 호출하고 결과를 텔레그램으로 알리기만 한다.
    다른 champion_* 잡들과 동일한 철학: anomalies가 비어있으면("이상 없음") 알림을 보내지 않는다
    (매일 밤 "이상 없음" 스팸 방지). 텔레그램 설정이 없으면 send_message가 조용히 False를 반환할
    뿐 예외는 나지 않는다.
    """
    from core.data_integrity import format_anomaly_telegram_message, run_integrity_checks

    print(f"[{datetime.now()}] data_integrity_check_job 시작")
    result = run_integrity_checks()
    print(f"  - 체크 {len(result['checks'])}건, 이상 {len(result['anomalies'])}건")
    if result["anomalies"]:
        for a in result["anomalies"]:
            print(f"    · [{a['severity']}] {a['check']}: {a['detail']}")
        send_message(format_anomaly_telegram_message(result["anomalies"]))
    else:
        print("  - 이상 없음 (알림 생략)")
    print(f"[{datetime.now()}] data_integrity_check_job 종료")


def daily_news_digest_job() -> None:
    """무료 뉴스 API의 최근 24시간 메타데이터를 HTML과 Telegram으로 보고한다.

    야간 전체 스캔과 겹치지 않는 KST 07:30에 둔다. VM 여유가 없으면 API/Gemini 호출을
    강행하지 않고 다음 일일 실행으로 넘긴다.
    """
    print(f"[{datetime.now()}] daily_news_digest_job 시작")
    if not has_headroom():
        print("  - 리소스 여유가 없어 뉴스 수집·요약을 이번 회차에는 건너뜁니다.")
        return
    try:
        result = run_news_pipeline()
        digests = result["digests"]
        send_message(render_daily_telegram_summary(digests))
        if digests:
            report_path = write_daily_html_report(digests)
            send_document(report_path, "📰 일일 티커 뉴스 리서치 전체 보고서")
        print(f"  - 새 기사 {result['refresh']['added']}건, 새 요약 {len(digests)}개")
    except Exception as exc:  # noqa: BLE001 - 다음 날 스케줄을 막지 않도록 기록만 남긴다.
        print(f"  - 뉴스 일일 보고 실패: {type(exc).__name__}: {exc}")
    print(f"[{datetime.now()}] daily_news_digest_job 종료")


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
# 2026-09-18 추가: 이 잡은 00:00~04:00 사이 몇 시간을 반복 백테스트로 채우는 이 VM에서 가장 무거운
# 작업이다. 같은 VM에서 독립적으로 도는 Telegram 큐(deploy/codex_telegram/runner.py)나 2주 실험
# 감독기(deploy/experiment_supervisor.py)도 아무 때나 Claude/Codex를 돌릴 수 있어서, 반복 시작
# 직전마다 core.resource_guard.has_headroom()으로 여유를 확인한다 — 부족하면 이번 반복을 건너뛰지
# 않고 그냥 잠시 기다렸다 재확인한다(반복 인덱스/시드가 흐트러지면 안 되므로).
_NIGHTLY_TUNING_HEADROOM_BACKOFF_SECONDS = 120
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
        if not has_headroom():
            print(f"  - 여유 리소스 부족(다른 작업과 겹침으로 추정) — "
                  f"{_NIGHTLY_TUNING_HEADROOM_BACKOFF_SECONDS}초 대기 후 재확인")
            time_module.sleep(_NIGHTLY_TUNING_HEADROOM_BACKOFF_SECONDS)
            continue
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
    scheduler.add_job(
        champion_signal_alert_job,
        # market_snapshot_job(00:00)과 겹치지 않도록 10분 뒤로 offset. 새틀라이트 스캔(수 분)이
        # strategy_nightly_tuning_job(00:05~04:00)과 같은 시간대에 겹쳐도, 별도 스레드(APScheduler
        # 기본 ThreadPoolExecutor)에서 동시 실행되므로 서로 막지 않는다.
        trigger=CronTrigger(hour=0, minute=10, timezone="Asia/Seoul"),
        id="champion_signal_alert",
        name="매일 한국시간 00:10 챔피언 전략 신호 변경 텔레그램 알림",
        replace_existing=True,
    )
    scheduler.add_job(
        champion_correlation_snapshot_job,
        # champion_signal_alert_job(00:10)이 그날의 신호 캐시를 갱신한 직후 1분 뒤 — 캐시만 읽으므로
        # 재스캔 없이 빠르다.
        trigger=CronTrigger(hour=0, minute=11, timezone="Asia/Seoul"),
        id="champion_correlation_snapshot",
        name="매일 한국시간 00:11 챔피언 전략 보유종목 상관관계 스냅샷 저장",
        replace_existing=True,
    )
    scheduler.add_job(
        champion_rebalance_reminder_job,
        # 기존 00:00/00:05/00:10/00:11 잡과 겹치지 않도록 15분 뒤로 offset(비어있는 슬롯).
        trigger=CronTrigger(hour=0, minute=15, timezone="Asia/Seoul"),
        id="champion_rebalance_reminder",
        name="매일 한국시간 00:15 챔피언 전략 리밸런싱 예정일 사전 텔레그램 알림",
        replace_existing=True,
    )
    scheduler.add_job(
        champion_earnings_reminder_job,
        # champion_rebalance_reminder_job(00:15) 바로 다음 슬롯(비어있음).
        trigger=CronTrigger(hour=0, minute=16, timezone="Asia/Seoul"),
        id="champion_earnings_reminder",
        name="매일 한국시간 00:16 챔피언 전략 새틀라이트 실적 발표 예정 텔레그램 알림",
        replace_existing=True,
    )
    scheduler.add_job(
        champion_weekly_report_job,
        # 기존 주간 잡(threads_weekly_report, 일요일 20:00 America/New_York)과 겹치지 않도록
        # 20분 뒤로 offset — 일간 00:00~00:20 KST 블록과 달리 이건 주 1회면 충분한 보고서라
        # 그 블록에 넣지 않고 다른 주간 잡 옆에 둔다.
        trigger=CronTrigger(day_of_week="sun", hour=20, minute=20, timezone="America/New_York"),
        id="champion_weekly_report",
        name="매주 일요일 20:20(America/New_York) 챔피언 전략 주간 HTML 보고 Telegram 전송",
        replace_existing=True,
    )
    scheduler.add_job(
        fred_indicator_prewarm_job,
        # 기존 00:00~00:15 잡들과 안 겹치도록 20분 뒤로 offset(비어있는 슬롯).
        trigger=CronTrigger(hour=0, minute=20, timezone="Asia/Seoul"),
        id="fred_indicator_prewarm",
        name="매일 한국시간 00:20 FRED 거시지표(환율 등) 캐시 미리 갱신",
        replace_existing=True,
    )
    scheduler.add_job(
        data_integrity_check_job,
        # fred_indicator_prewarm_job(00:20)이 FRED 캐시를 막 갱신한 다음 슬롯(비어있는 슬롯) —
        # 갱신 직후 상태를 검사해야 "방금 실패한 갱신"을 그날 바로 잡아낼 수 있다.
        trigger=CronTrigger(hour=0, minute=22, timezone="Asia/Seoul"),
        id="data_integrity_check",
        name="매일 한국시간 00:22 가격/FRED 캐시/뉴스 다이제스트 데이터 무결성 체크",
        replace_existing=True,
    )
    scheduler.add_job(
        daily_news_digest_job,
        trigger=CronTrigger(hour=7, minute=30, timezone="Asia/Seoul"),
        id="daily_news_digest",
        name="매일 한국시간 07:30 티커별 뉴스 HTML/Telegram 보고",
        replace_existing=True,
    )

    print("스케줄러 시작. 평일 16:30 에 관심 종목을 스캔하고, 매주 일요일 20:00 에 Threads 주간")
    print("인사이트 리포트를, 20:20 에 챔피언 전략 주간 보고를 생성합니다 (모두 America/New_York")
    print("기준). 매일 한국시간(Asia/Seoul) 00:00 에는 시장 국면/섹터 강도 스냅샷을 미리 계산해두고,")
    print("00:05~04:00 에는 #3 전략을 서버가 허락하는 만큼 반복 미세튜닝하며, 00:10 에는 챔피언")
    print("전략 신호 변경을, 00:11 에는 보유종목 상관관계 스냅샷을, 00:15 에는 리밸런싱 예정일을,")
    print("00:16 에는 새틀라이트 실적 발표 예정을, 00:20 에는 FRED 거시지표(환율 등) 캐시를 미리")
    print("갱신/알리고, 00:22 에는 가격/FRED 캐시/뉴스 다이제스트 데이터 무결성을 체크해 이상 감지 시")
    print("텔레그램으로 알립니다. 매일 한국시간 07:30에는 무료 뉴스 API 기반 티커별 HTML/Telegram 리포트를 보냅니다.")
    print("Ctrl+C 로 종료할 수 있습니다.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("스케줄러 종료.")


if __name__ == "__main__":
    main()
