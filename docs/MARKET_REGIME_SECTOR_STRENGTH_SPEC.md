# 시장 국면 판단 + 섹터/테마 강도 지표 (논의 노트)

> **상태: 구현 완료 (2026-07-15).** 새 모듈이 아니라 기존 `app/pages/7_매크로_대시보드.py`
> (모듈 G) 안의 새 탭으로 구현. 핵심 로직은 `core/market_regime.py`(신규) + `core/sector_strength.py`(신규).
> 구현/검증 상세 로그는 `PROGRESS.md`(2026-07-15 항목) 참고.

## 1. 요청 요약 (2026-07-15)

S&P500 등을 통해 전체 시장이 강세장/약세장인지, 그리고 DRAM/반도체/우주섹터 등 섹터별로 얼마나
힘(모멘텀)이 센지를 **정량적으로** 보여주는 기능. 구현 전 인터넷 리서치(최소 5분)로 업계 표준
방법론을 조사한 뒤 설계에 반영하도록 요청받음.

## 2. 리서치 근거

**시장 국면(강세/약세) 판단**
- 학계/업계 모두 HMM 등 통계·ML 기반 레짐 탐지도 쓰지만, 개인 대시보드 수준에서는 룰 기반 복합
  지표가 훨씬 널리 쓰이고 "왜 그렇게 판단했는지" 설명 가능함.
