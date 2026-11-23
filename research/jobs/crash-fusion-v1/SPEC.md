# crash-fusion-v1 — 급락 예측 융합: 랜드마크 ⊕ 경로 모의, 깊이 → 회복 두 단계 (사전 등록 2026-11-23)

가설 장부 H-029(parent: crash-landmark-v1). 규칙 버전 `crash-fusion/v1`, 판정 버전 `crash-fusion-judge/v1`, 공용 정의 `research/jobs/crash-cycle-lab/SPEC.md`.
규칙·판정은 결과를 보기 전에 고정했다. 바꾸려면 새 id 로 새로 사전 등록한다.
실행: `python research/jobs/crash-fusion-v1/run.py --out DIR --checkpoint DIR [--smoke]` (종료 코드 0 = 완료; 체크포인트 없음, `resumable: false`).
공용 lab(`research/jobs/crash-cycle-lab/lab.py`)과 기존 작업 파일은 고치지 않는다. 새 함수는 모두 이 작업의 `run.py` 에 있다.

## 사용자 요청

> "예측모델을 더욱 고도화시키는 전략을 opus 5.5 effort extra high가 7개를 만들도록 구현을 medium effort가 진행하도록 해서 각 실험 결과를 확인하고 서로 융합할 수 있는 것이 있다면 그 후속연구까지 진행해줘" (2026-11-23)

이 연구는 마지막 부분(융합 후속)이다.

확정된 결정(2026-11-23, 호출자 확인): 미국 SIMMIX 는 판정하지 않는다(설명용, 판정 4개·홈 족 그대로). 해외 군집을 주 판정 집단으로 하고 3.8 의 '가장 나은 모델' 규칙을 그대로 쓴다. 새 급락의 실시간 예측 기록은 범위 밖이다.

## 결정 요약

| 항목 | 결정 | 이유 |
|---|---|---|
| id·장부 | `crash-fusion-v1`, 장부 **H-029**(다음 빈 번호, origin/main 마지막 H-028), parent `crash-landmark-v1` | |
| 섞는 것 1 | **SIMMIX** = 랜드마크 모델(LM) ⊕ 그 랜드마크 상태에서 출발한 경로 모의(SIM), **같은 비중 0.5/0.5**(깊이 = 분위수 평균, 회복 = 확률 평균) | LM(사건 유사 표본 28개)과 SIM(일별 수익 25,000일·변동성 상태)은 정보원이 다르다. 비중은 고정(적합하지 않음) |
| 섞는 것 2 | **TWOPH** = LM 깊이 모델의 '남은 추가 하락'을 회복 모델에 넣어, 남은 회복 시간 = 바닥까지 시간 + 바닥에서 전고점까지 오르는 시간(바닥 거리에 비례) 두 단계로 나눈 회복 확률 | 회복은 최종 깊이가 정한다(v1). LM_ANCHOR(덧셈형 추가 하락)와 LM_SCALED(전체 시간 비례)의 서로 다른 가정을 한 모형으로 묶는다. 자유 모수 없음 |
| 뺀 것 | 거시·신용(H-022), 시장 내부, 업종 이전, 자기 보정 — 판정에서 뺌. 해외 합치기는 **설명용 LM_POOL** 만. 모델 3(투입) 뺌 | 1 절 |
| 판정 | **4개, 새 족, 홈(Holm) 족 오류율 0.05**: `SIMMIX_M1_INTL`, `SIMMIX_M2_INTL`, `TWOPH_M2_US`, `TWOPH_M2_INTL` | 3.2 절 |
| 비교 대상 | **LM 단독**(깊이 LM_ANCHOR, 회복 LM_SCALED), 같은 (사건, 랜드마크) 쌍에서 같은 함수로 다시 계산. v1 기준선 대비는 **설명용** | LM 대 v1 기준선은 이미 모든 미국 사건·해외 군집에서 보았다 → 다시 '확인'할 수 없다 |
| 판정 집단 | SIMMIX = **해외 군집만**(미국은 설명용). TWOPH = **미국 사건 + 해외 군집** | 미국에서 SIMMIX 대 LM 합친 평균의 부호는 공개 결과 + 볼록성으로 이미 정해져 있다(3.6 절). 해외 랜드마크의 SIM 은 계산된 적이 없다 |
| 랜드마크 | 21·63·126 그대로(공용 상수 `lab.LANDMARKS`). 63·126 만의 값은 견고성(보고만) | 사전 논리(3.6.3 절) |
| 층 | 미국 A·B·C(사건 단위, 세 평균 양수), 해외 I1·I2(군집 단위, 두 평균 양수). 2024-10 이후 발생 사건은 보고만 | 7연구와 같은 규칙 |
| 검정력 | Holm 첫 문턱 0.0125 에서 필요 효과 미국 n=21 **0.53 sd**, 해외 SIMMIX 24 군집 **0.49 sd**, 해외 TWOPH 27 군집 **0.46 sd** | 3.4 절. 참고: LM 자신이 v1 기준선 대비 보인 크기는 약 0.4 sd 였다 |
| 사전 기대 | 4개 모두 FAIL 가능성이 높다(통과 7~15%) | 3.5 절 |
| 통과의 뜻 | 설명 도구(급락 중 읽기)로 쓸 후보까지. **엔진·아침 메시지·주문은 바뀌지 않는다** | |

## 7연구 결과 요지

| 연구 | 판정(α = 0.05/15) | 평균 d (층별) · p | 융합 |
|---|---|---|---|
| crash-landmark-v1 | LM_M1 FAIL_UNDERPOWERED · LM_M2 FAIL_UNDERPOWERED | 깊이 +0.0038/+0.0029/+0.0064 (A/B/C), p 0.0295 · 회복 +0.0574/+0.0119/+0.0320, p 0.0429. 이득은 63·126 에서(21: 깊이 +0.0013 p 0.25, 회복 −0.0035 p 0.58). 해외 재현(보고): 깊이 p 0.035, 회복 p 0.17. 63 의 1년 회복 예측 66% vs 실제 67%(BASE 51%) | **들어감**(모든 변형의 바탕이자 비교 대상) |
| crash-simpath-v1 | SIM_M1 FAIL · SIM_M2 FAIL | 발생일: 깊이 +0.0183/−0.0039/+0.0009 p 0.28, 회복 +0.0834/−0.0015/−0.0042 p 0.14(시대 A 가 끌어올림). **랜드마크(보고만) SIM vs 같은 BASE**: 깊이 +0.0041/+0.0054/+0.0019(21/63/126), 회복 +0.0117/+0.0466/+0.0721(p 0.29/0.044/0.022) | **들어감**(SIMMIX). 발생일 실패는 '발생일 정보'의 실패이고, 랜드마크 상태에서 출발한 모의는 LM 과 같은 '발생 뒤 경로' 정보를 다른 방식(일별 수익)으로 쓴다 |
| crash-macro-credit-v1 | 3개 FAIL | 깊이 p 0.84, 회복 p 0.82, 분할 p 0.38. 분류 실력: 브라이어 p_lb 0.334 vs 기준 확률 π 0.303(더 나쁨). 미적합 6개 | **빠짐**. p_lb 에 실력이 없어 LM 유사 사건 재가중은 잡음만 더한다. 발생일 정보 |
| crash-internals-v1 | 2개 FAIL | 깊이 p 0.99, 회복 p 0.98(기준선보다 나쁨). 분류 실력 0.337 vs 0.303 | **빠짐**. 기준선보다 나빴고 실력 없음. 구체적 기전 없음 |
| crash-intl-pool-v1 | 2개 FAIL | 해외 군집: 깊이 p 0.50, 회복 p 0.67(차이 거의 0) | **판정에서 빠짐, 설명용 LM_POOL 만**. 기전(뒤 랜드마크의 작은 유사 표본을 키움)은 있으나 ① 발생일에서 이득 0, ② 미국 시대 A·B(1992 이전)는 정의상 LM 과 같아 미국 판정의 '세 시대 양수'를 원리적으로 못 채우고, ③ 해외 군집은 이 연구의 깨끗한 판정 집단이라 그 사건을 판정 변형의 학습에 넣지 않는다 |
| crash-industry-transfer-v1 | 2개 FAIL | 회복 +0.0028/+0.0013/+0.0016 p 0.38(무시할 크기), 깊이 음수. 분류 실력 0.266 vs 0.281 | **빠짐**. 크기가 무시할 만하고 랜드마크에서 쓸 기전이 없다 |
| crash-recal-v1 | 2개 FAIL | 해외 군집: 깊이 p 0.97, 회복 p 0.97(더 나쁨) | **빠짐**. 더 나빴고, 처방 자체가 v1 보정 실패를 보고 고른 것. LM 의 63 보정은 이미 맞았다(66% vs 67%) |

