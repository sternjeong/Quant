# 새틀라이트 R&D 계약 (sat_designer · sat_critic 이 지킨다)

- 목적: 챔피언 새틀라이트(포트폴리오의 15%, 개별 S&P500 종목)를 **어떤 규칙으로 고를지** 더 나은 방법을 찾는다.
  비교 대상은 현 규칙(research/satellite_lab/seeds/S-SEED-000)과 같은 후보 풀에서의 무작위 선정이다.
- 쓰기는 지시받은 폴더(research/satellite_lab/variants/<id>/)에만 한다. 다른 파일을 바꾸면 배치가 되돌린다.
- 무료 일봉 데이터만. 분봉·옵션·공매도·레버리지·재무제표·뉴스·외부 파일·네트워크는 신호에서 쓸 수 없다.

## 스펙 (research/satellite_lab/variants/<id>/spec.json)
```json
{
  "id": "S-YYYYMMDD-NNN",
  "parent": "S-SEED-000 또는 다른 S-… 또는 null",
  "title": "20자 안팎의 한국어 이름",
  "thesis": "왜 이 규칙이 현 규칙보다 종목을 더 잘 고르는가(검증 가능한 한두 문장)",
  "source": "근거(논문·기존 실패 교훈·context.md 의 어떤 결과)",
  "pool": {"type": "champion40 | sp500_pit"},
  "signal": {"params_grid": [{"lookback": 252}]},
  "portfolio": {"top_k": 3, "hold_months": 6},
  "exit": {"type": "none"}
}
```
- pool: champion40 = 현 규칙과 같은 '섹터별 그 시점 시총 상위 40종목'(반기 갱신), sp500_pit = 그 시점 S&P500 전체.
- top_k 3~10, hold_months 1·3·6(매월 / 1·4·7·10월 / 1·7월 첫 거래일에 다시 고름).
- exit: {"type":"none"} 또는 {"type":"trailing_stop","stop_pct":0.05~0.40} (보유 중 고점 대비 하락 시 팔고 다음 리밸런싱까지 현금).
- params_grid 1~4개. **조합 하나가 시도 1회로 영원히 누적**되어 모든 후보의 통과 기준(G2)을 엄격하게 만든다. 1~2개를 권한다.
- 동결된 스펙은 바꿀 수 없다. 개선안은 parent 를 지정한 새 id 다.

## 신호 (research/satellite_lab/variants/<id>/signal.py)
```python
def score(prices: dict[str, pd.DataFrame], as_of: pd.Timestamp, params: dict) -> dict[str, float]:
```
- prices: 그 리밸런싱일의 후보 풀 종목별 일봉(Open/High/Low/Close/Volume), **리밸런싱일 전날(as_of) 종가까지**, 리밸런싱일 전 730달력일(약 2년, 현 규칙과 같은 창).
- 반환: {종목: 점수}. 유한한 점수가 큰 순(동점은 티커순)으로 top_k 를 동일가중으로 산다. 담지 않을 종목은 빼거나 NaN.
  음수 점수도 후보가 된다(현 규칙과 같음) — 제외하려면 dict 에서 뺀다.
- 순수 함수: pandas, numpy, math 만. 전역 상태·파일·네트워크·시드 없는 난수 금지. 이력 부족 종목은 조용히 건너뛴다.
- 같은 폴더에 test_signal.py: 합성 데이터로 (1) 모든 params 조합에서 dict[str,float] 반환 (2) 이력 부족 종목 건너뜀
  (3) as_of 이후 데이터를 바꿔도 결과가 같음. `python -m pytest research/satellite_lab/variants/<id>` 통과.

## 판정은 코드가 한다 (core/satellite_lab.py, sat-judge/v1 — 결과를 보기 전에 고정)
같은 시뮬레이터·같은 풀·편도 8bp 비용으로 2010년~현재. 마지막 2년은 떼어 두고 파라미터는 그 앞(IS)에서만 고른다.
- G1 IS 샤프가 같은 구조로 무작위로 고른 200번의 95백분위 이상 (우연보다 나은가)
- G2 현 규칙 대비 일별 초과수익의 Deflated Sharpe ≥ 0.95, 누적 시도 수 반영 (다중검정 보정)
- G3 떼어 둔 2년: 현 규칙보다 샤프가 높고 무작위 분포 중앙 이상
- G4 숫자 파라미터를 ×0.5·×1.5 로 바꿔도 현 규칙 대비 초과 샤프가 모두 양수, 중앙값 ≥ 선택값의 절반
- G5 IS 최대낙폭이 현 규칙보다 10%p 넘게 나쁘지 않음, IS 리밸런싱 12회 이상
통과는 '사람 검토 대기'일 뿐 챔피언에 자동 반영되지 않는다. 에이전트는 성과를 판정하지 않는다.
