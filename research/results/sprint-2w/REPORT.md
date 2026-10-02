# 2주 R&D 스프린트 결과

생성 2026-10-02T13:11:11+00:00

판정 sprint-judge/v1: 앞 구간 최선 → 시도 수 보정 DSR ≥ 0.95 → 과적합 확률 PBO ≤ 25% → 떼어 둔 2년에서 현 규칙보다 나음. 모두 만족하면 CANDIDATE(사람 검토 후보), 아니면 KEEP_CURRENT(현 규칙 유지).

## F2 코어 선정

- 판정 **KEEP_CURRENT** · 설정 180/180개 · 현 규칙 앞 구간 순위 26위
- 앞 구간 최선: `9m|top5|spy200|corr-|buf-` (샤프 0.75, 연 8%, 최대낙폭 -19%)
- 현 규칙: `12m|top4|spy200|corr-|buf-` (샤프 0.66, 연 8%, 최대낙폭 -20%)
- DSR 0.12 · 과적합 확률 PBO 57% · 떼어 둔 2년 샤프 승자 1.02 vs 현 규칙 1.04
- 사유: DSR 0.12 < 0.95 (시도 180); 과적합 확률 PBO 57% > 25%; 떼어 둔 2년 샤프 1.02 ≤ 현 규칙 1.04

| 앞 구간 상위 | 앞 구간 샤프 | 떼어 둔 2년 샤프 |
|---|---|---|
| `9m|top5|spy200|corr-|buf-` | 0.75 | 1.02 |
| `mix3-12|top5|spy200|corr-|buf-` | 0.73 | 0.91 |
| `mix3-12|top4|spy200|corr0.8|buf6` | 0.73 | 1.04 |
| `mix3-12|top5|spy200|corr-|buf6` | 0.72 | 0.90 |
| `mix3-12|top5|spy200|corr0.8|buf6` | 0.71 | 0.84 |
| `9m|top5|spy200|corr-|buf6` | 0.71 | 1.16 |
| `mix3-12|top4|none|corr0.8|buf6` | 0.70 | 1.06 |
| `9m|top3|spy200|corr0.8|buf-` | 0.70 | 0.37 |
| `9m|top5|none|corr-|buf-` | 0.70 | 1.03 |
| `9m|top4|spy200|corr-|buf-` | 0.70 | 1.00 |

## F3 코어 보유 중 매도

- 판정 **KEEP_CURRENT** · 설정 22/22개 · 현 규칙 앞 구간 순위 1위
- 앞 구간 최선: `none` (샤프 0.66, 연 8%, 최대낙폭 -20%)
- 현 규칙: `none` (샤프 0.66, 연 8%, 최대낙폭 -20%)
- DSR 0.05 · 과적합 확률 PBO 30% · 떼어 둔 2년 샤프 승자 1.04 vs 현 규칙 1.04
- 사유: 앞 구간 최선이 현 규칙 자신; DSR 0.05 < 0.95 (시도 22); 과적합 확률 PBO 30% > 25%; 떼어 둔 2년 샤프 1.04 ≤ 현 규칙 1.04

| 앞 구간 상위 | 앞 구간 샤프 | 떼어 둔 2년 샤프 |
|---|---|---|
| `none` | 0.66 | 1.04 |
| `trail20%|daily` | 0.65 | 1.04 |
| `trail20%|weekly` | 0.65 | 1.04 |
| `trail15%|weekly` | 0.64 | 0.97 |
| `rank_out_of_top8|weekly` | 0.63 | 1.04 |
| `trail15%|daily` | 0.63 | 1.01 |
| `spy_below_200|weekly` | 0.61 | 0.97 |
| `mom12_negative|weekly` | 0.59 | 1.04 |
| `trail10%|daily` | 0.55 | 0.80 |
| `trail10%|weekly` | 0.54 | 0.96 |

## F4 사고파는 가격

| 칸 | 판정 | 앞 구간 최선 | 앞 구간 개선 | 떼어 둔 2년 | DSR | PBO | 사유 |
|---|---|---|---|---|---|---|---|
| core|buy | **KEEP_CURRENT** | limit1%|1d | +1.0bp | +8.5bp | 0.22 | 86% | DSR 0.22 < 0.95 (시도 43); 과적합 확률 PBO 86% > 25% |
| core|sell | **KEEP_CURRENT** | limit5%|10d | +47.0bp | +66.7bp | 0.65 | 57% | DSR 0.65 < 0.95 (시도 43); 과적합 확률 PBO 57% > 25% |
| satellite|buy | **KEEP_CURRENT** | limit3%|1d | +15.2bp | +49.2bp | 0.14 | — | DSR 0.14 < 0.95 (시도 43); 과적합 확률 PBO — > 25% |
| satellite|hold_take_profit | **KEEP_CURRENT** | tp30% | +137.6bp | +245.2bp | 0.51 | — | DSR 0.51 < 0.95 (시도 7); 과적합 확률 PBO — > 25% |
| satellite|sell | **KEEP_CURRENT** | split5x5d | +126.5bp | +104.2bp | 0.47 | — | DSR 0.47 < 0.95 (시도 43); 과적합 확률 PBO — > 25% |

## F1 새틀라이트 선정

- 판정 **KEEP_CURRENT** · 설정 1044/1044개 · 현 규칙 앞 구간 순위 9위
- 앞 구간 최선: `trend_mom(d10,s0.1,lb252)|champion40|k5|h1|none` (샤프 0.88, 연 18%, 최대낙폭 -34%)
- 현 규칙: `trend_mom(d20,s0.15,lb252)|champion40|k3|h6|none` (샤프 0.86, 연 22%, 최대낙폭 -32%)
- DSR 0.00 · 과적합 확률 PBO 79% · 떼어 둔 2년 샤프 승자 0.71 vs 현 규칙 0.78
- 사유: DSR 0.00 < 0.95 (시도 1044); 과적합 확률 PBO 79% > 25%; 떼어 둔 2년 샤프 0.71 ≤ 현 규칙 0.78

| 앞 구간 상위 | 앞 구간 샤프 | 떼어 둔 2년 샤프 |
|---|---|---|
| `trend_mom(d10,s0.1,lb252)|champion40|k5|h1|none` | 0.88 | 0.71 |
| `lowvol_trend(v63)|champion40|k5|h3|ts0.15` | 0.88 | 0.20 |
| `trend_mom(d10,s0.1,lb252)|champion40|k5|h1|ts0.25` | 0.88 | 0.66 |
| `trend_mom(d55,s0.15,lb252)|champion40|k5|h6|none` | 0.87 | 0.85 |
| `trend_mom(d10,s0.1,lb252)|champion40|k8|h1|none` | 0.86 | 0.92 |
| `trend_mom(d10,s0.1,lb252)|champion40|k8|h1|ts0.25` | 0.86 | 0.88 |
| `trend_mom(d20,s0.1,lb252)|champion40|k3|h1|ts0.25` | 0.86 | 0.05 |
| `trend_mom(d20,s0.1,lb252)|champion40|k5|h1|ts0.25` | 0.86 | 0.66 |
| `trend_mom(d20,s0.15,lb252)|champion40|k3|h6|none` | 0.86 | 0.78 |
| `trend_mom(d20,s0.1,lb252)|champion40|k5|h1|none` | 0.86 | 0.73 |

- 상위 목록의 떼어 둔 2년 숫자는 참고용이다(승자 선택에 쓰지 않았다). 과거 결과는 미래를 보장하지 않는다. CANDIDATE 도 엔진에 자동 반영되지 않는다.
