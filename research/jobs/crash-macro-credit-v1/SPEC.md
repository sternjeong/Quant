# crash-macro-credit-v1 — 금리·신용 여건으로 가른 긴 약세장 확률: 깊이·회복·분할 비율 (사전 등록 2026-11-23)

가설 장부 **H-022**(parent: crash-cycle-model-v1; 상태 queued → registered, study_id 채움). 규칙 버전 `crash-macro-credit/v1`, 판정 버전 `crash-adv-judge/v1`,
공용 정의 `research/jobs/crash-cycle-lab/SPEC.md`. 규칙·판정은 결과를 보기 전에 고정했다. 바꾸려면 새 id 로 새로 사전 등록한다.
실행: `python research/jobs/crash-macro-credit-v1/run.py --out DIR --checkpoint DIR [--smoke]`.

## 사용자 요청

> "예측모델을 더욱 고도화시키는 전략을 …" (2026-11-23) — 급락 예측모델 고도화 7전략 중 3. 장부에 대기 중이던 H-022 를 이 연구가 맡는다.

## 이미 본 관련 결과

- crash-cycle-model-v1: 판정 14/14 FAIL. 금리 특징 RATECHG 는 일별 RF 의 0.01% 계단(연 2.5%p) 결함으로 사실상 미검증(사후 분석).
  분할 투입이 도운 사건은 긴 약세장(2000·2008·2022)뿐이었다.
- 막다른 길: 급락 중 매수 시점 신호, 업종 고르기, 인버스. 모델 3 은 발생일에 비율을 한 번 정하고 달력대로 넣는다(신호 기다리기가 아님).

## 자료

- 미국 시장 일별 총수익: `lab.load_us(smoke)` → `lab.us_context`.
- 월별 RF: `lab.load_rf_monthly(smoke)` = Ken French `ff3_monthly` 의 RF(소수/월, 1926-07~). 못 받으면 RuntimeError(실행기 재시도).
- 무디스 AAA·BAA 월별(%): `lab.load_moodys(smoke)` = 저장소 스냅숏 `research/jobs/crash-cycle-lab/data/moodys_monthly.csv`(1919-01~, 출처·sha256 은 공용 SPEC). 네트워크 안 씀.
- 스모크: `synthetic_rf_monthly`·`synthetic_moodys`(실제 무디스 파일을 읽지 않음).

## 사건·층

공용 SPEC 과 같다. 판정 층 A·B·**C(2008-01~2024-09)**, 2024-10 이후 보고만.
**v1 관례와 다른 점**: v1 은 A·B 만 판정했다. 이 연구는 검정력 때문에 C 를 판정에 넣는다(합친 n ≈ 14 → ≈ 21). C 의 사건들은 이미 crash-cycle-model-v1 보고서에서 본 것이다
— 그래서 A·B·C 각 층의 평균이 모두 양수여야 통과한다.

## 특징 (발생일이 속한 달 m 의 m−1 달 값, 모두 연율 소수)

| 코드 | 식 | 근거 |
|---|---|---|
| RATECHG_M | 12·(RF[m−1] − RF[m−13]) | Lunde & Timmermann(2004). v1 RATECHG 의 일별 RF 계단 결함 수정판 |
| TERM | AAA[m−1]/100 − 12·RF[m−1] | Fama & French(1989) TERM(Aaa − 1개월 국채). 낮거나 역전이면 침체 신호(Estrella & Mishkin 1998, Chen 2009) |
| DEF | (BAA[m−1] − AAA[m−1])/100 | Fama & French(1989) DEF. 신용 경색(Muir 2017, Gilchrist & Zakrajšek 2012) |

`lab.macro_features`. 필요한 달이 없으면 nan(표준화 뒤 0 = 평균 대치). 부호는 강제하지 않는다. 표준화는 예측마다 그 학습 집합으로.

## 방법

1. 미국 사건마다 x_j = (RATECHG_M, TERM, DEF)(발생일 m−1 달).
2. 사건 i(D = 발생일): 분류기 학습 집합 C(i) = {j : t0_j < D, lb_label(j, D) 있음}(라벨 1 = 252거래일 안 회복 못 함, D 에 알 수 있는 것만),
   `fit_ridge_logit(X_C, y_C, λ = 4)`. 'fit 가능'(n ≥ 6, 두 갈래 각 1개 이상, 수렴)이 아니면 미적합 → 그 사건은 세 판정 모두에서 빠짐(n_unfit).
3. 모델 1·2(MACRO): T1 = m1_pool(us, D), m2_pool(us, D) 의 각 사건 라벨·특징으로 p_center → 가중치(라벨 1 → p/π, 0 → (1−p)/(1−π), 모름 → 1) →
   재가중 분위수(모델 1, 발생일 깊이로 변환)·베란 KM(모델 2). p_center 가 None 이면 미적합.
4. p_lb, π = p_center(fit, x_i, X_C, y_C)(p 는 [0.05, 0.95] 로 자름, 기울기가 모두 0 이면 p = π).
5. 모델 3(t0 + 1 + 756 ≤ 자료 끝일 때): a = 1 − p_lb, a0 = 1 − π, 일정 T(a) = [(0, a)] + [(21·k, (1 − a)/6), k = 1..6](a = 0.5 면 v1 HALF6),
   W = `v1.schedule_path(L, rf, t0 + 1, 756, T)`(기다리는 돈은 그날 RF, 마지막 회차는 남은 현금 전부), D3 = ln W_SPLIT_P[756] − ln W_SPLIT_P0[756].
