# 애널리스트 추정치 매일 기록 (estimate shadow) — 2026-11-10

상태: 구현·테스트 완료, 배포 후 매일 07:05 KST 자동 기록(스케줄러 잡 `estimate_shadow_record`, 기본 켜짐). 성과 미검증, 매매 없음.

## 왜

사용자 요청(2026-11-10): "연구도 실적 추정치 변화 등으로 확장해서 이어서 진행". 추정치 변화(리비전)는 가격 밖의 정보지만
과거 이력(IBES 등, WRDS)은 구할 수 없다(확정). 그래서 **지금부터** yfinance 가 보여 주는 현재 추정치를 기록 시각과 함께 매일 쌓는다.
6~12개월 뒤 이 기록은 미리 보기가 전혀 없는 진짜 표본 밖(out-of-sample) 추정치 변화 자료가 되고, 그때 새 id 로 사전 등록 연구를 한다
(판정 기준은 그 연구에서 결과를 보기 전에 고정). 그 전까지 이 기록으로는 아무것도 매매하지 않는다.

## 무엇을 기록하나 (`core/estimate_shadow.py`)

- 대상: 오늘 기준 S&P 500 구성종목(`data/sp500_historical_constituents.csv` 최신 행), 최대 520종목. 시간 상한 12분, 종목 사이 0.15초.
  상한에 걸리면 멈추고, 시작 위치를 날짜마다 돌려 같은 종목만 계속 빠지지 않게 한다. 처음부터 25종목 연속 실패면 그날은 중단(실패 알림).
- 항목(종목마다, yfinance 1.7 기준): `eps_trend`(0q/+1q/0y/+1y 의 현재·7/30/60/90일 전 컨센서스), `eps_revisions`(7/30일 상향·하향 수),
  `earnings_estimate`·`revenue_estimate`(평균·최저·최고·애널리스트 수·1년 전·성장률), `period_end_dates`(0q 등이 가리키는 기간 끝 — yfinance 내부 값, 없을 수 있음),
  `recommendations_summary`(의견 수), `price_targets`(목표주가).
- 저장: `data/estimate_shadow/estimates.sqlite`, 표 `snapshots(record_date[KST], recorded_at[UTC], ticker, kind, payload JSON, source)`,
  `(record_date, ticker, kind)` 유일 + `INSERT OR IGNORE` — 과거 줄을 고치거나 지우지 않는다(append-only, 시점 기준). 표 `runs` 에 실행마다 요약.
- 읽기: `load_history(ticker, kind)`, `coverage()`.

## 한계

- 출처가 야후 화면 값이다. 응답이 막히거나 형식이 바뀌면 그날은 비고, 빠진 날은 나중에 채울 수 없다.
- 7/30/60/90일 전 값은 야후가 주는 값이라 우리 기록 이전 기간의 변화도 일부 보이지만, 연구 판정에는 **우리가 기록한 시각의 값만** 쓴다.
- 종목 목록은 기록하는 날의 S&P 500 이다(그날 기준이라 생존 편향 없음, 대신 편입 변화로 종목이 바뀐다).
