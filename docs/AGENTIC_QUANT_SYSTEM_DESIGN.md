# 에이전트 결합형 퀀트 시스템 설계 (제안)

작성 2026-09-25. 상태: **S1~S5 구현(단위 테스트) + 허브 화면, S6 일부.** 사용자 결정(2026-09-25): 추천안 채택, 에이전트 배치 03:00 KST, 토큰 예산은 위임.
목적: 개인 VM 1대에서 AI 에이전트를 토큰 효율적으로 쓰면서, 가짜 발견을 걸러내고 전략을 지속적으로 발굴·검증한다. 실거래가 아니라 **검증용**이다(paper 까지).

## 0. 설계 원칙

1. **에이전트는 생각하고, 코드는 판정한다.** 성과 판정·통계 검정·승격에는 LLM 을 쓰지 않는다(재현 가능, 토큰 0).
2. **모든 시도를 센다.** 후보를 많이 만들수록 우연히 좋아 보이는 전략이 늘어난다. 시도 수를 기록하고 기준을 그만큼 올린다.
3. **표본은 사람 없이 쌓인다.** shadow 원장·paper 계좌처럼 매일 자동으로 증거가 누적되는 장치에만 의존한다.
4. **사람은 폰으로 예/아니오만.** 사람 결정이 필요한 곳은 텔레그램 1건 + 허브 화면 1개로 끝낸다.
5. **산출물은 파일이다.** 에이전트 출력은 커밋 가능한 스펙·코드·리포트여야 하고, 대화 맥락에 의존하지 않는다.

## 1. 전체 구조

```
          ┌──────────────── 에이전트 층 (토큰 사용) ────────────────┐
 소스 ──▶ │ Scout ─▶ Hypothesis Writer ─▶ Implementer ─▶ Critic      │
          └───────────────────────┬──────────────────────────────────┘
                                  │ 동결된 스펙(JSON) + 신호 코드
          ┌──────────────── 결정론 층 (토큰 0) ─────────────────────┐
          │ Registry ─▶ Judge(백테스트·검정) ─▶ Shadow ─▶ Paper      │
          └───────────────────────┬──────────────────────────────────┘
                                  │ 승격 후보
                         사람(텔레그램 예/아니오, 허브 화면)
```

| 층 | 구성요소 | 기존 자산 재사용 |
|---|---|---|
| 데이터 | 가격(yfinance+Alpaca 교차검증), FRED, SEC EDGAR, Alpaca 뉴스, 거장 13F/ARK | `price_crosscheck`, `guidance_event_provider`, `filing_changes`, `alpaca_news`, `guru_schedule` |
| 레지스트리 | 가설 스펙·시도 카운터·상태 전이 | 신규(`core/hypothesis_registry.py`) |
| 심판 | PIT 백테스트, 실측 비용, 레짐 분리, 다중검정 보정, 챔피언 상관 | `trade_ledger`, `cost_calibration`, `market_regime`, `strategy_variants` |
| 전진 검증 | 매일 판정 기록, 성과 추적 | `candidate_ledger`, `variant_shadow_record` |
| 실행 | paper 자동 주문(게이트) | `paper_auto_trade`, `paper_execution`, `paper_tracking` |
| 에이전트 실행 | 큐 + 배치 러너 | `deploy/codex_telegram/runner.py`(Claude 백엔드), `resource_guard` |
| 관제 | 허브 `/research` 화면, 텔레그램 요약 | `hub/`, `telegram_notify` |

## 2. 가설 스펙 (에이전트 ↔ 코드의 계약)

```json
{
  "id": "H-2026-0042",
  "parent": "H-2026-0031",
  "source": "sec_8k_guidance",
  "thesis": "연간 가이던스 상향 후 20거래일 초과수익",
  "universe": {"type": "sp500_pit", "min_price": 5, "min_adv_usd": 5000000},
  "signal": {"module": "signals/h0042.py", "function": "score", "params": {"lookback": 20}},
  "portfolio": {"top_k": 10, "weighting": "equal", "rebalance": "weekly", "max_weight": 0.15},
  "costs": "measured_or_25bp",
  "horizon_days": 20,
  "regimes": ["bull", "bear", "sideways"],
  "kill_criteria": {"min_trades": 60, "max_drawdown": 0.35},
  "param_grid_size": 4,
  "frozen_at": "2026-10-01T00:00:00Z"
}
```

- `param_grid_size` 까지 시도 수로 센다(파라미터 4개 조합이면 시도 4회).
- 동결(`frozen_at`) 후에는 수정 불가. 고치려면 `parent` 를 가진 **새 가설**이 되고 시도 수가 늘어난다.
- 신호 코드는 `signals/` 아래 순수 함수로, 입력은 as-of 날짜까지의 데이터만 받는다(미래 참조를 인터페이스로 차단).

## 3. 결정론 층 상세

