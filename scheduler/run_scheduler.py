"""독립 실행 스케줄러: 매일 미국 장마감 후 관심 종목 50개를 스캔해 타점 알림을 보내고,
매주 일요일 저녁에는 Threads 추적 티커별 주간 AI 인사이트 리포트를 생성한다.

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

주의:
    - 이 스크립트는 core.* 를 프로젝트 루트 기준으로 임포트하므로, 아래처럼 sys.path에
      루트를 추가하는 부트스트랩이 필요하다 (app/Home.py 와 동일한 패턴).
"""

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from core.db import init_db
from core.notify import send_desktop_notification
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

    print("스케줄러 시작. 평일 16:30 에 관심 종목을 스캔하고, 매주 일요일 20:00 에 Threads 주간")
    print("인사이트 리포트를 생성합니다 (모두 America/New_York 기준).")
    print("Ctrl+C 로 종료할 수 있습니다.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("스케줄러 종료.")


if __name__ == "__main__":
    main()
