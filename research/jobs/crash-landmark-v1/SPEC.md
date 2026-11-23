# crash-landmark-v1 — 급락 진행 중 예측 갱신: 발생 뒤 21·63·126거래일 (사전 등록 2026-11-23)

가설 장부 H-023(parent: crash-cycle-model-v1). 규칙 버전 `crash-landmark/v1`, 판정 버전 `crash-adv-judge/v1`, 공용 정의 `research/jobs/crash-cycle-lab/SPEC.md`.
규칙·판정은 결과를 보기 전에 고정했다. 바꾸려면 새 id 로 새로 사전 등록한다.
실행: `python research/jobs/crash-landmark-v1/run.py --out DIR --checkpoint DIR [--smoke]`.

## 사용자 요청

> "예측모델을 더욱 고도화시키는 전략을 …" (2026-11-23) — crash-cycle-model-v1 의 깊이·회복 예측을 고도화하는 전략 7개를 각각 실험하고 비교한 뒤 융합. 이 연구는 그중 1.

## 이미 본 관련 결과

- crash-cycle-model-v1: 판정 14/14 FAIL. 발생일에는 빠른 반등과 긴 약세장을 가를 정보가 없었다. 회복 기간은 사후 최종 깊이가 정했다(−25% 안쪽 93% 가 1년 안 회복,
  −40% 너머 3년 안 0%). 사건의 바닥까지 거래일 중앙 34일.
- 막다른 길: 급락 중 매수 시점 신호(crash-rebound-signal-v1·dca-dip-deploy-v1), 업종 고르기(crash-industry-pick-v1), 인버스(crash-inverse-v1).
  이 연구의 랜드마크 예측은 투입 결정에 연결하지 않는다(모델 3 없음).

## 자료

- 판정: 미국 시장 일별 총수익 `lab.load_us(smoke)`(Ken French ff3_daily, 평일 달력) → `lab.us_context`(v1 과 같은 사건·기준선).
- 보고만: 해외 3지역 `lab.load_intl(smoke, required=False)` — 못 받으면 "해외 자료 없음"으로 보고하고 판정·종료 코드는 그대로.
- 스모크: 합성 미국(`lab0.synthetic_data`)·합성 해외(`lab.synthetic_intl`). SPY 는 실제 실행에서만 보고(`v1.extra_spy`).

## 사건·층

공용 SPEC 과 같다. v1 사건 목록 그대로. 판정 층 A(1927-07~1966)·B(1967~2007)·**C(2008-01~2024-09)**. 2024-10 이후 발생 사건(층 X)은 보고만.

**v1 관례와 다른 점**: v1 은 A·B 만 판정하고 C 는 보고만 했다. 이 연구(와 7연구 전체)는 검정력 때문에 C 를 판정에 넣는다(합친 n ≈ 14 → ≈ 21, 필요 효과 0.86 → 0.66 sd).
C 의 사건들은 이미 crash-cycle-model-v1 보고서에서 본 것이다 — 그래서 합친 검정과 함께 A·B·C 각 층의 평균이 모두 양수여야 통과한다.

## 특징·경로 상태 (랜드마크 asof = t0 + e 종가까지)

- 랜드마크 e ∈ (21, 63, 126) 평일(1·3·6개월). `landmark_state(r, e)`: tau = t0 + e 가 자료 끝을 넘거나 이미 회복(rec ≤ tau)이면 없음.
- d = L[tau]/P − 1(지금 전고점 대비), m = min(L[t0..tau])/P − 1(지금까지 최저), x = max(ln(P/L[tau]), X_FLOOR), X_FLOOR = −ln(1 − 0.05) = 0.0512933(v1 사건 종료 문턱).
- yrem(j, e) = ln(min(L_j[t0+e .. end1]) / L_j[t0+e]) ≤ 0 (랜드마크 뒤 남은 추가 하락).

## 방법

