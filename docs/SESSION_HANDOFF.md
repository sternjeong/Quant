# 세션 인계

최종 갱신: 2026-09-25 (관제 센터 사용 설명서 + 설명서 작성 중 발견한 결함 5건 수정)

## 최신 상태 요약

- **커밋 상태(2026-09-24 갱신):** 브랜치 `engine-upgrade-2026-09` 에 두 커밋으로 보존했다 — `9cf9e70`(엔진 정합성·주문 게이트·후보 shadow 원장), `874512d`(Alpaca 활용 4종·거장 자동 추적·가이던스 provider). **push 하지 않았다**(main 에 올리면 VM 이 5분 내 자동 배포하므로 사용자 승인 필요). 사용자 소유가 아닌 `COPY_ME.md`·`new/` 는 커밋에서 제외했다. 커밋 전 비밀값·이메일·live 엔드포인트 스캔 통과.
- **VM 위험(해소 전):** VM 이 받아간 `origin/main` 의 `core/paper_execution.py`·`scripts/champion_paper_trade.py` 는 **구버전**이라 주문 게이트·회차 ID·멱등성이 없고, SPY 결측 시 목표비중 0 → 보유 전량 매도 계획을 만드는 청산 버그가 그대로 있다. 스케줄러가 주문 스크립트를 호출하지 않고 사람이 `--submit --confirm` 을 줘야만 주문이 나가므로 자동 사고 위험은 없으나, **푸시 전까지 그 스크립트를 `--submit` 으로 실행하면 안 된다.**
- **Alpaca paper 키:** VM `/opt/quant/.env` 에 등록됨(이름·길이만 확인, 값 미확인). Codespace 에는 없다. **실제 API 호출은 아직 0회** — 아래 4개 모듈의 응답 스키마는 전부 문서 기반 가정이며 VM 검증 스크립트 실행 전까지 신뢰하면 안 된다.
- 전체 `pytest tests` **1644 passed**(2026-09-24, 이 세션이 직접 실행).

- ENG-01·02·03·04·05·07·10은 아래 2차 통합 표의 단계까지 구현됐다. 전체 pytest 1120건 통과는 사용자와 기존 세션이 직접 실행한 기록이며, 이번 연구 세션에서는 재실행하지 않았다.
- **주문 게이트·회차 관리(3차, 아래 절 참고)는 구현·단위 테스트까지 완료했다. paper API 실계정 검증은 여전히 0건이다.** 야간 CI의 legacy/v2 분리, 전략 스튜디오 legacy 배지, 주문 회차 수동 종료 도구(`scripts/paper_run_admin.py`)는 이번에 구현했다.
- ENG-01의 실제 캐시 Close는 AAPL 2020-08 구간에서 분할 반영 상태였다. 조정 헬퍼의 실제 차이는 배당 재투자 총수익 기준이며, 과거의 “분할 왜곡” 설명은 실제 캐시에는 적용하지 않는다.
- [정보 수집·판단 엔진 연구](./INFORMATION_DECISION_ENGINE_RESEARCH.md)의 RES-01(모든 후보 shadow 원장)은 **구현·단위 테스트 완료 + 스케줄러 연결 완료**(아래 절). RES-04(가이던스 변화)·RES-05(공시 변화 veto)는 추출기·스펙까지 구현했고 실제 EDGAR 표본도 받았으나, 개별주 위성 신호 연결과 사람 검증은 아직이다. 신규 수익·승률 개선은 전부 미입증이며 세 제안 모두 주문 경로에 연결하지 않았다.
- Streamlit 첫 화면은 긴 모듈 안내문에서 `오늘` 명령 센터로 교체했다(다른 세션 작업). 저장된 챔피언 신호·시장 국면·작업·백업·관심종목 알림만 읽어 현재 상태와 다음 확인 항목을 보인다. 홈 진입은 새 시장 스캔이나 주문을 실행하지 않는다.
- Streamlit UI 2차로 사이드바를 홈/운용/탐색/리서치/시장/시스템 업무공간으로 재구성하고, 13개 상세 페이지에 `기준 시각 / 신선도 / PIT / 전략 버전` 공통 헤더를 적용했다. 전체 pytest 1463건과 홈·환경설정·Threads 헤드리스 렌더링이 통과했다. 커밋·VM 배포·실브라우저 검증은 하지 않았다.
- **공유 Codespace 이력:** 엔진 고도화 3차 세션과 UI 재구성 세션이 동시에 작업했다. 엔진 세션은 UI 파일을 건드리지 않았고, UI 2차 세션은 최신 엔진 문서 변경을 보존한 채 인계 내용을 병합했다. 다음 에이전트도 먼저 `git status`로 동시 변경 여부를 확인한다.
- **아직 커밋되지 않은 작업이 많다.** 이 세션의 엔진 변경(`core/candidate_ledger.py`, `core/candidate_recorder.py`, `core/earnings_events.py`, `core/filing_changes.py`, `core/trade_ledger.py`, `core/tuning_ledger.py` 등)과 이전 세션들의 ENG-01~10 변경이 모두 아직 로컬 작업트리에만 있다. 사용자는 별도 브랜치(`engine-upgrade-2026-09` 제안, 아직 승인 대기)로 커밋하는 방안을 논의 중이었다. **push는 사용자 승인 없이 하지 않았다.**
- 이 최신 요약이 아래 과거 세션의 당시 상태보다 우선한다. 과거 기록은 의사결정 이력 보존을 위해 삭제하지 않았다.

## 2026-09-25 S6 승인 버튼·paper 편입 + 역할별 모델 UI (구현·단위 테스트, 배포 전)

- **승인 버튼:** 승격 후보 텔레그램 알림에 [✅ paper 편입][🗑 종료]. 러너(`h:` 콜백)가 `scripts/hypothesis_admin.py` 를 venv 로 실행, id 정규식·채팅 id 검증.
- **paper 편입:** `core/research_sleeve.py` + `paper_execution` research 슬리브 게이트(fail-closed) + `champion_paper_trade.build_plan(research=)` + `paper_auto_trade` 연결. 슬리브 10%/가설당 5%, 기록 5일 초과 시 슬리브 보류. research=None 이면 계획이 도입 전과 비트 동일(테스트로 고정).
- **역할별 모델:** 허브 `/research` 드롭다운(POST, Origin 검사) + 텔레그램 `/models` 순환 버튼, 공유 파일 `data/agent_models.json`(gitignore·백업). 예산 추정은 모델 단가 비율(haiku 0.25·sonnet 1·opus 2.5)로 조정.
- **함께 고친 기존 결함:** ① 텔레그램 `/processes` 목록에 레지스트리 잡 14개가 빠져 있었음(`paper_auto_trade` 포함 — 이전에 "/processes 로 켜라"고 안내한 버튼이 실제로 없었다) → 전부 추가 + 동기화 테스트. ② shadow 가 00:48 KST(미 장중)에 미완성 당일 봉을 쓸 수 있었음 → 16:15 ET 이전 당일 봉 제외. ③ 백업이 `.gitignore` 된 허용 파일(`data/process_toggles.json`)을 한 번도 백업하지 않았음 → 무시된 정확한 파일 항목을 직접 포함.
- 검증: 신규·수정 테스트(research 슬리브 11, 모델 6, 러너 3, 백업 1). 실 텔레그램 버튼·VM 실행 미검증.

## 2026-09-25 에이전트 결합형 퀀트 시스템 S1~S5 구현 (단위 테스트, 배포 전)

