"""독립 실행 스케줄러: 매일 미국 장마감 후 관심 종목 50개를 스캔해 타점 알림을 보내고,
매주 일요일 저녁에는 Threads 추적 티커별 주간 AI 인사이트 리포트를 생성하고,
매일 한국시간 00:00에는 시장 국면/섹터 강도 스냅샷을 미리 계산해두고,
00:05~04:00에는 #3 전략을 서버가 허락하는 만큼 반복 미세튜닝하며,
00:10에는 챔피언 전략(코어/새틀라이트) 신호 변경을 텔레그램으로 알리고,
00:11에는 챔피언 전략 보유종목 상관관계 스냅샷을 저장하고,
00:12에는 챔피언 전략 페이퍼 트레이딩 원장에 오늘자 실현 수익률을 기록하고,
00:13에는 그 원장이 60/40 벤치마크 대비 크게 뒤처지면 텔레그램으로 알리고,
00:15에는 챔피언 전략 리밸런싱 예정일(과 겹치면 칼라 헤지 롤 예정도 함께)을 미리 텔레그램으로 알리고,
00:16에는 챔피언 전략 새틀라이트 실적 발표 예정을 미리 텔레그램으로 알리며,
00:18에는 챔피언 전략 알파 감쇠(백테스트 성과 이탈) 여부를 체크해 감지되면 텔레그램으로 알리고,
00:20에는 FRED 거시지표(원/달러 환율 등) 캐시를 미리 강제로 새로 받아와 데워두고,
00:22에는 가격/FRED 캐시/뉴스 다이제스트 데이터 무결성을 체크해 이상 감지 시 텔레그램으로 알리며,
00:25에는 그날 밤 다른 모든 챔피언 전략 잡(신호/상관관계/원장/벤치마크/리밸런싱/실적/알파감쇠/
데이터무결성)의 결과를 모아 "오늘의 브리핑" 한 장짜리 HTML로 텔레그램 전송하고(daily_briefing_job,
core.daily_briefing 참고 — 다른 야간 잡들이 그날의 데이터를 다 갱신한 뒤 마지막에 요약하도록 배치),
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
      생략된다. (2026-09-19 추가) 코어 리밸런싱일이 임박했을 때는 칼라 헤지 롤 예정도 같은
      메시지에 함께 알린다 — 칼라도 매월 첫 거래일에 롤되는 동일 스케줄이라 별도 잡을 새로
      만들지 않고 이 자리에 붙였다(core.champion_strategy._collar_roll_reminder_line 참고).
    - 매일 한국시간(Asia/Seoul) 00:11에 champion_correlation_snapshot_job() 을 실행한다(2026-09-18
      추가). champion_signal_alert_job(00:10)이 그날 갱신한 신호 캐시(코어 top4+새틀라이트)를 읽어
      core.champion_strategy.compute_champion_correlation() 으로 보유종목 간 상관관계를 계산하고
      save_champion_correlation_snapshot() 으로 이력에 저장한다 — 새로 스캔하지 않고 캐시만 읽으므로
      가볍다. core.portfolio/core.backtest_engine이 이미 쓰는 "매번 새 스냅샷을 쌓아 추이를 보라"는
      원칙을 챔피언 전략 보유종목에도 적용한다(app/pages/11_챔피언_전략.py 상관관계 섹션에서 확인).
    - 매일 한국시간(Asia/Seoul) 00:12에 champion_ledger_record_job() 을 실행한다(2026-09-19 추가).
      core.champion_strategy.record_daily_ledger_entry() 가 "어제 저장해둔 추천 비중으로 오늘
      실제 실현됐을 수익률"을 계산해 champion_ledger_entries 테이블에 누적 기록하고, 오늘 기준
      새 추천 비중을 내일 쓸 값으로 다시 저장한다 — 지금까지의 알림들은 전부 "추천"이나 "과거
      백테스트"만 다뤘는데, 이 잡이 처음으로 "실제로 매일 따랐다면"의 관점을 기록으로 남긴다.
    - 매일 한국시간(Asia/Seoul) 00:13에 champion_benchmark_gap_job() 을 실행한다(2026-09-19 추가).
      champion_ledger_record_job(00:12)이 쌓은 원장의 누적 실현수익률을 60/40(SPY/TLT) 벤치마크와
      비교해(core.champion_strategy.check_and_notify_benchmark_gap()), 크게 뒤처지면(기본
      -5%p 이상) 텔레그램으로 알린다. 원장이 20영업일 미만이면 비교 자체를 건너뛴다(표본 부족을
      정직하게 인정 — 억지로 이른 판정을 내리지 않음).
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
    - 매일 한국시간(Asia/Seoul) 00:18에 champion_alpha_decay_job() 을 실행한다(2026-09-19 추가).
      core.champion_strategy.check_and_notify_champion_alpha_decay() 가 챔피언 전략(코어+새틀라이트)
      백테스트를 전체기간과 최근 6개월로 각각 돌려 최근 성과가 전체기간 대비 얼마나 이탈했는지
      비교하고(core.backtest_engine.compute_alpha_decay와 동일한 판정 원칙), 감쇠가 감지되면
      텔레그램으로 알린다 — "이 전략을 계속 믿어도 되는가"를 사람이 매번 수동으로 백테스트를
      다시 돌려보지 않아도 알 수 있게 하는 라이브-백테스트 드리프트 감지다. 감쇠 상태가 계속되는
      동안은 매일 재알림하지 않는다(dedupe). 전체기간(기본 8년) 백테스트를 매일 다시 돌리는 게
      무거운 계산이라(챔피언 백테스트 안에서도 새틀라이트 반기 point-in-time 스캔이 가장 느림)
      champion_earnings_reminder_job(00:16) 바로 다음 슬롯에 뒀다.
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
    - 매일 한국시간(Asia/Seoul) 00:25에 daily_briefing_job() 을 실행한다(2026-09-19 추가).
      core.daily_briefing.send_daily_briefing() 이 그날 밤 다른 모든 챔피언 전략 잡(신호/상관관계/
      리밸런싱/실적/알파감쇠/데이터무결성)이 이미 계산·저장해둔 결과를 읽기만 해서(새 계산 없음)
      "오늘 확인이 필요한 게 있는가"를 30초 안에 훑어볼 수 있는 한 장짜리 HTML로 모아 텔레그램
      문서로 전송한다 — 지금까지는 이 잡들이 각각 따로 텔레그램 메시지를 보내 흩어져 있었는데,
      사용자가 이 프로젝트를 거의 전적으로 폰 텔레그램 봇으로 접하기 때문에(데스크톱 UI를 직접
      여는 경우가 드묾) 하나로 모아 보여주는 게 더 유용하다. 요약할 데이터가 그날 밤 전부
      갱신되어 있어야 의미가 있으므로, 00:00~00:22 블록의 다른 모든 잡보다 뒤(첫 빈 슬롯)에 둔다.

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

import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from core.db import init_db
from core.process_registry import is_enabled
from core.job_health import attach_job_run_listener, report_job_failure
from core.champion_strategy import (
    check_and_notify_benchmark_gap,
    check_and_notify_champion_alpha_decay,
    check_and_notify_signal_changes,
    check_and_notify_upcoming_earnings,
    check_and_notify_upcoming_rebalance,
    compute_champion_correlation,
    record_daily_ledger_entry,
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
from core.notify import send_desktop_notification
from core.screener import get_universe
from core.sector_strength import compute_theme_strength, save_theme_strength_snapshot
from core.threads_summary import generate_weekly_report, list_tracked_tickers, save_weekly_report
from core.news_digest import render_daily_telegram_summary, run_news_pipeline, write_daily_html_report
from core.telegram_notify import send_document, send_message
from core.watchlist import scan_watchlist


def watchlist_scan_job() -> None:
    """관심 종목 전체를 스캔해서 저장된 전략 조건 충족 여부를 확인하는 잡.

    실제 스캔/알림 로직은 core.watchlist.scan_watchlist() 에 있다 (모듈 C 공용 로직,
    Streamlit UI의 수동 스캔 버튼과 동일한 함수를 재사용).
    """
    if not is_enabled("watchlist_scan"):
        print(f"[{datetime.now()}] watchlist_scan_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
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
    if not is_enabled("threads_weekly_report"):
        print(f"[{datetime.now()}] threads_weekly_report_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
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
    if not is_enabled("market_snapshot"):
        print(f"[{datetime.now()}] market_snapshot_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
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
    if not is_enabled("champion_signal_alert"):
        print(f"[{datetime.now()}] champion_signal_alert_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
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
    if not is_enabled("champion_rebalance_reminder"):
        print(f"[{datetime.now()}] champion_rebalance_reminder_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
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
    if not is_enabled("champion_correlation_snapshot"):
        print(f"[{datetime.now()}] champion_correlation_snapshot_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    print(f"[{datetime.now()}] champion_correlation_snapshot_job 시작")
    result = compute_champion_correlation()
    if result["correlation"].empty:
        print(f"  - 종목이 2개 미만이라 건너뜀 (tickers={result['tickers']})")
    else:
        snap_id = save_champion_correlation_snapshot(result["correlation"])
        print(f"  - 스냅샷 저장 완료 (id={snap_id}, 종목={result['tickers']})")
    print(f"[{datetime.now()}] champion_correlation_snapshot_job 종료")


def champion_ledger_record_job() -> None:
    """페이퍼 트레이딩 원장에 오늘자 항목을 기록한다 (2026-09-19 추가). 어제 저장해둔 비중으로
    오늘 실현된 수익률을 계산하고, 오늘 기준 새 추천 비중을 다음날 쓸 값으로 다시 저장한다 —
    core.champion_strategy.record_daily_ledger_entry 참고. champion_correlation_snapshot_job
    (00:11) 다음 슬롯 — 코어/새틀라이트 추천을 다시 계산하므로 순서상 상관없지만 챔피언 관련
    일간 잡들을 한 블록에 모아둔다.
    """
    if not is_enabled("champion_ledger_record"):
        print(f"[{datetime.now()}] champion_ledger_record_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    print(f"[{datetime.now()}] champion_ledger_record_job 시작")
    result = record_daily_ledger_entry()
    if result["skipped"]:
        print("  - 오늘자 항목이 이미 있어 건너뜀")
    else:
        print(f"  - 기록 완료 (실현수익률={result['realized_return_pct']}%, 누적자산={result['cumulative_equity']})")
    print(f"[{datetime.now()}] champion_ledger_record_job 종료")


def champion_benchmark_gap_job() -> None:
    """페이퍼 트레이딩 원장의 실현 성과가 60/40(SPY/TLT) 벤치마크 대비 크게 뒤처지면 텔레그램으로
    알린다 (2026-09-19 추가). champion_ledger_record_job(00:12) 바로 다음 슬롯 — 그날 막 기록된
    원장 항목을 포함해서 비교한다. core.champion_strategy.check_and_notify_benchmark_gap 참고.
    """
    if not is_enabled("champion_benchmark_gap"):
        print(f"[{datetime.now()}] champion_benchmark_gap_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    print(f"[{datetime.now()}] champion_benchmark_gap_job 시작")
    result = check_and_notify_benchmark_gap()
    comparison = result["comparison"]
    if not comparison.get("available"):
        print(f"  - 비교 불가: {comparison.get('reason')}")
    elif result["notified"]:
        print(f"  - 벤치마크 대비 부진 감지, 텔레그램 알림 전송 시도:\n{result['message']}")
    else:
        print(f"  - 알림 없음 (gap_vs_sixty_forty_pct={comparison.get('gap_vs_sixty_forty_pct')})")
    print(f"[{datetime.now()}] champion_benchmark_gap_job 종료")


def champion_earnings_reminder_job() -> None:
    """챔피언 전략 새틀라이트 보유종목 중 향후 5거래일 이내 실적 발표가 있으면 텔레그램으로
    미리 알린다 (2026-09-18 추가). 코어는 전부 ETF라 개별 기업 실적이 없으므로 새틀라이트만
    대상이다 — core.champion_strategy.check_and_notify_upcoming_earnings 참고.
    """
    if not is_enabled("champion_earnings_reminder"):
        print(f"[{datetime.now()}] champion_earnings_reminder_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    print(f"[{datetime.now()}] champion_earnings_reminder_job 시작")
    result = check_and_notify_upcoming_earnings()
    if result["notified"]:
        print(f"  - 실적 발표 예정 감지, 텔레그램 알림 전송 시도:\n{result['message']}")
    else:
        print(f"  - 알림 없음 (upcoming={result['upcoming']})")
    print(f"[{datetime.now()}] champion_earnings_reminder_job 종료")


def champion_alpha_decay_job() -> None:
    """챔피언 전략(코어+새틀라이트) 백테스트 성과가 최근 이탈(감쇠)했는지 체크해 텔레그램으로
    알린다 (2026-09-19 추가). core.champion_strategy.check_and_notify_champion_alpha_decay가
    실제 계산/판정/dedupe/알림을 전부 담당한다.
    """
    if not is_enabled("champion_alpha_decay"):
        print(f"[{datetime.now()}] champion_alpha_decay_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    print(f"[{datetime.now()}] champion_alpha_decay_job 시작")
    result = check_and_notify_champion_alpha_decay()
    decay = result["decay"]
    if result["notified"]:
        print(f"  - 알파 감쇠 감지, 텔레그램 알림 전송 시도:\n{result['message']}")
    else:
        print(f"  - 알림 없음 (is_decayed={decay['is_decayed']}, decay_ratio={decay['decay_ratio']})")
    print(f"[{datetime.now()}] champion_alpha_decay_job 종료")


def champion_weekly_report_job() -> None:
    """챔피언 전략의 이번 주 상태를 HTML 보고서로 만들어 텔레그램 문서로 전송한다 (2026-09-18
    추가). core.champion_strategy.send_weekly_report가 실제 조립/전송을 담당한다.
    """
    if not is_enabled("champion_weekly_report"):
        print(f"[{datetime.now()}] champion_weekly_report_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
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
    if not is_enabled("fred_indicator_prewarm"):
        print(f"[{datetime.now()}] fred_indicator_prewarm_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
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
    if refreshed == 0:
        # 하나도 못 받았으면 API 키/네트워크 문제다 — 이 잡은 예외를 삼키므로 실행 이력에 실패로 직접 남긴다.
        report_job_failure("fred_indicator_prewarm", f"FRED 지표 {len(series_ids)}개를 하나도 갱신하지 못함(API 키/네트워크 확인)")


def data_integrity_check_job() -> None:
    """야간 데이터 무결성 체크 (2026-09-19 추가).

    core.data_integrity.run_integrity_checks()가 실제 검사(가격 이상치/FRED 캐시 stale/뉴스
    다이제스트 파싱 오류)를 전부 담당한다 — 이 잡은 호출하고 결과를 텔레그램으로 알리기만 한다.
    다른 champion_* 잡들과 동일한 철학: anomalies가 비어있으면("이상 없음") 알림을 보내지 않는다
    (매일 밤 "이상 없음" 스팸 방지). 텔레그램 설정이 없으면 send_message가 조용히 False를 반환할
    뿐 예외는 나지 않는다.
    """
    if not is_enabled("data_integrity_check"):
        print(f"[{datetime.now()}] data_integrity_check_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    from core.data_integrity import (
        CROSSCHECK_NIGHTLY_MAX_SYMBOLS,
        crosscheck_priority_tickers,
        format_anomaly_telegram_message,
        mark_crosscheck_alerted,
        price_crosscheck_enabled,
        route_crosscheck_anomalies,
        run_integrity_checks,
    )

    print(f"[{datetime.now()}] data_integrity_check_job 시작")
    # 2026-09-25: Alpaca 키가 있을 때만 가격 교차 대조(core.price_crosscheck)를 켠다. 키가 없으면(Codespace)
    # 예전과 똑같이 인자 없이 호출한다. 대상은 챔피언 코어·위성 보유+SPY 중 최대 N개.
    if price_crosscheck_enabled():
        cross_tickers = crosscheck_priority_tickers()
        print(f"  - Alpaca 가격 교차 대조 켬: {len(cross_tickers)}개 종목(상한 {CROSSCHECK_NIGHTLY_MAX_SYMBOLS})")
        result = run_integrity_checks(
            enable_price_crosscheck=True, crosscheck_tickers=cross_tickers,
            crosscheck_kwargs={"max_symbols": CROSSCHECK_NIGHTLY_MAX_SYMBOLS})
    else:
        result = run_integrity_checks()
    print(f"  - 체크 {len(result['checks'])}건, 이상 {len(result['anomalies'])}건")
    for a in result["anomalies"]:
        print(f"    · [{a['severity']}] {a['check']}: {a['detail']}")
    # 교차 대조 finding 은 major 불일치·분할 의심만, 그것도 처음 보는 (종목, 날짜)만 텔레그램으로 보낸다.
    # 나머지 교차 대조 경고(조회 불가 등)는 로그에만 남긴다. 기존 세 체크의 알림 규칙은 그대로다.
    routed = route_crosscheck_anomalies(result["anomalies"])
    if routed["crosscheck_suppressed"]:
        print(f"  - 교차 대조: 이미 알린 불일치 {len(routed['crosscheck_suppressed'])}건은 다시 알리지 않음")
    if routed["crosscheck_log_only"]:
        print(f"  - 교차 대조: 알림 대상이 아닌 경고 {len(routed['crosscheck_log_only'])}건(로그만)")
    to_send = routed["base"] + routed["crosscheck_new"]
    if to_send:
        sent = send_message(format_anomaly_telegram_message(to_send))
        if sent and routed["crosscheck_new"]:
            mark_crosscheck_alerted(routed["crosscheck_new"])
    else:
        print("  - 이상 없음 (알림 생략)")
    print(f"[{datetime.now()}] data_integrity_check_job 종료")


def daily_briefing_job() -> None:
    """오늘의 브리핑 (2026-09-19 추가).

    core.daily_briefing.send_daily_briefing()이 실제 조립·저장·전송을 전부 담당한다 — 이 잡은
    호출하고 결과를 출력만 한다. 00:00~00:22 블록의 다른 모든 챔피언 전략/데이터무결성 잡보다
    뒤에 실행되어야 그날 밤 갱신된 최신 데이터를 요약할 수 있다.
    """
    if not is_enabled("daily_briefing"):
        print(f"[{datetime.now()}] daily_briefing_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    from core.daily_briefing import send_daily_briefing

    print(f"[{datetime.now()}] daily_briefing_job 시작")
    result = send_daily_briefing()
    print(f"  - 브리핑 저장: {result['path']} (전송 {'성공' if result['sent'] else '실패/미설정'})")
    print(f"[{datetime.now()}] daily_briefing_job 종료")


def daily_news_digest_job() -> None:
    """무료 뉴스 API의 최근 24시간 메타데이터를 HTML과 Telegram으로 보고한다.

    야간 전체 스캔과 겹치지 않는 KST 07:30에 둔다. VM 여유가 없으면 API/Gemini 호출을
    강행하지 않고 다음 일일 실행으로 넘긴다.
    """
    if not is_enabled("daily_news_digest"):
        print(f"[{datetime.now()}] daily_news_digest_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
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
        report_job_failure("daily_news_digest", f"{type(exc).__name__}: {exc}")  # 예외를 삼키는 잡이라 이력에 직접 남긴다
    print(f"[{datetime.now()}] daily_news_digest_job 종료")


def candidate_ledger_record_job() -> None:
    """후보 shadow 원장 기록 (RES-01, 2026-09-22 추가, docs/CANDIDATE_LEDGER_SPEC.md).

    core.candidate_recorder.record_daily_candidates()가 발굴(stock_discovery)/섹터리더
    (sector_leaders)/챔피언 새틀라이트 세 소스의 오늘 후보 전체(채택+보류+거절)를 관측 전용으로
    동결 기록한다. 페이지 렌더링이 아니라 이 잡에서만 기록해야 같은 날 표본이 중복되지 않는다
    (core/candidate_recorder.py 모듈 docstring 참고). 주문 경로(core.paper_execution,
    scripts/champion_paper_trade.py)는 호출하지 않으며 이 잡의 결과는 주문에 영향을 주지 않는다.
    daily_news_digest_job(07:30) 이전, 00:22 data_integrity_check와 00:25 daily_briefing 다음
    비어있는 슬롯.
    """
    if not is_enabled("candidate_ledger_record"):
        print(f"[{datetime.now()}] candidate_ledger_record_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    from core.candidate_recorder import record_daily_candidates, summarize_recording

    print(f"[{datetime.now()}] candidate_ledger_record_job 시작")
    try:
        result = record_daily_candidates()
        print(f"  - {summarize_recording(result)}")
        if not result["ok"]:
            report_job_failure("candidate_ledger_record", "세 소스 모두 후보를 기록하지 못함")
    except Exception as exc:  # noqa: BLE001 - 다음 날 스케줄을 막지 않도록 기록만 남긴다.
        print(f"  - 후보 원장 기록 실패: {type(exc).__name__}: {exc}")
        report_job_failure("candidate_ledger_record", f"{type(exc).__name__}: {exc}")
    print(f"[{datetime.now()}] candidate_ledger_record_job 종료")


def candidate_ledger_outcome_update_job() -> None:
    """후보 shadow 원장의 만기 도래한 horizon 결과를 채운다 (RES-01, 2026-09-22 추가).

    core.candidate_ledger.update_forward_outcomes()는 멱등이며(이미 final/missing인 (후보, horizon)은
    다시 계산하지 않음), candidate_ledger_record_job(00:27)이 그날 후보를 기록한 직후 1분 뒤 실행해도
    당일 기록분은 아직 진입 전이라 영향이 없다 — 그 이전에 기록된 후보들의 만기가 채워진다.
    """
    if not is_enabled("candidate_ledger_outcome_update"):
        print(f"[{datetime.now()}] candidate_ledger_outcome_update_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    from core.candidate_ledger import update_forward_outcomes

    print(f"[{datetime.now()}] candidate_ledger_outcome_update_job 시작")
    try:
        result = update_forward_outcomes()
        print(
            f"  - 확정 {result['finalized']}건, 결측 {result['missing']}건, 보류 {result['pending']}건 "
            f"(검토 {result['n_decisions_examined']}건)"
        )
        if result.get("errors"):
            print(f"  - 오류 {len(result['errors'])}건: {result['errors'][:3]}")
    except Exception as exc:  # noqa: BLE001 - 다음 날 스케줄을 막지 않도록 기록만 남긴다.
        print(f"  - 후보 원장 성과 채움 실패: {type(exc).__name__}: {exc}")
        report_job_failure("candidate_ledger_outcome_update", f"{type(exc).__name__}: {exc}")
    print(f"[{datetime.now()}] candidate_ledger_outcome_update_job 종료")


def guidance_shadow_record_job() -> None:
    """가이던스 shadow 기록 (RES-04, docs/EARNINGS_GUIDANCE_EXPERIMENT_SPEC.md).

    core.guidance_shadow.record_guidance_shadow()가 오늘 위성 후보에 가이던스 신호 판정을 병행
    기록한다. 관측 전용이다 — 원전략의 실제 채택/보류와 주문 경로(core.paper_execution,
    scripts/champion_paper_trade.py)에는 아무 영향도 주지 않으며, 이 잡은 그 모듈을 import 도
    호출도 하지 않는다. candidate_ledger_outcome_update_job(00:28) 다음 빈 슬롯(00:30).
    """
    if not is_enabled("guidance_shadow_record"):
        print(f"[{datetime.now()}] guidance_shadow_record_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    from core.guidance_shadow import (
        NIGHTLY_FETCH_KWARGS,
        NIGHTLY_MAX_TICKERS,
        format_event_fetch_summary,
        record_guidance_shadow,
    )

    # 2026-09-25: 실제 SEC 조회를 켠다(fetch_events=True). 상한 — 티커 NIGHTLY_MAX_TICKERS 개, 소요 시간·SEC
    # 요청 수는 NIGHTLY_FETCH_KWARGS(티커 사이 소프트 상한). 하루 캐시 재사용·403 즉시 중단·티커별 실패 격리는
    # core.guidance_event_provider 가 담당하며, 조회가 실패해도 기록은 no_release 로 계속된다(잡이 죽지 않음).
    # User-Agent 는 SEC_EDGAR_USER_AGENT 환경변수(값은 출력하지 않는다).
    print(f"[{datetime.now()}] guidance_shadow_record_job 시작")
    try:
        result = record_guidance_shadow(
            fetch_events=True, max_tickers=NIGHTLY_MAX_TICKERS, fetch_kwargs=dict(NIGHTLY_FETCH_KWARGS))
        print(f"  - as_of={result.get('as_of')} 후보 {result.get('n_pool')}건, 삽입={result.get('inserted')}")
        summary = result.get("event_fetch_summary")
        print(f"  - SEC 가이던스 조회: {format_event_fetch_summary(summary)}")
        if summary and summary.get("n_observations_unknown"):
            print(f"    · unknown 사유: {summary.get('unknown_reason_counts')} "
                  f"(알려진 한계: {summary.get('known_limitation')})")
        if not result.get("ok"):
            report_job_failure("guidance_shadow_record", str(result.get("error") or "가이던스 shadow 기록 실패"))
    except Exception as exc:  # noqa: BLE001 - 다음 날 스케줄을 막지 않도록 기록만 남긴다.
        print(f"  - 가이던스 shadow 기록 실패: {type(exc).__name__}: {exc}")
        report_job_failure("guidance_shadow_record", f"{type(exc).__name__}: {exc}")
    print(f"[{datetime.now()}] guidance_shadow_record_job 종료")


def filing_veto_shadow_record_job() -> None:
    """공시 변경 veto shadow 기록 (docs/FILING_CHANGE_VETO_SPEC.md, 미동결·성과 미검증).

    core.filing_veto_shadow.record_filing_veto_shadow()가 오늘 위성 채택 종목에 filing_veto 판정을
    병행 기록한다. 관측 전용이다 — 판정이 hold 여도 실제 주문은 바뀌지 않으며, 이 잡은 주문 경로
    (core.paper_execution, scripts/champion_paper_trade.py)를 import 도 호출도 하지 않는다.
    guidance_shadow_record_job(00:30) 다음 빈 슬롯(00:32) — 두 shadow 가 같은 위성 원전략 계산을
    각자 수행하므로 같은 분에 겹치지 않게 띄운다.
    """
    if not is_enabled("filing_veto_shadow_record"):
        print(f"[{datetime.now()}] filing_veto_shadow_record_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    from core.filing_veto_shadow import record_filing_veto_shadow

    print(f"[{datetime.now()}] filing_veto_shadow_record_job 시작")
    try:
        result = record_filing_veto_shadow()
        print(
            f"  - as_of={result.get('as_of')} 후보 {result.get('n_candidates')}건, "
            f"veto_hold={result.get('n_held_by_veto')}, 노출={result.get('n_exposed')}"
        )
    except Exception as exc:  # noqa: BLE001 - 다음 날 스케줄을 막지 않도록 기록만 남긴다.
        print(f"  - 공시 veto shadow 기록 실패: {type(exc).__name__}: {exc}")
        report_job_failure("filing_veto_shadow_record", f"{type(exc).__name__}: {exc}")
    print(f"[{datetime.now()}] filing_veto_shadow_record_job 종료")


def account_snapshot_sync_job() -> None:
    """실계좌 스냅샷 + 목표 대비 이탈 감지 (2026-09-24 추가, core/account_sync.py 모듈 docstring 참고).

    core.account_sync.sync_paper_account()가 Alpaca paper 계좌의 /v2/account, /v2/positions 를 GET 으로만
    조회해 스냅샷을 저장하고, 챔피언 전략의 목표 비중과 실제 비중의 괴리를 계산한다. 조회 전용이다 —
    주문 경로(core.paper_execution, scripts/champion_paper_trade.py)를 import 도 호출도 하지 않으며
    이탈이 크게 나와도 주문은 만들어지지 않는다(정보 제공까지만). 보류 중인 슬리브
    (new_orders_allowed=False)는 "목표 0%"가 아니라 비교 불가(unknown)로 기록된다.

    API 키(ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET)가 없으면 조용히 건너뛰되 그 사유를 출력한다 —
    키 값 자체는 어디에도 남기지 않는다.

    시각(00:35 KST): 00:00~00:32 KST 야간 블록이 이미 가득 찼고(마지막이 00:32 filing_veto_shadow_record),
    그 다음 빈 슬롯이다. 그날 밤 챔피언 전략 계산이 모두 끝난 뒤 돌아야 같은 날 목표 비중과 비교된다.
    """
    if not is_enabled("account_snapshot_sync"):
        print(f"[{datetime.now()}] account_snapshot_sync_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    from core.account_sync import summarize_drift, sync_paper_account

    print(f"[{datetime.now()}] account_snapshot_sync_job 시작")
    try:
        result = sync_paper_account()
        if result.get("skipped"):
            print(f"  - 건너뜀: {result.get('reason')}")
        elif result.get("ok"):
            print(f"  - {summarize_drift(result['drift'])} (저장={result.get('saved')})")
            if result.get("errors"):
                print(f"  - 부분 오류 {len(result['errors'])}건: {result['errors'][:3]}")
        else:
            print(f"  - 계좌 스냅샷 실패: {result.get('reason')}")
            report_job_failure("account_snapshot_sync", str(result.get("reason") or "계좌 스냅샷 실패"))
    except Exception as exc:  # noqa: BLE001 - 다음 날 스케줄을 막지 않도록 기록만 남긴다.
        print(f"  - 계좌 스냅샷 실패: {type(exc).__name__}: {exc}")
        report_job_failure("account_snapshot_sync", f"{type(exc).__name__}: {exc}")
    print(f"[{datetime.now()}] account_snapshot_sync_job 종료")


def guru_holdings_sync_job() -> None:
    """거장 포트폴리오 자동 동기화 (2026-09-24 추가, core/guru_schedule.py 모듈 docstring 참고).

    기존에는 Streamlit 페이지의 "🔄 동기화" 버튼을 사용자가 거장 1명씩 눌러야만 갱신됐다.
    core.guru_schedule.sync_all_gurus()가 전체 거장을 순회하되 한 명이 실패해도 나머지를 계속
    진행하며, ARK(캐시 우드)는 매일 CSV 를 갱신하고 13F 거장은 SEC submissions 의 최신 accession 을
    먼저 비교해 새 분기 공시가 있을 때만 infoTable 을 파싱한다(멱등 — 같은 공시를 다시 파싱해도
    GuruHolding 에 중복 행이 쌓이지 않는다). 조회/기록 전용이며 주문 경로와는 무관하다.

    시각(12:00 KST): 00:00~00:32 KST 야간 블록이 이미 꽉 차 있는 데다, ARK 운용사가 일별 보유내역
    CSV 를 미국 동부 저녁(대략 20~21시 ET)에 공개하므로 12:00 KST(= 전날 22~23시 ET)에 돌려야
    가장 최근 거래일 파일을 받는다 — 00:3x KST 에 돌리면 한 거래일 더 오래된 파일을 받게 된다.
    """
    if not is_enabled("guru_holdings_sync"):
        print(f"[{datetime.now()}] guru_holdings_sync_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    from core.guru_schedule import summarize_sync, sync_all_gurus

    print(f"[{datetime.now()}] guru_holdings_sync_job 시작")
    try:
        result = sync_all_gurus()
        print(f"  - {summarize_sync(result)}")
        if result.get("n_failed") and not result.get("n_synced"):
            report_job_failure("guru_holdings_sync", "모든 거장 동기화 실패")
    except Exception as exc:  # noqa: BLE001 - 다음 날 스케줄을 막지 않도록 기록만 남긴다.
        print(f"  - 거장 포트폴리오 동기화 실패: {type(exc).__name__}: {exc}")
        report_job_failure("guru_holdings_sync", f"{type(exc).__name__}: {exc}")
    print(f"[{datetime.now()}] guru_holdings_sync_job 종료")


def alpaca_verification_bootstrap_job() -> None:
    """Alpaca paper API 가정 검증 자동 실행 (2026-09-24, core/alpaca_verification.py 모듈 docstring 참고).

    사용자는 폰으로만 작업해 VM 에서 검증 스크립트를 직접 돌리기 어렵다. 배포 직후 사람이 아무것도 하지 않아도
    첫 검증이 돌도록, 최근 7일 안에 전체 PASS 가 없을 때만 읽기 전용 검증 4개를 실행하고 요약을 텔레그램 1건으로
    보낸다(자가 치유). 이미 PASS 가 있으면 조용히 건너뛴다. 같은 실패는 3일 안에 반복 알리지 않는다.
    주문을 내는 --write 경로는 절대 실행하지 않는다. 키는 환경변수에서만 읽고 어디에도 값을 남기지 않는다.

    시각(00:40 KST): 00:00~00:35 야간 블록(마지막이 00:35 account_snapshot_sync) 다음 빈 슬롯.
    """
    if not is_enabled("alpaca_verification_bootstrap"):
        print(f"[{datetime.now()}] alpaca_verification_bootstrap_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    print(f"[{datetime.now()}] alpaca_verification_bootstrap_job 시작")
    try:
        from core.alpaca_verification import run_bootstrap_if_needed

        outcome = run_bootstrap_if_needed()
        print(f"  - {outcome}")
    except Exception as exc:  # noqa: BLE001 - 다음 날 스케줄을 막지 않도록 기록만 남긴다.
        print(f"  - Alpaca 검증 실패: {type(exc).__name__}: {exc}")
        report_job_failure("alpaca_verification_bootstrap", f"{type(exc).__name__}: {exc}")
    print(f"[{datetime.now()}] alpaca_verification_bootstrap_job 종료")


def cost_calibration_refresh_job() -> None:
    """거래비용 가정(5/10/25bp) 보정 갱신 — 관측 전용(주문 경로 미연결).

    core.cost_calibration 은 다른 작업에서 만드는 중이라 없을 수 있어 잡 안에서 lazy import 하고
    ImportError 도 다른 예외와 같이 report_job_failure 로 처리한다(스케줄러 기동·다른 잡에 영향 없음).
    시각(00:42 KST): 00:40 검증 잡 다음 슬롯.
    """
    if not is_enabled("cost_calibration_refresh"):
        print(f"[{datetime.now()}] cost_calibration_refresh_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    print(f"[{datetime.now()}] cost_calibration_refresh_job 시작")
    try:
        from core.cost_calibration import refresh_cost_calibration

        print(f"  - {str(refresh_cost_calibration())[:300]}")
    except Exception as exc:  # noqa: BLE001 - ImportError 포함, 다음 날 스케줄을 막지 않는다.
        print(f"  - 비용 보정 갱신 실패: {type(exc).__name__}: {exc}")
        report_job_failure("cost_calibration_refresh", f"{type(exc).__name__}: {exc}")
    print(f"[{datetime.now()}] cost_calibration_refresh_job 종료")


def variant_shadow_record_job() -> None:
    """전략 변형 shadow 기록 — 관측 전용(주문 경로 미연결).

    core.strategy_variants 는 다른 작업에서 만드는 중이라 없을 수 있어 lazy import + ImportError 격리.
    시각(00:44 KST): 00:42 비용 보정 다음 슬롯.
    """
    if not is_enabled("variant_shadow_record"):
        print(f"[{datetime.now()}] variant_shadow_record_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    print(f"[{datetime.now()}] variant_shadow_record_job 시작")
    try:
        from core.strategy_variants import record_variant_shadow

        print(f"  - {str(record_variant_shadow())[:300]}")
    except Exception as exc:  # noqa: BLE001
        print(f"  - 변형 shadow 기록 실패: {type(exc).__name__}: {exc}")
        report_job_failure("variant_shadow_record", f"{type(exc).__name__}: {exc}")
    print(f"[{datetime.now()}] variant_shadow_record_job 종료")


def paper_tracking_refresh_job() -> None:
    """paper 계좌 vs 챔피언 가상 원장 추적오차 (로드맵 P1, core/paper_tracking.py). 관측 전용.

    시각(00:46 KST): 00:35 계좌 스냅샷·00:12 원장 기록이 끝난 뒤, 00:44 변형 shadow 다음 슬롯.
    """
    if not is_enabled("paper_tracking_refresh"):
        print(f"[{datetime.now()}] paper_tracking_refresh_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    print(f"[{datetime.now()}] paper_tracking_refresh_job 시작")
    try:
        from core.paper_tracking import refresh_paper_tracking, summarize

        print(f"  - {summarize(refresh_paper_tracking())}")
    except Exception as exc:  # noqa: BLE001
        print(f"  - 추적오차 계산 실패: {type(exc).__name__}: {exc}")
        report_job_failure("paper_tracking_refresh", f"{type(exc).__name__}: {exc}")
    print(f"[{datetime.now()}] paper_tracking_refresh_job 종료")


def paper_auto_trade_job() -> None:
    """챔피언 계획 paper 자동 제출 (로드맵 P3, core/paper_auto_trade.py). **기본 꺼짐**.

    조건(최근 검증 PASS·개장일·중복 없음·계좌 정상·거래가능·총액 상한)을 모두 확인한 뒤에만 제출한다.
    시각(06:10 KST 화~토 = 미 동부 전날 16:10/17:10): 장 마감 뒤라 market/day 주문이 다음 개장 시가에 체결된다.
    """
    if not is_enabled("paper_auto_trade"):
        print(f"[{datetime.now()}] paper_auto_trade_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    print(f"[{datetime.now()}] paper_auto_trade_job 시작")
    try:
        from core.paper_auto_trade import format_summary, run_auto_round
        from core.telegram_notify import send_message

        res = run_auto_round()
        print(f"  - {res}")
        if res["status"] != "skipped" or res["reason"] not in ("market closed today", "already submitted today"):
            send_message(format_summary(res))
    except Exception as exc:  # noqa: BLE001
        print(f"  - paper 자동 주문 실패: {type(exc).__name__}: {exc}")
        report_job_failure("paper_auto_trade", f"{type(exc).__name__}: {exc}")
    print(f"[{datetime.now()}] paper_auto_trade_job 종료")


def strategy_research_report_job() -> None:
    """전략 변형 연구 보고서 작성 — 관측 전용, 주 1회(일요일 00:50 KST).

    매일 쓸 필요가 없다: shadow 표본은 하루 1건씩 천천히 쌓이고 판정에 주 단위 이상이 필요하다. 일요일 KST 은
    금요일 미국 장마감 기록(토요일 00:44 shadow)이 반영된 뒤이고 사용자가 주말에 검토하기 좋다.
    core.strategy_variants 는 lazy import + ImportError 격리.
    """
    if not is_enabled("strategy_research_report"):
        print(f"[{datetime.now()}] strategy_research_report_job 건너뜀 (비활성화됨 — 텔레그램 /processes 로 켤 수 있음)")
        return
    print(f"[{datetime.now()}] strategy_research_report_job 시작")
    try:
        from core.strategy_variants import write_research_report

        print(f"  - {str(write_research_report())[:300]}")
    except Exception as exc:  # noqa: BLE001
        print(f"  - 연구 보고서 작성 실패: {type(exc).__name__}: {exc}")
        report_job_failure("strategy_research_report", f"{type(exc).__name__}: {exc}")
    print(f"[{datetime.now()}] strategy_research_report_job 종료")


def main() -> None:
    init_db()

    scheduler = BlockingScheduler(timezone="America/New_York")
    # 잡이 끝날 때마다(성공/오류/놓침) scheduler_job_runs에 한 줄 기록 — 브리핑과 워치독이 '밤사이 정말 돌았나'를 판단한다.
    attach_job_run_listener(scheduler)
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
        champion_signal_alert_job,
        # market_snapshot_job(00:00)과 겹치지 않도록 10분 뒤로 offset.
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
        champion_ledger_record_job,
        # champion_correlation_snapshot_job(00:11) 다음 비어있는 슬롯.
        trigger=CronTrigger(hour=0, minute=12, timezone="Asia/Seoul"),
        id="champion_ledger_record",
        name="매일 한국시간 00:12 챔피언 전략 페이퍼 트레이딩 원장 기록",
        replace_existing=True,
    )
    scheduler.add_job(
        champion_benchmark_gap_job,
        # champion_ledger_record_job(00:12)이 그날 원장을 막 기록한 직후 1분 뒤 — 그 항목을 포함해 비교.
        trigger=CronTrigger(hour=0, minute=13, timezone="Asia/Seoul"),
        id="champion_benchmark_gap",
        name="매일 한국시간 00:13 챔피언 전략 60/40 벤치마크 대비 격차 텔레그램 알림",
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
        champion_alpha_decay_job,
        # champion_earnings_reminder_job(00:16) 다음 비어있는 슬롯. 전체기간(기본 8년) 백테스트를
        # 포함해 챔피언 잡 중 가장 무거운 계산이라 00:20(fred_indicator_prewarm)과는 겹치지 않게
        # 2분 여유를 둔다.
        trigger=CronTrigger(hour=0, minute=18, timezone="Asia/Seoul"),
        id="champion_alpha_decay",
        name="매일 한국시간 00:18 챔피언 전략 알파 감쇠(백테스트 성과 이탈) 체크 텔레그램 알림",
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
        daily_briefing_job,
        # data_integrity_check_job(00:22)까지가 00:00~00:22 KST 야간 블록의 마지막 잡이라, 그
        # 다음 빈 슬롯(00:25)에 둔다 — 이 잡은 다른 모든 챔피언 전략 잡의 결과를 요약하므로 반드시
        # 맨 마지막에 실행되어야 그날 밤 갱신된 데이터를 담는다.
        trigger=CronTrigger(hour=0, minute=25, timezone="Asia/Seoul"),
        id="daily_briefing",
        name="매일 한국시간 00:25 오늘의 브리핑 HTML Telegram 전송",
        replace_existing=True,
    )
    scheduler.add_job(
        candidate_ledger_record_job,
        # daily_briefing_job(00:25)까지가 00:00~00:25 KST 야간 블록이라, 그 다음 빈 슬롯(00:27)에
        # 둔다. 관측 전용이라 다른 잡의 순서에 영향받지 않는다.
        trigger=CronTrigger(hour=0, minute=27, timezone="Asia/Seoul"),
        id="candidate_ledger_record",
        name="매일 한국시간 00:27 후보 shadow 원장 기록 (RES-01, 관측 전용)",
        replace_existing=True,
    )
    scheduler.add_job(
        candidate_ledger_outcome_update_job,
        # candidate_ledger_record_job(00:27) 다음 슬롯 — 그날 막 기록한 후보는 아직 진입 전이라
        # 멱등하게 영향 없이, 이전에 기록된 후보들의 만기 결과만 채운다.
        trigger=CronTrigger(hour=0, minute=28, timezone="Asia/Seoul"),
        id="candidate_ledger_outcome_update",
        name="매일 한국시간 00:28 후보 shadow 원장 성과 채움 (RES-01)",
        replace_existing=True,
    )
    scheduler.add_job(
        guidance_shadow_record_job,
        # candidate_ledger_outcome_update_job(00:28) 다음 빈 슬롯 — 관측 전용이라 다른 잡의 순서에
        # 영향받지 않지만, 위성 원전략 계산을 다시 하므로 00:28 잡과 같은 분에 겹치지 않게 둔다.
        trigger=CronTrigger(hour=0, minute=30, timezone="Asia/Seoul"),
        id="guidance_shadow_record",
        name="매일 한국시간 00:30 가이던스 shadow 기록 (RES-04, 관측 전용)",
        replace_existing=True,
    )
    scheduler.add_job(
        filing_veto_shadow_record_job,
        # guidance_shadow_record_job(00:30) 다음 슬롯 — 두 shadow 가 각자 위성 원전략을 계산하므로
        # 2분 띄운다. 판정이 hold 여도 실제 주문 경로에는 영향이 없다.
        trigger=CronTrigger(hour=0, minute=32, timezone="Asia/Seoul"),
        id="filing_veto_shadow_record",
        name="매일 한국시간 00:32 공시 변경 veto shadow 기록 (관측 전용)",
        replace_existing=True,
    )
    scheduler.add_job(
        account_snapshot_sync_job,
        # 00:00~00:32 KST 야간 블록의 마지막 잡(00:32 filing_veto_shadow_record) 다음 빈 슬롯 —
        # 그날 밤 챔피언 전략 계산이 모두 끝난 뒤여야 같은 날 목표 비중과 실제 보유를 비교할 수 있다.
        trigger=CronTrigger(hour=0, minute=35, timezone="Asia/Seoul"),
        id="account_snapshot_sync",
        name="매일 한국시간 00:35 실계좌 스냅샷 + 목표 대비 이탈 감지 (조회 전용)",
        replace_existing=True,
    )
    scheduler.add_job(
        guru_holdings_sync_job,
        # 00:00~00:32 KST 야간 블록이 가득 찼고, ARK 일별 CSV 는 미국 동부 저녁(20~21시 ET)에
        # 공개되므로 12:00 KST(= 전날 22~23시 ET)가 "가장 최근 거래일 파일"을 받는 가장 이른 시각.
        trigger=CronTrigger(hour=12, minute=0, timezone="Asia/Seoul"),
        id="guru_holdings_sync",
        name="매일 한국시간 12:00 거장 포트폴리오 자동 동기화 (ARK 매일 / 13F 새 공시 시)",
        replace_existing=True,
    )
    scheduler.add_job(
        alpaca_verification_bootstrap_job,
        # 야간 블록 마지막 잡(00:35 account_snapshot_sync) 다음 빈 슬롯. 읽기 전용 검증만 하며 최근 7일 안에
        # PASS 가 있으면 즉시 종료한다(자가 치유: 배포 직후 사람 개입 없이 첫 검증이 돈다).
        trigger=CronTrigger(hour=0, minute=40, timezone="Asia/Seoul"),
        id="alpaca_verification_bootstrap",
        name="매일 한국시간 00:40 Alpaca paper 읽기 전용 검증 (7일 내 PASS 없을 때만)",
        replace_existing=True,
    )
    scheduler.add_job(
        cost_calibration_refresh_job,
        trigger=CronTrigger(hour=0, minute=42, timezone="Asia/Seoul"),
        id="cost_calibration_refresh",
        name="매일 한국시간 00:42 거래비용 보정 갱신 (관측 전용)",
        replace_existing=True,
    )
    scheduler.add_job(
        variant_shadow_record_job,
        trigger=CronTrigger(hour=0, minute=44, timezone="Asia/Seoul"),
        id="variant_shadow_record",
        name="매일 한국시간 00:44 전략 변형 shadow 기록 (관측 전용)",
        replace_existing=True,
    )
    scheduler.add_job(
        paper_tracking_refresh_job,
        trigger=CronTrigger(hour=0, minute=46, timezone="Asia/Seoul"),
        id="paper_tracking_refresh",
        name="매일 한국시간 00:46 paper 계좌 추적오차 (관측 전용)",
        replace_existing=True,
    )
    scheduler.add_job(
        paper_auto_trade_job,
        # 미 장 마감 뒤(화~토 KST = 월~금 ET). 기본 꺼짐 — /processes 로 켜야 제출한다.
        trigger=CronTrigger(day_of_week="tue-sat", hour=6, minute=10, timezone="Asia/Seoul"),
        id="paper_auto_trade",
        name="화~토 한국시간 06:10 챔피언 paper 자동 주문 (기본 꺼짐)",
        replace_existing=True,
    )
    scheduler.add_job(
        strategy_research_report_job,
        # 주 1회면 충분: shadow 표본이 하루 1건씩 쌓여 판정에 주 단위가 필요하다. 일요일 KST 는 금요일 미국
        # 장마감 기록이 반영된 뒤다.
        trigger=CronTrigger(day_of_week="sun", hour=0, minute=50, timezone="Asia/Seoul"),
        id="strategy_research_report",
        name="매주 일요일 한국시간 00:50 전략 변형 연구 보고서 (관측 전용)",
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
    print("전략 신호 변경을, 00:11 에는 보유종목 상관관계 스냅샷을, 00:12 에는 페이퍼 트레이딩")
    print("원장 기록을, 00:13 에는 그 원장의 60/40 벤치마크 대비 격차를, 00:15 에는 리밸런싱")
    print("예정일(및 칼라 헤지 롤)을, 00:16 에는 새틀라이트 실적 발표 예정을, 00:18 에는 챔피언")
    print("전략 알파 감쇠 여부를, 00:20 에는 FRED 거시지표(환율 등) 캐시를 미리 갱신하고, 00:22")
    print("에는 가격/FRED 캐시/뉴스 다이제스트 데이터 무결성을 체크해 이상 감지 시 텔레그램으로")
    print("알리며, 00:25 에는 그날 밤 결과를 모은 오늘의 브리핑 HTML을 텔레그램으로 전송합니다.")
    print("매일 한국시간 07:30에는 무료 뉴스 API 기반 티커별 HTML/Telegram 리포트를 보냅니다.")
    print("Ctrl+C 로 종료할 수 있습니다.")

    # 배포(=스케줄러 재시작) 직후 Alpaca 검증을 한 번 돌려, 00:40 을 기다리지 않고 관제 센터에서 결과를 보게 한다.
    # 잡 자체가 최근 7일 PASS 가 있으면 즉시 건너뛰고 같은 실패 알림은 3일간 반복하지 않으므로 재시작마다 반복돼도 안전하다.
    # 스케줄러 기동을 막지 않도록 백그라운드 스레드로 돌린다(테스트 중에는 돌리지 않음).
    if not os.getenv("PYTEST_CURRENT_TEST"):
        import threading

        threading.Thread(target=alpaca_verification_bootstrap_job, name="startup-alpaca-verify", daemon=True).start()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("스케줄러 종료.")


if __name__ == "__main__":
    main()
