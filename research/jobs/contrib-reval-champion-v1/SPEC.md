# 처음 목돈 + 매달 적립으로 다시 본 챔피언·후보 v1 — 사전 등록

등록일: 2026-10-17(결과를 보기 전). 판정 코드: `research/jobs/contrib-reval-champion-v1/run.py`(`RULES_VERSION = contrib-reval-champion-v1/2026-10-17`).
판정 기준을 바꾸려면 이 id 를 고치지 않고 새 id 로 다시 등록한다. 엔진(챔피언) 반영은 결과를 본 사용자 확인 뒤 별도 작업이다.

## 왜

사용자 목표: 엔진을 처음 목돈 + 매달 적립으로 끝없이 굴리고, 한국 세금 뒤 장기적으로 SPY 를 이긴다.
지금까지 후보 연구는 한 시작일(2010-01)에 목돈 한 번만 넣고 쟀다. 시작일 운과 적립 효과를 함께 보려면 매달 시작하는 많은 구간에서
같은 적립금을 받는 SPY 그냥 보유와 비교해야 한다(`core/rolling_eval.py`, `core/tax_fx.py` 적립 기능).

## 전략(10개 — 판정 8개)

각 전략은 출처 연구의 함수를 그대로 불러(다시 구현하지 않음) 2010-01 부터 끝까지 일별 목표 비중 표를 **한 번** 만들고, 구간마다 잘라 쓴다.
모든 표는 CHAMP 의 거래일 축에 맞춘다(같은 구간의 SPY 기준이 모든 전략에 같은 날짜로 돈다).

| id | 내용 | 출처 |
|---|---|---|
| SPY | 그냥 보유(기준, 같은 적립금) | `tax_fx.buy_and_hold_weights` |
| CHAMP | 라이브 코어 85% + S-SEED-000 15%(라이브 방식) | spy-champion-v1 `champion_weights` = satellite-value-v1 A |
| P1 | SPY 85% + 새틀라이트 15%, 1월 리셋 | spy-champion-v1 `candidate_weights("P1")` |
| P3 | SPY 70% + 새틀라이트 30%, 1월 리셋 | 같은 함수 `"P3"` |
| P4 | SPY 50% + 새틀라이트 30% + 코어 20%, 1월 리셋 | 같은 함수 `"P4"` |
| P1ST | SPY 85% + 새틀라이트 5%×3(재선정 1·7월 / 3·9월 / 5·11월), 각 하위 슬리브 K6 순위 버퍼, 1월 리셋 | core/forward_tournament_v3 P1ST 규칙을 과거에: spy-champion-v1 `sleeve_weights` + sat-buffer-v1 `build_schedules`(K=6) + sat-stagger-v1 `sim_dates` |
| KRS | 상대강도 코어(252일 수익 > 같은 기간 SPY) 85% + S-SEED-000 15% | signal-swap-v1 `core_variant_weights("KRS")` + `tax_fx.champion_weights` |
| CHAMP_K6 | 현 챔피언, 새틀라이트만 K6_H6 버퍼 | sat-buffer-v1 `_weights("champ", "K6_H6")` |
| L15F | SPY 85% + 합성 2배 15%(200일선 ±2% 완충, 월초, 그 다리에만) | lev-base-v1 `_assemble` + `portfolio_weights(0.15, True)` |
| D1 | SPY 85% + 거장 우선 S-SEED-019 15%(1월 리셋) — 13F 가 2014 부터라 **보고만** | guru-champion-v1 `build_weights()["D1"]` |

P1ST 세부: 세 하위 슬리브 모두 첫 달(2010-01 첫 거래일)에 처음 고르고(보유가 없어 그냥 상위 3), 그 뒤 자기 재선정 달 첫 거래일에만 다시 고른다.
점수는 sat-buffer-v1 `score_inputs` 와 같은 식(그날 champion40 풀, 전날까지 가격, S-SEED-000 신호)을 매달 날짜에 적용한다(`scores_on_dates`).
보유 종목이 그날 추세 활성이고 순위 6 안이면 유지, 빈자리만 상위 종목으로. 하위 슬리브 안은 고른 종목 균등(`schedule_to_log` — 3개 미만이면 있는 종목에 균등).

## 계좌 시나리오(`core/tax_fx.AccountConfig`, 카카오페이증권 기본값, 적립 정책 `underweight_first`)

| id | 처음 | 매달 적립 | 역할 |
|---|---|---|---|
| B | 1,000만 원 | 15만 원 | **판정** |
| A | 1,000만 원 | 없음 | 목돈만(보고, 같은 규칙 결과 비교) |
| C | 300만 원 | 15만 원 | 보고 |
| B10 | 1억 원 | 150만 원 | 보고(규모 민감도 — 250만 원 공제가 원화 고정이라 결과가 규모에 따라 다르다) |

