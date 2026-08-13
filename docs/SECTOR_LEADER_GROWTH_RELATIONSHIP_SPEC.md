# 섹터별 대표 ETF · 대장주 · 성장주 관계 분석 (논의 노트)

> **상태: 구현 완료, 같은 날 후속 확장까지 반영 (2026-07-15).** 새 독립 페이지(사용자가 "페이지를 따로
> 만들어달라"고 명시). 핵심 로직은 `core/sector_leaders.py`(신규), 기존 `core/sector_strength.py`(대표
> ETF 프록시 재사용)와 `core/screener.py`/`core/valuation.py`(시가총액/이익성장률 재사용) 위에 얹는다.
> 같은 날 사용자가 (1) 성장주에 애플/MS 같은 초대형주가 섞이는 문제, (2) 기술주 테마 세분화(방산/
> 냉각/사이버보안/클라우드/로보틱스 신규), (3) "대형주 추세추종→소형주" 레깅 후보 플래그를 추가
> 요청 — 6절 참고.

## 1. 요청 요약 (2026-07-15)

"각 섹터마다 대표하는 ETF, 대장주, 성장주들의 관계를 정량적으로 분석할 수 있는 페이지를 따로 만들어줘."
— 섹터/테마별로 (1) 대표 ETF, (2) 그 섹터의 대장주(시가총액 1위), (3) 그 섹터의 성장주 여러 개를 자동
선정하고, 셋의 가격 흐름이 어떤 정량적 관계(민감도/동조화/상대강도)를 갖는지 보여준다.

## 2. 리서치 근거 (WebSearch, 2026-07-15)

- **상대강도(RS) 비율**: 종목가/ETF가 비율의 추세로 그 종목이 섹터를 이끄는지(비율 상승) 처지는지
  (비율 하락) 판단하는 기법 — ETF 대비 상대강도 비교의 표준 기법. 모멘텀 리서치에 따르면 개별 종목
  수익률의 상당 부분이 소속 산업의 강도로 설명된다는 근거도 확인함(대장주-섹터 연동성의 이론적 근거).
- **베타/상관계수**: 개별 종목 수익률을 섹터 ETF 수익률에 회귀해 베타(민감도)를 구하고, 상관계수로
  동조화 정도를 별도로 본다 — "베타가 달라도 상관계수는 비슷할 수 있다"(민감도과 동조화는 별개
  차원)는 것이 실무에서 흔히 쓰이는 구분. 섹터 내 종목 분산도(dispersion)가 클수록 대장주 vs 성장주
  선별 비교의 의미가 커진다는 근거도 확인.
- 기존 `MARKET_REGIME_SECTOR_STRENGTH_SPEC.md`에서 이미 채택한 IBD 스타일 RS 점수/추세 개념과
  같은 철학(투명한 규칙 기반, 통계·ML 레짐 모델 배제)을 유지한다.

