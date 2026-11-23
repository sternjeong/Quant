# crash-simpath-v1 — 급락 경로 모의: GARCH 변동성 상태 + 과거 일별 수익 재표집 (사전 등록 2026-11-23)

가설 장부 H-024(parent: crash-cycle-model-v1). 규칙 버전 `crash-simpath/v1`, 판정 버전 `crash-adv-judge/v1`, 공용 정의 `research/jobs/crash-cycle-lab/SPEC.md`.
규칙·판정은 결과를 보기 전에 고정했다. 바꾸려면 새 id 로 새로 사전 등록한다.
실행: `python research/jobs/crash-simpath-v1/run.py --out DIR --checkpoint DIR [--smoke]`.

## 사용자 요청

> "예측모델을 더욱 고도화시키는 전략을 …" (2026-11-23) — 급락 예측모델 고도화 7전략 중 2.

## 이미 본 관련 결과

- crash-cycle-model-v1: 판정 14/14 FAIL. 특징 모델은 사건 28개의 잡음에 묻혔다. 기준선 KM 은 발생일 깊이·변동성을 무시한다.
- 막다른 길: 급락 중 매수 시점 신호, 업종 고르기, 인버스. 이 연구는 예측만 하고 투입 결정이 없다.

## 자료

- 판정: 미국 시장 일별 총수익만(`lab.load_us(smoke)` → `lab.us_context`).
- 보고만: 해외 3지역(`lab.load_intl(smoke, required=False)`) — 각 지역 자기 일별 수익으로 모의, 못 받으면 "해외 자료 없음".
- 스모크: 합성 자료, 경로 수 400(N_SIM_SMOKE).

## 사건·층

공용 SPEC 과 같다. 판정 층 A·B·**C(2008-01~2024-09)**, 2024-10 이후 보고만.
**v1 관례와 다른 점**: v1 은 A·B 만 판정했다. 이 연구는 검정력 때문에 C 를 판정에 넣는다. C 의 사건들은 이미 crash-cycle-model-v1 보고서에서 본 것이다 — 그래서 A·B·C 각 층의 평균이 모두 양수여야 통과한다.

## 방법 — `lab.simulate(Lv, market, P, tau, m_so_far, e, n_paths)`

1. r = 일별 로그수익, 과거 = r[1 .. tau](tau 종가까지). tau < 756(SIM_MIN_HIST) 이면 모의 없음.
2. mu = 평균, v = 분산(ddof = 0), omega = (1 − 0.08 − 0.90)·v.
3. 거르기: h = v 에서 시작, s = 1..tau 순서로 eps = r[s] − mu, z[s] = eps/√h, h = omega + 0.08·eps² + 0.90·h. 끝난 h = 다음 날 분산 h_next, 표준화 잔차 풀 Z = z[1..tau].
4. 난수: `default_rng([SEED, MARKET_CODE[market], tau])`(SEED = 20261124, 결정적).
5. 초기값(경로 n_paths 개): ell = ln(L[tau]/P), run_min = ln(1 + m_so_far), hit = ∞, hc = h_next, cap = 756 − e.
6. k = 1..1260: Z 에서 복원 추출 zk, eps = √hc·zk, ell += mu + eps, hc = omega + 0.08·eps² + 0.90·hc; k ≤ cap 이면 아직 회복 전인 경로의 run_min 갱신;
   처음 ell ≥ 0 이 된 경로의 hit = k.
7. 최종 깊이 분위수 = exp(run_min) − 1 의 분위수 5개(0.10·0.25·0.50·0.75·0.90), 회복 확률 F(h) = mean(hit ≤ h), h ∈ (252, 504, 756, 1260).

연구의 계산:
1. 미국 사건 i 마다 랜드마크 0: SIM = simulate(L, "US", P_i, t0_i, dd0_i, 0, 4000), BASE = v1 발생일 기준선(`lab.base0`).
2. 쌍 차이: d1 = 핀볼(FD, BASE) − 핀볼(FD, SIM)(깊이 확정·둘 다 있음), d2 = 브라이어(R, BASE) − 브라이어(R, SIM)(자료 안 회복·둘 다 있음).
3. 층 A·B·C → `judge_us` → SIM_M1, SIM_M2.

## 판정