랜드마크 0: `BASE` = v1 발생일 기준선(`lab.base0`). LM 은 0 에서 정의하지 않는다. e ∈ LANDMARKS 마다 st 가 있으면(D = asof 날짜):

1. BASE_V1 = base_m1(m1_pool(us, D), dd0) — v1 진행 중 읽기의 깊이(발생일 깊이로 변환, 학습은 asof 기준).
2. BASE_TRUNC[q] = min(m, BASE_V1[q]) — 지금까지 최저보다 얕은 예측은 불가능하므로 자른 기준선(자명한 자르기 이득을 기준선에 미리 줌).
3. BASE(회복) = base_m2(m2_pool(us, D), e) — v1 생존 조건 KM(대상 사건 자신도 e 에서 중도절단으로 들어감, v1 진행 중 읽기와 같음).
4. LM_ANCHOR: T1L = m1_pool(us, D) 중 alive_at(j, e)(자기 랜드마크에 아직 미회복); 6개 미만이면 없음.
5. LM_ANCHOR[q] = min(m, (1 + d)·exp(wquantile(yrem(T1L, e), 1, q)) − 1).
6. LM_SCALED: T2L = {j : t0_j + e ≤ 끝, 날짜(t0_j + e) < D, alive_at(j, e)}; T_j = R_j − e(rec_date ≤ D) 아니면 D 위치 − (t0_j + e) 중도절단;
   x_j = max(ln(P_j / L_j[t0_j + e]), X_FLOOR); V_j = T_j / x_j.
7. T2L 6개 미만 또는 회복 3개 미만이면 없음. 아니면 F(h) = 1 − S_V(h / x), S_V = V 의 KM, h ∈ (252, 504, 756, 1260).
8. 쌍 차이: d1[i,e] = 핀볼(FD_i, BASE_TRUNC) − 핀볼(FD_i, LM_ANCHOR)(깊이 확정·둘 다 있음), d2[i,e] = 브라이어(R_i − e, BASE) − 브라이어(R_i − e, LM_SCALED)(회복·둘 다 있음).
9. 사건 값 d1_i·d2_i = 있는 랜드마크의 단순 평균(같은 사건의 랜드마크끼리는 독립이 아니므로). 하나도 없으면 판정에서 빠짐.

## 판정

| 키 | 비교 | 점수 | 라벨 |
|---|---|---|---|
| LM_M1 | LM_ANCHOR vs BASE_TRUNC | 평균 핀볼(분위수 5개) | BEATS_BASELINE / FAIL / NOT_EVALUABLE |
| LM_M2 | LM_SCALED vs BASE(생존 조건 KM) | 브라이어(1·2·3·5년 평균) | 같음 |

`lab.judge_us`: A ≥ 4·B ≥ 5·C ≥ 4·합친 ≥ 15, 무효 가드, A·B·C 평균 모두 양수 + 합친 한쪽 부호 뒤집기 p < α = 0.05/15 → BEATS_BASELINE.
그 밖 FAIL(세 평균 모두 양수면 FAIL_UNDERPOWERED), 표본 미달·무효 → NOT_EVALUABLE. 족 15개(공용 SPEC 표) 공통 α.

## 검정력·사전 기대

- 모든 미국 사건은 21일째 살아 있다. 모델 1 학습 조건은 1946-09 사건부터 충족 → 예상 판정 n: A 5·B 9·C 7 = 21(모델 1·2 같음). 필요 효과 0.66 sd,
  참 효과 δ = 0.5 / 0.8 에서 통과 확률 약 34% / 83%.
- LM_M1: BEATS_BASELINE 가능성이 높다(약 55%). LM_M2: BEATS_BASELINE 가능성이 가장 높다(약 65%). (문장 전체는 run.py EXPECTED)

## 편향 방지

- '남은 거리'를 쓰자는 생각은 v1 의 사후 깊이 구간별 KM 을 보고 나왔다. 그러나 '전고점까지 남은 거리가 멀수록 오래 걸린다'는 무작위 보행 첫 도달 시간에서 나오는
  선험적 관계이고 변환에 자유 모수가 없다(X_FLOOR 는 v1 의 −5% 를 그대로 씀).
