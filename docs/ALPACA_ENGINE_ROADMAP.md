# Alpaca paper 키 활용 엔진 고도화 로드맵

작성 2026-09-25. **목적: 전략 수립·검증용이며 실거래용이 아니다.** 모든 주문은 paper(모의) 계좌로만 가고 live 계좌 경로는 코드에 없다.
상태 표기: **구현**(코드+mock 테스트) / **제안**(미구현). 실 API 검증은 모든 항목이 아직 0회다(키는 VM 에만 있음).

## 단계별 상태

| 단계 | 목적 | 구현 | 상태 |
|---|---|---|---|
| P0 실 API 검증 | 문서 기반 스키마 가정을 실제 응답으로 확인 | `core/alpaca_verification.py`(기존, 00:40 KST 자동) + 5번째 검사 `market_meta_news` 추가 | 구현. VM 첫 실행 결과 대기 |
| P1 주문 전 점검 | 거래정지·상폐 종목을 주문 전에 표시 | `core/alpaca_market_meta.py`, `scripts/champion_paper_trade.py` 의 `tradability` 출력(경고만, 계획 불변) | 구현 |
| P1 추적오차 | paper 실제 vs 챔피언 가상 수익 괴리 | `core/paper_tracking.py`, 잡 `paper_tracking_refresh` 00:46 KST | 구현. 구간 20개 미만이면 추적오차 None. 원인 '분해'는 하지 않고 후보만 나란히 표시 |
| P2 비용 환류 | 5/10/25bp 가정을 실측으로 보정 | `core/cost_calibration.py`(기존, 00:42 KST) → `trade_ledger`·`strategy_variants` 에 옵트인 `measured` 시나리오 | 구현(다른 세션). 체결 30건 미만이면 사용 안 함 |
| P2 뉴스 연구 | 막혀 있던 과거 뉴스 이벤트 스터디 | `core/alpaca_news.py`(PIT), `core/news_event_study.py`, `scripts/news_event_study.py`(수동 실행) | 구현. 감성 판단 없음, 이벤트 30건 미만이면 평균 None |
| P3 자동 주문 | 사람 `--confirm` 없이 paper 포워드 테스트 표본 축적 | `core/paper_auto_trade.py`, 잡 `paper_auto_trade` 화~토 06:10 KST | 구현, **기본 꺼짐**. `/processes` 로 켜야 동작 |

## P3 자동 주문의 안전 조건 (하나라도 거짓·모름이면 제출 안 함)
paper 엔드포인트 확인 → 키 존재 → 최근 7일 P0 전체 PASS → 미 동부 오늘이 개장일(캘린더 조회 실패=건너뜀) → 오늘 미제출 →
계좌 정상 → 매수 종목 전부 거래가능 확인(조회 실패=불가) → 주문 총액 ≤ 자산×1.1. 이후 기존 `submit_plan` 의 슬리브 보류 게이트·
회차 ID·멱등성이 다시 적용된다. 결과는 텔레그램 1건.

## 알려진 한계
- 제출 시각(장 마감 뒤)에 낸 market/day 주문이 다음 개장 시가에 체결된다는 것은 Alpaca 문서 기준 가정이다.
- 챔피언 가상 원장은 00:12 KST(미 장중)에 비중을 정하고 자동 주문은 06:10 KST(장 마감 뒤)에 계획을 다시 계산한다. 이 시차가 추적오차에 섞인다.
- paper 체결은 실계좌 체결과 같다는 보장이 없다(IEX 피드, 유동성 모델).

## 다음 결정(사람)
1. main 푸시 → VM 00:40 검증 결과 확인. 2. PASS 후 `paper_auto_trade` 를 켤지. 3. 뉴스 연구 대상 티커·기간.

## 하지 않는 것
live 계좌 연결, IEX 를 SIP 와 동일시하는 주장, 표본 부족 시 대표값 주장, 검증 PASS 전 자동 주문.
