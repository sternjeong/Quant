# 세션 인계

## 2026-10-07 실제 매입 기록 기반 코어·새틀라이트 재선정 알림

- 요청: 실제 매입일을 기준으로 종목·주수 안내, 코어에도 같은 방식 적용.
- 결정: 코어는 다음 월 첫 미국 거래일부터, 새틀라이트는 매입/보유 유지 확인일의 6개월 후 거래일부터 검토. 기간 만료만으로 매도하지 않는다. 최신 완전한 추천에서 제외된 기록은 해당 주수 매도 확인, 계속 선정되면 보유·목표비중 검토, 추천이 없거나 낡으면 재추천 필요.
- 구현: 기존 DB를 보존하며 운용 구분·보유 유지 확인일 컬럼 추가. 알려진 코어 ETF는 자동 분류, 일반 주식은 직접 관리가 기본; 새틀라이트는 표에서 지정한다. 오늘 처리할 일·포트폴리오·챔피언 주문 목록에 기록별 알림. 보유 유지 확인은 원래 매입일을 유지하며 다음 주기를 시작한다. 매도 후 수량 수정/기록 삭제는 사용자가 수행한다.
- 챔피언: 중복 티커의 실제 가치·주수를 합산해 비중 조정 계산. 등록 새틀라이트는 매입일별 알림을 사용하도록 일별 신규 추천의 교체 목록에서 제외. 코어 부분 조정 주수는 기존 주문 표에서 계산. 배포 중 새 함수·DB 필드 준비 전에는 안내 화면. 주문 제출·전략 변경 없음.
- 수정: `core/{portfolio,models,db,today_dashboard}.py`, 포트폴리오·챔피언 페이지, `app/views/today.py`, 관련 테스트, `docs/SPEC.md`, guide·인계·PROGRESS.
- 검증: 집중 테스트 138 passed. 기존 DB 기록 보존, 동일 티커 만료/미만료 물량 분리, 낡은/미래 추천 보류, 월말·휴일, 코어 월간 확인 및 다음 주기 복귀 검증. guide check·diff check 통과.
- 상태: 구현·검증·VM 배포 완료. `a551a77` origin/main 및 VM 반영, 전체 2506 passed·4 skipped(360.91초), Telegram runner 72 passed. 2026-10-07 11:42:10 UTC 재시작, 11:42:23 UTC 전체 서비스 정상. Streamlit·허브 health 정상, 운영 DB 두 컬럼 존재 및 새 helper import 확인. 개인 보유 내역은 조회하지 않았다. 배포 확인 기록은 개발 작업트리에 갱신했으며 문서만으로 배포 관문을 재실행하지 않았다. 다음: 사용자는 화면 새로고침 후 운용 구분을 지정하고 알림을 확인한다.

## 2026-10-07 보유 기록 편집 표 5행 높이

- 요청: '보유 종목' 편집 표는 5개 기록까지 보이고 이후는 내부 스크롤.
- 구현: `app/pages/8_포트폴리오_관리.py` data_editor에 행 높이 35px·최대 5개 행과 헤더를 포함한 높이를 지정했다. 전체 기록을 전달하므로 스크롤 아래 행도 기존 ID로 수정·저장할 수 있다. `/guide` 화면 안내도 갱신.
- 검증·배포: 화면 편집 회귀 1 passed, 가이드 검사 통과. `687dd72` origin/main 및 VM 반영. VM 전체 2494 passed·4 skipped(416.03초), Telegram runner 72 passed 후 2026-10-07 11:12:42 UTC 서비스 재시작. Streamlit·허브 health 정상, 세 서비스 active 확인. 이 배포 확인 기록은 개발 작업트리에만 추가했다.

## 2026-10-07 포트폴리오 ImportError 배포 확인·해소

- 사용자 오류: `aggregate_pnl_by_ticker` import 실패. VM 운영 파일에는 함수가 있었지만 Streamlit 프로세스는 10:33 UTC 시작의 이전 모듈을 메모리에 유지했다. 자동배포가 10:48 UTC 새 화면·모듈을 pull한 뒤 전체 테스트를 실행하는 동안 발생한 일시적 버전 불일치다.
- 이번 세션에서 로컬 systemctl·sudo 권한으로 VM `/opt/quant` 상태를 직접 조회할 수 있음을 확인했다. 이전의 'VM 접근 불가' 설명은 이번 환경에 적용되지 않는다. 운영 소스 직접 수정·테스트 관문 우회 없이 진행 중인 배포 완료를 확인했다.
- 배포: `7c6bd7d` VM 반영 완료. 전체 2494 passed·4 skipped(395.29초), Telegram runner 72 passed. 2026-10-07 10:55:40 UTC 서비스 재시작, 10:55:54 UTC 전체 서비스 정상 확인. Streamlit health·허브 health 모두 정상, 운영 venv 새 함수 import 성공.
- 코드 추가 수정 없음. 현재 사용자는 화면 새로고침으로 다시 진입하면 된다. 이 확인 기록은 개발 작업트리에만 갱신했으며 문서만으로 전체 배포 관문을 재실행시키는 푸시는 하지 않았다.

## 2026-10-07 포트폴리오 손익 표 티커별 합산

- 사용자 요청: '보유 종목 손익'에서 같은 티커의 매입 기록을 합쳐 표시.
- 구현: `core/portfolio.py`의 `aggregate_pnl_by_ticker()`가 수량·매입금액을 합산하고 수량 가중평균 단가로 손익률·비중을 재계산한다. 화면의 손익 표시 표에만 적용하며 개별 매입 기록·표 편집·매매근거 검증은 기존 기록별로 유지한다. 가격 결측은 0으로 오인하지 않고 미확인으로 표시한다.
- 수정 파일: `core/portfolio.py`, `app/pages/8_포트폴리오_관리.py`, `tests/test_portfolio.py`, `hub/guide/content_pages_a.py`, `hub/guide/content_modules_b.py`, 인계 문서·PROGRESS.
- 검증: 포트폴리오 테스트 56 passed, 가이드 검사·diff check 통과. 서로 다른 단가의 중복 티커 합산·손익률·가중평균·총 매입금액 보존·가격 결측을 검증했다.
- 상태: 구현·검증 완료, `c34d32b` origin/main 푸시 완료. VM 자동배포 완료는 직접 확인하지 못했다. 다음은 배포 후 화면 확인.

## 2026-10-07 챔피언 전략 투자금 배분·주수 계산

- 사용자 요청: 챔피언 전략의 추천 티커·비율에 투자 가능 금액을 넣어 종목별 배분 금액과 매수 주수를 계산한다.
- 구현: `core/champion_recommendation.py`에 순수 함수 `investment_allocation_with_shares()` 추가. 금액×목표비중 후 저장된 추천 기준가로 정수 주 내림, 주별 예상 매수액과 남는 현금을 계산한다. 가격 누락 시 그 종목을 표시하고 전체 잔액을 미계산으로 둔다.
- 화면: 챔피언 전략 `✅ 지금 할 일`의 목표 표에 항상 투자 가능 금액 시뮬레이션 입력 및 배분 금액·기준가·예상 주수·매수액을 표시. 이 표는 처음 구성 시나리오이고, 등록 보유가 있는 경우 3단계 실제 매매 목록은 등록 보유·현금 기준으로 별도 계산한다. 입력·계산은 주문 제출이나 보유 변경을 하지 않는다.
- 가격: 코어·새틀라이트 추천에 저장된 가격 근거를 우선 사용하고, BIL은 기존 화면 규칙과 같이 필요할 때 조회. 추천 기준일 표시 및 가격 변화·수수료·세금 제외 안내.
- 검증: 1,000달러·5,000달러 두 예산으로 XLE $63.08, XLK $201.62 기준 주수·매수액·잔액 산술 검증. missing price·비유한 예산도 확인. `tests/test_champion_recommendation.py` 60 passed, `python -m hub.guide.check`, `git diff --check` 통과.
- 수정 파일: `app/pages/11_챔피언_전략.py`, `core/champion_recommendation.py`, `tests/test_champion_recommendation.py`, `hub/guide/content_pages_a.py`, `PROGRESS.md`, 이 문서.
- 상태: 구현·검증 완료, 아직 커밋·배포 전. 다음은 커밋·main 반영 후 VM 자동배포 확인.

## 2026-10-07 R&D 센터 토글·후보 사유 가독성

- 사용자 요청: 연구 주제의 끄기/켜기 동작을 칸 안에 잘 들어가는 ON/OFF로 표시하고, 새틀라이트 후보 순위의 탈락 사유가 길게 세로로 늘어지는 문제를 개선한다.
- 구현: `hub/satellite_lab_page.py` 주제별 버튼을 고정 폭의 ON/OFF pill로 바꾸고 현재 상태 색상·접근성 라벨을 추가했다. 후보 표 탈락 사유를 `<br>` 강제 줄바꿈에서 구분점이 있는 인라인 문구로 바꾸고 셀 최소 폭·줄 간격을 지정했다.
- 가이드: `hub/guide/content_modules_b.py` 사용법을 ON/OFF 버튼 기준으로 갱신하고 verified 날짜를 2026-10-07로 올렸다.
- 테스트: `tests/test_rnd_topics.py`에 ON/OFF 버튼 및 탈락 사유 가독성 렌더 검증 추가. 대상 12 passed, `python -m hub.guide.check` 통과, `git diff --check` 통과.
- 수정 파일: `hub/satellite_lab_page.py`, `hub/guide/content_modules_b.py`, `tests/test_rnd_topics.py`, `PROGRESS.md`, 이 문서.
- 상태: 구현·검증 완료. 변경 커밋 `dae0b8f`를 VM 연구 결과 커밋과 병합한 `e4ddd8f`로 origin/main에 푸시했다. VM 연결 설정이 없어 실제 배포·재시작은 직접 확인하지 못했다.

최종 갱신: 2026-10-07 (자산군 확장·생존편향 연구 등록)

## 2026-10-07 오늘의 브리핑 가독성 개선

- 사용자 요청: `📋 오늘의 브리핑`에서 문장이 길게 세로로 쌓여 읽기 힘든 문제 해결.
- 구현: `core/daily_briefing.py` 본문 최대 폭을 1080px로 확대하고 카드 섹션을 데스크톱 2열, 620px 이하 화면 1열로 반응형 배치. 데이터 이상·운영 상태는 넓은 영역을 쓰고, 카드 안 긴 텍스트는 폭 안에서 자연 줄바꿈한다.
- 가이드: `hub/guide/content_modules_a.py`와 `hub/guide/content_ops.py`에 새 레이아웃과 확인 순서를 반영했다.
- 검증: `tests/test_daily_briefing.py` 20 passed, `python -m hub.guide.check` 및 `git diff --check` 통과.
- 수정 파일: `core/daily_briefing.py`, `tests/test_daily_briefing.py`, `hub/guide/content_modules_a.py`, `hub/guide/content_ops.py`, `PROGRESS.md`, 이 문서.
- 상태: 구현·검증 완료. main 반영 후 자동배포 확인 예정. 브리핑 HTML은 매일 00:25 KST 생성하므로 새 레이아웃은 다음 생성본부터 보인다. 이미 저장된 날짜별 HTML은 자동 재생성되지 않는다.

## 2026-10-07 자산군 확장·생존편향 연구 영역 추가

