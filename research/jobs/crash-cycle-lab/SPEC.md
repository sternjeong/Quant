# crash-cycle-lab — 급락 예측 고도화 7연구 공용 정의 (사전 등록 2026-11-23)

이 폴더는 작업이 아니다(job.json 없음 — `sat-selection-lab` 선례). 연구 7개(`crash-landmark-v1` · `crash-simpath-v1` ·
`crash-macro-credit-v1` · `crash-internals-v1` · `crash-intl-pool-v1` · `crash-industry-transfer-v1` · `crash-recal-v1`)가
`lab.py` 를 `importlib` 로 읽는다(모듈 이름 `crash_cycle_lab`). 규칙·숫자는 결과를 보기 전에 고정했고 바꾸지 않는다.
바꿔야 하면 새 id 로 다시 사전 등록한다.

## 사용자 요청

"예측모델을 더욱 고도화시키는 전략을 …" — crash-cycle-model-v1(급락 깊이·회복 기간·투입 일정) 뒤에, 예측모델을 고도화하는 전략 7개를
각각 실험하고 결과를 비교한 뒤 섞을 수 있는 것은 융합 후속 연구로(융합은 이 등록의 범위가 아니다).

## 이미 본 관련 결과

- crash-cycle-model-v1: 판정 14개 모두 FAIL(특징 하나 커널 가중 모델 1·2, 달력 고정 분할 모델 3). 발생일에는 '빠른 반등'과 '긴 약세장'을
  가를 정보가 없었고, 사건 28개뿐이라 특징 하나·커널 가중은 잡음에 묻혔다. 기준선은 평가 사건에서 1년 회복을 37% 로 예측했지만 실제 59%.
  금리 특징(RATECHG)은 일별 RF 의 0.01% 계단 결함으로 사실상 미검증(사후 분석, `research/frontier/postmortems/crash-cycle-model-v1.md`).
- 막다른 길 3개: 급락 중 매수 시점 신호(crash-rebound-signal-v1·dca-dip-deploy-v1), 업종 고르기(crash-industry-pick-v1), 인버스(crash-inverse-v1).
  추가로 '발생일 가격·업종 특징 하나를 띠폭·문턱만 바꿔 다시'도 막다른 길로 본다.

## 자료

| 변수 | 로더 | 시작 | 판정 |
|---|---|---|---|
| 미국 시장 일별 총수익·일별 RF | `lab0.load_real()`(core-longrun-v1/lab.py, Ken French `ff3_daily`) → `v1_series` | 1926-07 | 예 |
| 12·49 산업 일별 | 같은 `load_real()` 의 `ind12`·`ind49` | 1926-07 | 예(연구 4·6) |
| 월별 RF | `core.french_factors.load("ff3_monthly")["RF"]` | 1926-07 | 예(연구 3) |
| 무디스 AAA·BAA 월별(%) | `lab.load_moodys()` = 저장소 스냅숏 `data/moodys_monthly.csv` | 1919-01 | 예(연구 3) |
| 해외 3지역 일별(USD) | `ff.load("intl_{Europe,Japan,Asia_Pacific_ex_Japan}_3")`, `Mkt-RF + RF` → 평일 달력 | 1990-07-02 | 예(연구 5·7), 보고(1·2) |
| 뉴스 지수 | `v1.load_news()` | 1900-01 | 아니오 |
| SPY 확인 | `v1.extra_spy` | 1993 | 아니오(스모크에서 부르지 않음) |

FRED 캐시 계열(FEDFUNDS·T10Y2Y·VIX·하이일드 등)은 판정에 쓰지 않는다: 시대 A(1927~1966)를 덮지 못하고, 실행기에서 키·캐시를 확신할 수 없다.

### 자료 출처 — 무디스 스냅숏