- 사용자 결정: [AGENTIC_QUANT_SYSTEM_DESIGN.md](./AGENTIC_QUANT_SYSTEM_DESIGN.md) 추천안 채택, 에이전트 배치 **03:00 KST**, 토큰 예산 위임 → 하룻밤 $15·주간 $60(API 환산), 역할별 상한은 설계 문서 8절.
- 구현: 가설 스펙·레지스트리(시도 카운터, 주간 동결 10·shadow 20), 백테스트 엔진·심판(DSR·레짐·상관·kill), shadow(00:48 잡, 60거래일 판정), 에이전트 배치(03:00 잡, 역할 5종 프롬프트, 권한 제한·git 가드·비밀값 제거), 허브 `/research`, `scripts/hypothesis_admin.py`.
- 검증: 신규 테스트 24건(가짜 에이전트로 Scout→Writer→Implementer→Critic→동결→심판 한 밤 전체 흐름, 합성 데이터로 좋은 전략 통과·시장 복제 탈락, shadow 기록·z 판정). **실제 Claude CLI 호출·VM 실행·실 가격 심판은 미검증.**
- 미구현: 텔레그램 승인 버튼, 승격 가설의 paper 자동 편입(현재 admin 스크립트로 상태만 전이).
- 주의: `research/hypotheses/`·`research/scout/`·`research/failures.md`·`data/agent_usage.jsonl` 은 VM 에서 생기는 미추적 파일 — 저장소에 커밋하지 말 것(자동 배포 pull 충돌 방지). 백업 허용 목록에 추가함.
- 다음: 푸시 → VM 첫 03:00 배치 결과(텔레그램·허브 `/research`) 확인 → CLI 플래그(`--allowedTools` 경로 규칙 등)가 VM 의 claude 버전과 맞는지 점검.

## 2026-09-25 관제 센터 개선 (구현·단위 테스트, 배포 전)

사용자 선택: 잡 건강 표시·운영 상태 페이지·카테고리/새로고침·리포트 슬롯·낡은 문서(1,4,5,6,7번). 로그인 횟수 제한 등 3번은 하지 않음.
- `hub/ops_status.py`(신규)+`/ops`: 잡 건강(`core.job_health`), 백업 status.json, 서버 자원, 타이머 유닛. 항목별 실패 격리. 스케줄러 카드에 "잡 이상 N개" 배지.
- 대시보드: `category` 필드로 앱/엔진/연구·검증/운영/리포트 묶음, 60초 자동 새로고침, 마지막 갱신 시각.
- 리포트 슬롯 3개(오늘의 브리핑·챔피언 주간·뉴스 다이제스트) + 최신 파일 시각 배지.
- 문서: DEPLOYMENT_ORACLE 13·14번, nginx-quant.conf(참고용 표시), PENDING 4번 갱신.
- 검증: hub 테스트 24건, 로컬 렌더링 확인. 이 Codespace 에는 systemd·백업이 없어 타이머/백업은 "확인 불가"로만 확인 — **VM 실화면 미확인**. 백업 status.json 경로 기본값 `/opt/quant-backup/status.json`은 backup_vm.py 기본 디렉터리 기준 추정.

## 2026-09-25 관제 센터 사용 설명서 + 발견 결함 5건 수정

관제 센터 `/guide`에 사용 설명서를 만들었다(`hub/guide/`). 화면·자동 잡 표·최근 변경·배포 버전은 코드에서 자동으로 읽고, 사람이 쓴 설명은 근거 파일과 확인일을 갖는다. 새 화면·잡·core 모듈·스크립트에 설명이 없으면 `tests/test_hub_guide.py`가 실패해 자동배포가 막힌다(`python -m hub.guide.check`로 목록 확인, 규칙은 `AGENTS.md`). 설명서를 쓰려고 코드를 대조하다 찾은 결함을 사용자 지시("전부 다 진행")로 고쳤다.

| 결함 | 수정 | 검증 |
|---|---|---|
| 관심종목 자동 스캔·Threads 주간 알림이 데스크톱 알림뿐이라 폰으로 안 옴 | 충족 종목이 있으면 텔레그램 요약 1건(0건이면 안 보냄, 같은 종목·전략·기준일은 1회, 실패 시 다음 실행에 재시도). Threads 완료도 1건 | 단위 테스트. VM 실전송 미확인 |
| 텔레그램 `/processes`가 27개 잡 중 15개만 제어 | runner가 `core/process_registry.py`를 ast로 읽어(import 없이) 전체 잡을 보여 줌. 목록 불일치는 `tests/test_telegram_process_catalog_sync.py`가 막음. `paper_auto_trade`는 켤 때 2단계 확인, 기본 꺼짐 유지. `/experiment`와 `deploy/checkpoint_notify.py` 삭제 | runner unittest·동기화 테스트. 실제 텔레그램 화면 미확인 |
| 시장 국면이 일부 신호 결측을 0점으로 합산해 중립 쪽으로 쏠림 | 시장폭 필수 + 가중치 coverage 0.75 미만이면 unknown, 이상이면 재정규화하고 `partial`·`missing_signals` 표시. 모든 신호가 있을 때 판정은 이전과 동일(96개 조합 대조) | 단위 테스트. 과거 스냅샷은 새 필드 없음 |
| 가이던스 야간 잡이 SEC 조회를 끈 채 돌아 데이터가 안 쌓임 / 가격 교차 대조를 켜는 곳이 없음 / info_dedup 호출처 없음 | 야간 잡 `fetch_events=True`(종목 20·요청 300·300초 상한, 403 즉시 중단). 무결성 점검이 Alpaca 키가 있을 때 최대 10종목 교차 대조, 큰 불일치·분할 의심만 같은 건 1회 알림. 가이던스·공시 shadow 행에 event_id·원문 해시 기록 | mock 테스트. 실제 SEC·Alpaca 호출 미확인 |
| 삭제된 기능을 가리키는 화면 문구·주석 | 12개 파일 문구만 수정(동작 불변). 챔피언 화면 unknown 부제는 스냅샷의 실제 사유를 표시 | 전체 테스트·화면 띄워 확인 |

- **의도적 미연결:** `core/alpaca_price_provider.py`는 후보 원장 가격으로 연결하지 않았다. 실행마다 가격 기준(yfinance/Alpaca IEX)이 섞이고 시가 차이를 검사하지 않기 때문이다. 교차 대조로 두 소스 차이를 먼저 관측한다.
- **VM에서 새로 생기는 외부 요청:** SEC 하룻밤 최대 300회(보통 종목당 1~3회), Alpaca 시세 최대 10회. VM에 `SEC_EDGAR_USER_AGENT`가 없으면 SEC가 403으로 막을 수 있고, 그러면 가이던스 기록이 매일 '발표 없음'이 된다(잡 로그에 표시).
- **검증:** 통합 결과 `pytest tests` 1917 passed, `deploy/codex_telegram` unittest OK, `hub.guide.check` 누락 없음. 운용 알림·시장 진단·챔피언 전략 화면과 설명서(폰 크기)를 실제로 띄워 오류 없음 확인.

## 2026-09-25 Alpaca 로드맵 P0~P3 구축 (구현·mock 테스트, 실 API 0회)

- 사용자 확인: 목적은 **전략 수립·검증용, 실거래 아님**. 로드맵 [ALPACA_ENGINE_ROADMAP.md](./ALPACA_ENGINE_ROADMAP.md) 맨 위에 명시.
- 기존 자산 재사용: P0 자동 검증(`alpaca_verification`, 00:40)·P2 비용 보정(`cost_calibration`, 00:42)은 다른 세션이 이미 구현 → 중복 구현하지 않고 P0 에 5번째 검사만 추가.
- 신규: `core/alpaca_market_meta.py`, `core/alpaca_news.py`, `core/paper_tracking.py`(잡 00:46), `core/news_event_study.py`+`scripts/news_event_study.py`, `core/paper_auto_trade.py`(잡 화~토 06:10, **default_enabled=False**), `scripts/champion_paper_trade.py` 에 거래가능 경고, `scripts/verify_alpaca_meta_news.py`.
- 검증: 신규 테스트 25건 포함 전체 pytest **1761 passed**. 실 API·VM 실행·텔레그램 발송은 미검증.
- 브랜치 `alpaca-roadmap-2026-09`, 미푸시(main 푸시는 VM 자동 배포 → 사용자 승인 필요).
- 관제 허브에 `Alpaca paper 검증` 카드와 `/alpaca` 화면 추가(`hub/alpaca_status.py`, 결과 파일만 읽음). 스케줄러 기동 시 검증 잡을 백그라운드로 1회 실행(최근 PASS 있으면 건너뜀) → 배포 직후 결과가 화면에 뜬다.
- 2026-09-25 사용자 승인으로 main 병합·푸시(VM 자동 배포). 배포 성공·실제 검증 결과는 이 세션에서 확인 불가.
- 다음: VM 검증 결과 확인(스키마 불일치 시 `_normalize_*` 만 수정) → PASS 후 자동 주문 켤지 사용자 결정.