- 사용자 요청: 현재 후보군에서 부족한 자산군을 소수 추가해 연구하고, 생존 종목만 분석하는 편향을 줄이도록 상장폐지·거의 붕괴한 종목의 사전 위험신호를 조사한다. 사용자는 CRSP/WRDS 등 정식 자료를 사용할 수 있다고 확인했다.
- R&D 센터 `자산군 확장·생존편향 연구` 섹션을 별도로 추가. ETF 연구 후보 5개: 미국 소형주 IWM, TIPS TIP, 미국 리츠 VNQ, 신흥국 주식 VWO, 투자등급 회사채 LQD. 각 단독 추가와 5종 묶음을 현 17자산 코어 규칙과 비교한다. 후보군 실험이며 보유 개수·챔피언·주문은 자동 변경하지 않는다.
- 사전 등록 `core-universe-expansion-v1`: 가격 Close·수익 Adj Close, 2008~현재 요청, 동일 기간 기준선 비교, core-judge/v1의 6회 시도 조정 DSR·최종 2년 홀드아웃·하위기간·낙폭 관문과 편도 8bp 스트레스 기준을 결과 확인 전에 고정했다. 부족한 공통 데이터는 NOT_EVALUABLE_DATA.
- 사전 등록 `delisted-precursors-v1`: CRSP `permno`로 일별·상폐 테이블을 연결하고 기업별 첫 유효 `dlret≤-50%` 상폐를 사건으로, `dlret≤-80%`를 보조 통계로 둔다. CRSP 공식 정의의 -55/-66/-88/-99 결측 코드는 손실로 오인하지 않고 별도 센다. 상폐 126거래 관측치 전의 모멘텀·낙폭·변동성·가격·거래대금 신호를 같은 연도/SIC 2자리 산업 대조군과 비교하며 기업 군집 부트스트랩 구간을 낸다. S&P 지수 편출은 상폐로 취급하지 않는다.
- CRSP 원자료는 현재 저장소에 반입되지 않았다. VM 입력 계약은 `data/research_inputs/crsp_delisted/daily.csv`(permno,date,prc,ret,vol,shrout; siccd 선택)와 `delists.csv`(permno,date,dlret,dlstcd)이며 데이터 행·원본은 결과/커밋에 포함하지 않고 입력 해시와 통계만 출력한다. 파일이 없으면 VM 연구는 NOT_EVALUABLE_DATA로 결과를 남긴다. WRDS 추출/파일 배치는 연구 전체 계산 전에 필요하다.
- R&D 화면·가이드·스모크 테스트 구현. 합성 스모크는 ETF 6후보, CRSP 연구 SMOKE_ONLY와 사건/대조군·경고 신호 계산을 통과했다. 관련 테스트 8 passed, `hub.guide.check` 통과. 실제 가격·CRSP 전체 연구는 대화 세션에서 실행하지 않는다.
- 상태: **구현·스모크 검증 완료, 513ffe6 origin/main 푸시 완료**. VM 자동배포가 main을 확인하도록 올렸으며, 이 작업 공간에 VM 접속 설정이 없어 서비스 재시작·연구 실행기 pending 상태는 직접 확인하지 못했다. 배포 후 우선순위 37/38로 실행되며, CRSP 파일이 들어오기 전 상폐 위험신호 결과는 평가 불가다. 다음은 VM 반영 상태 확인, 허가된 CRSP 내보내기 파일 입력, 미평가 작업 재시도와 결과 검토다.

## 2026-10-07 토큰 없는 VM 연구 자원 상향

- 사용자 요청: Claude 토큰을 쓰지 않는 연구를 VM 하드웨어 자원의 약 80%까지 활용해 빠르게 수행한다.
- `core/research_jobs.py`: 연구 자식 우선순위를 nice 19→5로 올리고, Linux `/proc/stat` CPU 사용률이 80% 이상이면 해당 자식 프로세스 그룹을 정지, 70% 이하에서 재개하도록 추가했다(5초 폴링). 작업 RSS 상한은 `min(job.max_memory_mb, 총 RAM×80%)`; 기본 10,240MB, 시스템 가용 메모리 예약량은 `max(600MB, 총 RAM×20%)`다. 실행 전에도 예약량을 못 남기면 건너뛴다. 한 번에 한 작업·디스크/시간 예산·취소 보호는 유지한다.
- `core/resource_guard.total_memory_mb()`는 Linux `MemTotal`만 읽는다. 가이드와 `docs/RESEARCH_JOBS.md` 갱신. VM의 실시간 RAM/서비스 부하는 이 작업 공간에서 직접 조회하지 않았다.
- 검증: 연구 실행기·resource_guard·신규 연구 테스트 64 passed. CPU counter 산출과 80% pause/70% resume 신호, 12GB RAM 기준 9.6GB RSS 상한·2.4GB 예약량을 확인. 전체 pytest **2489 passed·4 skipped(422.57초)**, Telegram runner **72 passed**, 가이드 검사와 diff check 통과.
- CPU 제한은 5초마다 측정하는 피드백 제어로 순간 초과가 가능하다. 커밋 `a3ab2dc`를 신규 VM 결과 커밋 `05b5518`·`ef65127`과 병합한 `a804ec7`로 origin/main에 푸시했다. VM 실행기가 연구 결과를 게시한 사실은 확인했지만 방금 반영한 자원 정책의 VM 적용 여부는 이 작업 공간에서 직접 조회하지 못했다.

## 2026-10-06 코인 R&D 채택 상태 재확인 (읽기 전용 점검)

- 사용자 질문: 현재 연구가 코인 편입을 권고하는지 보류인지. 결론은 보류, 현 챔피언의 85% 코어·15% 새틀라이트 유지.
- 근거: info-rnd-v1 완료 결과 KEEP_CURRENT. 사전 등록 앞 구간 승자 BTC 코어 자산 추가가 떼어 둔 2년 샤프 0.99 vs 현 규칙 1.04로 최종 조건 미충족. EMA100 BTC·ETH 5%는 같은 표본에서 1.12 vs 1.04였으나 사후 선택이므로 채택 판정 아님.
- VM 직접 확인: champion-crypto-v2 failed·실패 3회, 코인 달력 일봉 누락으로 판정 결과 없음. 성과 FAIL과 구별한다. crypto_shadow·forward_tournament 원장은 각각 2줄(10/05·10/06), 10/06부터의 정식 기록은 막 시작했으며 252거래일 판정 전.
- 이번 점검은 결과·코드·상태 파일 읽기와 인계 기록 갱신만 수행. 연구 재실행·판정 변경·배분 변경·배포 없음. 다음은 과거 입력 확보 또는 새 id 사전 등록과 기존 전진 기록 누적 확인이다.
- 후속 질문 '관련 연구를 하고 있는지'에 VM 상태 재확인: 기존 연구 완료·전진 원장 최근 10/06 기록·후속 v2 데이터 실패 중단을 구분해 설명한다. 모든 연구가 정상 계산 중이라고 표현하지 않는다. 읽기 확인만 수행, 코드·운용 변경 없음.

## 2026-10-06 ETH 공통기간·BTC 매매규칙 후속 연구

- 사용자 요청: ETH 상장 이후 공통 기간으로 새 연구를 진행하고, 나아가 BTC 편입이 합리적일 때 적정 비중·코인 특성·매수/매도 규칙도 연구한다. 앞선 ID의 계약은 바꾸지 않고 두 개의 사전등록 작업으로 나눈다.
- `champion-crypto-v3`: ETH/BTC 공통 일봉 2017-11-09부터 EMA 워밍업, 평가기간 2018-03-01~2026-10-02, 기존 4개 BTC·ETH 후보와 고정 Holm 기준. VM 캐시에서 ETH 연속일봉, BTC 2019-12-31 누락을 확인했고 Yahoo Finance 직접 재조회로 해당 BTC Close를 받았다. 스크립트는 실행 때 누락 날짜만 제공자에 재요청, 여전히 비면 실패하며 합성/전방 채움은 하지 않는다.
- `champion-crypto-v4`: BTC 특성(분포·변동성·낙폭/회복·주말·챔피언/코어/SPY 상관) + 1/2.5/5/10% 고정 목표 비중, EMA50/100/200 추세 매수·매도, EMA100+60일 변동성 조절 12안. 2014-09-17 워밍업, 2015-01-01~2026-10-02 평가, 3개 사전 고정 시대 구간·12가설 Holm·BTC 50bp 비용 스트레스. 통과해도 `CANDIDATE_FORWARD_ONLY`, 별도 전진검증 필요.
- 두 작업은 각자 고정 SPEC/job.json/run.py, 원자 체크포인트, JSON/보고서 출력. hub 가이드 갱신. 합성 스모크 두 작업 통과(SMOKE_ONLY만 생성), 실행기 작업 정의 모두 유효, `python -m hub.guide.check` 통과.
- 전체 VM venv 검증: `pytest tests -q` 2482 passed·4 skipped(303.74초), 텔레그램 runner unittest 72 passed. 두 연구 스모크 및 이어읽기 재호출, 작업 정의 검증, guide check 통과.
- 배포 완료: **e9fee9b** origin/main 및 VM 반영. 자동 관문 `pytest tests` 통과, runner unittest 통과, codex-telegram/quant-streamlit/quant-scheduler/quant-hub 재시작 후 정상. VM 연구 실행기 목록에서 v3·v4 모두 `pending`, runs=0 확인. 연구창에 따라 순차 실행 예정(v3 priority34, v4 priority35); 실제 결과는 아직 없음.
- VM 결과 확인(2026-10-07): v3·v4 실행기가 계산을 끝내 `research/results/`에 보고서를 게시했다. 두 작업의 후보는 Holm 다중검정 보정 미통과로 모두 FAIL이며 일부는 IR도 미달한다. 코인 편입·챔피언 변경은 없다. 상세는 각 REPORT.md, 결과 커밋 `ef65127`·`05b5518`.
- 현재 결론: 전략·주문·기존 252일 원장 변경 없음. 결과는 후보 탐색 판단이며 별도 확인 없이 운용에 넣지 않는다.

## 2026-10-06 포트폴리오 표 직접 편집 (사용자 UI 정정 요청)

- 사용자 요청: 별도 종목 선택·수정 폼을 쓰지 않고 표 셀을 직접 수정. 기존 수정 폼을 '보유 종목' data_editor로 교체했다. 티커·수량·매입 단가·매입일 편집 후 '💾 표 수정 저장', 계산 열 매입금액은 읽기 전용. 가격 조회 이전에 편집 표를 표시한다.
- 저장: 숨긴 행 인덱스의 원래 보유 ID로 변경 행만 저장(동일 티커 여러 행 구별). core.portfolio.update_holdings가 모든 입력·대상 존재를 확인하고 한 트랜잭션으로 저장한다. 잘못된 행/사라진 기록이 하나라도 있으면 다른 행도 저장하지 않는다. 기존 매매근거·검증 이력 보존, 저장 후 표 상태와 분석 갱신. 삭제는 별도 '보유 기록 삭제'에 유지.
- 수정 파일: app/pages/8_포트폴리오_관리.py, core/portfolio.py, tests/test_portfolio.py, hub/guide/content_pages_a.py·content_modules_b.py, docs/SPEC.md, 인계 문서.
- 검증: VM venv 포트폴리오 55 passed(실제 data_editor 세션 edited_rows로 셀 변경→저장→재조회 AppTest, 중복 티커·잘못된 마지막 행/없어진 ID의 전체 저장 거절), 가이드 28 passed·설명 검사·diff check 통과. 추가로 셀의 단가·날짜 변경(행 순서 변경)까지 같은 AppTest를 강화해 1 passed 확인. 실제 보유 데이터는 읽거나 바꾸지 않았다.
- 배포 완료: 구현 8889a77을 원격 야간 시장 스냅샷 3개와 병합해 **5df4da4 main·VM 반영**. 2026-10-06 23:10 UTC 관문 전체 **2482 passed·4 skipped(328.43초)**·러너 unittest 72 OK, 서비스 재시작 후 모두 정상 확인. 사용자가 새로고침해 표 셀 편집 후 저장하면 된다.

## 2026-10-06 포트폴리오 관리의 보유 기록 수정

