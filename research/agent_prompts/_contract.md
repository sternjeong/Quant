# 공통 계약 (모든 역할이 지킨다)

- 목적: 무료 일봉 데이터로 검증 가능한 주식·ETF 전략 가설을 만든다. 실거래가 아니라 검증용이다.
- 쓰기는 지시받은 경로에만 한다. 다른 파일을 바꾸면 배치가 자동으로 되돌리고 기록한다.
- 네트워크 호출·파일 시스템 탐색·외부 패키지 설치를 하는 신호 코드는 금지다.
- 분봉·데이트레이딩·옵션·공매도·레버리지 전략은 만들지 않는다(데이터 제약, 사용자 결정).

## 가설 스펙 v1 (research/hypotheses/<id>/spec.json)
```json
{
  "id": "H-YYYYMMDD-NNN",
  "parent": null,
  "source": "씨앗 출처(예: scout/2026-10-05.md#3, failures.md 교훈)",
  "thesis": "한두 문장의 검증 가능한 주장(무엇이 왜 초과수익을 내는가)",
  "universe": {"type": "etf_core | sp500_pit | list", "tickers": ["list 일 때만, 최대 200"]},
  "signal": {"params_grid": [{"lookback": 60}, {"lookback": 120}]},
  "portfolio": {"top_k": 10, "rebalance": "weekly | monthly", "max_weight": 0.1},
  "period": {"start": "2010-01-01", "end": null},
  "kill_criteria": {"min_rebalances": 24, "max_drawdown": 0.4}
}
```
- params_grid 는 1~8개. **조합 하나하나가 시도 1회로 영구 누적**되어 통과 기준을 엄격하게 만든다. 꼭 필요한 조합만 넣는다.
- max_weight ≤ 0.25, top_k 1~50, period.start ≥ 2005-01-01, min_rebalances ≥ 12.
- 동결된 스펙은 바꿀 수 없다. 개선안은 parent 를 지정한 새 가설이다.

## 신호 함수 계약 (research/hypotheses/<id>/signal.py)
```python
def score(prices: dict[str, pd.DataFrame], as_of: pd.Timestamp, params: dict) -> dict[str, float]:
    ...
```
- prices: 종목별 일봉(Open/High/Low/Close/Volume, Adj Close 는 있을 수도 있음). 엔진이 as_of 종가까지 잘라서 준다.
- 반환: {종목: 점수}. 점수가 큰 순으로 top_k 를 동일가중으로 담는다. 양수·유한한 점수만 후보가 된다(담지 않을 종목은 빼거나 0 이하).
- 순수 함수여야 한다: 전역 상태·파일·네트워크·난수(시드 없는) 금지. pandas, numpy, math 만 사용.
- 이력이 부족한 종목은 조용히 건너뛴다(예외를 던지지 않는다).

## 판정은 코드가 한다
에이전트는 성과를 판정하지 않는다. 동결된 가설은 결정론 심판이 판정한다: Deflated Sharpe ≥ 0.95(누적 시도 수 반영),
레짐(강세/약세/횡보)별 SPY 대비 과반 우위, SPY 상관 < 0.9, 챔피언 상관 < 0.7, 최대낙폭·리밸런싱 수 기준.