## 2026-09-24 관제 센터 로그인 UI (구현·단위 확인, 배포 전)

- 기존: nginx `auth_basic` 브라우저 기본 팝업(스타일 불가). 변경: 허브 `/login` 폼(`hub/server.py`) → `/_login` 이 htpasswd 로 검증 후 세션 쿠키(`qt_session`, 도메인 공유) 발급 → hub/app 은 쿠키 검사, 미로그인은 `/login?next=` 로 302. 401 은 `WWW-Authenticate` 없이 내려 팝업 방지. code-server 는 변경 없음.
- 토큰은 `/etc/nginx/quant-session.conf`(root:www-data 640, 재실행 시 재사용; 지우면 전 기기 로그아웃). 단일 사용자용 정적 토큰이라 개별 세션 만료·폐기는 없음(로그아웃은 쿠키 삭제만).
- 수정: `hub/server.py`, `deploy/setup_gateway.sh`. hub 테스트 33건 통과, `bash -n` 통과. **nginx 실적용·브라우저 확인은 미실시** — VM 에서 `sudo bash deploy/setup_gateway.sh hessejeong.duckdns.org` 재실행 필요(nginx -t 실패 시 자동 롤백). 푸시 전이며 미커밋.

## 2026-09-24 Alpaca paper 계정 활용 4종 + 거장 자동 추적

사용자 지시: "이 api key 를 활용한 서비스 혹은 이를 활용하여 핵심 엔진 고도화를 해", "거장 포트폴리오도 주기를 정해 트래킹해라(내가 누를 때 동기화되는 게 말이 되냐)". paper 키로 열리는 세 API(paper 거래, Market Data, Corporate Actions)가 모두 도달 가능함을 확인(401=인증 필요, 엔드포인트 존재)하고, 엔진의 **알려진 구멍**에 각각 대응시켰다.

| 대상 | 기존 결함 | 구현 | 검증 |
|---|---|---|---|
| `core/corporate_actions.py` + `core/trade_ledger.py` | ENG-01 배당 현금 유입 **미구현**, `dividend_cash_flow_modeled` 가 항상 False 하드코딩 | Alpaca Corporate Actions 조회 + ex-date 배당 현금 입금·분할 수량/단가 조정(옵트인, 기본 None 이면 기존과 비트 동일) | 손계산 대조(100주×$0.5=+$50, 2:1 분할 NAV 불변, 역분할+배당 동시). 단위 테스트 26건. **실 API 미호출** |
| `core/execution_reconciliation.py` | 거래비용 5/10/25bp 가 **가정값**, 백테스트 vs 실체결 대조 없음(로드맵 P0 reconciliation 미구현) | 실제 체결 조회 → `trade_ledger.LEDGER_COLUMNS` 동일 스키마 정규화 → client_order_id 매칭 → 실측 슬리피지 bp·체결률·지연 | 손계산(예상100.00/실제100.05 매수=+5bp 등). 21건. **n<30 이면 중앙값·분위수를 None 으로 강제**(표본 부족 시 대표값 주장 차단). DB 저장 안 함(브로커가 원본) |
| `core/price_crosscheck.py` + `core/data_integrity.py` | 모든 가격이 yfinance **단일 소스**, 교차 대조 수단 없음 | Alpaca 일봉 vs yfinance 캐시 대조(match/minor/major/한쪽 결측/unavailable), 분할 의심·거래량 괴리 플래그 | 22건. IEX≠SIP 한계를 결과 메타에 명시하고 **어느 소스가 옳은지 판정하지 않음**. data_integrity 에 기본 꺼짐 옵트인(키 없으면 기존 동작 불변) |
| `core/account_sync.py` | 챔피언은 "따랐다면"의 가상 수익만 기록, **실계좌 보유 vs 목표 괴리 미추적** | 계좌·포지션 스냅샷(DB 저장) + 종목/슬리브별 이탈(%p)·회전 필요량 | 20건. GET 전용·주문 경로 import 금지를 AST 테스트로 강제. 잡 `account_snapshot_sync` 00:35 KST |
| `core/guru_schedule.py` | 거장 포트폴리오가 **사람이 버튼 누를 때만** 동기화 | 자동 잡 `guru_holdings_sync` 12:00 KST. ARK 매일, 13F 는 3일 간격 확인 + 새 accession 있을 때만 파싱. 신규편입/전량청산 텔레그램 요약 1건 | 18건. 기존 sync 가 delete-후-재삽입이라 **이미 멱등**이었음을 확인하고 테스트로 고정 |
| `core/guidance_event_provider.py` | RES-04 가 events_by_ticker 없이는 전부 no_release | 티커→CIK→8-K Item 2.02→가이던스 변화 배선(옵트인 `fetch_events=True`, 기본 꺼짐), 하루 캐시·실패 격리·403 즉시 중단 | 10건 + **실제 SEC 3티커 점검 완료** |

**12:00 KST 선택 근거(거장):** ARK 일별 CSV 가 미 동부 저녁(대략 20~21시 ET)에 공개되므로 12:00 KST(=전날 22~23시 ET)가 최신 거래일 파일을 받는 가장 이른 시각이다. 00:3x 에 돌리면 하루 묵은 파일을 받는다. 야간 블록(00:00~00:35)은 이미 포화이기도 하다.

**실제 SEC 점검에서 나온 중요한 사실(우회하지 않고 기록):** NVDA 8-K 에서 가이던스 4건을 추출했으나 **전부 `change="unknown"`(`no_previous_in_retrieved_history`)** 이었다. 분기 가이던스는 매 분기 새 period_key(FY2027Q3 등)를 가리켜 같은 기간의 직전 가이던스가 없기 때문이다. 즉 현재 배선으로는 **분기 가이던스에서 raised/lowered 가 거의 나오지 않고 연간(FY) 가이던스를 주는 기업에서만 방향이 잡힌다.** RES-04 표본이 예상보다 훨씬 느리게 쌓인다는 뜻이며, 실험 설계(스펙 6절 최소 사건 수) 재검토가 필요하다.

**RES-05 독립 검증 결과(별도 에이전트):** 요구사항 6개 중 5개 충족, 1개 부분 충족. 부분 충족은 무작위 비교군(Arm C)이 스펙 8절의 "같은 달·같은 form 층화 10,000회"가 아니라 candidate_ledger 기본값(결정일 배치 1,000회)을 쓴다는 점 — "새 통계 규칙 금지" 제약 때문에 의도한 타협이며 스펙 개정 또는 ledger 확장이 필요하다. 또한 후보가 top_k 선정 종목뿐이라 **스펙 10절 최소 표본(보류 100건)에 수년이 걸릴 수 있다**(브레이크아웃 풀 관측은 champion_strategy 확장 필요, 사람 결정 사항).