- 요청: 실제 보유 종목 입력의 오타를 화면에서 고칠 수 있도록. 실제 보유 데이터는 직접 열람하거나 수정하지 않았다.
- 구현: 화면 상단 '✏️ 보유 종목 수정 / 삭제'에서 기록 ID별 선택(티커·매입일·수량 표시), 티커·수량·매입 단가·매입일 수정. 가격 조회가 대기/실패여도 양식에 접근할 수 있다. 동일 티커 여러 매입도 각 기록을 선택해 수정·삭제한다.
- 구현: core.portfolio.update_holding에 keyword-only ticker 추가(기존 positional 호출 호환), 공백 제거·대문자 정규화, 빈 티커·0 이하/비유한 수량·단가 거절. 기존 ID·매매근거·과거 검증 스냅샷 유지. 손익/리스크 조회 키에 입력값 포함, 오래된 코멘트와 수정 전 진행 중 검증의 화면 추적 해제.
- 수정 파일: core/portfolio.py, app/pages/8_포트폴리오_관리.py, hub/guide/content_pages_a.py·content_modules_b.py, docs/SPEC.md, tests/test_portfolio.py, 인계 문서.
- 검증: VM venv 대상 포트폴리오·가이드 80 passed. 임시 DB로 기록·검증 이력 보존 및 잘못된 수정의 원본 보존, Streamlit AppTest로 가격 조회 완료 전 수정·중복 티커 구별·조회 키 갱신 확인. 가이드 검사·diff check 통과. 전체 **2479 passed·4 skipped(475.70초)**, 텔레그램 러너 unittest 72 OK. 커밋·배포 준비 완료, VM 관문은 아직.
- 배포 완료: **1afc91f** main 반영, 2026-10-06 10:54 UTC VM 자동배포 관문 2479 passed·4 skipped(368.40초)·러너 unittest 72 OK, 서비스 재시작 및 정상 상태 확인. 사용자가 페이지를 새로고침해 기록을 선택한 뒤 직접 정정하면 된다.
- 별도 읽기 확인: 이전 champion-crypto-v2 연구는 VM에서 실패 3회 후 failed. 원인은 '코인 달력 일봉 누락'(ETH 캐시 최초 2017-11-09라 사전 등록 2016년 시작을 충족하지 못함, BTC 캐시에도 달력일 2개 부족). 기존 판정/기간을 사후 변경하지 않았다. 데이터 확보 또는 새 id 사전 등록이 필요하며 이번 포트폴리오 수정 범위에서는 연구 계약을 변경하지 않았다.

## 2026-10-06 챔피언 2023·2026 패배 분석 + 코인 VM 연구

- 요청: 두 해의 패배 원인 분석 및 코인 결합안을 R&D 센터에 등록해 VM 연구. 엔진 변경·주문 변경은 요청에 포함하지 않았고 수행하지 않았다.
- 근거: 저장 champion_performance_807d356e7c530722.json(2021~2026-10-02), 비중 이벤트·core_holdings·VM 가격 캐시. 두 해 절대 수익은 양수: 2023 +5.80% vs SPY +26.18%, 2026 YTD +10.77% vs +13.75%.
- 해석: 2023 코어 +2.50%(직전 에너지·원자재 승자, BIL, XLK 5월/XLC 6월 진입), 새틀라이트 +24.96%가 완화. 2026 코어 +12.25% vs 새틀라이트 +0.83%, 새틀라이트 배분이 코어 단독보다 약 1.49%p 낮춤. 종목 기여의 캐시 대조 차이는 2023 약 0.000007%p, 2026 −0.1705%p라 2026 종목 기여는 근사로 표시. 상세 docs/CHAMPION_2023_2026_CRYPTO_RESEARCH.md.
- 사전 등록·구현: research/jobs/champion-crypto-v2/{job.json,SPEC.md,run.py}. 2016~2026-10-02 고정, EMA100 코인 최대 5% 4개(혼합 코어 재원/BTC 단독/혼합 새틀라이트 재원/변동성 축소). 기존 코인 결과를 이미 봤으므로 탐색이며 최고 판정 CANDIDATE_FORWARD_ONLY. CAGR·양 구간·IR·MDD·25bp 비용 스트레스·20일 블록 2,000회 Holm α=.05 고정. 기존 252일 코인 shadow·forward 토너먼트 불변.
- 구현: 동일 챔피언 기준선과 코어·새틀라이트 종목 기여의 일별 대조(1e-9), 입력·계약 해시 및 원자 체크포인트, 예산 부족 종료 3. 전체 챔피언 1회 계산 중 끊기면 해당 단계 재실행, 완료 입력은 재사용. hub/satellite_lab_page.py의 '사전 등록 VM 연구' 상태 표·결과 링크와 hub/guide/content_modules_b.py 설명 추가.
- 검증: VM /opt/quant/.venv Python 사용. 합성 스모크 종료 0, 신규 5개 테스트(미래정보·현금 전환·판정·3→0 재개·화면 escape) 통과. 관련 회귀 64 passed. 전체 2471 passed·4 skipped(539.90초), 가이드 검사·diff check 통과. 마지막 가격 입력 ffill·엔진 소스 해시 보강 후 신규 5개 재검증 통과. 실제 전체 연구는 대화 세션에서 실행하지 않았다.
- 배포 완료: f663da5 구현을 VM의 새 champion-aftertax-v1 결과 커밋과 병합해 **56d1943**으로 main 반영. 2026-10-06 04:43 UTC VM 자동배포 완료, 실제 관문 2471 passed·4 skipped(421.53초, 480초 이내), 러너 unittest 72 OK. 서비스 정상. 운영 트리 직접 수정 없음.
- VM 접수 확인: champion-crypto-v2 status=pending, runs=0. 전체 계산 완료는 아직 아니다. 다음: VM 연구 창에서 실행 → research/results/champion-crypto-v2/ 보고서·텔레그램 결과. 좋은 역사 결과여도 운용 반영은 사용자 확인 이후 별도 작업.

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

## 2026-10-08 (후속5) 반등장 연구 등록 — 코어도 알파를 (사용자 의도)

- 근거: docs/CHAMPION_2023_2026_CRYPTO_RESEARCH.md(2023 −20.4%p: XLE·DBC 유지, XLK 5월·XLC 6월 편입, 1월 코어 75% BIL).
- core_lab.CoreConfig 옵션 추가(기본 꺼짐, 라이브 영향 없음): turnaround_lookback/months, cash="bil_spy", cool_exclude. 단위 테스트 3개.
- research/jobs/rebound-rnd-v1(rebound-judge/v1, priority 15): H1 전환점 가속, H2 빈 슬롯 SPY, H3 H1+H2, H4 식은 승자 제외,
  H5 국면 전환(월초 SPY ≥ 200일선이면 SPY 100%, 아래면 현 코어 — 사용자 "강세장엔 흐름 타고 고꾸라지면 방어"). 판정: 앞 구간 샤프 > V0 & DSR ≥ 0.95(시도 5),
  가족 PBO ≤ 25%, 떼어 둔 2년 샤프 > V0, 세후 원화 > V0. SPY 대비 세후 차이·회귀 알파·반등/하락 해 격차는 보고. 스모크만 실행.

## 2026-10-08 (후속4) 테마 순환 연구 등록 (사용자 기준: 1 지금 불장인 시장 2 빨리 잡기 3 많이 안 갈아타도 SPY 압도)

- research/jobs/theme-rotation-v1(theme-judge/v1, 사전 등록, priority 20): 테마 ETF 28개 고정(상장 252거래일 뒤부터 후보), '불장' = 200일선 위 & L일 수익률 > SPY,
  규칙 18개(L 21/63/126 × 상위 1/2/3 × 보유 1/3개월, 남는 슬롯 SPY), 기준선 SPY 그냥 보유. 판정 A: 앞 구간 최선의 SPY 대비 DSR ≥ 0.95·PBO ≤ 25%·떼어 둔 2년 샤프 > SPY,
  B: 세후·청산 후 원화 연수익이 SPY 보다 전체 +2.0%p 이상 & 떼어 둔 2년에서도 높음. 진단(판정 아님): 적중률·뜨거운 달 포착률·지연.
  스모크만 실행(종료 0). 2007년부터라 2008 하락장 포함.
- 7700094 배포 관문 실패 1건(test_worker_smoke_runs_end_to_end SIGTERM) — 같은 시각 5년 세후 계산(대화 세션)이 VM 을 점유해 579초. 코드 문제 아님 → 재배포.
  **교훈: 배포 직후 관문이 도는 동안 무거운 계산을 돌리지 않는다.**
- 사용자 질문 "5년은 챔피언이 낫지 않았나" — 측정(2021-01-04~2026-10-07, 3,000만 원, 원화): 세전 챔피언 22.12% vs SPY 20.46%(달러 기준 17.6% vs 15.3%),
  세후 평가액 19.11% vs 20.19%, 지금 다 팔면 18.14% vs 17.35%, MDD −17.4% vs −17.1%. 1억: 청산 후 17.44% vs 17.25%. → 최근 5년은 세후로 거의 비김.

## 2026-10-08 (후속3) 애널리스트 R&D 등록 + R&D 결과 종합

- VIX(공포지수)는 info-rnd-v1 A(13변형, KEEP_CURRENT, PBO 40%)·tech-rnd-v1(고변동 게이트) 에서 이미 기각 → 재시험 안 함.
- research/jobs/analyst-rnd-v1(analyst-judge/v1, 사전 등록): 현 새틀라이트(S-SEED-000) + V1 목표가 하향 거부권·V2 등급 하향 거부권·V3 목표가 상향 가점·
  V4 목표가 괴리 상위. yfinance upgrades_downgrades(2012~, 리밸런싱 전날까지). 판정: 앞 구간 반기 초과 평균 > 0 & t ≥ 본페로니(α=0.05/4),
  떼어 둔 2년 > 0, 선택이 바뀐 반기 ≥ 3. t 분위수는 scipy 없이 코니시-피셔(검증: 자유도 9·19·30 에서 표값과 일치). 스모크만 실행.
- R&D 종합(사용자에게 보고): 코어·새틀라이트·실행·세금·코인·VIX·유니버스 확장 등 거의 모든 사전 등록 변형이 FAIL/KEEP_CURRENT. 세후 원화(2010~) 챔피언 11.13% vs SPY 15.12%,
  원화 MDD −24.2% vs −29.7%. 다음 제안(미실행): 'SPY 85% + 새틀라이트 15%' 등 SPY 기반 배분을 같은 세후 측정으로 사전 등록 비교.

## 2026-10-08 (후속2) 코어에서 PTP(DBC) 제외 — 사용자 결정

- 사용자: "PTP 종목은 판매 금액의 10% 를 내야 해(IRC 1446(f) 외국인 매도 원천징수). DBC 는 PTP." 측정(사전 등록 아님, 2010~ 배당 포함 코어 100%):
  17자산 10.10%/MDD −19.8% → DBC 제외 9.49% → PDBC 교체 9.56%(2015~: 8.84 / 8.40 / 8.08). 사용자가 'DBC 빼기(16자산)' 선택.
- champion_strategy.CORE_UNIVERSE 16자산, PTP_EXCLUDED=("DBC",), CORE_UNIVERSE_V2026_10(옛 17자산), 버전 core-momentum-top4+spy200dma/2026-10-bil-noptp
  (예전 추천·새벽 캐시 자동 무효). core_lab.CoreConfig.universe 추가. **앞으로 토너먼트(forward-tournament/v1)는 등록 당시 17자산을 고정** — 라이브 T0 와 이제 다름.
  geo_shadow·agent_batch 문구는 자산 수를 코드에서 읽음. 오늘 코어: XLE·XLK·XLV·XLB(DBC 자리 → XLB).
- 미처리: 새틀라이트(S&P500 개별주) PTP 검사는 하지 않음(S&P500 에 PTP 가 거의 없음 — 필요하면 목록 추가). 사용자 계좌에 DBC 가 있다면 '추천 밖 보유'로 전량 매도 안내가 나온다(그때 10% 원천징수 발생 — 사용자 판단).

## 2026-10-08 (후속) 주문 목록을 '할 일 문장'으로 + 정수 주 주문 (사용자 "주문목록에서 뭘 말하고자 하는지 전혀 모르겠다")

- 사용자가 잔고 맞추기를 썼으나 입력칸이 기존(틀렸을 수 있는) 합계로 미리 채워져 있어 같은 수량(XLK 2·XLE 6·XLV 1·FCX 2, 현금 0)이 다시 저장됨 → 표가 그대로.
  수정: 입력칸을 비우고 '지금 기록'은 참고 문구로만. 실제 수량은 사용자 확인 필요(데이터는 손대지 않음).
