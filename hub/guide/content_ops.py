"""스크립트 · 자동 잡 보충 · 운영 안내 · 루틴 · 용어집 · 시작 안내.

2026-09-25 에 코드(scheduler/run_scheduler.py, core/*, scripts/*, deploy/*)와 docs/ 를 직접 읽고 대조해 작성했다.
코드에서 확인하지 못한 것은 적지 않았고, 문서와 코드가 다르면 코드를 따랐다.
"""

from hub.guide.schema import JobGuide, OpsSection, Routine, ScriptGuide, Term

V = "2026-09-25"

# 잡 함수가 예외를 내면 APScheduler 리스너가 실행 이력(scheduler_job_runs)에 error 로 남긴다(core/job_health.py).
# 이력은 화면 '오늘' 의 '운영 경고' 숫자, 오늘의 브리핑 '운영 상태', 아침 워치독 알림이 읽는다.
_HISTORY = "실패는 실행 이력에 남아 화면 '오늘' 의 '운영 경고' 숫자와 오늘의 브리핑 '운영 상태', 아침 워치독(09:05 KST) 텔레그램 알림으로 드러납니다."
_NOTHING = "따로 할 일 없음."

# ---------------------------------------------------------------------------
# 처음 보는 분을 위한 안내
# ---------------------------------------------------------------------------
START_HERE: tuple[str, ...] = (
    "이 시스템은 개인용 미국 주식 도우미입니다. 서버(Oracle VM) 한 대에서 스케줄러가 밤마다 시장 데이터를 계산해 두고, "
    "브라우저에서는 '퀀트 대시보드'(Streamlit 화면들)로, 폰에서는 텔레그램 알림·브리핑 파일로 그 결과를 봅니다. "
    "이 설명서(관제 센터의 /guide)는 화면 이름 그대로 무엇을 누르고 무엇을 읽는지 안내합니다.",

    "주문은 paper(모의투자) 전용입니다. 주문 코드(core/paper_execution.py)에는 실계좌 주소가 아예 없고 Alpaca paper 주소 하나만 있습니다. "
    "그리고 스케줄러는 주문 스크립트를 호출하지 않습니다. 주문은 사람이 scripts/champion_paper_trade.py 를 --submit 과 --confirm(주문 계획 지문)으로 "
    "직접 실행해야만 나갑니다. 그러니 밤에 오는 알림 때문에 저절로 주문이 나가는 일은 없습니다.",

    "화면과 알림의 '추천'은 신호이지 자동 주문이 아닙니다. 예를 들어 '챔피언 전략 신호 변경' 텔레그램은 추천 종목 목록이 어제와 달라졌다는 "
    "알림일 뿐이며, 그것을 따를지는 사람이 정합니다. '오늘' 화면도 주문 버튼이 없고 저장된 상태만 읽습니다.",

    "이 시스템은 대부분의 연구 결과를 '미입증'으로 표시합니다. 미입증은 '틀렸다'가 아니라 '성과가 좋아진다는 증거가 아직 없다'는 뜻입니다. "
    "shadow(관측 전용) 기록, 후보 원장, 가이던스·공시 실험, 전략 변형(hold-band)은 모두 표본을 쌓는 중이며 주문에 연결되어 있지 않습니다. "
    "'unknown' 도 약세 신호가 아니라 데이터가 부족해 판단을 보류한다는 뜻입니다. 좋은 숫자를 발견해도 그것을 검증된 개선으로 읽지 마세요.",

    "설명서 읽는 법: 맨 위 '상황별 사용법'에서 지금 하려는 일과 맞는 순서를 고르고, 막히면 '화면 안내'·'자동 잡'·'운영 도구'·'운영·알림'에서 "
    "해당 항목을 찾으세요. 각 항목 끝의 '확인일'이 코드와 대조한 날짜이며, 그 뒤에 코드가 바뀌었다면 '낡았을 수 있음' 표시가 붙습니다. "
    "낡은 표시가 있는 설명은 코드가 우선입니다. 자동 잡의 이름·시각·켜짐/꺼짐은 서버 설정에서 자동으로 가져오므로 항상 최신입니다.",

    "폰에서는 위쪽 검색창에 낱말(예: 알림, 백업, PIT, 주문)을 치면 그 낱말이 들어간 항목만 남고 자동으로 펼쳐집니다. "
    "지우면 전체가 다시 보입니다. 표(자동 잡)도 같은 검색창으로 걸러집니다. 용어가 낯설면 맨 아래 '용어집'에서 먼저 찾아보세요.",
)