공통 결론: **발생일 정보는 종류를 바꿔도 다시 실패했고, 발생 뒤 경로(랜드마크)만 세 시대 모두 같은 방향이었다.** 그래서 두 융합 모두 '발생 뒤 경로' 위에 쌓는다.

## 무엇을 섞고 무엇을 뺐나

위 표의 '융합' 열이 섞은 것과 뺀 것이다.

### 모델 3(투입 결정)을 뺀 이유

랜드마크 정보로 투입을 정하는 규칙은 어떤 형태로 짜도 '급락이 진행되는 중(발생 뒤 e 일)에 그때까지의 경로를 보고 얼마를 넣을지 정하는 것' = **급락 중 매수 시점 신호**다. 이것은 선언된 막다른 길(crash-rebound-signal-v1 사후 분석: "급락 중 가격·변동성·뉴스 기반 매수 시점 신호", crash-cycle-model-v1 사후 분석: "달력 고정 분할 투입으로 수익 내기")에 그대로 들어간다.
발생일에 한 번 정하는 분할(MAC_M3)도 p 0.38 로 실패했고 그 입력(p_lb)에는 실력이 없었다. 깨끗하게 짤 방법이 없으므로 **모델 3 은 넣지 않는다.**

### LM ⊕ BASE(기준선 쪽으로 줄이기)를 판정하지 않는 이유

BASE 는 LM 보다 정보가 적은 같은 계열(지금 깊이를 모름)이다. 섞기는 '줄이기(shrinkage)'만 시험하고, LM 이 BASE 보다 평균적으로 나았다는 것(본 결과)을 알기 때문에 기대가 음수 쪽이다. **설명용 `LMB`** 로만 계산한다.

## 자료

1. 미국: `data = lab.load_us(smoke)` → `ctx = lab.us_context(data)` → `us = ctx["recs"]`(v1 과 같은 28개 사건, 마지막 2025-04-04 는 층 X).
2. 해외: `intl = lab.load_intl(smoke, required=True)`(판정 자료 — 한 지역이라도 못 받으면 `RuntimeError`, 실행기 재시도. VM 캐시 있음).
   `ictx = {k: lab.market_context(intl[k], k) for k in lab.INTL_REGIONS}`, `intl_recs = [r for k in lab.INTL_REGIONS for r in ictx[k]["eps"]]`, `all_recs = us + intl_recs`.
3. 대상: 미국 사건 전부와 해외 사건 전부(층 무관하게 계산·저장, 판정은 층 A·B·C / I1·I2 만).
4. 쌍: 대상 r 과 e ∈ `lab.LANDMARKS` = (21, 63, 126). `st = lab.landmark_state(r, e)` 가 None(자료 끝을 넘거나 이미 회복)이면 그 쌍은 없다.
   있으면 `st["x_raw"] = math.log(r["P"] / r["_Lv"][st["tau"]])`(바닥 거리 계산용, 하한 없음)를 더한다.
5. 학습 집합(날짜 기준, 공용 규칙): BASE·LM·TWOPH 는 **미국 사건 `us`** 로만(대상이 해외여도 — crash-landmark-v1 의 해외 재현과 같음). LM_POOL 만 `all_recs`. SIM 은 대상 시장 자기 일별 수익(asof 종가까지).

## 변형

### 2.2 기준 LM 과 기준선 BASE (다시 계산, 기존 함수 그대로)

- `B = lab.landmark_base(us, r, e)` → **BASE** = (깊이 `B["m1_trunc"]`, 회복 `B["m2"]`) — crash-landmark-v1 의 BASE 줄과 같은 값.
- `M = lab.landmark_lm(us, r, e)` → **LM** = (깊이 `M["m1"]` = LM_ANCHOR, 회복 `M["m2"]` = LM_SCALED) — crash-landmark-v1 의 LM 줄과 같은 값.

### 2.3 SIM — 랜드마크 상태에서 출발한 경로 모의 (구성 요소, 기존 함수 그대로)

`S = lab.simulate(r["_Lv"], r["market"], r["P"], st["tau"], st["m"], e, n_paths)`, `n_paths = lab.N_SIM_SMOKE(400) if smoke else lab.N_SIM(4000)`.
`st["tau"] < lab.SIM_MIN_HIST(756)` 이면 None(해외 1993-05 무렵 이전 asof). 반환 `S["q"]`(깊이 분위수, 키 "0.1"…"0.9"), `S["F"]`(asof 부터 h 안 회복 확률, 키 int), `S["vol_now"]`.
seed 는 lab 이 정한다(`default_rng([lab.SEED, MARKET_CODE[market], tau])`) → 미국 랜드마크의 SIM 은 crash-simpath-v1 의 랜드마크 SIM 줄과 같은 값.

### 2.4 SIMMIX — LM ⊕ SIM 같은 비중

```python
W_MIX = 0.5
QK = ("0.1", "0.25", "0.5", "0.75", "0.9")

def mix_q(qa, qb, w=W_MIX):
    """분위수 평균(Vincentization). 둘 중 하나라도 None 이면 None. {k: w*qa[k] + (1-w)*qb[k] for k in QK}"""

def mix_F(Fa, Fb, w=W_MIX):
    """확률 평균(선형 의견 풀). 하나라도 None 이면 None. {h: w*Fa[h] + (1-w)*Fb[h] for h in lab.HZ}(키 int; 입력이 str 키여도 int h 로 읽는다)"""
```

1. SIMMIX 깊이 = `mix_q(M["m1"], S["q"] if S else None)`. 두 입력 모두 ≤ m 이고 q 에 대해 오름차순이므로 결과도 그렇다(별도 처리 없음).
2. SIMMIX 회복 = `mix_F(M["m2"], S["F"] if S else None)`. 두 입력 모두 h 에 대해 줄지 않으므로 결과도 그렇다.
3. 대비책 없음: 한쪽이 없으면 SIMMIX 도 없다(그 쌍은 SIMMIX 판정에서 빠진다). LM 으로 대신 채우지 않는다.

근거: 같은 비중 결합은 작은 표본에서 추정 비중보다 잘 맞는 경우가 많고(Clemen 1989, Smith & Wallis 2009 '결합 퍼즐'), 분위수 평균은 핀볼 손실이 두 손실 평균 이하다(Lichtendahl·Grushka-Cockayne·Winkler 2013). 비중 0.5 는 결과 전에 고정하며 격자를 시험하지 않는다.

### 2.5 TWOPH — 깊이 → 회복 두 단계

생각: 지금(랜드마크)부터 회복까지 = **바닥까지 걸리는 시간 Δ** + **바닥에서 전고점까지 오르는 시간 U**. 표류 있는 무작위 보행에서 U 의 평균은 바닥 거리에 비례한다(첫 도달 시간 = 거리/표류 — LM_SCALED 와 같은 선험 관계). 바닥이 얼마나 더 낮아질지(y)와 그때까지 시간(Δ)은 LM_ANCHOR 와 **같은 유사 사건**에서 짝으로 가져온다.