- champion_recommendation.whole_share_orders(목표 금액 ÷ 현재가 반올림, 매도는 보유 이하, 매수 합계가 매도 대금+현금 넘으면 넘친 매수부터 줄임)·
  whole_share_text·order_steps. 화면 11 3단계: '① 먼저 팔기 / ② 판 돈으로 사기 / 이번엔 안 해도 되는 것(이유)' 문장 + 남는 현금, 근거 표는 접어 둠.
  아침 텔레그램 주문 줄도 정수 주. 세금 미리보기는 정수 주 수량 사용.
- 테스트: VM venv 전체 2511 passed. 사용자 사례(총 $1,095) → XLK 1주·XLE 2주·FCX 1주 팔기, DBC 7주 사기, XLV·CAT·GEV 건너뜀.

## 2026-10-08 잔고 한 번에 맞추기 (사용자 "실제 내 포트폴리오에 맞게 싱크… 혼선이 없도록")

- 원인: VM 보유 기록에 XLK(10/06·10/07 각 1주)·XLE(각 3주)가 두 줄씩 → 주문 목록이 XLK $403 으로 계산. 사용자 실제 수량은 아직 미확인
  (사용자가 'XLE 2주, XLK 6주'라 했으나 입력·총액과 맞지 않아 되물음 → "직접 다시 적겠다"). **보유 데이터는 손대지 않았다.**
- 카카오페이증권은 개인 공개 API 가 없어 자동 연동 대신 사용자 선택 '잔고 한 번에 덮어쓰기'로 구현: core/portfolio.parse_balance_text·plan_balance_sync·sync_balance
  (종목당 한 줄로 합침, 적지 않은 종목 삭제, 평균단가 생략 시 기존 가중 평균, 매입일은 가장 이른 기록, 현금 잔고 함께, 한 트랜잭션).
  화면 8 맨 위 '📋 잔고 한 번에 맞추기'(미리보기 → '✅ 이대로 맞추기'), '➕ 보유 종목 추가'에 이미 있는 종목이면 합산 경고.
- 한계: 종목을 한 줄로 합치면 매입일별 기록(세금 플래너의 매입일 환율)이 가장 이른 날 하나로 근사된다.
- 테스트: VM venv 전체 2508 passed·4 skipped. AppTest(임시 DB)로 중복 XLK 2줄 → 1줄 합침 확인.
- 배포: caf3f8d 관문에서 전체 2508 통과했지만 528초로 480초 제한 초과(같은 시각 다른 분석 스크립트가 CPU 사용) → 재배포. **테스트가 부하에 따라 280~530초 — 관문 제한 상향 또는 테스트 단축 검토 필요(제안, 미실행).**
- 다음: 사용자가 실제 잔고로 한 번 맞추기. 주문 목록 소수점 금액·정수 주 최적 배분 표시(제안만, 미구현).

## 2026-10-06 (후속6) 세후 계산에 새틀라이트 15% 포함 + 2010~ 측정 작업

- tax_fx.champion_weights(코어 × 0.85 + 새틀라이트 반기 선정 로그 × 0.15, 첫 선정일부터, 슬리브 사이 매일 재조정 없음)·run_champion_vs_core(새벽 계산의 최근 3년 챔피언 백테스트 rebal_log 사용).
  화면 16 '대상' 선택(코어만 / 코어 85% + 새틀라이트 15%). 실데이터(2024-01-02~2026-10-05, 3,000만 원): 챔피언 세전 26.45% → 세후 23.94%(양도세 1.70백만),
  코어만 23.23% → 21.22%(1.01백만), SPY 23.93% → 23.65%(세금 이연). 한 구간(약 3년)이라 결론 아님.
- 연구 측정 champion-aftertax-v1(판정 없음, priority 35, 타임아웃 3시간): run_champion_backtest 2010~ 로 같은 계산 — VM 실행기가 돌림. 스모크만 실행(종료 0).
- 테스트 시간: 4분 40초(부하 없을 때) vs 6분 47초(연구 실행기와 겹칠 때). 특정 테스트 문제 아님(최장 19초 satellite_lab 스모크).
- 테스트: 전체 2465 passed·4 skipped.
- **배포 관문 실패 2회(2eb5374·5df1be1, 서비스는 bf9ed0d 유지) → 고침:** 10/06 새벽 계산 결과가 VM 에 생기자 챔피언 전략 화면 '새틀라이트 반기 리밸런싱 로그' 표의
  ranked_active([종목, 점수] 목록, JSON 으로 읽어 문자·숫자 혼합)가 Streamlit 1.63(VM)에서 표 변환 예외 → 화면 전체 멈춤(실서비스도 10/06 아침부터 같은 문제였을 것).
  로컬 .venv 는 Streamlit 1.64 라 재현 안 됨. 수정: 목록·사전 열을 글자로 바꿔 표시, tests/conftest.py 가 새벽 캐시·tax_year.json 을 임시 위치로 격리,
  회귀 테스트(test_page_shows_dawn_backtest_with_ranked_active_lists — VM venv 에서 수정 전 실패·후 통과 확인).
  **교훈: 배포 전 전체 테스트를 /opt/quant/.venv/bin/python 으로도 돌린다(라이브러리 버전이 다름).** VM venv 전체 2466 passed.
  **배포 완료 3c95373**(관문 통과 23:50 UTC, 서비스 재시작) — 새틀라이트 포함 세후 화면·champion-aftertax-v1 작업도 이 배포로 반영.

## 2026-10-05 (후속5) 세금을 고려하는 엔진 (사용자 "이러한 세금들도 고려하도록 엔진을 구축해주라")

- **tax_fx 수정 2건(이전 숫자 정정):** ① 배당을 다음 리밸런싱까지 현금으로 두던 것 → 받는 날 같은 종목 재투자(SPY 그냥 보유가 연 1.3%p 낮게 나오던 원인).
  ② 세전 기준선이 리밸런싱 날 수익에 새 비중을 쓰던 하루 앞선 계산 → 고침(코어 세전 11.58% 는 부풀려진 값, 맞는 값 11.22%; 이제 무비용 계좌 = 기준선 정확히 일치, 테스트).
  정정된 실데이터(2010~, 3,000만 원): 코어 세전 11.22% → 세후 9.28%(청산 126.7백만, 원화 MDD −25.6%), SPY 15.41% → 15.10%(청산 259.0백만, MDD −29.7%), 코어 매번 환전 2.61%.
- tax_fx 옵션: harvest_gains(연말 공제 채우기)·harvest_losses(연말 손실 확정) — 12월 마지막 거래일 3일 전 팔았다 바로 다시 사기. 결과에 harvests.
- **core/tax_planner.py(신규, 도구):** 포트폴리오 보유(매입일 환율로 원화 취득가, 이동평균) → 종목별 원화 손익, 매도별 실현 차익, 공제 잔액·다음 해 5월 예상 세금, 연말 제안(11/15 부터 '지금 할 때').
  올해 실현 이익은 사용자 입력(data/tax_year.json). 화면: 16 '📒 내 계좌 올해 세금' 탭, 11 3단계 '🧾 이 매도들의 세금 미리보기'(토글 켤 때만 환율 조회),
  아침 09:01 텔레그램에 11/15~12/26 연말 점검 한 줄. 매매 규칙은 바꾸지 않음.
- **연구 tax-rnd-v1(사전 등록, tax-judge/v1):** V1 공제 채우기·V2 손실 확정·V3 둘 다·V4 순위 완충 6·V5 V3+V4 vs V0, 지표 세후·청산 후 원화 연수익.
  PASS = 전체 ≥ +0.15%p & 두 절반(2010~2017, 2018~) 모두 > 0 & 1억 계좌 > 0 & MDD 3%p 이내. V4·V5 는 sprint F2 에서 본 설정이라 PASS 여도 앞으로 검증 먼저.
  스모크만 실행(가짜 데이터, 종료 0). 전체 계산은 VM 실행기(priority 30). 엔진 반영은 결과와 사용자 확인 뒤.
- 미확인(사용자 확인 필요): 카카오 자동환전 우대율, 취득가액 방식, 한국 해외주식에 wash sale 규정 없음, 연말 결제 마감일.
- 테스트: 전체 2464 passed·4 skipped(이번 실행 6분 48초 — 이전 4분 35초보다 느림. 배포 관문 480초에 가까워지면 원인 확인 필요).
- 상태: **배포 완료**(0ca335a, VM 관문 통과 14:59 UTC). **tax-rnd-v1 결과(10/06 01:00 KST, research/results/tax-rnd-v1): 5개 모두 FAIL.**
  V0 세후·청산 9.01%. 공제 채우기 +0.05%p·손실 확정 +0.03%p·둘 다 +0.06%p(양도세 12.2→10.9백만) — 방향은 +지만 기준 0.15%p 미달, V1 은 앞 절반 −0.03.
  매번 원화 환전이면 오히려 손해(−0.5%p). 순위 완충 6 은 MDD −25.6→−19.9% 로 낮췄지만 수익 −0.46%p(뒤 절반 −1.66). 엔진 반영 없음.
  해석: 코어는 매달 갈아타 해마다 이미 이익을 실현하므로(공제가 대개 이미 소진) 연말 수확의 여지가 작다. 플래너 제안은 개별 계좌의 수수료 대비 이득을 보여 주는 도구로 유지.
- 첫 실제 실행 확인(VM): forward_tournament_record 10/05 15:39 UTC 첫 줄 기록(날짜 2026-10-05 — START 이전이라 평가는 10/06 줄부터), dawn_precompute 10/06 기준일 5단계 모두 정상 1,150초.

## 2026-10-05 (후속4) 세후·환전 후 계산 + 앞으로 토너먼트 + 새벽 미리 계산 (사용자 요청)

- **새벽 미리 계산**(요청 "당일 눌러서 확인할 수 있는거 미리 새벽 시간에 돌려놔"): core/dawn_precompute.py + 잡 dawn_precompute(06:40 KST, 기본 켜짐, VM 여유 최대 20분 대기).
  가격 최신화 → 챔피언 성과 최근 5년 → 챔피언 전략 point-in-time 새틀라이트·3. 백테스트(최근 3년)·S&P500 스캔. 화면 버튼과 같은 함수, 화면 11·14 가 '🌅 새벽 자동 계산 결과'로 자동 표시(7일 이내·같은 사이징·같은 전략 버전).
  하위 에이전트가 만들다 API 529 로 멈춘 것을 이어받아 테스트·가이드 추가. 테스트가 DataFrame 날짜 인덱스 유실을 잡아 저장 형식에 인덱스 보존 추가(옛 파일도 읽힘).
  로컬 실데이터 1회 전체 실행: 5단계 모두 정상, 1,265초. 주간 엔진 점검에 '새벽 미리 계산' 항목.
- **세후·환전 후 계산**(카카오페이증권): core/tax_fx.py(수수료 0.1%, 환전 스프레드 1%×(1−우대율), 양도세 250만 공제 후 22%·다음 해 5월 납부·이동평균/선입선출, 배당 원천징수 15%)
  + 화면 '세후 수익 계산'(app/pages/16, 운용 메뉴). 실데이터(2010~, 3,000만 원, 코어 100%): 세전 연 11.58% → 달러 보유 세후 9.26% / 매번 환전(우대 0%) 2.62% / 선입선출 9.20%.
  SPY 그냥 보유 세전 15.41% → 세후 13.98%(최종 268.7백만, 지금 다 팔면 221.7백만). 원화 기준 최대낙폭 코어 −25.6% vs SPY −26.5%(원화 기준에서는 코어의 낙폭 이점이 거의 없음).
  미확인: 카카오 자동환전 우대율, 카카오 취득가액 방식 — 화면에서 사용자가 골라 보게 함. 새틀라이트 15% 미포함. 추정치, 신고용 아님.
