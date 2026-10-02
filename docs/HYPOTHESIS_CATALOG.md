# 가설 카탈로그 — 주식·코인 매매자들이 쓰는 전략과 필요한 정보 (2026-10-02 조사)

사용자 요청: 구글링으로 주식·코인 매매 전략과 그에 필요한 정보를 조사하고 가설을 세운다. 여기 적힌 것은 **가설**이며 검증 결과가 아니다.
각 가설은 시험하기 전에 사전 등록 연구(research/jobs/<id>)로 판정 규칙을 고정한 뒤 돌린다.

## 0. 조사에서 얻은 전제 (시험 설계에 반영)

- **공개되면 줄어든다.** 학술 논문으로 공개된 수익 예측 신호는 표본 밖에서 평균 26%, 공개 뒤 58% 약해졌다(McLean & Pontiff 2016).
  → 문헌 수치를 기대값으로 쓰지 않고, 우리 데이터·최근 구간으로 다시 잰다.
- **차트 매매는 비용·데이터 스누핑을 넣으면 대부분 사라진다.** 95개 연구 중 56개가 수익을 보고했지만 비용·사후 선택을 감안하면 줄고,
  최근 일봉 기반 연구에서는 주식·외환·선물 모두 크게 약해졌다(Park & Irwin 리뷰). → tech-rnd-v1 이 이 질문을 우리 데이터로 직접 시험 중.
- **유명한 이벤트 효과도 사라진다.** FOMC 발표 전 상승(pre-FOMC drift)은 2015년 이후 사실상 사라졌고(Kurov·Wolfe·Gilbert 2021),
  실적 발표 후 표류(PEAD)는 대형주에서 2006년 무렵 거의 0 이 됐다.
- **코인은 아직 추세가 강하다는 보고가 있다.** 8개 주요 코인 2020~2025 시계열 모멘텀이 연 32% 수준(표본이 짧고 강세장 포함 — 그대로 믿지 않는다).
  펀딩비(무기한 선물) 캐리는 수익이 줄어드는 중이고 공매도·파생상품이 필요해 이 시스템의 계약(롱온리·무레버리지) 밖이다.
- **소셜 심리는 밈 종목에만 약하게 통한다.** WallStreetBets 감성은 GME·AMC 같은 밈 종목 외에는 신호가 거의 없고, 구글 검색량이 감성보다 약간 낫다.
- **13F 따라 사기(거장 복제)는 공시 지연(최대 45일) 때문에 효과가 약하다**는 보고와, 유동성 있는 보유만 복제하면 일부 펀드는 원본을 이긴다는 보고가 섞여 있다.

## 1. 우리가 이미 가진 정보 (2026-10-02 확인)

| 정보 | 이 시스템의 원천 | 과거 시험 가능? |
|---|---|---|
| 일봉 가격·거래량(주식·ETF) | core/market_data.py (yfinance, 캐시) | 예(상장폐지 일부 결측) |
| 코인 일봉 | yfinance BTC-USD 2014-09~, ETH-USD 2017-11~ | 예 |
| 변동성 기간구조 | ^VIX 2005~, ^VIX3M 2006-07~ | 예 |
| 거시 지표 | core/fred_data.py (금리차·실업 등; 하이일드 스프레드는 최근 3년만) | 대부분 예 |
| 그 시점 S&P500 편입·시가총액 | core/point_in_time_universe.py, point_in_time_market_cap.py | 예 |
| 공시 문구 변화(10-K/10-Q) | core/filing_changes.py (EDGAR) | 부분(조회량 상한) |
| 실적 일정·가이던스 | core/earnings_events.py, guidance_event_provider.py | 앞으로만(과거 이력 짧음) |
| 거장 13F 보유 | core/guru_tracker.py | 부분(최근 분기 위주) |
| 뉴스 | core/news_digest.py, alpaca_news.py | 앞으로만 |
| 팩터 수익(French) | core/french_factors.py | 예 |
| 없음 | 내부자 거래(Form 4), 공매도 잔고, 풋콜 비율, 구글 검색량, 온체인(MVRV 등), 펀딩비 | 새로 모아야 함 |

## 2. 가설 목록

표기: **[바로]** 지금 데이터로 과거 시험 가능 · **[수집]** 데이터 수집부터 · **[앞으로]** 과거로 정직하게 시험 불가 → 기록만(shadow) · **[범위 밖]** 계약 밖(공매도·레버리지·분봉).

### A. 변동성·위험 신호 (코어의 약점: 2020년 같은 급락에 늦음)
- **A1 [바로] VIX 기간구조 급락 필터** — VIX/VIX3M > 1(단기 공포가 장기보다 큼, 역전)이면 다음 날 코어 위험자산 절반 → 단기국채. SPY 200일선(월 1회)보다 빨리 반응해 2020-03 같은 급락을 줄인다.
  비교: 현 코어(200일선 월간). 위험: 잦은 오신호로 반등을 놓침(손익분기 비용·횟수를 같이 본다).
