# 차트 매매 규칙(유튜브 대본 출신) R&D v1

생성 2026-10-02T11:49:57+00:00 · 개발 ~2020-01-01 · 검증 ~2024-10-01 · 그 뒤 2년 떼어 둠 · 전체 시도 312개 (R1 204, R2 90, R3 18)

샤프는 모두 단기국채(BIL) 대비 초과수익 기준. 비교 기준(개발+검증 구간): 현 새틀라이트 샤프 0.85, 현 챔피언 샤프 0.82, 그냥 사서 들고 있기(champion40) 0.82, (S&P500 PIT) 0.77

## 단독 슬리브(R1+R2) — 새틀라이트 대신 쓸 만한가

- 판정 **KEEP_CURRENT** · 앞 구간 최선 `__bench__` · 비교 대상 현 새틀라이트(같은 엔진, 15% 슬리브)
- 앞 구간 샤프 승자 0.85 vs 비교 대상 0.85 · DSR 0.04 · 과적합 확률 PBO 44% · 떼어 둔 2년 샤프 승자 0.68 vs 0.68
- 사유: 앞 구간 최선이 비교 대상 자신; 앞 구간 최선이 현 규칙 자신; 과적합 확률 PBO 44% > 25%; 떼어 둔 2년 샤프 0.68 ≤ 현 규칙 0.68; DSR 0.04 < 0.95 (이 연구 전체 시도 312)

| 앞 구간 상위 | 앞 구간 샤프 | 최대낙폭 | 떼어 둔 2년 샤프 |
|---|---|---|---|
| `__bench__` | 0.85 | -32% | 0.68 |
| `R2|golden_cross50/200|champion40|k5|k_double` | 0.82 | -32% | 0.38 |
| `R1|golden_cross50/200|champion40|k10` | 0.82 | -32% | 0.38 |
| `R2|golden_cross50/200|champion40|k10|k_half` | 0.82 | -32% | 0.38 |
| `R2|golden_cross50/200|champion40|k5|k_half` | 0.82 | -32% | 0.38 |
| `R1|golden_cross50/200|champion40|k5` | 0.82 | -32% | 0.38 |
| `R2|golden_cross50/200|champion40|k10|weekly` | 0.81 | -33% | 0.42 |
| `R2|golden_cross50/200|champion40|k5|weekly` | 0.81 | -33% | 0.42 |
| `R2|golden_cross50/200|champion40|k10|k_double` | 0.80 | -32% | 0.35 |
| `R1|golden_cross50/200|champion40|k20` | 0.80 | -32% | 0.35 |

## 챔피언과 결합(R3) — 시너지가 있는가

- 판정 **KEEP_CURRENT** · 앞 구간 최선 `R3|add_tech10|R2|bb_squeeze_q0.2|champion40|k20|k_half` · 비교 대상 현 챔피언(코어 85 + 새틀라이트 15)
- 앞 구간 샤프 승자 0.84 vs 비교 대상 0.82 · DSR 0.00 · 과적합 확률 PBO 10% · 떼어 둔 2년 샤프 승자 1.00 vs 1.05
- 사유: 떼어 둔 2년 샤프 1.00 ≤ 현 규칙 1.05; DSR 0.00 < 0.95 (이 연구 전체 시도 312)

| 앞 구간 상위 | 앞 구간 샤프 | 최대낙폭 | 떼어 둔 2년 샤프 |
|---|---|---|---|
| `R3|add_tech10|R2|bb_squeeze_q0.2|champion40|k20|k_half` | 0.84 | -17% | 1.00 |
| `R3|add_tech10|R1|bb_squeeze_q0.2|champion40|k10` | 0.84 | -17% | 1.00 |
| `R3|add_tech10|R1|bb_squeeze_q0.2|champion40|k5` | 0.83 | -18% | 1.00 |
| `__bench__` | 0.82 | -19% | 1.05 |
| `R3|bear_switch|R2|bb_squeeze_q0.2|champion40|k20|k_half` | 0.82 | -17% | 0.89 |
| `R3|bear_switch|R1|bb_squeeze_q0.2|champion40|k10` | 0.82 | -17% | 0.89 |
| `R3|bear_switch|R1|bb_squeeze_q0.2|champion40|k5` | 0.82 | -17% | 0.87 |
| `R3|split_sat|R1|bb_squeeze_q0.2|champion40|k10` | 0.79 | -18% | 1.02 |
| `R3|split_sat|R2|bb_squeeze_q0.2|champion40|k20|k_half` | 0.79 | -18% | 1.02 |
| `R3|split_sat|R1|bb_squeeze_q0.2|champion40|k5` | 0.79 | -18% | 1.02 |