- **앞으로 토너먼트**(forward-tournament/v1, 결과 보기 전 고정): core/forward_tournament.py, T0 현 코어·T1 BTC 18번째·T2 9개월 5종목·T3 혼합·상관 0.8·완충 6·T4 4분할·T5 코어+코인 5%·B1 SPY·B2 60/40.
  잡 forward_tournament_record(00:39 KST)가 2026-10-06 부터 원장 data/forward_tournament/ledger.jsonl 에 하루 1줄, R&D 주제 'forward_tournament'(주제 7개), R&D 센터 '앞으로 기록' 표, 주간 엔진 점검 항목.
  252거래일 뒤 판정: T0 대비 IR ≥ 0.5·누적 초과 > 0·MDD 가 T0 보다 5%p 넘게 나쁘지 않음. 배분·주문 미연결.
- 상태: 구현·전체 테스트 통과(로컬 4분 35초). **배포 완료**: 8aa378f, VM 테스트 관문 통과(14:17→14:22 UTC)·서비스 재시작, 배포 코드에서 잡 2개 시각·주제 7개·'세후 수익 계산' 메뉴 확인. 새 잡의 실제 첫 실행(00:39·06:40 KST)은 아직 확인 전.
- 다음: 10/06 이후 원장 첫 줄 확인, 내일 06:40 새벽 계산 VM 실행 확인, 세후 계산에 새틀라이트 15% 포함(선택), 카카오 자동환전 우대·취득가액 방식 사용자 확인.

## 2026-10-05 (후속3) R&D 센터 주제 켜기/끄기 + 새틀라이트 진입·매도 규칙 + 코어 분기 연구실

- core/rnd_topics.py: 주제 6개(sat_selection·sat_entry·sat_exit·core_quarterly·geo_shadow·crypto_shadow), data/rnd_topics.json, 기본 켜짐.
  끄면 새 아이디어·재작업·판정(기록)이 멈추고 상태·대기열·시도 수는 보존 → 다시 켜면 이어짐. 관제 센터 'R&D 센터'(/satellite-lab, /rnd) 맨 위 버튼(POST /rnd/topics, 같은 출처 확인).
  tests/conftest.py 에서 모든 테스트가 임시 주제 파일을 쓰게 격리(VM 설정이 배포 관문을 흔들지 않게).
- 새틀라이트: entry(close·delay·pullback)·exit(none·trailing_stop·take_profit·time_stop·trend_break)·topic 필드, 시뮬레이터 일반화(기본값은 이전과 같은 결과 — 기존 테스트 통과).
  structure_key 에 진입·청산 포함(무작위 기준선이 같은 규칙으로 비교). 야간 배치는 켜진 주제 중 가장 적게 한 주제로 새 아이디어, 꺼진 주제의 진행 중 아이디어는 건너뜀.
- 코어 분기 연구실: core/core_rnd.py(설정 조합만, 코드 없음, 시도 수 229 에서 시작), scripts/core_lab_worker.py, 역할 core_designer(분기 1회 + 형식 오류 시 1회 더),
  research_jobs 빈 창에서 새틀라이트 다음 순서로 판정, 텔레그램 '[코어 분기 연구]'. 프롬프트 research/agent_prompts/core_designer.md.
- 주의(이번 세션 실수): 날짜 일괄 치환(sed)이 관련 없는 테스트 2개의 날짜까지 바꿔 실패 → 되돌림. 일괄 치환은 대상 파일을 좁혀서.
- 테스트: 전체 2440 passed·4 skipped.

## 2026-10-05 (후속2) 주문 목록에 현재가·약 몇 주 + 아침 텔레그램 주문 줄

- 챔피언 '지금 할 일' 3단계 표에 현재가·약 몇 주(전량 매도는 보유 수 그대로, 매도는 보유 수 이하), 주문 방식 문구(장 마감 무렵 시장가, 지정가·목표가 없음).
  현재가는 재추천 근거 표에서, 페이지 진입 시 조회는 BIL 하나뿐(차트 클릭 전 가격 조회 금지 원칙 유지 — 테스트가 잡음). 1주 미만이면 그렇게 표시.
- 아침 09:01 텔레그램에 주문 줄(보유 등록 시 보유 기준, 아니면 $10,000 새 시작 기준) 최대 8줄.
- 사용자 질문 '코어는 매달 바꾸나' — 2008~ 226개월 중 종목이 바뀐 달 68%(대부분 1종목, 평균 0.84종목/월), 32% 는 그대로.

## 2026-10-05 (후속) 새틀라이트 배당 포함(sat-judge/v2) + 코인 추세 슬리브 앞으로 기록 (사용자 "진행시켜")

- 새틀라이트 R&D: LabData.closes 를 Adj Close 로(신호는 ohlcv Close 그대로 — 현 규칙 선택 불변). JUDGE_VERSION sat-judge/v2, migrate_registry() 가
  v1 등록부를 registry_sat-judge_v1.json 으로 보관하고 모든 아이디어를 재심판 대기열에(누적 시도 수 유지). has_work 가 버전 차이를 '할 일'로 봄.
  기준선 캐시 이름에 버전 포함. sprint-2w F1·tech-rnd-v1 도 다음 실행부터 같은 데이터 경로라 총수익 기준.
- core/crypto_shadow.py(crypto-forward/v1): BTC·ETH EMA100 위면 보유, 5% 코어에서, 2026-10-06 부터 매일 00:37 KST 원장 기록(잡 crypto_shadow_record).
  252거래일 뒤 판정(초과 IR ≥ 0.5 & 누적 > 0). 평가는 기록된 상태만, 기록이 있는 날까지만(테스트에서 기록 뒤 날짜까지 늘려 평가하던 버그 발견·수정).
  주간 엔진 점검에 '코인 추세 기록' 항목 추가(12개).
- 테스트: 전체 2426 passed·4 skipped.

## 2026-10-05 주간 엔진 점검 잡 (사용자 요청, 구현·전체 테스트)

- core/engine_audit.py + scripts/engine_audit.py + 잡 engine_weekly_audit(월 08:15 KST, 토글 기본 켜짐, 읽기 전용). 11개 항목(서비스·자동 잡·백업·배포 동기화·연구 실행기·
  새틀라이트 R&D(설계 횟수 상한 초과 = 오염 탐지 포함)·야간 AI 에이전트·아침 재추천(버전 바뀐 뒤부터 셈)·신호/가격·국제정세·디스크), 텔레그램 1건 + data/engine_audit/.
- 배포 전 실제 VM 데이터로 시험 실행: 11개 중 10개 정상, 아침 재추천 누락은 버전 변경 전 날짜 오탐 → 고침.

## 2026-10-05 상태 점검 (사용자 요청 "연구 에이전트·엔진 정상 작동?")

- 정상: 서비스 4개 active. 연구 작업 전부 done(info·tech·sprint-2w 는 10/02 저녁 첫 실행에 끝까지 계산 — 스프린트 1,044+180+22+F4 완료, 결과 research/results/). 아침 재추천 10/03·04·05 09:01 실행·캐시 저장. 새틀라이트 R&D: 에이전트 아이디어 S-20261004-001(거래 과열 승자 제외)이 테스트·Critic 통과 → 10/05 13:20 심판 FAIL(91백분위). 새벽 배치 매일 실행(scout·sat_designer·sat_critic·postmortem).
- 이상 1(수정): 10/02 배포 관문의 test_agent_system(당시 격리 없음, 테스트 시각 2026-10-05 03:10)이 VM 실제 data/satellite_lab/agent/S-20261005-001.json 에 가짜 설계 횟수를 남겨, 10/05 새벽 진짜 아이디어가 1회 실패로 바로 폐기됨. 58e8361 에서 격리는 이미 고쳤고, 상태 파일을 rounds=1 로 수동 정정(note 필드).
- 이상 2(수정, 미배포): sat_designer 가 thesis/source 글자 수(500/300) 제한을 몰라 형식 탈락 → _sat_contract.md 에 명시. Claude CLI 백업·MCP 로그(.claude/backups, .cache/claude-cli-nodejs)를 _guard 가 매번 지우며 경고 → .gitignore.
- 참고: writer(일반 가설) 10/05 실패 1회, S-20261003-001 은 자기 테스트 실패로 오늘 밤 폐기 예정(정상 동작).
- 결과 요약: sprint-2w 4가족 전부 KEEP_CURRENT(F1 승자 PBO 79%, F2 9개월·5종목이 앞 구간 최선이나 PBO 57%·최근 2년 패배, F3 보유 중 매도 규칙 전부 현 규칙보다 나쁨, F4 PBO 57~86%). tech-rnd-v1: 단독·결합 모두 KEEP_CURRENT(차트 규칙 최고 골든크로스 0.82 < 새틀라이트 0.85, 고변동 국면에서 −15~−27%).

## 2026-10-02 (후속4) 매매 실행 R&D + 2주 R&D 스프린트 + 아침 9시 자동 재추천 (구현·테스트, 배포 전)

- 사용자 요청: "얼마에 사고팔아야 하나" 연구 → exec-rnd-v1(core/execution_lab.py, 사전 등록 26칸). 실데이터(매매 578건) 결과 26칸 전부 FAIL —
  지정가 매수는 66~71% 싸게 체결되지만 놓칠 때 더 비싸게 사서 평균 손해(역선택), 익절은 앞 구간만 좋고 최근 2년 손해. 결과 research/results/exec-rnd-v1/.
- 사용자 요청: "가설을 스스로 세워 2주 동안 매일 돌려 최적값" + "코어 매도 시점 정량화" → sprint-2w(core/sprint_lab.py, 사전 등록 sprint-judge/v1):
  F1 새틀라이트 ~1,040개, F2 코어 선정 180개, F3 코어 보유 중 매도 22개, F4 매매 가격 ~200개. 승자 = IS 최선 → DSR ≥ 0.95(분산=실제 시도 분산) → CSCV PBO ≤ 25% → 떼어 둔 2년 한 번.
  마감 2026-10-16 23:50 KST. 스모크(합성) 1분 40초로 끝까지 확인. 실데이터 계산은 VM 실행기에 맡김(로컬에서 돌리지 않음).
- 실행 창: core/research_jobs.py SPRINT_UNTIL=2026-10-16, SPRINT_WINDOWS 07:50~08:50·10:40~11:50·17:00~23:50(잡 없는 틈), CRON 시각 확장(job_schedule·run_scheduler 동일).
  새틀라이트 R&D 는 대기 연구가 있어도 20시간마다 한 번 차례(_satellite_lab_due). 야간 배치에서 국제정세·새틀라이트 트랙을 Writer 보다 먼저(plan 순서).
- 아침 자동 재추천: champion_recommendation_daily(09:01 KST — 09:00 은 대회 알림 슬롯이라 1분 뒤, 서버 UTC 날짜도 맞음). 버튼과 같은 재추천을 매일 계산·캐시 + 텔레그램 요약 1건, 주문 없음. VM 여유 없으면 최대 30분 대기, job_health 유예 2시간. 버전 변경 뒤 첫 실행은 백테스트 캐시 재생성으로 15~20분. VM 실제 실행·전송 미확인.
- 추가: info-rnd-v1(가설 카탈로그 1차, docs/HYPOTHESIS_CATALOG.md) 로컬 실데이터 — A 급락 필터 13개 전부 기각, B 코인은 BTC 18번째 자산이 떼어 둔 2년에서만 탈락(가장 유망), 코인 추세 5% 는 앞으로 기록으로 확인 필요. tech-rnd-v1(차트 규칙 3라운드)·sprint-2w 는 VM 실행기에 맡김. 샤프는 BIL 대비 초과수익으로(스모크에서 발견한 '매매 안 하는 규칙' 문제).
- 테스트: test_research_jobs(창 테스트를 스프린트 전후로 분리 + 새 테스트 2), test_agent_system(위성·국제정세 트랙 격리), test_sprint_lab(10).

## 2026-10-02 (후속3) 총수익 순위 되돌림 + 배포 관문 실패 수정

