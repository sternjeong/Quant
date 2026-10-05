"""엔진 모듈 설명 — core/ 의 앞쪽 절반(파일명 a~l)."""

from hub.guide.schema import ModuleGuide

V = "2026-09-25"

MODULES: tuple[ModuleGuide, ...] = (
    ModuleGuide(
        module="core/contests.py", name="AI 대회 관리", group="운영·안전", status="운영중",
        what="관제 센터 'AI 대회' 섹션의 뒷단입니다. 대회마다 /srv/contests/<이름> 작업 폴더를 만들고 뼈대 파일(README·data/·notebooks/·src/·submissions/·.gitignore·requirements.txt)을 넣은 뒤 GitHub private 저장소(contest-<이름>)를 만들어 푸시합니다. 마감 알림도 여기서 계산합니다.",
        how_to_use="관제 센터 → AI 대회 → '+ 새 대회'. 대회 화면의 'VS Code 에서 열기'를 누르면 브라우저 VS Code(code-server)가 그 폴더로 열립니다. 상태·마감·메모는 대회 화면에서 고칩니다.",
        where_to_see="관제 센터 /contests, 텔레그램(마감 알림)",
        cautions="처음 한 번은 code-server 터미널에서 'sudo bash /opt/quant/deploy/setup_contests.sh' 를 실행해야 폴더를 만들 수 있습니다. 저장소는 항상 private 입니다. data/·submissions/ 는 대회 규정·용량 때문에 커밋되지 않습니다. GitHub 단계가 실패해도 폴더는 남고 대회 화면에서 다시 시도할 수 있습니다.",
        verified="2026-09-26",
    ),
    ModuleGuide(
        module="core/agent_batch.py", name="AI 에이전트 야간 배치", group="리서치 인프라", status="실험",
        what="매일 03:00 KST에 AI 에이전트(Scout·Writer·Implementer·Critic·Post-mortem)를 차례로 돌려 새 전략 가설을 만들고, Critic이 승인한 가설을 동결해 자동 심판에 넘깁니다. 매달 25일 이후 한 번은 geo_analyst 가 다음 달 코어 리밸런싱 전 국제정세 의견을 남깁니다(기록만, core/geo_shadow.py). 분기마다 core_designer 가 코어 아이디어를 최대 3개 제안합니다(core/core_rnd.py). 각 연구는 R&D 센터의 주제 스위치를 따릅니다(꺼진 주제는 건너뜀). 새틀라이트 R&D 트랙도 함께 돕니다: sat_designer 가 새틀라이트 선정 규칙 아이디어 하나를 스펙·신호·테스트로 만들고, 결정론 검사(테스트 + 합성 데이터 실행 + 미래 비의존 확인)와 sat_critic 검토를 통과하면 VM 연구 창의 계산기가 동결·심판합니다(재작업 최대 3회, 동시에 2개까지). 중간에 끊겨도 다음 날 밤 그 자리에서 이어집니다. 아이디어를 고르는 Scout·Writer에게는 이미 재검증에서 실패한 방향 목록(research/agent_prompts/dead_ends.md)과 고전 팩터 감쇠표(research/factor_decay.md)를 함께 줘서 같은 실패를 되풀이하지 않게 합니다.",
        how_to_use="자동입니다. 결과는 아침 텔레그램 요약과 허브 'AI 에이전트 연구' 화면에서 봅니다. 역할별 모델은 그 화면이나 텔레그램 /models 에서 바꿉니다.",
        where_to_see="허브 /research, 텔레그램(배치 요약 1건)",
        cautions="에이전트는 자기 작업 폴더(research/)에만 쓸 수 있고, 그 밖의 파일을 바꾸면 자동으로 되돌립니다. 새틀라이트 아이디어의 '준비 완료' 표시는 에이전트가 쓸 수 없는 data/satellite_lab/agent/ 에 배치가 기록합니다. 브로커·텔레그램 키는 에이전트에게 넘기지 않습니다. 주문 경로와 연결되어 있지 않습니다. 새틀라이트 트랙은 실제 Claude CLI로 아직 한 번도 실행하지 않았습니다.",
        verified="2026-10-02",
    ),
    ModuleGuide(
        module="core/agent_budget.py", name="에이전트 토큰 예산", group="리서치 인프라", status="운영중",
        what="에이전트 역할별 모델·최대 턴·시간·주간 실행 횟수와 하룻밤 $15·주간 $60(API 환산 금액) 상한을 정하고, 실행마다 사용량을 기록합니다. 사람이 고른 역할별 모델도 여기서 반영합니다. 새틀라이트 R&D 역할(sat_designer 주 8회, sat_critic 주 8회)·국제정세 의견(geo_analyst 월 1회)·코어 분기 제안(core_designer 분기 1~2회)도 같은 예산을 나눠 씁니다.",
        how_to_use="허브 /research 의 '역할별 모델' 표나 텔레그램 /models 에서 모델을 바꾸면 다음 배치부터 적용됩니다. 비싼 모델일수록 예산이 빨리 찹니다.",
        where_to_see="허브 /research 의 '에이전트 예산'·'역할별 모델'",
        cautions="금액은 Claude CLI가 보고하는 API 환산값으로, 구독 요금제에서는 실제 청구액이 아니라 사용량의 대리 지표입니다. 05:30 이후에는 새 작업을 시작하지 않고 05:50에 멈춥니다.",
        verified="2026-10-02",
    ),
    ModuleGuide(
        module="core/hypothesis_spec.py", name="가설 스펙 계약", group="리서치 인프라", status="운영중",
        what="에이전트나 사람이 쓰는 전략 가설 JSON의 형식을 검사합니다. 파라미터 조합 하나하나가 '시도 1회'로 영구히 누적되어 통과 기준을 엄격하게 만듭니다.",
        how_to_use="직접 쓸 일은 없습니다. 사람이 가설을 넣을 때는 scripts/hypothesis_admin.py add 가 이 검사를 거칩니다.",
        where_to_see="화면 없음",
        cautions="동결된 스펙은 바꿀 수 없고, 고치려면 새 가설로 등록해야 합니다.",
        verified="2026-09-25",
    ),
    ModuleGuide(
        module="core/hypothesis_registry.py", name="가설 레지스트리·시도 카운터", group="리서치 인프라", status="운영중",
        what="가설의 상태(초안→동결→심판 통과/탈락→shadow→승격 후보→paper 편입/종료)를 되돌릴 수 없게 기록하고, 지금까지 동결된 모든 가설의 시도 수를 셉니다. 주간 동결 10개, shadow 동시 20개가 상한입니다.",
        how_to_use="허브 /research 의 '가설 퍼널'로 봅니다. 사람이 상태를 바꿀 때는 텔레그램 승인 버튼이나 hypothesis_admin 스크립트를 씁니다.",
        where_to_see="허브 /research",
        cautions="누적 시도 수는 실패·폐기돼도 줄지 않습니다. 이 숫자가 클수록 새 가설이 통과하기 어려워지는 것이 정상입니다.",
        verified="2026-09-25",
    ),
    ModuleGuide(
        module="core/hypothesis_engine.py", name="가설 백테스트 엔진", group="분석·백테스트", status="운영중",
        what="동결된 가설의 신호 코드를 과거 데이터로 돌려 일별 순수익을 만듭니다. 신호에는 그날 종가까지의 데이터만 넘기고, 오늘 정한 비중은 다음 거래일부터 적용하며 리밸런싱 비용을 뺍니다.",
        how_to_use="자동 심판이 씁니다. 직접 쓸 일은 없습니다.",
        where_to_see="화면 없음(심판 결과로 반영)",
        cautions="과거 S&P500 구성종목 목록을 쓰지만 상장폐지 종목의 가격이 무료 소스에 없으면 빠지므로 생존편향이 남습니다(심판 결과에 가격 커버리지로 표시).",
        verified="2026-09-25",
    ),
    ModuleGuide(
        module="core/hypothesis_judge.py", name="가설 자동 심판", group="분석·백테스트", status="운영중",
        what="AI 없이 코드로만 가설을 통과/탈락 판정합니다. 누적 시도 수를 반영한 Deflated Sharpe 0.95 이상, 강세·약세·횡보장 과반에서 SPY보다 나음, SPY 상관 0.9 미만, 챔피언 상관 0.7 미만, 최대낙폭·리밸런싱 횟수 기준을 모두 만족해야 통과합니다. 여기에 강건성 검사 세 가지가 더 붙습니다: 수익이 0이 되는 비용(손익분기 bp)이 가정 비용의 2배 이상, 가장 좋았던 3개월을 빼도 샤프가 절반 이상 유지, 대표 파라미터를 절반·1.5배로 바꿔도 샤프가 양수이고 중앙값이 절반 이상. 또 마지막 2년은 떼어 두고(표본 밖) 파라미터는 그 앞 구간만 보고 고르며, 떼어 둔 2년의 샤프가 0 이하면 탈락합니다(기간이 짧으면 분리하지 않고 경고). Ken French 팩터 회귀(시장·규모·가치·수익성·투자·모멘텀)는 참고용으로만 기록합니다.",
        how_to_use="자동입니다. 탈락 사유는 허브 /research 의 '최근 상태 전이'에서 봅니다.",
        where_to_see="허브 /research",
        cautions="비용은 실측 교정이 있으면 그것을, 없으면 편도 25bp를 보수적으로 가정합니다. 데이터 오류가 3번 이어지면 탈락 처리합니다.",
        verified="2026-09-26",
    ),
    ModuleGuide(
        module="core/french_factors.py", name="Ken French 팩터 데이터", group="리서치 인프라", status="관측 전용",
        what="다트머스 Ken French 데이터 라이브러리(1926년부터, 상장폐지 종목까지 포함)를 받아 두 가지에 씁니다. 하나는 심판을 받는 가설의 수익이 이미 알려진 팩터(시장·규모·가치·수익성·투자·모멘텀)로 얼마나 설명되는지 보는 회귀, 다른 하나는 고전 팩터가 원 논문 공개 전후로 얼마나 약해졌는지 보는 감쇠표입니다.",
        how_to_use="자동입니다. 심판 결과에 팩터 회귀가 붙고, 알파 t가 2 미만이면 '알려진 팩터로 대부분 설명됨' 경고가 뜹니다. 감쇠표는 scripts/french_factor_report.py 로 새로 만듭니다.",
        where_to_see="허브 /research(심판 경고), research/factor_decay.md",
        cautions="팩터 회귀는 통과/탈락에 쓰지 않습니다. 우리 가설은 매수만 하므로 시장 베타가 크게 나오는 것이 정상입니다. 원자료는 한두 달 늦게 갱신되고, 7일마다 다시 받으며 실패하면 저장해 둔 사본을 씁니다.",
        verified="2026-09-26",
    ),
    ModuleGuide(
        module="core/hypothesis_shadow.py", name="가설 shadow 전진 검증", group="리서치 인프라", status="관측 전용",
        what="심판을 통과한 가설의 판정과 실현수익을 매일 기록합니다(주문 없음). 60거래일이 쌓이면 백테스트보다 유의하게 나쁘지 않은지 판정해 승격 후보로 올리거나 종료합니다. 승격 후보가 되면 [paper 편입][종료] 버튼이 달린 텔레그램이 옵니다.",
        how_to_use="승격 후보 알림이 오면 버튼 하나로 결정합니다. 누르지 않으면 아무것도 바뀌지 않습니다.",
        where_to_see="텔레그램(승격 후보 알림), 허브 /research",
        cautions="승격 후보는 'paper에서 더 볼 가치가 있다'는 뜻이지 검증 완료가 아닙니다. 미국 장 마감 전의 당일 봉은 기록에 쓰지 않습니다.",
        verified="2026-09-25",
    ),
    ModuleGuide(
        module="core/research_sleeve.py", name="승격 가설 paper 편입(research 슬리브)", group="운용", status="실험",
        what="사람이 승인한 가설을 paper 계좌의 research 슬리브(자산의 10%, 가설당 최대 5%)로 편입할 목표 비중을 만듭니다. 챔피언 비중은 그만큼 줄여 전체가 100%를 넘지 않게 합니다.",
        how_to_use="승격 후보 텔레그램의 [✅ paper 편입] 버튼을 누르면 다음 자동 주문(화~토 06:10)부터 반영됩니다. [🗑 종료]를 누르면 다음 자동 주문에서 정리됩니다.",
        where_to_see="텔레그램(자동 주문 결과에 research 슬리브 표시), 허브 /research",
        cautions="paper 자동 주문이 꺼져 있으면 실제로 제출되지 않습니다. 승격 가설의 기록이 5일 넘게 오래되면 research 슬리브만 보류합니다(새로 사지 않고 보유 유지). 승격 가설이 없으면 주문 계획은 기존과 같습니다.",
        verified="2026-09-25",
    ),
    ModuleGuide(
        module="core/alpaca_market_meta.py", name="Alpaca 거래 가능 여부·휴장 캘린더", group="데이터", status="도구",
        what="Alpaca에 물어 종목이 실제로 거래 가능한지(상장폐지·거래정지·비활성 여부)와 그날이 미국 증시 개장일인지를 확인합니다. 읽기 전용입니다.",
        how_to_use="자동 주문 실행기(paper_auto_trade)가 제출 직전에 이 점검을 씁니다. 직접 쓸 일은 없고, 응답 형식이 가정과 맞는지는 scripts/verify_alpaca_meta_news.py로 VM에서 확인합니다.",
        where_to_see="화면 없음(자동 주문 실행기의 텔레그램 결과에 반영)",
        cautions="Alpaca 응답 형식은 문서를 보고 가정한 것이며 실제 API로 아직 검증하지 않았습니다. 이 점검은 알림용이고 주문을 스스로 막지는 않습니다.",
        verified="2026-09-25",
    ),
    ModuleGuide(
        module="core/alpaca_news.py", name="Alpaca 뉴스 수집(당시 기준)", group="데이터", status="실험",
        what="Alpaca 시장 데이터의 뉴스를 가져와, 기사가 처음 게시된 시각 기준으로 정리합니다. 나중에 수정된 시각은 별도로 보관해 과거 실험에 미래 정보가 섞이지 않게 합니다. 감성 점수는 만들지 않습니다.",
        how_to_use="뉴스 이벤트 연구(news_event_study)의 입력으로만 쓰입니다. 직접 쓸 일은 없습니다.",
        where_to_see="화면 없음. 연구 스크립트가 data/research/ 에 결과 파일을 남깁니다.",
        cautions="과거 날짜 조회가 된다는 것은 문서 기준이며 아직 검증하지 않았습니다. 무료 뉴스 API의 한계를 우회하려는 실험용입니다.",
        verified="2026-09-25",
    ),
    ModuleGuide(
        module='core/account_sync.py',
        name='실계좌 스냅샷·목표 이탈 감지',
        group='운용',
        status='관측 전용',
        what=
            'Alpaca 모의(paper) 계좌에 실제로 들고 있는 종목을 조회해 저장하고, 챔피언 전략이 추천한 목표 비중과 얼마나 벌어졌는지 계산합니다. 조회만 하며 주문은 만들지도 내지도 않습니다.',
        how_to_use=
            '매일 밤 00:35(KST) 자동으로 돕니다. 직접 할 일은 없고, 목표와 크게 벌어졌는지가 궁금할 때 VM에서 scripts/sync_paper_account.py 를 돌려 결과를 볼 수 있습니다. 잡이 실패하면 오늘 화면의 잡 상태에 표시됩니다.',
        where_to_see=
            '화면 없음(DB 저장 + 스크립트 출력)',
        cautions=
            '이 결과가 주문으로 이어지지 않습니다. Alpaca 키가 없으면 그냥 건너뜁니다. 이탈 계산은 참고 정보일 뿐 리밸런싱 지시가 아닙니다.',
        sources=('scheduler/run_scheduler.py', 'scripts/sync_paper_account.py'),
        verified=V,
    ),
    ModuleGuide(
        module='core/alpaca_price_provider.py',
        name='Alpaca 가격 교차검증 공급자',
        group='데이터',
        status='실험',
        what=
            '후보 원장의 사후 성과를 채울 때 쓸 가격을 Alpaca 일봉으로 받되, 기존 yfinance 데이터와 대조해 깨끗할 때만 Alpaca 값을 쓰고 아니면 기존 데이터로 되돌리는 어댑터입니다.',
        how_to_use=
            '직접 쓸 일은 없습니다. 의도적으로 연결하지 않은 상태라 사용자에게 보이는 결과도 없습니다.',
        where_to_see=
            '화면 없음',
        cautions=
            "의도적으로 미연결입니다(2026-09-25 결정). 후보 원장의 진입가(시가)가 실행할 때마다 yfinance 또는 Alpaca(IEX) 중 어느 쪽에서 오느냐에 따라 달라지면 같은 원장 안에서 가격 기준이 섞이는데, 이 어댑터는 종가만 대조하고 시가 차이는 검사하지 않습니다. 그래서 먼저 데이터 무결성 점검의 가격 교차 대조(매일 00:22)로 두 소스의 차이를 관측하고, 그 기록을 본 뒤에 연결 여부를 정합니다. 지금 후보 원장 성과 채움 잡은 기본(yfinance) 가격 공급자를 씁니다.",
        sources=('core/price_crosscheck.py', 'core/data_integrity.py'),
        verified=V,
    ),
    ModuleGuide(
        module='core/alpaca_verification.py',
        name='Alpaca 검증 자동 실행기',
        group='운영·안전',
        status='운영중',
        what=
            'Alpaca 모의 계좌 연동이 가정대로 동작하는지 읽기 전용 검증 4개(멱등성 읽기, 기업행동, 가격 교차검증, 계좌 형식)를 자동으로 돌려 PASS/FAIL 을 JSON 으로 남깁니다.',
        how_to_use=
            '최근 7일 안에 전체 PASS 가 없을 때만 매일 00:40(KST)에 돌고, 결과 요약이 텔레그램 1건으로 옵니다. FAIL 이 왔을 때만 내용을 확인하면 됩니다.',
        where_to_see=
            '텔레그램 알림 + 파일(data/verification/)',
        cautions=
            '주문을 내지 않고 키 값은 저장하지 않습니다. Alpaca 키가 없으면 건너뜁니다. 검증이 PASS 여도 전략 성과를 보장하지 않고 연동이 가정대로라는 뜻일 뿐입니다.',
        sources=('scheduler/run_scheduler.py',),
        verified=V,
    ),
    ModuleGuide(
        module='core/backtest_engine.py',
        name='백테스팅 엔진',
        group='분석·백테스트',
        status='도구',
        what=
            '전략의 매매 신호(보유/미보유)를 받아 자산 곡선과 수익률, 최대낙폭(MDD), 샤프, 승률, 매매 횟수 등을 계산하고 S&P500·개별 종목 매수보유와 비교합니다. 수수료·슬리피지 가정도 넣을 수 있습니다.',
        how_to_use=
            '전략 스튜디오에서 전략을 돌릴 때, 챔피언 전략·시장 진단 화면의 백테스트 부분에서 자동으로 쓰입니다. 직접 부를 일은 없고 화면에서 결과 그래프와 지표를 봅니다.',
        where_to_see=
            '전략 스튜디오, 챔피언 전략, 시장 진단 화면',
        cautions=
            '과거 데이터로 계산한 결과이며 미래 성과를 보장하지 않습니다. 비용 가정을 바꾸면 결과가 크게 달라질 수 있습니다.',
        sources=('app/pages/1_전략_스튜디오.py',),
        verified=V,
    ),
    ModuleGuide(
        module='core/backup_status.py',
        name='백업 상태 읽기',
        group='운영·안전',
        status='운영중',
        what=
            "VM 백업이 남기는 상태 파일을 읽어 '마지막 백업이 언제였나, 실패는 없나' 를 한 줄로 요약합니다. 읽기만 하고 백업 자체는 다른 스크립트가 합니다.",
        how_to_use=
            "오늘 화면의 '백업' 칩과 워치독(감시) 점검에서 자동으로 쓰입니다. 칩이 '확인 필요/차단'이면 백업이 밀렸다는 뜻이니 그때 백업 로그를 확인하세요.",
        where_to_see=
            '오늘 화면(백업 칩), 워치독 알림',
        cautions=
            "백업이 설치되지 않은 환경(개발 PC 등)에서는 '상태 없음'으로 표시됩니다. 오래된 성공/최근 실패 기준(36시간 등)은 코드에 고정돼 있습니다.",
        sources=('deploy/watchdog.py', 'core/today_dashboard.py'),
        verified=V,
    ),
    ModuleGuide(
        module='core/candidate_ledger.py',
        name='후보 shadow 원장',
        group='리서치 인프라',
        status='관측 전용',
        what=
            "채택한 종목뿐 아니라 보류·거절한 후보까지 같은 진입·청산·비용 규칙으로 끝까지 추적해 DB에 쌓는 원장입니다. 나중에 '채택이 정말 보류보다 나았나' 를 검증하기 위한 자료입니다.",
        how_to_use=
            '매일 밤 자동으로 기록(00:27)하고 만기 지난 결과를 채웁니다(00:28). 직접 할 일은 없고, 수동으로 결과를 채우려면 scripts/candidate_ledger_update.py 를 씁니다.',
        where_to_see=
            '화면 없음(DB)',
        cautions=
            '주문에 영향을 주지 않는 관측 전용이며 성과나 승률 개선을 입증하지 않았습니다. 표본이 충분히 쌓이기 전에는 결론을 내리면 안 됩니다. '
            '판정은 PIT 근거가 있는 행만 인정합니다: 5개 시각이 모두 있는 행(full_contract) 또는 진입 시가보다 먼저 원장에 기록된 행(forward_recorded, 매일 밤 잡이 쌓는 후보). '
            '과거 날짜로 나중에 소급 기록한 행은 인정되지 않아, 하나라도 섞이면 판정은 미입증입니다. 진입 전 기록은 원천 데이터의 발표 시각까지 보증하지 않습니다(공급자의 소급 수정 가능). '
            '표본 수·결측률·신뢰구간 조건은 그대로입니다.',
        sources=('scheduler/run_scheduler.py', 'scripts/candidate_ledger_update.py', 'docs/CANDIDATE_LEDGER_SPEC.md', 'core/candidate_ledger.py'),
        verified=V,
    ),
    ModuleGuide(
        module='core/exit_variants.py',
        name='후보 원장 청산 규칙 비교',
        group='리서치 인프라',
        status='관측 전용',
        what=
            "후보 shadow 원장에 이미 기록된 후보를 같은 진입(다음 시가)에서 청산 규칙만 바꿔 다시 계산하고, 원장과 같은 판정 틀로 비교합니다. 변형은 사전에 고정한 4개입니다: 원장과 같은 20거래일 보유, 진입가 -8% 고정 손절, 최고 종가 -10% 추적 손절, 위성 전략의 최고 종가 -15% 트레일링 스탑(모두 20거래일 상한). 손절은 일봉 종가로 판단하고 다음 거래일 시가에 체결된다고 봅니다.",
        how_to_use=
            "자동 잡에 연결되어 있지 않습니다. 보고서가 필요하면 파이썬에서 core.exit_variants.write_exit_variants_report() 를 부르면 data/reports/exit_variants_날짜.md·.json 이 만들어집니다. 채택 그룹의 비용 후 기대값·승률·손익비·최대 손실과 놓친 기회를 변형별로, 기준선 대비 차이와 함께 봅니다.",
        where_to_see=
            '화면 없음(data/reports/exit_variants_날짜.md)',
        cautions=
            "기준선이 아닌 변형 3개는 여러 규칙을 동시에 본 탐색 결과라 신뢰구간을 3배 보수적으로 잡고 '탐색 결과'로만 표시합니다. 표본 부족·PIT 미인증이면 '미입증'입니다. 결과는 과거 관측이며 미래 성과를 보장하지 않고, 주문에 영향을 주지 않습니다.",
        sources=('docs/EXIT_VARIANTS_SPEC.md',),
        verified='2026-09-26',
    ),
    ModuleGuide(
        module='core/candidate_recorder.py',
        name='후보 원장 기록 잡',
        group='리서치 인프라',
        status='관측 전용',
        what=
            '후보 shadow 원장에 실제 후보(종목 발굴, 섹터 리더, 위성 후보)를 하루 한 번 스냅샷으로 기록해 넣는 스케줄 잡 어댑터입니다. 원래 전략 함수는 읽기만 합니다.',
        how_to_use=
            '매일 밤 00:27(KST)에 자동으로 돕니다. 사용자가 할 일은 없습니다. 꺼두고 싶으면 텔레그램 /processes 로 끌 수 있습니다.',
        where_to_see=
            '화면 없음(DB)',
        cautions=
            '관측 전용이라 주문과 무관하고 성과는 미검증입니다. 화면을 열 때마다 기록하지 않고 스케줄 잡에서만 기록하도록 설계돼 있습니다. 위성 후보는 2026-09-25부터 채택 종목만이 아니라 그 반기 풀 표본 전체를 기록합니다: 채택=selected, 돌파는 켜졌지만 상위 3위 밖=held, 돌파 없음=rejected, 가격 이력 부족=missing_data. 결정은 위성 전략 결과를 그대로 옮길 뿐 다시 계산하지 않습니다.',
        sources=('scheduler/run_scheduler.py', 'docs/CANDIDATE_LEDGER_SPEC.md', 'core/candidate_recorder.py'),
        verified='2026-09-26',
    ),
    ModuleGuide(
        module='core/champion_strategy.py',
        name='챔피언 전략 엔진',
        group='운용',
        status='운영중',
        what=
            '리서치 종합 결론(코어 자산배분 + 위성 종목)을 오늘 기준 추천 비중으로 계산합니다. 신호 변화, 리밸런싱, 실적 발표 임박, 알파 감쇠, 주간 리포트 등 챔피언 관련 자동 잡의 계산 본체이기도 합니다.',
        how_to_use=
            '챔피언 전략 화면에서 오늘의 추천 비중과 근거를 봅니다. 매일 밤 자동 잡이 신호가 바뀌었을 때 텔레그램으로 알려 주니, 그 알림이 오면 화면을 열어 확인하세요.',
        where_to_see=
            '챔피언 전략, 챔피언 최적화, 오늘 화면 + 텔레그램 알림',
        cautions=
            '이 모듈은 계산만 하며 주문은 별도 스크립트(scripts/champion_paper_trade.py)가 담당합니다. 확신도가 낮은 구성요소도 숨기지 않고 표시합니다. 과거 백테스트 기반이라 미래 수익을 보장하지 않습니다. 2026-09-25부터 반기 위성 결과에 관측 전용 필드(candidates=돌파가 켜진 후보 전체와 모멘텀 순위, rejected_tickers=돌파 없음, missing_tickers=이력 부족)가 더 붙습니다. 이 필드는 후보 원장·shadow 실험 기록에만 쓰이고, 고르는 종목·비중·주문은 전과 똑같습니다(변경 전 코드와 대조하는 테스트로 확인). 2026-10-02 사용자 결정으로 코어에서 남는 몫(시장필터 축소분·빈 슬롯)은 수익 0 현금 대신 단기국채 ETF(BIL)에 담습니다(paper 주문도 BIL 을 삽니다). 고르는 종목(순위·절대모멘텀·SPY 200일선)은 예전처럼 가격 기준이고, 백테스트 수익만 배당·분배금 포함 총수익(Adj Close)으로 잽니다. 이 변경은 코어 R&D v2 의 C01 로, G2~G5 는 통과했지만 효과가 작아 G1 은 넘지 못했습니다(2008년~ 총수익 기준 CAGR 9.36%→9.52%, 최대낙폭 −19.7%→−19.8%). 같은 날 순위를 총수익 기준으로도 바꿨다가 18년 전체 성과가 나빠(CAGR 9.12%, 최대낙폭 −21.7%) 되돌렸습니다. 새틀라이트는 가격(Close) 기준입니다. 전략 버전이 바뀌어 예전 재추천 결과는 다시 계산해야 합니다.',
        sources=('app/pages/11_챔피언_전략.py', 'scheduler/run_scheduler.py', 'core/champion_strategy.py'),
        verified='2026-10-02',
    ),
    ModuleGuide(
        module="core/champion_tracking.py", name="챔피언 주간 추적 판정", group="운용", status="관측 전용",
        what=(
            "챔피언 전략이 실제 시장에서 백테스트대로 움직이는지 매주 판정합니다. 가상 원장(00:12 기록)에 적힌 추천 비중을 "
            "장 마감 종가에 다시 적용해 라이브 N거래일 누적수익을 만들고, 라이브 시작 전 8년 백테스트에서 같은 길이 N거래일 "
            "구간을 모두 모은 분포의 몇 분위인지 계산합니다. 규칙은 미리 고정돼 있습니다: 5~95분위면 '백테스트 범위 안(정상)', "
            "그 밖이면 '범위 밖 — 주의', 1분위 아래·99분위 위이거나 라이브 최대낙폭이 백테스트 최악 낙폭보다 깊으면 "
            "'이탈 — 확인 필요', 20거래일 미만이면 '판정하기엔 이름(표본 부족)'(수치만 표시). SPY·60/40 대비 초과수익 분위도 "
            "같이 보여 주지만 한 줄 판정에는 쓰지 않습니다. 함께 점검하는 것: paper 계좌가 추천을 실제로 따르는지(추적오차 파일), "
            "원장 비중이 그날 추천과 같은지, 원장·가격 결측."
        ),
        how_to_use=(
            "자동입니다. 일요일 01:10 KST 텔레그램 '챔피언 주간 검증' 1건을 읽으세요. 첫 줄이 판정, 마지막에서 두 번째 줄이 "
            "'조치: 필요 없음/필요'입니다. 문제가 없어도 매주 오므로, 일요일에 오지 않으면 잡이 멈춘 것입니다. "
            "자세한 수치는 VM 의 data/reports/champion_tracking_날짜.json 에 있습니다."
        ),
        where_to_see="텔레그램(일요일 요약 1건), data/reports/champion_tracking_YYYY-MM-DD.json, 백테스트 캐시 data/cache/champion_backtest_daily.json",
        cautions=(
            "겹치는 구간으로 만든 분위라 독립 표본이 아니며 p-값처럼 읽으면 안 됩니다. 라이브 기간이 짧으면 기대 범위가 넓어 "
            "거의 항상 '범위 안'이 나옵니다(판정력이 낮음). 백테스트 자체에 PIT 한계(새틀라이트 표본추출·생존편향, 배당 미포함)가 "
            "있어 '범위 안'은 전략이 좋다는 증거가 아니라 '백테스트와 모순되지 않는다'는 뜻입니다. 원장은 매일 목표를 다시 계산하고 "
            "백테스트 코어는 월초에만 바꾸므로 '백테스트 규칙과 코어 종목 다른 날'에는 이 구조 차이가 섞여 있습니다. "
            "60/40 격차·알파 감쇠 알림은 다시 보내지 않고 '발동 중' 한 줄로만 알립니다. 주문과 연결되어 있지 않습니다."
        ),
        sources=("core/champion_strategy.py", "core/paper_tracking.py", "scheduler/run_scheduler.py"),
        verified="2026-09-26",
    ),
    ModuleGuide(
        module="core/champion_performance.py", name="챔피언 성과 해부", group="운용", status="운영중",
        what="챔피언 백테스트가 만든 코어·새틀라이트 비중 시계열을 그대로 풀어 거래(보유 구간) 목록·비중 조정 기록·달러 자산곡선·연도별 수익·종목별 손익 기여를 만들고, 같은 구간 SPY·60/40과 비교합니다. 새 전략 판단은 하지 않으며 거래 손익 합이 기존 백테스트 자산곡선과 맞는지 스스로 검산합니다. 따로, 2026-09-19부터 쌓인 '추천을 따랐다면' 원장과 paper 계좌 스냅샷으로 실제 시장 기록을 계산합니다(백테스트와 섞지 않음).",
        how_to_use="챔피언 성과 화면에서 씁니다. 저장된 결과가 없으면 화면의 '📊 계산 시작' 버튼으로 백그라운드 계산을 시작합니다. 결과를 초기 금액 대비 배수로 저장해 두고 화면에서 곱하므로 초기 금액을 바꿔도 다시 계산하지 않습니다.",
        where_to_see="챔피언 성과 화면. 계산 결과는 data/cache/champion_performance_<해시>.json",
        cautions="백테스트 부분은 과거 가격에 규칙을 적용한 가상 결과이고 비용은 편도 고정 bp만, 새틀라이트 후보는 현재 S&P500 명단 기반이라 생존편향이 있습니다. 실시간 부분은 실제 주문 기록이 아닙니다. 주문 경로를 import 하지 않습니다. 캐시 키에는 기간·새틀라이트 비중·전략 버전·비용 가정이 들어가며, 전략 버전이 바뀌면 옛 결과는 쓰지 않습니다.",
        sources=("core/champion_strategy.py", "app/pages/14_챔피언_성과.py"),
        verified="2026-09-26",
    ),
    ModuleGuide(
        module="core/champion_recommendation.py", name="챔피언 지금 기준 재추천", group="운용", status="운영중",
        what=(
            "챔피언 전략 화면 맨 위의 '🔄 지금 기준으로 다시 추천' 버튼이 누르는 계산입니다. 새 전략을 만들지 않고 이미 "
            "검증된 함수만 모아 네 칸을 채웁니다: ① 지금 들고 있어야 하는 것(코어 17자산 모멘텀 상위 4개와 SPY 200일선 "
            "필터, 새틀라이트는 '오늘 기준으로 다시 뽑은 종목'이 주 추천이고 '직전 반기 리밸런싱일에 매수했다면 지금 들고 "
            "있을 종목'은 접어서 참고로 보여 줍니다), ② 과거 같은 길이 구간에서 나온 범위(3개월·6개월 겹치는 구간의 중앙값·5~95백분위·최악 구간·구간 내 "
            "최대낙폭·SPY 대비 초과수익·SPY 를 이긴 구간 비율, 주간 추적 판정이 쓰는 분위 계산과 같은 것), ③ 근거(각 결정의 "
            "확신도 등급, 종목별 돌파 발생일·모멘텀 순위·트레일링스탑 여유·섹터, 기각된 아이디어, 진행 중인 검증 연구 판정), "
            "④ 지금 할 일 — 목표 비중표(target_allocation), '포트폴리오' 화면에 입력한 보유와 비교한 매도/매수 목록(order_plan, "
            "보유가 없으면 '처음 매수'), 추천이 낡았는지(freshness: 지난달 결과이거나 오늘 계산한 코어와 다르면 다시 계산 요청), "
            "다음에 다시 볼 날(next_checkpoints). 어제 밤 저장 상태와의 비교는 코어만 합니다 — 그 저장 상태의 새틀라이트는 "
            "빠른 근사 스캔(다른 방법론)이라 비교하면 매번 '교체 필요'가 뜨기 때문입니다."
        ),
        how_to_use=(
            "챔피언 전략 화면 맨 위 '✅ 지금 할 일' 카드에서 버튼을 한 번 누릅니다. 계산은 백그라운드에서 돌아 수 분 걸릴 수 "
            "있고 다른 화면으로 옮겨도 계속 진행됩니다. 결과는 저장되므로 다시 들어와도 그대로 보이며 '며칠 전 결과'인지 함께 "
            "표시됩니다. 금액 칸을 바꿔도 다시 계산하지 않습니다(결과를 배수로 저장하기 때문). 매일 09:01 KST 에는 자동 잡 "
            "champion_recommendation_daily 가 같은 계산(run_daily_refresh, 사이징 equal)을 미리 돌려 두고 목표 비중·직전 추천 "
            "대비 바뀐 종목·다음 확인일을 텔레그램 1건으로 보냅니다."
        ),
        where_to_see="챔피언 전략 화면 맨 위, 텔레그램 '✅ 오늘의 지금 할 일'(매일 09:01 KST 시작). 계산 결과는 data/cache/champion_recommendation_<해시>.json",
        cautions=(
            "'지금 할 일'의 주문 목록은 계산 결과이고 주문이 아닙니다 — 이 모듈은 주문 경로를 import 하지 않습니다. 분포는 예상 "
            "수익이 아니라 과거 같은 길이 구간의 실적 범위이고, 겹치는 구간이라 독립 표본이 아니므로 p-값처럼 읽으면 안 됩니다. "
            "숫자가 나빠도 그대로 보여 줍니다. 선정 절차는 날짜 인자만 다른 같은 함수이므로 오늘 뽑는 것이 규칙을 벗어나는 "
            "일은 아니지만, 백테스트가 실제로 측정한 것은 1·7월에 시작한 구간들이고 시작 날짜가 결과를 얼마나 흔드는지는 아직 "
            "측정되지 않았습니다(화면에 같은 취지를 적어 두고 기다리라거나 지금 사라고 권하지 않습니다). 다음 재선정일은 "
            "'매수일 + 6개월'로 계산한 값입니다. "
            "트레일링스탑 여유는 표시값이고, 백테스트는 보유 6개월 사이 중도 청산을 검증하지 않았으므로 매도 신호가 아닙니다. "
            "다음 리밸런싱일은 NYSE 휴장일 근사로 구한 예정일입니다. 분포는 주간 추적 잡이 만든 백테스트 캐시가 있어야 나오고, "
            "새틀라이트 슬리브 단독 분포는 '챔피언 성과' 화면의 계산 결과가 저장돼 있을 때만 나옵니다."
        ),
        sources=("core/champion_strategy.py", "core/champion_tracking.py", "core/champion_performance.py",
                 "app/pages/11_챔피언_전략.py"),
        verified="2026-10-02",
    ),
    ModuleGuide(
        module="core/core_lab.py", name="코어 R&D 엔진", group="리서치 인프라", status="실험",
        what="챔피언 코어(17자산 12개월 모멘텀 상위 4개, 월간, SPY 200일선 필터)의 선정 방식을 한 번에 하나씩 바꿔 현 코어와 같은 체결 모델로 비교합니다. 바꿔 볼 수 있는 것: 놀고 있는 현금을 단기국채(BIL)로, 4분할 시차 리밸런싱, 3·6·9·12개월 모멘텀 혼합, 현금보다 나을 때만 사기, 상관 높은 자산 겹치지 않기, 순위 완충, 종목 수, 변동성 반비례 비중, 자산별 추세 필터, 신용 스트레스(HYG/IEF) 필터, 순위를 배당 포함 총수익으로. 현 코어는 라이브 엔진과 일별 비중까지 같게 재현됩니다(테스트로 확인).",
        how_to_use="직접 쓰지 않습니다. 사전 등록 검증 연구 research/jobs/core-rnd-v1·core-rnd-v2 가 이 엔진으로 계산하고, 결과는 관제 센터 '검증 연구 결과'와 저장소 research/results/<id>/REPORT.md 에서 봅니다. v2 가 기준입니다(배당·분배금 포함 총수익).",
        where_to_see="관제 센터 '검증 연구 결과', research/results/core-rnd-v2/REPORT.md",
        cautions="판정(core-judge/v1: 다중검정 보정 DSR·떼어 둔 2년·3구간 일관성·이웃 설정·최대낙폭)은 결과를 보기 전에 고정했습니다. 2026-10-02 실행에서 13개 변형 모두 탈락했습니다 — 현 코어보다 확실히 나은 것을 찾지 못했다는 뜻입니다. 실험 당시 엔진은 가격(Close)만 써서 배당·분배금이 빠져 있었고(v1 이 이 기준), 2026-10-02 사용자 결정으로 코어 엔진은 남는 몫 BIL 을 반영했고(C01), 총수익 순위(C13)는 반영했다가 되돌렸습니다(챔피언 전략 엔진 항목 참고). 판정용 기준선 C00 은 실험 당시 규칙(가격 순위·현금 0)입니다. 통과해도 챔피언에 자동 반영되지 않습니다.",
        sources=("core/core_lab.py", "research/jobs/core-rnd-v1/run.py", "research/jobs/core-rnd-v2/run.py"), verified="2026-10-02",
    ),
    ModuleGuide(
        module="core/crypto_shadow.py", name="코인 추세 슬리브 앞으로 기록", group="리서치 인프라", status="관측 전용",
        what="info-rnd-v1 에서 가장 유망했던 'BTC·ETH 를 100일 지수이동평균 위일 때만 보유하는 5% 슬리브(코어에서 떼어 옴)'를, 과거 데이터는 이미 다 봤으므로 2026-10-06 부터 앞으로만 검증합니다. 매일 밤 각 코인의 보유 여부를 원장(data/crypto_shadow/ledger.jsonl)에 한 줄씩 남기고, 평가는 그 기록만 씁니다(나중에 다시 계산하지 않음).",
        how_to_use="자동입니다(매일 00:37 KST 기록). 경과는 월요일 '[주간 엔진 점검]'의 '코인 추세 기록' 줄에서 봅니다(현 챔피언 대비 누적 초과).",
        where_to_see="텔레그램 '[주간 엔진 점검]', VM data/crypto_shadow/ledger.jsonl",
        cautions="배분에 반영하지 않습니다. 판정(crypto-forward/v1)은 252거래일(약 12개월)이 쌓인 뒤에만 합니다: 현 챔피언 대비 일별 초과수익의 연환산 정보비율 ≥ 0.5 이고 누적 초과 > 0 이면 '도입을 사람이 검토할 후보'입니다. 12개월은 짧아 운의 영향이 큽니다. 과거 백테스트 구간(2015~2024)은 비트코인의 역사적 강세장이었다는 점도 감안해야 합니다.",
        sources=("core/crypto_shadow.py", "scheduler/run_scheduler.py", "research/results/info-rnd-v1/REPORT.md"), verified="2026-10-05",
    ),
    ModuleGuide(
        module="core/engine_audit.py", name="주간 엔진 점검", group="운영·안전", status="운영중",
        what="모든 주식 엔진과 연구 에이전트가 제대로 굴러가는지 한 번에 확인합니다: 서비스 4개 실행 여부, 등록된 자동 잡이 제때 돌았는지, 백업, 실행 중 코드가 main 과 같은지, 검증 연구 실행기가 깨어나고 실패한 작업이 없는지, 새틀라이트 R&D(기준선·계산 오류·준비됐는데 판정 안 된 아이디어·설계 횟수가 상한을 넘은 오염 기록), 지난 7일 야간 AI 에이전트 실행·실패·사용량, 아침 자동 재추천이 매일 저장됐는지, 새벽 미리 계산이 돌았는지, 코인 추세 기록·앞으로 토너먼트 원장이 매일 쌓이는지, 야간 신호와 가격 캐시가 최신인지, 국제정세 의견이 제때 기록됐는지, 디스크 여유.",
        how_to_use="자동입니다. 매주 월요일 08:15 KST 에 텔레그램 '[주간 엔진 점검]' 요약이 정상이어도 옵니다. 지금 바로 보려면 scripts/engine_audit.py 를 실행합니다.",
        where_to_see="텔레그램 '[주간 엔진 점검]', VM data/engine_audit/latest.json",
        cautions="읽기 전용이라 아무것도 고치지 않습니다. 점검 하나가 예외로 실패해도 그 항목만 ❌ 로 남기고 나머지는 계속합니다. 2026-10-05 사람이 손으로 한 점검을 옮긴 것이라 새 엔진이 생기면 항목을 같이 늘려야 합니다.",
        sources=("core/engine_audit.py", "scripts/engine_audit.py", "scheduler/run_scheduler.py"), verified="2026-10-05",
    ),
    ModuleGuide(
        module="core/dawn_precompute.py", name="새벽 미리 계산", group="운영·안전", status="운영중",
        what="낮에 화면에서 버튼을 눌러 기다리던 계산을 기본 설정으로 매일 새벽에 미리 돌려 둡니다: 가격 최신화(장 마감 값으로), 챔피언 성과 최근 5년 백테스트, 챔피언 전략의 point-in-time 새틀라이트·3. 백테스트(최근 3년)·새틀라이트 후보 스캔(S&P500). 화면 버튼과 같은 함수를 부르며 새 전략 로직은 없습니다.",
        how_to_use="자동입니다(매일 06:40 KST, 자동 잡 dawn_precompute). 챔피언 전략·챔피언 성과 화면을 열면 '🌅 새벽 자동 계산 결과' 문구와 함께 바로 보입니다. 다른 설정이나 지금 데이터로 보려면 화면 버튼을 누르면 됩니다.",
        where_to_see="챔피언 전략·챔피언 성과 화면, 실패 시 텔레그램 1건, VM data/cache/dawn_precompute_status.json(최근 실행 기록)",
        cautions="전체 20분 안팎 걸립니다. 한 단계가 실패해도 나머지는 계속합니다. VM 여유가 없으면 최대 20분 기다린 뒤 건너뜁니다. 7일보다 오래된 결과나 다른 사이징·전략 버전의 결과는 화면에 보여 주지 않습니다. 주문 경로와 연결되어 있지 않습니다.",
        sources=("core/dawn_precompute.py", "scheduler/run_scheduler.py", "app/pages/11_챔피언_전략.py", "app/pages/14_챔피언_성과.py"),
        verified="2026-10-05",
    ),
    ModuleGuide(
        module="core/tax_fx.py", name="세후·환전 후 수익 계산", group="분석·백테스트", status="도구",
        what="같은 목표 비중을 실제 계좌처럼 굴려 원화로 얼마가 남는지 계산합니다: 매매 수수료, 환전 스프레드(달러 보유/매번 환전), 해외주식 양도소득세(연 250만 원 공제 후 22%, 다음 해 5월 납부, 이동평균/선입선출), 배당 원천징수 15%(나머지는 받는 날 같은 종목으로 재투자). 선택하면 연말 공제 채우기·손실 확정(12월 마지막 거래일 3일 전에 팔았다 바로 다시 사기)도 넣습니다. 비용·세금 없는 세전 기준선과 '지금 다 팔면 낼 세금'도 함께 냅니다. 대상은 코어만(원하는 시작일부터) 또는 코어 85% + 새틀라이트 15%(새벽 미리 계산한 최근 3년 챔피언 백테스트의 새틀라이트 선정 기록 사용)입니다.",
        how_to_use="'세후 수익 계산' 화면 '📈 전략을 세후로' 탭에서 설정을 고르고 '▶ 계산'을 누릅니다. 세금을 줄이는 매매 규칙 변형의 판정은 연구 작업 tax-rnd-v1 이 이 모듈로 합니다.",
        where_to_see="'세후 수익 계산' 화면",
        cautions="추정치이며 세금 신고용이 아닙니다. 카카오페이증권 수수료·환전 우대는 2026-10 조사값이고, 자동환전 우대율과 취득가액 방식은 확인되지 않았습니다. 금융소득 종합과세는 넣지 않았습니다.",
        sources=("core/tax_fx.py", "app/pages/16_세후_수익_계산.py", "research/jobs/tax-rnd-v1/run.py",
                 "research/jobs/champion-aftertax-v1/run.py"),
        verified="2026-10-05",
    ),
    ModuleGuide(
        module="core/tax_planner.py", name="내 계좌 세금 플래너", group="운용", status="도구",
        what="포트폴리오 화면에 입력한 보유(매입일·단가·수량)를 매입일 환율로 원화 취득가로 바꿔 종목별 원화 손익을 내고, '지금 할 일' 매도마다 실현될 차익과 올해 공제 잔액·다음 해 5월 예상 양도세를 계산합니다. 연말에는 공제 채우기(이익 난 종목을 팔았다 바로 다시 사서 250만 원 공제 사용)·손실 확정(손실 난 종목을 팔았다 바로 다시 사서 상계)을 수량과 함께 제안합니다. 매매 규칙(무엇을 언제 사고파나)은 바꾸지 않습니다.",
        how_to_use="'세후 수익 계산' 화면 '📒 내 계좌 올해 세금' 탭에서 올해 이미 실현한 이익(증권사 앱의 양도세 예상 금액)을 넣고 저장한 뒤 '📒 내 보유로 올해 세금 계산'을 누릅니다. 챔피언 전략 화면 3단계의 '🧾 이 매도들의 세금 미리보기'를 켜면 이번 매도의 세금이 나옵니다. 11/15~12/26 에는 아침 '지금 할 일' 텔레그램에 연말 점검 한 줄이 붙습니다.",
        where_to_see="'세후 수익 계산' 화면, 챔피언 전략 화면 3단계, 아침 텔레그램(11/15~12/26), VM data/tax_year.json(입력한 올해 실현 이익)",
        cautions="추정치이며 신고용이 아닙니다. 포트폴리오 화면의 매입 단가가 수수료를 뺀 값이면 실제보다 이익이 약간 크게 나옵니다. 올해 이미 판 것은 알 수 없어 사용자가 입력한 값만 씁니다. 팔았다 바로 다시 사기를 막는 규정이 한국 해외주식에 없다는 점과 연말 결제일 마감은 증권사 공지로 확인해야 합니다.",
        sources=("core/tax_planner.py", "app/pages/16_세후_수익_계산.py", "app/pages/11_챔피언_전략.py", "core/champion_recommendation.py"),
        verified="2026-10-05",
    ),
    ModuleGuide(
        module="core/forward_tournament.py", name="앞으로 토너먼트", group="리서치 인프라", status="관측 전용",
        what="과거 데이터를 여러 번 판정에 써서 생긴 과적합을 피하려고, 현 코어(T0)와 아깝게 떨어진 후보 5개(T1 비트코인 18번째 자산, T2 9개월 모멘텀 5종목, T3 3~12개월 혼합·상관 제한·순위 완충, T4 4분할 시차 리밸런싱, T5 코어 + 코인 추세 5%)와 비교선(B1 SPY, B2 60/40)의 목표 비중을 2026-10-06 부터 매일 원장(data/forward_tournament/ledger.jsonl)에 한 줄씩 기록합니다. 평가는 기록된 비중만 씁니다(나중에 다시 계산하지 않음).",
        how_to_use="자동입니다(매일 00:39 KST, 자동 잡 forward_tournament_record). R&D 센터에서 '앞으로 토너먼트' 주제로 켜고 끕니다. 경과는 월요일 '[주간 엔진 점검]'에 나옵니다.",
        where_to_see="관제 센터 'R&D 센터'의 '앞으로 기록', 텔레그램 '[주간 엔진 점검]', VM data/forward_tournament/ledger.jsonl",
        cautions="252거래일(약 1년) 전에는 판정하지 않습니다. 판정 규칙(forward-tournament/v1: T0 대비 정보비율 0.5 이상·누적 초과 > 0·최대낙폭이 T0 보다 5%p 넘게 나쁘지 않음)은 기록 시작 전에 고정했고 바꾸려면 새 토너먼트로 다시 등록합니다. PASS 도 사람이 도입을 검토할 후보일 뿐이며 배분·주문과 연결되어 있지 않습니다.",
        sources=("core/forward_tournament.py", "scheduler/run_scheduler.py", "core/engine_audit.py"),
        verified="2026-10-05",
    ),
    ModuleGuide(
        module='core/chart_rendering.py',
        name='전략 차트 그리기',
        group='화면 지원',
        status='도구',
        what=
            '캔들 차트 위에 지표를 겹쳐 그리고 진입·청산 지점에 삼각형 표시를 찍어 주는 그림 그리기 도구입니다.',
        how_to_use=
            '전략 스튜디오에서 전략을 돌리면 자동으로 차트가 그려집니다. 사용자가 직접 부를 일은 없습니다.',
        where_to_see=
            '전략 스튜디오 화면',
        cautions=
            '표시 전용이며 계산 결과를 바꾸지 않습니다.',
        sources=('app/pages/1_전략_스튜디오.py',),
        verified=V,
    ),
    ModuleGuide(
        module='core/corporate_actions.py',
        name='기업행동(배당·분할) 수집',
        group='데이터',
        status='실험',
        what=
            'Alpaca 에서 배당과 주식 분할 같은 기업행동 데이터를 받아 오는 클라이언트입니다. 원장 백테스트에 배당 현금과 분할 조정을 넣기 위한 재료입니다.',
        how_to_use=
            '직접 쓸 일은 거의 없습니다. Alpaca 검증 잡이 이 기능이 정상인지 확인할 때 쓰고, 필요하면 scripts/verify_alpaca_corporate_actions.py 로 수동 확인합니다.',
        where_to_see=
            '화면 없음(검증 결과 파일/텔레그램)',
        cautions=
            '백테스트에 넣는 것은 선택 사항(옵트인)이며 기본 화면·잡의 계산에는 반영되지 않습니다. 호출하지 않으면 기존 동작에 영향이 없습니다.',
        sources=('scripts/verify_alpaca_corporate_actions.py', 'core/trade_ledger.py'),
        verified=V,
    ),
    ModuleGuide(
        module='core/cost_calibration.py',
        name='거래비용 보정',
        group='분석·백테스트',
        status='관측 전용',
        what=
            "실제 모의 체결에서 측정한 슬리피지(가격 미끄러짐)로 백테스트의 비용 가정(5/10/25bp)이 맞는지 보정한 값을 만듭니다. 표본이 30건 미만이면 값을 지어내지 않고 '표본 부족'이라고 남깁니다.",
        how_to_use=
            '매일 밤 00:42(KST) 자동 갱신되어 파일(data/cache/cost_calibration.json)로 저장되고, 전략 변형 shadow 기록이 이 값을 읽습니다. 사용자가 할 일은 없습니다.',
        where_to_see=
            '화면 없음(파일)',
        cautions=
            '관측 전용이며 주문 경로에는 연결돼 있지 않습니다. 수수료는 이 표본으로 측정하지 못해 0 으로 둡니다. 체결 표본이 적은 동안에는 값이 나오지 않는 것이 정상입니다.',
        sources=('scheduler/run_scheduler.py', 'core/strategy_variants.py'),
        verified=V,
    ),
    ModuleGuide(
        module='core/daily_briefing.py',
        name='오늘의 브리핑',
        group='운용',
        status='운영중',
        what=
            '밤사이 다른 잡들이 계산해 둔 결과(신호 변경, 리밸런싱, 실적, 알파 감쇠, 데이터 무결성, 백업, 잡 상태)를 한 장짜리 HTML 로 모아 텔레그램으로 보냅니다. 새로 계산하지 않고 읽기만 합니다(알파 감쇠 재계산 제외).',
        how_to_use=
            "매일 00:25(KST)에 텔레그램으로 문서가 옵니다. 아침에 이것 하나만 열어 '오늘 확인할 일이 있나' 를 30초 안에 훑어보면 됩니다.",
        where_to_see=
            '텔레그램(HTML 문서)',
        cautions=
            '다른 잡이 먼저 돌아야 내용이 최신입니다. 어떤 잡이 실패했다면 그 부분은 비어 있거나 낡은 값일 수 있습니다.',
        sources=('scheduler/run_scheduler.py',),
        verified=V,
    ),
    ModuleGuide(
        module='core/data_integrity.py',
        name='데이터 무결성 검사',
        group='운영·안전',
        status='운영중',
        what=
            "가격·FRED 거시 캐시·뉴스 캐시에 0원 종가, 하루 이상 낡은 값 같은 '에러 없이 조용히 이상한 값' 이 있는지 점검합니다. 2026-09-26부터 데이터 소스가 멈춰 같은 봉을 날짜만 바꿔 되풀이하는 경우(종가·거래량이 같은 봉 3거래일 연속, 거래량이 없으면 종가 6거래일 연속)도 경고합니다. 읽기만 하고 데이터를 고치지는 않습니다.",
        how_to_use=
            '매일 00:22(KST)에 자동으로 돌고, 이상이 발견될 때만 텔레그램 경고가 옵니다(이상 없으면 조용). 경고가 오면 어떤 데이터인지 읽고 해당 화면 값을 신뢰하지 않은 채 확인하세요. 2026-09-25부터 VM 에 Alpaca 키가 있으면 챔피언 코어·위성 보유 종목과 SPY(최대 10개)의 가격을 Alpaca 일봉과도 대조합니다.',
        where_to_see=
            '텔레그램(이상 발견 시), 오늘의 브리핑, VM 스케줄러 로그(교차 대조 전체 결과)',
        cautions=
            "알림이 없다는 것이 데이터가 완벽하다는 뜻은 아닙니다. 정해진 몇 가지 검사만 합니다. 교차 대조는 종가 큰 불일치와 분할 의심만 텔레그램으로 알리고, 같은 종목·같은 날짜의 불일치는 한 번만 알립니다(조회 불가 같은 나머지는 로그에만). 어느 소스가 옳은지는 판정하지 않습니다. Alpaca 키가 없으면(Codespace) 교차 대조 없이 예전 그대로 동작합니다. 오늘의 브리핑의 데이터 이상 섹션에는 교차 대조가 들어가지 않습니다.",
        sources=('scheduler/run_scheduler.py', 'core/price_crosscheck.py'),
        verified="2026-09-26",
    ),
    ModuleGuide(
        module='core/earnings_events.py',
        name='실적 보도자료·가이던스 추출',
        group='데이터',
        status='실험',
        what=
            'SEC EDGAR 의 8-K(Item 2.02) 실적 보도자료를 받아 발행사가 밝힌 향후 전망(가이던스) 문장을 규칙 기반으로 뽑아내는 연구용 모듈입니다.',
        how_to_use=
            '직접 쓸 일은 없습니다. 가이던스 shadow 기록의 SEC 공급기가 내부에서 쓰며, 수동 표본 확인은 scripts/earnings_guidance_extraction_sample.py 로 합니다.',
        where_to_see=
            '화면 없음',
        cautions=
            "연구용이며 주문·화면과 연결돼 있지 않습니다. 추출 정확도나 성과를 주장하지 않습니다. 2026-09-25부터 가이던스 shadow 야간 잡(00:30 KST)이 SEC 조회를 켜므로 이 모듈이 매일 밤 위성 후보 종목(최대 20개)에 대해 실제로 돕니다. 2026-09-25부터 상향·하향·유지 판정은 '연간 가이던스를 같은 회계연도끼리 다시 발표했을 때'만 냅니다. 분기 가이던스는 매번 새 분기를 가리켜 같은 기간끼리 비교할 수 없고, 다른 분기끼리 비교하면 계절성·성장이 섞이므로 항상 '판단 불가(unknown, quarterly_not_comparable)'입니다. 같은 발표에 다음 해 가이던스가 함께 있으면 끝난 해의 수치(실적일 가능성)는 비교하지 않습니다. 각 판정에는 비교 방식, 비교에 쓴 직전 발표 번호·시각·대상 기간, 세부 사유(no_prior_same_fy, unit_mismatch 등)가 남습니다. 분기 가이던스만 내거나 보도자료에 가이던스가 없는 기업은 방향이 나오지 않으며, 현재 추출기로는 revenue·eps 항목의 약 80%가 판단 불가입니다(스펙 6절 조사).",
        sources=('docs/EARNINGS_GUIDANCE_EXPERIMENT_SPEC.md', 'scripts/earnings_guidance_extraction_sample.py', 'core/guidance_event_provider.py'),
        verified="2026-09-25",
    ),
    ModuleGuide(
        module='core/era_validation.py',
        name='시대별 강건성 검증',
        group='분석·백테스트',
        status='도구',
        what=
            '이미 정한 전략 설정을 재조정 없이 성격이 다른 여러 시대(약세장, 패닉, 횡보 등)에 다시 돌려, 강세장에서만 좋아 보인 것은 아닌지 확인합니다.',
        how_to_use=
            '전략 스튜디오에서 전략을 만든 뒤 시대별 검증 항목을 실행해 시대마다 성과가 어떻게 다른지 봅니다.',
        where_to_see=
            '전략 스튜디오 화면',
        cautions=
            '과거 시대 구간에 대한 백테스트일 뿐이라 통과했다고 앞으로도 통한다는 뜻은 아닙니다.',
        sources=('app/pages/1_전략_스튜디오.py',),
        verified=V,
    ),
    ModuleGuide(
        module='core/etf_holdings.py',
        name='ETF 구성종목 조회',
        group='데이터',
        status='도구',
        what=
            'SPY, XLK 같은 SPDR 계열 ETF 의 구성종목을 운용사 파일에서 받아 옵니다. iShares 등 자동 연동이 막힌 ETF 와 국내 ETF 는 CSV/엑셀 업로드로 읽습니다.',
        how_to_use=
            '거장 포트폴리오 화면에서 ETF 를 조회하거나 파일을 올려 구성종목을 봅니다.',
        where_to_see=
            '거장 포트폴리오 화면',
        cautions=
            '자동 조회는 SPDR 계열만 됩니다. 나머지는 직접 파일을 올려야 합니다.',
        sources=('app/pages/4_거장_포트폴리오.py',),
        verified=V,
    ),
    ModuleGuide(
        module='core/execution_reconciliation.py',
        name='체결 대조 엔진',
        group='분석·백테스트',
        status='도구',
        what=
            '실제 Alpaca 모의 체결을 백테스트 원장과 같은 형식으로 바꿔 실측 슬리피지, 예상 대비 체결 수량, 주문-체결 지연, 미체결/부분체결/거절을 계산합니다.',
        how_to_use=
            '필요할 때 VM 에서 scripts/reconcile_paper_fills.py 를 수동으로 돌려 결과를 봅니다. 자동 잡은 없습니다(비용 보정 잡이 이 계산을 재사용).',
        where_to_see=
            '화면 없음(스크립트 출력)',
        cautions=
            "표본이 30건 미만이면 대표값을 주장하지 않고 '표본 부족'으로 표시합니다. 모의 계좌 체결이라 실제 시장 체결과 다를 수 있습니다.",
        sources=('scripts/reconcile_paper_fills.py', 'core/cost_calibration.py'),
        verified=V,
    ),
    ModuleGuide(
        module='core/expression_engine.py',
        name='직접 수식 해석기',
        group='분석·백테스트',
        status='도구',
        what=
            "'close > sma(close, 20) and rsi(close, 14) < 30' 처럼 사용자가 직접 쓴 조건식을 안전하게 해석해 매수 조건으로 씁니다. 허용된 함수와 변수만 계산하도록 막아 임의 코드가 실행되지 않게 합니다.",
        how_to_use=
            '전략 스튜디오의 직접 수식 입력칸에 조건을 쓰면 이 모듈이 검사하고 계산합니다. 문법이 틀리면 화면에 오류 이유가 나옵니다.',
        where_to_see=
            '전략 스튜디오 화면',
        cautions=
            '조건이 맞아 보여도 성과가 좋다는 뜻은 아닙니다. 허용되지 않은 함수는 쓸 수 없습니다.',
        sources=('app/pages/1_전략_스튜디오.py',),
        verified=V,
    ),
    ModuleGuide(
        module='core/filing_changes.py',
        name='공시 변화 추출·veto 규칙',
        group='데이터',
        status='실험',
        what=
            'SEC 10-K/10-Q 공시를 받아 위험요인 등의 문장이 직전 공시보다 새로 생기거나 바뀐 것을 찾고, 악재로 볼 만한 변화에 규칙으로 태그를 붙입니다. 공시 변화가 있으면 매수를 보류할지(veto) 판정하는 규칙도 있습니다.',
        how_to_use=
            '직접 쓸 일은 없습니다. 공시 변경 veto shadow 기록이 내부에서 쓰고, 수동 점검은 scripts/filing_change_extraction_check.py 로 합니다.',
        where_to_see=
            '화면 없음',
        cautions=
            "사전 등록 스펙이 아직 동결되지 않은 연구 단계입니다. 관측 전용이며 성과는 미검증입니다. 문장을 못 찾으면 추측하지 않고 '섹션 없음' 으로 남깁니다.",
        sources=('docs/FILING_CHANGE_VETO_SPEC.md', 'scripts/filing_change_extraction_check.py', 'core/filing_veto_shadow.py'),
        verified=V,
    ),
    ModuleGuide(
        module='core/filing_veto_shadow.py',
        name='공시 변경 veto shadow 기록',
        group='리서치 인프라',
        status='관측 전용',
        what=
            "챔피언 위성의 후보 풀(돌파가 켜진 후보 전체: 실제 채택 종목 + 상위 3위 밖 후보)에 '공시 변화 때문에 보류(veto)했다면?' 판정을 병행 기록합니다. 원래 채택 결정은 건드리지 않고 기록에 그대로 옮겨 적습니다(2026-09-25부터 채택 종목만이 아니라 풀 전체, 기록 버전 v2).",
        how_to_use=
            '매일 밤 00:32(KST) 자동으로 기록됩니다. 사용자가 할 일은 없습니다. 꺼두려면 텔레그램 /processes 를 씁니다.',
        where_to_see=
            '화면 없음(DB)',
        cautions=
            "veto 가 hold 로 나와도 실제 주문은 바뀌지 않습니다. 스펙 미동결·성과 미검증이며, 종목별 SEC 조회에 실패하면 그 종목은 '통과'로 처리합니다. SEC 조회 상한: 하루 최대 20종목, 요청 약 150회, 5분(종목 사이에서 확인). 넘치면 채택 종목 먼저, 그다음 모멘텀 순위 순으로 조회하고 나머지는 '조회 안 함(missing_data)'으로 남습니다. 풀을 넓혀 관측 종목은 약 3개에서 최대 20개로 늘었지만, 가정값으로 추정하면 최소 표본(보류 100건)까지 여전히 10년 이상 걸릴 수 있어 가까운 시일에 결론이 나지 않습니다(스펙 문서 §9).",
        sources=('scheduler/run_scheduler.py', 'docs/FILING_CHANGE_VETO_SPEC.md', 'core/filing_veto_shadow.py'),
        verified='2026-09-26',
    ),
    ModuleGuide(
        module='core/fred_data.py',
        name='FRED 거시지표 조회',
        group='데이터',
        status='운영중',
        what=
            '미국 연준(FRED)의 금리·물가·고용 같은 거시지표를 받아 파일로 캐시합니다. 키가 없거나 호출이 실패해도 오류를 던지지 않고 빈 값을 돌려주며, 일시적 네트워크 문제는 몇 번 재시도합니다.',
        how_to_use=
            '시장 진단 화면의 거시 지표가 이 데이터를 씁니다. 매일 00:20(KST)에 미리 갱신(예열)하는 잡이 있어 사용자가 할 일은 없습니다.',
        where_to_see=
            '시장 진단 화면',
        cautions=
            'FRED_API_KEY 가 없으면 화면에 지표가 비어 있을 수 있습니다. 발표 지연이나 나중 수정된 값이 그대로 반영될 수 있어 발표 당시 값(PIT)이 아닙니다.',
        sources=('app/pages/7_시장_진단.py', 'scheduler/run_scheduler.py'),
        verified=V,
    ),
    ModuleGuide(
        module='core/gemini_client.py',
        name='Gemini AI 호출 도우미',
        group='화면 지원',
        status='운영중',
        what=
            'AI(Gemini) 호출을 한곳에서 처리합니다. 한 키의 무료 한도가 다 되면 다음 키, 그다음 모델로 자동으로 넘어가고, 그 밖의 실패는 호출한 쪽의 기본 대체 로직으로 넘깁니다.',
        how_to_use=
            '자연어 전략 입력, Threads 요약, 포트폴리오 설명 등 AI 기능이 있는 화면에서 자동으로 쓰입니다. AI 답이 안 나오면 키 한도 소진일 수 있으니 환경설정에서 키를 확인하세요.',
        where_to_see=
            '화면 없음(AI 기능이 있는 각 화면)',
        cautions=
            '무료 한도가 있어 하루 사용량이 많으면 실패하거나 기본 대체 결과가 나올 수 있습니다. 키 값은 기록·표시하지 않습니다.',
        sources=('core/nl_strategy.py', 'core/threads_summary.py'),
        verified=V,
    ),
    ModuleGuide(
        module='core/guidance_event_provider.py',
        name='가이던스 SEC 데이터 공급기',
        group='데이터',
        status='실험',
        what=
            '가이던스 shadow 실험용으로 티커에서 SEC 회사코드, 8-K 실적 발표, 가이던스 추출까지 이어서 실제 SEC 자료로 관측 목록을 만들어 주는 공급기입니다. 파싱 규칙은 새로 만들지 않고 기존 모듈을 호출합니다.',
        how_to_use=
            '직접 쓸 일은 없습니다. 매일 밤 00:30(KST) 가이던스 shadow 잡이 호출합니다(fetch_events=True). 결과 요약(조회 종목 수, 실패 수, 관측 수, 방향 판정 수와 판단 불가 수, SEC 요청 수/상한)은 VM 의 스케줄러 로그에 한 줄로 남습니다.',
        where_to_see=
            '화면 없음',
        cautions=
            "안전장치: 한 번에 최대 20종목, SEC 요청 약 300회·5분 상한(종목과 종목 사이에서 확인), 같은 날 다시 돌면 하루 캐시 재사용, SEC 가 403 으로 막으면 즉시 멈추고 잡은 실패로 죽지 않습니다. User-Agent 는 VM .env 의 SEC_EDGAR_USER_AGENT 이름으로 읽으며 값은 기록하지 않습니다. 이 이름이 없으면 SEC 가 막을 수 있습니다. 방향 판정은 연간 가이던스의 같은 회계연도 재발표끼리만 나오고 분기 가이던스는 항상 '판단 불가(unknown)'입니다. 요약에 그 수와 사유가 따로 나옵니다. 같은 회계연도의 직전 값은 보통 바로 앞 분기 발표에 있어 과거 조회 범위(400일, 종목당 발표 6건)는 그대로 두었습니다. 최악의 경우 종목당 요청 13회 × 20종목 = 260회로 상한 안입니다. 2026-09-25 비교 정책 변경 때 캐시 형식을 올려, 예전 방식으로 만든 같은 날 캐시는 다시 쓰지 않습니다. 성과 미검증입니다.",
        sources=('core/guidance_shadow.py', 'scheduler/run_scheduler.py', 'core/earnings_events.py'),
        verified="2026-09-25",
    ),
    ModuleGuide(
        module='core/guidance_shadow.py',
        name='가이던스 shadow 기록',
        group='리서치 인프라',
        status='관측 전용',
        what=
            "챔피언 위성 후보 풀(돌파가 켜진 후보 전체: 채택 종목 + 상위 3위 밖 후보)에 '발행사가 실적 전망을 올렸나/내렸나' 신호를 나란히 붙여 기록합니다. 원래 위성의 채택·보류 결정은 그대로 옮겨 적을 뿐 절대 바꾸지 않습니다(2026-09-25부터 풀 전체, 기록 버전 v2).",
        how_to_use=
            '매일 밤 00:30(KST) 자동으로 기록됩니다. 사용자가 할 일은 없습니다. 꺼두려면 텔레그램 /processes 를 씁니다.',
        where_to_see=
            '화면 없음(DB)',
        cautions=
            "관측 전용이며 원전략과 실제 주문에 영향이 없고 성과는 미검증입니다. 2026-09-25부터 야간 잡이 실제 SEC 조회를 켜서 호출합니다. 다만 최근 20거래일 안에 실적 발표가 없는 후보는 여전히 '발표 없음'이고, 발표가 있어도 분기 가이던스는 대부분 '판단 불가'로 기록됩니다. SEC 가 막히면 그날은 모든 후보가 '발표 없음'으로 기록됩니다. 후보가 20종목을 넘으면 채택 종목 먼저, 그다음 모멘텀 순위 순으로 조회하고 나머지는 건너뜁니다. 각 후보의 조회 결과(guidance_fetch_status)가 함께 남으니, '발표 없음' 중 실제로 조회하지 못한 후보를 구분할 수 있습니다.",
        sources=('scheduler/run_scheduler.py', 'docs/EARNINGS_GUIDANCE_EXPERIMENT_SPEC.md', 'core/guidance_shadow.py'),
        verified='2026-09-26',
    ),
    ModuleGuide(
        module='core/guru_schedule.py',
        name='거장 자동 동기화',
        group='데이터',
        status='운영중',
        what=
            '추적 중인 거장(버핏 등 13F 공시 거장, 캐시 우드 ARK)의 보유 종목을 전체 순회해 자동으로 갱신합니다. 한 명이 실패해도 나머지는 계속하고, 13F 는 새 분기 공시가 있을 때만 다시 읽습니다.',
        how_to_use=
            '매일 12:00(KST) 자동으로 돌고 변동이 있으면 텔레그램으로 알림이 옵니다. 거장 포트폴리오 화면에서 마지막 자동 동기화 상태를 확인할 수 있고, 수동 동기화 버튼도 있습니다.',
        where_to_see=
            '거장 포트폴리오 화면 + 텔레그램 알림',
        cautions=
            '13F 는 분기 공시라 최대 수개월 전 보유 내역입니다(ARK 만 매일). 실시간 매매가 아닙니다.',
        sources=('app/pages/4_거장_포트폴리오.py', 'scheduler/run_scheduler.py'),
        verified=V,
    ),
    ModuleGuide(
        module='core/guru_tracker.py',
        name='거장 포트폴리오 추적',
        group='데이터',
        status='운영중',
        what=
            'SEC 13F 공시를 읽어 거장의 최신 보유 종목을 가져오고, 티커를 찾아 DB 에 저장합니다. ARK 는 매일 공개되는 CSV 를 쓰고, 여러 거장이 함께 담은 종목(공통 보유)도 계산합니다. 커스텀 거장 추가도 됩니다.',
        how_to_use=
            '거장 포트폴리오 화면에서 보유 종목과 공통 보유 종목을 봅니다. 자동 갱신은 거장 자동 동기화 잡이 맡습니다.',
        where_to_see=
            '거장 포트폴리오 화면, 챔피언 전략 화면 일부',
        cautions=
            '13F 는 분기 후 최대 45일 뒤에 공개되고 공매도·비미국 자산은 나오지 않습니다. 종목명으로 티커를 추정하므로 드물게 틀릴 수 있습니다.',
        sources=('app/pages/4_거장_포트폴리오.py', 'core/guru_schedule.py'),
        verified=V,
    ),
    ModuleGuide(
        module='core/indicators.py',
        name='기술적 지표 계산',
        group='분석·백테스트',
        status='도구',
        what=
            '이동평균, RSI, 볼린저밴드, MFI 같은 기술적 지표를 가격표에서 계산하는 함수 모음입니다. 전략 엔진이 이 함수들을 조합해 매매 신호를 만듭니다.',
        how_to_use=
            '차트 조회와 전략 스튜디오에서 지표를 켜면 자동으로 계산됩니다. 직접 부를 일은 없습니다.',
        where_to_see=
            '차트 조회, 전략 스튜디오 화면',
        cautions=
            '지표 값은 과거 가격에서 계산한 것이라 미래를 예측하지 않습니다.',
        sources=('app/pages/9_차트_조회.py', 'core/strategy_engine.py'),
        verified=V,
    ),
    ModuleGuide(
        module='core/info_dedup.py',
        name='정보 중복 제거·비용 집계',
        group='리서치 인프라',
        status='실험',
        what=
            '같은 내용의 기사·공시를 여러 개의 독립 근거로 세지 않도록 원문 해시로 중복을 제거하고, 정보 수집 비용과 추출 품질을 집계하는 유틸입니다.',
        how_to_use=
            '직접 쓸 일은 없습니다. 2026-09-25부터 가이던스 shadow(00:30)와 공시 veto shadow(00:32) 야간 기록이 이 도구로 후보 행마다 근거 공시의 사건 ID(event_id, 공시 접수번호 기준)와 원문 해시를 채웁니다. 같은 8-K·10-K 가 여러 날·여러 후보 행에 반복돼도 같은 ID 라서 나중에 분석할 때 한 건의 근거로 묶을 수 있습니다.',
        where_to_see=
            '화면 없음(후보 원장 DB 의 event_id·info_content_hash 열)',
        cautions=
            '지금은 ID 와 해시를 기록만 합니다. 후보 원장의 판정 계산이 이 ID 로 중복을 자동으로 걸러 주지는 않습니다(그 계산 모듈은 바꾸지 않았음). 근거 공시가 없는 후보 행은 비워 두고 ID 를 지어내지 않습니다. 비용 집계·추출 품질 집계 함수는 아직 호출하는 곳이 없습니다.',
        sources=('docs/INFORMATION_DECISION_ENGINE_RESEARCH.md', 'core/guidance_shadow.py', 'core/filing_veto_shadow.py'),
        verified=V,
    ),
    ModuleGuide(
        module='core/job_health.py',
        name='잡 실행 이력·건강 판정',
        group='운영·안전',
        status='운영중',
        what=
            "자동 잡이 돌 때마다 성공·실패·누락을 DB 에 한 줄씩 기록하고, '지금쯤 돌았어야 할 잡이 실제로 돌았나' 를 판정합니다. 조용한 실패를 찾는 것이 목적입니다. 잡이 시작되고 끝날 때 '지금 실행 중' 표시도 남겨, 관제 센터에서 실행 중인 잡을 볼 수 있게 합니다.",
        how_to_use=
            '오늘 화면과 오늘의 브리핑에서 잡 상태로 자동 표시됩니다. 실패/누락 표시가 보이면 해당 잡의 로그를 확인하세요. 지금 돌고 있는 잡은 관제 센터 → 지금 돌고 있는 작업(/live)에서 봅니다.',
        where_to_see=
            '오늘 화면, 오늘의 브리핑, 관제 센터 /live',
        cautions=
            '꺼둔 잡은 안 돈 것이 정상으로 취급합니다. 잡 함수가 스스로 예외를 삼키는 경우는 별도로 실패 보고를 남긴 잡만 잡아냅니다.',
        sources=('scheduler/run_scheduler.py', 'core/today_dashboard.py'),
        verified="2026-09-27",
    ),
    ModuleGuide(
        module='core/job_manager.py',
        name='백그라운드 작업 실행기',
        group='화면 지원',
        status='운영중',
        what=
            '오래 걸리는 계산을 별도 스레드에서 돌려 화면을 옮겨도 끊기지 않게 합니다. 실행 중인 작업 목록을 사이드바에 보여 줍니다.',
        how_to_use=
            '각 화면에서 무거운 계산을 시작한 뒤 다른 화면으로 가도 계속 돕니다. 돌아와서 결과를 보면 됩니다. 별도 조작은 필요 없습니다.',
        where_to_see=
            '각 화면(사이드바의 실행 중 작업)',
        cautions=
            '서버(앱)를 재시작하면 실행 중이던 작업은 사라집니다. 1인 사용 전제의 단순한 구조입니다.',
        sources=('app/pages/11_챔피언_전략.py',),
        verified=V,
    ),
    ModuleGuide(
        module='core/kostolany_cycle.py',
        name='코스톨라니 달걀 국면 판정',
        group='분석·백테스트',
        status='운영중',
        what=
            '가격과 거래량만으로 시장과 섹터가 코스톨라니 달걀 6국면(A1~B3) 중 어디쯤인지 근사합니다. 52주 범위 내 위치와 거래량 비율, 추세로 판정하고 스냅샷을 저장합니다.',
        how_to_use=
            '시장 진단 화면에서 현재 국면을 봅니다. 매일 00:00(KST) 시장 스냅샷 잡이 자동으로 저장합니다.',
        where_to_see=
            '시장 진단 화면',
        cautions=
            '투자자 심리 데이터가 없어 가격·거래량으로 근사한 것이라 원래 이론과 다릅니다. 국면 판정이 매매 신호가 되는 것은 아닙니다.',
        sources=('app/pages/7_시장_진단.py', 'scheduler/run_scheduler.py'),
        verified=V,
    ),
    ModuleGuide(
        module='core/kostolany_scenario_engine.py',
        name='코스톨라니 시나리오 백테스트',
        group='분석·백테스트',
        status='도구',
        what=
            '과거 내내 코스톨라니 국면 신호(매수 관심이면 진입, 매도 검토면 청산 또는 인버스)를 따랐다면 어떤 결과였을지 백테스트합니다. 지수, 종목, 테마 단위로 돌릴 수 있습니다.',
        how_to_use=
            '시장 진단 화면에서 시나리오를 실행해 과거 수익 곡선과 매매 시점을 봅니다.',
        where_to_see=
            '시장 진단 화면',
        cautions=
            '과거 백테스트이며 성과를 보장하지 않습니다. 국면 근사 자체의 한계도 그대로 이어받습니다.',
        sources=('app/pages/7_시장_진단.py',),
        verified=V,
    ),
)

# 사용자에게 설명할 필요 없는 내부 유틸: {"core/x.py": "이유"}
INTERNAL: dict = {
    'core/app_navigation.py': '화면 메뉴 구조를 담은 순수 데이터로, 사용자에게는 화면 목록 절이 이미 이 내용을 보여 줌',
    'core/db.py': 'SQLite 연결·세션을 여는 내부 배관으로 사용자가 직접 보거나 조작할 것이 없음',
    'core/job_schedule.py': '자동 잡 시각표 데이터로, 잡 목록 절이 코드에서 직접 읽어 자동 표시하므로 별도 설명 불필요',
}