- 주소 형식: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=AAA`, `...?id=BAA` (FRED 공개 CSV, 키 불필요). 계열: Moody's Seasoned Aaa / Baa Corporate Bond Yield, 월별, %.
- 만든 스크립트: `build_moodys_snapshot.py`(작업 아님, 실행기·테스트가 부르지 않음). 열 `observation_date` 를 달(YYYY-MM)로 맞춰 합침.
- 받은 날짜: **2026-11-23** · 행 수: **1294**(1919-01 ~ 2026-10) · sha256: `ec1797dc088003cca8ba2a5c4336faf55a2b4d25a1860a71c3ec14e64879acec`
- 스크립트 안 검사: 첫 달 1919-01, 빠진 달 없음, 값 모두 양수, 마지막 달 ≥ 2026-08. 무디스 계열은 개정되지 않는 시장 수익률이라 스냅숏이 곧 실시간 값이다.
- 구현자는 스냅숏을 만든 뒤 어떤 급락 사건 날짜의 값도 들여다보지 않았다. 스모크·테스트는 합성 자료를 쓴다.

## 사건·층

- 사건: v1 과 똑같은 미국 사건 목록(총수익 252일 고점 대비 −15% 첫날, −5% 위로 올라오면 끝, 같은 고점을 공유하면 병합) — `v1.build_episodes` 를 그대로 부른다.
  해외·업종 사건도 같은 정의(`market_context`).
- 미국 층: pre(< 1927-07-01) · **A**(~1966-12-31) · **B**(~2007-12-31) · **C**(~2024-09-30) · X(2024-10-01~, 보고만).
- 해외 층: **I1**(< 2008-01-01) · **I2**(~2024-09-30) · IX(2024-10-01~, 보고만).
- **v1 과 다른 점(결과 전에 정함, 일곱 연구 모두 같게)**: v1 은 A·B 만 판정하고 C(2008~)는 보고만 했다. 이번에는 검정력 때문에 C 를
  판정에 넣는다(합친 n ≈ 14 → ≈ 21, 필요 효과 0.86 sd → 0.66 sd). **C 의 사건들은 이미 crash-cycle-model-v1 보고서에서 본 것이다**
  (사건 목록·회복 기간·기준선 오차). 그래서 통과에는 A·B·C 세 층 각각의 평균이 양수일 것을 함께 요구한다. 2024-10 이후 사건은
  '소진된 구간' 규칙(RESEARCH_JOBS.md 판정 설계 규칙 3)대로 보고만.

## 미래 정보 규칙

- 예측 시점 asof = 발생일 t0(랜드마크 0) 또는 t0 + e 의 종가. 투입(연구 3 모델 3)은 t0 + 1 종가부터.
- 월별 자료: 날짜 t 의 달 m 에서 m−1 달 값까지만.
- 다른 사건을 학습에 쓰려면 asof 날짜까지 확정되어 있어야 한다: 깊이 = `end1_date ≤ asof`, 회복 = `rec_date ≤ asof` 이면 사건, 아니면 asof 에서 중도절단.
  시장이 달라도 날짜로 맞춘다. 같은 날 확정 허용.

## 공통 모델 형식·기준선

- 깊이 = 최종 깊이 FD 분위수 5개(0.10·0.25·0.50·0.75·0.90), 회복 = asof 부터 1·2·3·5년(252·504·756·1260거래일) 안 회복 확률.
- 기준선 BASE: 랜드마크 0 = v1 발생일 기준선(과거 추가 하락 분포를 발생일 깊이로 변환 · KM). 해외 사건의 BASE 는 미국 사건만으로 학습한 같은 계산.
  랜드마크 e > 0 = 깊이 BASE_TRUNC(v1 진행 중 읽기의 분위수를 지금까지 최저로 자름), 회복 = v1 생존 조건 KM.
- 두 갈래 모델(연구 3·4·6): 능형 로지스틱(λ = 4, 표준화 기울기)으로 '긴 약세장(252거래일 안 회복 못 함) 확률' p 를 만들고,
  학습 사건을 라벨 1 → p/π, 0 → (1−p)/(1−π), 라벨 모름 → 1 로 재가중. 기울기가 모두 0 이면 p = π 라 기준선과 같다(내포 관계).
  p 는 [0.05, 0.95] 로 자른다. 분류기 미적합(라벨 있는 학습 6개 미만·한 갈래뿐·미수렴) 사건은 그 연구의 모든 판정에서 빠진다(n_unfit).

## 판정 족 15개 (순서·이름 고정, `lab.FAMILY`)

| 순서 | 키 | 작업 | 비교(모델 vs 기준선) | 점수 |
|---|---|---|---|---|
| 1 | LM_M1 | crash-landmark-v1 | LM_ANCHOR vs BASE_TRUNC (랜드마크) | 평균 핀볼 |
| 2 | LM_M2 | crash-landmark-v1 | LM_SCALED vs BASE (v1 생존 조건 KM, 랜드마크) | 브라이어 |
| 3 | SIM_M1 | crash-simpath-v1 | SIM vs BASE (발생일) | 평균 핀볼 |
| 4 | SIM_M2 | crash-simpath-v1 | SIM vs BASE (발생일) | 브라이어 |
| 5 | MAC_M1 | crash-macro-credit-v1 | MACRO vs BASE | 평균 핀볼 |
| 6 | MAC_M2 | crash-macro-credit-v1 | MACRO vs BASE | 브라이어 |
| 7 | MAC_M3 | crash-macro-credit-v1 | SPLIT_P vs SPLIT_P0 (같은 평균 비율의 고정 분할) | 3년 로그 계좌 차이 D |
| 8 | INT_M1 | crash-internals-v1 | INTERNAL vs BASE | 평균 핀볼 |
| 9 | INT_M2 | crash-internals-v1 | INTERNAL vs BASE | 브라이어 |
| 10 | POOL_M1 | crash-intl-pool-v1 | POOL vs BASE(미국만 학습) | 평균 핀볼 |
| 11 | POOL_M2 | crash-intl-pool-v1 | POOL vs BASE(미국만 학습) | 브라이어 |
| 12 | XFER_M1 | crash-industry-transfer-v1 | XFER vs BASE | 평균 핀볼 |
| 13 | XFER_M2 | crash-industry-transfer-v1 | XFER vs BASE | 브라이어 |
| 14 | RECAL_M1 | crash-recal-v1 | RECAL vs BASE(미국만 학습) | 평균 핀볼 |
| 15 | RECAL_M2 | crash-recal-v1 | RECAL vs BASE(미국만 학습) | 브라이어 |

- 본페로니 α = 0.05/15 = 0.0033333(한쪽). 각 작업은 자기 판정만 계산하지만 같은 α 를 쓴다.
- d = 기준선 점수 − 모델 점수(양수 = 모델이 더 잘 맞힘). 모델 3 은 D3 = ln W_SPLIT_P[756] − ln W_SPLIT_P0[756].
- 미국(`judge_us`): A ≥ 4 · B ≥ 5 · C ≥ 4 · 합친 ≥ 15, 무효 가드(`core.research_power.noop_guard`), A·B·C 평균 모두 양수 + 합친 부호 뒤집기 p < α
  → 통과(모델 1·2 `BEATS_BASELINE`, 모델 3 `BEATS_FIXED_SPLIT`). 그 밖 FAIL(세 평균 모두 양수면 세부 `FAIL_UNDERPOWERED`), 표본 미달·무효 → `NOT_EVALUABLE`.
- 해외(`judge_intl`, 연구 5·7): 동시 급락 군집(앞 사건 발생일과 평일 63일 넘게 떨어지면 새 군집, 군집 값 = 구성 사건 평균, 층 = 첫 사건 날짜) 단위,
  I1 ≥ 3 · I2 ≥ 3 · 합친 ≥ 10, I1·I2 평균 모두 양수 + 합친 p < α.
- 부호 뒤집기는 `v1.signflip_p`(n ≤ 16 정확, 그 위 몬테카를로 200,000회, 검정마다 `default_rng(v1.SEED)`).
- 통과는 '설명 도구로 쓸 근거'까지만 뜻한다. 엔진·아침 메시지·주문은 바뀌지 않는다(사용자 확인 뒤 별도 작업).

## 예측 파일 `predictions.csv` (모든 작업 공통, 26열 고정 = `PRED_COLUMNS`)

`study, model, market, episode_id, t0, era, landmark, asof, n_train, p_lb, d_q10, d_q25, d_q50, d_q75, d_q90, r_252, r_504, r_756, r_1260, a_now,
y_FD, y_depth_settled, y_R_asof, y_recovered, judged_m1, judged_m2`. 실수 소수 6자리, 빈칸 = 없음, 줄 정렬 (market, t0, landmark, model),
250,000 바이트 넘으면 실패. 모델 줄이 있는 모든 (market, episode_id, landmark)에 BASE 줄이 있다. 점수는 `lab.score_row()` 하나로 다시 계산한다
→ 융합 후속 연구가 재학습 없이 섞을 수 있다.

## 스모크

합성 자료만(`lab0.synthetic_data()`, `synthetic_intl()`, `synthetic_rf_monthly()`, `synthetic_moodys()`). 네트워크(SPY·FRED·French)를 부르지 않는다.