### 3.1 Registry 상태 전이
`draft → frozen → judged(pass|fail) → shadow → promoted_paper → retired`
각 전이는 시각·근거와 함께 SQLite 에 남는다. 상태를 되돌리는 전이는 없다.

### 3.2 Judge (백테스트 + 검정)
1. PIT 유니버스로 백테스트, 비용은 실측 교정(30건 이상일 때) 아니면 25bp 보수 가정.
2. 레짐별로 따로 평가한다(같은 레짐 안에서만 비교 — 기존 결정).
3. **다중검정 보정:** 누적 시도 수 N 으로 Deflated Sharpe Ratio(또는 Bonferroni 계열 임계값)를 계산. N 은 전 기간 누적이며 줄지 않는다.
4. 챔피언 수익과의 상관이 0.7 이상이면 "새 정보 없음"으로 탈락.
5. 최소 거래 수·최대 낙폭 등 `kill_criteria` 적용.
6. 결과는 고정 형식 JSON + 1쪽 HTML. 판정은 pass/fail 두 가지뿐(모호한 "유망" 없음).

### 3.3 Shadow (전진 검증)
- 통과 가설은 매일 00:4x KST 에 판정만 기록한다(주문 없음).
- **60거래일** 후 백테스트 기대치 대비 전진 성과를 비교: 기대치의 신뢰구간 안이면 승격 후보, 밖이면 retired.
- 동시에 shadow 에 있을 수 있는 가설 수 상한(예: 20개) — 자원과 사람 주의력 보호.

### 3.4 Paper 승격
- 사람이 텔레그램에서 승인하면 champion 의 위성 슬롯 일부(예: 자산 10%)로 paper 편입.
- 추적오차·실측 슬리피지가 기존 모듈로 자동 기록된다.
- 실거래는 이 설계 범위 밖(별도 사람 결정).

## 4. 에이전트 층 상세

| 역할 | 하는 일 | 모델·빈도 | 입력 → 출력 |
|---|---|---|---|
| Scout | 새 공시·뉴스·거장 변화·논문에서 가설 씨앗 수집 | 저가 모델(Haiku급), 매일 1회 | 데이터 diff → 씨앗 목록 md |
| Hypothesis Writer | 씨앗 + **실패 기록**을 읽고 스펙 작성 | 상위 모델, 주 2~3회 배치 | 씨앗·실패 로그 → 스펙 JSON 1~5개 |
| Implementer | 스펙의 신호 함수 작성 + 단위 테스트 | 중간 모델(Sonnet급) | 스펙 → `signals/*.py` + 테스트 |
| Critic | 미래 참조·생존편향·데이터 누수 코드 리뷰 | 상위 모델, 동결 직전 1회 | 코드 diff → 통과/반려 사유 |
| Post-mortem | fail/retired 가설의 원인 요약 → 실패 기록에 추가 | 중간 모델, 주 1회 | 판정 JSON → 실패 로그 |

**핵심:** Critic 은 결과(수익률)를 보지 않고 코드만 본다. Writer 는 과거 결과를 보되 **이미 동결된 스펙은 못 바꾼다.** 결과를 보고 스펙을 다듬는 루프를 구조적으로 차단한다.

### 4.1 실행 방식
- 큐: `data/agent_queue/*.json`(작업 1건 = 파일 1개, 상태 포함). 러너가 하나씩 꺼내 Claude CLI 로 실행.
- 스케줄: 사람이 자는 시간대 배치(예: 02:00~06:00 KST), `resource_guard` 로 스케줄러 야간 블록과 겹치지 않게.
- 사용량 한도에 걸리면 작업을 `deferred` 로 두고 다음 배치에 이어 처리(재시도 폭주 없음).
- 산출물은 브랜치 `agent/<날짜>` 에 커밋, **테스트 통과 시에만** main 병합 후보. main 푸시는 기존 자동 배포 규칙 그대로.

### 4.2 토큰 예산
| 항목 | 주간 예산 비중 |
|---|---|
| Hypothesis Writer | 40% |
| Implementer | 25% |
| Critic | 20% |
| Scout / Post-mortem | 15% |
판정·백테스트·리포트는 0%. 주간 가설 동결 수 상한(예: 10개)을 두어 예산과 다중검정 부담을 동시에 제한한다.

## 5. 사람 접점

- **텔레그램:** 주 1회 요약(동결 N·통과 N·shadow 현황·승격 후보) + 승격 후보가 생길 때만 즉시 1건. 버튼: 승인 / 보류 / 폐기.
- **허브 `/research`:** 가설 퍼널(동결→통과→shadow→paper), 누적 시도 수와 현재 유의성 임계값, 최근 실패 원인 상위 5개.
- 사람이 응답하지 않으면 **아무것도 승격되지 않는다**(기본값은 현상 유지).