- 사용자가 "좋아진 게 아니지 않나" 지적 → 분해해 보니 나빠진 원인은 총수익 순위(C13). 사용자 결정으로 순위·절대모멘텀·SPY 200일선을 가격(Close)으로 되돌리고 남는 몫 BIL·수익 총수익 측정은 유지. 버전 "…/2026-10-bil", CORE_SIGNAL_FIELD="Close". run_core_backtest: 신호 Close, 수익 Adj Close. 2008~ CAGR 9.52%·MDD −19.8%·OOS 2년 샤프 1.37(= v2 C01).
- 첫 배포(275a255)는 VM 테스트 관문에서 test_page_ticker_chart_loads_only_on_click 1건 실패로 서비스 재시작이 막혔다(실서비스는 이전 버전 유지). 원인: VM 에만 있는 data/cache/champion_signal_state.json 때문에 상관관계 칸이 가격을 받음. page_env 에서 get_current_holdings 를 격리. 로컬에 같은 파일을 두고 재현·수정 확인.
- 그 사이 VM 연구 실행기가 core-rnd-v2 를 실행해 결과를 main 에 커밋(bc28f24).

## 2026-10-02 (후속2) 코어 엔진 총수익 순위 + 남는 몫 BIL 반영, main 배포 (사용자 결정)

- 사용자 결정: (1) main 배포 허락 (2) 코어 순위를 총수익 기준으로 (3) 남는 몫 → 단기국채 반영. 사전 등록 판정은 통과하지 않은 조합임을 알렸고 그대로 진행(C13 FAIL, C01 은 G1 만 FAIL).
- 구현: core/champion_strategy.py — CHAMPION_STRATEGY_VERSION "…/2026-10-tr-bil", CORE_PRICE_FIELD="Adj Close", CORE_CASH_ETF="BIL", _price_series. compute_core_recommendation(순위·SPY 200일선 총수익, 남는 몫 per_ticker_weights["BIL"], cash_etf_weight 필드), _build_core_weights(cash_ticker, 기본 None=기존 동작), run_core_backtest(총수익·BIL), _closes_from_histories(field). core/champion_performance.py 동일 기준. 화면 문구(현금→단기국채), target_allocation 의 BIL 구분 '코어 남는 몫(단기국채)'. paper 주문도 BIL 을 산다(plan_targets 가 per_ticker_weights 사용).
- 백테스트(2008~, 총수익): 이전 CAGR 9.36%·MDD −19.7%·OOS 2년 샤프 1.35 → 반영 후 9.12%·−21.7%·1.50. 오늘(10/2) 코어 선택은 같음(DBC·XLE·XLK·XLV).
- 새틀라이트는 여전히 Close(가격) 기준. 일별 라이브 원장(record_daily_ledger_entry)도 Close 기준 — 필요하면 후속.
- 테스트 수정: test_champion_strategy 2건(필터 축소분이 BIL 로 가는 것, inverse_vol 합계)을 새 동작에 맞춤.

## 2026-10-02 (후속) 코어 R&D v1·v2 + AI 국제정세 의견 shadow + 실데이터 실행 (구현·전체 테스트·로컬 실데이터 실행, 미배포)

- 사용자 지시: "제안한 것 다 허락, 진행" — 코어 개선안 1~10 전부. main push 는 Claude Code 안전장치(실서비스 배포)에 막혀 사용자 확인 대기.
- 코어 R&D: core/core_lab.py(현 코어를 라이브 엔진과 일별 비중까지 동일 재현 + 변형 옵션), research/jobs/core-rnd-v1·v2(사전 등록, core-judge/v1: DSR·OOS 2년·3구간·이웃·MDD). 스모크에서 '관측 분산' 방식이 극단값 하나로 모두의 기준을 올리는 것을 보고 실데이터 실행 전에 고정 가정 분산(연 0.5)으로 바꿈(run.py 에 기록).
- **발견: 코어 엔진(라이브·백테스트)이 Close(가격)만 써서 배당·분배금이 빠져 있다.** 2022~23 BIL 가격 −0.04% vs 총수익 +6.42%, HYG −11.1% vs −0.7%. v1(가격 기준) 결과는 보존, 측정 기준만 총수익으로 바꾼 v2 를 새로 등록(C13 '순위도 총수익' 추가, N=13). final_config 문구는 '총수익률 랭킹'인데 코드는 가격 — 엔진 수정 여부는 사용자 결정.
- 결과(로컬 실데이터, research/results/core-rnd-v1·v2/): v2 현 코어 총수익 CAGR 9.4%·샤프 0.79·MDD −19.7%(가격 기준 7.9%). **13개 변형 전부 FAIL.** C01 현금→BIL·C04 듀얼 모멘텀만 CAGR +0.1%p 로 G2~G5 통과, G1(DSR 0.12·0.07)만 탈락. C13 총수익 순위는 개선 없음.
- AI 국제정세 의견 shadow: core/geo_shadow.py(geo-judge/v1, 24개월 뒤 판정), agent_batch geo_plan + 역할 geo_analyst(월 1회, WebSearch), research/agent_prompts/geo_analyst.md, 챔피언 화면 '🌐 AI 국제정세 의견'(배분 미반영). 실제 Claude CLI 실행은 아직 없음(첫 실행 10/25 이후 배치).
- 새틀라이트 실데이터(로컬, data/satellite_lab/ — VM 서비스 등록부 아님): 현 규칙 무작위 대비 IS 93백분위(기존 리서치 93백분위와 일치), 풀 843종목 중 가격 636종목(상장폐지 결측). 판정 진행 중. 새틀라이트 랩도 Close 기준(배당 미포함) — 종목 간 배당 차이로 약한 편향, v2 후보.
- 검증: 전체 pytest 2377 passed·4 skipped, codex_telegram unittest OK, hub.guide.check 누락 없음.
- 다음: 사용자 승인 후 main 병합(VM 이 research/jobs 의 core-rnd-v1·v2 를 다시 돌려 공식 결과 커밋, 새틀라이트 랩·에이전트 트랙 시작). 엔진 총수익 전환·C01 반영은 사용자 확인 뒤 별도 작업.

## 2026-10-02 새틀라이트 R&D 센터 + 종목 차트 (구현·전체 테스트, 미커밋·미배포)

- 계기: 7/1 새틀라이트(CAT·GEV·JNJ) 3개월 약 −9%(같은 풀 평균 −5%, SPY +2%) → 사용자 "새틀라이트 종목 선정 R&D 센터를 만들어 계속 연구시켜라". 사용자 결정: 아이디어 = AI 에이전트 + 시작 목록, 범위 = 선정 규칙 + 보유기간·종목 수·청산.
- 설계·사전 고정 판정 규칙: [SATELLITE_LAB.md](./SATELLITE_LAB.md) (sat-judge/v1, G1~G5). 후보·현 규칙·무작위 200회가 같은 시뮬레이터·풀·비용. 현 규칙 재현은 테스트로 확인(_pick_satellite_at_date 와 날짜별 동일 선정).
- 구현: core/satellite_lab.py(엔진·심판·등록부 data/satellite_lab/), scripts/satellite_lab_worker.py(계산기, --smoke), research/satellite_lab/seeds/S-SEED-000~009, core/research_jobs.py(대기 연구 없는 창에서 계산기 실행·텔레그램 '[새틀라이트 R&D]'), core/agent_batch.py + core/agent_budget.py + deploy/codex_telegram/runner.py(sat_designer·sat_critic 역할), research/agent_prompts/_sat_contract.md·sat_designer.md·sat_critic.md, hub/satellite_lab_page.py + hub/server.py + hub/apps_registry.py(/satellite-lab 카드), 설명서 content_modules_a/b·content_ops, docs/RESEARCH_JOBS.md, .gitignore, tests/test_satellite_lab.py(18), tests/test_hub.py(제목 이스케이프).
- 종목 차트(하위 에이전트): '지금 할 일' 카드에 티커 버튼(st.pills) → 1년 캔들 + 현재가·20일 돌파선·트레일링스탑(코어는 12개월 전 가격) + '매수 금액 ÷ 현재가 = 약 N주'. 목표 매수가는 만들지 않음(백테스트는 리밸런싱일 종가 매수). core/champion_recommendation.py 헬퍼 4개, app/pages/11_챔피언_전략.py, 테스트 8건.
- 검증: 전체 pytest 2359 passed·4 skipped, codex_telegram unittest 72 OK, hub.guide.check 누락 없음, 계산기 스모크(합성 데이터) 10개 동결·9개 판정·종료 0(45초). **실데이터 전체 계산·실제 Claude CLI 로 새틀라이트 트랙 실행·실브라우저 확인은 안 함.**
- 다음: main 병합(사용자 승인) → 첫 VM 연구 창에서 champion40 풀 캐시·가격 로딩 시간 확인(sp500_pit 는 첫 실행 때 가격 내려받기가 길 수 있음, 종료 코드 3 으로 이어감) → 기준선 '현 규칙 무작위 대비 백분위' 확인. PASS 가 나와도 챔피언 반영은 사용자 확인 뒤 별도 작업.

## 2026-10-02 챔피언 화면 '✅ 지금 할 일' 카드 (구현·전체 테스트, 미커밋·미배포)

- 계기: 사용자 "챔피언 전략 화면에서 당장 무엇을 해야 하는지 직관적으로 알 수 없다".
- 원인: 새틀라이트 목록이 세 개(홈·어제 밤 저장=빠른 근사 스캔 5종목, 재추천=오늘자 PIT 3종목, 참고=직전 반기일 PIT)였고, '지금 해야 할 행동'이 다른 방법론인 어제 밤 목록과 비교해 매번 '새틀라이트 N개 교체 필요'를 띄웠다. 사용자 보유와는 비교하지 않았다.
- 결정: 화면 맨 위 한 카드로 1단계 추천 최신 여부(지난달 결과·오늘 코어와 불일치 → 다시 계산) → 2단계 목표 비중표 → 3단계 내 보유('포트폴리오' 입력) 대비 매도→매수 목록(미등록이면 투자금 입력 후 '처음 매수') → 4단계 다음 확인일(코어 다음 달 첫 거래일, 새틀라이트 매수일+6개월). 근거·분포·확신도는 카드 아래 탭으로 내림. '오늘의 종합 판단'·'5. 내 포트폴리오와 비교' 절은 카드로 흡수해 삭제, 6→5 재번호. `action_summary`는 새틀라이트 비교를 하지 않음(코어만). 홈 '현재 전략 상태' 새틀라이트는 마지막 재추천의 오늘자 목록 우선, 없으면 빠른 근사 스캔을 '참고용'으로 표시.
- 수정: core/champion_recommendation.py(target_allocation·order_plan·freshness·next_checkpoints, action_summary), app/pages/11_챔피언_전략.py, app/views/today.py, hub/guide/content_pages_a.py·content_modules_a.py(verified 2026-10-02), tests/test_champion_recommendation.py.
- 검증: 전체 pytest 2333 passed·4 skipped, `python -m hub.guide.check` 누락 없음, 실제 VM 재추천 캐시(2026-09-29)로 헤드리스 렌더 확인(1단계 '다시 계산' 경고, $10,000 기준 코어 4×$2,125·새틀라이트 3×$500). 실브라우저 미확인.
- 남은 것(제안): 야간 `check_and_notify_signal_changes`의 새틀라이트가 여전히 빠른 근사 스캔이라 텔레그램·상관관계·실적 알림 대상도 그 목록이다 — PIT 로 바꿀지는 사용자 결정. 커밋·main 병합(=자동 배포)은 사용자 승인 후.

## 2026-09-27 VM 검증 연구 작업 실행기 (구현·전체 테스트, 미병합·미배포)

- 결정: 실행 창은 01:00~02:50(야간 잡 뒤·03:00 에이전트 배치 전)과 13:00~16:50 KST(등록 잡이 없는 낮). 04:10~06:30 은 에이전트 배치(~05:50)·06:10 paper·06:30 백업과 겹쳐 제외. 창 목록은 `core/research_jobs.RUN_WINDOWS`/`CRON` 과 `core/job_schedule.py` 가 같아야 한다.
- 구현 파일: core/research_jobs.py, scheduler/run_scheduler.py(잡), core/process_registry.py, core/job_schedule.py, core/job_health.py(유예 4시간), hub/apps_registry.py(report 슬롯), hub/engine_status.py·hub/guide/live.py(여러 값 cron 표시), scripts/research_jobs_admin.py, research/jobs/smoke-noop/, docs/RESEARCH_JOBS.md, AGENTS.md, 설명서 content_*, tests/test_research_jobs.py, tests/test_hub.py, .gitignore.
- 검증: pytest 2080 passed, runner unittest OK. VM 실행·push 권한·ionice 존재는 미확인.
- 다음: main 병합 → 첫 실행 창에서 smoke-noop 완료 텔레그램과 research/results/smoke-noop/ 커밋이 오는지 확인.