**주문 게이트 변이 재검증(유실된 결과 재현):** 저장소 사본에서 5개 변이(게이트 무력화 / plan_targets 구버그 회귀 / run_id 대신 날짜 / 부분체결 재제출 / 위성 플래그 통합)를 하나씩 넣어 전부 테스트가 잡아내는 것을 확인했다. **다만 `test_incomplete_round_survives_midnight_with_same_ids` 가 이름과 달리 날짜 혼입 변이를 못 잡는 사각지대**를 발견(그 테스트의 mock 이 모든 조회를 ConnectionError 로 실패시켜 증상이 드러나기 전에 루프가 끊김). 이 세션이 `test_client_order_id_is_wall_clock_independent` 와 `test_resume_across_midnight_with_healthy_lookup_reuses_same_id_no_duplicate_post` 2건을 실제 트리에 추가하고, 변이를 일부러 넣어 두 테스트가 실패하는 것까지 확인한 뒤 원복했다.

### 다음 단계 (우선순위)

1. **사용자 승인 후 push** → VM 자동 배포 → 그때 비로소 새 주문 안전장치가 VM 에 들어간다(현재 VM 은 구버전+청산 버그).
2. **VM 에서 검증 스크립트 4개 실행**(전부 읽기 전용, 키 값 미출력): `scripts/verify_alpaca_paper_idempotency.py`(멱등 가정 5개), `scripts/verify_alpaca_corporate_actions.py`(AAPL 2020 4:1 분할·배당 스키마), `scripts/verify_price_crosscheck.py`(IEX 대조·분할 조정 여부), `scripts/sync_paper_account.py --no-save`(계좌 스키마). **응답 스키마가 가정과 다르면 각 모듈의 파싱 지점만 고치면 되도록 한곳에 모아 두었다.**
3. **사람 검증(G0):** `docs/experiment_validation/earnings_guidance_extraction_sample.md`·`filing_change_extraction_check.md` 의 '사람 확인' 열을 사용자가 10건 내외 채워야 RES-04/05 가 신호 실험 단계로 갈 수 있다.
4. RES-04 분기 가이던스 비교 불가 문제에 대한 설계 결정(연간 가이던스만 쓸지, period 매칭 정책을 바꿀지).
5. 실측 슬리피지가 30건 이상 쌓이면 `compare_with_cost_assumptions()` 로 5/10/25bp 가정 점검.

## 2026-09-22 엔진 고도화 3차: 운영 안전성 완료 + RES-01 스케줄 연결 + RES-04/05 shadow 준비

사용자 지시("운영 안전성 마무리 → 전체 후보 shadow 원장 → 실적·가이던스 변화 실험 → 공시 변화 악재 필터 → 확률 기반 선택기는 나중")에 따라 4개 병렬 에이전트로 시작했다. 세션 API 사용량 한도로 4개 모두 한 차례 중단됐으나 대부분 파일은 중단 직전까지 저장돼 있었다(전체 pytest는 중단 시점에도 통과 상태). 재개 지시로 이어서 완료했고, 그중 "RES-01 스케줄 연결" 1건은 재개 후에도 파일이 전혀 남지 않아 이 세션이 직접(서브에이전트 없이) 구현했다. 아래는 **이 세션이 직접 확인한 사실**만 적는다 — 일부 에이전트의 최종 보고 텍스트는 이 세션의 맥락에 남아 있지 않아 재구성하지 않았다.

| 항목 | 구현 | 기존 경로 연결 | 단위 테스트 | 통합 검증 | paper 검증 | 배포 |
|---|---|---|---|---|---|---|
| 주문 회차 수동 종료 | 완료(`scripts/paper_run_admin.py`: list/close --run-id --reason [--force]/audit) | `core.paper_execution.RunStore` | 완료(`tests/test_paper_run_admin.py`) | 미완료 | 미완료 | 미완료 |
| 위성 보류 플래그 | 완료(core 보류와 독립적인 fail-closed) | 완료 | 완료(`tests/test_satellite_order_gate.py`) | 미완료 | 미완료 | 미완료 |
| legacy/v2 튜닝 분리 | 완료 | `scripts/five_strategy_batch_ci.py`가 `score_version` 필터, 전략 스튜디오에 legacy 배지 | 완료(`tests/test_five_strategy_batch_legacy_split.py`, `tests/test_studio_legacy_badge.py`) | 미완료 | 해당없음 | 미완료 |
| Alpaca paper 검증 도구 | 완료(`scripts/verify_alpaca_paper_idempotency.py`, 읽기전용 기본/`--write` 옵션) | 해당없음(별도 도구) | 완료 — **requests mock 뿐, 실제 API 호출 0건**(`docs/PAPER_API_VERIFICATION_RUNBOOK.md`에 명시) | **미완료 — VM에서 키로 실행 필요** | 미완료 | 해당없음 |
| 게이트 변이 테스트 | 지시함 | - | **이 세션에서 결과를 확인하지 못함**(에이전트 최종 보고 유실, 직접 재현 안 함) | 불명 | - | - |
| RES-01 후보 shadow 원장 | 완료(`core/candidate_ledger.py`, `docs/CANDIDATE_LEDGER_SPEC.md`) | 해당없음(관측 인프라) | 완료(`tests/test_candidate_ledger.py`) | 완료(합성 데이터 손계산 대조 + 변이 시험 10종 전부 검출, 에이전트 보고 기준) | 실운영 데이터 0건 | 미완료 |
| RES-01 스케줄 연결 | 완료(`core/candidate_recorder.py`) — **이 세션이 직접 작성** | `scheduler/run_scheduler.py`(00:27/00:28 KST 2개 잡), `core/job_schedule.py`, `core/process_registry.py` | 완료(`tests/test_candidate_recorder.py` 12건, 소스검사로 주문경로 미참조 강제) | 부분(스케줄러 fake 등록 테스트만, 실제 스케줄러 프로세스로는 미확인) | 해당없음 | **미완료 — 배포되면 매일 밤 실제 DB에 CandidateBatch/CandidateDecision이 쌓이기 시작함** |
| RES-04 가이던스 변화 | 스펙+추출기 완료(`docs/EARNINGS_GUIDANCE_EXPERIMENT_SPEC.md`, `core/earnings_events.py`) | 없음(개별주 위성 신호에 미연결 — 지시된 범위 밖) | 완료(`tests/test_earnings_events.py`, 오프라인 fixture) | 실제 EDGAR 12개 발표 표본 완료(`docs/experiment_validation/earnings_guidance_extraction_sample.md`, 이 세션이 직접 실행) — **사람 검증 대기**(작성자=검증자라 정확도 미주장) | 미완료 | 미완료 |
| RES-05 공시 악재 필터 | 스펙+추출기+veto 규칙 완료(`docs/FILING_CHANGE_VETO_SPEC.md`, `core/filing_changes.py`) | 없음(기존 모멘텀 후보에 미연결 — 지시된 범위 밖) | 완료(`tests/test_filing_changes.py`, 오프라인 fixture) | 실제 EDGAR 5개 기업 10-K 점검 완료(`docs/experiment_validation/filing_change_extraction_check.md`, 이 세션이 직접 실행, 섹션 추출 8/8) — **사람 검증 대기** | 미완료 | 미완료 |
| 튜닝 점수 v2 DB 저장 | 이전 세션에서 완료 | 완료 | 완료 | 확인 | 해당없음 | 미완료 |

**SEC 환경변수 수정:** 1차 지시에서 `SEC_USER_AGENT`로 잘못 지정했다. 기존 관례(`core/guru_tracker.py`, `.env.example`)는 `SEC_EDGAR_USER_AGENT`이고 사용자 `.env`에 이미 설정돼 있었다. 재지시로 `core/earnings_events.py`·`core/filing_changes.py` 모두 `SEC_EDGAR_USER_AGENT` → `SEC_USER_AGENT` → 개인정보 없는 일반 문자열 순으로 고쳤다. 값은 코드·로그·문서 어디에도 남기지 않는다.

