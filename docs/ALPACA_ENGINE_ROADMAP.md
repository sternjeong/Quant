# Alpaca paper 키 활용 엔진 고도화 로드맵

작성 2026-09-25. 상태 표기: **구현**(코드+mock 테스트) / **제안**(미구현). 실 API 검증은 모든 항목이 미완료다.

## 이미 구현(2026-09-24, 실 API 미검증)
배당·분할 현금흐름(`corporate_actions`), 실체결 슬리피지(`execution_reconciliation`), 가격 교차검증(`price_crosscheck`),
계좌-목표 괴리(`account_sync`), 거장 자동 추적(`guru_schedule`).

## 이번 추가(구현, 실 API 미검증)
| 모듈 | 메우는 구멍 | 비고 |
|---|---|---|
| `core/alpaca_market_meta.py` | 주문 단계에서야 알게 되는 거래정지·상폐, 추정에 의존하는 휴장일 | 종목별 격리, 조회 실패를 거래불가로 단정하지 않음 |
| `core/alpaca_news.py` | FMP/Finnhub 유료, Alpha Vantage 25콜/일 때문에 막힌 과거 뉴스 실험 | `created_at` 기준 PIT, 감성 점수는 만들지 않음 |
| `scripts/verify_alpaca_meta_news.py` | 위 둘의 스키마 가정 확인 | VM 에서 1회 실행 |

## 제안(미구현, 우선순위 순)
1. **P0 실 API 검증 6종 실행** — 기존 4개 + 위 1개. 스키마가 다르면 파싱 지점만 수정. 이게 끝나야 아래가 의미가 있다.
2. **P1 주문 전 사전 점검 연결** — `champion_paper_trade.py --submit` 직전에 `check_tradability` 로 목표 종목을 확인하고 불가 종목은 계획에서 사람에게 표시(자동 차단은 사람 결정 사항).
3. **P1 포워드 테스트 추적오차** — paper 계좌 자산곡선 vs 챔피언 가상 수익. 괴리의 원인을 슬리피지·미체결·배당 시차로 분해. `account_snapshot_sync` 가 쌓는 스냅샷이 원료다.
4. **P2 실측 비용 모델 환류** — 체결 30건 이상 쌓이면 `compare_with_cost_assumptions()` 결과로 5/10/25bp 가정을 보정하고 튜닝 엔진 비용 입력에 반영(보정은 사람 승인 후).
5. **P2 뉴스 이벤트 스터디 연결** — `alpaca_news` 를 매크로 이벤트 스터디(메모: FRED 외 뉴스 부재)에 공급. 감성 분류기는 별도 검증 후.
6. **P3 자동 주문 루프** — 게이트·회차 ID 는 있으나 현재 사람이 `--submit --confirm` 을 줘야 한다. 1~4 가 실계정에서 검증된 뒤에만 paper 한정으로 검토.

## 하지 않는 것
live 계좌 연결, IEX 데이터를 SIP 와 동일시하는 주장, 실측 n<30 의 대표값 주장, 검증 전 자동 주문.