# ---------------------------------------------------------------------------
# 자동 잡 보충 (이름·시각·설명은 레지스트리에서 자동 표시)
# ---------------------------------------------------------------------------
JOBS: tuple[JobGuide, ...] = (
    JobGuide(
        job_id="paper_tracking_refresh",
        where_to_see="화면 없음. data/cache/paper_tracking.json 파일",
        if_alert="따로 할 일 없음. 구간이 20개 미만이면 추적오차를 계산하지 않는 것이 정상입니다.",
        verified="2026-09-25",
    ),
    JobGuide(
        job_id="paper_auto_trade",
        where_to_see="텔레그램(제출 결과 1건). 기본값이 꺼짐이라 켜지 않았다면 아무 일도 일어나지 않습니다. 켜려면 텔레그램 /processes 에서 버튼을 누른 뒤 확인 버튼을 한 번 더 누르거나 '/processes on paper_auto_trade confirm' 을 보냅니다(확인 없이는 켜지지 않음).",
        if_alert="제출이 건너뛰어졌다면 텔레그램에 사유가 옵니다(검증 미통과, 휴장일, 거래 불가 종목, 주문 총액 초과 등). 사유를 확인하고, 반복되면 이 잡을 끄세요('/processes off paper_auto_trade' 또는 버튼, 확인 없이 즉시).",
        verified="2026-09-25",
    ),
    JobGuide(
        "daily_watchlist_scan",
        "화면 '운용 알림'(관심 티커 리스트)의 알림 목록과 '읽지 않은 알림' 숫자, 화면 '오늘', 그리고 텔레그램. 조건 충족 종목이 있으면 텔레그램 요약 1건(🔔 관심종목 타점 발생 N건)이 오고, 충족 0건이면 오지 않습니다. 같은 종목·전략·기준일은 재실행해도 한 번만 보냅니다. "
        "관심종목이 하나도 없으면 아무것도 하지 않습니다. 화면의 '지금 스캔 실행' 버튼은 같은 함수를 수동으로 돌립니다.",
        "충족 알림은 '전략의 신규 진입 조건을 만족했다'는 신호이지 주문이 아닙니다. 보고 싶으면 '운용 알림'에서 확인하고 '전체 읽음 처리'를 누르면 됩니다. "
        "텔레그램 전송이 실패하면 알림 로그 기록은 그대로 남고 실패가 실행 이력에 남으며, 다음 실행 때 같은 충족 건을 다시 보내 봅니다. " + _HISTORY,
        V,
    ),
    JobGuide(
        "weekly_threads_report",
        "화면 'Threads 요약'의 주간 리포트. 저장된 글이 최근 7일에 없는 티커는 건너뛰고, 추적 티커가 없으면 그냥 끝납니다. 완료 알림(📝 주간 Threads 인사이트 리포트 생성 완료)은 텔레그램으로 1건 옵니다. 리포트 본문은 텔레그램으로 보내지 않으므로 화면에서 읽습니다.",
        "요약은 GEMINI_API_KEY 가 없거나 API 호출이 실패하면 '요약을 생성하지 못했다'는 문구가 저장됩니다(예외 없이 끝남). 그런 문구가 보이면 VM 의 .env 에 그 키 이름이 있는지 확인하세요. " + _HISTORY,
        V,
    ),
    JobGuide(
        "daily_market_snapshot",
        "화면 '시장 진단'의 '시장 국면 / 섹터 강도'·'코스톨라니 달걀 이론' 섹션과 화면 '오늘'의 시장 국면. 이 잡이 안 돌아도 화면이 첫 방문자에게 그 자리에서 재계산하는 자체 폴백이 있고, "
        "GitHub Actions(nightly_market_snapshot)가 커밋해 두는 스냅샷 JSON 도 폴백으로 쓰입니다.",
        "시장 국면이 'unknown' 이면 약세가 아니라 데이터 부족으로 판단을 보류한다는 뜻입니다. 그 외에는 " + _NOTHING + " " + _HISTORY,
        V,
    ),
    JobGuide(
        "champion_signal_alert",
        "텔레그램 '🏆 챔피언 전략 신호 변경 (날짜)' 메시지(코어 top4·시장필터·새틀라이트 보유종목이 어제 저장 상태와 달라졌을 때만 옴, 처음 실행 때는 '최초 신호 기록'). 상세는 화면 '챔피언 전략'과 '오늘'.",
        "추천이 바뀌었다는 알림일 뿐 자동 주문이 아닙니다. '챔피언 전략'에서 어떤 종목이 바뀌었는지 확인하고, 실제로 따르려면 루틴 '주문을 내기 전 체크리스트(paper 전용)'를 따르세요. 텔레그램 설정이 없으면 알림만 조용히 생략됩니다.",
        V,
    ),
    JobGuide(
        "champion_correlation_snapshot",
        "화면 '챔피언 전략'의 보유종목 상관관계 섹션(이력). 알림은 없습니다. 보유종목이 2개 미만이면 그날은 저장하지 않고 건너뜁니다.",
        _NOTHING + " " + _HISTORY,
        V,
    ),
    JobGuide(
        "champion_ledger_record",
        "전용 화면은 없습니다(어느 Streamlit 화면도 이 원장을 읽지 않음). 'DB 의 챔피언 페이퍼 원장'에 하루 한 줄씩 쌓이며, 20영업일 이상 쌓이면 다음 잡(champion_benchmark_gap)이 읽습니다. 오늘자 항목이 이미 있으면 건너뜁니다.",
        "'추천 비중을 그대로 따랐다면'의 가상 수익 기록이지 실제 계좌 성과가 아닙니다. " + _NOTHING + " " + _HISTORY,
        V,
    ),
    JobGuide(
        "champion_benchmark_gap",
        "텔레그램 '📉 챔피언 전략, 60/40 벤치마크 대비 부진'. 원장 누적 수익이 60/40(SPY/TLT)보다 5%p 이상 뒤처질 때만 오며, 원장이 20영업일 미만이면 비교 자체를 건너뜁니다(알림 없음).",
        "표본이 짧은 가상 원장 기준의 알림이라 이것 하나로 전략을 바꾸지 말고, 화면 '챔피언 전략'과 '챔피언 최적화'에서 성과를 함께 확인하세요.",
        V,
    ),
    JobGuide(
        "champion_rebalance_reminder",
        "텔레그램 '⏰ 챔피언 전략 리밸런싱 예정 알림'(리밸런싱 하루 전, 같은 날짜는 한 번만). 코어 리밸런싱은 매월 첫 거래일, 새틀라이트는 1월·7월 첫 거래일이며 코어와 겹치면 칼라 헤지 롤 예정도 같은 메시지에 붙습니다.",
        "'내일이 첫 거래일인가'를 달력 요일로 근사하므로 거래소 휴장일이 월초에 끼면 며칠 틀릴 수 있습니다. 알림이 와도 자동으로 무언가 실행되지 않으며, 리밸런싱 뒤의 신호는 화면 '챔피언 전략'에서 확인합니다.",
        V,
    ),
    JobGuide(
        "champion_earnings_reminder",
        "텔레그램 '📅 챔피언 전략 새틀라이트 실적 발표 예정'(새틀라이트 보유종목 중 5거래일 이내 실적 발표가 있을 때만, 같은 종목·실적일은 한 번만). 화면 '챔피언 전략'의 실적 발표 예정 섹션과 오늘의 브리핑에도 나옵니다. 코어는 전부 ETF라 대상이 아닙니다.",
        "실적 발표 전후 변동이 커질 수 있다는 예고입니다. 해당 종목을 계속 보유할지는 사람이 판단하는 일이며 자동 조치는 없습니다.",
        V,
    ),
    JobGuide(
        "champion_alpha_decay",
        "텔레그램 '⚠️ 챔피언 전략 알파 감쇠 감지'(전체기간 대비 최근 6개월 백테스트 성과가 이탈했을 때만, 감쇠가 계속되는 동안 매일 다시 알리지 않음). 오늘의 브리핑에도 감쇠 섹션이 있습니다.",
        "'이 전략을 계속 믿어도 되는가'를 점검하라는 신호입니다. 바로 전략을 바꾸지 말고 화면 '챔피언 전략'의 백테스트와 '챔피언 최적화'로 최근 성과를 확인하세요. 무거운 백테스트를 매일 다시 돌리는 잡이라 서버가 느려 보일 수 있습니다.",
        V,
    ),
    JobGuide(
        "champion_weekly_report",
        "텔레그램 문서 '🏆 챔피언 전략 주간 보고'(HTML 파일, 코어·새틀라이트 현황과 최근 상관관계). VM 의 data/cache/champion_reports 에 저장되고, 화면 '챔피언 전략'의 '지금 주간 보고 보내기' 버튼으로 수동 전송할 수도 있습니다.",
        "전송에 실패하면 로그에 '전송 실패/미설정'으로 남고, 텔레그램 토큰·채팅 설정이 없으면 파일만 저장됩니다. 그 외에는 " + _NOTHING,
        V,
    ),
    JobGuide(
        "fred_indicator_prewarm",
        "화면 '시장 진단'의 '경제지표'와 '경기 사이클 / 섹터 로테이션'(원/달러 환율 등)이 빨리 열리도록 캐시를 데워 둘 뿐 별도 결과는 없습니다.",
        "지표 하나가 실패해도 나머지는 계속합니다. 하나도 못 받으면 실행 이력에 실패로 남으니(FRED_API_KEY 또는 네트워크 문제), VM 의 .env 에 FRED_API_KEY 이름이 있는지 확인하세요. " + _HISTORY,
        V,
    ),
    JobGuide(
        "data_integrity_check",
        "텔레그램 '🚨 데이터 무결성 이상 감지 (critical n건, warning n건)'(이상이 있을 때만 옴, 정상일 땐 알림 없음)과 오늘의 브리핑의 데이터 이상 섹션. 읽기 전용 검사입니다.",
        "메시지의 항목은 가격 이상값·중복, FRED 캐시 비어 있음·오래됨, 뉴스 다이제스트 오류 등입니다. 챔피언 신호에 쓰이는 가격에 대한 이상이라면 원인이 확인될 때까지 그날의 신호는 참고만 하세요. critical 이 반복되면 개발 요청(텔레그램 지시)으로 원인을 보게 하면 됩니다. "
        "2026-09-25부터 VM 에 Alpaca 키가 있으면 보유 종목·SPY(최대 10개)의 yfinance 가격을 Alpaca 일봉과도 대조합니다. 이 대조에서는 '종가 큰 불일치'와 '분할 조정 의심'만, 처음 보는 종목·날짜일 때 한 번만 메시지에 들어갑니다. 어느 쪽 가격이 옳은지는 판정하지 않으니(무료 Alpaca 시세는 거래소 하나 기준) 원인을 확인하기 전까지 참고만 하세요. 조회 불가 같은 나머지 교차 대조 결과는 스케줄러 로그에만 있습니다.",
        V,
    ),
    JobGuide(
        "daily_briefing",
        "텔레그램 문서 '📋 오늘의 브리핑'(HTML 한 장, 00:25 KST). VM 의 data/cache/champion_reports/daily_briefing_날짜.html 로도 저장됩니다. 맨 위 상태 줄에 데이터 이상·알파 감쇠·운영 문제 개수가 나옵니다.",
        "운영 문제(잡 실패, 백업 문제)가 있으면 '운영 상태' 섹션이 맨 위에 빨강으로 나오고 없으면 맨 아래에 한 줄 요약이 옵니다. 붉은 항목이 있으면 그 잡·백업 항목을 '운영·알림'의 확인 순서대로 보세요. 이 브리핑이 아예 안 오면 아침 워치독이 알립니다.",
        V,
    ),
    JobGuide(
        "daily_news_digest",
        "텔레그램 요약 메시지 + '📰 일일 티커 뉴스 리서치 전체 보고서' HTML 첨부(07:30 KST), 화면 '뉴스 리서치', 텔레그램 명령 /news 또는 /news 티커. 연구용 정보이며 매매 권고가 아닙니다.",
        "서버 여유(메모리·CPU)가 부족하면 그날은 건너뛰고 실패로 치지 않습니다. 뉴스 수집·요약이 예외로 실패하면 실행 이력에 '실패'로 남습니다. " + _HISTORY,
        V,
    ),
    JobGuide(
        "candidate_ledger_record",
        "전용 화면은 없습니다. DB 의 후보 shadow 원장(RES-01)에 쌓이고, 요약은 scripts/candidate_ledger_update.py 로 출력해 볼 수 있습니다. 종목 발굴·섹터 리더·챔피언 새틀라이트 세 소스의 오늘 후보(채택+보류+거절)를 기록합니다.",
        "관측 전용이라 주문에 영향이 없고 결과는 '미입증'이 기본입니다. 세 소스를 모두 기록하지 못했을 때만 실행 이력에 실패가 남습니다. 그 외에는 " + _NOTHING,
        V,
    ),
    JobGuide(
        "candidate_ledger_outcome_update",
        "전용 화면은 없습니다. 이미 기록된 후보의 만기 도래한 horizon(며칠 뒤 결과)만 채우며, 결과는 scripts/candidate_ledger_update.py 의 요약 출력에서 봅니다.",
        _NOTHING + " 결과가 채워졌다는 것이 곧 성과 개선의 증거는 아닙니다. " + _HISTORY,
        V,
    ),
    JobGuide(
        "guidance_shadow_record",
        "전용 화면은 없습니다(DB 에 병행 기록). 오늘 새틀라이트 후보에 실적 가이던스 판정을 옆에 적어 둘 뿐이며 원전략의 채택·보류와 주문은 바뀌지 않습니다.",
        _NOTHING + " 2026-09-25부터 매일 밤 SEC 에 실제로 조회합니다(최대 20종목, 요청 약 300회·5분 상한, 하루 캐시, 403 이면 즉시 중단). 스케줄러 로그의 'SEC 가이던스 조회:' 줄에 조회 종목 수·실패 수·관측 수·방향 판정 수 대 판단 불가 수·SEC 요청 수가 나옵니다. 분기 가이던스는 대부분 판단 불가로 나오는 것이 알려진 한계입니다. SEC 가 막혀도 잡은 실패로 끝나지 않고 그날 기록이 '발표 없음'으로 남으니, 이 줄에 '접근 차단'이 보이면 VM .env 에 SEC_EDGAR_USER_AGENT 이름이 있는지 확인하세요. 추출 정확도(G0)를 사람이 확인하기 전까지 성과는 미검증입니다. 기록 자체의 실패는 실행 이력에 남습니다.",
        V,
    ),
    JobGuide(
        "filing_veto_shadow_record",
        "전용 화면은 없습니다(DB 에 병행 기록). 오늘 새틀라이트 채택 종목에 공시 변경 veto 판정을 기록하며, veto 가 hold 로 나와도 실제 주문은 바뀌지 않습니다.",
        _NOTHING + " 스펙이 아직 동결되지 않았고 성과는 미검증입니다. " + _HISTORY,
        V,
    ),
    JobGuide(
        "account_snapshot_sync",
        "전용 화면은 없습니다(어느 Streamlit 화면도 읽지 않음). DB 에 Alpaca paper 계좌 스냅샷과 목표 비중 대비 이탈이 저장되며, 지금 바로 보려면 scripts/sync_paper_account.py --no-save 를 실행하세요. 키가 없으면 그 사유를 로그에 남기고 건너뜁니다.",
        "조회 전용이며 이탈이 커도 주문은 만들어지지 않습니다. 보류(hold) 슬리브는 '목표 0%'가 아니라 '비교 불가'로 기록됩니다. 실패하면 실행 이력에 남으니 그때는 VM .env 의 ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET 이름이 있는지 확인하세요.",
        V,
    ),
    JobGuide(
        "alpaca_verification_bootstrap",
        "텔레그램 '[Alpaca paper 검증] 전체 PASS (4/4 PASS)' 같은 요약 1건과 VM 의 data/verification/alpaca_날짜_시각.json(UTC 기준 파일명). 최근 7일 안에 전체 PASS 가 있으면 조용히 건너뜁니다.",
        "FAIL 은 응답이 코드 가정과 달랐다는 뜻(해당 모듈 수정 필요), UNEXPECTED 는 판정 불가(인증·네트워크·구독 등급 등)입니다. 같은 실패는 3일 안에 다시 알리지 않습니다. "
        "'키가 없어 건너뜀' 메시지면 VM .env 에 키 이름이 없다는 뜻입니다. FAIL 이 하나라도 있는 동안은 champion_paper_trade.py --submit 을 쓰지 마세요. 전체 PASS 여도 읽기 전용 범위뿐이며 중복 주문 방지는 미검증입니다.",
        V,
    ),
    JobGuide(
        "cost_calibration_refresh",
        "전용 화면은 없습니다. VM 의 data/cache/cost_calibration.json 을 갱신합니다. Alpaca paper 체결 표본이 30건 미만이면 대표값을 만들지 않고 'insufficient_sample' 로 남깁니다(값을 지어내지 않음).",
        "관측 전용이라 주문 경로와 백테스트 비용 가정(5/10/25bp)은 자동으로 바뀌지 않습니다. " + _NOTHING + " " + _HISTORY,
        V,
    ),
    JobGuide(
        "variant_shadow_record",
        "전용 화면은 없습니다. 챔피언 코어의 변형(baseline 과 hold-band)이 오늘 어떤 목표 집합을 냈을지를 병행 기록하고 상태는 VM 의 data/cache/strategy_variants_state.json 에 저장됩니다. 시장필터가 unknown 인 날은 기록하지 않습니다.",
        "관측 전용이며 원전략의 실제 결정은 바뀌지 않습니다. 성과 개선은 미검증입니다. " + _HISTORY,
        V,
    ),
    JobGuide(
        "strategy_research_report",
        "전용 화면은 없습니다. 일요일마다 VM 의 data/reports/strategy_research_날짜.md 와 .json 을 만듭니다(텔레그램으로는 보내지 않음). 파일은 /cat 명령이나 브라우저 코드 스페이스에서 열어 봅니다.",
        "성과 개선을 주장하지 않는 관측 보고서입니다(표본이 부족하거나 PIT 미인증이면 항상 '미입증'). " + _NOTHING + " " + _HISTORY,
        V,
    ),
    JobGuide(
        "guru_holdings_sync",
        "화면 '거장 포트폴리오'의 '거장 포트폴리오' 탭(마지막 자동 동기화·다음 예정 시각 표시). 새로 편입되거나 전량 청산된 종목이 있으면 텔레그램으로 요약 1건이 옵니다. ARK 는 매일, 13F 거장은 새 분기 공시가 있을 때만 갱신됩니다.",
        "한 명이 실패해도 나머지는 계속하며, 전원 실패일 때만 실행 이력에 실패가 남습니다. 13F 는 분기 지연 데이터라 '지금 보유'가 아닙니다. " + _NOTHING,
        V,
    ),
)

# ---------------------------------------------------------------------------
# 운영 도구(scripts/ 와 deploy/)
# ---------------------------------------------------------------------------
_KEYRUN = (
    "sudo systemd-run --wait --collect --pipe -p User=quant -p WorkingDirectory=/opt/quant "
    "-p EnvironmentFile=/opt/quant/.env /opt/quant/.venv/bin/python "
)