```python
def x_raw_of(st) -> float:
    """st["x_raw"] 가 있으면 그것, 없으면 -math.log(1 + st["d"]) (조견표의 가상 상태)."""

def twoph_analog(j, e, D):
    """유사 사건 j 하나의 (delta, y, x_tr, U, ev). lab.alive_at(j, e) 가 아니거나 s > j["end1"] 이면 None.
    1) s = j["t0"] + e;  seg = j["_Lv"][s : j["end1"] + 1];  k = int(np.argmin(seg))   (같은 값이면 첫 위치);  tau = s + k
    2) delta = k                                   (랜드마크에서 남은 바닥까지 거래일)
    3) y = math.log(seg[k] / j["_Lv"][s])          (≤ 0, = lab.yrem(j, e))
    4) x_tr = max(math.log(j["P"] / seg[k]), lab.X_FLOOR)   (남은 바닥의 전고점까지 로그 거리)
    5) j["rec_date"] is not None and j["rec_date"] <= D  →  U = j["rec"] - tau, ev = 1
       그 밖                                          →  U = lab.pos_le(j["_idx"], D) - tau, ev = 0   (D 에서 중도절단)"""

def twoph_from_arrays(delta, y, U, ev, x_tr, x_raw, hs=lab.HZ) -> dict:
    """1) W = U / x_tr  (오르는 시간을 바닥 거리 1 단위로 맞춤)
    2) tauW, SW = v1.wkm(W, ev)                     (v1 = lab.v1(); 보통 KM)
    3) h ∈ hs 마다: F(h) = (1/n) Σ_k g_k(h),  u_k = h − delta[k]
          u_k ≤ 0  →  g_k = 0
          그 밖    →  g_k = 1 − v1.surv_at(tauW, SW, u_k / max(x_raw − y[k], lab.X_FLOOR))
    4) 반환 {h: float(F(h))}  (h 에 대해 줄지 않음 — 각 g_k 가 그렇다)"""

def twoph_from_state(train_recs, st, e) -> Optional[dict]:
    """D = st["asof"].
    1) A = [j for j in lab.m1_pool(train_recs, D) if lab.alive_at(j, e)]   ← LM_ANCHOR 의 T1L 과 같은 유사 사건
    2) 각 j 에 twoph_analog(j, e, D); None 인 것은 버린다(e > 756 일 때만 생김).
    3) 남은 수 < lab.MIN_TRAIN(6) 또는 Σev < lab.MIN_EVENTS_M2(3) → None.
    4) 반환 {"m2": twoph_from_arrays(..., x_raw_of(st)), "n": 남은 수, "n_events": Σev}"""

def twoph(train_recs, r, e) -> Optional[dict]:
    """st = lab.landmark_state(r, e) (None → None); st["x_raw"] = math.log(r["P"] / r["_Lv"][st["tau"]]); twoph_from_state(train_recs, st, e)."""
```

성질(테스트로 확인): 모든 유사 사건이 랜드마크 뒤 더 빠지지 않고(Δ = 0, y = 0) D 까지 회복했으면 TWOPH = LM_SCALED(정확히) — 즉 TWOPH 는 LM_SCALED 를 품고, 다른 점은 '랜드마크 뒤 더 빠진 유사 사건'을 두 단계로 다루는 것뿐이다.
TWOPH 는 깊이 예측이 없다(깊이 칸 빈칸).

### 2.6 설명용 모델 (판정 없음)

- **LMB** = (`mix_q(M["m1"], B["m1_trunc"])`, `mix_F(M["m2"], B["m2"])`) — LM 을 v1 기준선 쪽으로 반 줄인 것.
- **LM_POOL** = `lab.landmark_lm(all_recs, r, e)` — 미국 + 해외 사건으로 학습한 LM(대상 자신은 날짜 조건으로 빠짐). 1992 이전 미국 대상은 LM 과 같다(개수 보고).
- **SIM**(단독) — 2.3.

### 2.7 쌍 하나의 계산 `pair_calc(us, all_recs, r, e, n_paths) -> Optional[dict]`

1. st(2.1 의 4), B, M, S, SIMMIX, TWOPH(`twoph_from_state(us, st, e)`), LMB, LM_POOL 을 위 순서로 만든다.
2. 예측 사전 `pred = {"BASE": (B["m1_trunc"], B["m2"]), "LM": (M["m1"], M["m2"]), "SIM": (S["q"], S["F"]) 또는 (None, None), "SIMMIX": (...), "TWOPH": (None, T["m2"] 또는 None), "LMB": (...), "LM_POOL": (P["m1"], P["m2"])}`.
3. 점수: `r["depth_settled"]` 이면 깊이 예측이 있는 모델마다 `s1[name] = lab.score_m1(r["FD"], q)`. `r["R"] is not None` 이면 회복 예측이 있는 모델마다 `s2[name] = lab.score_m2(r["R"] − e, F)`.
4. 쌍 차이(없으면 None):
   - 판정량: `q["SIMMIX_M1"] = s1["LM"] − s1["SIMMIX"]`, `q["SIMMIX_M2"] = s2["LM"] − s2["SIMMIX"]`, `q["TWOPH_M2"] = s2["LM"] − s2["TWOPH"]`.
   - 설명량: `q["SIM_M1"]`, `q["SIM_M2"]`, `q["LMB_M1"]`, `q["LMB_M2"]`, `q["LMPOOL_M1"]`, `q["LMPOOL_M2"]` = LM 점수 − 그 모델 점수;
     `q["B_<모델>_M1"]` = s1["BASE"] − s1[모델] (모델 ∈ LM, SIM, SIMMIX, LMB, LM_POOL), `q["B_<모델>_M2"]` = s2["BASE"] − s2[모델] (모델 ∈ LM, SIM, SIMMIX, TWOPH, LMB, LM_POOL).
5. 반환 `{"e", "st", "B", "M", "S", "T", "pred", "s1", "s2", "q"}`.

`episode_calc(us, all_recs, r, n_paths)`: e ∈ LANDMARKS 마다 pair_calc(None 은 건너뜀) → `{"r": r, "pairs": {e: pair}, "val": {Q: 있는 랜드마크 q[Q] 의 단순 평균 또는 None}}` (Q = 4 의 모든 이름).
**사건 값 = 있는 랜드마크의 단순 평균**(crash-landmark-v1 과 같음 — 같은 사건의 랜드마크끼리는 독립이 아니다).

### 사전 등록 상수 (run.py)

```python
STUDY = "crash-fusion-v1"
RULES_VERSION = "crash-fusion/v1"
JUDGE_VERSION = "crash-fusion-judge/v1"
KEYS = ("SIMMIX_M1_INTL", "SIMMIX_M2_INTL", "TWOPH_M2_US", "TWOPH_M2_INTL")   # 순서 고정(같은 p 의 순위 결정에도 씀)
K = 4
FAMILY_ALPHA = 0.05
PASS_LABEL = "BEATS_LANDMARK"
LABELS = ("BEATS_LANDMARK", "FAIL", "NOT_EVALUABLE")
VERDICT_SPEC = {"SIMMIX_M1_INTL": ("SIMMIX_M1", "INTL"), "SIMMIX_M2_INTL": ("SIMMIX_M2", "INTL"),
                "TWOPH_M2_US": ("TWOPH_M2", "US"), "TWOPH_M2_INTL": ("TWOPH_M2", "INTL")}
DESCRIPTIVE_US = ("SIMMIX_M1", "SIMMIX_M2")       # 미국 SIMMIX — 판정 아님(3.6 절)
W_MIX = 0.5
GRID_E = (21, 63, 126)                             # = lab.LANDMARKS (조견표)
GRID_D = (-0.05, -0.10, -0.15, -0.20, -0.25, -0.30, -0.40)
GRID_DD0 = -0.15
ROBUST_LANDMARKS = (63, 126)                       # 견고성(보고만)
JSON_MAX_BYTES = 230_000                           # results.json 크기 대비책 문턱(4.1)
MODEL_NAMES = {"SIMMIX_M1_INTL": "SIMMIX vs LM_ANCHOR (깊이, 해외 군집)",
               "SIMMIX_M2_INTL": "SIMMIX vs LM_SCALED (회복, 해외 군집)",
               "TWOPH_M2_US": "TWOPH vs LM_SCALED (회복, 미국 사건)",
               "TWOPH_M2_INTL": "TWOPH vs LM_SCALED (회복, 해외 군집)"}
```

