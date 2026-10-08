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
- **글자 수 제한(넘으면 결정론 검사에서 바로 탈락):** title 1~80자, thesis 1~500자, source 1~300자. 긴 논증은 signal.py 주석에 쓴다.
- pool: champion40 = 현 규칙과 같은 '섹터별 그 시점 시총 상위 40종목'(반기 갱신), sp500_pit = 그 시점 S&P500 전체.
- top_k 3~10, hold_months 1·3·6(매월 / 1·4·7·10월 / 1·7월 첫 거래일에 다시 고름).
- topic: "selection"(무엇을 고르나) | "entry"(언제 사나) | "exit"(언제 파나) | "guru"(거장 13F 를 어떻게 쓰나 — data 에 "guru13f") — 지시받은 주제를 그대로 쓴다. 사용자가 R&D 센터에서 주제별로 켜고 끈다.
- entry(언제 사나, 기본 {"type":"close"} = 리밸런싱 날 종가):
  {"type":"delay","days":1~20} — 그 거래일 수만큼 뒤 종가에 산다.
  {"type":"pullback","sma":3~50,"max_wait":1~40} — 그 안에 종가가 sma일 이동평균 아래로 내려온 날 사고, 안 오면 max_wait 째 종가에 산다.
  사기 전까지 그 몫은 현금(수익 0)이다.
- exit(언제 파나, 기본 {"type":"none"} = 다음 리밸런싱까지 보유) — 판 뒤에는 다음 리밸런싱까지 현금:
  {"type":"trailing_stop","stop_pct":0.05~0.40} 고점 대비 하락 / {"type":"take_profit","tp":0.05~2.0} 진입가 대비 상승 /
  {"type":"time_stop","days":5~120} 진입 뒤 거래일 수 / {"type":"trend_break","sma":10~200} 종가가 이동평균 아래로.
- 무작위 기준선(G1)은 같은 entry·exit 를 그대로 쓴 무작위 선정과 비교한다 — 진입·청산 규칙 자체의 효과는 G2(현 규칙 대비)로 판정된다.
- 참고(이미 시험해 탈락): 보유 중 15% 손절(S-SEED-003), 3개월 보유(002), 매매 실행 R&D 의 지정가·눌림목·분할·익절(research/results/exec-rnd-v1, sprint-2w F4).
- params_grid 1~4개. **조합 하나가 시도 1회로 영원히 누적**되어 모든 후보의 통과 기준(G2)을 엄격하게 만든다. 1~2개를 권한다.
- 동결된 스펙은 바꿀 수 없다. 개선안은 parent 를 지정한 새 id 다.

## 신호 (research/satellite_lab/variants/<id>/signal.py)
```python
def score(prices: dict[str, pd.DataFrame], as_of: pd.Timestamp, params: dict) -> dict[str, float]:
```
- prices: 그 리밸런싱일의 후보 풀 종목별 일봉(Open/High/Low/Close/Volume), **리밸런싱일 전날(as_of) 종가까지**, 리밸런싱일 전 730달력일(약 2년, 현 규칙과 같은 창).
- 반환: {종목: 점수}. 유한한 점수가 큰 순(동점은 티커순)으로 top_k 를 동일가중으로 산다. 담지 않을 종목은 빼거나 NaN.
  음수 점수도 후보가 된다(현 규칙과 같음) — 제외하려면 dict 에서 뺀다.
- 재무·실적 정보(2026-10-08): spec.json 에 `"data": ["fundamentals"]` 를 넣으면 `score(prices, as_of, params, ctx)` 로 불린다.
  `ctx.fundamentals(종목)` → as_of 까지 SEC 에 공시된 것만: sic(업종 코드), gp_assets(최근 연간 매출총이익/총자산), rev_yoy·rev_yoy_prev
  (최근·직전 분기 매출 전년 대비 성장), ni_yoy(순이익), last_earnings(최근 실적 발표 8-K 날짜) — 모르면 None 또는 dict 자체가 None.
  `"data": ["guru13f"]` 면 `ctx.guru(종목)` → as_of 까지 공시된 거장 13F(버핏·버리·애크먼·우드·드러켄밀러·테퍼·클라만, 2013년 2분기~):
  n_holders(보유 거장 수), n_new(최근 공시에서 새로 산 거장 수), n_top5(상위 5 보유인 거장 수), max_weight(거장 포트폴리오 내 최대 비중). 데이터 없으면 {}.
  None 을 '나쁨'으로 취급해 빼지 말 것(상장폐지 회사가 데이터에서 빠져 결과가 부풀려진다). 시작 목록 S-SEED-010~017 이 예시.
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
