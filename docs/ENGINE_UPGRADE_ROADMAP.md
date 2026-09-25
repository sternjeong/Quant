# 기존 엔진 고도화 로드맵

상태: Astra 분석 완료. 2026-09-21 ENG-01·02·03·04·05·07·10 코드 구현·단위 테스트 완료(2차 통합 후 전체 pytest 1120건 통과). paper 검증·배포·운영 적용은 미완료. 단계별 상태는 SESSION_HANDOFF.md 표 참고.

## 목적과 원칙

기존 엔진을 새 전략으로 무작정 늘리기보다, 신호 생성부터 데이터 기준시각, 체결, 비용, 성과 판정까지 하나의 재현 가능한 경로로 연결한다. 모든 개선은 기존 기준선과 동일한 기간·유니버스·비용 조건으로 비교하고, train/test 또는 워크포워드 경계를 보존한다. 승률만 올리는 최적화는 채택하지 않으며 기대손익·최대낙폭·회전율·벤치마크 초과성과를 함께 본다.

## 현재 엔진별 고도화 후보

| 엔진 | 현재 역할 | 고도화 후보 | 상태 |
|---|---|---|---|
| `core/backtest_engine.py` | 전략 신호와 수익곡선 계산 | 다음 거래일 시가 체결, 갭·수수료·슬리피지·세금 모델 분리, 기업행동 반영, 거래 원장과 신호 시각 저장 | 제안 |
| `core/strategy_engine.py` | 전략 실행·조건 평가 | 신호/주문/체결 상태 분리, 중복 신호·재진입·보유 밴드 정책 명시, 결정 이유 기록 | 제안 |
| `core/indicators.py` | 공통 기술지표 | 결측·워밍업 계약, 계산 시점 검증, 지표 메타데이터와 단위 명시, 중복 계산 캐시 | 제안 |
| `core/stock_discovery.py` | 종목 발굴·팩터 점수 | PIT 재무·가격·유니버스, 업종 내 percentile rank, 팩터별 기여도와 결측 플래그 | 제안 |
| `core/strategy_tuning.py` | 스타일별 튜닝·워크포워드 | 탐색 이력과 다중검정 기록, 그룹 풀링 안정성, 고정 holdout, 파라미터 민감도와 실패 사유 보고 | 제안 |
| `core/market_regime.py` / `sector_strength.py` | 시장 국면·섹터 강도 | 발표시각 기준 매크로 vintage, 국면 전환 히스테리시스, 신호 지연과 전환 비용 검증. `n_data_ok=0`을 약세로 오인하지 않도록 unknown 분리 | 제안 |
| `core/portfolio.py` | 포트폴리오 관리 | 목표 비중·실제 비중·주문 상태 분리, turnover/노출/상관 제약, 리밸런싱 밴드 | 제안 |
| `core/champion_strategy.py` | 챔피언 전략·실적 일정 | 기존 `get_upcoming_earnings`와 reminder를 재사용해 장전/장후 구분, 일정 수정 이력, PIT 컨센서스와 주문 판단을 연결 | 제안 |
| `core/data_integrity.py` | stale/anomaly 점검 | 기존 점검 시스템을 추천·주문 게이트와 연결하고, 차단 사유·수동 해제 이력을 저장 | 제안 |
| `scheduler/`·paper execution | 자동 실행·모의 체결 | idempotency, 재시도·장애 원장, 데이터 스냅샷 해시, 예상 체결과 실제 체결 비교 | 제안 |

## 우선순위 게이트

1. **정합성 기반:** 진정한 point-in-time 데이터, 상장폐지·기업행동, 다음 시가 체결과 비용을 먼저 고정한다.
2. **엔진 관측성:** 각 신호가 사용한 데이터 시각, 구성요소 점수, 주문·체결 결과, 탈락 사유를 저장한다.
3. **전략 개선:** 보유 순위 완충(hold band), 실적 발표·컨센서스 변화, 표준화된 퀄리티 점수를 각각 독립 실험한다.
4. **운영 안정성:** paper 결과와 백테스트를 같은 거래 원장 형식으로 비교하고, 재시도해도 중복 주문·중복 기록이 생기지 않게 한다.

## 평가 계약

각 엔진 변경은 다음을 남긴다.