| 키 | 비교 | 점수 | 통과 라벨 |
|---|---|---|---|
| SIM_M1 | SIM vs BASE(발생일) | 평균 핀볼 | BEATS_BASELINE |
| SIM_M2 | SIM vs BASE(발생일) | 브라이어(1·2·3·5년) | BEATS_BASELINE |

`lab.judge_us`: A ≥ 4·B ≥ 5·C ≥ 4·합친 ≥ 15, 무효 가드, A·B·C 평균 모두 양수 + 합친 한쪽 부호 뒤집기 p < α = 0.05/15. 그 밖 FAIL(세 평균 양수면 FAIL_UNDERPOWERED),
표본 미달·무효 → NOT_EVALUABLE. 족 15개 공통 α.

## 검정력·사전 기대

- 평가 집합은 v1 기준선이 있는 사건(짝 비교라 기준선 조건을 따름): A 5·B 9·C 7 = 21 → 필요 효과 0.66 sd.
- SIM_M1 통과 약 15%, SIM_M2 약 25%(문장 전체는 run.py EXPECTED).
- 가정 값(연 표류 7.6%·연 변동성 17%)으로 한 손 계산에서 무작위 보행의 −15% 뒤 1년 회복 확률 약 49%, 5년 약 89%(v1 KM 기준선 50%·89% 와 같은 크기 — 실제 자료 아님).

## 편향 방지

GARCH 상수(0.08, 0.90)·경로 수·길이는 문헌 전형값과 계산 예산으로 정했고, v1 결과에는 GARCH 에 관한 정보가 없다. 표류는 그때까지 전체 과거 평균(1930년대 포함)이라
v1 에서 본 '기준선이 비관적'이라는 사실 쪽으로 맞춘 것이 아니다. 해외 재현은 보고만.

## 지금 읽기 (설명용 — 추천 아님)

진행 중 사건이면 오늘 상태(e = 마지막 날 − t0, 지금까지 최저)에서 모의, 아니면 "만약 오늘이 발생일이라면(−15% 고정, 변동성 상태는 오늘 값)"(ell = ln 0.85, m = −0.15, e = 0)
+ 오늘 연율 변동성 vs 장기. READING_HEADER 문구, SPY 확인 한 줄.

## 보고만

- (a) 랜드마크 21·63·126: simulate(L, "US", P, t0 + e, 지금까지 최저, e, 4000) vs 연구 1 BASE(BASE_TRUNC·생존 조건 KM).
- (b) SIM_IID: 같은 절차에서 거르기 없이 분산 상수(hc ≡ v, Z = (r − mu)/√v) — 변동성 상태의 몫.
- (c) 해외: 지역 자기 수익으로 SIM(과거 756일 미만이면 없음) vs 미국 학습 BASE, I1·I2 평균 d·군집 p.
- A+B 만 p, 미국 겹침 군집 p, 층별 평균 핀볼·브라이어(BASE·SIM·SIM_IID), 80% 포함률, 회복 보정표, 발생일 변동성(vol_now/vol_lr)별 사건 표.
- 7개 사건: 발생일 SIM vs BASE vs 실제, 사건 안은 기준일 상태에서 모의 스냅숏.
- predictions.csv: US·해외 랜드마크 0 = BASE, SIM(미국은 SIM_IID 도). 21/63/126 = BASE(연구 1 과 같은 값), SIM. judged = 미국 A·B·C 랜드마크 0 의 SIM 쌍.

## 계산 예산

스모크(경로 400): 약 11초. 실제(경로 4,000): 모의 한 번 약 0.13초(VM, 1,260단계·거르기 포함) × 약 200번 ≈ 30~60초, 메모리 약 150MB(설계 예산 2분 안팎·1024MB 안).
체크포인트는 쓰지 않는다(`--checkpoint` 폴더만 만든다).

## 한계

1. 표류 고정·평균 회귀 없음·대칭 GARCH. 2. 잔차는 독립 재표집(달력 군집 없음). 3. 경로 하나의 시장만(정책·거시 없음). 4. 모의 오차(경로 4,000개, 결정적 seed).

## 의도적으로 뺀 것

마르코프 전환·HMM·GARCH-MIDAS·비대칭 GARCH 추정(자유도 과다, numpy 만으로 추정 부담), GARCH 모수 추정(고정값만 씀), 평균 회귀 항.