SCRIPTS: tuple[ScriptGuide, ...] = (
    ScriptGuide(
        path="scripts/verify_alpaca_meta_news.py", name="Alpaca 거래 가능·캘린더·뉴스 응답 확인",
        when_to_run="Alpaca 뉴스와 거래 가능 여부 기능을 처음 쓰기 전에, 응답 형식이 가정과 맞는지 확인할 때(VM에서 한 번).",
        command="python scripts/verify_alpaca_meta_news.py",
        risk="읽기 전용",
        what_it_prints="AAPL·SPY는 거래 가능, 존재하지 않는 종목은 not_found로 나오는지, 휴장 캘린더와 뉴스 응답이 기대한 형식인지 한 줄씩 보여줍니다. 키가 없으면 안내만 하고 종료하며 키 값은 출력하지 않습니다. 종료 코드가 0이 아니면 가정이 어긋난 것이므로 그 결과를 알려 주세요.",
        verified="2026-09-25",
    ),
    ScriptGuide(
        path="scripts/news_event_study.py", name="뉴스 이벤트 연구 실행",
        when_to_run="특정 종목들의 뉴스 이후 수익률이 평소와 다른지 연구할 때(VM에서 한 번).",
        command="python scripts/news_event_study.py AAPL MSFT --start 2024-01-01 --end 2024-12-31",
        risk="파일/DB 쓰기",
        what_it_prints="결과를 data/research/news_event_study_*.json 에 저장합니다. 이벤트가 30건 미만이면 평균과 초과수익 대신 표본 부족으로 나옵니다. 뉴스의 좋고 나쁨은 판단하지 않고 거래비용도 반영하지 않으므로, 결과를 매매 신호로 쓰지 마세요.",
        verified="2026-09-25",
    ),
    ScriptGuide(
        "scripts/champion_paper_trade.py",
        "챔피언 전략 paper 주문 계획 만들기 / 제출",
        "챔피언 신호를 실제로 paper 계정에 반영해 보고 싶을 때. 먼저 --submit 없이 계획만 본 뒤, 계획이 마음에 들 때만 제출합니다. 루틴 '주문을 내기 전 체크리스트(paper 전용)'를 먼저 읽으세요.",
        "# 1) 계획만 보기(주문 없음)\n" + _KEYRUN + "scripts/champion_paper_trade.py\n"
        "# 2) 제출(paper 전용, 1)에서 나온 plan.fingerprint 값을 그대로 넣음)\n" + _KEYRUN + "scripts/champion_paper_trade.py --submit --confirm <계획의 fingerprint>",
        "주문 가능",
        "옵션은 --submit 과 --confirm 둘뿐입니다. 코드에서 확인한 사실: Alpaca paper 주소(paper-api.alpaca.markets)만 호출하고 실계좌 주소는 코드에 없습니다. "
        "--submit 은 --confirm 이 없으면 즉시 중단되고, 지문이 계획과 다르면 제출하지 않습니다. 출력의 core·satellite 는 추천 종목, plan.orders 는 낼 주문(시장가·당일, 매수는 금액 기준, 매도는 수량 기준, 매도 먼저), "
        "plan.fingerprint 가 지문, hold_reason 은 신규 주문 보류 사유입니다. 종목당 비중 25%·주문당 25,000달러 상한을 넘거나 25달러 미만 변동은 계획에서 빠지거나 오류가 납니다. "
        "코어(시장필터 unknown)·새틀라이트가 보류면 그 쪽 매수는 막히고 보유는 유지됩니다. 지문은 주문 목록에서 계산되므로 계획을 본 뒤 시장·보유가 바뀌면 달라져 제출이 거부될 수 있습니다(그때는 1)부터 다시). "
        "제출 결과의 reconcile_state 가 unresolved 면 결과가 확정되지 않은 것이니 Alpaca paper 대시보드의 Orders 에서 직접 확인하세요. 같은 회차 재시도는 같은 주문 ID 를 재사용하도록 설계됐지만 실제 Alpaca 응답 검증(--write)은 아직 하지 않았습니다. "
        "확인할 것: (1) VM 에 배포된 코드가 주문 게이트·회차 ID 가 들어 있는 버전인지(2026-09-24 인계 문서 기준 그 시점 VM 은 구버전이라 --submit 금지였음), (2) Alpaca 검증에 FAIL 이 없는지, (3) 열린 회차가 없는지(paper_run_admin.py list --status open).",
        V,
    ),
    ScriptGuide(
        "scripts/paper_run_admin.py",
        "paper 주문 실행 회차 조회·수동 종료",
        "주문 후 회차가 열린 채 남았을 때(조회 실패 등) 목록을 보거나, 정리해야 할 때. 새 주문을 내기 전에 열린 회차가 없는지 볼 때도 씁니다.",
        "# 열린 회차 목록(키 불필요)\n"
        "sudo -u quant /opt/quant/.venv/bin/python /opt/quant/scripts/paper_run_admin.py list --status open\n"
        "# 감사 로그\n"
        "sudo -u quant /opt/quant/.venv/bin/python /opt/quant/scripts/paper_run_admin.py audit\n"
        "# 수동 종료(브로커 조회를 위해 키 필요)\n" + _KEYRUN + "scripts/paper_run_admin.py close --run-id r00012 --reason \"사유\"",
        "파일/DB 쓰기",
        "list 는 --status open|closed|all, --limit, --json 옵션이 있고 audit 는 --run-id 로 좁힐 수 있습니다. close 는 회차 DB(data/paper_runs.db)에 종료를 기록할 뿐 주문을 내지 않습니다. "
        "브로커에 미종결 주문이 보이거나 조회할 수 없으면 종료를 거부합니다(종료 코드 2). --force 로만 강제 종료할 수 있는데, 종료 뒤 다음 제출은 새 회차·새 주문 ID 를 받으므로 "
        "브로커에 남은 옛 주문과 겹쳐 노출이 두 배가 될 수 있으니 먼저 Alpaca paper 대시보드에서 옛 주문을 정리해야 합니다. 사유(--reason)는 필수이며 감사 로그에 남습니다.",
        V,
    ),
    ScriptGuide(
        "scripts/verify_alpaca_paper_idempotency.py",
        "Alpaca paper 주문 멱등성 가정 검증",
        "자동 검증(alpaca_verification_bootstrap)이 PASS 를 내도 미검증으로 남는 '중복 주문 방지' 가정을 사람이 확인할 때. 기본(읽기 전용)은 자동 잡이 매일 돌리므로 보통 --write 실행이 목적입니다.",
        "# 읽기 전용(주문 없음)\n" + _KEYRUN + "scripts/verify_alpaca_paper_idempotency.py > ~/paper_verify_readonly.json\n"
        "# 쓰기 포함(읽기 전용이 PASS 일 때만): paper 계정에 SPY 1주 지정가 매수 1건을 냈다가 취소\n" + _KEYRUN + "scripts/verify_alpaca_paper_idempotency.py --write > ~/paper_verify_write.json",
        "주문 가능",
        "--write 를 주면 paper 계정에 SPY 1주 지정가($1.00, 시세보다 훨씬 낮아 체결되지 않음) 매수 1건을 내고 같은 client_order_id 로 재제출·조회·취소합니다. Alpaca paper 주소만 호출하며 주소를 바꾸는 옵션이 없고, "
        "주문 금액이 25달러를 넘게 만드는 값(--limit-price 등)은 도구가 거부합니다. --symbol, --limit-price, --output, --poll-tries, --poll-interval 옵션이 있고 --output 은 저장소의 data/ 밖이어야 합니다. "
        "쓰기 전 확인: 읽기 전용 실행이 PASS 인지, 열린 회차가 없는지, 계정이 paper 인지. 결과는 steps 별 PASS/FAIL/UNEXPECTED 이며 종료 코드 0/1/2(3=설정 오류)입니다. "
        "실행 중 끊기면 Alpaca paper 대시보드에서 client_order_id 가 qverify- 로 시작하는 주문이 남았는지 직접 확인해 취소하세요. FAIL 이 해소되기 전에는 champion_paper_trade.py --submit 을 쓰지 않습니다. "
        "읽기 전용이 PASS 여도 리포트의 idempotency_verified 는 false 입니다. 자세한 절차는 docs/PAPER_API_VERIFICATION_RUNBOOK.md.",
        V,
    ),
    ScriptGuide(
        "scripts/verify_alpaca_corporate_actions.py",
        "Alpaca 기업행동(분할·배당) 응답 스키마 검증",
        "Alpaca Corporate Actions 응답이 코드의 파싱 가정과 맞는지 사람이 확인하고 싶을 때(자동 검증 잡도 이 검사를 포함해 돌립니다).",
        _KEYRUN + "scripts/verify_alpaca_corporate_actions.py --no-cache --symbol AAPL",
        "읽기 전용",
        "알려진 사례를 조회해 PASS(기대한 기업행동과 필수 필드 확인), FAIL(못 찾았거나 필드 비어 있음: 파싱 가정이 틀렸을 수 있음), UNEXPECTED(조회 실패·모르는 필드)로 판정한 JSON 을 출력합니다. "
        "종료 코드 0=전부 PASS, 1=FAIL 있음, 2=UNEXPECTED. --no-cache 는 응답 캐시를 쓰지 않고, --symbol 은 모든 케이스의 심볼을 덮어씁니다. 주문·계좌 변경 API 는 건드리지 않고 키 값은 출력하지 않습니다.",
        V,
    ),
    ScriptGuide(
        "scripts/verify_price_crosscheck.py",
        "가격 교차검증(Alpaca vs yfinance) 리포트",
        "저장소 가격(yfinance 단일 소스)이 Alpaca 일봉과 크게 어긋나는지, Alpaca 가 분할 조정 가격을 주는지 확인하고 싶을 때.",
        _KEYRUN + "scripts/verify_price_crosscheck.py --symbols AAPL MSFT SPY --days 30 --no-cache",
        "읽기 전용",
        "심볼별 최근 종가 대조를 match / minor_diff / major_diff / missing / unavailable 로 집계한 JSON 을 출력합니다. --symbols(3~5개), --days, --no-cache, --skip-split-check 옵션이 있고 "
        "주문 URL 은 이 파일에 없으며 데이터 엔드포인트만 호출합니다(--no-cache 없이 실행하면 data/cache/alpaca 에 응답 캐시가 생김). 해석 주의: Alpaca 무료 티어는 IEX 피드라 거래량·종가가 전체 시장과 다를 수 있어 "
        "불일치는 '플래그'일 뿐 yfinance 가 틀렸다는 판정이 아니며, 2020년 구간이 비면 데이터 오류보다 구독 등급의 과거 데이터 한계일 가능성이 큽니다.",
        V,
    ),
    ScriptGuide(
        "scripts/sync_paper_account.py",
        "Alpaca paper 계좌 스냅샷 + 목표 대비 이탈 리포트",
        "실제 paper 계좌가 챔피언 목표 비중과 얼마나 벌어졌는지 지금 보고 싶을 때(스케줄러 잡 account_snapshot_sync 와 같은 함수).",
        "# 저장 없이 리포트만\n" + _KEYRUN + "scripts/sync_paper_account.py --no-save\n"
        "# DB 에 저장까지\n" + _KEYRUN + "scripts/sync_paper_account.py",
        "파일/DB 쓰기",
        "옵션은 --no-save 하나이며 이것을 주면 DB 에 저장하지 않습니다(안 주면 계좌 스냅샷을 DB 에 저장). 출력 JSON 의 summary 가 이탈 요약, drift 가 종목·슬리브별 이탈입니다. "
        "조회(GET) 전용이라 주문을 만들거나 내지 않으며, 보류 슬리브는 '목표 0%'가 아니라 비교 불가(unknown)로 표시됩니다. 종료 코드 0=성공, 1=조회 실패, 2=키 없음(건너뜀). credentials_present 는 키 존재 여부만 알려주고 값은 없습니다.",
        V,
    ),
    ScriptGuide(
        "scripts/reconcile_paper_fills.py",
        "paper 실체결 vs 예상 체결 대조(슬리피지)",
        "paper 계정에 체결이 쌓인 뒤, 실제 체결가가 예상과 얼마나 다른지(슬리피지) 보고 백테스트의 비용 가정(5/10/25bp)을 점검하고 싶을 때.",
        _KEYRUN + "scripts/reconcile_paper_fills.py --days 30 --reference-open",
        "읽기 전용",
        "GET 만 하며 주문 제출·취소·수정 코드가 없습니다. 옵션: --days(기본 30), --expectations(예상 체결 JSON 경로), --reference-open(예상가 없는 주문에 체결일 시가를 캐시에서 채움), --include-activities, --min-sample, --rows. "
        "출력은 JSON 하나이며 표본이 30건 미만이면 'insufficient_sample' 이 찍히고 대표 슬리피지를 주장하지 않습니다. 가정 비용과의 비교표는 차이만 보여줄 뿐 어느 쪽이 옳다는 판정이나 백테스트 결과 갱신은 하지 않습니다. "
        "종료 코드 0=정상, 2=일부 조회 실패, 3=설정 오류(키 없음 등).",
        V,
    ),
    ScriptGuide(
        "scripts/candidate_ledger_update.py",
        "후보 shadow 원장 갱신 + 채택 vs 보류 요약",
        "후보 원장(RES-01)이 얼마나 쌓였고 채택과 보류 중 어느 쪽이 나았는지 요약을 보고 싶을 때. 결과가 '미입증'인 것이 기본입니다.",
        "cd /opt/quant && sudo -u quant .venv/bin/python scripts/candidate_ledger_update.py --no-report\n"
        "cd /opt/quant && sudo -u quant .venv/bin/python scripts/candidate_ledger_update.py --strategy-version stock_discovery/v2 --json",
        "파일/DB 쓰기",
        "만기 도래한 horizon 결과를 DB 에 채운(갱신) 뒤 채택 vs 보류/거절 요약을 출력합니다. 옵션: --as-of 날짜, --strategy-version, --horizons, --no-report(요약 생략), --n-boot, --json. "
        "관측 전용이라 주문 경로를 호출하지 않으며, 출력 수치는 성과·승률 개선의 증거가 아닙니다. 판정 규칙상 표본 부족·PIT 미인증·결측 과다면 무조건 '미입증'이고 자동 채택·폐기는 없습니다(docs/CANDIDATE_LEDGER_SPEC.md).",
        V,
    ),
    ScriptGuide(
        "scripts/earnings_guidance_extraction_sample.py",
        "실적 가이던스 추출 표본 문서 생성(RES-04, 사람 검증용)",
        "사람이 원문과 대조(G0 검증)할 표본 문서를 새로 만들거나 갱신할 때. 사용자가 '사람 확인' 열을 채워야 RES-04 가 다음 단계로 갑니다.",
        "cd /opt/quant && sudo -u quant .venv/bin/python scripts/earnings_guidance_extraction_sample.py --history 3",
        "파일/DB 쓰기",
        "SEC EDGAR 에서 사전 고정된 기업 목록의 최근 8-K 실적 발표(Item 2.02)를 받아 docs/experiment_validation/earnings_guidance_extraction_sample.md 를 다시 씁니다(--out 으로 다른 경로, --history 로 직전 이력 개수, 기본 3). "
        "이 문서는 추출 정확도를 주장하지 않으며 '사람 확인' 열이 채워지기 전까지는 표본일 뿐입니다. SEC 가 403 으로 막으면 재시도하지 않고 중단하며, User-Agent 값은 어디에도 남기지 않습니다(환경변수 SEC_EDGAR_USER_AGENT 이름만 사용).",
        V,
    ),
    ScriptGuide(
        "scripts/filing_change_extraction_check.py",
        "공시(10-K) 변경 추출 점검(RES-05, 사람 검증용)",
        "기업 공시의 직전 동종 공시 대비 변경 추출이 잘 되는지 사람이 확인할 표본을 만들 때.",
        "cd /opt/quant && sudo -u quant .venv/bin/python -m scripts.filing_change_extraction_check --forms 10-K",
        "파일/DB 쓰기",
        "다섯 개 기업의 최근 공시 2개씩으로 섹션 추출 성공률과 diff 크기를 재고 docs/experiment_validation/filing_change_extraction_check.md 를 씁니다(--forms 로 10-K 등 지정, --out 으로 경로 변경, 사람 메모 아래 줄은 보존됨). "
        "DB 에는 쓰지 않고 주문과 무관하며 정확도 주장이 아닙니다. SEC 가 차단(403 등)하면 재시도 없이 그 사실만 기록하고 멈춥니다. 저장소 루트에서 모듈(-m) 방식으로 실행해야 합니다.",
        V,
    ),
    ScriptGuide(
        "deploy/backup_vm.py",
        "VM 백업 수동 실행",
        "백업을 지금 한 번 돌려 보고 싶을 때(원격 저장소를 처음 연결한 직후 확인, 복구 리허설 확인 등). 평소에는 매일 한국시간 06:30 에 타이머가 실행합니다.",
        "# 무엇이 백업될지 목록만(아무것도 쓰지 않음)\n"
        "sudo -u quant python3 /opt/quant/deploy/backup_vm.py --dry-run\n"
        "# 실제 백업\n"
        "sudo -u quant python3 /opt/quant/deploy/backup_vm.py",
        "파일/DB 쓰기",
        "옵션은 --dry-run 하나입니다. 요약에 '비공개 저장소 push 성공'이 나오면 원격에도 올라간 것이고, 원격 미설정이면 같은 디스크에만 있다는 뜻입니다. "
        "허용 목록 밖의 파일과 점(.) 폴더는 구조적으로 제외되고, 비밀처럼 보이는 파일은 격리되어 텔레그램으로 알립니다. 결과는 /opt/quant-backup/status.json 에 기록되어 브리핑·워치독이 읽습니다.",
        V,
    ),
    ScriptGuide(
        "deploy/watchdog.py",
        "워치독 수동 실행",
        "아침 워치독 결과를 지금 미리 보고 싶을 때(밤사이 작업·백업이 정상인지 점검).",
        "python3 /opt/quant/deploy/watchdog.py --dry-run",
        "읽기 전용",
        "--dry-run 을 주면 텔레그램 알림을 보내지 않고 결과만 출력합니다. 확인 항목: 최근 26시간 잡 기록 유무, error/missed 잡, 최신 브리핑 생성 여부, 백업 상태, 재부팅 필요 표시 14일 방치. "
        "문제가 있으면 종료 코드 1, 없으면 조용히 끝납니다(--dry-run 없이 실행하면 문제가 있을 때 텔레그램 발송).",
        V,
    ),
    ScriptGuide(
        "deploy/github_watch.py",
        "GitHub Actions 실패 감시 수동 실행",
        "GitHub 워크플로(야간 스냅샷, 업타임 등)가 실패했는지 지금 확인하고 싶을 때. 평소에는 15분마다 타이머가 돌며 새 실패만 텔레그램으로 알립니다.",
        "python3 /opt/quant/deploy/github_watch.py --dry-run",
        "읽기 전용",
        "--dry-run 은 알림도 상태 저장도 하지 않습니다(--limit 로 확인할 실행 수 지정). 토큰 없이 공개 저장소의 GitHub API 를 읽습니다. 첫 실행은 과거 실패를 쏟아내지 않고 현재 상태만 기록하며, "
        "실패했다가 다시 성공한 워크플로는 '복구됨'을 한 번 알립니다.",
        V,
    ),
    ScriptGuide(
        "deploy/set_code_server_password.sh",
        "코드 스페이스 로그인 비밀번호 바꾸기",
        "브라우저 코드 스페이스(code 주소)의 자동 생성 비밀번호를 외울 수 있는 것으로 바꾸고 싶을 때. 사람이 직접 터미널에서 실행해야 합니다.",
        "ssh -t quant-vm 'sudo bash /opt/quant/deploy/set_code_server_password.sh'",
        "서버 설정 변경",
        "비밀번호는 화면에 표시되지 않게 두 번 입력하며 명령줄·대화·로그에 남지 않습니다. 12자 이상, 영문·숫자·기호만 가능(공백·작은따옴표·한글 불가, 한/영 키가 한글 상태면 거절됨)이며 4자리 숫자 같은 것은 일부러 거절합니다. "
        "code-server 를 재시작하고 새 비밀번호로 실제 로그인이 되는지 확인해 안 되면 예전 설정으로 되돌립니다. 이 비밀번호 하나가 곧 VM 셸이므로 약한 것으로 바꾸지 마세요. 비밀번호 값은 어디에도 적지 마세요.",
        V,
    ),
    ScriptGuide(
        "deploy/set_backup_passphrase.sh",
        "비밀 암호화 백업의 passphrase 정하기(선택)",
        "로그인 파일·.env·토큰 같은 비밀까지 암호화해서 백업하고 싶을 때(기본은 비밀을 백업에서 완전히 제외). 사람이 직접 터미널에서 실행해야 합니다.",
        "ssh -t quant-vm 'sudo bash /opt/quant/deploy/set_backup_passphrase.sh'",
        "서버 설정 변경",
        "20자 이상이면 제한이 거의 없고 입력은 화면에 표시되지 않으며 저장 뒤 실제 암복호화 왕복까지 확인합니다. 다음 백업부터 비밀 파일이 암호화되어 함께 백업됩니다. "
        "중요: passphrase 는 VM 에만 저장되므로 VM 디스크가 사라지는 경우까지 대비하려면 같은 값을 사람이 따로(비밀번호 관리자 등에) 보관해야 하며, 잊으면 아무도 복구할 수 없습니다.",
        V,
    ),
)