**RES-01 스케줄 연결 설계 결정(이 세션 직접 작업):**
- 기록은 스케줄된 잡(00:27 KST `candidate_ledger_record`)에서만 한다. Streamlit 페이지 렌더링 시점에 기록하면 같은 날 후보가 중복 관측되어 표본이 오염되므로 원전략 함수(`discover_candidates`, `compute_leader_and_growth`, `compute_satellite_recommendation_point_in_time`)는 잡 안에서만 호출하고 페이지 코드는 그대로 뒀다.
- 세 소스(stock_discovery/sector_leaders/champion_satellite) 중 하나가 예외를 내도 나머지는 계속 기록한다. `core/candidate_recorder.py`의 소스 검사 테스트가 `core.paper_execution`/`scripts.champion_paper_trade` import를 금지해 주문 경로와의 결합을 구조적으로 막는다.
- 시간 계약을 지어내지 않는다: 가격·재무 기반 후보는 `decision_cutoff`만 채우고 나머지 4개 시간 필드는 비운다 → `pit_certified=False` → `decide_verdict`는 이 사실만으로 항상 '미입증'을 반환한다(원장 규칙을 우회하지 않음).
- `stock_discovery`는 매일 상위 100개(`STOCK_DISCOVERY_POOL_N`)를 풀로 기록하고 상위 10개(`STOCK_DISCOVERY_SELECTED_N`)만 채택으로 본다 — S&P500 전체(500+)를 매일 스캔하는 비용을 피한 타협값이며, "전체 후보"가 아니라 "채택보다 훨씬 큰 held 표본"이라는 한계가 있다.
- `sector_leaders`는 21개 테마 전체(`THEME_UNIVERSE`)를 매일 순회하며 테마 하나가 실패해도 나머지는 기록한다. `compute_leader_and_growth`가 후보 풀을 반환하지 않아 `get_theme_candidate_tickers`로 티커만 pool로 넘겼다 — 점수 없이 held/missing_data로만 구분된다.
- 위성은 라이브 스캔이 아니라 `compute_satellite_recommendation_point_in_time`(백테스트가 실제로 검증한 것과 같은 방법론)을 쓴다. `new_orders_allowed=False`면 채택 대신 `held`로 기록해 데이터 부족을 청산으로 잘못 번역하지 않는다(ENG-03 규칙과 동일 원칙).
- `update_forward_outcomes`는 00:28 KST(기록 1분 뒤)에 실행한다. 그날 막 기록한 후보는 아직 진입 전이라 영향이 없고, 이전에 기록된 후보들의 만기 결과만 채운다(함수 자체가 멱등).
- `core/process_registry.py`에 `candidate_ledger_record`/`candidate_ledger_outcome_update`를 `research` 카테고리·기본 켜짐으로 등록했다. 텔레그램 `/processes`로 끌 수 있다.
- 검증: `pytest tests/test_candidate_recorder.py tests/test_job_health.py` 및 전체 `pytest tests` 1457건 통과(이 세션이 직접 실행).

**RES-04/05 실제 EDGAR 표본에서 발견한 것(이 세션이 직접 실행, `--out`으로 산출):**
- 가이던스: 발표 12건 중 가이던스 item을 하나도 못 얻은 발표 1건(8%, 원문에 실제 없는 것과 추출 누락을 사람 확인 전까지 구분 못함). item 총 121건 중 비교 불가(기간 미확정·스케일 모호 등) 34건. G0 게이트(≥95% exact match, ≥60 item·30개 발표·8개 기업·별도 정답 작성자)를 판정하기엔 표본이 작다.
- 공시: 5개 기업 10-K 중 JPM은 비교 가능한 직전 동종 공시가 1개뿐이라 비교 불가로 정직하게 표시됐다. 나머지 4개 기업은 Item 1A·유동성 섹션 추출 8/8 성공. diff는 신규/삭제/재서술/숫자변경을 분리해 표로 남겼다(예: GME MD&A 유동성 절이 `length_shock, mostly_new_text` 플래그).
- 두 표본 모두 "사람 확인" 열이 비어 있고 작성자=검증자 문제로 정확도를 주장하지 않는다. **다음 단계는 사용자가 각 10건 내외를 원문과 대조하는 것**(RES-03/04/05 검증과 거절 계약의 G0 게이트).

**이 세션이 확인하지 못한 것(정직하게 남김):**
- 운영 안전성 에이전트의 "변이 테스트(게이트 제거/plan_targets 회귀/run id 날짜화/부분체결 재제출 등 10종)" 결과 보고를 이 세션 맥락에서 찾지 못했다. 관련 테스트(`test_satellite_order_gate.py` 등)는 통과하지만, 변이가 실제로 실패를 유발하는지는 이 세션이 재확인하지 않았다.
- Alpaca paper 실계정 검증은 0건. VM에서 `python scripts/verify_alpaca_paper_idempotency.py`(읽기전용) 및 필요시 `--write` 실행이 다음 최우선 단계다.
- RES-04/05 추출 결과의 사람 검증(10건 내외 원문 대조)이 없다.
- 개별주 위성 신호에 RES-04/05를 실제로 붙이는 shadow 실험은 아직 시작하지 않았다(스펙만 있음, 지시된 범위가 "준비"까지였음).
- `docs/PAPER_API_VERIFICATION_RUNBOOK.md`는 VM에서 한 번도 실행되지 않았다.

## 현재 목표

기존 주식 서비스 엔진을 고도화할 후보를 정리하고, 이후 에이전트가 같은 맥락에서 분석·구현·검증을 이어갈 수 있는 문서 흐름을 만든다.

## 2026-09-22 UI 1차 구현: Today 명령 센터

| 구분 | 상태 | 내용 |
|---|---|---|
| 제안 | 완료 | 노션형 장문 홈을 판단·근거·안전 실행 흐름의 명령 센터로 전환 |
| 구현 | 완료 | `app/Home.py`의 상태 칩·4개 요약 지표·조치 큐·전략 상태·업무공간 링크, `core/today_dashboard.py` 읽기 전용 뷰 모델, 공통 상태/조치 카드 CSS |
| 검증 | 완료 | `tests/test_today_dashboard.py`와 `tests/test_page_order.py` 11건 통과, `py_compile`, `git diff --check`, Streamlit `AppTest` 렌더링(지표 4개) 통과 |
| 배포 | 미완료 | 커밋·VM·paper API 검증을 수행하지 않음 |

결정과 근거:

- 홈은 `get_current_holdings`, 최신 시장 국면 스냅샷, 작업 상태, 백업 상태, 관심종목 알림 수를 안전하게 읽는다. 한 소스가 실패해도 홈 전체가 실패하지 않고 해당 상태를 비어 있음/알 수 없음으로 표시한다.
- `unknown` 국면은 약세 신호가 아니라 데이터 부족에 따른 판단 보류로 보인다. 홈은 주문 가능 여부를 바꾸지 않으며, 주문 버튼도 제공하지 않는다.
- 환경의 Streamlit 1.59.1은 `st.page_link(..., type=...)`를 지원하지 않아 버튼 타입 의존성을 제거했다. 링크는 호환 인자만 사용한다.

수정 파일: `app/Home.py`, `core/theme.py`, `core/today_dashboard.py`, `tests/test_today_dashboard.py`, `docs/SESSION_HANDOFF.md`, `PROGRESS.md`.

다음 단계:

1. 공통 상태 헤더와 업무공간 내비게이션은 아래 UI 2차에서 구현했다.
2. 선택 종목 컨텍스트와 챔피언 전략의 리서치/운용 분리를 설계·구현한다.
3. 실브라우저와 모바일 너비에서 UI 2차 배치를 확인한다.

## 2026-09-22 UI 2차 구현: 상태 계약과 업무공간 내비게이션

| 구분 | 상태 | 내용 |
|---|---|---|
| 제안 | 완료 | 상세 화면의 신뢰 상태 어휘와 업무 목적별 정보 구조 확정 |
| 구현 | 완료 | `st.navigation` 라우터, 6개 업무공간, 13개 상세 화면 공통 상태 헤더, 상태 판정·내비게이션 순수 모델 |
| 검증 | 완료 | 전체 `pytest tests` 1463건, 홈·환경설정·Threads `AppTest`, 전 페이지 `py_compile`, `git diff --check` 통과 |
| 배포 | 미완료 | 커밋·VM 배포·실브라우저·모바일 검증 미수행 |