Sources: [Using Relative Strength Analysis to Invest in ETFs (AAII)](https://www.aaii.com/journal/article/using-relative-strength-analysis-to-invest-in-etfs),
[How to Use Relative Strength Tools to Compare Stocks and ETFs](https://www.investing-tools.com/how-to-use-relative-strength-tools-to-compare-stocks-and-etfs/),
[Sector Dispersion & Correlation (Nasdaq)](https://indexes.nasdaqomx.com/docs/DWANQFF%20Research.pdf),
[Sector Investing: A Powerful Portfolio Construction Tool (SSGA)](https://www.ssga.com/library-content/pdfs/etf/us/sector-investing-a-powerful-portfolio-investing-tool.pdf)

## 3. 확정된 설계 결정 (AskUserQuestion으로 확인, 2026-07-15)

| 항목 | 결정 |
|---|---|
| UI 위치 | 새 독립 페이지 (`app/pages/12_섹터_리더_성장주.py`) — 기존 매크로 대시보드 탭에 추가하지 않음 |
| 대장주/성장주 정의 방식 | **완전 자동 산출.** GICS 11개 섹터는 `core/screener.get_universe()`의 섹터별 종목 중 시가총액 1위=대장주, 나머지 종목 중 이익성장률(없으면 PER) 배치 내 백분위 상위=성장주. 반도체/DRAM/우주 등 GICS에 없는 테마는 후보 종목 목록만 코드에 미리 정의해두고, 그 후보군 안에서 동일한 방식(시가총액/성장점수)으로 자동 선정 |
| 성장주 개수 | 섹터(테마)당 3개 |
| 관계 분석 지표 | 베타(ETF 대비 민감도) + 상관계수(동조화 정도) + 상대강도(RS) 비율 추세, 3종 조합 |

## 4. 기술 설계 (위임받은 세부사항 — 근거와 함께 직접 결정)

### 4.1 대표 ETF

기존 `core/sector_strength.THEME_UNIVERSE`(14개 테마 → 프록시 ETF 리스트)를 그대로 재사용. 새로
만들지 않음.

### 4.2 후보 종목 유니버스 (`core/sector_leaders.py`)

- GICS 11개 섹터: `THEME_TO_GICS_SECTOR`(한국어 테마명 → GICS 영문 섹터명) 매핑을 새로 정의하고,
  `screener.get_universe()`(S&P500 전체, Symbol/Security/Sector)에서 해당 섹터 종목만 필터링.
- 반도체/메모리·DRAM/우주(GICS에 없음): `NICHE_THEME_CANDIDATES` 프리셋 딕셔너리로 후보 종목을
  미리 정의(THEME_UNIVERSE의 ETF 프록시 프리셋과 같은 방식 — 나중에 종목이 바뀌면 딕�셔너리만 수정).
  - 반도체: NVDA/AVGO/AMD/TXN/QCOM/INTC/MU/ASML/LRCX/AMAT/KLAC/ADI/MRVL/ON/MPWR (SOXX/SMH
    주요 보유 종목 기준)
  - 메모리/DRAM: MU/005930.KS(삼성전자)/000660.KS(SK하이닉스) — `MARKET_REGIME_SECTOR_STRENGTH_SPEC.md`에
    이미 리서치된 "DRAM ETF는 이 세 종목이 비중 약 75%"를 그대로 반영(야후 파이낸스가 `.KS` 접미사로
    한국 종목도 조회 가능, `core.market_data`가 내부적으로 yfinance를 그대로 쓰므로 별도 어댑터 불필요)
  - 우주: LMT/RTX/NOC/BA/GD/ASTS/RKLB/LHX (UFO/ARKX/ROKT의 순수 우주기업 + 방산 대형주 혼합 구성을
    반영, 기존 스펙 리서치 근거 재사용)

### 4.3 대장주/성장주 선정 알고리즘

```
compute_leader_and_growth(theme, top_n_growth=3) -> dict:
    candidates = get_theme_candidate_tickers(theme)
    각 후보에 대해 screener.get_fundamentals(ticker) → market_cap, name
                 valuation.fetch_valuation_inputs(ticker) → earnings_growth, per
    leader = market_cap 최댓값 종목 (1개)
    growth_pool = candidates - {leader}
    growth_score = percentile_rank(growth_pool.earnings_growth.fillna(growth_pool.per))
    growth_stocks = growth_score 상위 top_n_growth개
```

`core/strategy_tuning.py::compute_style_scores`의 growth_score 계산 방식(이익성장률, 없으면 PER로
대체 후 배치 내 백분위)과 **같은 공식**을 쓰되, 그 함수 자체를 호출하지 않고 이 모듈에 얇게 재구현한다
— `compute_style_scores`는 모멘텀/퀄리티 계산을 위해 가격 히스토리까지 조회해 이 기능엔 불필요한
네트워크 호출이 추가되기 때문(성장 점수만 필요하므로 밸류에이션 조회만으로 충분).

### 4.4 관계 지표 계산

대표 ETF 가격 시계열은 `core/sector_strength.py`의 기존 프록시 평균 로직을 공개 함수로 승격해
재사용(`_theme_price_history` → `theme_price_history`, 동작 변경 없음, 유일한 호출부도 함께 수정).

각 종목(대장주/성장주 3개)에 대해 최근 252거래일(약 1년) 일간 수익률로:
- **베타** = `Cov(종목 수익률, ETF 수익률) / Var(ETF 수익률)`
- **상관계수** = `corr(종목 수익률, ETF 수익률)`
- **상대강도(RS) 비율 추세** = `(종목가/ETF가)`를 시작일=100으로 정규화한 뒤, 최근 20거래일 전후
  비교로 "상승/하락/횡보" 판정(`core.sector_strength`의 테마 추세 판정과 동일한 패턴 재사용) + 3개월
  RS 비율 변화율(%)도 함께 표시

1년 일간 수익률 윈도우를 쓴 이유: 5년/월간 수익률(전통적 CAPM 베타)보다 최근 국면을 더 잘 반영하고,
`core/market_regime.py`가 이미 200일선 등 최근 1년 내외 지표를 기본으로 쓰는 것과 일관성 유지.

### 4.5 UI (`app/pages/12_섹터_리더_성장주.py`)

- 테마 선택 셀렉트박스(14개 테마, `THEME_UNIVERSE` 키 재사용)
- 무거운 연산(섹터 내 최대 ~65개 종목 펀더멘털 조회 + 개별 가격 히스토리)이므로 기존 페이지들과
  동일하게 `job_manager.ensure`/`render` 백그라운드 패턴 적용
- 상단: 대장주 카드(종목명/시가총액/베타/상관계수/RS 추세를 `st.metric`으로)
- 정규화(시작일=100) 가격 라인 차트: ETF(점선, 기준선) + 대장주 + 성장주 3개, 총 5개 시리즈.
  dataviz 스킬의 검증된 다크모드 카테고리 팔레트(파랑/주황/초록/노랑/보라 5색, 앱 기존 캔들 상승/하락
  색상[#26a69a/#ef5350]과 겹치지 않도록 선택)로 색 고정
- 하단: 성장주 3개 비교 표(종목명/이익성장률/베타/상관계수/RS 추세)

## 5. 범위에서 제외한 것 (과설계 방지)

- 리드-래그(시차 상관) 분석: 확인 질문에서 사용자가 베타+상관계수+RS추세 조합(더 단순한 안)을 선택,
  시차 분석은 넣지 않음. *(2026-07-15 후속 요청으로 결국 리드-래그 개념을 "레깅 후보" 플래그 형태로
  단순화해 반영함 — 아래 6절 참고. 시차 상관계수 자체를 수치로 계산하는 정식 리드-래그 분석은 여전히
  범위 밖.)*
- 성장주 선정 기준 커스터마이징 UI(가중치 조절 등): 코드 프리셋 알고리즘 그대로, 편집 화면 없음.
- 니치 테마(반도체/DRAM/우주) 후보 종목 리스트의 UI 편집 기능: `THEME_UNIVERSE`와 동일하게 코드
  프리셋으로 시작, 필요 시 딕셔너리만 수정.
- 대장주/성장주를 다종목 미세튜닝 엔진(`STRATEGY_TUNING_ENGINE_SPEC.md`)의 종목 선택에 자동 연동하는
  것: 이번엔 대시보드 표시까지만, 향후 확장 과제로 남겨둠.

## 6. 후속 확장: 성장주 재정의 + 테마 세분화 + 대형주→소형주 추세추종 (2026-07-15)

사용자가 세 가지를 추가 요청: (1) 기술주를 DRAM/방산/냉각 등으로 더 세분화, (2) 애플/마이크로소프트
같은 초대형주가 "성장주"로 잘못 잡히는 문제 수정, (3) 인터넷 리서치(5분) 후 "대형주 추세추종 →
소형주" 아이디어를 페이지에 반영. AskUserQuestion으로 3가지 방향을 확인 후 진행.

### 6.1 리서치 근거

- **초대형주=성장주 문제**: 최근 러셀 지수 재조정에서 애플/MS 등 초대형주가 밸류 지수 쪽으로도 편입될
  만큼 성장/가치 경계가 흐려짐이 확인됨. [ETF Trends](https://www.etftrends.com/equity-etf-content-hub/growth-value-share-megacaps-latest-russell-reconstitution/)
- **방산 vs 우주 분리**: 실무에서도 현금흐름 안정적인 대형 방산 프라임과 계약모멘텀 기반 고변동성
  우주기업을 별개 트레이드로 취급. [TS2 Space/Defense Outlook 2026](https://ts2.tech/en/space-and-defense-stocks-outlook-for-2026-rocket-lab-lockheed-rtx-ast-spacemobile-and-the-golden-dome-catalyst/)
- **AI 데이터센터 냉각**: Vertiv/Modine 등이 뚜렷한 독립 테마로 부상. [Yahoo: Vertiv vs Modine](https://finance.yahoo.com/news/vertiv-vs-modine-stock-edge-133600659.html)
- **기술 세부 테마(사이버보안/클라우드/로보틱스)**: 실제 거래되는 유동성 있는 테마 ETF(CIBR/SKYY·WCLD/BOTZ)
  기준으로 선정. [Global X Next Big Theme 리스트](https://www.globalxetfs.com/articles/the-next-big-theme-june-2026)
- **대형주 추세추종 → 소형주(리드-래그)**: Lo-MacKinlay(1990)가 시가총액 기준 정렬 포트폴리오에서
  대형주 수익률이 소형주 수익률을 선행함을 발견했고, Hou(2007)는 이 효과가 **같은 산업 내**에서 특히
  강하게 나타남을 보임(정보확산 지연 — 대형주는 애널리스트 커버리지가 많아 정보가 빨리 반영되고,
  소형주는 늦게 반영). 단, 거래비용(편도 40bp 이상) 반영 시 이 예측력에 기반한 초과수익은 빠르게
  사라진다는 한계도 같은 연구에서 확인됨 — 페이지에 그대로 안내. [리드-래그 연구](https://jfr.ut.ac.ir/article_85051.html?lang=en)

### 6.2 확정된 설계 결정 (AskUserQuestion)

| 항목 | 결정 |
|---|---|
| 성장주 재정의 | 대장주 한 종목만 빼는 대신, 후보군 내 **시가총액 상위 25%(quantile) 전체**를 성장주 후보에서 제외 |
| 테마 세분화 | "우주"를 방산(대형 프라임+중소형 방산기술주)과 순수 우주기업으로 완전 분리 + 냉각 신규 추가. 추가로 기존 "기술" ETF 라인업을 조사해 사이버보안/클라우드/로보틱스도 신규 세분화 |
| 대형주→소형주 신호 형태 | 레깅(lagging) 후보 플래그 — 대장주가 절대 가격 기준 상승추세이고, 성장주의 베타/상관계수가 임계값(0.5) 이상인데 아직 RS추세가 "상승"이 아니면 "🐢 추격 후보"로 표시 |

### 6.3 기술 설계

- **성장주 후보 시가총액 상한 필터**: `core/sector_leaders.py::compute_leader_and_growth`에
  `MEGA_CAP_EXCLUDE_QUANTILE = 0.75` 추가. `growth_pool = df[df["market_cap"] < df["market_cap"].quantile(0.75)]`
  (대장주는 항상 최댓값이라 자동으로 포함됨). 후보군이 작아(니치 테마 3~4개) 상위 25%를 잘라내면
  아무도 안 남으면 대장주 한 종목만 제외하는 기존 동작으로 폴백.
- **테마 재구성** (`core/sector_strength.THEME_UNIVERSE` + `core/sector_leaders.NICHE_THEME_CANDIDATES`,
  둘 다 신규 5테마 추가로 14→19개):
  - 방산(신규): ETF `ITA`, 후보 LMT/RTX/NOC/GD/LHX(대형) + KTOS/AVAV/MRCY(중소형). 보잉(BA)은
    매출 대부분이 상업 항공기라 대장주 선정을 왜곡할 수 있어 제외.
  - 우주(기존 유지, 후보만 정리): ETF는 그대로 UFO/ARKX/ROKT, 후보를 순수 우주기업 ASTS/RKLB +
    소형주 LUNR/RDW로 교체(대형 방산 프라임 제거).
  - 냉각(신규): ETF `DTCR`(순수 냉각 전용 ETF는 아직 없어 데이터센터 인프라 ETF로 대체), 후보
    VRT/MOD/AAON/NVT.
  - 사이버보안(신규): ETF `CIBR`, 후보 CRWD/PANW/FTNT/ZS/S/OKTA/QLYS.
  - 클라우드(신규): ETF `SKYY`+`WCLD` 평균, 후보 CRM/NOW/SNOW/DDOG/NET/MDB.
  - 로보틱스(신규): ETF `BOTZ`, 후보 ISRG/ROK/TER/PATH/SYM.
  - **실증 검증 중 발견한 상장폐지 종목 교체**: CyberArk(CYBR)는 2026-02-11 Palo Alto Networks에
    인수합병 완료돼 나스닥 상장폐지(→ QLYS로 교체), iRobot(IRBT)는 2025-12 챕터11 파산 후 Picea에
    인수되며 상장폐지(→ SYM으로 교체). 둘 다 yfinance 404 응답으로 먼저 발견한 뒤 뉴스로 확인.
- **대장주 절대 추세 신호**: `core/sector_leaders.py::_abs_trend_label()` 신규 — 기존
  `core.market_regime.score_trend_position`/`score_ma_cross`(200일선 위/아래 + 50/200일 골든·
  데드크로스)를 그대로 재사용해 "상승"/"하락"/"혼조"/"N/A"(데이터 부족)로 라벨링. 기존 `trend`
  필드(ETF 대비 RS비율 추세)와는 별개 개념 — `abs_trend`는 종목 자체의 절대 가격 추세.
- **레깅 후보 플래그**: `core/sector_leaders.py::_is_lag_candidate()` 신규 — 대장주 `abs_trend`가
  "상승"이고, 성장주의 베타≥0.5·상관계수≥0.5(둘 다 `LAG_*_THRESHOLD`)인데 `trend`(RS추세)가
  "상승"이 아니면 True. `analyze_theme_relationships()`가 각 성장주에 `lag_candidate` 필드로 추가.
- **UI**(`app/pages/12_섹터_리더_성장주.py`): 대장주 카드에 "추세추종 신호" 메트릭 추가, 성장주
  표에 시가총액 컬럼 + "🐢 추격 후보" 컬럼 추가, 하나라도 있으면 리드-래그 연구 근거 + 거래비용
  한계 + "투자 조언이 아닌 관찰 지표" 안내 문구를 `st.info`로 표시.

### 6.4 검증

실제 yfinance 데이터로 19개 테마 전부 `analyze_theme_relationships()` 실행해 확인:
- "기술" 테마가 이제 정확히 애플/마이크로소프트를 제외하고 진짜 중형 성장주(MCHP/COHR/LITE, 시총
  $47~63B)를 뽑음(기존엔 AAPL $4.6T/MSFT $2.9T가 그대로 성장주로 잡혔었음 — 수정 전후를 직접 비교
  확인).
- "우주"(RKLB 상승추세 + ASTS/LUNR/RDW 전부 레깅 후보), "반도체"(NVDA 상승추세 + 성장주 3개 전부
  레깅 후보) 등에서 "대형주 추세추종 → 소형주" 플래그가 의도대로 실제 데이터에서 발동함을 확인.
- Streamlit `AppTest`로 페이지 렌더링(메트릭/표/안내문구 실제 값) 확인.
- **검증 중 발견한 무관한 환경 버그를 함께 고침**: `core/screener.py`의 위키피디아 S&P500 스크레이핑이
  `pd.read_html()`에 필요한 `lxml` 패키지 부재로 조용히 실패해(예외가 `except Exception`에 삼켜짐)
  10여 종목짜리 소규모 폴백 유니버스로 계속 대체되고 있었다(이 세션 이전부터 존재하던 문제 — "산업재"
  테마가 항상 후보 0개였던 것도 같은 원인). `requirements.txt`에 `lxml>=5.0` 추가로 해결, 이후
  503종목 전체 유니버스가 정상 로드됨을 확인(스크리너/밸류에이션/시장국면 등 GICS 유니버스를 쓰는
  다른 기능에도 영향을 미치는 범위가 넓은 수정이라 PROGRESS.md에도 별도 기록).
- `tests/test_sector_leaders.py`/`tests/test_sector_strength.py`에 단위테스트 6개 추가(초대형주 다중
  제외, 신규 테마 후보 존재, abs_trend 상승/N-A, 레깅 후보 True/False 분기). 전체 pytest 336개 통과.