lab 상수는 다시 정의하지 않고 이름으로 쓴다: `lab.LANDMARKS, lab.HZ, lab.Q, lab.MIN_TRAIN, lab.MIN_EVENTS_M2, lab.X_FLOOR, lab.N_SIM, lab.N_SIM_SMOKE, lab.SIM_MIN_HIST, lab.H, lab.SEED, lab.US_STRATA, lab.INTL_STRATA, lab.MIN_N_US, lab.MIN_N_INTL, lab.CLUSTER_GAP, lab.HOLDOUT_START, lab.READING_HEADER, lab.PRED_COLUMNS, lab.YEARS_US, lab.YEARS_INTL`.

## 판정

### 3.1 평가 집합

- **쌍이 판정량 Q 에 들어가는 조건**: 대상의 결과를 알고(깊이 = `depth_settled`, 회복 = `R is not None`) LM 과 변형의 예측이 **둘 다** 있다. LM 의 점수는 바로 그 쌍에서 쓴다(같은 쌍 비교).
- **사건 값** = 2.7 의 `val[Q]`. 하나도 없으면 그 사건은 Q 에서 빠진다.
- 미국 판정: 층 A·B·C 사건의 값 → `dmap = {s: [...]}`.
- 해외 판정: 층 I1·I2 사건의 (사건, 값) → `lab.intl_verdict(pairs, PASS_LABEL)` 안에서 `lab.clusters`(평일 63일 넘게 떨어지면 새 군집, 군집 값 = 구성 사건 값 평균, 군집 층 = 첫 사건 날짜의 층).
- 층 X(미국 2025-04-04, 랜드마크 21 만)·IX(해외 2개)는 계산·저장만, 판정 밖.

### 3.2 판정 4개

| 순서 | 키 | 변형 vs 기준 | 점수 | 집단·단위 | 예상 n |
|---|---|---|---|---|---|
| 1 | `SIMMIX_M1_INTL` | SIMMIX 깊이 vs LM_ANCHOR | 평균 핀볼(분위수 5개) | 해외 3지역 군집 I1·I2 | 사건 38 · 군집 24 (I1 12 · I2 12) |
| 2 | `SIMMIX_M2_INTL` | SIMMIX 회복 vs LM_SCALED | 브라이어(1·2·3·5년 평균) | 해외 군집 | 사건 38 · 군집 24 (12 · 12) |
| 3 | `TWOPH_M2_US` | TWOPH 회복 vs LM_SCALED | 브라이어 | 미국 사건 A·B·C | 21 (A 5 · B 9 · C 7) |
| 4 | `TWOPH_M2_INTL` | TWOPH 회복 vs LM_SCALED | 브라이어 | 해외 군집 | 사건 43 · 군집 27 (15 · 12) |

d = **LM 점수 − 변형 점수**(양수 = 변형이 더 잘 맞힘). 예상 n 은 crash-landmark-v1 predictions.csv 의 LM 줄(날짜·층·값 유무)로 센 값이다. 해외 SIMMIX 는 SIM 이 지역 자기 이력 756일을 요구해 asof 가 1993-05 무렵 이전인 쌍이 빠진다(43 → 38 사건). TWOPH 의 예상 n 은 LM 과 같다고 보았다(유사 사건 조건이 LM_ANCHOR 와 같음).

### 3.3 검정·홈 절차·라벨 (`judge_all`)

1. 각 키: 미국은 `raw = lab.judge_us(dmap, PASS_LABEL)`, 해외는 `raw, cl = lab.intl_verdict(pairs, PASS_LABEL)`.
   이 함수들의 **표본 조건·무효 가드·층별 평균·한쪽 부호 뒤집기 p(`v1.signflip_p`, n ≤ 16 정확, 그 위 몬테카를로 200,000회)만** 쓴다.
   `raw["verdict"]` 는 7연구의 α = 0.05/15 로 붙은 값이므로 **버린다**(detail 에 넣지 않는다).
2. `det = {"population": "US"|"INTL", "compare": MODEL_NAMES[key], "n": raw["n"], "mean": raw["mean"], "p": raw["p"], "p_method": raw["p_method"], "t": raw["t"], "p_t": raw["p_t"]}`;
   `det["evaluable"] = raw["p"] is not None`; 아니면 `det["reason"] = raw["reason"]`(표본 부족·무효 가드 사유).
   `det["allpos"] = evaluable and 모든 층(미국 A·B·C / 해외 I1·I2) 평균 > 0`. 해외는 `n_episodes`, `p_episode`, 군집 목록(`{"first","stratum","members","value"}`)도 넣는다.
3. 홈 절차(K = 4 고정 — 평가 불가 키가 있어도 K 를 줄이지 않는다):
   - 평가 가능한 키를 (p, KEYS 안 순서)로 오름차순 정렬. 순위 i = 1, 2, … 의 문턱 = `FAMILY_ALPHA / (K − i + 1)` → 0.0125, 0.016667, 0.025, 0.05.
   - 앞에서부터 `p < 문턱` 이면 '홈 기각', 처음으로 아닌 순위에서 멈추고 그 뒤는 모두 기각 아님.
   - 방향 조건(`allpos`)은 기각 순서에 영향을 주지 않는다(기각됐지만 방향이 어긋난 키가 있어도 다음 순위로 진행). 통과를 줄이기만 하므로 족 오류율 0.05 는 그대로 지켜진다.
   - 각 키에 `holm_rank`, `holm_threshold`, `holm_reject` 를 기록(평가 불가 = None·None·False).
4. 라벨: 평가 불가 → `NOT_EVALUABLE`; 홈 기각이고 allpos → `BEATS_LANDMARK`; 그 밖 → `FAIL`,
   `fail_kind` = allpos 이면 `FAIL_UNDERPOWERED`(사유 "홈 문턱 미달") 아니면 `FAIL`(사유 "층 방향 불일치(평균 음수 층 있음)").
5. 7연구 족(15개, 0.05/15)과 **별개의 새 족**이다. 급락 연구 전체(15 + 4)를 묶은 보정은 하지 않는다 — 한계로 적는다.

## 검정력·사전 기대

### 3.4 검정력 (사전 계산, 정규 근사·t 임계값 = `lab.v1()._cr().t_crit`)

`power_holm(n)` → `{"n", "needed_effect_sd": {"first": t_crit(0.05/4, n−1)/√n, "last": t_crit(0.05, n−1)/√n}, "min_p": 2**−n, "pass_prob_first": {δ: 1 − Φ(z_{1−0.0125} − δ√n) for δ in (0.2, 0.3, 0.5, 0.8)}}`; n < 2 이면 수치 None.

| n | 첫 문턱(0.0125) 필요 효과 | 통과 확률 δ 0.2 / 0.3 / 0.5 / 0.8 | 마지막 문턱(0.05) 필요 효과 |
|---|---|---|---|
| 21 (TWOPH 미국) | 0.529 sd | 9% / 19% / 52% / 92% | 0.376 sd |
| 24 (SIMMIX 해외 군집) | 0.489 sd | 10% / 22% / 58% / 95% | 0.350 sd |
| 27 (TWOPH 해외 군집) | 0.458 sd | 11% / 25% / 64% / 97% | 0.328 sd |