결정과 근거:

- 내비게이션의 단일 정의는 `core/app_navigation.py`다. 숫자 파일명을 바꾸던 기존 환경설정은 새 라우터에 영향을 주지 않아 오해를 만들므로, 실제 그룹과 상태 표기 원칙을 보여 주는 시스템 화면으로 교체했다.
- `core/ui_status.py`는 저장된 챔피언·시장 스냅샷만 읽고 네트워크 요청이나 재계산을 하지 않는다. 기준 시각이 없으면 임의의 현재 시각 대신 `확인되지 않음 / Unknown`을 표시한다.
- Fresh는 저장 시각이 48시간 이내인 경우이며, 그보다 오래되면 Stale이다. PIT는 `해당 없음 / 미검증 / 혼합 / 부분 검증`으로 분리했다. 이 상태들은 매수·매도 신호가 아니다.
- 챔피언과 시장 화면은 저장 스냅샷 기준일을 사용한다. 나머지 화면은 신뢰할 저장 기준일이 아직 없어 Unknown이며, 후속으로 각 엔진 결과 메타데이터를 저장하면 같은 헤더에 연결한다.

수정 파일: `app/Home.py`, `app/views/today.py`, 13개 `app/pages/*.py`, `core/app_navigation.py`, `core/ui_status.py`, `core/theme.py`, `tests/test_app_navigation.py`, `tests/test_ui_status.py`, 인계 문서.

다음 단계:

1. 브라우저와 모바일 너비에서 6개 그룹 및 상태 헤더의 실제 밀도·줄바꿈을 확인한다.
2. 스크리닝·튜닝·뉴스·포트폴리오 결과에 `as_of / strategy_version / pit_status`를 저장해 현재 Unknown 헤더를 실제 상태와 연결한다.
3. 챔피언 화면의 리서치와 운용 섹션을 분리하고 선택 종목 컨텍스트를 화면 간에 공유한다.

## 이번 세션의 결정

- 전략 고도화 분석은 Astra가 담당했고, 핵심 엔진과 P0~P2 우선순위를 로드맵에 반영했다.
- 단순 문서 작성은 Luna가 담당한다.
- 이번 작업 범위는 문서 생성과 인계 구조이며, 코드 변경·배포·실거래는 포함하지 않는다.
- 기존 `docs/experiment_validation/` 및 `new/` untracked 파일은 보존한다.
- 모델/에이전트 배분은 이번 요청의 작업 분담이며, 향후 자동 강제 정책으로 기록하지 않는다.

## 현재 근거

기존 검토에서 PIT 재무·상폐 가격·기업행동·체결 정합성을 최우선으로 보았다. `stock_discovery`의 `as_of_date`는 현재 유니버스와 현재 재무·가격을 조합하므로 진정한 PIT 검증이 아니며, 원시 재무값 평균은 스케일 문제를 가진다. `backtest_engine`의 기존 수익곡선은 다음 시가 체결·갭·비용을 완전히 표현하지 않는다. 기존 14일 S1-S6 검증은 건드리지 않고, 후속 hold-band·실적 정보·퀄리티 실험을 별도로 다룬다.

추가 코드 읽기 발견: `sector_leaders._percentile_score`는 일부 결측에서 `na_option='bottom'`과 ascending rank 조합으로 결측이 높은 점수가 될 가능성이 있고, 성장률이 없을 때 고PER을 대체값으로 사용할 수 있다. 데이터 없음과 고성장을 혼동할 위험이 있으므로 별도 재현 테스트와 수정 검토가 필요하다. 이번 세션에는 코드 수정·재현 테스트를 하지 않았다.

## 수정 파일

- `AGENTS.md`: 세션 시작·종료 인계 규칙
- `docs/ENGINE_UPGRADE_ROADMAP.md`: 기존 엔진 고도화 초안
- `docs/SESSION_HANDOFF.md`: 본 인계 문서
- `docs/README.md`: 문서 색인 항목
- `PROGRESS.md`: 현재 인계 링크 및 세션 기록

## 검증

문서 파일 존재·색인·인계 링크와 `git diff --check`를 확인했다. 코드와 테스트는 변경하지 않았으므로 실행하지 않았다.

기존 Day 4 PIT 입력 부족 `BLOCKED`, 인증 반기·공통 거래일 0, S1/S6 `NOT_EVALUABLE`은 기존 PROGRESS 로그 상태다. 이번 세션에서 재실행하거나 변경하지 않았으며, VM 현재 상태를 직접 확인한 결과로 해석하지 않는다.

## 다음 단계

1. 로드맵 ENG-01~ENG-11의 후보를 관련 코드와 기존 검증 문서로 대조한다.
2. 문서 에이전트가 구현·검증·배포 상태를 갱신한다.
3. 사용자 요청 범위(명시적 요청과 맥락상 위임 포함)에 들어온 항목만 구현 에이전트가 코드·테스트·PROGRESS에 반영한다. 제안·구현·검증·배포 상태를 구분한다.
4. 구현 전후 기준선, 비용, PIT 여부, 검증 결과를 함께 기록한다.

## 2026-09-21 구현 세션 (7개 에이전트 병렬)

사용자가 역할 분배 후 문제 해결을 요청해 ENG-01·02·03·04·05·07·10을 구현했다. 커밋·배포는 하지 않았다.

| ID | 수정 파일 | 내용 |
|---|---|---|
| ENG-01 | `core/trade_ledger.py`(신규), `tests/test_trade_ledger.py` | 다음 시가 체결, 비용 분리, 거래 원장. 기존 `backtest_engine` 미수정 |
| ENG-02 | `core/market_regime.py`, `app/pages/7_시장_진단.py`, `tests/test_market_regime.py` | breadth 데이터 0개를 약세가 아닌 unknown으로 분리, coverage 저장 |
| ENG-03 | `core/champion_strategy.py`, `app/pages/11_챔피언_전략.py`, `tests/test_champion_strategy.py` | SPY 없음 시 unknown·신규 주문 보류, snapshot에 거래일·coverage·버전·사유 |
| ENG-04 | `core/strategy_tuning.py`, `core/tuning_ledger.py`(신규), `tests/test_tuning_ledger.py` | 탐색 장부, 순위 불안정, 이웃 안정성, DSR 근사 |
| ENG-05 | `core/paper_execution.py`, `tests/test_paper_execution.py` | client order ID 멱등, 재조회 대조, 상태 분류 |
| ENG-07 | `core/stock_discovery.py`, `tests/test_stock_discovery.py` | 업종 내 percentile rank, 결측·기여도·대체 플래그, `pit_verified=False` |
| ENG-10 | `core/sector_leaders.py`, `tests/test_sector_leaders.py` | 결측 중립 처리, PER 대체 제거, `growth_data_missing` |

검증: 전체 `pytest tests` 1094건 통과. 이 검증은 단위 테스트 수준이다. 실제 paper API, Streamlit 렌더링, VM 배포는 확인하지 않았다.

