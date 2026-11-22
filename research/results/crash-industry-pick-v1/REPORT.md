# 급락 진입 때 무엇을 살까 — 12 산업 (crash-industry-pick-v1)

시장이 252일 고점 대비 −15% 아래로 내려간 날, 그날 종가까지의 정보로 12 산업 중 3개를 골라 다음 날 사서 250일 들고 있으면 시장보다 나았나. 규칙·판정은 SPEC.md(결과 전 고정).

**판정:** P1_MOST_FALLEN(가장 많이 빠진 3 산업) **FAIL** · P2_LEAST_FALLEN(가장 덜 빠진 3 산업) **FAIL** · P3_HIGH_BETA(베타 높은 3 산업) **FAIL** · P4_LOW_BETA(베타 낮은 3 산업) **FAIL**

판정 기준(industry-pick-judge/v1): 시대 A(1927~1966)·B(1967~2007) 각각 사건 ≥ 5, 두 시대 모두 250일 D(로그, 대 시장) 평균 > 0 이고 단측 p < 0.0125.

## 시대 A 1927~1966 (판정) — 사건 12개

| 후보 | 250일 D 평균 / 중앙 | 시장 이긴 비율 | 단측 p | 120일 D | 60일 D | 평가 사건 |
|---|---|---|---|---|---|---|
| 가장 많이 빠진 3 산업 | -0.6% / -3.2% | 33% | 0.6388 | +1.1% | -1.5% | 12 |
| 가장 덜 빠진 3 산업 | +4.6% / +5.3% | 67% | 0.0352 | +0.6% | +1.6% | 12 |
| 베타 높은 3 산업 | +0.2% / +0.5% | 50% | 0.4605 | +1.9% | -1.0% | 12 |
| 베타 낮은 3 산업 | +4.2% / +2.5% | 58% | 0.0831 | +0.7% | +2.7% | 12 |

## 시대 B 1967~2007 (판정) — 사건 11개

| 후보 | 250일 D 평균 / 중앙 | 시장 이긴 비율 | 단측 p | 120일 D | 60일 D | 평가 사건 |
|---|---|---|---|---|---|---|
| 가장 많이 빠진 3 산업 | -2.6% / -2.5% | 27% | 0.9567 | -2.0% | -0.4% | 11 |
| 가장 덜 빠진 3 산업 | +5.4% / +3.3% | 55% | 0.0845 | +2.9% | +0.6% | 11 |
| 베타 높은 3 산업 | -0.5% / -1.1% | 45% | 0.5944 | +1.2% | +2.3% | 11 |
| 베타 낮은 3 산업 | +3.0% / -4.0% | 45% | 0.2593 | +0.6% | -1.3% | 11 |

## 시대 C 2008~ (보고만) — 사건 8개

| 후보 | 250일 D 평균 / 중앙 | 시장 이긴 비율 | 단측 p | 120일 D | 60일 D | 평가 사건 |
|---|---|---|---|---|---|---|
| 가장 많이 빠진 3 산업 | -0.4% / -1.8% | 50% | 0.5235 | -0.6% | +0.3% | 8 |
| 가장 덜 빠진 3 산업 | -1.9% / -1.4% | 50% | 0.6635 | -3.1% | -2.4% | 8 |
| 베타 높은 3 산업 | +1.2% / +1.8% | 62% | 0.4183 | +2.6% | +1.6% | 8 |
| 베타 낮은 3 산업 | -2.6% / -3.6% | 38% | 0.7207 | -4.1% | -3.1% | 8 |

## 견고성: 49 산업 같은 규칙 (보고만)

| 후보 | A 250일 D | B 250일 D | C 250일 D |
|---|---|---|---|
| 가장 많이 빠진 3 산업 | -11.3% | +5.0% | +8.1% |
| 가장 덜 빠진 3 산업 | +7.6% | +9.7% | -5.3% |
| 베타 높은 3 산업 | -2.1% | -3.4% | +7.2% |
| 베타 낮은 3 산업 | +4.0% | +6.5% | -6.2% |

## 사건별 고른 산업