- 표본 조건(미국 A ≥ 4·B ≥ 5·C ≥ 4·합친 ≥ 15, 해외 I1 ≥ 3·I2 ≥ 3·합친 ≥ 10)은 예상 n 보다 충분히 낮다 → 네 판정 모두 평가 가능하다(평가 불가가 구조적으로 예상되는 변형은 등록하지 않았다).
- 참고(본 결과): LM 이 v1 기준선 대비 보인 효과는 약 0.4 sd(n 21 에서 p 0.03·0.04)였다. 변형 대 LM 의 효과는 대개 그보다 작을 것이라 **중간 크기 이하의 이득은 원리적으로 못 잡는다. FAIL 은 '효과 없음'의 증명이 아니다.**
- `results.json["power"] = rp.power_report(lab.YEARS_US, K)`, `["power_intl"] = rp.power_report(lab.YEARS_INTL, K)`(판정 설계 규칙 1).

### 3.5 사전 기대 (`EXPECTED`, results·REPORT 에 그대로)

```python
EXPECTED = {
 "SIMMIX_M1_INTL": "FAIL 가능성이 높다(통과 약 12%). 두 깊이 예측이 같은 상태(지금 수준·지금까지 최저)에서 출발하고, 분위수 평균은 핀볼 손실을 크게 줄이지 않는다. 해외 지역 일별 이력이 짧아(1990~) 모의의 표류·변동성 추정이 거칠다.",
 "SIMMIX_M2_INTL": "FAIL 가능성이 높다(통과 약 15%). 모의 회복 확률은 지역 자기 표류에서 나와 사건 유사 표본(LM)과 오차가 덜 겹치면 섞기가 도울 수 있다. 그러나 발생일 모의의 해외 성적은 I1 양수·I2 음수로 엇갈렸다.",
 "TWOPH_M2_US": "FAIL 가능성이 높다(통과 약 8%). 같은 유사 사건의 정보를 다르게 나눌 뿐이고, 깊이가 확정된 사건만 쓰므로 LM_SCALED 보다 유사 사건이 조금 적다. 63·126 에서는 대부분의 유사 사건이 이미 바닥을 지나 LM_SCALED 와 거의 같아진다.",
 "TWOPH_M2_INTL": "FAIL 가능성이 높다(통과 약 7%). 미국 유사 사건의 '바닥까지 시간'과 '오르는 속도'를 USD 기준 해외 사건에 옮긴다. 해외 회복 속도가 미국과 다르면 두 단계 분해의 이득이 묻힌다.",
}
```

넷 중 하나라도 통과할 확률은 대략 25~35%(판정끼리 독립이 아니어서 대략)로 본다.

## 이미 본 것과 그 영향(편향 진술)

#### 3.6.1 이미 본 것

1. 미국 사건 28개의 실제 결과(최종 깊이·회복)는 v1 부터 모두 보았다.
2. 미국 랜드마크 쌍의 **LM 대 BASE**: 랜드마크·층별 평균 점수와 보정표(crash-landmark-v1 REPORT), 사건·랜드마크별 점수(results.json `episodes[].landmarks`), 예측 전부(predictions.csv).
3. 미국 랜드마크 쌍의 **SIM(그 시점 상태에서 출발) 대 같은 BASE**: 랜드마크별 합친 평균·p(crash-simpath-v1 REPORT 견고성 절), 사건·랜드마크별 d(results.json), 예측 전부(predictions.csv).
   → 두 비교의 BASE 가 같으므로 **미국에서는 쌍마다 SIM 대 LM 점수 차를 공개 파일에서 바로 뺄 수 있다.** 설계자는 계산하지 않았다. 그러나 설계자가 읽은 REPORT 의 랜드마크별 합친 평균만으로도 21·63 에서(평가 쌍 21개가 같음) SIM 이 LM 보다 회복은 평균 약 +0.015·+0.006, 깊이는 약 +0.003·+0.0003 잘 맞혔다는 것이 나온다(126 은 평가 쌍이 하나 달라 근사: 회복 약 +0.03, 깊이 약 −0.004).
   브라이어 점수와 핀볼 손실은 예측에 대해 볼록하므로 쌍마다 `점수(SIMMIX) ≤ ½(점수(LM) + 점수(SIM))`, 즉 SIMMIX 의 LM 대비 이득 ≥ ½ × (SIM 의 LM 대비 이득)이다. 따라서 **미국에서 SIMMIX 대 LM 의 합친 평균은 계산 전에 사실상 양수로 정해져 있다**(회복 하한 약 +0.007, 깊이 하한 약 0). 미국 SIMMIX 를 판정하지 않고 설명용으로 내린 이유다.
4. 해외 군집: **LM(미국 학습) 대 BASE** 의 반쪽별 평균·p(깊이 I1 +0.0042·I2 +0.0005, p 0.035; 회복 I1 +0.0056·I2 +0.0118, p 0.17), 사건별 값(results.json — 랜드마크별 해외 값은 REPORT 에 없고 설계자는 파일에서 보지 않았다).
   해외 SIM 은 **발생일에서만** 계산되었다(대 BASE: 깊이 I1 +0.0065·I2 −0.0052, 회복 I1 +0.0562·I2 −0.0189). **해외 랜드마크의 SIM 은 어디서도 계산된 적이 없다** → 해외 SIMMIX 대 LM 은 공개 정보로 정해지지 않는다.
5. **TWOPH 는 어디서도 계산된 적이 없다.** 그러나 그 재료(LM_ANCHOR 의 유사 사건·남은 추가 하락)와 비교 대상(LM_SCALED)의 성적은 보았다: LM_SCALED 는 21 에서 1년 회복을 덜 예측했고(47% vs 실제 67%) 63 에서는 맞았다(66% vs 67%), 63 의 3년은 더 예측했다(88% vs 81%).
   이 보정 양상을 아는 것이 '두 단계' 구조를 고르는 데 영향을 줄 수 있었다. 설계자는 TWOPH 가 이 양상을 어느 쪽으로 바꿀지 계산하지 않았고 알지 못한다. 두 단계 구조는 첫 도달 시간 논리에서 나왔고 자유 모수가 없다(X_FLOOR 는 v1 의 −5% 종료 문턱 그대로).
6. **변형 선택 자체가 결과를 보고 한 것이다**(융합 연구의 본성): 일곱 중 성적이 가장 좋았던 둘(LM·SIM)을 골랐다. 공개 성적의 일부는 우연(승자의 저주)이라 기대보다 약하게 나올 수 있다. 비교 대상이 LM 이므로 LM 선택의 영향은 양쪽에서 상쇄되지만, SIM 은 미국 랜드마크 성적을 보고 골랐다 → SIMMIX 를 해외에서만 판정한다.
7. 2024-10 이후 사건(미국 2025-04, 해외 2개)은 여러 연구가 이미 봤다 → 보고만.

#### 3.6.2 판정이 말할 수 있는 것과 없는 것

- **통과가 뜻하는 것**: "1991~2024-09 해외 3지역 군집(USD) / 1946~2024-09 미국 사건에서, 그 변형이 LM 단독보다 표본 밖 점수가 우연 이상으로, 두 반쪽(세 시대) 모두에서 같은 방향으로 나았다." 설명 도구 후보·앞으로 생길 급락에서 기록해 볼 후보까지.
- **말할 수 없는 것**: LM(또는 융합)이 v1 기준선보다 낫다는 확인(본 자료 — 설명용 값만), 미국에서의 SIMMIX 이득(부호가 미리 정해짐), 수익·투입 시점, 앞으로의 급락에서의 성능, 엔진·주문 변경.
- **FAIL**: 효과 없음의 증명이 아니다(필요 효과 0.46~0.53 sd).
- 진짜로 손대지 않은 자료는 **앞으로 생길 급락**뿐이다(판정 설계 규칙 3 의 '전진 원장' 정신). 이 연구는 그 자리를 대신하지 못한다.

#### 3.6.3 랜드마크 21 — 남긴다 (사전 논리)