## 2026-09-26 (후속) 심판 OOS 분리 + 멈춘 가격 피드 탐지 (구현·전체 테스트, 미커밋·미배포)

- 계기: 사용자가 내려받은 FidetoLabs 릴스 9개(`video/`, 음성은 음악뿐 → 프레임 확대로 분석, 대부분 정적 UI 데모)에서 나온 제안 중 추천 1·2를 지시.
- 1) `core/hypothesis_judge.py`: 마지막 `HOLDOUT_YEARS`(2)년 OOS 분리. 파라미터 선택·DSR 은 IS(≥3년)만, 고른 조합 OOS 연샤프 ≤ 0 이면 탈락. 짧으면 분리 없이 경고. 결과 JSON 에 `holdout{split,is_stats,oos_stats}`. **새 탈락 조건** — 이후 심판부터. 에이전트 계약(`_contract.md`)에 반영.
- 2) `core/data_integrity.py`: `price_frozen`(warning) — 종가·거래량이 같은 봉 3거래일 연속, 거래량 없으면 종가 6거래일 연속. 실데이터(코어 17종+SPY·BIL·SHV·SGOV·대형주, 2025-09~2026-09)로 오탐 점검: 종가+거래량 최장 1, 종가만 최장 4(HYG) → 종가만 임계값을 5→6 으로 올림.
- `video/` 는 타인 영상이라 `.gitignore` 에 추가.
- 검증: 전체 `pytest tests` 2032 passed, `python -m hub.guide.check` 누락 없음. 다음 단계 후보(제안만): 허브 /research 가설별 단계 진행 화면, no-trade band shadow 실험.

## 2026-09-26 가설 심판 강건성·실패 방향 목록·Ken French 시험대 (구현·전체 테스트, 미커밋·미배포)

- 계기: 사용자가 FidetoLabs(인스타 @fidetolabs, 논문 재현 노트·qanat 백테스트 엔진)를 분석해 달라고 요청 → 제안 1·3·2 순서로 진행 지시. 인스타는 로그인 벽이라 웹사이트·GitHub·노트 원문으로 분석했다.
- 1) 심판 강건성(`core/hypothesis_judge.py`, `hypothesis_engine.backtest` 에 total_turnover 추가): 손익분기 편도 bp ≥ 가정 비용×2, 상위 3개월 제외 샤프 ≥ 50%, 파라미터 ×0.5·×1.5 이웃 샤프 >0·중앙 ≥ 50%. **새 탈락 조건이다** — 이후 심판부터 적용, 과거 판정은 그대로. 이웃 백테스트만큼 심판 시간이 늘어난다(최대 6회).
- 3) `research/agent_prompts/dead_ends.md`(단기 반전·월말 효과·Sell in May·모멘텀 크래시 필터·BAB·accruals) → Scout·Writer 시스템 프롬프트에만 붙인다(`agent_batch.system_prompt`). 근거는 FidetoLabs 노트이며 우리 엔진 재현은 아님(단기 반전 공개 전 수치는 아래 2)로 독립 재현됨).
- 2) `core/french_factors.py` + `scripts/french_factor_report.py` → `research/factor_decay.md`. 심판에 FF5+모멘텀 회귀를 **보고 전용**으로 붙였다(`judge_frozen` 기본 on, `judge()` 는 factors_fn 줄 때만). 테스트는 conftest 에서 오프라인·임시 캐시로 막았다.
- 검증: 실제 데이터로 단기 반전 1926-02~1990-12 월 +0.884%·t 6.35·샤프 0.90(779개월)이 FidetoLabs 수치와 일치. SPY 회귀 β 0.99·R² 0.991(알파 −1.6%/년은 배당 미포함 Close 때문). 전체 `pytest tests` 2027 passed, `python -m hub.guide.check` 누락 없음.
- 미실행: 실제 에이전트 배치에서 새 프롬프트·심판 동작 확인, 커밋·push. 다음 단계 후보(제안만): qanat식 decay 블렌딩 shadow 실험, 읽기 전용 MCP 서버.

## 2026-09-27 관제 센터 '지금 돌고 있는 작업'(/live) (구현·단위 테스트, 배포)

- 사용자 요청: VM 에서 백그라운드로 무엇이 돌고 있고 그 내용이 무엇인지 보는 UI.
- 구현: `hub/live_status.py` + `/live` 라우트 + '운영' 카테고리 카드. 절: 실행 중 스케줄러 잡(경과 시간·설명), 텔레그램 작업 큐(running/queued/retry/blocked, 지시 요약), 서비스(상태·메모리·CPU 누적·재시작), 프로세스(quant·ubuntu 계정, 무엇인지 설명, 비밀값 가림, code-server 하위 묶음), 12시간 안에 돌 잡. 15초 새로고침, 읽기 전용.
- `core/job_health.py`: APScheduler SUBMITTED 이벤트로 `data/running_jobs.json`(gitignore)에 시작 표시, 종료 시 제거, 스케줄러 재시작 시 초기화, 죽은 PID 기록은 무시. 설명서 항목 갱신.
- 검증: `tests/test_live_status.py`(14건). VM 실화면 미확인 — Streamlit 내부 백그라운드 작업(job_manager)은 프로세스 메모리 안이라 이 화면에 안 나온다.

## 2026-09-26 관제 센터 'AI 대회' 섹션 (구현·단위 테스트, VM 1회 설정 필요)

- 사용자 결정: 브라우저 code-server 로 열기, 저장소 private 고정, 기본 정보·마감 알림, 기본 뼈대. 관리 항목 "Other" 는 내용이 비어 있어 확인 대기.
- 구현: `core/contests.py`, `hub/contests_page.py`(+`hub/server.py` 라우트, `apps_registry` 카드·'AI 대회' 카테고리), 잡 `contest_deadline_alert` 09:00 KST, `deploy/setup_contests.sh`, 설명서 항목, `tests/test_contests.py`(15건, git 실제·gh 가짜). 설계: [AI_CONTESTS.md](./AI_CONTESTS.md).
- 버그 수정(구현 중): 마감 D-1 대회에 D-7 알림을 고르던 단계 선택 오류.
- **VM 미실행:** `/srv/contests` 가 없으면 화면에 설정 안내가 뜬다. 사용자가 code-server 터미널에서 `sudo bash /opt/quant/deploy/setup_contests.sh` 1회 실행 필요. 실제 gh 저장소 생성·code-server 폴더 열기는 미검증.

## 2026-09-25 후보 원장 사전 기록(forward_recorded) PIT 인증 (구현·단위 테스트, 브랜치 `eng-pit-forward-cert`, main 미병합·미배포)

- 문제: 가격·재무 기반 후보는 decision_cutoff 만 채워 5필드 PIT 인증이 불가능 → `decide_verdict` 가 영원히 '미입증'.
- 결정: `core/candidate_ledger.compute_pit_basis()` 로 행마다 `pit_basis ∈ {full_contract, forward_recorded, none}` 계산(DB 컬럼 추가 없음, `load_outcome_frame` 이 붙임). forward_recorded = `CandidateBatch.created_at <= next_executable_fill`(확정된 진입 시가, UTC) 이고 `decision_cutoff <= next_executable_fill`. full_contract 우선. 소급 기록(created_at > 진입)은 none.
- PIT 게이트만 full_contract|forward_recorded 인정으로 바꿨고 표본·군집·블록·결측·진단 horizon·주 대상/비용 게이트는 그대로. 결과에 `pit_basis_counts`·`pit_basis_limitation`(원천 데이터 발표 시각·소급 수정은 보증 안 함) 포함. `pit_certified_fraction` 은 이제 인정 근거 비율.
- 수정: `core/candidate_ledger.py`, `tests/test_candidate_ledger.py`(+15), `docs/CANDIDATE_LEDGER_SPEC.md`, `hub/guide/content_modules_a.py`, `hub/guide/content_ops.py`. models.py·db.py 미수정.
- 다음: main 병합 여부는 사용자/상위 세션 결정. VM 실데이터에서 기존 행의 pit_basis 분포 확인은 아직 안 함.

## 2026-09-25 위성 후보 풀 전체 기록 (브랜치 eng-satellite-pool, 구현·단위 테스트, 배포 전)

- 결정: 위성 원전략 결정은 그대로 두고 후보 풀을 **관측 전용 추가 필드**로만 노출(`candidates`/`rejected_tickers`/`missing_tickers`, `core/champion_strategy.py`). 후보 원장(`core/candidate_recorder.py`)은 풀 전체를 selected/held/rejected/missing_data 로, 두 shadow(`core/guidance_shadow.py`·`core/filing_veto_shadow.py`)는 돌파 활성 후보 집합 C(채택+상위 3위 밖)를 기록. 모집단이 바뀌어 shadow strategy_version 을 v2 로 올림(v1 행 보존).
- 외부 조회 상한: 가이던스 기존 상한(20종목·300회·300초) 유지 + 조회 순서 채택 > 모멘텀 순위. 공시 veto 에 새 상한 20종목·150회·300초, 넘친 후보는 missing_data(fetch_status=skipped_*).
- 원전략 불변 검증: 변경 전(031e9cc) `_pick_satellite_at_date` 본문을 테스트에 그대로 두고 무작위 입력으로 비트 단위 대조(`tests/test_satellite_candidate_pool.py`), 주문 계획 동일성 테스트. 전체 pytest 2016 passed(2026-09-26).
- 표본 추정(저장된 실행 기록 기반, 가정): 돌파 활성 후보 반기당 16~39(평균 34), 채택 3. 상한 20이면 약 6.7배. 공시 veto 보류 100건까지 풀로도 약 13~42년, 가이던스 veto 165건은 약 40년 이상 → 여전히 forward shadow 만으로는 결론 불가. 자세한 표는 FILING_CHANGE_VETO_SPEC §9.
- 다음 단계(제안): 상한 20이 대부분 반기에서 걸리므로 상한 상향 여부는 사람 결정. 과거 재구성으로 표본을 늘릴지 검토. VM 실행 검증 전.

## 2026-09-26 후보 원장 국면별 판정 + 실측 비용 진단 칸 (구현·단위 테스트, 브랜치 eng-regime-eval, 미배포)

- 결정: 원장 판정이 전체 기간을 섞던 문제(사용자 원칙 "같은 국면 안에서만 검증")와 실측 비용 미반영을 진단 레이어로 해결. 원장(`core/candidate_ledger.py`)·스케줄러는 수정하지 않음.
- 신규 `core/regime_eval.py`: 결정 이전 최신 스냅샷만 사용(5거래일 초과 → unknown), 스냅샷 없으면 결정 시점 확정 봉으로 `classify_daily_regime` 재계산(캐시 전용), unknown 별도 칸, 다중비교 라벨, `measured` 비용 칸(진단용, 주 검정 10bp 불변).
- `core/strategy_variants.py`: 주간 보고서에 '국면별 판정'·'실측 비용 반영 결과' 절 추가(실패해도 기존 절은 생성). 설명서 `hub/guide/content_modules_b.py` 갱신, `docs/CANDIDATE_LEDGER_SPEC.md`에 절 추가.
- 검증: `tests/test_regime_eval.py` 16건, 전체 pytest 2007 passed(이 세션 직접 실행), `python -m hub.guide.check` 빠진 설명 없음. VM 실행·실데이터 보고서 미확인.
- 한계·다음: 거래일 계산은 평일 기준(휴장일 미반영), 스냅샷 이력은 2026-07 이후만 존재, CI 폴백 JSON 스냅샷은 라벨에 쓰지 않음. `pit_certified_fraction` 의미가 원장 버전마다 다를 수 있어 regime_eval은 그 값을 해석·표시하지 않고 verdict_reasons만 옮긴다.

