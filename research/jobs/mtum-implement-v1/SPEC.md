# mtum-implement-v1 — French 대형주 승자 모멘텀의 실제 ETF 이전 검증

## 질문과 근거

`contrib-reval-longrun-v1`의 6 ME×Prior return 대형주 승자 50% + 시장 50%(BH50)는 선택·확인 장기 구간의 시나리오 B에서 `CONTRIB_BEATS_MARKET`를 통과했다. 하지만 이 포트폴리오는 투자 가능한 ETF가 아니고, 실제 SPY·섹터 ETF 세후 비교(`spy-sector-blend-v1`, `contrib-reval-sector-v1`)는 통과하지 못했다. 이 실험은 BH50의 시장 구성은 고정한 채 실제 거래 가능한 iShares MSCI USA Momentum Factor ETF(MTUM)로 모멘텀 다리만 대체한다. MTUM은 2013년 상장이라 긴 표본이 없으며 이 검정은 최근 10년 안팎의 이행 가능성 시험일 뿐이다.

## 사전 고정 전략·자료

- 후보 한 개: SPY 50% + MTUM 50%, 1월 첫 거래일에만 50/50으로 재조정. 창 시작일에도 50/50으로 진입한다. 매달 적립금은 `underweight_first`로 집행되고 매도하지 않는다. 월 적립과 1월 재조정은 기존 `core/tax_fx.simulate` 규칙을 따른다.
- 대조군: 같은 날짜·같은 납입의 SPY 100% 매수 후 보유. 다른 신호/비중/주기는 시험하지 않는다.
- 가격: yfinance `Close`와 `Adj Close`(배당 재투자 추정), 일별 USDKRW `core.tax_fx.usdkrw_series()`. MTUM 상장 전 데이터를 역채우지 않는다. 두 가격의 공통 구간 중 MTUM 거래일 252일이 지난 다음 거래일부터 평가한다. 작은 quote 공백은 최대 3거래일 전진 채움; 그보다 긴 공백, 판정기간 종가/환율 누락은 실행 실패다.
- 계좌: `tax_fx.AccountConfig()` 카카오 기본값, 초기 1,000만 원 + 매월 15만 원, 다음 달 첫 거래일부터 적립, 수수료·환전·배당 원천징수·양도세 22%/연 250만 원 공제 적용. 종료일에 전부 청산한 뒤 세금 차감 금액으로 IRR을 낸다.
- 데이터 시작: common MTUM/SPY history에서 252거래일 워밍업 후의 첫 거래일(예상 2014년 4월); 매월 첫 거래일마다 5년 계좌를 시작한다. 끝이 2024-09-30 이하인 창만 판정한다. 이후 종료 창은 결과에 넣지 않는다. 단일 연속 계좌 전체기간 결과는 참고 보고다.

## 판정

단일 후보가 모든 관문을 만족할 때만 `PASS_FORWARD_CANDIDATE`(전진 원장에 올려 검토할 후보, 채택 아님)다.

1. 판정 5년 창의 청산 후 최종 자산이 SPY보다 큰 비율 ≥70%.
2. 창별 세후 XIRR 차이 중앙값 ≥+0.5%p, 10분위 ≥−1.5%p.
3. 창별 시간가중 MDD 중앙값은 SPY보다 5%p 넘게 나쁘지 않다.
4. 연속 판정기간 일별 세후 TWR 차이에 대한 paired circular 126거래일 block bootstrap 2,000회(seed 20261019), CAGR 차이의 90% 하한 >−0.5%p.

창들은 크게 겹친다. 창 승률은 독립 시행 횟수처럼 해석하지 않는다. 탈락은 `classify_fail`의 관측 일별 IR 및 `power_report(10.45, 1)`로 `FAIL`/`FAIL_UNDERPOWERED`를 함께 기록한다. 이 검정력은 단일 고정 후보만 반영하며 이전 연구 탐색 전체를 보정하지 않는다. 통과해도 이미 살펴본 현대 자료의 전진 후보일 뿐 독립 확인은 다음 거래일부터 동결 원장으로 수행한다.

## 한계·보호

MTUM은 2013-04-16 출시되어 역사가 짧고 판정 창은 중첩된다([iShares 공식 팩트시트](https://www.ishares.com/us/literature/fact-sheet/mtum-ishares-msci-usa-momentum-factor-etf-fund-fact-sheet-en-us.pdf)). MTUM은 MSCI USA Momentum 지수를 추종하며 French의 대형주 prior-return 분류와 신호·구성·교체 규칙이 같지 않다. 이 실험은 동일 전략 복제가 아니라 투자 가능한 모멘텀 ETF 대체물의 결과를 평가한다. ETF 비용·tracking difference는 Adj Close에 반영된 범위만 포함되며 별도 호가 차이는 10bp 매매 수수료 근사에 포함되지 않는다. tax_fx는 세무 신고용이 아니다. 기존 엔진·챔피언·원장은 수정하지 않는다.

실행 계약: `python research/jobs/mtum-implement-v1/run.py --out <dir> --checkpoint <dir>`; 확인 모드 `--smoke`는 합성자료만 쓴다.