- **A2 [바로] VIX 수준 + 추세 결합** — VIX > 30 이고 SPY < 50일선일 때만 축소. A1 보다 신호가 드물어 회전율이 낮다.
- **A3 [바로] 실현 변동성 급등** — SPY 20일 실현변동성이 1년 분포의 상위 5%면 축소. (코어 변동성 타깃팅은 이미 기각 — 여기선 '극단에서만' 켜는 스위치라는 점이 다르다.)

### B. 코인 (새 자산군)
- **B1 [바로] 비트코인을 코어 18번째 자산으로** — 12개월 모멘텀 순위에 BTC-USD 를 넣는다(상위 4 에 들면 21.25%). 상관이 낮은 자산이 추가되면 분산 효과가 있다는 가설.
  위험: 변동성이 주식의 3~4배라 한 자리 21% 는 과도할 수 있음 → B2 와 비교.
- **B2 [바로] 코인 추세 슬리브 5%** — BTC(·ETH)를 지수이동평균 여러 기간(예 20/50/100일) 위에 있을 때만 보유, 아니면 단기국채. 포트폴리오의 0~5%.
  문헌의 시계열 모멘텀 결과를 우리 데이터(2014~)로 재현하고, 챔피언과 결합했을 때 샤프·낙폭을 본다.
- **B3 [바로] 코인 주말 효과·반감기 주기** — 달력 효과는 공개 뒤 사라지는 경향이 강해(전제 0) 낮은 우선순위, 반대 증거 확인용.
- **B4 [수집] 온체인 과열(MVRV)·거래소 유입** — 무료 원천이 제한적. 일부 지표(채굴·거래소 잔고)는 공개 API 로 일 단위 수집 가능한지 먼저 확인.
- **B5 [범위 밖] 펀딩비 캐리·현선물 베이시스** — 공매도·파생상품 필요.

### C. 이벤트·정보 (개별주 = 새틀라이트와 결합)
- **C1 [앞으로] 실적 서프라이즈 확인 후 매수(PEAD × 새틀라이트)** — 새틀라이트 후보 중 최근 실적이 예상치를 웃돈 종목만. 대형주 PEAD 는 거의 사라졌다는 보고가 있어
  단독이 아니라 '모멘텀 + 실적 확인' 결합 가설. 과거 실적 서프라이즈 이력이 부족해 기록만부터.
- **C2 [수집] 내부자 순매수 군집** — 여러 임원이 한 달 안에 장내 매수한 종목. SEC Form 4(EDGAR) 일괄 수집이 필요. 새틀라이트 후보 가점/거부권으로 결합.
- **C3 [수집] 13F 거장 합의 종목** — 여러 추적 펀드가 새로 산 종목. 공시 지연 45일을 그대로 반영해야 공정하다. 이미 있는 guru_tracker 를 과거 13F 로 확장.
- **C4 [바로 일부] 공시 문구 변화(lazy prices)** — 10-K 위험 문구가 크게 바뀐 종목을 피한다. 이미 filing_veto_shadow 가 기록 중 — 과거 재구성으로 표본을 늘릴 수 있는지 확인.
- **C5 [수집] 공매도 잔고 급증 종목 회피** — FINRA 반월 공시. 새틀라이트 거부권 후보.

### D. 달력·시점 (대부분 공개 뒤 약해짐 — 확인용)
- **D1 [바로] FOMC 발표 전 상승** — 2015년 이후 사라졌다는 보고를 우리 데이터로 확인(사라졌으면 기각 기록).
- **D2 [바로] 밤사이 vs 장중 수익** — 코어 ETF 수익이 주로 밤사이(종가→다음 날 시가)에 나는가. 매매 시점(종가 vs 시가)에 대한 실행 R&D 보강.
- **D3 [범위 밖·확인] 월말 효과·Sell in May** — 이미 실패 목록(research/agent_prompts/dead_ends.md).

### E. 심리·대체 데이터
- **E1 [수집] 구글 검색량 급증** — 밈 종목에서만 3~7일 예측력 보고. 개별 대형주 새틀라이트에는 약할 것으로 예상 — 우선순위 낮음.
- **E2 [수집] 풋콜 비율·AAII 심리 극단값(역발상)** — 극단적 공포일 때 코어 축소를 늦추는 신호로 결합 가설.
- **E3 [앞으로] 뉴스 감성** — 이미 뉴스를 모으고 있다. 기록만부터(과거 재구성 시 미래 정보 위험).