적립금은 시작 다음 달부터 매달 첫 거래일 종가에 들어와 목표보다 모자란 종목부터 산다. SPY 기준도 같은 날 같은 돈을 받는다.

## 구간

`core/rolling_eval.rolling_windows`: 2010-01 부터 매달 첫 거래일에 시작, 5년(판정)·10년(보고) 뒤 마지막 거래일에 끝.
판정 = **2024-09-30 이하에서 끝나는 구간**. 그 뒤에 끝나는 구간은 따로 보고만 한다(떼어 둔 구간 소진 — 판정 설계 규칙 3).
D1 은 자기 첫 날(2014-01 첫 S-SEED-019 리밸런싱) 이후 시작하는 구간만.

## 지표

구간마다(`rolling_eval.evaluate_windows`): 청산 후 최종 원화(마지막 날 다 팔고 세금까지), 적립 흐름을 넣은 연 IRR(XIRR), 시간가중 최대낙폭(mdd_tw), 돈 기준 최대낙폭(mdd_mw), 낸 양도세.
요약(`rolling_eval.summarize`): SPY 보다 많이 남은 구간 비율(share_terminal_win), IRR 차이(전략 − SPY) 중앙·평균·10/90 분위, 최악·최고 구간, 겹치지 않는 구간 수(전체 기간 ÷ 구간 길이).

## 판정 (시나리오 B, 5년, 판정 구간 — 8개 전략 각각)

`CONTRIB_BEATS_SPY` ⇔ 모두:

- (a) share_terminal_win ≥ 0.70
- (b) IRR 차이 중앙값 ≥ +0.5%p
- (c) IRR 차이 10분위 ≥ −1.5%p
- (d) 시간가중 최대낙폭 중앙값(전략) − 중앙값(SPY) ≥ −5%p

그 밖은 FAIL. `research_power.classify_fail(중앙 IRR 차이, power_report(14.7, 8))` 로 `FAIL_UNDERPOWERED` 를 구분한다
(관측 효과는 연 수익률 차이, MDE 는 연 정보비율이라 단위가 달라 근사 — 사실상 중앙 차이가 양수면 FAIL_UNDERPOWERED, 0 이하면 FAIL).
구간마다 최종 금액 차이가 전부 0 이면(`noop_guard`) NOT_EVALUABLE. 시도 수 n_trials = 8(SPY·D1 제외).
같은 규칙을 A·C·B10 에도 적용해 보고하고, 목돈만(A)과 적립(B)의 판정이 다른지 표로 낸다(보고만, 판정은 B 뿐).
D1 도 같은 규칙 결과를 보고만 한다.

## 결과

`results.json`(요약만, 200KB 미만 — 구간별 행은 넣지 않음, `verdicts` = 8개 판정), `REPORT.md`(한국어 표: 시나리오별, 구간 수·겹치지 않는 구간 수,
양도세 중앙값, 적립이 순위를 어떻게 바꿨나, 판정이 바뀌었나, 2024-10 뒤 끝나는 구간).

## 한계

- 구간이 크게 겹친다(5년 판정 구간 약 117개, 겹치지 않는 구간 약 3개). 비율은 '시작일 운'을 보여 줄 뿐 독립 시행이 아니다.
- 새틀라이트 생존편향(상장폐지 종목 가격 없음). 새틀라이트 비중이 클수록 좋게 기운다.
- 2010~2024 는 출처 연구들이 이미 본 자료다. 통과는 '전진 원장 후보'까지만 뜻한다.
- 전체 기간 표를 잘라 쓰므로 1월 리셋 전략을 1월이 아닌 달에 시작하면 그때까지 표류한 비율로 시작한다.
- L15F 의 2배 상품은 합성이다. 세금은 추정이다. 엔진은 바뀌지 않는다.

## 실행

재개 가능(입력 단계별 체크포인트 `base/krs/lev/guru/prep.pkl`, 전략×시나리오별 구간 캐시 `win_<전략>_<시나리오>.pkl`,
시나리오별 SPY 기준 캐시 `bench_<시나리오>.pkl` — 모든 전략이 함께 씀). 예산(`RESEARCH_JOB_DEADLINE_EPOCH` − 90초)이나 SIGTERM 이면 저장하고 3 으로 끝낸다.
`--smoke`: 합성 자료(네트워크 없음), 24개월 간격 시작. `--max-sims-per-run N`: 재개 확인용.