- 200일 이동평균 대비 위치: 가장 기본적인 장기추세 필터.
- 골든크로스(50일선이 200일선 상향 돌파)/데드크로스: [MarketWatch 분석](https://www.forex.com/en-us/news-and-analysis/golden-cross-vs-death-cross-indicators/)에 따르면
  골든크로스 후 1년 평균 +9.9%. 단, 데드크로스는 이미 하락이 상당 부분 진행된 뒤에 나오는 후행
  신호라 "이후 매도"의 근거로는 약함(리서치에서 확인된 한계 — 그대로 UI에 캡션으로 명시).
- 시장폭(breadth) — [Schwab](https://www.schwab.com/learn/story/breadth-check-strength-and-weakness-trend-tracker),
  [Pro Trader Dashboard](https://protraderdashboard.com/blog/percent-stocks-above-ma/): 지수 구성종목 중
  200일선 위 비율이 70%↑면 강세, 30%↓면 약세, 85~90%↑는 과열(조정 임박 가능성)로 해석.
- 고점 대비 낙폭 -20%는 통상적인 "공식 약세장" 정의 기준으로 널리 사용됨(-10~-20%는 조정).

**섹터/테마 강도**
- [IBD RS Rating](https://www.ainvest.com/news/ibd-rs-rating-quick-gauge-stock-strength-2506/): 최근
  3개월에 가중치를 더 준 12개월 수익률을 0~100 percentile로 환산.
  `StrengthFactor = 0.4·ROC(63) + 0.2·ROC(126) + 0.2·ROC(189) + 0.2·ROC(252)` (거래일 기준).
- [Relative Rotation Graphs(RRG)](https://chartschool.stockcharts.com/table-of-contents/chart-analysis/chart-types/relative-rotation-graphs-rrg-charts):
  추세(RS-Ratio) + 모멘텀(RS-Momentum) 2축으로 섹터를 Leading/Weakening/Lagging/Improving 4분면에
  배치하는 업계 표준 기법. 이번 구현에서는 산점도 4분면 차트까지는 만들지 않고(범위 확대 방지),
  "레벨(RS 점수)"과 "추세 방향(최근 20거래일 RS 점수 변화)" 두 축으로 RRG의 핵심 아이디어만
  단순화해 표/막대차트로 반영.
- DRAM/반도체/우주섹터는 GICS 표준 11개 섹터에 없지만 실제 대응 ETF가 존재:
  [반도체 ETF 가이드](https://www.etf.com/sections/news/semiconductor-etfs-101-dram-euv-smh-soxx-soxl-complete-guide-2026)
  — SOXX(iShares, 30종목 균등가중 성격, 최근 미드캡 반도체 랠리 더 잘 포착), SMH(VanEck, 유동성 최대,
  최근 엔비디아 등 대형주 비중 큼). DRAM은 Roundhill Memory ETF(티커 그대로 `DRAM`, SK하이닉스/마이크론/
  삼성전자 비중 약 75%). 우주는 [UFO/ARKX/ROKT 비교](https://trendspider.com/learning-center/ufo-vs-arkx-why-these-space-etfs-are-not-the-same-investment/)
  — UFO(ProCure, 순수 우주기업), ROKT(SPDR, 록히드마틴 등 방산 대형주 54% 포함), ARKX(ARK, 액티브
  운용+인접 혁신테마). 세 ETF가 구성이 상당히 달라 하나만 쓰면 편향될 수 있어 이번 설계는 테마당
  **여러 프록시 ETF를 평균**하는 방식을 채택.

## 3. 확정된 설계 결정 (AskUserQuestion으로 확인)

| 항목 | 결정 |
|---|---|
| UI 위치 | 새 페이지 아님. 기존 `app/pages/7_매크로_대시보드.py`(모듈 G)에 새 탭 추가 |
| 시장 국면 판단 방식 | 룰 기반 복합지표 (통계/ML 배제 — 기존 `core/macro_cycle.py`와 같은 "투명한 간이 프레임워크" 스타일 유지) |
| 섹터 강도 대상 정의 | 대표 ETF 프록시 (개별 종목 바스켓 직접 구성 X) |
| 테마 확장 방식 | 코드에 정의된 프리셋 딕셔너리로 시작(11개 GICS 섹터 SPDR ETF + 반도체/DRAM/우주). 나중에 테마가 더 필요하면 딕셔너리에 항목만 추가하면 됨. UI 편집 화면은 이번 범위에 넣지 않음(과설계 방지) |

## 4. 기술 설계 (위임받은 세부사항 — 근거와 함께 직접 결정)

### 4.1 시장 국면 점수 (`core/market_regime.py`, 벤치마크 `^GSPC` — 기존 `backtest_engine.DEFAULT_BENCHMARK_TICKER`와 동일 티커 재사용)

4개 신호를 각각 점수화해 합산(총점 -100~+75, 대칭이 아닌 이유: 고점대비낙폭은 "패널티 전용" 신호라
플러스 기여가 없음):

| 신호 | 기여 범위 | 규칙 |
|---|---|---|
| 200일선 대비 위치 | ±25 | 종가 > SMA200 → +25, 아니면 -25 |
| 50/200일 골든·데드크로스 | ±25 | SMA50 > SMA200 → +25(골든), 아니면 -25(데드) |
| 시장폭(S&P500 중 200일선 위 종목 비율) | ±25 (선형, 50%=0 기준 30%/70%에서 ±25로 클립) | `clip((breadth% - 50) * 1.25, -25, 25)` |
| 52주 고점 대비 낙폭 | -25~0 (선형, -20%에서 -25 클립) | `clip(drawdown% / 20 * 25, -25, 0)` |

레이블: 총점 ≥ 35 → "강세장", ≤ -35 → "약세장", 그 사이 → "중립/혼조". 데드크로스 신호는 후행성이
크다는 리서치 근거를 UI 캡션에 그대로 명시(과신 방지).

시장폭 계산은 `core.screener.get_universe()`의 S&P500 전체 목록(~500종목)에 대해 각 종목의 종가가
200일선 위인지 확인해야 해서 네트워크 호출이 많음 → 기존 스크리너/미세튜닝 페이지와 동일하게
`job_manager.start()`로 백그라운드 실행 + `core.market_data.get_multiple_price_history()`의 기존
영구 로컬 캐시를 그대로 활용(최초 1회만 느리고 이후는 캐시 히트).

### 4.2 섹터/테마 강도 (`core/sector_strength.py`)

프리셋 딕셔너리 `THEME_UNIVERSE: dict[str, list[str]]` (테마명 → 프록시 ETF 티커 리스트):

- 기존 GICS 11개 섹터: SPDR Select Sector ETF (기술=XLK, 금융=XLF, 헬스케어=XLV, 임의소비재=XLY,
  필수소비재=XLP, 에너지=XLE, 산업재=XLI, 소재=XLB, 유틸리티=XLU, 부동산=XLRE, 커뮤니케이션=XLC)
- 세부 테마: 반도체=[SOXX, SMH], DRAM/메모리=[DRAM], 우주=[UFO, ARKX, ROKT]

테마별 강도 = IBD 방식 `StrengthFactor = 0.4·ROC63 + 0.2·ROC126 + 0.2·ROC189 + 0.2·ROC252`(프록시가
여러 개면 평균) → 전체 테마 집합 내 percentile rank(0~100)로 변환해 "RS 점수"로 표시. 추가로
최근 20거래일 전후의 RS 점수 변화를 "상승/하락/횡보" 추세 화살표로 함께 표시(RRG의 모멘텀 축을
단순화 반영). `core/indicators.py`에 `roc(close, window)` 헬퍼 신규 추가(sma/ema와 동일 패턴).

### 4.3 UI

`app/pages/7_매크로_대시보드.py`에 3번째 탭 "📈 시장 국면 / 섹터 강도" 추가:
- 상단: 강세장/중립/약세장 배지 + 종합점수 + 4개 하위 신호 각각을 `st.metric`으로 분해 표시
- 하단: 테마별 RS 점수 막대차트(내림차순 정렬, dataviz 스킬 가이드 적용) + 3/6/12개월 수익률과
  추세 화살표를 곁들인 표

## 5. 범위에서 제외한 것 (과설계 방지)

- RRG 산점도(4분면) 차트: 아이디어(레벨+모멘텀)만 반영하고 실제 산점도는 만들지 않음
- 테마 목록 UI 편집 기능: 코드 프리셋으로 시작
- 통계/ML 기반 레짐 전환 확률 모델(HMM 등): 룰 기반으로 충분히 설명 가능한 범위로 한정
- 이 국면/강도 지표를 다종목 미세튜닝 엔진의 실시간 탐색 로직에 자동 결합하는 것: `STRATEGY_TUNING_ENGINE_SPEC.md`에
  이미 기록된 것처럼 향후 확장 과제로 남겨둠(이번엔 대시보드 표시까지만)