### 결정 대기·후속
- `core/strategy_tuning.py`의 `_percentile_score`(`na_option="bottom"`)와 `earnings_growth.fillna(per)`는 ENG-10과 같은 결함이다. 수정하면 튜닝 결과 기준선이 바뀌므로 사용자 결정 후 진행한다.
- ENG-05: 같은 fingerprint가 다른 날 다시 나오면 어제 주문으로 오인할 수 있다. 실행 날짜를 ID에 넣을지 결정이 필요하다. 주문이 매도 우선이 아니고, `scripts/champion_paper_trade.py`가 `reconcile_state`를 출력하지 않는다.
- ENG-03: 실제 주문 경로가 `new_orders_allowed`를 존중하는지 확인 필요.
- ENG-02: 부분 결측 coverage 임계값 정책 필요. 과거 저장 스냅샷에는 unknown 필드가 없다.
- ENG-04: 새 필드가 `save_tuning_run`·DB 모델에 반영되지 않았다.
- ENG-01: 기업행동 미구현, 기존 백테스트·전략 엔진과 미연결.
- ENG-07: 진정한 PIT 유니버스와 IC·단조성 검증 미수행. 새 플래그의 UI 노출 없음.
- ENG-10: `test_..._falls_back_to_per_when_earnings_growth_missing` 이름과 주석이 현재 동작과 맞지 않아 정리 필요.
- 작업 중 에이전트 두 곳이 `git stash`를 써서 일시적으로 다른 작업이 되돌려졌다. 전원 복원됐고 전체 테스트가 통과했다.

## 2026-09-21 2차 세션: 통합 단계

1차 구현 후 사용자 검토 의견을 반영해 통합 작업을 진행했다. 아래 표는 단계별로 구분한다. 현재 어떤 항목도 paper 검증·배포 단계가 아니다. 전체 `pytest tests` 1120건 통과는 회귀 방지 근거이며 주문 안전성이나 성과 개선의 증거가 아니다.

| ID | 구현 | 기존 경로 연결 | 단위 테스트 | 통합 검증 | paper 검증 | 배포 |
|---|---|---|---|---|---|---|
| ENG-01 | 완료 | 옵트인 연결(`execution_model`), 순열·민감도·적립식 미연결 | 완료(손계산 대조) | 실데이터 조정가격 미확인 | 해당 없음 | 미완료 |
| ENG-02 | 완료 | 페이지 표시만, 주문 게이트는 ENG-03 경로로 연결 | 완료 | 미완료 | 해당 없음 | 미완료 |
| ENG-03 | 완료 | champion 주문 경로 연결 | 완료 | mock 통합 완료 | 미완료 | 미완료 |
| ENG-04 | 완료 | 저장·재조회 연결 | 완료(임시 SQLite 왕복) | 야간 CI 스크립트·UI 미반영 | 해당 없음 | 미완료 |
| ENG-05 | 완료 | 최종 제출 함수에서 게이트 강제 | 완료 | mock 통합 완료 | 미완료 | 미완료 |
| ENG-07 | 완료 | 기존 컬럼 호환 | 완료 | 합성 데이터 비교만 | 해당 없음 | 미완료 |
| ENG-10 | 완료(`sector_leaders`, `strategy_tuning` 점수 v2) | 연결 | 완료 | 합성 데이터 비교만 | 해당 없음 | 미완료 |

### 결정 사항(사용자 의견 반영)
- 튜닝 점수 결함은 수정하고 `STYLE_SCORE_VERSION=2`를 도입했다. 예전 결과는 삭제하지 않고 legacy로 표시한다. v1과 v2 결과는 직접 비교하지 않는다.
- 주문 ID는 날짜가 아니라 영속 저장되는 실행 회차 식별자로 만든다(`RunStore`, 기본 `data/paper_runs.db`). 같은 회차의 재시도는 같은 ID, 다음 회차는 새 ID다.
- 최종 제출 함수 `submit_plan`이 `new_orders_allowed`를 강제한다. 플래그가 없으면 차단한다(fail-closed).
- 데이터 부족은 신규 매수 보류이며 청산이 아니다. 기존 코드는 SPY 누락 시 목표 비중 0이 되어 보유 전량 매도 계획을 만들었다. 재현 후 수정했고, 보류 중에는 명시한 사유가 있는 종목만 매도한다.

### 미해결·후속
- **paper 검증:** 실제 Alpaca paper API의 `client_order_id` 중복·404 응답은 mock 가정이다. 최우선 후속.
- **주문 회차:** 조회가 계속 실패하면 회차가 열린 채 남고 수동 종료 도구가 없다. 체결 대기 중에는 새 계획이 반영되지 않는다. 위성 전략에는 별도 보류 플래그가 없다.
- **일부 테스트의 독립성:** 주문 경로 통합 테스트는 구현을 먼저 쓴 뒤 작성했다. 예상값은 요구사항에서 정했으나 구 코드에서 실패하는 것은 확인하지 못했다. 구 로직 재현은 별도로 했다.
- **야간 CI:** `scripts/five_strategy_batch_ci.py`가 legacy와 v2 결과를 한 리더보드에 섞는다. `score_version=2` 필터 또는 필드 추가 필요. 전략 스튜디오 화면에 legacy 배지 없음.
- **ENG-01:** 배당 현금 유입 미구현. 실제 캐시 데이터(AAPL 2020-08 분할 구간)로 확인한 결과 Close는 분할이 이미 반영돼 있고 배당만 미반영이다. 따라서 조정 헬퍼의 실제 효과는 분할 보정이 아니라 배당 재투자 가정의 총수익 기준 전환이며, 앞선 에이전트의 '미조정 가격이라 분할 왜곡' 설명은 이 데이터에는 맞지 않는다. 분할 왜곡 테스트는 원시 가격 합성 데이터 기준이다. `adjust_prices=True`는 지표 계산에도 조정가격을 쓰므로 채택 전 영향 확인 필요.
- **ENG-07·10 발견 결함:** 결측 종목 점수 50이 음수 성장 종목보다 뒤에 정렬되는 표시 불일치, 표본 3개 업종의 33/67/100 점수, 대체 rank와 업종 내 rank 혼합, 업종 결측이 하나로 묶임, value 지표 스케일 혼합. 예측력 개선은 입증되지 않았다(합성 데이터 1회 비교).
- **ENG-02:** 부분 결측 coverage 임계값 정책, 과거 저장 스냅샷에 unknown 필드 없음.
- **협업 방식:** 병렬 에이전트 두 곳이 `git stash`를 써 다른 작업이 잠시 되돌려졌다. 다음 병렬 작업은 미커밋 변경을 먼저 브랜치 또는 커밋으로 보존한 뒤 에이전트별 worktree와 통합 담당자를 쓴다. 전체 테스트 통과만으로 모든 변경의 복원을 증명할 수 없다.

## 2026-09-25 ENG-02 후속: 시장 국면 부분 결측 정책 (브랜치 fix-regime-partial, 미병합·미배포)

- **결정:** 결측 신호를 0점으로 합산하지 않는다. 가중치(각 신호 최대 절대점수 25, 4개 동일) 기준 coverage가 `MIN_REGIME_SIGNAL_COVERAGE=0.75` 미만이거나 시장폭이 없으면 `unknown`, 그 외 결측이 있으면 가용 점수 합/coverage로 재정규화해 판정하고 `partial=True`, `missing_signals`로 표시한다.
- **근거:** 전체 데이터에서도 신호 1개(25점)로는 ±35를 못 넘는다(최소 2개 신호 합의 필요). 재정규화 후 이 불변식이 유지되려면 25/c<35, c>0.714 → 가능한 값 중 최소 0.75. 시장폭은 나머지 3개(모두 같은 벤치마크 종가에서 파생)와 독립된 유일한 데이터라 필수로 유지(기존 ENG-02 테스트 그대로).
- **실제 영향:** 200일선·크로스는 같은 조건(이력 200거래일)으로 함께 빠지므로, 벤치마크 이력 부족 시 예전엔 낙폭+시장폭 합으로 '중립/혼조'가 나오던 것이 이제 `unknown`이다. 모든 신호가 있을 때 점수·국면은 불변(구 로직 재현 96개 조합 대조).
- **변경:** `core/market_regime.py`(`combine_regime_signals`, `signal_status`/`coverage`/`raw_total_score`/`regime_reason` 저장, `select_regime_for_trading`은 partial이면 `is_ambiguous=True`, unknown 사유 전달), `app/pages/7_시장_진단.py`(unknown 사유·일부 신호 결측 경고만 추가), `hub/guide/content_pages_b.py`·`content_modules_b.py`·`content_ops.py`, `tests/test_market_regime.py`.
- **검증:** 전체 pytest 통과, `python -m hub.guide.check` 빠진 설명 없음. Streamlit 렌더링·실데이터 스냅샷은 확인하지 않았다. 과거 저장 스냅샷은 수정하지 않았다(새 필드 없음, 읽는 쪽은 `.get()`).
- **후속:** `app/pages/11_챔피언_전략.py`의 unknown 부제 '시장폭 데이터 없음'은 고정 문구라 새 사유(coverage 미달)와 다를 수 있다(당시 다른 세션 담당이라 미수정). 오늘 화면은 partial을 따로 표시하지 않는다.