1. `LANDMARKS = (21, 63, 126)` 는 공용 상수이고, '같은 (사건, 랜드마크) 쌍에서 LM 단독 대비'라는 질문은 crash-landmark-v1 의 사건 값(랜드마크 평균) 정의를 그대로 써야 성립한다.
2. 융합의 목적은 LM 이 쓰이는 모든 시점에서 예측을 낫게 하는 것이다. 발생 뒤 1개월도 사용자가 읽는 시점이다.
3. 21 에서 LM 의 이득이 없었다는 것(본 결과)을 이유로 빼면 결과를 보고 고르는 것이 된다.
4. 공개(선언된 한계): 미국에서는 21 에서 SIM 이 LM 보다 회복을 가장 크게 앞섰다(약 +0.015) — 21 을 남기는 것은 미국 SIMMIX 값에 유리하다. 이것도 미국 SIMMIX 를 판정하지 않는 이유 중 하나다. 해외 판정과 TWOPH 에는 21 의 방향을 알려 주는 공개 정보가 없다.
5. 63·126 만으로 다시 계산한 값을 견고성 절에 보고한다(라벨 없음).

## 설명용 비교·견고성

공통 요약 함수 `summ(values, pop)`:
- 미국: 층 A·B·C 사건 값 목록 → `{"n": {A,B,C,pooled}, "mean": {A,B,C,pooled}, "p": lab.signflip(합친 값)}`.
- 해외: `cl = lab.clusters([(r["t0_date"], v, r["id"]) for I1·I2 사건])` → `{"n_episodes", "n_clusters", "mean": {I1, I2, pooled(군집 값 평균)}, "p_cluster": lab.signflip(군집 값)}`.

1. **v1 기준선 대비(설명용 — 이미 본 자료)**: 모델 ∈ {LM, SIM, SIMMIX, TWOPH(회복만), LMB, LM_POOL}, 깊이·회복, `summ(val["B_<모델>_M1/M2"], 미국/해외)`.
   LM 의 미국 값은 crash-landmark-v1 의 LM_M1·LM_M2(평균 +0.0043·+0.0295, p 0.0295·0.0429)를 재현해야 한다(4.1 `checks.published_check`).
2. **미국 SIMMIX(설명용)**: `summ(val["SIMMIX_M1"], "US")`, `summ(val["SIMMIX_M2"], "US")` + 볼록성 하한 `bound = ½ × mean(val["SIM_M1"/"SIM_M2"])`(같은 사건들의 합친 평균). REPORT 문구: "합친 평균의 부호는 볼록성 때문에 계산 전에 정해져 있으므로 근거로 쓰지 않는다. 시대별 부호는 참고."
3. **SIM 단독 vs LM**, **LMB vs LM**: 미국·해외 각각 `summ`.
4. **LM_POOL vs LM**: 해외 `summ`, 미국은 층 C 사건만(`{"n","mean","p"}`), 그리고 미국 판정 층 사건 중 LM_POOL = LM(차이 0)인 사건 수.
5. 견고성(판정량 3개 × 해당 집단):
   (a) 63·126 만: 사건 값을 e ∈ ROBUST_LANDMARKS 의 쌍만으로 다시 평균 → `summ`.
   (b) 랜드마크별: 판정 층 쌍의 `{"n", "mean", "p": lab.signflip}` (e = 21, 63, 126).
   (c) 해외: 사건 단위(군집 아님) p = `raw["p_episode"]`.
   (d) TWOPH_M2_US: 미국 겹침 군집 p = `v1.cluster_p([(r["t0"], r["rec"], val) ...])`.

## 해석 규칙·지금 읽기·조견표

### 해석 규칙과 '가장 나은 모델' 규칙 (결과 전 고정)

- `interpretation["SIMMIX"]`: SIMMIX_M1_INTL·SIMMIX_M2_INTL 통과 여부로 "해외 깊이·회복 모두 통과" / "해외 깊이만 통과" / "해외 회복만 통과" / "통과 없음" + 항상 "미국 값은 설명용(합친 평균 부호는 볼록성으로 미리 정해짐)".
- `interpretation["TWOPH"]`: "미국·해외 모두 통과(두 집단에서 지지)" / "미국만 통과" / "해외만 통과" / "통과 없음". (미국 C 와 해외 I2 는 같은 세계 급락을 겹쳐 담아 두 집단이 완전히 독립은 아니다 — 한 줄 덧붙임.)
- `best`(지금 읽기·조견표용):
  - 깊이: `SIMMIX_M1_INTL == BEATS_LANDMARK` 이면 "SIMMIX", 아니면 "LM".
  - 회복: 지지 수 = TWOPH 는 (TWOPH_M2_US, TWOPH_M2_INTL) 중 통과 수, SIMMIX 는 SIMMIX_M2_INTL 통과면 1. 지지 수가 가장 큰 모델(≥ 1); 같으면 통과 판정들의 최소 p 가 작은 쪽; 그래도 같으면 TWOPH. 모두 0 이면 "LM".
  - 표시 문구: 통과 모델이면 "판정 통과 모델", LM 이면 "판정 통과 모델 없음 → 랜드마크 모델(LM) 표시. LM 도 crash-landmark-v1 판정은 통과하지 못했다(FAIL_UNDERPOWERED)".

### 조견표 — 비전문가용 한 장 (항상 만든다)

계산(D = 미국 자료 마지막 날, `last = ctx["last"]`):
1. 행: e ∈ GRID_E × d ∈ GRID_D = 21행. `m = min(d, GRID_DD0)`, `st = {"asof": D, "d": d, "m": m, "x": max(-math.log(1 + d), lab.X_FLOOR), "x_raw": -math.log(1 + d)}`.
2. BASE = `lab._base_from_state(us, st, GRID_DD0, e)`(m1_trunc, m2), LM = `lab._lm_from_state(us, st, e)`, TWOPH = `twoph_from_state(us, st, e)`.
3. SIM: `g = lab.garch_filter(lab.logret(ctx["Lv"])[1:last + 1])`(한 번만). 출발 분산 `h0_e` = 이 실행의 미국 쌍(층 무관) 중 랜드마크 e 에서 SIM 이 있는 쌍의 `S["vol_now"]**2 / 252` 의 **중앙값**(없으면 `g["v"]`).
   `rng = np.random.default_rng([lab.SEED, 0, int(last), int(e), gi])`(gi = GRID_D 안 위치 0~6), `lab.simulate_from(math.log(1 + d), math.log(1 + m), g["mu"], g["omega"], h0_e, g["z"], lab.H - e, n_paths, rng)`.
   `v_e = math.sqrt(252 * h0_e) * 100`, `vol_note = f"모의의 변동성은 과거 미국 급락의 같은 시점 중앙값(연율 21일째 {v_21:.0f}% · 63일째 {v_63:.0f}% · 126일째 {v_126:.0f}%)에서 출발한다. 오늘의 변동성은 쓰지 않는다."`
4. SIMMIX = mix(LM, SIM). best = 3.8.
5. 행 값: `best_depth`(q0.1·q0.5·q0.9), `best_rec`(252·504·1260), `rec1_range` = [최소, 최대] of 1년 회복 확률 over {BASE, LM, SIM, SIMMIX, TWOPH}(있는 것), `depth50_range` = [최소, 최대] of q0.5 over {BASE, LM, SIM, SIMMIX}, `n_depth = LM["n1"]`, `n_rec = LM["n2"]`, `base` = (BASE q0.5, BASE 1년).