## 2026-09-26 후보 원장 청산 규칙 변형 비교 (구현·단위 테스트, 미배선)

- 결정: 원장 후보에 청산 규칙 4개를 사전 고정해 비교([EXIT_VARIANTS_SPEC.md](./EXIT_VARIANTS_SPEC.md), 코드보다 먼저 커밋). `baseline_20d`(원장과 동일)·`fixed_stop_8`·`trailing_10`·`satellite_trailing_15`(champion 위성 `SATELLITE_DONCHIAN_STOP_PCT` 그대로), 모두 20거래일 상한. 손절은 일봉 종가 판단 → 다음 거래일 시가 체결, 갭은 그 시가.
- 구현: `core/exit_variants.py`(새 테이블 없음, 원장·가격 캐시 읽기 전용), `write_exit_variants_report()` → `data/reports/exit_variants_날짜.{md,json}`. 판정은 `candidate_ledger.evaluate_selection` 재사용, 기준선 외 3개는 Bonferroni α=0.05/3 + '탐색 결과' 라벨. 결측·대기는 기준선과 같은 상태·사유.
- 검증: `tests/test_exit_variants.py` 18건(기준선=원장 정확 일치 포함), `hub.guide.check` 누락 없음. 실제 원장 데이터로는 실행하지 않음.
- 미배선: 스케줄러 연결 안 함(주간 잡에서 `update_forward_outcomes` 뒤 try/except 로 호출 제안). 브랜치 `eng-exit-variants`, main 병합은 조정자가 한다.

## 2026-09-25 RES-04 가이던스 비교 정책 annual_same_fy_v1 (구현·단위 테스트, 브랜치 eng-guidance-annual, 배포 전)

- **결정:** 방향(raised/lowered/maintained)은 연간 가이던스의 같은 회계연도 재발표끼리만 낸다. 분기·반기는 항상 unknown(`quarterly_not_comparable` 등). 분기끼리 억지 비교와 '실적/컨센서스 대비 가이던스'는 기각(스펙 3절). 같은 발표에 +1년 연간 항목이 있으면 그 해의 이전 연도 항목은 끝난 해의 실적으로 보고 비교하지 않는다(`annual_period_superseded_in_release`).
- **근거:** 캐시+무작위 S&P 5개 = 19개 기업, 57개 발표 재계산에서 옛 규칙의 분기 방향 판정 13건이 전부 실적·배당 문장 오염이었다. 연간 방향 56건, 방향 있는 발표 13/57, V=1 형태 0/57. revenue·eps unknown 80%.
- **구현:** `core/earnings_events.py`(`period_type`, `COMPARISON_POLICY`, GuidanceChange 추가 필드 `reason_detail`·`comparison_method`·`period_type`·`policy`, `previous_*` 속성, `evidence()`; 기존 `change`·`reason` 코드 유지), `core/guidance_event_provider.py`(캐시 형식 2, 새 필드 직렬화, params 에 정책). history_days 400·max_filings 6 은 유지(티커당 최대 13요청 × 20 = 260 ≤ 300).
- **스펙:** `docs/EARNINGS_GUIDANCE_EXPERIMENT_SPEC.md` 3절 비교 정책, 6절 공급 조사·최소 사건 수 평가 — **veto 165건 도달은 현재 추출기·정책으로 비현실적**(상한 추정 연 10~20 episode), 실험은 `미입증` 유지가 정상.
- **다음:** 사람 정답 대조(G0), 표 형식·YEND/FY 표기 추출 개선은 별도 작업. guidance_shadow 요약에서 `reason_detail` 을 쓰도록 바꾸는 것은 그 파일 담당 에이전트 몫.

## 2026-09-25 허브 모델 저장 forbidden 수정 (배포)

- 증상: VM 허브 `/research` 에서 모델 바꾸고 저장 → `forbidden`. 원인: 허브 응답의 `Referrer-Policy: no-referrer` 때문에 브라우저가 폼 POST 의 `Origin` 을 `null` 로 보내 Host 비교가 실패. 수정: Origin 이 실제 주소일 때만 Host 와 비교하고, 그 외에는 `Sec-Fetch-Site`(cross-site·same-site 거부)로 판단(`hub/server.py::_same_origin_post`). 테스트 추가.
- 사용자 확인(2026-09-25): 허브 카드·/research·텔레그램 /models·/processes 모두 보임. paper 자동 주문 켜기는 요청받았으나 이 세션은 VM 에 접근할 수 없어 사용자가 텔레그램에서 켜야 함.

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
- **배포 후 발견·수정(3042eaf):** VM 에서만 자동배포 테스트 관문이 실패해 서비스가 이전 버전으로 남았다. VM `.env` 의 Alpaca 키를 모듈 import 시 `load_dotenv()` 가 읽어, 테스트 결과가 키 유무에 따라 달라졌기 때문이다. `tests/conftest.py` 가 모든 테스트에서 Alpaca·텔레그램 키를 빈 값으로 가리도록 고쳤다(테스트가 실제 계좌·텔레그램에 닿을 가능성도 제거). 가짜 키를 넣은 환경에서 전체 테스트를 돌려 VM 을 재현·확인했고, 사용자가 텔레그램 `/processes` 로 새 버전 배포를 확인했다.

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

## 2026-09-25 관제 허브: 엔진 카드 제어 + 사용 설명서 UX (인프라)

사용자 요청 두 건을 병렬로 처리했다. 엔진 카드 쪽은 이 세션이, 설명서 UX는 별도 에이전트가 격리된 워크트리에서 맡았고
겹치는 파일이 없도록 경계를 정한 뒤 합쳤다(설명서 에이전트는 `content_*.py`를 건드리지 않았다 — 내용이 아니라 표시만 바꿈).

**결정과 근거**
- 엔진 카드(`/status/<id>`)가 systemd 한 줄과 "별도 웹 UI 없이 동작합니다"로 끝나서, 자동 잡 29개의 상태 확인·on/off가
  텔레그램 `/processes`로만 가능했다. 사용자는 폰 브라우저로도 관제 센터를 보므로 화면에서도 같은 일을 할 수 있어야 한다.
- **주문을 내는 잡(`places_orders`)은 웹 클릭 한 번으로 켜지지 않는다.** 텔레그램의 확인 규칙을 그대로 옮겨, 확인 화면을
  거쳐 `confirm=1`이 붙은 POST에만 적용한다. 끄기는 확인 없이 즉시(안전한 방향이라).
- 꺼둔 잡은 `job_health` 판정이 '기록 없음'이 되는데, 화면에는 '꺼짐'으로 표시한다 — 고장으로 오해하지 않게.
- 설명서는 내용을 지우지 않고 탭·검색·접기로 재배치만 했다. 카드 수는 전후 모두 123개이고, 테스트가 사람 작성 문구가
  렌더링 결과에 남아 있는지 검사한다.

**상태 (구현/검증/배포 구분)**
- 구현·테스트·배포 완료: 엔진 카드 잡 목록과 on/off(커밋 `031e9cc`, VM 배포 및 재시작 후 상태 확인까지 정상).
- 구현·테스트 완료, **배포 대기**: 설명서 UX(이 커밋). 자동배포가 5분 내 가져간다.
- **실제 폰 브라우저 육안 확인은 아직 못 했다** — 고정 바 높이와 탭 가로 스크롤은 배포 후 사람이 봐야 한다.

**수정 파일**: `hub/engine_status.py`(신규), `hub/server.py`(엔진 본문·POST 라우팅·확인 페이지), `hub/guide/content_ops.py`(화면에서도 켜고 끌 수 있다는 설명),
`hub/guide/render.py`·`hub/guide/ui.py`(신규)·`tests/test_hub_guide.py`(설명서 UX), `tests/test_hub_engine_status.py`(신규).

**검증**: `python3 -m hub.guide.check` 통과, 전체 `pytest tests`(다른 세션의 미완성 `tests/test_candidate_ledger.py` 제외) **1,943건 통과**.
엔진 페이지는 서버를 실제로 띄워 라우팅·CSRF·확인 단계까지 검증했다(`tests/test_hub_engine_status.py`의 live_hub 테스트).

**다음 단계**: 배포 후 폰에서 `/guide`와 `/status/scheduler`를 눈으로 확인. 검색은 단순 부분문자열 일치라 초성·오타는 안 잡힌다.


## 2026-10-01 — VM에서 직접 코딩하도록 저장소 이전 (구현·검증 완료, 푸시 인증은 사용자 대기)

- 결정: Codespace 대신 VM(code-server, 사용자 `ubuntu`)에서 코딩한다. 개발용 사본은 `~/repos/<이름>`. **운영 트리 `/opt/quant`(사용자 `quant`)는 직접 고치지 않는다** — `~/repos/Quant`에서 고쳐 main에 push하면 자동배포가 `/opt/quant`로 가져간다.
- 한 일: GitHub 저장소 8개(Quant, new_ugrp, phone_english, UGRP_2026, Adobe, Half_Film, dotfiles, intership-2025, 전부 공개) 클론. `ubuntu` git 이름/이메일을 Codespace와 같게 설정. `~/repos/Quant/.venv` 생성.
- Codespace에만 있던 것은 `~/repos/_from_codespace/`(권한 700): UGRP_2026 미푸시 커밋(번들 → `~/repos/UGRP_2026`에 병합, origin보다 2개 앞섬, 아직 push 안 함), Quant 작업트리의 커밋 안 된 수정 4건(패치 파일, 헤더에 원 브랜치·기준 커밋), `new/` 사진, `COPY_ME.md`, awesome-design-md 클론. 그 밖의 로컬 브랜치는 전부 GitHub에 이미 있음(동기화용 병합 커밋 1개 제외).
- 검증: VM `~/repos/Quant`에서 `pytest tests` → 2327 통과, 4 건너뜀.
- 사용자 대기: VM `ubuntu`에 GitHub 로그인 없음(push 불가). code-server 터미널에서 `gh auth login` → `gh auth setup-git` 필요.
- 미완: `core/db.py` 잠금 원인 수정(`_add_missing_columns` 읽기 먼저·`init_db` 프로세스당 1회)은 여전히 적용 전.

## 2026-10-01 (후속) core/db.py 잠금 원인 수정 (구현·전체 테스트, 배포 전)

- 바로 위 절에서 미완으로 남긴 두 가지를 적용했다. `/opt/projects/sternjeong/Quant`(자동화 `quant` 계정 작업공간)에서 작업 — `ubuntu`의 `~/repos/Quant`는 이 세션에서 접근할 수 없다.
- `init_db()`: 전역 `_initialized_engine`(engine 객체 동일성 비교)로 같은 engine에 대해서는 실제 초기화를 1회만 수행하고 이후 호출은 즉시 반환한다. engine이 교체되면(테스트의 monkeypatch 패턴) 다시 수행되므로 기존 테스트의 "engine 바꿔치기 후 init_db() 재호출" 관례는 그대로 유지된다.
- `_add_missing_columns()`: `inspect(engine)`로 먼저 전부 읽기 전용 확인 후 추가할 컬럼 목록을 모으고, 하나도 없으면 `engine.begin()` 쓰기 트랜잭션을 열지 않는다(기존엔 매번 열었음 — 호출마다, 심지어 아무것도 추가할 게 없을 때도 쓰기 잠금을 시도해 야간 블록 동시 호출에서 불필요한 대기를 유발했다).
- 검증: `tests/test_db.py`에 3건 추가(같은 engine 재호출 시 1회만 동작, engine 교체 시 재동작, 추가할 컬럼 없으면 `engine.begin()` 미호출). 전체 `pytest tests` **2330 passed, 4 skipped**(이 세션이 직접 실행, 기존 2327 대비 테스트 3건 증가). `python -m hub.guide.check` 통과.
- 다음: 커밋·push → VM 자동배포 5분 내 반영. `ubuntu`의 `gh auth login`(push 권한)은 여전히 사용자 대기 — 이 세션은 그 계정에 접근할 수 없어 대신 처리할 수 없다.