## 연속성 한계

이 문서 체계는 저장소를 이용하는 에이전트가 결정 중심 요약을 이어 읽도록 돕는다. 모든 대화 원문이나 외부 세션의 상태를 자동 보존한다는 보장은 없다.

## 2026-09-21 정보 수집·판단 엔진 연구

사용자 요청에 따라 한 에이전트가 해외 전략·서비스·퀀트 사례와 아이디어를 만들고, Sol 에이전트가 누수·데이터 비용과 사용권·기존 기능 중복·선택편향·확률보정·독립 검증 관점에서 반박했다. 두 에이전트가 한 차례 직접 논의해 [연구 문서](./INFORMATION_DECISION_ENGINE_RESEARCH.md)의 RES-01~07로 확정했다.

결정은 모든 후보와 보류를 같은 exit로 추적하는 shadow 원장, 정보 비용·중복 라우터, 기존 thesis review의 사전 KPI·반증 계약을 먼저 연구하는 것이다. 발행사 가이던스 기대 변화와 SEC 공시 diff는 개별주 위성 shadow 실험으로 수정 채택했다. 충분한 OOS 사건 전 확률 선택기와 PIT 관계·라이선스가 없는 공급망 graph는 보류했다. `P(비용 후 수익 > 0)`과 `P(벤치마크 초과 > 0)` 중 목표를 사전 고정하고 비용 후 기대값·선택률·기회비용·수익분포를 함께 본다.

수정 파일은 `docs/INFORMATION_DECISION_ENGINE_RESEARCH.md`, `docs/README.md`, `docs/ENGINE_UPGRADE_ROADMAP.md`, `docs/SESSION_HANDOFF.md`, `PROGRESS.md`다. 코드·테스트·DB·배포는 변경하지 않았고 pytest는 재실행하지 않았다. 문서 링크와 `git diff --check`만 확인한다. 신규 제안은 모두 연구 상태이고 구현·paper 검증·운영 적용·성과 개선은 미완료다.

## 2026-09-21 VM 운영 안정화 세션 (인프라 — 주식 엔진 코드와 무관)

사용자 요청("다른 해결할 사항/보강할 것을 제안하고 해결", "보강할 것을 다시 제안하고 진행")에 따라 Oracle VM 운영을 손봤다. 엔진 고도화 세션과 같은 작업 공간을 동시에 썼으므로 커밋에는 인프라 파일만 담았고(파일별 증감 줄 수로 확인), 공유 파일 `PROGRESS.md`는 인덱스에만 올려 다른 세션의 미커밋 수정과 섞이지 않게 했다.

**결정과 근거**
- 저장소(Quant)가 **공개**라서 DB·연구 산출물 백업을 여기에 올릴 수 없다 → 별도 **비공개** 저장소 + 전용 배포 키. Codespace 토큰으로는 저장소를 만들 수 없어 사람이 만든다.
- 백업은 점(.) 폴더(인증 정보)를 구조적으로 제외하는 **허용 목록** 방식이고, 허용 폴더 안의 비밀 의심 파일은 격리한다. 비밀(로그인 파일, .env, 토큰)은 일부러 백업하지 않는다.
- 자동 재부팅·자동 롤백은 하지 않는다: 부팅 실패 시 복구 수단이 없고(OCI CLI 키 401), 자동배포의 비파괴 원칙이 있다. 대신 방치 알림(재부팅 14일)과 배포 뒤 상태 확인/실패 알림을 둔다.
- 실험 슈퍼바이저는 **일시정지**(`.experiment-control/control.json` mode=paused): 누적 97회 실행에 완료 3일, Day 4가 PIT 데이터 부재로 반복 BLOCKED였다.

**상태 (구현 / 검증 / 배포를 구분)**
- 구현·단위 테스트·VM 배포 완료, VM 실데이터로 확인: 백업(검증+복구 리허설 통과), 워치독(재부팅 28일 방치 감지), 잡 실행 이력 테이블·브리핑 운영 섹션, Streamlit 127.0.0.1 바인딩, rpcbind 중지, 인증서 갱신 리허설(3개 도메인 성공), 재시작 후 상태 확인 함수(라이브 서비스 4개 정상).
- 구현·배포 완료, **아직 실전 미검증**: 잡 이력 기반 판정(첫 야간 실행 2026-09-22 00:00 KST부터 쌓임), 소프트 실패 보고(다음 07:30 KST 뉴스 잡·00:20 FRED 잡), 워치독 첫 정기 실행(2026-09-22 09:05 KST), 주간 생존 신호(다음 일요일), `RECONCILE_FILES` 확장(그 파일이 upstream에서 바뀔 때), 자동배포의 재시작 후 확인(이 커밋을 처리한 배포는 옛 스크립트라 다음 배포부터).
- 구현·푸시 완료, **GitHub 러너에서 첫 실행 미확인**: `.github/workflows/uptime.yml`(토큰에 dispatch 권한이 없어 수동 실행 불가 — 스케줄 또는 Actions 탭에서 확인).

**수정 파일**: `deploy/{backup_vm.py, watchdog.py, setup_backup.sh, post_deploy_check.sh, progress_reconcile.sh, auto_deploy.sh, setup_gateway.sh 등}`, `core/{job_health.py, job_schedule.py, backup_status.py, daily_briefing.py}`, `scheduler/run_scheduler.py`(리스너·소프트 실패 보고), `core/models.py`(`SchedulerJobRun` 테이블), `.github/workflows/uptime.yml`, 관련 `tests/`. 상세와 운영 절차는 `deploy/DEPLOYMENT_ORACLE.md` 12·14~17번, `PROGRESS.md` 작업 94~98.

**검증**: 전체 `pytest tests` 1,198건 통과(다른 세션의 미완성 `tests/test_candidate_ledger.py`는 `core.candidate_ledger` 부재로 수집 오류라 제외 — 이 작업과 무관). 자동배포 테스트 게이트가 VM에서도 통과.

**다음 단계 / 결정 대기**
1. 사람: 비공개 백업 저장소 생성 + 배포 키 등록 + `/opt/quant-backup/remote` 설정(절차는 `DEPLOYMENT_ORACLE.md` 15번). 그 전까지 백업은 같은 디스크에만 있다.
2. 사람: Oracle 콘솔 8501/8080 Ingress 규칙 삭제(사용자가 완료했다고 알림, 밖에서 확인 불가), 공인 IP가 Reserved인지 확인.
3. 사람: 재부팅 시점 결정(커널 보안 업데이트가 2026-08-24부터 대기). 콘솔 접근이 가능할 때, 서비스·방화벽·주소 점검까지 같이.
4. 사람: 2주 실험 재개 조건 결정 — PIT 구성종목/섹터 데이터를 구하거나, 가진 데이터 범위로 실험을 재정의(2026-09-25 감독기와 `/experiment` 명령을 삭제했다 — 재개하려면 `docs/prune/PRUNE_E.md`의 복구 절차부터).
5. 제안(미구현): 비밀의 **암호화 백업**(사용자가 기억할 passphrase 필요), 공인 IP가 Ephemeral일 때 DuckDNS 자동 갱신.