| 진입일 | 시대 | 많이 빠진 3 | 덜 빠진 3 | 고베타 3 | 저베타 3 | 250일 D(많이 빠진) |
|---|---|---|---|---|---|---|
| 1929-10-23 | A | Durbl, Utils, Money | Other, Telcm, NoDur | Chems, Durbl, BusEq | Hlth, Other, NoDur | -4.9% |
| 1933-07-21 | A | Durbl, Money, BusEq | Shops, NoDur, Telcm | Manuf, BusEq, Durbl | Telcm, NoDur, Hlth | -5.8% |
| 1934-05-07 | A | Utils, BusEq, Money | Telcm, Chems, Shops | Manuf, BusEq, Durbl | Telcm, Hlth, NoDur | -4.1% |
| 1937-06-14 | A | Utils, Durbl, Shops | Chems, Telcm, NoDur | Manuf, BusEq, Durbl | Hlth, Telcm, NoDur | +4.4% |
| 1939-03-31 | A | Manuf, BusEq, Durbl | NoDur, Telcm, Hlth | BusEq, Manuf, Durbl | Hlth, Telcm, NoDur | +2.8% |
| 1940-05-14 | A | Durbl, Enrgy, Manuf | NoDur, Hlth, Telcm | Enrgy, Durbl, Manuf | Hlth, Telcm, Shops | +5.0% |
| 1941-12-22 | A | Utils, Durbl, BusEq | Chems, Hlth, Enrgy | Other, Durbl, Manuf | Hlth, Telcm, NoDur | +13.1% |
| 1946-09-03 | A | Durbl, Shops, Other | NoDur, Enrgy, Telcm | Other, Manuf, Durbl | Telcm, NoDur, Enrgy | -4.5% |
| 1949-06-06 | A | Enrgy, Manuf, Other | Telcm, Hlth, Utils | Other, BusEq, Enrgy | Telcm, NoDur, Hlth | -3.5% |
| 1957-10-10 | A | Enrgy, Manuf, BusEq | Shops, NoDur, Telcm | BusEq, Manuf, Enrgy | Telcm, Utils, NoDur | -0.3% |
| 1962-05-23 | A | BusEq, NoDur, Hlth | Utils, Durbl, Enrgy | Telcm, Durbl, BusEq | Utils, Other, Enrgy | -6.6% |
| 1966-08-26 | A | Durbl, Other, Telcm | Hlth, Enrgy, BusEq | Manuf, BusEq, Other | Utils, Money, Shops | -2.9% |
| 1969-07-23 | B | Other, Money, NoDur | Utils, Hlth, Telcm | Money, Other, BusEq | Utils, Telcm, NoDur | -0.3% |
| 1973-05-17 | B | Other, Shops, Money | Enrgy, Hlth, Telcm | Manuf, Shops, BusEq | Utils, Telcm, NoDur | -0.7% |
| 1978-10-31 | B | Other, Hlth, Shops | Enrgy, Utils, Telcm | Manuf, BusEq, Hlth | Utils, Telcm, NoDur | -2.5% |
| 1980-03-24 | B | BusEq, Other, Enrgy | NoDur, Telcm, Utils | Other, BusEq, Enrgy | Telcm, Utils, NoDur | +2.4% |
| 1981-09-25 | B | Enrgy, BusEq, Other | NoDur, Utils, Telcm | Other, BusEq, Enrgy | Telcm, NoDur, Utils | -6.4% |
| 1982-03-04 | B | Enrgy, Manuf, Other | Telcm, NoDur, Utils | Other, BusEq, Enrgy | Telcm, Utils, NoDur | -5.6% |
| 1987-10-19 | B | Durbl, Shops, Chems | Telcm, Money, Utils | Durbl, Chems, BusEq | Utils, Money, Other | +2.9% |
| 1990-08-23 | B | Money, Durbl, Telcm | Hlth, Utils, Enrgy | NoDur, Hlth, Telcm | Utils, Enrgy, Money | -3.9% |
| 1998-08-28 | B | Money, Other, Enrgy | Hlth, Telcm, Utils | Hlth, Money, BusEq | Utils, NoDur, Telcm | -11.2% |
| 2000-04-14 | B | BusEq, Chems, NoDur | Manuf, Hlth, Enrgy | Hlth, Money, BusEq | Utils, Enrgy, Chems | +2.9% |
| 2000-10-12 | B | BusEq, Telcm, Chems | Utils, NoDur, Enrgy | Money, Telcm, BusEq | Utils, Enrgy, Chems | -6.4% |
| 2008-01-18 | C | Durbl, Money, Telcm | Utils, NoDur, Hlth | Enrgy, Durbl, Money | Hlth, NoDur, Chems | -22.9% |
| 2010-06-30 | C | Durbl, Money, Enrgy | Telcm, NoDur, Utils | Money, Manuf, Durbl | NoDur, Hlth, Utils | +3.8% |
| 2011-08-08 | C | Durbl, Money, Manuf | Shops, Utils, NoDur | Money, Manuf, Durbl | NoDur, Utils, Hlth | -10.7% |
| 2016-02-11 | C | Enrgy, Durbl, Money | Telcm, Utils, NoDur | Money, BusEq, Enrgy | Utils, NoDur, Telcm | +6.1% |
| 2018-12-19 | C | Enrgy, Durbl, Manuf | Chems, Telcm, Utils | Other, Manuf, BusEq | Utils, NoDur, Telcm | -7.5% |
| 2020-03-09 | C | Enrgy, Durbl, Money | NoDur, Utils, Hlth | Money, Durbl, Enrgy | Utils, NoDur, Telcm | +30.1% |
| 2022-04-29 | C | Durbl, Telcm, BusEq | Enrgy, Utils, NoDur | Shops, BusEq, Durbl | Utils, NoDur, Enrgy | -14.8% |
| 2025-04-04 | C | Durbl, BusEq, Enrgy | Telcm, Utils, NoDur | Manuf, BusEq, Durbl | NoDur, Chems, Utils | +12.9% |

## 읽는 법

- D 가 양수면 그 후보가 같은 날 산 시장보다 1년 뒤 더 많이 남겼다는 뜻이다(로그 차이).
- 사건이 시대당 10개 안팎이라 매우 큰 효과만 통과한다. FAIL 이 '효과 없음'의 증명은 아니다.
- 산업 지수는 실제 업종 ETF 와 다르고 세금·비용을 넣지 않았다. 통과도 추천 반영이 아니며 사용자 확인 뒤 별도 작업이다.