## 6. 구현 순서

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| S1 | 스펙 스키마 + Registry + 시도 카운터 | 스펙 동결·상태 전이·카운트 테스트 |
| S2 | Judge 하네스(기존 백테스트 재사용 + DSR + 상관 필터) | 기존 챔피언을 가설로 넣어 재현 |
| S3 | Shadow 연결 + 60일 판정 | 가설 1개 매일 기록 |
| S4 | 에이전트 큐·러너(Implementer, Critic 먼저) | 사람이 쓴 스펙으로 코드 자동 생성·리뷰 |
| S5 | Scout + Writer + Post-mortem | 주간 자동 가설 사이클 1회 |
| S6 | 허브 `/research` + 텔레그램 승인 버튼 | 폰으로 승격 결정 |

S1~S3 는 에이전트 없이도 가치가 있다(사람이 가설을 넣어도 동작). 에이전트는 심판이 준비된 뒤에 붙인다.

## 7. 한계와 위험

- 무료 데이터 한계: PIT 구성종목이 불완전하면(2주 실험 중단 원인) 유니버스를 데이터가 있는 범위로 제한해야 한다.
- 60거래일 shadow 는 통계적으로 짧다. 승격은 "paper 에서 더 볼 가치가 있다"이지 "검증됐다"가 아니다.
- DSR 도 시도 수를 정직하게 셀 때만 의미가 있다. 레지스트리 밖에서 한 실험(수동 노트북 등)은 카운트에 넣는 규칙이 필요하다.
- 에이전트가 쓴 신호 코드의 미래 참조는 Critic + 인터페이스 차단으로 줄일 뿐 0으로 만들지는 못한다.

## 8. 구현 현황 (2026-09-25)

| 단계 | 파일 | 상태 |
|---|---|---|
| S1 스펙·레지스트리·시도 카운터 | `core/hypothesis_spec.py`, `core/hypothesis_registry.py`, `core/models.py`(Hypothesis·HypothesisEvent·HypothesisShadowRecord) | 구현. 주간 동결 10, shadow 20 |
| S2 심판 | `core/hypothesis_engine.py`, `core/hypothesis_judge.py` | 구현. DSR≥0.95, 레짐 과반, SPY 상관<0.9, 챔피언 상관<0.7(라이브 원장 60일 이상일 때), kill 기준 |
| S3 shadow | `core/hypothesis_shadow.py`, 잡 `hypothesis_shadow_record` 00:48 KST | 구현. 60거래일 뒤 z≥−1.96 이면 승격 후보 |
| S4 큐·러너 | `core/agent_batch.py`, `scripts/agent_batch.py`, 잡 `agent_batch` 03:00 KST | 구현. 큐 파일 대신 매 단계 상태에서 재계획(중단 후 자동 재개) |
| S5 역할 5종 | `research/agent_prompts/*.md` | 구현(프롬프트). 실제 Claude 실행은 VM 첫 배치에서 처음 확인 |
| 예산 | `core/agent_budget.py` | 하룻밤 $15·주간 $60(API 환산), 역할별 모델·턴·시간·주간 횟수 |
| S6 허브·승인 | `hub/research_status.py`(`/research`), `scripts/hypothesis_admin.py` | 허브 구현. **텔레그램 승인 버튼·paper 자동 편입은 미구현**(승인은 admin 스크립트) |

### 토큰 예산 (사용자 위임으로 설정)
| 역할 | 모델 | 최대 턴 | 시간 | 주간 횟수 | 요일 |
|---|---|---|---|---|---|
| Scout | haiku | 12 | 15분 | 7 | 매일 |
| Writer | opus | 25 | 30분 | 3 | 월·수·금 |
| Implementer | sonnet | 40 | 30분 | 12 | 매일 |
| Critic | opus | 15 | 20분 | 14 | 매일 |
| Post-mortem | sonnet | 15 | 20분 | 1 | 일 |
03:00 시작, 05:30 이후 새 작업 금지, 05:50 강제 종료. 사용량 한도 메시지가 보이면 그 밤 배치 중단.

### 안전장치
에이전트 쓰기 권한은 자기 작업 폴더로 제한(`--allowedTools`), 실행 후 `research/` 밖 변경 자동 되돌림, 자식 환경에서
브로커·텔레그램 비밀값 제거, 동결본(스펙+코드)은 DB 에 복사, 작업 폴더(`research/hypotheses/` 등)는 git 미추적·백업 대상.

## 9. 결정 필요(사람)
1. 주간 가설 동결 상한(제안 10개)과 shadow 동시 상한(제안 20개).
2. 다중검정 방식: DSR(제안) vs 더 단순한 Bonferroni.
3. 에이전트 배치 시간대와 주간 토큰 예산 상한.
4. ~~S1 부터 착수할지~~ — 착수·구현 완료. 남은 결정: 텔레그램 승인 버튼과 승격 가설의 paper 편입 자동화를 할지.