INTERNAL_SCRIPTS: dict = {
    "scripts/nightly_market_snapshot_ci.py": (
        "사람이 실행하는 도구가 아니라 GitHub Actions 워크플로(nightly_market_snapshot, 매일 15:00 UTC)가 부릅니다. "
        "시장 국면·섹터 강도·코스톨라니 스냅샷을 계산해 data/*_snapshot_ci.json 으로 저장소에 커밋하고, VM 은 그 커밋을 자동 배포로 받아 폴백 데이터로 씁니다. "
        "결과는 화면 '시장 진단'과 '오늘'에서 봅니다."
    ),
}

# ---------------------------------------------------------------------------
# 운영 안내
# ---------------------------------------------------------------------------
OPS: tuple[OpsSection, ...] = (
    OpsSection(
        "telegram-commands",
        "텔레그램 명령과 뜻",
        (
            "텔레그램 봇(deploy/codex_telegram/runner.py)은 두 가지 일을 합니다. 하나는 '명령'으로 상태를 보거나 작업을 관리하는 것, 다른 하나는 일반 문장을 보내면 저장소 → Claude/Codex 버튼을 골라 서버에서 코드 작업을 시키는 것입니다. "
            "완료·접수 메시지에 답장(reply)하면 같은 프로젝트로 이어서 지시합니다. /help 는 전체 목록을 다시 보여줍니다.",
            "/processes 는 서버에 등록된 자동 잡 전체를 알림·연구·기록·유지보수 묶음별 메시지로 보여 줍니다(켜짐 ✅, 꺼짐 ⏸, 묶음마다 켜짐 개수). "
            "목록은 레지스트리(core/process_registry.py)에서 바로 읽으므로 새 잡이 생기면 자동으로 나타나고, /help 의 잡 개수도 실제 개수입니다. "
            "주문을 내는 잡(💸 표시, 현재 '챔피언 paper 자동 주문' 하나)은 켤 때 한 번 더 확인합니다. 버튼이나 '/processes on paper_auto_trade' 는 확인 요청만 보내고, "
            "확인 버튼을 누르거나 '/processes on paper_auto_trade confirm' 을 보내야 켜집니다. 끄기는 확인 없이 바로 됩니다.",
        ),
        (
            ("/help 또는 /start", "명령 목록을 보여줍니다."),
            ("/status", "최근 작업 8개의 상태와 현재 기본 실행 대상(claude 또는 codex)."),
            ("/queue", "대기·실행·차단(blocked) 중인 작업 전체."),
            ("/cancel 작업ID", "대기 중인 작업을 취소하거나 실행 중인 작업의 중지를 요청."),
            ("/retry 작업ID", "blocked 상태의 작업을 다시 시도하도록 예약."),
            ("/diff 작업ID", "그 작업이 실제로 커밋한 내용 요약."),
            ("/digest", "마지막 확인 이후 끝난 작업과 지금 대기·실행 중인 작업을 한눈에."),
            ("/usage", "최근 7일 사용량과 한도 도달 횟수."),
            ("/claude 또는 /codex", "기본 실행 대상을 바꿉니다. '/claude 지시' 처럼 뒤에 지시를 쓰면 그 작업만 그 대상으로."),
            ("/project quant", "다음 줄에 지시를 적어 Quant 를 바로 선택해 작업을 시킵니다."),
            ("/processes", "자동 잡 전체의 on/off 목록을 묶음별로 버튼과 함께 표시. 버튼을 누르면 켜고 끕니다. 끄면 그 잡은 '건너뜀'으로 돕니다."),
            ("/processes on 키, /processes off 키", "글자로 켜고 끄기(키는 목록에서 이름 아래 줄). 주문을 내는 잡은 'on 키 confirm' 까지 보내야 켜집니다."),
            ("/news 또는 /news XLK", "최신 티커 뉴스 요약. 원문 링크는 일일 HTML 이나 화면 '뉴스 리서치'에서."),
            ("/note 메모", "비공개 위치(서버의 notes 폴더)에 메모 저장. 사진·파일을 보내도 저장됩니다."),
            ("/progress 내용", "공개 저장소의 PROGRESS.md 에 바로 커밋·푸시합니다(공개 저장소이므로 민감한 내용 금지)."),
            ("/cat 경로 [줄수]", "저장소 파일의 끝부분 보기(예: /cat PROGRESS.md 30)."),
            ("/log [개수]", "최근 커밋 요약."),
            ("/repo", "서버 작업 폴더의 상태(HEAD, origin 과의 차이, 미커밋 파일)."),
            ("/idea 메모, /ideas, /ideas 비우기", "AI 를 부르지 않고 아이디어만 저장, 목록 보기, 전체 삭제."),
        ),
        V,
    ),
    OpsSection(
        "alert-kinds",
        "알림 종류와 읽는 법",
        (
            "알림은 대부분 텔레그램으로 옵니다. 정상일 때는 조용한 것이 원칙이라 '이상이 있을 때만' 오는 알림이 많습니다. 알림이 없다는 것과 알림이 안 온다는 것은 다르므로, "
            "일요일마다 워치독이 '주간 생존 신호'를 보냅니다. 일요일에 그 메시지가 오지 않으면 그 자체가 이상 신호입니다.",
            "관심종목 스캔(평일 장마감 후)은 조건 충족 종목이 있을 때만 텔레그램 요약 1건을 보내고(충족 0건이면 조용함), Threads 주간 리포트는 완료 알림 1건을 텔레그램으로 보냅니다. 자세한 내용은 화면 '운용 알림', 'Threads 요약'에서 보세요. 데스크톱 알림은 앱을 내 컴퓨터에서 직접 돌릴 때만 뜹니다.",
            "텔레그램 설정(봇 토큰·채팅 ID)이 없으면 텔레그램 알림은 조용히 생략됩니다(예외 없이 넘어감).",
        ),
        (
            ("🏆 챔피언 전략 신호 변경", "자동 잡 champion_signal_alert. 코어 top4·시장필터·새틀라이트 종목이 어제와 달라짐. 신호 변경일 뿐 주문이 아님."),
            ("⏰ 챔피언 전략 리밸런싱 예정 알림", "champion_rebalance_reminder. 코어(매월 첫 거래일)·새틀라이트(1월·7월 첫 거래일) 리밸런싱 하루 전(칼라 롤 예정 포함, 달력 근사)."),
            ("📅 챔피언 전략 새틀라이트 실적 발표 예정", "champion_earnings_reminder. 5거래일 이내 실적 발표 예정 종목."),
            ("⚠️ 챔피언 전략 알파 감쇠 감지", "champion_alpha_decay. 최근 6개월 백테스트 성과가 전체기간보다 이탈. 전략을 믿어도 되는지 점검하라는 신호."),
            ("📉 챔피언 전략, 60/40 벤치마크 대비 부진", "champion_benchmark_gap. 가상 원장이 60/40 보다 5%p 이상 뒤처짐(원장 20영업일 이상일 때만)."),
            ("🔔 관심종목 타점 발생 N건", "daily_watchlist_scan. 관심종목의 연결 전략 신규 진입 조건이 충족된 종목 요약(상위 10개와 '외 k건'). 충족 0건이면 오지 않음. 신호일 뿐 주문이 아님."),
            ("📝 주간 Threads 인사이트 리포트 생성 완료", "weekly_threads_report. 일요일 20:00 ET. 몇 개 티커의 리포트를 만들었는지만 알림. 본문은 화면 'Threads 요약'."),
            ("🚨 데이터 무결성 이상 감지", "data_integrity_check. critical/warning 개수와 항목별 설명."),
            ("📋 오늘의 브리핑 (HTML 파일)", "daily_briefing. 밤사이 결과를 한 장으로 모은 것. 맨 위 상태 줄과 붉은 '운영 상태'부터 읽기."),
            ("🏆 챔피언 전략 주간 보고 (HTML 파일)", "champion_weekly_report. 일요일 미국 저녁(20:20 ET)."),
            ("📰 일일 티커 뉴스 리서치", "daily_news_digest. 07:30 KST 요약 + HTML 첨부. 매매 권고가 아님."),
            ("[Alpaca paper 검증] 전체 PASS 등", "alpaca_verification_bootstrap. 읽기 전용 검증 결과 1건. FAIL/UNEXPECTED 는 어떤 단계 가정이 달랐는지 한 줄씩."),
            ("거장 보유 변동 요약", "guru_holdings_sync. 신규 편입·전량 청산이 있을 때만."),
            ("[자동배포] 성공/실패", "자동 배포 결과. 아래 '자동 배포' 절 참고."),
            ("[워치독] 밤사이 확인이 필요합니다 / 주간 생존 신호", "워치독. 아래 '워치독·헬스체크·업타임' 절 참고."),
            ("⚠️ [Quant VM] 디스크/메모리 사용률 초과, ✅ 복구됨", "VM 헬스체크. 기본 임계값 디스크 85%, 메모리 90%."),
            ("⚠️ 서비스이름.service 실패/재시작됨", "systemd 가 서비스(streamlit·scheduler·codex-telegram) 실패를 감지하면 자동으로 보냅니다."),
            ("백업 관련 알림", "백업 실패, 36시간 넘게 성공 없음, 원격 push 3일 넘게 실패, 복구 리허설 실패, 비밀 의심 파일 격리."),
        ),
        V,
    ),
    OpsSection(
        "backup",
        "백업: 무엇이 어디에 있고 어떻게 복구하나",
        (
            "매일 한국시간 06:30 에 deploy/backup_vm.py 가 서버 디스크에만 있는 것들을 백업합니다. (1) data/quant.db 를 sqlite 온라인 백업으로 일관된 사본으로, "
            "(2) 아직 GitHub 에 커밋되지 않은 파일 중 허용 목록(analysis/, docs/, .experiment-control/, PROGRESS.md, RESUME_NOTE.md, data/process_toggles.json 등) 아래의 것만 복사합니다. "
            "이미 GitHub 에 있는 파일은 복사하지 않습니다.",
            "비밀은 기본적으로 백업에서 완전히 제외됩니다. 점(.)으로 시작하는 폴더(인증 정보가 든 곳)는 허용 목록에 없어 구조적으로 빠지고, 허용 폴더 안이라도 비밀처럼 보이는 파일은 격리(백업 제외 + 텔레그램 알림)됩니다. "
            "사람이 deploy/set_backup_passphrase.sh 로 passphrase 를 정하면 그때만 로그인 파일·.env·토큰 등을 암호화해 함께 백업합니다(선택).",
            "저장 위치는 서버의 /opt/quant-backup/repo(로컬 git 저장소, 버전 이력 유지)입니다. 같은 디스크라 실수로 지우거나 파일이 깨지는 것은 막지만 디스크가 사라지는 것은 막지 못합니다. "
            "그래서 /opt/quant-backup/remote 에 '비공개' 저장소 주소가 설정되어 있으면 거기로도 push 합니다. 이 Quant 저장소는 공개이므로 백업을 여기 올리면 안 됩니다. "
            "비공개 저장소 생성·배포 키 등록은 사람이 해야 하며(deploy/DEPLOYMENT_ORACLE.md 15번), 그 전까지는 백업이 같은 디스크에만 있습니다(브리핑의 백업 상태에 원격 미설정으로 표시).",
            "'써졌다'와 '복구된다'는 다르므로 매 실행마다 sha256 매니페스트로 저장본 전체를 검증하고 DB 무결성을 확인하며, 원격 push 뒤 원격 HEAD 를 비교합니다. 검증이 실패하면 밖으로 올리지 않습니다. "
            "7일에 한 번은 백업 저장소를 새로 클론해 검증하는 복구 리허설을 하고 결과를 status.json·브리핑에 표시합니다.",
            "복구 절차(요약, 자세한 명령은 deploy/DEPLOYMENT_ORACLE.md 15번): 백업 저장소를 클론 → 스케줄러·앱을 멈춤 → db/quant.db 를 data/quant.db 로 복사 → files/ 를 저장소 폴더로 rsync(PROGRESS.md 는 덮어쓰지 말고 차이만 옮김) → 서비스 재시작. "
            "암호화 비밀은 openssl 로 라벨별 .enc 파일을 복호화해 원위치에 복원합니다. 사람 손이 필요한 작업이므로 텔레그램으로 개발 요청을 보내 진행하는 것이 안전합니다.",
        ),
        (
            ("실행 시각", "매일 한국시간 06:30(quant-backup.timer)."),
            ("상태 파일", "/opt/quant-backup/status.json — 브리핑의 '운영 상태'와 워치독이 읽음."),
            ("수동 실행", "운영 도구의 deploy/backup_vm.py 항목 참고(--dry-run 으로 목록만 보기 가능)."),
        ),
        V,
    ),
    OpsSection(
        "watchdog-health",
        "워치독·헬스체크·업타임: 조용한 실패를 막는 그물",
        (
            "사용자는 폰으로만 운영하므로 저널 로그를 뒤져야만 보이는 실패는 없는 것과 같습니다. 그래서 서로 다른 층의 감시가 있습니다. 어느 하나도 자동으로 재부팅하거나 롤백하지 않고 알리기만 합니다.",
            "잡 실행 이력: 스케줄러 잡 하나가 끝날 때마다 ok/error/missed(및 스스로 예외를 삼킨 잡의 failed)를 DB 에 남깁니다. 화면 '오늘'의 '운영 경고' 숫자와 브리핑 '운영 상태'가 이 이력으로 잡을 판정합니다"
            "(예정 시각 45분 뒤에도 기록이 없으면 overdue). 한계: 잡이 '돌았는가'를 보장할 뿐 결과가 좋았는지는 아니며, 결과의 신선도는 데이터 무결성 체크가 따로 봅니다.",
            "워치독(deploy/watchdog.py): 스케줄러·앱과 독립적으로 매일 한국시간 09:05 에 도는 별도 타이머입니다(브리핑도 스케줄러 안의 잡이라 스케줄러가 죽으면 같이 안 오기 때문). "
            "최근 26시간 잡 기록, error/missed 잡, 최신 브리핑 생성 여부, 백업 상태, 재부팅 필요 표시 14일 방치를 확인하고 문제가 있을 때만 텔레그램으로 알립니다. 일요일(KST)에는 문제가 없어도 생존 신호 한 통을 보냅니다.",
            "VM 헬스체크(deploy/vm_health_check.sh): 15분마다 디스크(/)와 메모리를 확인해 임계값(기본 디스크 85%, 메모리 90%)을 넘으면 텔레그램으로 알리고, 회복될 때까지 6시간에 한 번만 재알림하며 회복하면 '복구됨'을 한 번 보냅니다. "
            "서비스 죽음 알림: streamlit·scheduler·codex-telegram 서비스가 실패·재시작되면 systemd 가 자동으로 텔레그램을 보냅니다.",
            "업타임(GitHub Actions uptime.yml): VM 이 죽으면 VM 안의 감시도 함께 죽으므로 서버 밖(GitHub)에서 30분마다 세 주소의 DNS·응답·인증서 만료(14일)와 닫아둔 포트(8501/8080/8000)가 밖에서 열려 있지 않은지 확인합니다. "
            "실패하면 워크플로가 실패로 표시되고 GitHub 이 알립니다(텔레그램은 저장소 시크릿을 추가했을 때만). GitHub 워크플로의 새 실패는 VM 의 github_watch 가 15분마다 텔레그램으로도 알립니다. "
            "이 업타임 워크플로는 첫 실행이 GitHub 에서 확인되지 않았다고 인계 문서에 기록돼 있습니다.",
        ),
        (
            ("워치독", "매일 09:05 KST, 문제가 있을 때만 알림 + 일요일 생존 신호."),
            ("VM 헬스체크", "15분마다, 디스크·메모리 임계값 초과 시."),
            ("서비스 실패 알림", "streamlit/scheduler/codex-telegram 서비스가 실패하거나 재시작될 때 즉시."),
            ("GitHub Actions 실패 감시", "15분마다 새로 실패한 워크플로만 알림, 복구되면 '복구됨' 한 번."),
            ("외부 업타임", "GitHub 에서 30분마다 서버 밖 점검."),
        ),
        V,
    ),
    OpsSection(
        "auto-deploy",
        "자동 배포: main 에 올라간 코드가 서버에 반영되는 과정",
        (
            "서버는 5분마다(부팅 2분 뒤 첫 실행) GitHub 의 main 을 확인합니다. 새 커밋이 없으면 아무것도 하지 않고 조용히 끝납니다. 새 커밋이 있으면 git pull --ff-only 로 받고, "
            "requirements.txt 가 바뀌었을 때만 패키지를 설치합니다. 그 다음 서비스를 재시작하기 전에 테스트 관문(pytest 전체 + 텔레그램 러너 테스트)을 통과해야 합니다. 이 설명서도 테스트에 걸려 있어, 새 화면·잡·모듈·스크립트에 설명이 빠지면 배포가 막힙니다.",
            "테스트가 실패하면 서비스를 재시작하지 않아 기존 버전이 계속 돌고, 실패한 테스트 출력 일부와 함께 '[자동배포] pull은 됐지만 테스트 실패' 텔레그램이 옵니다(같은 커밋을 반복 테스트·반복 알림하지 않음). "
            "테스트가 통과하면 서비스를 재시작하고 재시작한 서비스가 실제로 active 인지, 헬스 응답이 있는지 확인한 뒤 '[자동배포] 성공'을 알립니다. 재시작 후 이상이면 '배포는 됐지만 재시작 후 서비스가 정상이 아님'이 옵니다.",
            "pull 자체가 안 되는 경우(히스토리 분기, 로컬 수정 충돌 등)에는 워킹트리를 건드리지 않고 '수동 확인 필요'만 알리며 같은 문제는 6시간에 한 번만 재알림합니다. git reset --hard·clean·stash 같은 파괴적 복구는 절대 하지 않습니다. "
            "자동 롤백도 없습니다: 문제가 있으면 되돌리는 커밋을 올리면 그것이 다시 자동 배포됩니다. VM 에 미커밋으로 쌓인 PROGRESS.md 기록은 3-way 병합으로 보존되고 병합에 실패하면 백업 위치와 함께 알립니다.",
            "참고: 배포가 성공하면 텔레그램 에이전트 서비스도 재시작되어 실행 중이던 작업이 몇 분 늦게 이어질 수 있습니다. 급히 반영하려고 5분을 못 기다리는 경우에는 사람이 서버에서 직접 pull·재시작할 수 있습니다(deploy/DEPLOYMENT_ORACLE.md 6번).",
        ),
        (
            ("주기", "5분마다 (quant-auto-deploy.timer)."),
            ("테스트 관문", "통과해야만 서비스 재시작. 시간 초과(기본 240초)도 실패로 취급."),
            ("성공 알림", "[자동배포] 성공(구→신 커밋, 재시작한 서비스 목록)."),
            ("실패 알림", "pip 설치 실패 / 테스트 실패 / 재시작 후 비정상 / 수동 확인 필요."),
        ),
        V,
    ),
    OpsSection(
        "alpaca-verification",
        "Alpaca paper 검증 자동 실행: 무엇이 검증되고 무엇이 아직인가",
        (
            "스케줄러가 매일 00:40 KST 에 최근 7일 안에 전체 PASS 결과가 없을 때만 읽기 전용 검증 4개(멱등성 스크립트의 읽기 전용 모드, 기업행동, 가격 교차검증, 계좌 스키마)를 실행하고 텔레그램 요약 1건을 보냅니다. "
            "이미 PASS 가 있으면 조용히 건너뛰고, 같은 실패는 3일 안에 반복 알리지 않습니다. 키가 없으면 '키가 없어 건너뜀' 알림만 옵니다. 키 값은 파일·텔레그램·로그 어디에도 남기지 않습니다.",
            "주문을 내는 --write 경로는 절대 자동으로 실행되지 않습니다. 그래서 자동 PASS 는 연결·인증·계정 필드·존재하지 않는 주문 ID 조회 시 404 같은 읽기 전용 범위만 뜻합니다. "
            "같은 client_order_id 재제출 시 422, 주문 직후 조회, 취소 의미(중복 주문 방지의 핵심 가정)는 사람이 scripts/verify_alpaca_paper_idempotency.py --write 를 돌리기 전까지 미검증입니다. "
            "결과 JSON 은 서버의 data/verification/ 에 남습니다. 끄려면 텔레그램 /processes 의 유지보수 묶음에서 'Alpaca paper 검증 자동 실행' 버튼을 누르거나 '/processes off alpaca_verification_bootstrap' 을 보내세요.",
        ),
        (
            ("PASS", "응답이 코드의 가정과 일치."),
            ("FAIL", "응답은 왔지만 코드의 가정과 다름 → 해당 모듈 수정 필요. 해소 전 champion_paper_trade.py --submit 금지."),
            ("UNEXPECTED", "판정 불가(인증 거부·네트워크·구독 등급 한계 등) 또는 위험 신호. note 를 읽고 원인 제거 후 재실행."),
            ("미검증으로 남는 것", "중복 POST 422, 주문 후 조회, 취소 의미, 시장가·notional 체결, 부분체결, 거절 사유별 응답, rate limit, 장중 체결."),
        ),
        V,
    ),
    OpsSection(
        "access",
        "접속 주소와 로그인",
        (
            "주소는 무료 DuckDNS 도메인 하나 아래에 나뉩니다(배포 문서에 기록된 운영 주소). 각 주소는 HTTPS 이며 nginx 가 각 앱을 서버 내부 주소로 중계합니다. "
            "예전의 http://IP:8501 같은 직접 접속은 방화벽에서 닫았고 다시 열면 안 됩니다.",
            "허브와 퀀트 대시보드는 '허브 아이디/비밀번호'로 로그인합니다(2026-09-24 브라우저 기본 팝업 대신 허브 로그인 화면 방식으로 바뀌었고 쿠키로 도메인 공유. 서버 적용은 인계 문서 기준 확인 전). "
            "코드 스페이스는 code-server 자체 비밀번호로 로그인하며 위 둘과 서로 다른 로그인입니다. 비밀번호는 이 설명서에 적지 않으며, 바꾸려면 운영 도구의 set_code_server_password.sh 를 쓰세요.",
            "공인 IP 가 예약(Reserved) IP 가 아니면 인스턴스를 중지했다 켤 때 IP 가 바뀌어 모든 주소가 깨질 수 있고, 그때는 DuckDNS 화면에서 IP 를 직접 고쳐야 합니다(배포 문서 17번, 인계 문서에서 사람이 확인할 항목으로 남아 있음). "
            "DuckDNS 자체가 가끔 불안정할 수 있습니다.",
        ),
        (
            ("관제 허브", "https://hessejeong.duckdns.org/ — 앱·서비스 카드, 이 설명서(/guide)."),
            ("퀀트 대시보드", "https://app.hessejeong.duckdns.org/ — Streamlit 화면들."),
            ("브라우저 코드 스페이스", "https://code.hessejeong.duckdns.org/ — code-server(브라우저 VS Code)."),
            ("로그인 값", "아이디·비밀번호는 문서에 기록하지 않습니다. 브라우저의 비밀번호 저장을 쓰면 다음부터 안 쳐도 됩니다."),
        ),
        V,
    ),
    OpsSection(
        "troubleshooting",
        "문제가 생겼을 때 확인 순서",
        (
            "당황하지 말고 아래 순서로 넓은 것에서 좁은 것으로 보세요. 대부분은 1~3번에서 원인이 드러납니다. 서버를 직접 고치는 일은 텔레그램으로 개발 요청을 보내 맡기는 것이 안전합니다.",
        ),
        (
            ("1. 텔레그램에 무엇이 왔나", "'[자동배포] 실패', '⚠️ 서비스 실패', '[워치독] 확인이 필요합니다', 'VM 디스크·메모리 초과' 중 이미 원인을 말해주는 알림이 있는지 먼저 봅니다."),
            ("2. 어젯밤 브리핑", "📋 오늘의 브리핑의 맨 위 상태 줄과 붉은 '운영 상태'. 안 왔다면 09:05 KST 워치독 알림이나 일요일 생존 신호 누락을 확인."),
            ("3. 화면 '오늘'", "'운영 경고' 숫자와 '오늘 처리할 일', 백업 칩, 시장 스냅샷 시각. 운영 경고가 0 이 아니면 어떤 잡인지 브리핑에서 확인."),
            ("4. 관제 허브", "카드의 서비스 상태(스케줄러·텔레그램 에이전트·VM 헬스체크). 죽어 있으면 서비스 문제입니다."),
            ("5. 화면 열림/느림", "'오늘'이 열리는지, 화면 상단의 기준 시각/신선도(Fresh 는 저장 48시간 이내, Stale 은 그보다 오래됨)를 봅니다. Stale 이면 밤 잡이 안 돈 것입니다."),
            ("6. 텔레그램 /status, /queue, /repo", "에이전트 작업이 막혔는지(blocked), 서버 저장소가 origin 과 얼마나 다른지."),
            ("7. 서버 로그(사람이 SSH 나 코드 스페이스에서)", "journalctl -u quant-scheduler / quant-auto-deploy / quant-streamlit. 폰만으로는 어려우니 개발 요청으로 로그 확인을 맡깁니다."),
            ("8. 그래도 안 되면", "재부팅 필요 표시가 오래 방치됐는지(워치독 알림), 공인 IP 가 바뀌었는지(주소가 아예 안 열리면), 백업 상태를 확인. 자동 재부팅·롤백은 하지 않도록 설계돼 있어 사람이 판단해야 합니다."),
        ),
        V,
    ),
)