6. 쌍 차이: d1 = 핀볼(BASE) − 핀볼(MACRO)(깊이 확정), d2 = 브라이어(BASE) − 브라이어(MACRO)(자료 안 회복). BASE = v1 발생일 기준선(`lab.base0`).

## 판정

| 키 | 비교 | 점수 | 통과 라벨 |
|---|---|---|---|
| MAC_M1 | MACRO vs BASE | 평균 핀볼 | BEATS_BASELINE |
| MAC_M2 | MACRO vs BASE | 브라이어(1·2·3·5년) | BEATS_BASELINE |
| MAC_M3 | SPLIT_P vs SPLIT_P0(같은 시점 기준 확률의 고정 분할) | D3 | BEATS_FIXED_SPLIT |

`lab.judge_us`: A ≥ 4·B ≥ 5·C ≥ 4·합친 ≥ 15, 무효 가드, A·B·C 평균 모두 양수 + 합친 한쪽 부호 뒤집기 p < α = 0.05/15. 그 밖 FAIL(세 평균 양수면 FAIL_UNDERPOWERED),
표본 미달·무효 → NOT_EVALUABLE. 족 15개 공통 α.

## 검정력·사전 기대

- 분류기 적합은 1946-09 사건부터 가능(라벨 있는 사건 6개: 긴 약세장 5·빠른 반등 1). 예상 n: 모델 1·2 A 5·B 9·C 7 = 21, 모델 3 A 5·B 9·C 7 = 21 → 필요 효과 0.66 sd.
  무디스(1919-01~)와 월별 RF(1926-07~)로 미국 사건 28개 모두 특징이 계산된다(첫 사건 1929-10 의 m−13 = 1928-09).
- MAC_M1 통과 약 10%, MAC_M2 약 12%, MAC_M3 약 8%(문장 전체는 run.py EXPECTED).

## 편향 방지

v1 의 금리 특징은 자료 결함으로 사실상 미검증이었고, TERM·DEF 는 이 저장소 급락 연구에서 한 번도 본 적이 없다. 특징 3개는 H-022 문장과 Fama-French(1989) 정의로
결과 전에 고정했고 부호를 정하지 않았다. 방법은 연구 4·6 과 같은 공용 코드라 이 연구만을 위해 고른 것이 없다. 모델 3 의 비교 대상은 같은 평균 비율의 고정 분할이라
'긴 약세장에서 분할이 도왔다'는 v1 관찰만으로는 통과할 수 없고 분류 실력이 있어야 한다. 구현자는 무디스 스냅숏을 만든 뒤 사건 날짜의 값을 들여다보지 않았다.

## 지금 읽기 (설명용 — 추천 아님)

마지막 날의 m−1 달 특징 값(없으면 "자료 없음"), "만약 오늘이 발생일이라면"(dd0 = −15%, 라벨 있는 모든 사건으로 학습) p_lb·MACRO 분위수·회복 확률·a_now = 1 − p_lb.
진행 중 사건이면 그 사건 발생일의 특징·깊이로(학습은 마지막 날까지, 회복은 경과일 조건부 — v1 과 같은 방식). SPY 확인 한 줄.

## 보고만 (라벨 없음)

- 특징 하나씩: MACRO_RATECHG·MACRO_TERM·MACRO_DEF(같은 절차, 특징 1개) — 평균 d·합친 p.
- KERNEL_RATECHG_M: v1 커널 가중(`v1.kernel_weights`) + v1 BASE 절차에 RATECHG_M — "v1 결함 수정판" 직접 비교.
- 분류 실력: 판정 사건의 실제 라벨로 (LB − p_lb)² 평균 vs (LB − π)² 평균. 기울기 요약: 마지막 날 적합의 표준화 기울기 3개, 판정 사건 적합들에서 각 기울기 양수 비율.
- A+B 만 p, 미국 겹침 군집 p, 모델 3 의 LUMP·HALF6 대비 평균 D·G·후회 비율.
- 7개 사건 표: 발생일 RATECHG_M·TERM·DEF·p_lb·MACRO vs BASE(깊이 10/50/90%, 회복 1·2·5년)·a_now·실제.
- predictions.csv(미국 랜드마크 0): BASE, MACRO(p_lb), MACRO_RATECHG·MACRO_TERM·MACRO_DEF·KERNEL_RATECHG_M(보고), SPLIT_P(a_now = a, p_lb), SPLIT_P0(a_now = a0).
  SPLIT 줄은 깊이·회복 칸이 빈칸. judged_m1/m2 는 모델 1·2 판정 쌍(MACRO 와 같은 열쇠의 BASE)에만 1(모델 3 판정 소속은 results.json episodes 의 D3).

## 한계

1. 월별 자료라 발생일 직전 몇 주의 급변을 못 본다. 2. 무디스 Baa 는 투자 등급(하이일드 아님). 3. TERM 의 장기 금리는 Aaa 회사채.
4. 사건 20개 남짓에 특징 3개. 5. 모델 3 은 고정 분할 대비만 판정(LUMP 대비는 보고).

## 의도적으로 뺀 것

FRED VIX·하이일드·T10Y3M·BAA10Y·실시간 침체 지표(시대 A·B 가 비어 구조적으로 평가 불가), 밸류에이션(CAPE — 실시간 자료 불확실), 부호 강제, 랜드마크에서 비율 다시 정하기(막다른 길).