### F. 결합·시너지 가설 (기존 엔진과 섞을 때)
- **F1 [바로] A1 은 언제 코어에 도움이 되나** — 급락 국면(2008·2020·2022)에서만 이기고 횡보장에서 잃는지 국면별로 분해.
- **F2 [바로] 코인 슬리브(B2)는 새틀라이트를 대신할까, 더할까** — 새틀라이트 15% 일부를 코인 추세로 바꿨을 때와 코어에서 떼어 더했을 때 비교.
- **F3 [바로] 차트 규칙 × 국면** — tech-rnd-v1 R2·R3 에서 시험 중(약세장·고변동에서만 평균회귀 규칙).
- **F4 [앞으로] AI 국제정세 의견 × 코인·원자재** — geo_shadow 기록이 쌓이면 원자재(DBC)·에너지(XLE)·코인에 대한 −1/+1 의견의 적중률을 따로 본다.

## 2-1. 1차 결과 (info-rnd-v1, 2026-10-02 실데이터 — research/results/info-rnd-v1/REPORT.md)

- **A(빠른 급락 필터) — 모두 기각, 현 코어 유지.** 13개 필터 전부 현 규칙(월간 200일선)보다 나빴다. VIX 기간구조 필터는 2008·2020 에서
  최대 +2.7%·+4% 도왔지만 2015-16·2018 4분기·2022·2025 관세 급락에서 잦은 오신호로 그만큼 잃었다. 느린 필터가 오신호를 피하는 셈이다.
- **B(코인) — 아슬아슬하게 탈락, 가장 유망.** 비트코인을 코어 18번째 자산으로 넣으면 앞 구간 샤프 1.17(현 0.67), DSR 0.95, PBO 16% 로 세 관문을
  넘었지만 떼어 둔 2년 샤프 0.99 < 1.04 로 탈락. 코인 추세 슬리브 5%(코어에서)는 앞 구간 0.96·최근 2년 1.11~1.14 로 둘 다 현 규칙보다
  나았지만 사전 등록상 앞 구간 1위만 판정 대상이라 정식 판정을 받지 않았다. 최근 2년을 이미 봤으므로 **앞으로 기록(shadow)으로만** 정직하게 확인 가능.
  주의: 2015~2024 는 비트코인의 역사적 강세장이고 비트코인 자체가 살아남은 코인이다(생존편향).
- **D2(밤사이 vs 장중)** — 주식 ETF 대부분은 밤사이 수익이 더 크다(XLK 밤 +10.8% vs 장중 +6.5%). 종가 매수가 다음 날 시가 매수보다 나았던
  매매 실행 R&D 결과와 일치.

## 3. 다음에 할 일 (제안)

1. **info-rnd-v1 (바로 시험 가능한 것 묶음)**: A1·A2·A3, B1·B2(·B3 확인), D1·D2, F1·F2 — 사전 등록 후 VM 실행기에서 돌린다.
2. **데이터 수집 파이프라인**: C2(Form 4), C3(과거 13F), C5(공매도 잔고), E2(풋콜·AAII) — 수집기를 만들고 쌓이는 대로 과거 재구성이 가능한 것은 백테스트, 아닌 것은 기록만.
3. **기록만(shadow)**: C1, E3 — 이미 있는 원장 구조(candidate_ledger, geo_shadow)에 붙인다.

## 출처

- McLean & Pontiff, *Does Academic Research Destroy Stock Return Predictability?* — https://Www.Gwern.net/doc/economics/2016-mclean.pdf
- Park & Irwin, *The Profitability of Technical Analysis: A Review* — https://ageconsearch.umn.edu/record/37487/files/AgMAS04_04.pdf
- Kurov·Wolfe·Gilbert, *The Disappearing Pre-FOMC Announcement Drift* — https://www.skidmore.edu/economics/documents/KurovWolfeGilbert-TheDisappearingPre-FOMC-Announce-Drift-200914.pdf
- PEAD 감쇠 — https://business.columbia.edu/sites/default/files-efs/imce-uploads/CEASA/Events%20Page/PEAD_Declined_over_time.pdf , https://quantpedia.com/?p=4238
- 코인 모멘텀 — https://www.journals.vu.lt/BATP/en/article/view/44540 , 코인 자산군 개관 https://arxiv.org/pdf/2510.14435
- 펀딩비·캐리 — https://www.bitmex.com/blog/funding-mean-reversions-2018 , https://tradingstrategy.ai/docs/learn/carry-trade.html
- 온체인 지표 — https://cse.hkust.edu.hk/~rossiter/independent_studies_projects/trading_bitcoin_onchain_data/trading_bitcoin_onchain_data.pdf
- 밤사이 수익 — https://www.advisorperspectives.com/articles/2022/06/24/night-moves-is-the-overnight-drift-the-grandmother-of-all-market-anomalies
- 소셜 심리 — https://arxiv.org/pdf/2507.22922 , https://neudata.co/literature-reviews/can-twitter-and-google-sentiment-lead-stock-market-returns
- 13F 복제 — https://www.cxoadvisory.com/?p=45478 , https://whalewisdom.com/help/backtesting_whitepaper
- 내부자 거래 × PEAD — https://clsbluesky.law.columbia.edu/2018/06/05/post-earnings-announcement-drift-and-corporate-insider-trading/