# ---------------------------------------------------------------------------
# 상황별 사용법
# ---------------------------------------------------------------------------
ROUTINES: tuple[Routine, ...] = (
    Routine(
        "daily-5min",
        "매일 아침 5분 점검",
        "하루 한 번, 밤 잡이 끝난 뒤(00:25 KST 이후, 보통 아침).",
        (
            "텔레그램에서 '📋 오늘의 브리핑' 파일을 엽니다. 맨 위 상태 줄에 데이터 이상·알파 감쇠·운영 문제 개수가 나옵니다. 붉은 '운영 상태'가 맨 위에 있으면 그 항목부터 봅니다.",
            "브라우저에서 관제 허브 → 퀀트 대시보드 → 화면 '오늘'. '운영 경고' 숫자(0 이어야 정상), '오늘 처리할 일', 백업 칩(정상이어야 함), 시장 국면(unknown 은 판단 보류)을 봅니다.",
            "화면 '챔피언 전략'에서 코어 top4·새틀라이트가 어제와 달라졌는지 봅니다(달라졌다면 밤에 '🏆 챔피언 전략 신호 변경' 텔레그램이 왔을 것). 신호는 추천일 뿐 주문이 아닙니다.",
            "화면 '운용 알림'에서 읽지 않은 알림(관심종목 조건 충족)을 보고 '전체 읽음 처리'를 누릅니다.",
            "07:30 KST 이후에는 '📰 일일 티커 뉴스 리서치'를 훑거나 화면 '뉴스 리서치'를 엽니다(연구용 정보, 매매 권고 아님).",
            "일요일에는 워치독 '주간 생존 신호'가 왔는지 확인합니다. 안 왔다면 그 자체가 이상 신호이므로 '운영·알림'의 확인 순서를 따르세요.",
        ),
        (
            "알림이 하나도 없는 날은 정상인 날이 많습니다(정상일 때 조용한 것이 원칙). 걱정되면 브리핑 상태 줄이 초록인지만 보세요.",
            "이 점검에서 주문을 낼 필요는 없습니다. 주문은 별도 루틴에서만 다룹니다.",
        ),
    ),
    Routine(
        "find-new-stock",
        "새 종목을 찾고 검토하는 법",
        "관심 갈 만한 종목을 새로 찾고 싶을 때.",
        (
            "화면 '종목 스크리닝'의 '필터 스크리닝' 탭에서 조건으로 후보를 좁히거나, '팩터 발굴' 탭에서 팩터 점수로 후보를 뽑습니다. 팩터 발굴 결과는 당시 기준(PIT)으로 검증된 것이 아닙니다.",
            "화면 '시장 진단'의 '섹터 리더·성장주' 섹션에서 강한 테마와 그 안의 후보(추격 후보 표시 등)를 함께 봅니다.",
            "관심 종목이 정해지면 화면 '차트 조회'로 가격 흐름을 보고, '밸류에이션'의 방법론별 비교·PER/PBR 밴드·피어 비교 탭으로 가격 수준을 점검합니다.",
            "화면 '거장 포트폴리오'에서 거장(13F·ARK)이 그 종목을 보유하는지 봅니다. 13F 는 분기 지연 데이터라 '지금 보유'가 아닙니다.",
            "화면 '뉴스 리서치'에서 그 티커의 최근 뉴스 요약과 원문 링크를 확인합니다.",
            "계속 지켜볼 종목은 화면 '운용 알림'에서 관심 티커로 등록하고 전략 조건을 붙여 두면 평일 장마감 후 스캔이 알려줍니다. 보유 종목은 화면 '포트폴리오'에서 관리합니다.",
        ),
        (
            "스크리닝 결과는 추천이 아니라 후보 목록입니다. 좋아 보이는 숫자를 검증된 개선으로 읽지 마세요.",
            "후보 원장(candidate_ledger_record)은 이런 후보를 자동으로 기록해 나중에 검증하는 장치이며, 지금은 미입증이 기본입니다.",
        ),
    ),
    Routine(
        "validate-strategy-idea",
        "전략 아이디어를 검증하는 법(과최적화 주의)",
        "새 매매 전략 아이디어를 시험하고 싶을 때.",
        (
            "화면 '전략 스튜디오'의 '지표 조합 백테스트' 탭에서 종목·지표 조합으로 백테스트를 실행합니다(자연어로 전략을 등록할 수도 있음).",
            "결과 아래 '전략 검증 테스트'의 4개 탭을 모두 봅니다: ① 민감도(안정성: 파라미터를 조금 바꿔도 결과가 유지되는가) ② 순열검정(우연이 아닌가) ③ 수익 분해(추세 덕인가 실력인가) ④ 벤치마크 종합비교.",
            "한 종목에서만 좋으면 '다종목 미세튜닝' 탭으로 여러 종목에서 같은 결과가 나오는지 봅니다. 여러 후보를 탐색했다면 탐색 후보 수가 늘수록 우연히 좋은 후보가 나올 확률이 커지므로 DSR(탐색 횟수를 보정한 값)과 순위 안정성을 함께 봅니다.",
            "'전략 상관관계' 탭으로 이미 가진 전략과 너무 비슷한지 확인합니다.",
            "여러 시대·국면에서 따로 성립하는지(워크포워드 관점)를 봅니다. 전체 기간 평균 하나만 좋고 특정 시기에만 성립하면 믿지 마세요.",
            "저장된 결과에 'legacy' 배지가 있으면 옛 점수 방식(v1)으로 만든 것이라 현재 방식(v2) 결과와 직접 비교하면 안 됩니다.",
        ),
        (
            "과최적화 신호: 파라미터를 조금만 바꿔도 성과가 급변, 순열검정에서 우연과 구분되지 않음, 한 시기·한 종목에만 성립, 탐색 횟수가 매우 많음.",
            "백테스트가 좋아도 '미입증'입니다. 실제 채택은 더 긴 검증과 사람의 판단이 필요하며, 이 설명서의 어떤 화면도 채택을 자동으로 결정하지 않습니다.",
        ),
    ),
    Routine(
        "before-order",
        "주문을 내기 전 체크리스트(paper 전용)",
        "챔피언 신호를 paper 계정에 실제로 반영해 보려 할 때. 실계좌 주문은 이 시스템에 없습니다.",
        (
            "먼저 '오늘' 화면과 '챔피언 전략' 화면에서 신호 상태를 봅니다. 시장필터가 unknown 이면 신규 매수는 보류(데이터 부족)이고, 코어·새틀라이트는 각각 따로 보류될 수 있습니다.",
            "VM 에 배포된 코드가 주문 안전장치(주문 게이트·실행 회차 ID)가 들어간 버전인지 확인합니다. 2026-09-24 인계 문서 기준으로 그 시점 VM 은 구버전이었고 '푸시 전에는 --submit 금지'였습니다. 이 설명서의 배포 버전 표시와 docs/SESSION_HANDOFF.md 를 보세요.",
            "Alpaca paper 검증 상태를 봅니다. 최근 텔레그램 '[Alpaca paper 검증]'이 전체 PASS 여야 하고 FAIL 이 없어야 합니다. 단 전체 PASS 는 읽기 전용 범위뿐이라 중복 주문 방지는 사람이 verify_alpaca_paper_idempotency.py --write 를 돌리기 전까지 미검증입니다.",
            "열린 주문 회차가 없는지 paper_run_admin.py list --status open 으로 봅니다. 남아 있으면 먼저 정리하세요.",
            "계획만 출력합니다: champion_paper_trade.py 를 --submit 없이 실행. 출력의 plan.orders(종목·매수/매도·금액), hold_reason, 매도 사유, plan.fingerprint 를 읽고 의도한 주문인지 확인합니다.",
            "의도와 맞을 때만, 방금 출력된 plan.fingerprint 를 --confirm 에 넣어 --submit 으로 제출합니다. 그 사이에 시장이 움직여 지문이 달라졌으면 제출이 거부되니 계획부터 다시 봅니다.",
            "제출 뒤 결과의 reconcile_state 를 읽고, unresolved 나 rejected 가 있으면 Alpaca paper 대시보드 Orders 에서 직접 확인합니다. 그 후 sync_paper_account.py --no-save 로 계좌와 목표의 이탈을 봅니다.",
        ),
        (
            "주문은 사람이 --confirm 지문을 넣어야만 나가며 스케줄러는 주문을 내지 않습니다. 코드에 실계좌 주소는 없습니다.",
            "이 경로의 실계정 검증은 아직 부분적입니다. 문서·테스트는 mock 기준이었고 실제 응답 검증(--write)은 사람이 해야 합니다. 확신이 없으면 제출하지 마세요.",
        ),
    ),
    Routine(
        "when-alert",
        "알림이 왔을 때 무엇을 볼까",
        "텔레그램 알림을 받았고 뭘 해야 할지 모를 때.",
        (
            "알림 첫 줄로 종류를 구분합니다. '🏆 신호 변경/⏰ 리밸런싱/📅 실적'은 정보 알림, '⚠️ 알파 감쇠/📉 벤치마크 부진'은 점검 신호, '🚨 데이터 무결성/[자동배포]/[워치독]/⚠️ 서비스 실패/디스크·메모리'는 운영 문제입니다(운영·알림 절에 전체 목록).",
            "정보·점검 알림이면 화면 '챔피언 전략'을 열어 해당 내용을 확인합니다. 알파 감쇠는 전략을 바로 바꾸지 말고 '챔피언 최적화'와 백테스트로 최근 성과를 봅니다.",
            "운영 문제 알림이면 화면 '오늘'의 '운영 경고'와 브리핑 '운영 상태'를 봅니다. 자동 잡 표에서 해당 잡의 '알림이 오면' 안내를 읽습니다.",
            "'[자동배포] 테스트 실패'는 기존 버전이 계속 돌고 있다는 뜻이라 급하지 않습니다. 원인 수정은 개발 요청으로 맡깁니다.",
            "'⚠️ 서비스 실패/재시작됨'은 서비스가 자동으로 다시 뜨는 경우가 많습니다. 반복되면 관제 허브의 서비스 상태와 워치독 알림을 함께 확인하고 개발 요청을 보내세요.",
            "정말 원인을 모르겠으면 알림 원문을 그대로 텔레그램 에이전트에 보내 원인 조사를 맡기는 것이 가장 안전합니다(비밀번호·키 값은 붙여 넣지 마세요).",
        ),
        (
            "알림이 왔다는 것과 자동으로 주문이 나갔다는 것은 무관합니다. 이 시스템의 알림은 주문을 내지 않습니다.",
        ),
    ),
    Routine(
        "read-research-infra",
        "연구 인프라(shadow 원장 등) 결과를 읽는 법(미입증이 기본값인 이유)",
        "후보 원장·shadow 기록·전략 변형 보고서·비용 보정 같은 연구용 결과를 볼 때.",
        (
            "먼저 이것들이 '관측 전용'임을 기억합니다. 후보 원장(RES-01), 가이던스 shadow(RES-04), 공시 변경 veto shadow(RES-05), 전략 변형(hold-band) shadow, 비용 보정은 모두 주문 경로에 연결되어 있지 않고 원전략의 실제 결정을 바꾸지 않습니다.",
            "이들의 전용 화면은 없습니다. 후보 원장은 scripts/candidate_ledger_update.py 요약으로, 전략 변형은 서버 data/reports/strategy_research_날짜.md(일요일 자동 생성)로, 비용 보정은 data/cache/cost_calibration.json 으로, 계좌 이탈은 sync_paper_account.py --no-save 로 확인합니다.",
            "판정 문구를 읽습니다. 후보 원장의 판정은 코드로 강제되어 있어, 표본 부족(채택 30건 미만 등)·PIT 미인증·결과 결측 과다·진단용 horizon 이면 신뢰구간과 무관하게 항상 '미입증'입니다. 양성/기각 '검토 대상'이 나와도 자동 채택·폐기는 없고 사람이 검토할 후보일 뿐입니다.",
            "표본 크기를 봅니다. 예: 실측 슬리피지는 30건 미만이면 대표값을 만들지 않습니다(insufficient_sample). 후보 원장은 채택 30건·종목 군집 20개·날짜 블록 6개 미만이면 미입증입니다.",
            "추출 정확도(G0)와 예측력은 따로입니다. 가이던스·공시 추출은 사람이 원문과 대조(G0)하기 전까지 정확도를 주장하지 않으며, 추출이 정확해도 예측력이 입증된 것은 아닙니다.",
            "결론은 '지금은 증거가 없다'입니다. 미입증 상태의 숫자로 종목·비중을 바꾸지 마세요.",
        ),
        (
            "미입증이 기본값인 이유: 처음 일어난 좋은 결과가 우연일 수 있고, 전체 후보가 아닌 채택 종목만 보면 선택편향이 생기며, 당시 알 수 있던 데이터(PIT)만 썼다는 증명이 없기 때문입니다. 그래서 표본이 충분히 쌓이고 조건을 통과해야만 '검토 대상'이 됩니다.",
        ),
    ),
)