## 진단 — 한계와 시너지가 나는 국면 (판정과 무관, 보고용)

| 단독 상위 | 개발 샤프 | 검증 샤프 | 챔피언과 상관 | 손익분기 비용(편도) | 약세장 초과(vs 새틀라이트) | 고변동 초과 |
|---|---|---|---|---|---|---|
| `R1|golden_cross50/200|champion40|k10` | 1.03 | 0.60 | 0.79 | 274bp | -1% | -15% |
| `R2|golden_cross50/200|champion40|k5|k_double` | 1.03 | 0.60 | 0.79 | 274bp | -1% | -15% |
| `R1|golden_cross50/200|champion40|k5` | 1.03 | 0.60 | 0.79 | 274bp | -1% | -15% |
| `R2|golden_cross50/200|champion40|k5|k_half` | 1.03 | 0.60 | 0.79 | 274bp | -1% | -15% |
| `R2|golden_cross50/200|champion40|k10|k_half` | 1.03 | 0.60 | 0.79 | 274bp | -1% | -15% |
| `R2|golden_cross50/200|champion40|k10|weekly` | 1.04 | 0.56 | 0.79 | 274bp | -3% | -16% |
| `R2|golden_cross50/200|champion40|k5|weekly` | 1.04 | 0.56 | 0.79 | 274bp | -3% | -16% |
| `R1|golden_cross50/200|champion40|k20` | 1.00 | 0.57 | 0.80 | 274bp | -6% | -18% |
| `R2|golden_cross50/200|champion40|k10|k_double` | 1.00 | 0.57 | 0.80 | 274bp | -6% | -18% |
| `R2|golden_cross50/200|champion40|k10|min_hold5` | 1.02 | 0.57 | 0.79 | 274bp | -2% | -16% |
| `R2|golden_cross50/200|champion40|k5|min_hold5` | 1.02 | 0.57 | 0.78 | 274bp | -2% | -16% |
| `R1|engulfing_after_dip,hold20|champion40|k20` | 1.11 | 0.45 | 0.55 | 52bp | -11% | -27% |
| `R2|bb_rev2.5,exit_upper|champion40|k20|weekly` | 0.97 | 0.62 | 0.66 | 139bp | 0% | -17% |
| `R1|bb_rev2.5,exit_upper|champion40|k10` | 0.96 | 0.58 | 0.69 | 139bp | -1% | -17% |
| `R2|bb_rev2.5,exit_upper|champion40|k20|k_half` | 0.96 | 0.58 | 0.69 | 139bp | -1% | -17% |

규칙 종류별 최고: rsi → `R1|rsi14<30,exit_rsi50|sp500_pit|k10`, bb_reversal → `R1|bb_rev2.5,exit_upper|champion40|k10`, bb_squeeze → `R1|bb_squeeze_q0.2|champion40|k10`, candle → `R1|engulfing_after_dip,hold20|champion40|k20`, ma_trend → `R1|golden_cross50/200|champion40|k10`, turtle → `R1|turtle55/20|champion40|k5`, volume_breakout → `R1|volume3.0x_breakout,hold10|sp500_pit|k20`, staged_126 → `R1|staged_1:2:6_full|sp500_pit|k5`

- 손익분기 비용이 8bp 근처거나 그보다 낮으면 회전율이 수익을 다 잡아먹는 규칙이다.
- 국면별 초과는 '언제 시너지가 나는가'를 보는 진단이며, 국면 게이트 변형(R2)·국면 전환 결합(R3)이 그 가설을 실제로 시험한다.
- CANDIDATE 도 엔진에 자동 반영되지 않는다. 과거 결과는 미래를 보장하지 않는다.