- 랜드마크는 결과 전에 고정(호출자 제시 20/60/120일 → 평일 21/63/126). 격자를 넓히지 않는다.
- 비교 대상은 같은 정보를 쓰는 가장 강한 기준선(v1 진행 중 읽기 + 자르기). v1 '이미 지금만큼 빠진 사건' 설명값(M1_ALREADY·M2_DEEP)과의 비교도 보고.
- 미국 사건 결과는 모두 알려져 있다 → 해외 3지역에서 같은 계산을 미국 학습으로 재현해 보고(라벨 없음).

## 지금 읽기 (설명용 — 추천 아님)

READING_HEADER 문구. 진행 중 사건이면 e_now = 마지막 날 − t0 에서 BASE·LM. 아니면 상태 한 줄 + 조견표: e ∈ {21, 63, 126} × d ∈ {−5, −10, −15, −20, −25, −30, −40%},
m = min(d, −15%), dd0 = −15%, 마지막 날까지 확정된 학습 집합으로 LM_ANCHOR 10/50/90%·LM_SCALED 1·2·5년과 BASE(표시용, 판정과 무관). SPY 확인 한 줄.
Ken French 자료 마지막 날 기준이라 오늘과 1~2개월 차이가 날 수 있음을 적는다.

## 보고만

- 7개 사건(1987·1998·2000·2001-09·2008·2020·2022): v1 과 같은 대응 문구, 그 사건의 랜드마크 21·63·126 의 d·m·BASE·LM·실제. 사건 안(2001-09-17, 2008-09-15 등)은
  기준일 e = 기준일 − t0 에서 같은 함수로 스냅숏.
- 모델 절: 랜드마크·층별 평가 수, 평균 핀볼(BASE_V1·BASE_TRUNC·LM_ANCHOR·M1_ALREADY), 80% 포함률; 평균 브라이어(BASE·LM_SCALED·M2_DEEP), 보정표.
- 견고성: (a) A+B 만 p(v1 방식), (b) 미국 겹침 군집 p(`v1.cluster_p`, 모델 1 [t0, end1], 모델 2 [t0, rec]), (c) 랜드마크 하나씩 평균·p, (d) 해외 3지역 재현(I1·I2 평균, 군집 p),
  (e) M1_ALREADY·M2_DEEP 대비 차이. 판정 함수는 부르지 않는다.
- M1_ALREADY = T1 중 FD ≤ m 인 사건의 FD 분위수(3개 미만이면 없음). M2_DEEP = m2_pool 행 중 (확정이면 FD, 아니면 asof 까지 최저) ≤ m 인 것만의 KM 을 e 에서 조건부(6개·회복 3개 미만이면 없음).
- v1_check: 미국 랜드마크 0 BASE 를 v1 결과 파일과 비교(보고만).
- predictions.csv: US·해외 랜드마크 0 = BASE; 21/63/126 = BASE(BASE_TRUNC·생존 조건 KM), BASE_V1, LM. judged 열은 미국 A·B·C 의 LM 쌍(과 같은 열쇠의 BASE 줄)에만 1.

## 한계

1. 랜드마크 예측은 발생일 뒤에만 쓸 수 있다(발생일 예측의 벽은 그대로). 2. 거리 비례 변환은 근사. 3. 126일 랜드마크는 시대 A 학습 사건이 적다.
4. 미국 사건 결과는 모두 알려져 있다(해외 재현은 보고만). 5. 총수익·명목, 3년 깊이 상한(v1 과 같음).

## 의도적으로 뺀 것

랜드마크에서 투입 다시 정하기(급락 중 매수 시점 신호 = 막다른 길), 랜드마크 격자 넓히기, 정책 대응(금리 인하)을 랜드마크 특징으로(융합 후속 후보).