- 변경 전 기준선과 변경 후 결과
- 데이터 기준 시각과 유니버스 구성
- 거래비용·슬리피지·체결 규칙
- CAGR, 샤프, 최대낙폭, 승률, 평균 이익/손실, turnover, 벤치마크 초과성과
- 표본 수, 기간별 결과, 실패·탈락 케이스
- 연구 중 제안인지, 승인된 구현인지, 운영 적용인지

## 외부 근거와 검토 대상

PIT 공시 데이터는 [SEC EDGAR API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces), 매크로 vintage는 [ALFRED](https://alfred.stlouisfed.org/)를 우선 검토한다. 거래비용을 줄이는 보유 밴드는 [Novy-Marx·Velikov 연구](https://www.nber.org/papers/w20721), 퀄리티는 [AQR QMJ](https://www.aqr.com/Insights/Research/Working-Paper/Quality-Minus-Junk), 운영 대조는 [QuantConnect reconciliation 문서](https://www.quantconnect.com/docs/v2/writing-algorithms/live-trading/reconciliation)를 참고한다. 연구 선택 편향은 [Deflated Sharpe Ratio](https://doi.org/10.2139/ssrn.2460551) 관점에서 기록한다.

## 분석 범위

Astra 분석을 아래 우선순위와 백로그에 반영했다. 아래 내용은 구현 완료나 성과 주장이 아니라, 사용자 요청 범위에 대한 구현 제안이다.

## Astra 분석 반영: 우선순위별 제안

### P0 — 공통 원장·실거래 안전성·검증 정직성

- **백테스트 원장:** 기존 `close.pct_change()*shift` 경로를 다음 거래일 시가 주문으로 분리하고 수량·현금·수수료·슬리피지를 공통 원장으로 만든다. 갭, 배당, 분할은 손계산 결과와 NAV를 대조하며 5/10/25bp 비용 검증을 남긴다.
- **챔피언 전략:** 기존 역변동성 배분, 라이브 전용 Kelly, 상관·성과감쇠 감시, 실적 일정, 칼라 관련 기능을 재사용한다. SPY가 없을 때 full exposure로 조용히 대체하지 않고 `unknown`과 신규 주문 보류로 분리한다. 실제 마지막 거래일, 데이터 coverage, 전략 버전, 배분 이유를 snapshot하고 live/PIT 동일 선정 검증을 한다. 이후 top 4 매수·6위 유지 hold-band를 독립 실험한다.
- **튜닝 엔진:** 기존 group walk-forward/permutation을 보존하면서 전체 후보·재시도·탈락·test 열람을 장부화한다. 외부 기간·외부 종목, 이웃 파라미터 안정성을 검증하고 `compute_overfitting_curve`의 test 1위 변경(`is_overfit`)과 순위 불안정을 분리한다. 전체 탐색에는 DSR/PBO와 block bootstrap CI를 적용한다.
- **시장 국면:** breadth 데이터 0을 0%로 해석하는 오류를 막고 coverage와 `unknown`을 저장한다. 학습용·live용 `classify_daily_regime`은 유지하되 dashboard의 4개 신호와 의미를 분리한다. 국면 완충은 급락 지연을 포함해 비교한다.
- **실행 브리핑:** 기존 fingerprint/한도는 유지하되 POST 리스트 실행을 client order ID 멱등성으로 보강한다. 미체결 확인, 부분 체결, 거절, 재시작 대조, 매수 가능액 순서를 명시하고 응답 유실 재현에서 중복 주문 0을 검증한다.

### P1 — 데이터·신호·포트폴리오 품질

- **국면·섹터:** ALFRED vintage를 사용하고 정적 섹터표에 조건부 실측값·표본수를 표시한다. ETF 합성은 구성·시작일·결측 재가중·리밸런싱 규칙을 저장하고 신규 ETF 인공 점프를 검사한다. 기존 상대강도 대비 증분 검증을 한다.
- **종목 발굴:** 지표별 업종 내 rank 후 합산하고 현재 유니버스 교집합 대신 완전 PIT 유니버스를 사용한다. silent fallback을 없애고 IC·단조성과 비용 후 결과를 보고한다.
- **뉴스:** 기존 `published_at`/`created_at`을 활용해 최초 수신시각, 정정, 중복 사건, 근거 문장, 예상 대비 변화를 저장한다. substring 첫 일치 대신 다중 이벤트를 추출하고 인간 라벨 정확도 → 과거 재생 → 이벤트 신호 독립 검증 순서로 진행한다.
- **포트폴리오:** 기존 상관·Kelly·역변동성 기능을 재사용하되 ETF 내역과 직접 보유 주식의 실제 기업 중복 노출을 계산한다. Kelly의 날짜 군집, OOS, 보수 추정을 검증하며 PIT 전에는 기본값으로 승격하지 않는다. 공동 손실 구간을 검증한다.
- **섹터 리더 결측:** `sector_leaders._percentile_score`의 결측 rank 방향과 성장률 부재 시 고PER 대체를 재현해 데이터 없음과 고성장을 분리한다.

### P2 — 밸류에이션 확장

현재 EPS/BVPS와 과거 가격 근사는 PIT 밴드, reverse DCF, 가정별 범위로 확장할 후보이다. 분석 정보의 표시 개선과 실제 예측 우위를 구분하고, 가정·기준일·데이터 해시를 저장한다.

### 공통 데이터 계약

가격·재무·뉴스·국면·주문 관측에는 가능한 한 `observation_date`, `published_at`, `first_seen_at`, `source`, `revision`, `data_hash`를 함께 보존한다. 모든 메타데이터가 항상 있어야 한다고 일괄 배제하지 않고, 각 신호의 이용 가능 시점 재현과 출처 추적이 충족됐는지 검증한다.

## 보류·기각된 기본값

기존 자체 검증에서 근거가 약하거나 기각된 변동성 타기팅, 위험조정 모멘텀, 개별주 전면 확장, 베타 헤지는 기본 전략으로 재도입하지 않는다. 새 데이터와 별도 가설로 독립 검증할 때만 후보가 된다.

## 추적용 백로그

| ID | 우선순위 | 후보 | 현재 상태 | 다음 읽을 파일 | 채택·기각 기준 |
|---|---|---|---|---|---|
| ENG-01 | P0 | PIT 데이터·체결·기업행동 공통 원장 | 구현·단위 테스트 완료(`core/trade_ledger.py`, 옵트인 연결·분할 조정 헬퍼), 배당 현금·전면 전환·배포 미완료 | `docs/SPEC.md`, `core/backtest_engine.py` | 데이터 기준시각과 비용을 재현하고 기준선보다 왜곡을 줄이는가 |
| ENG-02 | P0 | 데이터 무결성·국면 unknown·주문 게이트 | 국면 unknown 구현·테스트 완료, 부분 결측 정책(coverage 0.75·재정규화·partial) 구현·테스트 완료(2026-09-25), 주문 게이트 연결·배포 미완료 | `core/data_integrity.py`, `core/market_regime.py` | stale/anomaly와 데이터 없음이 추천·주문에서 안전하게 처리되는가 |
| ENG-03 | P0 | 챔피언 snapshot·SPY unknown·실적 판단 | SPY unknown·snapshot 구현·테스트 완료, 제출 함수 게이트 강제·mock 통합 완료, paper 검증 미완료 | `core/champion_strategy.py` | 일정·coverage·버전·배분 이유와 정보시점을 보존하는가 |
| ENG-04 | P0/P1 | 그룹 WF·탐색 장부·과적합 분리 | 장부·순위불안정·이웃안정성·DSR 근사 구현·테스트 완료, DB 저장 완료, 야간 CI·UI·배포 미완료 | `core/strategy_tuning.py` | 외부 기간·종목 및 이웃 파라미터에서 안정적인가 |
| ENG-05 | P0 | 실행 브리핑 멱등 주문·재시작 대조 | 실행 회차 ID·멱등·게이트 mock 통합 완료, 수동 회차 종료 도구(`scripts/paper_run_admin.py`)와 검증 도구(`scripts/verify_alpaca_paper_idempotency.py`, mock만) 완료, **실제 paper API 검증 0건**·배포 미완료 | `core/paper_execution.py`, `core/daily_briefing.py`, `docs/PAPER_API_VERIFICATION_RUNBOOK.md` | 응답 유실·부분 체결 재현에서 중복 주문이 0인가(VM 실계정 실행 필요) |
| ENG-06 | P1 | ALFRED 섹터·ETF 합성·결측 계약 | 제안 | `core/market_regime.py`, `core/sector_strength.py` | vintage·구성·리밸런싱과 기존 RS 대비 증분이 재현되는가 |
| ENG-07 | P1 | 발굴 PIT rank·IC·단조성 | 업종 내 rank·플래그·pit_verified=False 구현·테스트 완료, 진정한 PIT·IC 검증 미수행 | `core/stock_discovery.py` | silent fallback 없이 비용 후 예측력이 유지되는가 |
| ENG-08 | P1 | 뉴스 이벤트 시점·정정·근거·독립 검증 | timestamp 존재, 보강 제안 | `core/news_digest.py`, `core/models.py` | 라벨 정확도와 과거 재생·이벤트 성과가 분리 검증되는가 |
| ENG-09 | P1 | 실제 기업 중복 노출·Kelly OOS·공동 손실 | 상관/Kelly/역변동성 존재, 보강 제안 | `core/portfolio.py` | 중복 위험과 OOS 비용 후 효과가 확인되는가 |
| ENG-10 | P1 | 섹터 리더 결측 분리 | 재현·수정·테스트 완료(`sector_leaders`), `strategy_tuning` 동일 결함도 점수 v2로 수정 | `core/sector_leaders.py` | 결측이 고성장으로 승격되지 않는가 |
| ENG-11 | P2 | PIT 밸류에이션·reverse DCF·가정 범위 | 제안 | `core/valuation.py` | 설명 개선과 예측 우위를 분리해 입증하는가 |

Astra 분석은 반영 완료했다. 이후 각 ID에 구현·검증·배포 상태를 갱신한다. 사용자 요청 범위 안의 문서 작업은 별도 승인 흐름으로 만들지 않으며, 코드 구현·배포는 해당 요청이 명시되거나 맥락상 위임된 경우에만 진행한다.

## 후속 연구: 정보 수집·판단 엔진

해외 연구·서비스 사례와 현재 코드의 중복을 대조하고, 생성안과 반박안을 한 차례 직접 조정한 결과는 [정보 수집·판단 엔진 연구](./INFORMATION_DECISION_ENGINE_RESEARCH.md)에 기록했다.

- **RES-01 모든 후보·보류 shadow 원장: 구현·단위 테스트·스케줄 연결 완료(2026-09-22).** `core/candidate_ledger.py`(진입/청산/비용/PIT/판정)와 `core/candidate_recorder.py`(매일 00:27/00:28 KST 스케줄 잡, stock_discovery/sector_leaders/champion_satellite 세 소스)가 있다. 관측 전용이며 주문 경로 미연결. 배포되면 실제 DB에 기록이 쌓이기 시작하므로 배포는 별도 결정 사항. RES-02 정보비용·중복 라우터(원문 중복 제거)는 아직 미구현(원장은 `event_id`/`info_cost` 필드만 갖고 있음).
- RES-03은 기존 thesis review의 사전 KPI·반증·원문 anchor 강화로 한정한다(미착수).
- **RES-04 발행사 가이던스 기대 변화: 스펙·추출기·오프라인 테스트 완료, 실제 EDGAR 12건 표본 완료(`docs/experiment_validation/earnings_guidance_extraction_sample.md`, 사람 검증 대기).** 개별주 위성 신호 연결(shadow)은 미착수.
- **RES-05 SEC 섹션 diff: 스펙·추출기·veto 규칙·오프라인 테스트 완료, 실제 EDGAR 5개 기업 10-K 점검 완료(`docs/experiment_validation/filing_change_extraction_check.md`, 사람 검증 대기).** 기존 모멘텀 후보에 대한 veto 연결(shadow)은 미착수.
- 충분한 OOS 사건 전의 RES-06 확률 선택기와 PIT 관계·사용권이 없는 RES-07 기업관계 graph는 보류한다(RES-01 실운영 데이터가 아직 0건이라 전제 조건 미충족).

모두 **연구 제안 또는 관측 인프라**이며 실제 투자 성과·승률 개선은 어느 것도 입증하지 않았다. 기존 ENG 운영 후속 중 legacy 리더보드/UI 분리와 수동 회차 종료는 2026-09-22에 완료했다. **실제 Alpaca paper API 검증(VM에서 `scripts/verify_alpaca_paper_idempotency.py` 실행)이 남은 최우선 항목**이며, 상세는 `docs/SESSION_HANDOFF.md`의 2026-09-22 절 참고.