REPORT 표(그대로의 열):
`| 급락 며칠째 | 지금 깊이 (지금까지 최저) | 최종 깊이 가운데 값 (10~90% 범위) | 1년 안 전고점 회복 | 2년 안 | 5년 안 | 모델 간 차이 (깊이 가운데 · 1년 회복) | v1 기준선 (깊이 가운데 · 1년 회복) |`
- 급락 며칠째: 21 → "약 1개월(21거래일)", 63 → "약 3개월(63거래일)", 126 → "약 6개월(126거래일)".
- 예: `| 약 3개월(63거래일) | −20% (−20%) | −26% (−56% ~ −20%) | 52% | 67% | 85% | −21~−27% · 45~60% | −21% · 59% |` 처럼(숫자는 실제 실행 값).
표 위 문장(그대로): "보는 법: 급락(1년 고점보다 15% 아래로 처음 내려간 날)이 시작되고 '며칠째'만큼 지났고 지금 전고점보다 '지금 깊이'만큼 아래일 때, 과거 급락에서 배운 모델이 말하는 최종 깊이(앞으로 3년 안 가장 낮은 지점)와 지금부터 전고점을 되찾을 확률이다. '10~90% 범위'는 과거 사건 열 개 중 여덟 개가 들어간 폭이고, '모델 간 차이'는 같은 자료로 만든 여러 모델이 얼마나 다르게 보는지다 — 폭이 넓을수록 불확실하다. 지금 깊이가 −15% 보다 얕은 줄은 −15% 까지 빠졌다가 반등한 경우다."
표 아래: best 표시 문구(3.8), `vol_note`, "학습 사건: 깊이 {n_depth}개 · 회복 {n_rec}개(랜드마크마다 다름 — 표 아래 각주)", "추천이 아니다. 엔진·주문과 연결되지 않는다."

## 7개 사건

`| e | 기준일 | 지금 깊이 d | 지금까지 최저 m | BASE 깊이 | LM 깊이 | SIMMIX 깊이 | BASE 회복 | LM 회복 | SIMMIX 회복 | TWOPH 회복 |`(깊이 = 10/50/90%, 회복 = 1/2/5년, `lab.q3`·`lab.r3`), 랜드마크 21·63·126(없으면 "이미 회복 또는 자료 끝"), "사건 안"(2001-09-17 → e 354, 2008-09-15 → e 165)은 기준일 스냅숏 줄 "← 기준일 스냅숏(판정 아님)". 실제(최종 깊이·회복일·회복 기간)는 events_note_lines 표에 있다.

## 산출물

### results.json

```
study, lab_version (lab.LAB_VERSION), rules (RULES_VERSION), judge_version (JUDGE_VERSION), smoke,
data: {source, first_date, last_date, n_days, intl: {region: {first_date, last_date, n_episodes}}},
constants: lab.lab_constants() + {KEYS, K, FAMILY_ALPHA, W_MIX, GRID_E, GRID_D, GRID_DD0, ROBUST_LANDMARKS, n_paths},
family: {k: 4, alpha: 0.05, method: "holm", alpha_expr: "Holm, 족 오류율 0.05, 문턱 0.05/4·0.05/3·0.05/2·0.05",
         keys: KEYS, this_study: KEYS, separate_from: "crash-cycle-lab 7연구 족(15개, 0.05/15)과 별개"},
power: rp.power_report(lab.YEARS_US, 4), power_intl: rp.power_report(lab.YEARS_INTL, 4),
power_episode: {키: power_holm(그 키의 합친 n)},
verdicts: {키: 라벨} (KEYS 순서),
summary: {≤ 8줄} — 키마다 f"{키} {짧은 이름}": f"{라벨} · n {합친 n} · 평균 d {합친 평균:+.4f} · p {p:.4f} · 홈 {순위}위 문턱 {문턱:.4f}"
         (평가 불가면 f"NOT_EVALUABLE · n {n} · {사유}"), 마지막 f"지금(Ken French {as_of})": lab.now_line(current),
detail: {키: 3.3 의 det + holm_rank·holm_threshold·holm_reject·verdict·fail_kind·reason + per_landmark(3.7-5b)},
interpretation: {SIMMIX: 문장, TWOPH: 문장}, best: {depth, recovery, label},
descriptive: {vs_base: {모델: {m1: {US, INTL}, m2: {US, INTL}}}, simmix_us: {m1: {..., bound}, m2: {..., bound}},
              sim_vs_lm: {...}, lmb_vs_lm: {...}, lm_pool_vs_lm: {INTL, US_C, n_identical_us}},
robustness: {only_63_126: {판정량·집단: summ}, per_landmark: {...}, p_episode_intl: {...}, cluster_us_twoph: p},
models: {m1: {f"{pop}_{e}_{s}": {n, score: {BASE, LM, SIM, SIMMIX}, cov80: {LM, SIM, SIMMIX}}},
         m2: {f"{pop}_{e}_{s}": {n, score: {BASE, LM, SIM, SIMMIX, TWOPH}}},
         calib: {f"{pop}_{e}": {h: {n, BASE, LM, SIM, SIMMIX, TWOPH, obs}}}},
episode_fields: ["d", "m", "s1_BASE", "s1_LM", "s1_SIM", "s1_SIMMIX", "s2_BASE", "s2_LM", "s2_SIM", "s2_SIMMIX", "s2_TWOPH"],
episodes: [{id, t0, era, dd0, FD, R, lm: {e: [episode_fields 순서의 값 11개]}, val: {SIMMIX_M1, SIMMIX_M2, TWOPH_M2}}],
events: [7개 — lab.events_rows(ctx, reader)], current: {...}, reading_table: {best, vol_note, rows: [21개]},
checks: {lm_check, sim_check, published_check}, seen: [3.6.1 의 문장 7개], expected: EXPECTED, notes: [...], limits: [...]
```

- `events`: `lab.events_rows(ctx, reader)`. `reader(ep, d, mapping)` 반환 = `{"landmarks": [...], "snapshot": {...} 또는 없음}`.
  `landmarks` 는 e ∈ LANDMARKS 마다, 그 사건의 episode_calc 에 쌍이 있으면 `brief(pair)` = `{"e", "asof", "d", "m", "BASE": {"m1", "m2"}, "LM": {"m1", "m2"}, "SIM": {"m1", "m2"}, "SIMMIX": {"m1", "m2"}, "TWOPH": {"m2"}}`, 없으면 `{"e", "note": "이미 회복 또는 자료 끝"}`.
  mapping == "inside" 이면 `e_s = d − ep["t0"]` 에서 `pair_calc(us, all_recs, ep, e_s, n_paths)` 를 새로 계산해 `snapshot = brief(...)`(None 이면 생략). 미국 사건의 랜드마크 쌍은 이미 계산한 episode_calc 를 id 로 찾아 다시 쓴다.
- `current`: `lab.reading_now(ctx)` + `"active"`: 진행 중 사건(`lab.active_episode(ctx, last)`)이 있고 `e_now = last − t0 ≤ lab.H` 이면 `brief(pair_calc(us, all_recs, ep, e_now, n_paths))` + best 모델 한 문장 재료, 그 밖 None(사유 문자열 `"active_note"`) + `"spy_check": lab.spy_check(state, smoke)`.
- `models` 의 쌍(쌍 단위, 설명용): pop ∈ {US, INTL}, e ∈ LANDMARKS, s ∈ 미국 {A, B, C, all} / 해외 {I1, I2, all}("all" = 판정 층 합). 깊이 표 = 깊이 확정이고 BASE·LM·SIM·SIMMIX 가 모두 있는 쌍. 회복 표·보정표 = 회복했고 BASE·LM·SIM·SIMMIX·TWOPH 가 모두 있는 쌍. cov80 = 실제 FD 가 그 모델의 [q0.1, q0.9] 안에 든 비율.
- `checks`(스모크에서는 `{"skipped": "스모크"}`):
  - `lm_check`: 이 실행의 LM 줄(미국·해외 랜드마크) vs `research/results/crash-landmark-v1/predictions.csv` 의 같은 (market, episode_id, landmark, "LM") 줄 — d_q*·r_* 최대 절대 차, 비교 줄 수, 차이 > 1e−6 인 줄 수. BASE 줄도 같은 방식(`base_check` 키로 함께).
  - `sim_check`: 미국 랜드마크 SIM 줄 vs `research/results/crash-simpath-v1/predictions.csv` 의 (US, episode_id, landmark ∈ {21,63,126}, "SIM") 줄.
  - `published_check`: 3.7-1 의 LM 미국 합친 평균·p vs `research/results/crash-landmark-v1/results.json` 의 `detail.LM_M1/LM_M2.mean.pooled`·`p`.
  - 파일이 없으면 `{"skipped": "파일 없음"}`. 어느 것도 실패 조건이 아니다(Ken French 가 과거 값을 고치면 작은 차이가 날 수 있음 — 보고만).