# ---------------------------------------------------------------------------
# 용어집
# ---------------------------------------------------------------------------
GLOSSARY: tuple[Term, ...] = (
    Term("PIT (point-in-time)", "그 날짜에 실제로 알 수 있던 데이터만으로 계산했다는 뜻. 나중에 정정·상장폐지·현재 구성종목을 되짚어 쓰면 PIT 가 아닙니다.",
         "PIT 미인증이면 후보 원장의 판정이 항상 '미입증'이 됩니다. 종목 발굴(stock_discovery)은 현재 유니버스·재무를 쓰므로 진정한 PIT 검증이 아닙니다."),
    Term("unknown (판단 보류)", "데이터가 부족해 판정할 수 없다는 상태. 약세나 0%가 아닙니다. 예: SPY 데이터가 없으면 시장필터가 unknown 이고 신규 주문을 보류합니다.",
         "unknown 을 약세로 번역하면 보유 전량을 파는 계획이 나오는 결함이 있었고(고침), 이제 보류로 다룹니다. 시장 국면은 시장폭이 없거나 4개 신호 중 계산된 비중이 75% 미만이면 unknown 입니다. 신호 1개만 빠졌으면 빠진 신호를 0점으로 치지 않고 남은 신호로 재정규화해 판정하되 '일부 신호 결측' 경고(partial)를 붙입니다."),
    Term("미입증", "성과가 좋아진다는 증거가 아직 충분하지 않다는 판정. '틀렸다(기각)'가 아닙니다.",
         "이 시스템 연구 결과의 기본값입니다. 표본 부족·PIT 미인증·신뢰구간이 0 을 포함하는 경우 등이 모두 미입증입니다."),
    Term("shadow (관측 전용 병행 기록)", "실제 판단·주문과 별개로 '이렇게 했다면'을 옆에서 기록만 하는 것.",
         "후보 원장·가이던스·공시 veto·전략 변형이 shadow 입니다. 주문에 영향이 없고 결과는 미입증이 기본입니다."),
    Term("후보 원장 (RES-01)", "채택된 후보만이 아니라 보류·거절된 후보와 결측까지 같은 진입·청산 규칙으로 추적하는 기록(candidate_ledger).",
         "채택 종목만 보면 선택편향이 생깁니다. 주 horizon 20거래일 하나를 사전 고정하고 나머지는 진단용으로 둡니다."),
    Term("hold-band", "이미 보유한 종목은 순위가 조금 밀려도(예: top4 → 6위 밖으로 밀릴 때만) 유지해 회전율·비용을 줄이는 방식.",
         "전략 변형 shadow 가 baseline(top4 그대로)과 hold_band_v1(신규는 top4, 보유는 6위 이내 유지)을 병행 기록합니다. 개선 여부는 미입증입니다."),
    Term("paper", "Alpaca 의 모의투자 계정. 진짜 돈이 아닙니다.",
         "이 시스템의 주문 코드는 paper 주소만 알고 있어 실계좌 주문 경로가 없습니다."),
    Term("주문 게이트", "주문을 실제로 내기 직전에 신규 주문 허용 플래그(코어·새틀라이트 각각)를 다시 확인하는 안전장치. 플래그가 없거나 True 가 아니면 매수를 막습니다(fail-closed).",
         "데이터 부족 슬리브는 매수가 막히고 보유는 유지됩니다. 매도는 명시한 사유가 있을 때만 허용됩니다."),
    Term("실행 회차 (run)", "주문 한 번의 실행 묶음. 회차 ID(예: r00012)가 저장되어 재시도 때 같은 주문 ID 를 재사용합니다.",
         "중복 주문 방지의 핵심입니다. 모든 주문이 확정되기 전에는 회차가 열린 채 남고, 필요하면 paper_run_admin.py 로 수동 종료합니다."),
    Term("계획 지문 (fingerprint)", "주문 계획 내용에서 계산한 짧은 해시. --submit 할 때 --confirm 으로 그 값을 넣어야 제출됩니다.",
         "사람이 계획을 확인했다는 표식입니다. 계획이 바뀌면 지문도 바뀌어 제출이 거부됩니다."),
    Term("멱등성 / client_order_id", "같은 요청을 여러 번 보내도 결과가 한 번만 반영되게 하는 성질. 주문마다 고유한 client_order_id 를 붙이고 재시도 전에 조회합니다.",
         "코드는 이 동작을 가정할 뿐이며 실제 Alpaca 응답 검증(--write)이 끝나기 전에는 미검증입니다."),
    Term("legacy / v2 점수", "전략 튜닝 점수의 방식 버전. legacy(v1)는 결측을 최상위로 취급하고 성장률 결측을 PER 로 대체하던 옛 방식, v2 는 결측을 순위에서 제외하고 중립값을 줍니다.",
         "v1 과 v2 결과는 직접 비교하면 안 됩니다. 옛 결과는 삭제하지 않고 화면 '전략 스튜디오'에 legacy 배지로 표시됩니다."),
    Term("DSR (Deflated Sharpe Ratio)", "여러 후보를 탐색했을 때 우연히 높게 나온 최대 샤프를 보정한 뒤에도 '진짜 샤프가 0보다 클' 확률(0~1). 0.95 이상이면 유의하다고 봅니다.",
         "탐색 후보가 많을수록 우연히 좋은 결과가 나오기 쉬우므로 과최적화 점검에 씁니다(근사치)."),
    Term("walk-forward (워크포워드)", "과거를 구간으로 나눠 앞 구간에서 정하고 뒤 구간에서 시험하는 방식. 이 프로젝트는 시대(era)·시장 국면별로 나눠 검증합니다.",
         "전체 기간 하나의 평균 성과가 특정 시기 덕인지 가려냅니다."),
    Term("과최적화 (curve-fitting)", "과거 데이터에 너무 맞춰 우연을 실력으로 착각한 상태. 파라미터를 조금 바꾸면 성과가 급변하고 다른 시기·종목에서 무너집니다.",
         "화면 '전략 스튜디오'의 민감도·순열검정·수익 분해와 DSR 이 이를 점검합니다. 좋은 백테스트는 증거가 아닙니다."),
    Term("순열검정", "수익률 순서를 무작위로 섞어 본 분포와 비교해 결과가 우연인지 보는 검정.",
         "화면 '전략 스튜디오'의 '순열검정(우연 아님?)' 탭에서 봅니다."),
    Term("슬리피지", "예상 체결가와 실제 체결가의 차이. 이 프로젝트의 백테스트는 5/10/25bp(0.05/0.10/0.25%) 비용 시나리오를 가정합니다.",
         "paper 체결이 30건 이상 쌓이면 실측 슬리피지와 가정을 비교할 수 있고, 그 전에는 대표값을 만들지 않습니다."),
    Term("코어", "챔피언 전략의 85% 부분. 17개 ETF(11개 섹터 ETF·채권 2·금·국제주식·하이일드·원자재) 중 12개월 모멘텀 상위 4개(top4, 절대모멘텀>0)를 동일비중으로 보유합니다.",
         "매월 첫 거래일에 리밸런싱합니다."),
    Term("새틀라이트 (위성)", "챔피언 전략의 15% 부분. S&P500 에서 돈치안 20일 브레이크아웃 추세추종 종목을 골라 보유합니다.",
         "1월·7월 첫 거래일에 리밸런싱합니다. 자체 신규 주문 허용 플래그로 코어와 따로 보류될 수 있습니다."),
    Term("top4", "코어에서 12개월 모멘텀이 가장 높은 4개 ETF(절대모멘텀 통과 종목 중).",
         "'코어 후보' 숫자와 화면 '챔피언 전략'의 코어 목록입니다."),
    Term("200일선 시장필터", "SPY 가 200일 이동평균선 아래면 코어 비중을 절반(50%)으로 줄이는 규칙. SPY 데이터가 없으면 unknown 으로 보류합니다.",
         "확신도가 낮은(weak) 구성요소로 명시된 규칙입니다. 방향은 살아있으나 통계적으로 약합니다."),
    Term("절대모멘텀", "자기 자신의 과거 수익률이 0 보다 큰지 보는 조건. 상대 순위와 별개로 걸러냅니다.",
         "코어 top4 후보는 이 조건을 통과한 종목 중에서만 뽑습니다."),
    Term("60/40 벤치마크", "SPY 60% + TLT 40%. 챔피언 페이퍼 원장 성과를 비교하는 기준입니다.",
         "5%p 이상 뒤처지면 '벤치마크 대비 부진' 알림이 옵니다(원장 20영업일 이상일 때만)."),
    Term("알파 감쇠", "전략의 최근 성과(6개월 백테스트)가 전체 기간에 비해 크게 이탈한 상태. '이 전략을 계속 믿어도 되는가'의 신호.",
         "감지되면 텔레그램으로 알리고 계속되는 동안 매일 재알림하지 않습니다."),
    Term("칼라 헤지", "옵션으로 손실 하단과 이익 상단을 묶는 방식. 챔피언 전략에서는 가장 확신도가 낮은 '조건부 고려' 요소입니다.",
         "화면 '챔피언 전략'에 모형가 기준 라이브 상태가 나오고, 코어 리밸런싱 알림에 롤 예정이 함께 붙습니다. 실제 옵션 주문 인프라는 없습니다."),
    Term("챔피언 페이퍼 원장", "추천 비중을 매일 그대로 따랐다면의 실현 수익을 하루 한 줄씩 누적하는 가상 기록(champion_ledger_record).",
         "실제 계좌 성과가 아닙니다. 실제 계좌는 account_snapshot_sync 가 따로 봅니다."),
    Term("13F", "미국 SEC 에 기관투자자가 분기마다 제출하는 보유종목 공시. 분기 지연 데이터라 항상 과거 시점의 보유입니다.",
         "화면 '거장 포트폴리오'가 이 공시를 파싱합니다. '지금 보유'가 아니므로 참고용입니다."),
    Term("ARK", "캐시 우드의 ARK 운용사. 13F 대신 매일 공개하는 보유내역 CSV 를 써서 더 최신입니다.",
         "guru_holdings_sync 가 매일 갱신합니다."),
    Term("가이던스", "기업이 실적 발표에서 제시하는 다음 분기·연간 전망치(매출·EPS 범위 등).",
         "RES-04 실험이 가이던스가 raised(상향)·lowered(하향)로 바뀌었는지를 추출합니다. 분기 가이던스는 직전 같은 기간이 없어 방향을 못 잡는 경우가 많습니다(unknown)."),
    Term("8-K", "미국 상장사의 수시 공시. 실적 발표 보도자료는 Item 2.02(Results of Operations) 아래 첨부됩니다.",
         "가이던스 추출이 8-K Item 2.02 첨부(EX-99.1)를 읽습니다."),
    Term("10-K / 10-Q", "연간(10-K)·분기(10-Q) 보고서. 위험요인(Item 1A)과 유동성 등 MD&A 절을 담습니다.",
         "RES-05 공시 변경 veto 가 직전 동종 공시와 비교해 새로 생긴 위험 문장 등을 찾습니다."),
    Term("스냅샷 신선도 (Fresh/Stale)", "저장된 결과의 기준 시각이 48시간 이내면 Fresh, 넘으면 Stale, 기준 시각이 없으면 Unknown(확인되지 않음).",
         "화면 상단 상태 헤더의 표기이며 매수·매도 신호가 아닙니다. Stale 이면 밤 잡이 안 돈 것일 수 있습니다."),
    Term("G0 게이트", "추출 품질 게이트. 사람이 만든 정답 표본과 핵심 필드가 95% 이상 정확히 일치하고 거래 방향을 바꿀 오류 0건 등이어야 통과합니다(권장 최소 60 item·30건 발표·8개 기업, 정답 작성자는 추출기 작성자와 다른 사람).",
         "통과 전에는 가이던스·공시 신호 실험으로 가지 않습니다. 사용자가 '사람 확인' 열을 채워야 진행됩니다."),
    Term("horizon", "후보 판단 이후 결과를 재는 기간(거래일 수). 후보 원장은 주 horizon 20거래일을 사전 고정합니다.",
         "나머지 horizon 은 진단용이며 이것으로 채택하지 않습니다(다중검정 방지)."),
    Term("코스톨라니 달걀", "코스톨라니의 시장 심리 순환 모델. 이 프로젝트는 시장과 테마별 국면을 계산합니다.",
         "화면 '시장 진단'의 '코스톨라니 달걀 이론' 섹션에서 봅니다."),
    Term("관측 전용", "결과를 기록만 하고 주문·전략 결정에는 연결하지 않는다는 표시.",
         "자동 잡 이름에 붙어 있으면 그 잡은 실제 판단에 영향을 주지 않습니다."),
    Term("데이터 무결성 체크", "가격(종가 0 이하·이상 수익률·중복·오래됨), FRED 캐시(비어 있음·파싱 오류·오래됨), 뉴스 다이제스트(빈 요약·깨진 링크)를 읽기 전용으로 검사하는 것.",
         "이상이 있을 때만 텔레그램으로 알립니다."),
    Term("리밸런싱", "목표 비중에 맞춰 보유를 다시 조정하는 일. 코어는 매월 첫 거래일, 새틀라이트는 1월·7월 첫 거래일.",
         "알림은 달력 근사라 휴장일이 월초에 끼면 며칠 어긋날 수 있습니다."),
)