- **크기 대비책(결정적)**: 결과 dict 를 `_clean` 한 뒤 `json.dumps(…, ensure_ascii=False, indent=1, default=str)` 바이트가 `JSON_MAX_BYTES` 를 넘으면 해외 사건의 `episodes[].lm` 을 null 로 바꾸고 notes 에 "results.json 크기 때문에 해외 사건의 랜드마크별 점수를 뺐다(predictions.csv 에 있음)"; 그래도 넘으면 미국 사건도 같은 처리. 예상 크기는 약 150KB 라 보통 일어나지 않는다.

### predictions.csv

- 줄: 쌍마다 `BASE`(B["m1_trunc"], B["m2"]), `LM`, `SIM`(있으면), `SIMMIX`(깊이·회복 중 하나라도 있으면), `TWOPH`(있으면 — 깊이 칸 빈칸). 랜드마크 0 줄은 쓰지 않는다(LM 이 0 에서 정의되지 않음). LMB·LM_POOL 은 줄을 쓰지 않는다(크기).
- `study = "crash-fusion-v1"`, `asof = st["asof"]`, `p_lb`·`a_now` 빈칸.
- `n_train`: BASE = `lab.n_train_of(B["m1_trunc"], B["n1"], B["m2"], B["n2"])`, LM·SIMMIX = `lab.n_train_of(M["m1"], M["n1"], M["m2"], M["n2"])`, SIM = `S["n_hist"]`, TWOPH = `T["n"]`.
- `judged_m1` / `judged_m2`(그 쌍이 그 판정의 사건 값에 들어갔고 사건 층이 판정 층일 때):
  - 미국 A·B·C 쌍: judged_m1 = 0(미국 깊이 판정 없음). judged_m2 = 1 — TWOPH 줄과 BASE·LM 줄, 쌍이 TWOPH_M2_US 에 들어갔을 때. SIMMIX·SIM 줄은 0.
  - 해외 I1·I2 쌍: judged_m1 = 1 — SIMMIX·BASE·LM 줄, SIMMIX_M1_INTL 에 들어갔을 때. judged_m2 = 1 — SIMMIX 줄은 SIMMIX_M2_INTL 에, TWOPH 줄은 TWOPH_M2_INTL 에 들어갔을 때; BASE·LM 줄은 둘 중 하나라도 들어갔을 때. SIM 줄은 0.
  - 층 X·IX: 모두 0.
- 크기: 쌍 약 196개(미국 73 + 해외 123) × 줄 4~5개 ≈ 960줄 × 약 175바이트 ≈ **약 170KB**(상한 250,000). 대비책(결정적): 쓰기 전에 `lab._cell` 로 같은 형식의 바이트 수를 세어 `lab.PRED_MAX_BYTES` 를 넘으면 `SIM` 줄을 빼고 notes 에 "predictions.csv 크기 때문에 SIM 줄을 뺐다(SIMMIX 줄은 남음)".

### 스모크·실행 시간

합성 미국(`lab0.synthetic_data`, `lab.load_us(True)`)·합성 해외(`lab.synthetic_intl`), `n_paths = 400`. SPY·checks 는 부르지 않는다(`{"skipped": "스모크"}`, spy_check = `lab.spy_check(state, True)`). 판정·홈 절차는 그대로 돈다(숫자에 뜻 없음). 끝까지 돌고 종료 0, 세 파일 생성, 120초 이내.

모의 약 207회(미국 쌍 73 + 해외 쌍 약 111 + 사건 안 스냅숏 2 + 조견표 21 + 진행 중이면 1) × 4,000경로 × 1,260일 ≈ 회당 0.2~0.3초 + GARCH 거르기 Python 반복(미국 최대 25,000일, 회당 약 0.03초) → **약 1~2분**. 유사 사건 계산(LM·BASE·TWOPH·LMB·LM_POOL)은 몇 초. 메모리 약 200MB(상한 1,024MB). 체크포인트 쓰지 않음(`--checkpoint` 폴더만 만듦), `resumable: false`.

## 한계

- 판정 사건의 결과는 모두 이미 알려져 있고 LM·SIM 의 미국 성적도 보았다. 진짜로 손대지 않은 자료는 앞으로 생길 급락뿐이다.
- 해외 판정은 USD 기준 선진국 3지역(1991~)이고, 지역 일별 이력이 짧아 모의의 표류·변동성 추정이 거칠다(asof 1993-05 무렵 이전 쌍은 SIM 이 없어 빠짐).
- TWOPH 는 깊이가 확정된 유사 사건만 써서 LM_SCALED 보다 유사 사건이 조금 적다. 오르는 시간이 바닥 거리에 비례한다는 것은 근사다.
- SIMMIX 비중 0.5 는 고정값이다(최적 비중을 찾지 않았다). 모의는 표류 고정·대칭 GARCH·독립 재표집(crash-simpath-v1 의 한계 그대로).
- 미국 C 와 해외 I2 는 같은 세계 급락(2008·2020·2022)을 겹쳐 담아 두 집단이 완전히 독립은 아니다. 급락 연구 전체(7연구 15개 + 이 연구 4개)를 묶은 다중 검정 보정은 하지 않았다.
- 총수익·명목 기준, 최종 깊이는 3년에서 자른다(v1 과 같음).

## 의도적으로 뺀 것

- 거시·신용, 시장 내부, 업종 이전, 자기 보정의 융합(7연구 결과 요지 표의 '융합' 열).
- 모델 3(랜드마크 정보로 투입 결정 = 급락 중 매수 시점 신호, 막다른 길).
- LMB(LM ⊕ BASE) 판정 — 설명용만.
- 미국 SIMMIX 판정(편향 진술 3).
- LM_POOL 판정 — 설명용만.
- 비중 격자·랜드마크 격자 확장, 3개 이상 섞기.
- 새 급락이 생길 때 실시간 예측 기록(범위 밖).

## 구현 해석 (설계의 모호점, 보수적으로 읽음)

- `power_holm(n)` 은 n < 2 이면 `needed_effect_sd`·`min_p`·`pass_prob_first` 의 수치를 모두 None 으로 둔다.
- '융합 2' 의 TWOPH 점수 표는 `models.m2`(BASE·LM·SIM·SIMMIX·TWOPH 가 모두 있는 쌍)를 그대로 쓴다. 판정·설명용 값(쌍 차이)은 각 모델이 있는 쌍만으로 따로 계산되므로 표의 평가 수와 다를 수 있다.
- `best.label` 은 깊이·회복이 모두 LM 이면 LM 문구 하나, 아니면 '깊이: 모델 — 문구 · 회복: 모델 — 문구'.
- 조견표·지금 읽기에서 표시 모델의 예측이 없으면(학습 사건 부족) 그 칸은 '—'.
- 재현 확인에서 한쪽만 값이 있는 칸은 '차이 > 1e-6' 줄로 센다. 공개 파일에 없는 줄은 따로 센다. 어느 것도 실패 조건이 아니다.
- 해외 자료는 판정 자료라 `load_intl(required=True)` — 한 지역이라도 못 받으면 예외(실행기 재시도).
- results.json 의 `detail` 에는 lab 판정 함수의 `verdict`·`fail_kind`(0.05/15 기준)를 넣지 않는다. 라벨은 홈 절차로만 붙인다.
