# 작업 진행 상황

> 세션이 자주 끊기는 작업 환경이라, 새 Claude 세션을 시작하면 **이 파일을 가장 먼저 읽고**
> "진행 중" 항목부터 이어서 작업할 것. 완료된 모듈은 `pytest` 로 회귀만 확인하고 건드리지 않는다.

## 모듈 체크리스트 (SPEC.md 순서 A~H)

| 모듈 | 상태 | core/ | app/pages/ | tests/ |
|---|---|---|---|---|
| A. 백테스팅 엔진 | ✅ 완료 | backtest_engine.py, strategy_engine.py, indicators.py, nl_strategy.py, expression_engine.py | 1_백테스팅.py | test_backtest_engine.py, test_strategy_engine.py, test_expression_engine.py |
| B. Threads 요약(+주간 인사이트 리포트) | ✅ 완료 | threads_summary.py, models.py(ThreadsWeeklyReport 추가) | 2_Threads_요약.py | test_threads_summary.py |
| C. 관심 티커 + 타점 모니터링 | ✅ 완료 | watchlist.py, notify.py | 3_관심종목_모니터링.py | test_watchlist.py |
| D. 거장 포트폴리오 추종 | ✅ 완료 | guru_tracker.py, etf_holdings.py | 4_거장_포트폴리오.py | test_guru_tracker.py, test_etf_holdings.py |
| E. 퀀트 스크리너 | ✅ 완료 | screener.py | 5_퀀트_스크리너.py | test_screener.py |
| F. 밸류에이션 도구 | ✅ 완료 | valuation.py | 6_밸류에이션.py | test_valuation.py |
| G. 매크로 대시보드 | ✅ 완료 (+시장국면/섹터강도 확장) | fred_data.py, macro_cycle.py, market_regime.py, sector_strength.py | 7_매크로_대시보드.py | test_fred_data.py, test_macro_cycle.py, test_market_regime.py, test_sector_strength.py |
| H. 포트폴리오 관리 | ✅ 완료 | portfolio.py | 8_포트폴리오_관리.py | test_portfolio.py |
| I. 차트 조회 (신규) | ✅ 완료 | market_data.py(clamp_start_for_interval 추가), indicators.py 재사용, watchlist.py 재사용 | 10_차트_조회.py | test_market_data.py |
| (부가) 환경설정(페이지 순서 편집) | ✅ 완료 | page_order.py(신규) | 11_환경설정.py | test_page_order.py |
| (부가) 섹터 리더/성장주 관계 분석 | ✅ 완료 | sector_leaders.py(신규), sector_strength.py(theme_price_history 공개화) | 12_섹터_리더_성장주.py | test_sector_leaders.py |
| (부가) 코스톨라니 달걀 이론 국면 | ✅ 완료 | kostolany_cycle.py(신규), models.py(KostolanyCycleSnapshot 추가), scheduler/run_scheduler.py(market_snapshot_job에 통합) | 16_코스톨라니_달걀_이론.py | test_kostolany_cycle.py |
| (부가) 챔피언 전략 (신규) | ✅ 완료 | champion_strategy.py(신규) | 11_챔피언_전략.py | test_champion_strategy.py |

**SPEC.md 모듈 A~H 전부 구현 완료** (2026-07-11). 전체 테스트 123개 통과, 신규 모듈(B/E/F/G/H) 페이지는
Streamlit `AppTest`로 헤드리스 스모크 테스트 완료 (밸류에이션/스크리너/포트폴리오는 실제 AAPL 등
라이브 데이터로 end-to-end 확인, Threads 요약/매크로 대시보드는 기본 로드만 확인).

**모듈 I. 차트 조회 추가 완료** (2026-07-12). 사용자가 "트레이딩뷰처럼 일봉/주봉 등으로 나눌 수 있고
티커 입력하면 차트가 나오게 해달라"고 요청 → 새 독립 페이지로 구현 (백테스트/전략 설정 없이 바로
조회). 확인 질문 3개(배치 위치/봉 주기 범위/지표 오버레이 필요 여부)로 답을 받아 진행:
- 새 독립 페이지 `app/pages/10_차트_조회.py` (기존 `1_백테스팅.py`의 캔들차트 렌더링 패턴 재사용)
- 봉 주기: yfinance 지원 전체(1m/2m/5m/15m/30m/60m/90m/1d/5d/1wk/1mo/3mo). `core/market_data.py`에
  `INTERVAL_MAX_LOOKBACK_DAYS` + `clamp_start_for_interval()` 추가 — 분봉/시간봉은 yfinance가
  과거 조회를 짧게 제한하므로(1분봉 6일/5~30분·90분봉 60일/60분봉 730일), 사용자가 더 오래된
  시작일을 고르면 자동 보정하고 화면에 경고 캡션 표시
- 지표 오버레이: 이동평균/볼린저밴드/일목균형표(캔들 위 오버레이) + RSI/MACD(하단 별도 패널) 전부
  토글 on/off 가능, `core/indicators.py` 계산 함수 그대로 재사용 (신규 계산 로직 없음)
- 거래량 바 차트는 항상 표시(양봉/음봉 색상 구분)
- 검증: Streamlit `AppTest`로 기본 로드/전체 지표 토글 조합/분봉 전환(자동 clamp 경고 확인)/
  잘못된 티커 에러 처리까지 실제 라이브 yfinance 데이터로 확인. `clamp_start_for_interval()`은
  `tests/test_market_data.py`에 단위 테스트 3개 추가. 전체 테스트 130개 통과.
- SPEC.md에 "모듈 I. 차트 조회" 항목 추가, `app/Home.py` 모듈 표에도 한 줄 추가.

**차트 UX 개선 3종 추가 완료** (2026-07-12, 같은 날 후속 요청). 사용자가 "차트 휠 확대/축소, 관심종목
빠른 찾기, 페이지 순서를 직접 편집할 수 있는 환경설정"을 요청 → 확인 질문 없이 바로 진행(직전 대화의
연장선이라 맥락이 명확했음):
- **휠 확대/축소**: `app/pages/10_차트_조회.py`와 `1_백테스팅.py`의 캔들차트(`render_price_chart`/
  `render_staged_price_chart`) 전부 `st.plotly_chart(..., config={"scrollZoom": True})`로 변경.
  Plotly 기본 동작이 이미 "휠 위로=확대/아래로=축소"라 별도 방향 반전 로직 불필요. 차트가 아닌 다른
  영역(등락 비교 라인차트 등)은 건드리지 않음(스코프를 캔들/가격 차트로 한정).
- **관심종목 빠른 찾기**: `10_차트_조회.py` 상단에 `core/watchlist.py`(모듈 C, 신규 로직 없이 재사용)
  기반 "⭐ 관심종목" 버튼 그리드 추가 — 클릭하면 즉시 그 티커로 조회. 티커 입력창 옆에 "☆ 관심종목
  추가"/"★ 관심종목 해제" 토글 버튼도 추가해 조회하던 티커를 바로 등록/해제 가능(50개 제한 초과 시
  `add_to_watchlist`가 던지는 `ValueError` 메시지를 그대로 경고로 표시). 티커 입력 위젯에 `key`가
  없어 세션 상태와 연결되지 않던 기존 버그도 함께 고침(watchlist 클릭이 입력값을 갱신하려면 `key`가
  필수였음) — `value=`+`key=` 동시 사용 시 발생하는 Streamlit 세션 상태 경고를 피하려고 date_input도
  전부 `st.session_state.setdefault(...)` 선반영 + `key`만 넘기는 방식으로 같이 정리함.
- **페이지 순서 환경설정**: Streamlit 멀티페이지 앱이 `app/pages/*.py` 파일명 맨 앞 숫자로 사이드바
  순서를 정하는 점에 착안, `core/page_order.py`(신규)에 `list_pages`/`reorder_pages`/`move_page`
  (top/up/down/bottom) 구현 — 여러 파일명이 한 번에 바뀔 때 충돌 없이 2단계(임시 이름 경유) rename.
  `app/pages/11_환경설정.py`에서 페이지 목록 + ⏫▲▼⏬ 버튼으로 노출. 코드로 미리 순서를 정하는 대신
  사용자가 웹사이트에서 직접 버튼으로 재배치하는 것이 요청의 핵심이라, `st.navigation`/`st.Page`
  기반 재설계 대신 기존 폴더 자동탐색 방식을 유지한 채 파일명만 실제로 바꾸는 가벼운 방식을 선택함
  (기존 10개 페이지의 `st.set_page_config()` 호출 구조를 건드릴 필요가 없어 회귀 위험이 낮음). 파일
  rename은 Streamlit 개발 서버의 일반적인 파일 변경 감지로 다음 새로고침 때 사이드바에 반영됨(같은
  세션 내 즉시 100% 보장은 아니라 페이지에 안내 문구 표시).
- 검증: `core/page_order.py`는 `tests/test_page_order.py`(8개, tmp_path에 더미 파일 생성 후 rename
  검증 — 실제 `app/pages/` 파일은 절대 건드리지 않음)로 커버. `10_차트_조회.py`의 관심종목 추가/해제/
  빠른선택 흐름은 `DATABASE_URL`을 임시 SQLite로 바꿔치기한 뒤 Streamlit `AppTest`로 라이브 검증(실제
  운영 DB `data/quant.db`는 건드리지 않음). `11_환경설정.py`는 로드만 스모크 테스트(버튼 클릭 시 실제
  페이지 파일이 rename되므로 자동화 테스트에서는 클릭하지 않음 — 수동으로 브라우저에서 확인 필요).
  전체 pytest 스위트 통과(동시에 다른 세션이 작업 중인 엔걸핑/다크모드 관련 테스트 포함 144개).

**차트 드래그 동작을 확대(zoom)에서 이동(pan)으로 변경** (2026-07-12, 같은 날 후속 요청). 사용자가
"마우스를 누르면 확대/축소되는 것 같은데 '움직임'으로 바꿔달라, 누른 채 위로 올리면 위쪽을 볼 수
있게"라고 요청 → Plotly 캔들차트 3곳(`10_차트_조회.py`의 `render_chart`, `1_백테스팅.py`의
`render_price_chart`/`render_staged_price_chart`) `fig.update_layout()`에 `dragmode="pan"` 추가.
`scrollZoom=True`(휠 확대/축소)는 그대로 유지 — 휠은 확대/축소, 드래그는 화면 이동으로 역할 분리.
y축이 autorange라 세로 드래그도 기본 지원(위로 드래그하면 차트 위쪽이 보임). 페이지 캡션 문구도
"드래그로 화면 이동이 가능합니다"로 갱신. 렌더링 로직만 바뀌어 별도 유닛테스트 없이 기존 스모크
테스트(AppTest 로드)로 회귀만 확인, 전체 144개 통과 유지.

**커서 위치의 시가/고가/저가/종가를 보여주는 호버 툴팁 추가** (2026-07-12, 같은 날 후속 요청). 사용자가
"커서를 올렸을 때 그 날의 시가/종가를 커서 옆에 작게 띄워달라"고 요청 → 캔들차트 3곳 모두에:
- `go.Candlestick`에 한글 라벨 `hovertemplate`(날짜/시가/고가/저가/종가, `<extra></extra>`로 트레이스명
  박스 제거) 추가. `10_차트_조회.py`는 분봉/시간봉일 때 날짜에 시:분까지 표시(`is_intraday` 분기).
- `hovermode="x"` + `fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor", ...)`로
  세로 크로스헤어 점선을 추가해 커서가 있는 지점에 값이 붙어 보이도록 함(트레이딩뷰 크로스헤어와 유사).
- 검증: Streamlit `AppTest`로 렌더된 `plotly_chart`의 실제 spec(JSON)을 파싱해
  `dragmode="pan"`/`hovermode="x"`/`xaxis.showspikes=True`/`config.scrollZoom=True`/candlestick
  `hovertemplate` 문자열까지 전부 실제 값으로 확인(스냅샷성 유닛테스트는 추가하지 않음, 렌더링 설정
  변경이라 회귀는 기존 AppTest 로드로 충분). 전체 144개 통과 유지.

**Threads 요약에 "주간 AI 인사이트 리포트" 추가** (2026-07-12, 같은 날 후속 요청). 사용자가
"티커별로 글을 모아서 일주일에 한번씩(또는 버튼으로) AI가 리포트를 만들되, 단순 요약이 아니라
인사이트를 달라. 마땅한 프롬프트가 없으면 구글링해서 찾아 채택하라"고 요청 → 프롬프트 설계 전에
실제로 웹 검색을 먼저 수행함(사용자가 명시적으로 지시한 절차):
- 검색 결과 두 가지 근거를 확보: (1) 학술 자료가 제시하는 2단계 LLM 프레임워크 — "시장 테마/
  리스크 요인/종목별 핵심 포인트"를 추출한 뒤 여러 개를 종합해 주간 리포트로 합성하는 구조,
  (2) 실무 프롬프트 설계 원칙 — Role-Task-Context 프레이밍 + "단순 요약이 아닌 실행 가능한
  인사이트" 강조. 바로 쓸 수 있는 완성형 템플릿은 못 찾았지만(검증된 소스들: [SurePrompts
  Finance](https://sureprompts.com/blog/ai-prompts-finance), [CFI 19 AI Prompts for Stock
  Analysis](https://corporatefinanceinstitute.com/resources/artificial-intelligence-ai/best-ai-prompts-for-stock-analysis/)
  둘 다 직접 확인했으나 소셜미디어 종합 리포트용 템플릿은 없었음), 위 두 근거를 결합해 직접 설계.
- `core/threads_summary.py`에 `WEEKLY_REPORT_SYSTEM_PROMPT` 신설 — 리포트를 5개 섹션(①이번 주
  핵심 테마 ②정서 변화[초반vs후반 변곡점 추적] ③촉매 및 리스크 ④다수의견 vs 소수의견[에코챔버
  방지] ⑤관찰 포인트)으로 강제하고, "개별 글의 재탕이 아니라 여러 글을 겹쳐봤을 때만 보이는 것에
  집중하라"고 명시. `generate_weekly_report(ticker, days=7)`가 `list_summaries_between()`으로
  기간 내 글을 시간순(오래된→최신, 정서 변화 추적 위해)으로 모아 `gemini_client.COMPLEX_TASK_MODELS`
  (복잡한 종합추론이라 LIGHT가 아닌 상위 모델 사용)로 호출. 키 없음/실패/글 없음 전부 예외 없이
  처리(기존 관례).
- DB: `core/models.py`에 `ThreadsWeeklyReport`(ticker/period_start/period_end/post_count/
  report_text) 신설. `save_weekly_report`/`list_weekly_reports`로 히스토리 누적(재생성해도 과거
  리포트는 보존).
- UI: `app/pages/2_Threads_요약.py`에 3번째 탭 "📅 주간 인사이트 리포트" 추가 — 티커 선택 + "최근
  며칠"(기본 7) + "🧠 리포트 생성" 버튼(누르면 즉시 생성·자동 저장) + 리포트 히스토리 expander 목록.
- 스케줄러: `scheduler/run_scheduler.py`에 `threads_weekly_report_job()` 추가, 매주 일요일 20:00
  (America/New_York, 월요일 개장 전)에 추적 중인 모든 티커에 대해 자동 생성하도록
  `BlockingScheduler`에 등록(기존 평일 16:30 watchlist 스캔 잡과 함께 상시 실행).
- 검증: 실제 AAPL 3건짜리 글로 end-to-end 실행해 실제 결과물 품질 확인(테마/정서변화/촉매·리스크/
  합의-소수의견 전부 잘 뽑힘, 데이터가 적을 때는 그 사실을 리포트 서두에 스스로 명시함도 확인) +
  Streamlit 브라우저로 버튼 클릭→생성→저장 토스트→렌더링까지 라이브 확인. `tests/test_threads_summary.py`
  에 단위테스트 6개 추가(기간 필터링, 글 없음/키 없음/API 실패 처리, 저장/조회) — 전체 149개 통과.

**차트에 TradingView 스타일 추세선/도형 그리기 + 다크 차트 테마 + 인터벌 탭 UI 추가** (2026-07-12,
같은 날 후속 요청). 사용자가 "추세선을 긋는 등 트레이딩뷰에서 하는 모든 걸 구현 가능한 범위에서
넣어달라, UI도 트레이딩뷰를 따라해달라"고 요청 → 커스텀 JS 컴포넌트 없이 Plotly.js 내장 기능만으로
구현 가능한 범위를 먼저 확인(Streamlit이 번들한 `PlotlyChart*.js`에 `drawline`/`drawopenpath`/
`drawclosedpath`/`drawcircle`/`drawrect`/`eraseshape`/`newshape`/`modebar` 문자열이 실제로 존재하는지
grep으로 먼저 검증한 뒤 진행):
- `core/theme.py`에 `TRADINGVIEW_CHART_CONFIG`(도형 그리기 버튼 추가 + lasso/box select 제거,
  scrollZoom 유지) + `style_chart_like_tradingview(fig)`(배경 `#131722`, 그리드 `#2a2e39`, 글자
  `#d1d4dc`, 모드바를 세로 배치 + 액센트 `#2962ff`, 새로 그리는 도형 기본색도 액센트) 신규 추가 —
  캔들 초록/빨강(#26a69a/#ef5350)은 원래부터 TradingView 색이라 그대로 둠.
  `10_차트_조회.py`/`1_백테스팅.py`의 캔들차트 3곳 전부 기존 `template="plotly_white"` +
  `config={"scrollZoom": True}`를 이 공용 헬퍼/설정으로 교체.
- `10_차트_조회.py`의 봉 주기 선택을 드롭다운(`st.selectbox`)에서 TradingView 타임프레임 탭처럼
  가로 버튼 행(선택된 인터벌은 `type="primary"`로 강조)으로 교체.
- **한계(사용자에게 페이지 캡션으로 안내)**: Plotly 도형 그리기는 클라이언트 상태라 지표 토글/티커/
  인터벌 변경 등 Streamlit 스크립트 재실행이 일어나면 그린 도형이 초기화된다 — Streamlit
  `st.plotly_chart`에는 relayout(도형 편집) 이벤트를 세션 상태로 되돌려주는 훅이 없어(선택 이벤트용
  `on_select`는 점 선택에만 해당) 재실행 간 영속화하려면 별도 커스텀 양방향 컴포넌트가 필요함 — 이번
  범위에서는 만들지 않고 한계로 명시. 순수 확대/축소/이동/호버는 재실행을 일으키지 않아 그 사이엔
  도형이 유지된다.
- 검증: Streamlit `AppTest`로 렌더된 `plotly_chart`의 실제 spec/config JSON을 파싱해
  `paper_bgcolor="#131722"`, `config.modeBarButtonsToAdd`에 6개 도형 도구 전부 포함,
  `1_백테스팅.py`는 백테스트 실행 버튼을 눌러 실제 생성된 차트까지 확인. 인터벌 탭 버튼 클릭 →
  세션 상태 갱신 → 주봉(1wk)으로 정상 전환되는 것도 실제 라이브 데이터로 확인. 렌더링/설정 변경이라
  별도 유닛테스트는 추가하지 않음, 전체 pytest 149개 통과 유지.

**주간 인사이트 리포트에 삭제 + 사후 검증(회고) 피드백 기능 추가** (2026-07-12, 같은 날 후속 요청).
사용자가 "생성한 리포트도 삭제할 수 있게 해달라. 그리고 그 리포트로 예측했던 것과 한 달쯤 지난 뒤
(또는 리포트가 다룬 기간만큼 지난 뒤) 실제 주가를 비교해서 피드백이 이뤄지는 기능도 만들어달라"고
요청:
- **삭제**: `core/threads_summary.py::delete_weekly_report(report_id)` 추가.
  `2_Threads_요약.py` 리포트 히스토리 각 항목에 "🗑️ 리포트 삭제" 버튼 추가.
- **사후 검증(회고) 피드백**: `core/models.py::ThreadsWeeklyReport`에 컬럼 4개 추가
  (`price_at_generation`: 리포트 생성 시점 종가, `feedback_text`/`feedback_price`/
  `feedback_generated_at`: 회고 결과 — 다시 생성하면 최신값으로 덮어씀, 리포트 자체처럼 버전을
  누적하지는 않음). `save_weekly_report()`가 저장 시점에 `core.market_data.get_latest_price()`로
  기준가를 자동 기록(조회 실패해도 저장은 계속 진행). `generate_report_feedback(report_id)`가
  경과일 계산 + 현재가 재조회 + 변화율 계산 후, `FEEDBACK_SYSTEM_PROMPT`(새로 작성 — "리포트의
  방향성이 맞았는지 / 어떤 부분이 적중했는지 / 어떤 부분이 빗나갔는지 / 다음에 참고할 점"을
  냉정하게 평가하도록 지시, 자화자찬 방지 문구 포함)로 `gemini_client.COMPLEX_TASK_MODELS` 호출.
  가격 데이터가 없거나(과거에 저장된 리포트 등) API 실패 시에도 예외 없이 대체 텍스트로 폴백.
  `save_report_feedback(report_id, feedback_text, feedback_price)`로 저장.
- UI: 리포트 히스토리 각 expander에 기준가/경과일 표시, 이미 회고가 있으면 회고 시점 가격·변화율과
  함께 표시, "🔍 피드백 확인"(또는 이미 있으면 "다시 확인") 버튼.
- **기존 DB 마이그레이션 필요**: `init_db()`의 `create_all()`은 이미 존재하는 테이블에 새 컬럼을
  자동으로 추가해주지 않는다 (SQLite 한계 아님 — SQLAlchemy의 기본 동작). 이번 세션에서 이미
  `data/quant.db`에 구 스키마로 `threads_weekly_reports` 테이블이 만들어져 있어서, 수동으로
  `ALTER TABLE threads_weekly_reports ADD COLUMN ...` 4개를 실행해 기존 데이터를 보존하며
  마이그레이션함. **앞으로 models.py에 컬럼을 추가할 때마다 이 문제가 재발하니, 운영 DB
  (`data/quant.db`)에 이미 해당 테이블이 있다면 `init_db()`만으로는 부족하고 수동 ALTER TABLE이
  필요하다는 점을 기억할 것** (테스트는 매번 새 임시 SQLite를 쓰므로 이 문제가 안 보임 — 실제 앱
  구동 시에만 드러남).
- 검증: 실제 저장된 리포트(가격 정보 없는 과거 리포트 포함)로 `generate_report_feedback` 실행해
  가격 데이터 없이도 리포트의 논리적 타당성 위주로 품질 높은 회고를 생성함을 확인. 브라우저로
  피드백 생성 → 저장 → 렌더링, 그리고 삭제 버튼 클릭 → 히스토리에서 실제로 사라짐까지 라이브 확인.
  `tests/test_threads_summary.py`에 단위테스트 6개 추가(삭제, id 조회, 피드백 없음 에러, 키
  없음/API 실패 폴백, 저장) — 전체 155개 통과.

**ImportError 핫픽스 + 차트 조회 페이지를 실제 TradingView 캡처 기준으로 레이아웃 재설계**
(2026-07-12, 같은 날 후속 요청).
- **ImportError 핫픽스**: 사용자가 `core.theme`에서 `TRADINGVIEW_CHART_CONFIG` import 실패를
  보고. 원인 파악: 디스크의 `core/theme.py`에는 이미 정상적으로 정의돼 있었고(컴파일/재 import로
  확인), 실제 원인은 **오래전에 띄워둔 Streamlit 프로세스가 그 파일이 추가되기 전 상태를
  `sys.modules`에 캐싱**하고 있었던 것 — Streamlit의 로컬 파일 워처가 이 케이스를 못 잡아낸 것으로
  추정. 기존 프로세스를 종료하고 새 프로세스로 재기동해 해결. **교훈**: `core/*.py`에 새 공개
  이름(상수/함수)을 추가한 직후 `ImportError`가 나면, 코드가 아니라 오래된 서버 프로세스를 먼저
  의심할 것 (재기동으로 먼저 확인 후 코드를 파고들 것).
- **브라우저 실행 확인**: `chromium-cli`가 없어 Python `playwright` 패키지(이미 설치돼 있음, 브라우저
  바이너리도 캐시에 있음)로 직접 헤드리스 브라우저를 띄워 실제 앱을 조작 — 차트 페이지 로드, 호버
  툴팁, 추세선 그리기(모드바의 "Draw line" 버튼 클릭 후 드래그), 인터벌 탭 전환, 백테스팅 페이지까지
  전부 실제 클릭/스크린샷으로 확인. 이 컨테이너에는 `chromium-cli` skill이 없다는 점, 대신
  `playwright` 파이썬 패키지 + 캐시된 크로미움 바이너리(`~/.cache/ms-playwright/`)로 동일한 역할을
  대체할 수 있다는 점을 기록해둔다.
- **레이아웃 재설계**: 사용자가 실제 TradingView 차트 캡처(NASDAQ:IREN, 30분봉)를 제공하며 "UI/UX를
  그대로 따라해달라"고 요청. 캡처를 분석해 Plotly/Streamlit으로 **실제로 재현 가능한 요소**만
  선별해 반영(불가능한 요소는 아래에 명시하고 만들지 않음):
  - 캔들 위 좌상단에 심볼/봉주기/OHLC 오버레이 텍스트를 겹쳐서 표시(등락에 따라 종가 색상,
    `fig.add_annotation(xref="x domain", yref="y domain", ...)`로 서브플롯 안쪽에 배치해 범례와
    안 겹치게 함).
  - 우측 가격축에 마지막 종가를 등락색 배지로 표시(`xref="x domain", x=1.0` + `yref="y"`).
  - 빠른 기간 버튼을 차트 "위"가 아니라 차트 **바로 아래**로 이동하고, 라벨을 TradingView 그대로
    (1일/5일/1개월/3개월/6개월/YTD/1년/전체)로 통일 — 기존에 인터벌별로 나뉘어 있던
    `DAILY_PRESETS`/`INTRADAY_PRESETS`도 단일 `RANGE_PRESETS`로 합침(분봉에서 너무 긴 기간을 누르면
    기존 `clamp_start_for_interval()`이 알아서 당겨주므로 굳이 나눌 필요 없었음). 버튼 클릭 값은
    session_state를 거쳐 차트보다 먼저 실행되는 fetch 코드에 반영되므로, 위젯의 "화면상 위치"와
    "로직상 실행 순서"가 달라도 정상 동작함(Streamlit 스크립트는 매 상호작용마다 위에서부터 다시
    실행되기 때문) — 다만 조회 실패/미입력 상태에서도 항상 노출되도록 if/elif/else 블록 바깥으로
    빼서, 잘못된 기간을 골랐어도 그 자리에서 바로 고칠 수 있게 함.
  - 지표 설정 패널을 `st.expander`로 접어서 기본 로드 시 차트가 먼저 눈에 들어오게 함(TradingView는
    지표를 팝업으로 설정하고 캔버스는 항상 깨끗하게 유지하는 것에 착안).
  - 날짜 직접 입력(시작일/종료일)도 `st.expander("📅 직접 기간 지정")`로 접어 기본 노출 최소화.
  - 다크 배경(#131722)·그리드(#2a2e39)·초록/빨강 캔들은 이전 세션에서 이미 캡처와 거의 동일하게
    맞춰져 있어 그대로 유지.
  - **의도적으로 만들지 않은 것(사용자에게 이유 설명함)**: TradingView 좌측의 15개 이상 그리기
    도구(피보나치/간/평행채널/자석모드/눈금자 등 — Plotly 모드바는 6개 도형 도구만 지원), 상단
    툴바의 거래/퍼블리시/리플레이/알림/비교 버튼(우리 앱에 해당 기능이 없어 눌러도 아무 동작 안 하는
    "죽은 버튼"이 되므로 안 만듦), 실시간 매수/매도 호가 박스(yfinance로는 실제 Bid/Ask 스프레드를
    못 받아와 가짜 데이터가 됨), TradingView 워터마크/브랜드 로고(상표 도용 우려로 넣지 않음), 좌측
    도킹형 세로 툴바(Plotly 모드바는 우측에만 도킹 가능, 왼쪽 배치는 Plotly API가 지원하지 않음).
- 검증: `AppTest`로 재구조화 후 회귀 확인(전체 155개 통과, 유닛테스트는 추가하지 않음 — 순수
  레이아웃/시각 변경) + 실제 브라우저(playwright)로 최종 스크린샷까지 확인해 심볼/OHLC 오버레이,
  우측 가격 배지, 하단 빠른기간 버튼, 접힌 지표 설정 패널 전부 의도대로 렌더링됨을 눈으로 확인.

**도형 편집(꼭짓점 이동/삭제) + 주말 캔들 공백 제거 + 도형 영속화 한계 확인** (2026-07-12, 같은 날
후속 요청). 사용자가 "추세선을 그은 뒤 클릭하면 꼭짓점을 옮길 수 있게, 선을 클릭하고 Delete를 누르면
삭제되게 해달라 / 날짜에 주말은 표시하지 말아달라 / 봉 주기를 바꿔도 그린 추세선이 유지(스케일링)되게
해달라"고 3가지를 요청. Plotly.js 번들 코드를 grep해서 실제 지원 여부를 먼저 확인한 뒤 진행(추측으로
구현하지 않음):
- **꼭짓점 드래그로 이동/리사이즈**: `TRADINGVIEW_CHART_CONFIG`에 `edits: {shapePosition: true}` 추가.
  기본 dragmode가 "pan"이어도(그리기 도구를 다시 켜지 않아도) 이미 그린 도형을 클릭해 꼭짓점을 드래그로
  옮길 수 있음을 playwright로 실제 확인(라인의 기울기가 드래그한 대로 바뀌는 것을 스크린샷으로 검증).
- **주말 공백 제거**: `core/theme.py::style_chart_like_tradingview()`에
  `fig.update_xaxes(rangebreaks=[dict(bounds=["sat","mon"])])` 추가 — 3개 차트(백테스팅 2종 + 차트
  조회) 전부에 공용으로 적용됨. 캔들이 주말 없이 연속으로 붙어 나오는 것을 스크린샷으로 확인.
- **"선 클릭 후 Delete 키로 삭제"는 실증적으로 불가능함을 확인**: `Delete`/`Backspace` 문자열이
  번들에 있길래(grep) 지원되는 줄 알았으나, 실제로는 `delete obj.prop` 같은 JS 키워드/내부 undo-redo
  이벤트명(`_onDelete` 등)일 뿐 키보드 삭제 기능이 아니었음 — playwright로 도형을 정확히 선택
  (`_fullLayout._activeShapeIndex`가 0이 되는 것까지 확인)한 이후에도 Delete/Backspace를 눌러보니
  도형이 안 지워짐을 직접 확인해 결론 내림(추측이 아니라 브라우저에서 직접 검증). **대신 이미 있는
  "지우개(eraseshape)" 도구가 실제로 동작함을 확인**: 도형을 한 번 클릭해 활성화한 뒤 모드바의
  지우개 아이콘을 누르고 그 도형을 다시 클릭하면 삭제됨(`layout.shapes.length`가 1→0으로 줄어드는
  것을 evaluate로 확인). 페이지 캡션을 "도형을 클릭한 뒤 지우개 도구로 삭제할 수 있습니다"로 갱신해
  실제 동작하는 방법을 안내하도록 수정.
- **"봉 주기를 바꿔도 그린 추세선이 유지"는 현재 구조로는 불가능 — 근본 원인 확인**: 그린 도형은
  브라우저의 Plotly.js 인스턴스 안에만 존재하는 클라이언트 상태이고, 인터벌 탭을 누르면
  `st.rerun()`이 스크립트를 처음부터 다시 실행해 매번 새 `go.Figure` 객체를 서버에서 만들어 보내므로
  도형이 사라진다. `st.plotly_chart()`의 시그니처를 직접 확인(`inspect.signature`)한 결과
  `on_select`는 포인트/박스/라쏘 선택 이벤트만 세션 상태로 돌려주고, 도형 편집(`plotly_relayout`)
  이벤트를 Python으로 되돌려주는 훅은 없음 — 이 한계는 이전 세션에서 이미 예상했던 것과 동일한
  근본 원인(도형 그리기 기능 추가 시 기록한 한계)이며, 해결하려면 `plotly_relayout` 이벤트를 듣고
  `Streamlit.setComponentValue()`로 shapes 배열을 돌려주는 **커스텀 Streamlit 컴포넌트**(작은
  JS 프론트엔드 번들 필요)를 새로 만들어야 한다 — 순수 파이썬 범위를 벗어나는 별도 엔지니어링
  작업이라 이번 세션에서는 만들지 않고, 사용자에게 트레이드오프를 설명하고 진행 여부를 확인 중.
- 검증: `core/theme.py`/`10_차트_조회.py` 컴파일 + 전체 pytest 155개 통과(로직 없는 시각/설정
  변경이라 신규 유닛테스트는 추가하지 않음). 위 3가지 전부 playwright로 실제 클릭/드래그/평가식
  실행까지 거쳐 사실관계를 확인함(문서만 보고 판단하지 않음).

**추세선 그리기 후 자동으로 화면 이동(pan) 모드 복귀** (2026-07-12, 같은 날 후속 요청). 사용자가
"선 긋는 도구를 누르면 선을 그린 후 다시 차트를 움직이는 모드로 자동 전환해달라"고 요청 (TradingView는
도형 하나 그리면 자동으로 커서/이동 모드로 돌아옴, 지금까지는 사용자가 매번 Pan 아이콘을 다시 눌러야
했음). Plotly config(`modeBarButtonsToAdd`/`newshape`/`edits`)만으로는 "그리기 완료 후 dragmode를
되돌리기"를 표현할 방법이 없어(그런 옵션이 존재하지 않음, grep으로 먼저 확인), 커스텀 Streamlit
컴포넌트 없이 갈 수 있는 유일한 경로로 `st.components.v1.html`의 srcdoc iframe을 통한 JS 주입을 사용:
- `core/theme.py`에 `inject_auto_pan_after_draw()` 신규 추가. iframe의 sandbox 속성에
  `allow-same-origin`이 포함돼 있음을 Streamlit 프론트엔드 번들(`IFrameUtil.*.js`)에서 먼저 확인한 뒤
  진행 — `window.parent.document`로 메인 앱의 `.js-plotly-plot` div를 찾고(`window.Plotly`가
  `window.Plotly=e` 형태로 전역 노출됨을 `PlotlyChart.*.js`에서 확인), `gd.on("plotly_relayout", ...)`
  로 이벤트를 감시하다가 **dragmode가 "draw"로 시작하면서 실제로 도형이 생겨난 경우**(eventData 키가
  `"shapes"`로 시작)에만 `Plotly.relayout(gd, {dragmode: "pan"})`을 호출해 되돌린다. 기존 도형의
  꼭짓점을 드래그로 옮기는 동작(`edits.shapePosition`)은 dragmode가 이미 "pan"인 채로 일어나므로 이
  조건에 걸리지 않아 서로 간섭하지 않음.
- `10_차트_조회.py`에서 `st.plotly_chart(...)` 직후에 `inject_auto_pan_after_draw()` 호출. 페이지
  캡션도 "그리고 나면 자동으로 화면 이동 모드로 돌아옵니다"로 갱신.
- **범위**: 사용자가 "차트 조회"만 언급해 이 페이지에만 적용, 백테스팅 페이지 2개 차트는 건드리지 않음.
- 꼭짓점 드래그로 다른 캔들 위에 옮기는 기능은 이전 세션에서 이미 `edits.shapePosition: true`로
  구현·검증되어 있었음(재작업 불필요) — 이번 세션에서 playwright로 재확인만 함(아래 검증 항목).
- 검증: playwright 헤드리스 브라우저로 실제 클릭/드래그하며 4가지를 순서대로 확인 — ① 초기
  dragmode가 "pan"인지, ② "Draw line" 모드바 버튼 클릭 시 dragmode가 "drawline"으로 바뀌는지, ③ 실제
  드래그로 선을 그은 직후 `_fullLayout.dragmode`가 다시 "pan"으로 자동 복귀하는지(성공 확인), ④ 그
  상태에서 차트를 드래그하면 새 도형이 생기지 않고(shapes 개수 유지) 실제로 x축 range가 이동하는지
  (성공 확인, `xaxis.range`가 5개월가량 이동함을 수치로 확인). 별도로 ⑤ 그린 선을 클릭 후 끝점을
  다른 위치로 드래그하면 그 끝점의 좌표(x1/y1)만 바뀌고 반대쪽 끝점(x0/y0)은 그대로 유지되는지도
  좌표값으로 직접 확인(스크린샷도 확보). 8501 포트에 떠 있던 기존(사용자) 세션은 건드리지 않고
  8502 포트에 별도 테스트 인스턴스를 띄워 검증 후 종료함. `python -m pytest tests/ -q` 전체 161개
  통과 유지(로직 없는 프론트엔드 JS 주입이라 신규 유닛테스트는 추가하지 않음).

**차트 조회: 거래 없는 구간 제거 + 도형 봉주기 간 유지 + 도형 색상 변경 + 주봉/월봉/분기봉 일봉 동기화**
(2026-07-12, 같은 날 후속 요청). 사용자가 "①워킹데이만 나오게, ②선을 그린 뒤 봉 주기를 바꿔도
스케일에 맞춰 유지되게, ③선 색을 임의로 바꿀 수 있게" 요청한 뒤, 작업 중간에 "④주봉/월봉/분기봉이
일봉과 동기화가 안 된다(일봉엔 있는 최신 날짜가 나머지엔 없다) — 일봉을 바탕으로 리샘플링해달라"를
추가 요청. `10_차트_조회.py`에만 적용(백테스팅 페이지 차트는 요청 범위 밖이라 손대지 않음):

- **①거래 없는 구간 제거**: 기존 `rangebreaks=[dict(bounds=["sat","mon"])]`는 주말만 가리고 공휴일·
  (분봉/시간봉의) 장외시간은 못 가렸다. `render_chart()`에서 x축을 `type="category"`로 바꿔 실제
  데이터가 있는 봉만 순서대로 나열하는 방식으로 교체(모든 트레이스의 `x=df.index` → 미리 포맷한
  `x_labels = df.index.strftime(date_fmt)` 문자열 배열, 총 14곳). 이러면 캔들차트뿐 아니라 분봉의
  장마감~다음 개장 사이 공백도 자동으로 사라진다(날짜별 대신 "실제로 존재하는 봉"만 그려지므로).
- **②도형 봉주기 간 유지 (스케일 문제)**: category 축으로 바꾸면서 Plotly가 도형의 x0/x1을 실제
  날짜가 아니라 "몇 번째 카테고리인지" 정수 인덱스로 관리한다는 걸 처음에 놓쳐서, 저장해뒀다가 복원한
  선이 주봉에서 완전히 엉뚱한 위치(빈 공간)에 나타나는 버그가 났음(스크린샷으로 실측 확인 후 원인
  파악). `core/theme.py::inject_chart_interactions()`에 `indexToLabel`/`labelToIndex` 변환 함수를
  추가해, localStorage에 저장할 때는 인덱스를 그 시점의 실제 카테고리 라벨(날짜 문자열)로 바꿔
  저장하고, 복원할 때는 그 날짜와 가장 가까운 카테고리를 현재 축에서 다시 찾아 인덱스로 되돌린다 —
  이렇게 해야 일봉에서 그은 선이 주봉으로 바꿔도 비슷한 실제 날짜/가격 위치에 재배치된다(정확히 같은
  날짜가 없으면 가장 가까운 봉에 스냅 — 해상도가 바뀌었으니 당연한 동작). path 타입(자유 곡선
  도형)은 x0/x1이 아니라 SVG path 문자열이라 이 변환 대상이 아님(추세선/사각형/원만 정확히 재배치).
- **③도형 색상 변경**: 처음엔 Plotly의 `_fullLayout._activeShapeIndex`로 "클릭된 도형"을 알아낼
  생각이었으나(직전 세션 기록에 그렇게 확인했다고 적혀 있었음), 실제로 붙어있는 Plotly 버전
  (3.7.0 — pip plotly 6.9.0의 `get_plotlyjs()`로 확인)으로 순수 Plotly HTML만 떼어내 독립 재현해보니
  클릭해도 그 값이 전혀 갱신되지 않음을 확인(꼭짓점 드래그 자체는 내부 상태 없이도 잘 동작). Plotly
  버전이 올라가며 도형 편집 내부 구현이 바뀐 것으로 추정 — 옛 기록을 그대로 믿지 않고 재검증해서
  다행히 이번에 잡음. 대신 Plotly가 모든 편집 가능한 도형마다 항상 그려두는 클릭 판정용 투명 오버레이
  `<g drag-helper="true" data-index="N">`를 document 클릭 이벤트에서 직접 찾아 인덱스를 읽는 방식으로
  교체 — 내부 상태가 아니라 항상 렌더링되는 DOM 구조라 더 안정적. 클릭한 도형 좌하단에 원형
  `<input type="color">`를 띄워 즉시 색 변경 가능(`Plotly.relayout(gd, {"shapes[N].line.color": ...})`).
  **버그 하나 더 발견/수정**: 클릭 리스너를 "이미 설치했으면 건너뛰기" 플래그(`doc.__qtvClickBound`)로
  중복 설치를 막았는데, 이 플래그는 부모 document에 남아있지만 실제 리스너는 봉주기/티커가 바뀌어
  `components.html` iframe이 통째로 새로 만들어질 때마다 브라우저가 자동으로 떼어내 버려서(iframe
  컨텍스트가 파괴되면 그 iframe 코드가 등록한 네이티브 DOM 리스너는 브라우저가 정리함 — Plotly의
  커스텀 `gd.on()` 이벤트는 이 정리 대상이 아니라 계속 살아있어서 나머지 기능은 멀쩡했음), 두 번째
  리런부터는 클릭이 조용히 아무 반응이 없었다. 콘솔 로그를 임시로 심어 "설치는 됐다는데 클릭 이벤트
  자체가 안 잡힌다"는 걸 직접 확인한 뒤, 매번 이전 리스너를 명시적으로 `removeEventListener`로 뗀
  다음 새로 붙이는 방식으로 고침(핸들러 함수 자체를 `doc.__qtvClickHandler`에 저장해 다음 리런에서
  정확히 그 레퍼런스로 제거).
- **④주봉/월봉/분기봉을 일봉에서 리샘플링**: yfinance가 "1wk"/"1mo"/"3mo"로 직접 주는 데이터는
  일봉과 별도 피드라 최신 반영이 늦어 동기화가 어긋난다. `core/market_data.py::resample_ohlcv(df, rule)`
  신규 추가 — Open=구간 첫 값/High·Low=구간 최고·최저/Close=구간 마지막 값/Volume=합계로 집계하고,
  인덱스는 달력상 주/월/분기 마지막 날이 아니라 그 구간의 **실제 마지막 거래일**로 맞춤(월말이
  주말이면 실제 거래일로 당김). `10_차트_조회.py`의 `_cached_price_history()`가 이 세 interval일 때
  yfinance에 직접 요청하지 않고 항상 "1d"를 받아와 여기서 리샘플링하도록 교체
  (`RESAMPLE_RULE_FOR_INTERVAL = {"1wk": "W-FRI", "1mo": "ME", "3mo": "QE"}` — pandas 2.3에서 "M"/"Q"는
  deprecated라 "ME"/"QE" 사용). MA/RSI/MACD 등 지표는 `render_chart()`가 어떤 `df`를 받든 그대로
  계산하므로 별도 대응 불필요. `tests/test_market_data.py`에 단위테스트 4개 추가(주간 집계 정확성,
  달력상 월말이 아닌 실제 마지막 거래일로 라벨링되는지, 빈 입력 처리).
- **동시 작업 주의사항**: 이 세션 도중 다른 Claude 세션이 같은 `core/theme.py`/`10_차트_조회.py`에
  동시에 Gemini 사용량 배지·백그라운드 job_manager 기능을 추가하고 있어 파일이 실시간으로 바뀌는
  채로 작업함 — 매 편집 전 파일을 다시 읽어 충돌 없이 이어붙임, 두 작업 모두 서로 다른 영역이라 실제
  충돌은 없었음.
- 검증: `python -m pytest tests/ -q` 전체 215개 통과. Playwright로 실제 브라우저 다수 라운드 검증
  (커스텀 minimal Plotly HTML 재현까지 포함해 색상피커 버그 두 개를 실제로 잡아냄) — 일봉/주봉/월봉/
  분기봉 전부 마지막 날짜가 동일(2026-07-10)함을 확인, 일봉에서 그은 선이 주봉 전환 후에도 캔들 위
  근접한 위치로 재배치됨을 좌표+스크린샷으로 확인, 도형 클릭 시 색상피커가 뜨고 변경한 색이
  `layout.shapes[].line.color`와 localStorage에 즉시 반영됨을 확인, 꼭짓점 드래그(다른 캔들 위로
  옮기기)가 이 변경들 이후에도 여전히 동작함을 재확인. 이 세션에서 띄운 임시 테스트 서버들은 모두
  종료하고, `app/Home.py`를 8501 포트(정식 포트)로 재기동해둠(핵심 파일이 여러 번 바뀌어 오래된 모듈을
  캐싱한 프로세스가 남아있으면 이전에 겪었던 것과 같은 ImportError가 재발할 수 있어 재기동으로 예방).

## 다음 세션에서 할 일

모든 모듈이 완료된 상태. 새 세션에서 이어갈 작업이 없다면:
1. `python -m pytest tests/ -q` 로 회귀만 확인.
2. 사용자가 신규 기능/버그 수정을 요청하면 이 표에 새 행을 추가해 추적.
3. `git status` 로 미커밋 변경사항이 많으니(전체가 아직 커밋 전) 사용자가 커밋을 요청하면 진행.
4. 각 모듈 규칙은 `README.md`의 "개발 컨벤션" 절, 스펙은 `SPEC.md` 참고.

## 알려진 제약 / 결정 사항

- **AI 제공자는 Anthropic → Gemini로 전환 완료** (2026-07-12). `core/nl_strategy.py`,
  `core/threads_summary.py`, `core/portfolio.py` 세 곳 모두 `core/gemini_client.py`(공통 헬퍼)를
  통해 `google-genai` SDK를 사용. `.env`에 실제 키 설정됨 (커밋 안 됨, gitignore 처리).
  - **다중 키 + 모델 자동 전환 (2026-07-12 추가)**: 사용자가 API 키 3개를 추가로 제공하며 "하나
    다 쓰면 가변적으로 바꿔달라"고 요청 → `core/gemini_client.py` 신설. `.env`의
    `GEMINI_API_KEYS`(쉼표구분 다중키, 신규 표준)를 우선 사용하고 없으면 기존 `GEMINI_API_KEY`
    (단일)로 폴백. `generate_content(models, ...)`가 **모델별로** 등록된 키를 순서대로 시도하다가
    429(RESOURCE_EXHAUSTED)만 다음 키/모델로 자동 전환하고, 그 외 오류(400 등)는 재시도 없이 즉시
    올려서 호출부의 기존 키워드 폴백이 그대로 동작하게 한다(`google.genai.errors.APIError.code`로
    판별, 문자열 매칭 아님). 세 모듈 모두 옛 `_MODEL` 단일 상수 대신
    `gemini_client.COMPLEX_TASK_MODELS`(nl_strategy, 복잡한 구조화 출력용)/
    `gemini_client.LIGHT_TASK_MODELS`(threads_summary·portfolio, 가벼운 작업용) 우선순위 리스트를
    사용. 이 계정에서 실제로 되는/안 되는 모델을 3개 키 전부에 대해 직접 호출해 확인함(2026-07-12):
    `gemini-3-flash-preview`/`gemini-3.5-flash`/`gemini-2.5-flash`/`gemini-flash-latest`/
    `gemini-flash-lite-latest`/`gemini-3.1-flash-lite` 정상, `gemini-*-pro-*` 계열
    전부(3-pro-preview/3.1-pro-preview/2.5-pro/pro-latest)와 `gemini-2.0-flash(-lite)`는 무료
    티어에서 429, `gemini-2.5-flash-lite`는 "신규 프로젝트에 더 이상 제공 안 함"으로 404 — 근거와
    함께 `core/gemini_client.py` 상단 주석에 기록해둠(결제 연결 시 pro 계열 재시도 가능).
    테스트는 `tests/test_gemini_client.py`(키 우선순위, 429 자동 전환, 400은 즉시 전파, 전부
    소진 시 마지막 에러 전파) 4개 추가.
  - 구조화 출력은 Gemini의 `response_json_schema` (표준 JSON Schema 그대로 사용 가능, Anthropic의
    `output_config.format.json_schema`와 거의 1:1 대응)로 구현. `response.text`로 결과 파싱.
  - 키 없거나 호출 실패 시 fallback 로직 사용은 기존과 동일 (예외 던지지 않음). 안내 문구/주석의
    `ANTHROPIC_API_KEY` 문자열은 전부 `GEMINI_API_KEY`로 치환했고, 테스트(`test_portfolio.py`,
    `test_threads_summary.py`)의 페이크 모듈도 `google.genai`로 갱신함.
  - **주의: `response_json_schema`에 `maxItems`를 쓰면 안 됨.** 문서에는 지원 키워드로 나와 있지만
    `gemini-3-flash-preview`에서 실제로는 400 INVALID_ARGUMENT로 요청 자체가 거부됨을 실증 확인함
    (`minItems`는 정상 동작). 배열 길이를 제한하고 싶으면 스키마가 아니라 파싱 후 Python 코드에서
    검증해야 한다 (`core/nl_strategy.py`의 `_staged_config_is_sane`/`_MAX_SANE_CONDITIONS` 패턴 참고).
  - `core/nl_strategy.py`의 1:2:6 staged 전략 해석기는 실제 후지모토 시게루 유튜브 영상(자동 자막,
    타임스탬프 포함 그대로)으로 end-to-end 검증함: 파싱 → `core.backtest_engine.run_backtest` →
    AAPL 2018~2026 백테스트까지 정상 동작(트레이드/지표 생성 확인). 검증 중 AI가 간헐적으로
    (a) JSON이 파싱 안 되는 폭주 응답, (b) 조건이 100개 넘게 중복되는 유효하지만 엉터리인 응답을
    내는 것을 발견 — `_staged_config_is_sane()`으로 조건/단계 개수 상한을 검증해 이상하면 자동으로
    `_fujimoto_staged_template()`(Pine Script와 정확히 일치하는 손검증 템플릿)로 폴백하도록 방어
    코드 추가. `STAGED_SYSTEM_PROMPT`도 보강해(동시조건 누락 금지, emergency_exit 필수화) 재검증
    결과 4/4 정상적인 staged_config 생성(entry_stages 0.1/0.2/0.6, exit_stages 대칭, emergency_exit
    항상 포함) 확인함.
- **다크모드 토글 완전 제거** (2026-07-12): 사용자가 "라이트모드 없이 다크모드만 존재하게 해달라"고
  요청 → `core/theme.py`에서 `_LIGHT` 팔레트/`st.toggle`을 삭제하고 `_DARK`만 항상 적용하도록 단순화.
  다른 어떤 파일도 `dark_mode` session_state를 참조하지 않아 부작용 없음.
- **자연어 전략 등록의 "수익률 0%" 원인 진단 + 재발 방지 장치 추가** (2026-07-12): 사용자가 다른
  유튜브 영상(볼린저밴드+인걸 캔들+RSI 전략)을 자연어로 등록했더니 실제 매수 신호는 발생하는데
  누적수익률이 정확히 0%가 나온다고 보고. 원인: AI가 만든 staged_config에서 진입 조건("종가가
  볼린저 밴드 하단보다 낮다")과 청산/emergency_exit 조건("종가가 20일 이평보다 낮다", `ma_cross
  short=1/long=20/type=dead`로 표현됨)이 수학적으로 항상 동시에 참이 됨(밴드 하단은 정의상 항상
  중심선보다 낮으므로) — 그래서 진입하자마자 같은 날 바로 청산되어 포지션을 하루도 못 버티고
  수익률이 항상 0%가 나옴. `core/backtest_engine.py`로 직접 재현 확인(AAPL 실데이터로 매매 99건 중
  99건 전부 당일 청산).
  - 근본 원인 중 하나: 이 영상의 실제 매수 신호인 "인걸(장악형) 캔들 패턴"을 표현할 지표가 아예
    없어서 AI가 볼린저+RSI만으로 억지로 근사했음. → `core/indicators.py`에 `compute_engulfing()`,
    `core/strategy_engine.py`에 `engulfing` 지표(`direction="bullish"|"bearish"`) 추가하고
    `core/nl_strategy.py`의 스키마/프롬프트(SYSTEM_PROMPT, STAGED_SYSTEM_PROMPT,
    STAGE_CONDITION_PROPERTIES)에도 반영.
  - **재발 방지 장치**: `core/backtest_engine.py::diagnose_strategy_health(indicator_config)` 추가 —
    AI가 만든 전략을 대표 종목(AAPL)·최근 5년 구간에 실제로 돌려보고, 발생한 매매가 전부(또는
    50% 이상) "진입 당일 바로 청산"되는 패턴인지 경험적으로 검사한다(조건을 정적으로 분석하는 대신
    실제 실행 결과의 매매 보유기간을 관찰하는 방식이라 어떤 지표 조합에서 발생하든 일반적으로
    잡아낸다). `app/pages/1_백테스팅.py`의 "🤖 자연어 전략 등록" 탭에서 AI 해석 직후 자동 호출되어
    `st.warning()`으로 즉시 표시됨 — 사용자가 프리뷰 백테스트를 직접 돌려보기 전에 미리 경고.
    `STAGED_SYSTEM_PROMPT`에도 "청산 조건이 진입 조건보다 항상 더 쉽게 만족되면 안 된다"는 경고
    문구를 추가함(프롬프트 레벨 방어는 보조 수단, `diagnose_strategy_health`가 최종 안전망).
  - 테스트: `tests/test_strategy_engine.py`(compute_engulfing/engulfing 조건 2개),
    `tests/test_backtest_engine.py`(diagnose_strategy_health 정상/이상 케이스 2개) 추가, 전체 130개
    통과.
  - 참고: 이 세션에서 Gemini `gemini-3-flash-preview`의 무료 티어 일일 요청 한도(20회/일)를 검증
    과정에서 다 써서 이후 호출은 429(RESOURCE_EXHAUSTED)로 폴백 로직만 동작함 — 앱은 정상 동작하지만
    (예외 없이 키워드 기반 대체), 내일 한도 리셋 전까지는 실제 AI 해석 결과를 보려면 결제 연결이
    필요할 수 있음.
- FRED_API_KEY는 아직 미설정 상태. 매크로 대시보드가 최소한 에러 없이 안내 문구를 보여줘야 함.
- **다크모드 기본값 이슈 수정** (2026-07-12): 사용자가 "페이지마다 다크모드 여부가 다른 것 같다"고
  보고. 원인은 `core/theme.py`의 커스텀 CSS가 `.stApp`/사이드바만 스타일링하고 Streamlit 자체
  최상단 헤더/툴바(`stHeader`/`stToolbar` 등)는 건드리지 않아, 첫 페인트 시 라이트 테마로 보였던 것.
  `.streamlit/config.toml`에 `[theme] base="dark"` + 팔레트 고정을 추가해 최초 로딩부터 다크로
  고정하고, `theme.py`에도 헤더/툴바용 CSS 규칙을 추가해 토글 상태를 따라가도록 보강함.
- 네트워크가 필요한 외부 API(yfinance, SEC EDGAR, FRED) 테스트는 `monkeypatch`로 목(mock) 처리하고,
  DB 관련 테스트는 `tests/conftest.py`의 `db_session` fixture(임시 SQLite)를 사용한다
  (`test_guru_tracker.py` 패턴 참고).
- 각 신규 페이지 파일은 `app/pages/{순번}_{한글이름}.py` 형식, 상단에 sys.path 부트스트랩 코드 필수.

**자연어 staged 전략의 "진입=청산 자기모순" 버그를 프롬프트 경고에서 자동 검증+자기교정 루프로 강화**
(2026-07-12, 같은 날 후속 요청). 사용자가 유튜브 볼린저밴드+인걸캔들+RSI 전략을 자연어로 등록해
staged(1:2:6) JSON을 얻었는데, 백테스트 매매횟수는 40건인데 누적수익률/CAGR/MDD/샤프/승률이 전부
정확히 0으로 나왔다고 보고. 원인 분석: AI가 만든 `emergency_exit`(및 `exit_stages[0]`)가
`ma_cross short=1 long=20 type="dead"` — short=1짜리 이평은 사실상 종가 그 자체라 "종가가 20일
이평 아래"라는 **상태(state)** 조건이 됐는데, 진입 조건(볼린저 하단 이탈)이 참인 날은 정의상 항상
이 상태도 참이었음. `simulate_staged_positions`는 같은 반복문 안에서 진입 처리 직후 곧바로
긴급청산을 체크하므로, 포지션이 `weight_signal`(자산가치 곡선에 반영되는 값)에 한 번도 반영되지
못한 채 매일 진입~당일청산을 반복 — 그래서 매매 40건은 로그로 잡히지만(진입일=청산일, 진입가=
청산가로 수익률 정확히 0.0%) 실제 보유 기간이 0이라 다른 지표는 전부 0. AAPL로 재현해 68건 전부
동일일 매매/수익률 0.0임을 실제 백테스트로 확인함.
- 이 정확한 패턴(진입≈청산 자기모순)을 잡는 `diagnose_strategy_health`와 `STAGED_SYSTEM_PROMPT`의
  경고 문구는 이미 이전 세션에서 만들어져 있었는데도 재발함 — **프롬프트 지시만으로는 AI가 항상
  지키지 않는다**는 것이 이번에 실증됨(같은 세션에서 라이브 재현 시에는 문제없이 통과하기도 했음,
  즉 AI 출력이 매번 다름). 그래서 방어를 "프롬프트 문구"에서 "생성 파이프라인 내부의 실제 검증
  +자동 재시도"로 한 단계 강화함.
- `core/nl_strategy.py`의 `_interpret_staged_strategy_text`를 재작성: AI가 staged config를 생성하면
  즉시 `_check_entry_exit_overlap()`(내부적으로 `diagnose_strategy_health` 재사용, AAPL 5년 실제
  백테스트로 진입일=청산일 비율 경험적 검증)을 호출. 문제가 발견되면 그 진단 메시지를 그대로 AI에게
  피드백으로 돌려주며 **한 번 더 생성을 재시도**(자기교정, 최대 2회 시도). 재시도까지 실패하면
  결과는 반환하되 `health_warnings`에 경고를 담고 `description`에 "⚠️ 자동 정합성 검증에
  실패했습니다"를 강제로 붙여 호출부가 조용히 넘어갈 수 없게 함. 반환 dict에 `health_warnings`
  키를 항상 포함시켜 UI가 아니라 함수 계약 자체에서 검증 결과가 보장되도록 함(이전에는
  `app/pages/1_백테스팅.py`가 별도로 `diagnose_strategy_health`를 다시 호출해야 경고가 보였는데,
  그 호출 자체를 잊거나 건너뛸 수 있는 구조였음).
- `app/pages/1_백테스팅.py`: 중복 `diagnose_strategy_health` 호출 제거하고 `nl_result["health_warnings"]`
  를 그대로 사용. 경고를 `st.warning`(넘어갈 수 있음)에서 `st.error`로 격상하고, 경고가 남아있으면
  "위 경고를 확인했습니다" 체크박스를 체크해야만 "📚 전략 라이브러리에 저장" 버튼이 활성화되도록
  `disabled=` 가드 추가 — 이전에는 경고가 떠도 저장 버튼을 누르는 데 아무 제약이 없었음.
- 검증: `tests/test_nl_strategy.py`(신규) 6개로 자기교정 재시도 성공/재시도 소진/API키 없음/AI
  실패/1회만에 통과(재시도 안 함)/진단 함수 예외 흡수 케이스를 전부 mock으로 커버. 그리고 실제
  Gemini API + yfinance로 라이브 검증: 사용자가 겪은 것과 동일한 패턴(진입=볼린저 하단, 청산=20일
  이평선 아래)을 자연어로 다시 넣어 `1_백테스팅.py`를 Streamlit `AppTest`로 직접 구동 — 이번에는
  AI가 청산을 `rsi_cross`(과매수 이벤트)+`ma_cross`(더 긴 20/60 데드크로스)로 만들었고
  `health_warnings`가 빈 배열로 통과함을 실제로 확인. 사용자가 원래 얻었던 깨진 JSON도 직접 고쳐
  (`exit_stages`를 상태 조건 대신 RSI≥70 이벤트로 통일) AAPL(승률 60%, 10건)/TSLA(승률 82%, 11건)로
  정상적인 0이 아닌 결과가 나옴을 확인. 전체 pytest 161개 통과.
**staged 전략의 entry/exit 단계 수 불일치(인덱스 미스매치) 버그 수정** (2026-07-12, 같은 날 후속
요청). 직전 항목에서 "알려진 잔여 한계"로 남겨뒀던 문제를 사용자가 바로 고쳐달라고 요청.
- 원인: `core/strategy_engine.py`의 `simulate_staged_positions`가 청산을
  `for k in range(1, n_exit+1): if k in open_tags and exit_signals[k-1]... ` 식으로, 청산 단계 k를
  "인덱스가 같은 진입 태그 k"에만 매칭시켰다. "마지막 청산 단계가 뜨면 잔량 전부 정리"라는 문서화된
  동작도 `if k == n_exit and open_tags` 블록이 `k in open_tags`(즉 태그 n_exit 자신이 열려있을 때)
  안에 중첩돼 있어, entry_stages가 exit_stages보다 많고(예: 3개 vs 2개) 마지막 entry 단계로 직행
  진입(중간 단계를 건너뜀)해 태그 인덱스가 `exit_stages` 범위를 벗어나면, 그 태그는 일반 청산으로
  절대 안 닫히고 `emergency_exit`에만 의존하게 되는 구조적 허점이 있었음.
- 수정: 마지막 청산 단계(exit_stages의 마지막 원소)를 "태그 인덱스와 무관하게 열려있는 물량을 전부
  정리하는 신호"로 재정의 — `elif n_exit > 0 and exit_signals[n_exit-1].iloc[i]:` 분기를 추가해 그
  조건이 참이면 `open_tags`에 뭐가 들어있든 전부 청산 이벤트로 기록하고 비운다. 나머지(마지막이 아닌)
  청산 단계는 기존과 동일하게 자기 인덱스와 일치하는 태그만 개별 정리(`range(1, n_exit)`로 축소,
  마지막 인덱스는 위에서 이미 처리하므로 제외). 문서화된 "마지막 단계=잔량 전부 정리" 동작을 코드가
  실제로 항상 보장하도록 만든 버그 수정이며 새 기능 추가는 아님.
- 검증: `tests/test_strategy_engine.py`에 `combine_conditions`를 모킹해 진입/청산 신호 타이밍을
  완전히 통제하는 방식으로 4개 테스트 추가 — ①entry 3단계/exit 2단계로 마지막 단계 직행 진입한
  태그가 마지막 청산 신호로 정상 정리되는지(수정 전 코드로 되돌려서 실행해보니 실제로 실패함을
  먼저 확인 → 수정 후 통과로 재확인), ②마지막이 아닌 청산 단계는 매칭되는 태그만 개별 정리하는지
  회귀 확인, ③emergency_exit은 여전히 단계 무관 전량 청산인지, ④`extract_staged_trades`의 가중평균
  체결가 계산. 기존 레퍼런스 전략(`_fujimoto_staged_template`, entry/exit 3단계씩 매칭)도 AAPL
  실백테스트로 재확인해 회귀 없음 확인(누적수익률 80%/CAGR 8.16%/27건, 자가진단 통과). 참고로 이
  수정 덕분에 이전엔 감지되지 못했던 "느슨한 마지막 청산 조건" 문제(태그가 아예 안 닫혀서
  `diagnose_strategy_health`가 same-day 비율을 계산할 기회조차 없었던 경우)도 이제 정상적으로
  잡히게 됨 — 즉 이 수정이 앞선 자기교정 파이프라인의 탐지력도 함께 강화함. 전체 pytest 165개 통과.

**우측 상단에 Gemini API 사용량 배지 추가** (2026-07-12, 같은 날 후속 요청). 사용자가 "자연어 전략
해석이 왜 이렇게 오래 걸리냐"고 물어봐 실측(Gemini 1회 호출 15~25초가 병목, 자가진단 자체는
0.1~0.5초로 무시할 수준, staged 전략의 자기교정 재시도가 걸리면 최대 2배)한 뒤, 사용자가 "Gemini
키 한도/용량을 화면에서 바로 확인할 수 있게 우측 상단에 작게 표시해달라"고 요청.
- Google 무료 티어는 잔여 할당량을 조회하는 API가 없어 "정확한 남은 횟수"는 알 수 없다 — 대신
  `core/models.py`에 `GeminiCallLog`(model/key_label/status["ok"|"quota_exceeded"|"error"]/
  error_message) 신설, `core/gemini_client.py`의 `generate_content()`가 (모델,키) 조합을 시도할
  때마다 결과를 기록하도록 `_log_call()` 추가(예외를 전부 삼켜 로깅 실패가 실제 AI 호출을 절대
  막지 않게 함) + `get_usage_today()`로 오늘 시도/성공/한도초과(429)/기타오류 횟수를 집계.
  이 로거가 `generate_content()`의 유일한 진입점에 있어 nl_strategy/threads_summary/portfolio
  전부가 자동으로 커버됨(별도 계측 불필요).
- `core/theme.py`에 `render_gemini_usage_badge()` 추가, 모든 페이지가 이미 호출하는
  `apply_theme()` 끝에서 자동 실행되도록 배선(페이지별로 따로 호출할 필요 없음). 키 없음(회색)/
  정상(초록, "🔑 Gemini 오늘 N회")/한도초과 이력 있음(주황)/방금 막 한도초과(빨강, "⚠️ 한도 근접")
  4단계로 색을 구분하고, hover 시 키 개수/성공/한도초과/오류 세부 내역을 title 툴팁으로 보여준다.
- **버그 발견 및 수정**: 처음 구현한 버전은 Streamlit `AppTest`(Python 레벨)에서는 정상 렌더링됐지만
  실제 브라우저(Playwright로 라이브 스크린샷 확인)에서는 DOM에 아예 나타나지 않았다 — 원인은
  `st.markdown(unsafe_allow_html=True)`에 넘긴 HTML `<div>`의 여는 태그 자체가 (들여쓰기된
  `style="..."` 속성 때문에) 여러 줄에 걸쳐 있어, 마크다운의 HTML 블록 인식이 실패했기 때문
  (`apply_theme()`의 `<style>` 블록은 같은 패턴이어도 문제없이 동작해 처음엔 안 의심했음 — `<style>`
  태그는 브라우저가 별도로 raw-text 취급해 마크다운 블록 인식 실패와 무관하게 항상 파싱되는 반면,
  `<div>`는 그렇지 않음). 태그 전체를 한 줄로 압축하고 tooltip의 개행은 `&#10;` HTML 엔티티로
  치환해서 고침. 이 라운드트립 검증 과정에서 실제로 진행 중이던 별도 세션의 동시 작업(표현식
  전략 엔진 추가 등, `core/strategy_engine.py`/`app/pages/1_백테스팅.py` 등)과 겹쳐 공용 포트
  8501 서버가 일시적으로 무관한 원인(다른 세션이 아직 완성하지 않은 `inject_auto_pan_after_draw`
  import)으로 에러를 낸 것을 발견 — 혼선을 피하려고 검증은 임시로 별도 포트(8502)에 격리된
  인스턴스를 띄워 진행하고 끝나고 정리함(공용 8501 서버는 건드리지 않음).
- 배치 위치: Streamlit 기본 헤더의 "Deploy" 버튼/"⋮" 메뉴와 겹치지 않도록 `right: 7.5rem`으로
  띄움(처음엔 4.5rem으로 겹쳤던 것을 Playwright로 두 요소의 실제 bounding box를 재서 확인 후 조정).
- 검증: `tests/test_gemini_client.py`에 6개 추가(성공/429후성공/기타오류 로깅, 키 없을 때 집계,
  DB 오류 시 조용히 무시) — 이 파일의 모든 테스트가 실제 운영 DB(`data/quant.db`)를 건드리지
  않도록 `core.db.get_session`을 임시 SQLite로 바꿔치기하는 autouse fixture를 추가함(기존엔
  이 파일에 그런 격리가 없어 이번에 처음 필요해짐). 최종적으로 Playwright로 실제 브라우저에서
  배지가 "Deploy" 버튼과 겹치지 않는 위치에 정확히 렌더링되는 것까지 스크린샷으로 확인. 전체
  pytest 통과(동시 작업 세션이 추가한 표현식 엔진 테스트 포함 215개).

**백테스팅 화면에 "직접 수식 입력" 전략 슬롯 추가** (2026-07-12, 같은 날 후속 요청). 사용자가
"백테스팅 하는 곳에 전략을 넣을 때 내가 직접 수식을 넣을 수 있도록 하는 슬롯도 만들어달라"고 요청
→ 지표 토글/AI 자연어 해석으로 표현하기 어려운 조건을 사용자가 파이썬과 비슷한 문법의 불리언 수식
으로 직접 입력할 수 있는 세 번째 전략 스키마를 추가.
- `core/expression_engine.py`(신규): `{"expression": "close > sma(close, 20) and rsi(close, 14) < 30"}`
  형태의 수식을 평가하는 안전한 인터프리터. `eval()`을 쓰면 임의 코드 실행(OWASP A03: Injection)
  위험이 있으므로, `ast.parse()`로 수식을 파싱한 뒤 허용된 노드 종류(BoolOp/UnaryOp/BinOp/Compare/
  Call/Name/Constant)만 재귀적으로 직접 평가하는 화이트리스트 인터프리터로 구현 — import/속성
  접근(attribute)/subscript/lambda/컴프리헨션 등은 파싱은 되어도 전부 미지원 노드로 거부됨.
  변수는 `open/high/low/close/volume`, 함수는 `sma/ema/rsi/macd_line/macd_signal/macd_hist/
  bb_upper/bb_mid/bb_lower/stdev/highest/lowest/crossover/crossunder/abs/min/max`만 허용(기존
  `ta` 패키지 계산 로직을 그대로 재사용해 지표 토글과 값이 일치하도록 함). `validate_syntax()`는
  합성 OHLCV 데이터로 즉시 실행해보는 방식으로 네트워크 없이 빠른 문법 사전 검증을 제공.
- `core/strategy_engine.py`: `is_expression_config()` 추가, `generate_positions()`/`evaluate()`
  (스케줄러·관심종목 모니터링이 매일 호출하는 진입점)가 `generate_regime_signal()`을 통해 레짐형/
  직접 수식 두 스키마를 모두 투명하게 처리하도록 디스패치 로직을 얹음 — `backtest_engine.run_backtest`
  는 이미 `generate_positions()`를 호출하고 있어 별도 수정 없이 자동으로 직접 수식 전략을 지원하게 됨.
- `core/strategy_library.py`: `detect_strategy_type()`에 `"expression"` 유형 추가,
  `validate_indicator_config()`(전략 관리 화면에서 JSON을 직접 수정할 때 저장 전 검증)에도
  expression 스키마 분기 추가(빈 문자열/문법 오류를 `validate_syntax()`로 저장 전에 걸러냄).
- `app/pages/1_백테스팅.py`: "📊 지표 조합 백테스트" 탭에 "전략 입력 방식" 라디오(🎛️ 지표 토글 /
  ✍️ 직접 수식 입력)를 추가해 같은 실행/결과/저장 흐름을 공유하는 세 번째 입력 슬롯으로 통합
  (1:2:6 단계별 전략이 `loaded_staged_config`로 토글 UI를 대체하던 기존 패턴과 동일하게, 직접 수식도
  `strategy_input_mode`+`expression_text` 세션 상태로 토글 UI를 대체). 사용 가능한 변수/함수
  치트시트를 expander로 제공하고, 실제 백테스트 실행 전에 합성 데이터로 미리 검증하는 "🔍 문법 검증"
  버튼도 추가. 전략 라이브러리 불러오기/저장/전략 관리 페이지의 "유형" 표시도 전부 "✍️ 직접 수식"
  라벨을 인식하도록 확장(`STRATEGY_TYPE_LABELS` 딕셔너리로 통일).
  - **부수 버그 발견 및 수정**: 검증 중 동시에 진행 중이던 다른 세션의 `core/job_manager.py`
    백그라운드 작업 전환 작업과 겹쳐, 백테스트 실행 버튼을 누르면(지표 토글/1:2:6/직접 수식 전부
    무관하게) 작업이 끝나는 다음 rerun에서 `NameError: name 'indicator_config' is not defined`가
    나는 것을 실제 Streamlit `AppTest` 라이브 구동으로 발견함 — `job_manager.start()`로 시작한
    작업은 버튼을 누른 그 rerun이 아니라 이후의 별도 rerun에서 완료되는데, 그 시점엔 `indicator_config`/
    `ticker`/`start_date`/`end_date` 같은 지역변수가 이미 사라져 있었음(페이지 전체가 깨지는 회귀라
    직접 수식 기능 검증을 위해 함께 고침). `job_manager.start()` 호출 직전에 이 값들을
    `st.session_state["pending_config"]` 등으로 저장해두고, 작업 완료 블록에서는 지역변수 대신 그
    값을 읽도록 수정.
- 검증: `tests/test_expression_engine.py`(신규 22개 — sma/rsi/crossover/crossunder가
  `core.indicators`의 기존 계산과 일치하는지, and/or/not 결합, `__import__`/속성 접근/리스트
  컴프리헨션/lambda/subscript/exec 등 위험한 구문이 전부 거부되는지, 문자열 리터럴 거부, 미지원
  변수/함수 거부, 비교 연산자 없는 수식 거부, `validate_syntax()` 정상/오류 케이스),
  `tests/test_strategy_engine.py`(`is_expression_config`/`generate_positions` 디스패치 2개),
  `tests/test_backtest_engine.py`(`run_backtest`가 expression config로 정상 동작 + 잘못된 수식이면
  `ExpressionError`를 전파하는지 2개), `tests/test_strategy_library.py`(신규 — `detect_strategy_type`/
  `validate_indicator_config`가 세 스키마를 전부 올바르게 판별/검증하는지 9개) 추가. 그리고 임시
  SQLite(`DATABASE_URL` 환경변수로 실제 `data/quant.db`와 분리)로 Streamlit `AppTest`를 라이브
  구동해 end-to-end 확인: 직접 수식 모드 전환 → AAPL 실데이터로 백테스트 실행(백그라운드 job 완료까지
  폴링) → 캔들차트/성과지표 렌더링 → 전략 라이브러리 저장 → 새 세션에서 "불러오기"로 저장된 수식이
  `strategy_input_mode`/`expression_text`에 정확히 복원되는지, "전략 관리" 페이지 목록에 "✍️ 직접
  수식"으로 표시되는지까지 전부 실제 데이터로 확인. 전체 pytest 215개 통과.

**모든 페이지의 무거운 작업을 백그라운드 실행으로 전환** (2026-07-12, 같은 날 후속 요청). 사용자가
"백테스팅 중 다른 페이지(예: 밸류에이션)로 이동해도 백테스팅 작업이 이어서 진행되게 해달라, 이건
모든 페이지에 대해서도 마찬가지"라고 요청. Streamlit은 사용자가 다른 페이지로 이동(또는 아무 위젯이나
조작)하면 현재 스크립트 실행을 그 자리에서 중단하고 새로 rerun하므로, `with st.spinner(...): 결과 =
무거운_함수()`처럼 페이지 스크립트 안에서 동기 실행하던 작업은 페이지를 벗어나는 순간 같이 취소된다 —
그래서 실제 작업은 스크립트 실행 스레드가 아닌 별도 스레드에서 돌리고, 페이지는 세션에 저장한 job id로
진행 상태만 폴링하는 구조로 바꿔야 한다.

- `core/job_manager.py`(신규) — 1인 로컬 앱 전제(SPEC.md 0장)라 작업 레지스트리를 프로세스 전역
  (모듈 레벨 dict + `ThreadPoolExecutor`)에 둔다. 세 가지 API:
  - `start(slot, func, *args, label=..., **kwargs)`: 버튼 클릭 등 명시적 트리거에서 새 작업을 시작.
  - `ensure(slot, params_key, func, ...)`: 페이지 로드 시 자동 실행되는 조회용 — `params_key`(예:
    티커)가 이전과 같으면 추적 중인 작업을 재사용하고 다르면 새로 시작(같은 작업이 폴링 rerun마다
    중복으로 다시 시작되는 것을 방지).
  - `render(slot, running_label=...)`: 매 rerun마다 호출 — 진행 중이면 경과 시간과 함께 `st.info` +
    `time.sleep` + `st.rerun()`으로 자동 새로고침하고, 끝났으면 `Job`(결과/에러)을 반환하며 추적을
    정리한다.
  - `render_active_jobs_sidebar()`: 모든 페이지 사이드바에 현재 백그라운드에서 실행 중인 작업 목록을
    보여준다(다른 페이지로 이동해도 이전 작업이 계속되고 있음을 확인할 수 있게). 이 함수 자체는
    rerun을 강제하지 않는다 — 무관한 페이지까지 몇 초마다 강제로 재실행하면 사용자가 입력 중인 다른
    위젯 포커스가 끊기는 부작용이 있어, 작업을 소유한 페이지의 `render()`만 실시간 폴링을 하고 다른
    페이지는 자연스러운 rerun 때마다 최신 상태를 보여주는 정도로 범위를 한정함.
- 적용 대상(모든 페이지의 `st.spinner` 블로킹 호출 전부 전환): `1_백테스팅.py`(백테스트 실행/AI 자연어
  해석/자연어 미리보기 백테스트), `2_Threads_요약.py`(글 분석/주간 리포트 생성/리포트 회고),
  `3_관심종목_모니터링.py`(관심종목 스캔), `4_거장_포트폴리오.py`(거장별 동기화/ETF 구성종목 조회),
  `5_퀀트_스크리너.py`(S&P500 스크리닝), `6_밸류에이션.py`(데이터 조회/피어 비교, `ensure()` 사용),
  `7_매크로_대시보드.py`(FRED 스냅샷, `ensure()` 사용), `8_포트폴리오_관리.py`(실시간 가격/리스크
  계산/AI 코멘트), `10_차트_조회.py`(가격 히스토리 조회, `ensure()` 사용). 모든 페이지 상단에
  `job_manager.render_active_jobs_sidebar()` 호출도 추가.
- **주의해서 피한 버그 패턴**: `job_manager.start()`로 시작한 작업은 버튼을 누른 그 rerun이 아니라
  나중의 별도 rerun(폴링 rerun)에서 완료되는데, 그 rerun에서는 `if <버튼 클릭>:` 블록 안에서만
  대입되던 지역변수가 이미 사라져 있다(버튼 클릭 이벤트는 그 rerun에서만 True). `1_백테스팅.py`의
  기존 백테스트 실행부에서 `indicator_config` 등을 그렇게 참조하다 `NameError`가 나는 것을 다른
  세션이 동시 검증 중 발견해 `st.session_state["pending_config"]` 등으로 미리 저장해두는 방식으로
  고쳤음(작업 시작 시점에 필요한 값을 세션에 저장 → 완료 블록에서는 지역변수 대신 세션값을 읽음). 이후
  나머지 페이지를 전환할 때는 완료 블록이 지역변수를 참조하지 않는지(위젯 값이면 `key=` 바인딩 또는
  무조건 매 rerun마다 재계산되는 값인지, 아니면 `job.result`/루프 변수인지) 전부 확인하며 진행함.
- 검증: `tests/test_job_manager.py`(신규 7개) — Streamlit `AppTest.from_function`으로 실제 스크립트를
  구동해 정상 완료/예외 발생 시 에러 상태 전달/추적 없음/`ensure()`의 중복 시작 방지/`params_key`
  변경 시 새 작업 시작/사이드바 렌더링까지 확인. 그리고 실제 앱을 기동해 Playwright로 라이브 검증:
  (1) 퀀트 스크리너에서 S&P500 전체 스크리닝을 실행한 직후 곧바로 매크로 대시보드로 이동 →
  이동한 페이지의 사이드바에 "🔄 백그라운드 작업 실행 중 — ⏳ 퀀트 스크리닝 — N초 경과"가 실시간으로
  표시됨을 확인, (2) 다시 스크리너 페이지로 돌아가면 스캔이 이미 완료되어 결과 테이블이 바로 보임을
  확인, (3) 백테스팅 페이지에서 백테스트 실행 → 곧바로 밸류에이션 페이지로 이동 → 다시 백테스팅
  페이지로 돌아가면 에러 없이 성과 지표/캔들차트가 정상 렌더링됨을 확인(위 NameError 버그가 실제로
  고쳐졌는지 재확인 포함). 전체 pytest 215개 통과.

**가격 데이터 로컬 캐시를 "쿼리별 스냅샷"에서 "티커·봉주기별 누적 저장소"로 재설계** (2026-07-14).
사용자가 무료 MVP 인프라를 상의하다가, 실제 최우선 요청은 "티커를 부를 때마다 / 알고리즘을
학습시킬 때마다 매번 주가를 새로 받는 대신 미리 저장해서 빠르게 불러오고 싶다"는 것으로 확인됨
(`STRATEGY_TUNING_ENGINE_SPEC.md`의 100종목×파라미터그리드 튜닝 엔진이 정확히 이 반복 조회 패턴이라
그 인프라 선행 작업이기도 함).
- **문제 확인**: 기존 `core/market_data.py` 캐시는 `{티커}_{start}_{end}_{interval}.csv`를 캐시 키로
  써서, `end=None`(오늘까지)처럼 매일 바뀌는 조회가 들어올 때마다 완전히 새 파일로 전체 이력을
  재다운로드했다. 실측: `data/cache/`에 AAPL 하나만으로 겹치는 캐시 파일 68개(5MB) 누적 확인.
- **재설계**: (ticker, interval)별로 Parquet 파일 하나에 "지금까지 받아온 전체 이력"을 계속 누적.
  요청 시작일이 저장 범위보다 과거면 그 차이만(`_download`+병합), 종료일이 저장 범위를 벗어나면
  저장된 마지막 날짜부터 델타만 받아온다. **명시적 end가 있고 이미 저장소가 커버하는 요청**(백테스트/
  다종목 튜닝처럼 같은 과거 구간을 반복 조회하는 패턴)은 `cache_ttl`(6시간)과 무관하게 항상 로컬
  데이터만으로 즉시 응답 — 확정된 과거 봉은 절대 재다운로드하지 않는다. `end=None`(최신 구간) 요청만
  6시간 TTL로 델타 갱신한다.
- `get_price_history`/`get_multiple_price_history`/`get_latest_price`/`clamp_start_for_interval`/
  `resample_ohlcv` 등 외부 시그니처는 전부 그대로 유지해 10여 곳의 호출부(backtest_engine/screener/
  valuation/strategy_engine/portfolio/threads_summary/차트 조회 페이지) 수정이 전혀 필요 없었다.
  내부 헬퍼만 교체(`_cache_key` 삭제 → `_store_path`/`_load_store`/`_save_store`/`_download`/
  `_merge_price_data`/`_full_history_marker` 신규).
- yfinance가 분봉/시간봉에서 간헐적으로 tz-aware 인덱스를 반환하는 것을 저장 전 tz-naive로
  통일(`_download` 내부) — 안 그러면 저장된 범위와 요청 범위를 비교하는 Timestamp 연산이 깨질 수
  있었음. `end`는 yfinance 관례대로 배타적(해당 날짜 미포함)으로 취급해 슬라이싱에도 동일 적용.
- `clear_cache()`는 `*.parquet`/`*.full`만 삭제하도록 범위를 좁혀, 같은 `data/cache/` 디렉터리를
  공유하는 다른 모듈(fred_data.py의 `fred_*.csv`, screener.py의 `sp500_universe.csv`/
  `fundamentals_*.json`, guru_tracker.py의 `issuer_ticker_cache.json`, etf_holdings.py의
  `spdr_holdings_*.xlsx`)을 건드리지 않게 함(기존 `"*.csv"` 전체 삭제는 fred 캐시까지 지울 수 있는
  잠재 위험이 있었는데, 포맷이 바뀌며 자연히 해소됨).
- 구 CSV 캐시 파일(`data/cache/{티커}_{날짜}_{날짜}_{interval}.csv`, 총 5MB)은 새 코드가 더 이상
  읽지 않지만 자동 삭제는 하지 않았다 — 다른 모듈 캐시와 같은 디렉터리에 섞여 있어 일괄삭제 스크립트
  대신 필요시 사용자가 수동으로 정리하도록 남겨둠.
- 검증: `tests/test_market_data.py`에 신규 테스트 4개 추가(저장 경로 생성, 같은 범위 재조회 시
  캐시 히트, 캐시가 TTL을 넘겨 오래됐어도 완전히 과거로 국한된 요청은 네트워크 안 탐, 저장 범위를
  벗어난 요청은 저장된 마지막 날짜부터 델타만 받아옴, 앞쪽 부족분만 백필). 전체 pytest 218개 통과.
  실제 yfinance로 라이브 스모크 확인(MSFT): 1차 조회 0.35초(신규 다운로드, 103행) → 겹치는 좁은
  범위 2차 조회 0.016초(완전 로컬 응답, 약 20배 빠름) → 범위를 넓힌 3차 조회는 저장된 마지막 날짜부터
  델타만 받아와 144행으로 확장. pandas `Timedelta(days=1)`가 유발하는 NumPy Deprecation 경고는
  `Timedelta(1, unit="D")`로 교체해 예방.

**모듈 A 확장: 다종목 미세튜닝 + 종목 스타일 매칭 엔진 신규 구현** (2026-07-14). 사용자가 "유튜브
전략 채널이 소개하는 전략을 S&P500 100종목에 백테스팅하고, 원본 전략을 미세튜닝하면서, 종목이
성장주/주도주 등 어떤 스타일인지 스스로 판별해 스타일에 맞는 전략을 찾는 엔진을 만들고 싶다"고 요청.
코드 작성 전 충분히 상의(요청대로 `STRATEGY_TUNING_ENGINE_SPEC.md`에 논의 과정을 정리하며 진행) →
설계 확정 후 "우선 진행해봐"로 구현 착수. **새 모듈이 아니라 기존 백테스팅 슬롯(모듈 A)의 신규
탭으로 통합**(사용자가 명시적으로 요청한 방향 — "뜯어고치는 게 아니라 기존 기능에 추가").
- **핵심 설계 원칙(백본 유지)**: 원본(유튜버) 전략의 지표 구성/조건 로직 구조는 절대 바꾸지 않고,
  수치 파라미터만 종목 스타일에 맞는 방향으로 탐색 범위를 다르게 잡아 grid/random search로
  미세튜닝한다. 강화학습은 쓰지 않음(사용자 확정). 사용자가 "완성되면 평생 쓰면서 6개월마다
  재튜닝할 것"이라고 밝혀, 매 실행을 새 DB 배치 레코드로 영구 저장하는 반영구 이력 시스템으로 설계
  (덮어쓰지 않음 — 반기 재실행 자체가 자연스러운 walk-forward 검증 효과를 냄).
- **신규 DB 모델** (`core/models.py`): `StrategyTuningRun`(배치 1건 — 원본전략id/원본config/종목
  표본/train_ratio/intensity/기간), `StrategyTuningResult`(배치 내 종목별 결과 — 스타일 유형/점수/
  튜닝된 config/train 지표/test 구간 3-way 비교 지표/초과수익/health_warnings). 둘 다 신규 테이블이라
  기존 `data/quant.db`에 수동 ALTER TABLE 불필요.
- **신규 core 모듈** (`core/strategy_tuning.py`):
  - `sample_universe(n=100)`: S&P500을 11개 GICS 섹터별로 균등 배분(섹터당 시가총액 상위)해 표본
    추출 — 시총 상위로만 뽑으면 빅테크 편중되어 섹터별 스타일 비교가 무의미해지는 문제를 피함.
  - `compute_style_scores()`: **종목 스타일 6개 카테고리**(주도주/성장주/가치주/경기민감주/
    경기방어주/퀄리티 컴파운더)를 기존 데이터만으로 정량화 — 주도주=최근 6개월 상대강도 백분위,
    성장주=이익성장률(없으면 PER로 대체), 가치주=저PER/PBR 백분위, 경기민감·방어주=GICS 섹터를
    `core/macro_cycle.py::SECTOR_ROTATION`(기존 매크로 대시보드 국면별 섹터 표, 모듈 G와 연동
    확정)에 매핑해 태깅, 퀄리티 컴파운더=장기 MDD 작음+200일선 위 체류 비율. 카테고리는 상호
    배타적이지 않을 수 있어 6개 점수를 모두 계산 후 최고점을 주 유형으로 태깅.
  - `build_param_grid()`: 원본 config 트리를 순회(`entry_stages`/`exit_stages`/`emergency_exit`/
    `conditions` 전부 지원, 1:2:6 단계별·레짐 스키마 공용)해 이평 기간류/임계값류 숫자 파라미터만
    스타일별 배수 범위(예: 주도주는 0.3~0.8배로 짧게, 경기방어주는 1.0~2.0배로 길게)로 변형한 후보를
    생성. 조합 수가 예산(빠름20/보통60/정밀150)을 넘으면 고정 시드 랜덤 샘플링(재현 가능). expression
    (직접 수식) 전략은 튜닝 파라미터를 식별할 수 없어 원본만 반환(한계로 인지, 향후 확장 여지).
  - `tune_strategy_for_ticker()`: 기간을 75%(train)/25%(test)로 시계열 분리, train에서 후보별 샤프
    지수를 비교해 최적 파라미터를 찾되 매매 5회 미만이거나 `diagnose_strategy_health`(기존 모듈 A
    안전장치 재사용)가 진입=청산 자기모순을 감지한 후보는 제외. 유효 후보가 하나도 없으면 원본으로
    폴백해 항상 결과를 낸다. 최종 채택 파라미터는 test 구간(out-of-sample)에서
    `compare_with_benchmarks()`(기존 3-way 비교 함수 그대로 재사용)로 검증.
  - `run_batch_tuning()`: 종목 하나가 실패해도 배치 전체는 계속 진행(에러는 `error` 필드로 개별 기록).
  - `save_tuning_run()`/`list_tuning_runs()`/`get_tuning_run()`: 배치 결과 영구 저장/조회.
- **UI** (`app/pages/1_백테스팅.py`에 "🧬 다종목 미세튜닝" 탭 추가): 백본 전략을 라이브러리에서
  선택하거나 새 텍스트를 붙여넣어 AI 해석(기존 `interpret_strategy_text` 재사용) → 표본 종목 수/
  탐색 강도/Train 비율/기간 설정 → `job_manager` 백그라운드 실행(기존 패턴 재사용, 종목 수·탐색
  강도에 따라 수 분 소요 가능) → 결과 테이블(초과수익 기본 정렬, 다른 지표로 재정렬·상위 N개 표시
  가능) → `st.dataframe(..., on_select="rerun", selection_mode="multi-row")`로 직접 종목 선택(선택
  없으면 상위 3종목) → 선택 종목의 3-way 비교 차트(test 구간/전체 기간 토글) → 전략 라이브러리 저장.
  과거 튜닝 실행 이력을 expander로 조회해 재열람 가능.
  - **버그 발견/수정**: 라이브 브라우저 검증 중 "백본 전략" 선택 목록을 만드는 코드가
    `with get_session() as session:` 블록 **밖에서** ORM 객체(`s.name`/`s.id`)에 접근해
    `sqlalchemy.orm.exc.DetachedInstanceError`가 실제로 발생함을 확인 → 딕셔너리 컴프리헨션을
    `with` 블록 안으로 이동(기존 "지표 조합 백테스트" 탭의 동일 패턴과 일치시킴)해 수정.
- **테스트용 대표 전략**: 사용자 요청으로 "볼린저 밴드 하단 반전 1:2:6 전략"(하단 이탈 10% →
  상승 인걸 캔들 +20% → RSI 30 상향 돌파 +60% 분할 진입, 상단 도달 → RSI 70 상향 돌파 → RSI 50
  하향 이탈(잔량 전부) 분할 청산, 상단 돌파+RSI 과매수 동시 발생 시 긴급청산)을 설계해 진입/청산
  조건이 방향상 겹치지 않도록(자기모순 버그 없도록) 구성 — `tests/test_strategy_tuning.py`와 라이브
  검증 양쪽에서 사용.
- 검증: `tests/test_strategy_tuning.py` 신규 20개(섹터 균등 표본 추출, 6개 스타일 점수·씨클리컬/
  방어 섹터 태깅·모멘텀 랭킹, 볼린저 1:2:6·레짐 스키마 양쪽에서 파라미터 그리드가 구조를 보존하며
  스타일 방향대로 변형되는지, 예산 초과 시 재현 가능한 랜덤 샘플링, train/test 분리, 최적 후보 선택/
  거래횟수 미달·자기모순 후보 배제/원본 폴백, 배치 부분 실패 처리, DB 저장/조회 왕복) 전부 통과.
  실제 Gemini/yfinance 없이 격리된 임시 SQLite로 `run_and_save_tuning` 전체 파이프라인을 AAPL/XOM/
  NEE 실데이터로 라이브 실행해 스타일 판별·튜닝·3-way 비교까지 정상 동작 확인(과최적화 방지 설계상
  이 기간엔 강세장 S&P500 대비 초과수익이 음수로 나오는 것도 확인 — 정상적인 결과, 버그 아님).
  Playwright로 실제 브라우저 조작까지 완료: 탭 진입 → 라이브러리에서 볼린저 1:2:6 전략 선택(위
  DetachedInstanceError를 이 과정에서 실제로 잡아냄) → 과거 실행 이력에서 결과 로드 → 결과 테이블
  (섹터/유형/초과수익/샤프/MDD/경고 컬럼, 행 선택 체크박스) 렌더링 → 3-way 비교 차트(TradingView
  다크 테마 재사용) 렌더링 → "전략 라이브러리에 저장" 버튼까지 전부 실제 클릭으로 확인. 전체 pytest
  241개 통과 / 1개 실패(`test_job_manager.py::test_cancel_stops_running_job_and_clears_sidebar`) —
  이 1개는 동시 진행 중이던 다른 세션이 작업 중인 job_manager 강제종료 기능 테스트로, 본 세션은
  `core/job_manager.py`/`tests/test_job_manager.py`를 전혀 건드리지 않았는데도 실패하는 것으로
  확인해(git diff로 해당 파일들이 이 세션 밖에서 수정 중임을 확인) 별개 세션의 진행 중 작업임을
  검증함 — 본 세션 범위 아니라 그대로 둠.
- **알려진 한계(향후 확장 과제로 명시)**: expression(직접 수식) 전략은 파라미터 자동 탐색 미지원
  (원본 그대로만 실행). 매크로 국면 필터를 "지금이 확장기이니 씨클리컬 종목 진입 비중을 높인다"처럼
  실시간으로 탐색 로직에 결합하는 것은 이번 범위에 넣지 않음(섹터 기반 정적 태깅까지만 구현) —
  `FRED_API_KEY` 미설정 상태와도 무관하게 항상 동작하도록 설계된 것이라 지금 당장 막힌 것은 아님.
  회차 간(예: 2026-07 1차 vs 2027-01 2차) 파라미터 변화를 나란히 비교하는 화면은 이력이 2회 이상
  쌓인 뒤 필요성을 보고 추가하기로 함(과설계 방지, `STRATEGY_TUNING_ENGINE_SPEC.md` 6절에 기록).

**사이드바 백그라운드 작업 목록에 강제 종료 버튼 추가** (2026-07-14, 같은 날 후속 요청). 사용자가
"백그라운드 작업 리스트는 잘 나오는데 각각을 강제종료할 수 있게 해달라"고 요청 → `core/job_manager.py`:
- `Job`에 `future`(스레드 풀 제출 결과)/`thread_ident`(실행 중인 스레드 id) 필드 추가, `_run()`
  시작 시 자기 스레드의 ident를 기록.
- `cancel(job_id)` 신규: 레지스트리(`_jobs`)에서 즉시 pop(아직 스레드 풀 큐에서 대기 중이었다면
  `future.cancel()`로 충분), 이미 실행 중이었다면 `ctypes.PyThreadState_SetAsyncExc`로 해당 스레드에
  종료 예외(`_JobCancelledError`, BaseException 상속이라 작업 함수의 `except Exception`을 그대로
  통과)를 주입해 강제 종료를 시도한다. 이 방식은 CPython 비공식 API라 스레드가 소켓 등 블로킹 C
  콜(네트워크 조회) 안에 있으면 그 콜이 끝날 때까지는 실제로 안 멈추는 베스트 에포트지만, 레지스트리
  에서는 즉시 제거되므로 사이드바 목록/각 페이지의 `render()`에서는 바로 "작업 없음"으로 보인다
  (기존에 `start()`가 이미 문서화한 "추적을 잃은 이전 작업은 스스로 끝나면 조용히 정리된다" 패턴과
  일관됨 — 스레드가 뒤늦게 끝나도 이미 pop된 job_id라 아무 부작용 없음).
- `render_active_jobs_sidebar()`: 각 작업 캡션 옆에 "🛑 강제 종료" 버튼 추가, 클릭 시 `cancel()` 후
  `st.rerun()`. 작업이 하나도 없어도 `with st.sidebar:` 블록에는 항상 진입하도록 변경(이전엔
  `if not jobs: return`으로 블록 진입 자체를 건너뛰었음 — 방금 종료된 마지막 작업 항목이 화면에서
  안 지워질 가능성을 없애기 위한 방어적 변경).
- 검증: `tests/test_job_manager.py`에 신규 테스트 3개 추가 — 대기열에서 시작 전 취소, 존재하지 않는
  job_id 취소 시 False, 사이드바 버튼 클릭이 실제로 `cancel()`을 호출해 레지스트리를 비우는지
  (무한루프 작업으로 실행 중 취소까지 재현). Streamlit `AppTest`가 "새 run에서 그려지지 않은 요소"의
  화면 잔류를 실제 브라우저처럼 재현하지 않는다는 한계를 확인해(간단한 재현으로 검증) 그 부분은
  단언하지 않고 레지스트리 상태만으로 검증. 전체 pytest 241개 통과.

**다종목 미세튜닝: 종목을 직접 스크롤하며 골라 담는 수동 선택 모드 추가** (2026-07-14, 같은 날
후속 요청). 사용자가 "휠을 넘기면 티커들이 계속 나오고 내가 담는 구조"를 요청 → 어디에 넣을지/
자동 표본과 어떻게 공존할지 확인 질문 2개 후 진행(다종목 미세튜닝 탭에 "모드 전환" 방식으로 추가).
- `app/pages/1_백테스팅.py`의 "🧬 다종목 미세튜닝" 탭에 "종목 표본 방식" 라디오(🎲 자동 섹터 균등
  표본 / 🧺 직접 선택) 추가. 직접 선택 모드에서는 `core.screener.get_universe()` 전체 목록(섹터→
  티커 정렬)을 `st.dataframe(..., on_select="rerun", selection_mode="multi-row", height=420)`로
  렌더링 — 고정 높이 컨테이너라 별도 무한스크롤 구현 없이 Streamlit 데이터그리드 자체의 내장
  스크롤(마우스 휠)로 "스크롤하면 더 많은 티커가 보인다"를 그대로 충족. 체크박스로 선택한 행이
  담은 티커 목록이 되며(선택 상태는 위젯 `key`로 자동 영속 — 별도 session_state 누적 로직 불필요,
  스크롤은 리런을 유발하지 않아 선택 중간에 화면이 끊기지 않음), 캡션에 "🧺 담은 종목 N개: ..."로
  실시간 표시.
- `core/strategy_tuning.py::run_and_save_tuning()`에 `tickers_df` 선택적 인자 추가 — 주어지면
  `sample_universe()` 자동 표본추출을 완전히 건너뛰고 그대로 사용(직접 선택 모드), 없으면 기존처럼
  자동 표본(자동 모드). 실행 버튼은 직접 선택 모드에서 담은 종목이 0개면 경고 후 막는다.
- 검증: `tests/test_strategy_tuning.py`에 2개 추가(`tickers_df` 제공 시 `sample_universe()`가 호출
  자체를 안 하는지 — 호출되면 즉시 실패하도록 만든 가짜 함수로 확인, 미제공 시 기존처럼 자동
  표본추출로 폴백하는지). Playwright로 실제 브라우저 검증: `st.dataframe`의 행 선택 체크박스가
  Streamlit `data-testid="stDataFrame"`이 아니라 캔버스 기반 `data-testid="data-grid-canvas"`로
  렌더링됨을 먼저 확인한 뒤(추측 대신 DOM 조사) 그 좌표로 실제 체크박스 클릭 → 2종목(GOOGL/AMZN)
  선택 → 캔버스 내부 마우스 휠로 스크롤하니 다음 섹터 종목(BRK.B/JPM/V/JNJ/UNH/AAPL/MSFT/NVDA)이
  나타나는 것을 확인 → `body` 텍스트에서 "🧺 담은 종목 2개: GOOGL, AMZN" 캡션이 스크롤 후에도 그대로
  유지됨을 직접 확인(선택 상태가 스크롤과 무관하게 보존됨을 실증). 이 샌드박스 환경은 Wikipedia
  접근이 막혀 있어 `get_universe()`가 20종목짜리 `_FALLBACK_UNIVERSE`로 대체되는 상태로 검증했음
  (실제 사용자 환경은 인터넷이 되므로 전체 S&P500 약 500종목이 뜬다) — 목록 크기와 무관하게 동작하는
  로직이라 결과에 영향 없음. 전체 pytest 243개 통과.

**(동시 세션 작업) expression(직접 수식) 전략 미세튜닝 지원 + 정의 순서 버그 수정** (2026-07-14,
같은 날). 이 세션이 티커 담기 기능을 검증하는 동안, `core/strategy_tuning.py`/`core/models.py`를
다른 동시 세션이 실시간으로 확장하는 것을 발견함(파일 크기가 체크할 때마다 늘어남, 커밋 전 상태를
공유하는 이 프로젝트의 기존 관례 — PROGRESS.md 여러 항목에 이미 기록된 패턴). 내용은 이전까지 "한계"로
남겨뒀던 expression 전략 튜닝 미지원을 해소하는 것: `identify_tunable_numbers()`가 Gemini로 수식 안의
숫자 리터럴이 튜닝 가능한 파라미터인지 판별(숫자 값 자체는 `ast`로 결정론적으로 추출해 Gemini가 값을
잘못 베낄 위험 원천 차단) → `_build_expression_param_grid()`로 기존 grid search와 동일한 예산/재현
가능한 랜덤 샘플링을 적용 → 그래도 test 구간에서 종목 매수보유+S&P500을 둘 다 못 이기면 그때만
`generate_structural_variants()`로 Gemini에게 구조가 다른 대안 수식을 1회성으로 최대 3개 제안받아
채택(반복 진화 없음, "백본 유지" 원칙은 이 escape hatch에서만 예외로 허용 — 사용자 확정). `StrategyTuningResult`에
`backbone_changed`(bool) 컬럼 추가.
- **이 세션에서 발견/수정한 버그 2건** (기능 자체는 건드리지 않고 버그만 수정, "반영은 하되 되돌리지
  않는다" 원칙): ① `tune_expression_strategy_for_ticker()`가 함수 기본 인자값으로
  `_DEFAULT_TRAIN_RATIO`를 참조하는데, 그 상수 정의가 원래 위치(파일 뒷부분 "4. train/test 분리"
  절)에 그대로 있어 새로 삽입된 함수보다 늦게 정의됨 → 모듈 임포트 자체가 `NameError`로 실패하는
  상태였음. 상수 정의를 새 함수들보다 앞으로 옮겨 해결(값 자체는 그대로, 정의 위치만 이동). ②
  `identify_tunable_numbers()`/`generate_structural_variants()` 관련 테스트 3개가 실패하고 있었는데,
  동시 세션이 디버그 print를 넣어 자체적으로 원인을 찾아 고치는 것을 재확인(이 세션은 원인 규명에는
  관여하지 않고 진행 상황만 모니터링) — 최종적으로 디버그 print까지 정리된 상태로 마무리됨.
- 검증: 두 세션의 변경사항을 합쳐 `python -m pytest tests/ -q` 전체 258개 통과, `core.strategy_tuning`
  모듈 임포트/`app/pages/1_백테스팅.py` 컴파일·`AppTest` 무예외 로드까지 재확인.

**(위 작업의 원 세션) 문서화 + UI 반영 + 실제 Gemini 라이브 검증 마무리** (2026-07-14, 같은 날). 위
expression 튜닝 기능을 실제로 설계·구현한 세션 본인 기준 마무리 기록 — 요청 배경: 사용자가 3/5절에서
이미 확정한 "백본 유지·RL 없음" 원칙과 충돌하는 요청("직접 수식 전략도 Gemini로 튜닝하고, training
시 매수보유를 아웃퍼폼하도록 백본을 바꿔달라")을 해서, 코드 전에 AskUserQuestion으로 적용 범위부터
확인(직접 수식 전략에만 적용 vs 전체 엔진 — "직접 수식에만"으로 확정, JSON 전략의 백본 유지 원칙은
안 건드림). 나머지(반복진화 vs 1회성, 실패 시 폴백 방식)는 위임받아 결정하고 근거를 남김
(`STRATEGY_TUNING_ENGINE_SPEC.md` 9절에 상세 기록).
- **문서화**: `STRATEGY_TUNING_ENGINE_SPEC.md`에 9절 신설 — 이 예외가 JSON 전략에는 전혀 영향 없음을
  명시하고, 2단계 구조(숫자 식별→튜닝, 그래도 못 이기면 구조 변경)와 설계 판단 근거(1회성 vs 반복진화,
  폴백 방식)를 기록.
- **UI** (`app/pages/1_백테스팅.py`): 다종목 미세튜닝 결과 표에 "백본변경"(🧬 예/-) 컬럼 추가, 탭
  상단 설명에 "직접 수식 전략만 예외로 구조 변경이 가능하다"는 문구 추가. `AppTest`로 기존 저장된
  실행 이력(run id=1, JSON 전략)을 로드해 새 컬럼이 전부 "-"로 정상 렌더링됨을 실제 DB 데이터로 확인.
- **실제 Gemini API 라이브 검증** (mock 유닛테스트와 별개로, 이 프로젝트 관례대로 실제 호출까지 확인):
  - `identify_tunable_numbers("close > sma(close, 20) and rsi(close, 14) < 30")` → 20을 "이동평균
    기간"(범위 5~200), 14를 "RSI 계산 기간"(7~28), 30을 "RSI 과매도 임계값"(10~50)으로 정확히 역할
    판별.
  - `generate_structural_variants(..., "가치주")` → 실행 가능한 대안 2개 생성(`sma+bollinger` 조합,
    `macd_hist+rsi` 조합) — 둘 다 원본과 다른 지표 구성이면서 `validate_syntax()` 통과.
  - `tune_expression_strategy_for_ticker`를 AAPL(2021~2026, 강세장이라 매수보유 CAGR 13~16%로 높음)에
    실제 실행(23초 소요) → 숫자 튜닝만으로는 못 이겨 구조 변경까지 갔고(`backbone_changed=True`,
    MACD 크로스 조합으로 교체), 그럼에도 여전히 종목/S&P500 매수보유를 못 이겼음
    (`outperformed_ticker_bh=False`, `outperformed_benchmark_bh=False`) — 이걸 숨기지 않고 정직하게
    반환하는 것까지 실제로 확인(설계 의도대로 "과최적화로 억지로 이긴 것처럼 안 보이게 하기" 안전장치가
    실전에서 작동함을 검증).
- `data/quant.db`의 `strategy_tuning_results` 테이블에 이미 10행이 있어(직전 세션 실행분) `core/models.py`에
  `backbone_changed` 컬럼 추가 후 수동 `ALTER TABLE ... ADD COLUMN backbone_changed BOOLEAN NOT NULL
  DEFAULT 0` 마이그레이션 실행(기존 데이터 보존, PROGRESS.md에 반복 기록된 기존 컨벤션과 동일).

**전략 저장 시 상세 자연어 설명을 수식과 함께 페어로 저장 (2026-07-15)**. 사용자가 "백테스팅할 때
수식뿐 아니라 자연어로 전략을 상세히 설명해달라, 매번 생성하지 말고 전략 생성 시 페어로 생성/저장해서
설명 페어가 없을 때만 생성해달라"고 요청. 확인해보니 전략 저장 지점 4곳(①지표 토글/직접 수식 저장,
②자연어 전략 등록 저장, ③다종목 미세튜닝 결과 저장 2곳) 중 ②만 저장 시점에 진짜 설명을 만들고
있었고(`core/nl_strategy.py`가 해석과 동시에 생성), 나머지는 보일러플레이트 문구나 튜닝 메타데이터만
`description`에 넣고 있었음 — 이를 4곳 모두 일관되게 고쳤다.
- `core/strategy_explainer.py` 신규: `explain_strategy(indicator_config)` — 레짐(AND/OR)/1:2:6
  단계별 전략은 `core.strategy_engine.describe_condition()`을 재사용해 결정론적으로 정확한 조건
  요약을 먼저 만들고(환각 방지용 근거), 이를 Gemini에게 주고 자연스러운 한국어 설명 문단으로 다듬게
  한다(`gemini_client.LIGHT_TASK_MODELS`). 직접 수식(expression) 전략은 결정론적 요약이 불가능해
  수식 자체를 Gemini에게 설명시킨다. GEMINI_API_KEY 미설정/API 실패 시 레짐·단계별은 결정론적 요약
  그대로, 수식은 원본 수식을 담은 안내 문구로 폴백(오프라인에서도 항상 동작).
- **"매번 생성 안 함"의 구현 방식**: 페이지 스크립트 자체가 아니라 각 "💾 저장" 버튼의 `if
  st.button(...)` 블록 안에서만 `explain_strategy()`를 호출하도록 배치 — Streamlit은 위젯 조작마다
  전체 스크립트를 다시 실행하지만 버튼 클릭 직후 1회 실행에서만 그 블록의 본문이 돌기 때문에, 자연히
  "전략을 실제로 저장할 때 1번만" 호출된다(🚀 백테스트 실행을 여러 번 눌러 반복 미리보기를 해도 호출
  안 됨). 생성된 설명은 `Strategy.description` 컬럼에 함께 저장되고, 이후 그 전략을 불러오거나
  반복 백테스트해도 DB에 저장된 값을 그대로 재사용할 뿐 다시 생성하지 않는다(그래서 "설명 페어가
  없을 때만 생성"이 자동으로 성립).
- `app/pages/1_백테스팅.py`: 지표토글/직접수식 저장·자연어 전략 저장·미세튜닝 단일종목 저장·미세튜닝
  다종목표 저장 4곳 모두 `explain_strategy()` 사용(미세튜닝 2곳은 튜닝 메타데이터를 뒤에 덧붙임). "불러오기"로
  기존 전략을 로드하면 저장된 설명을 상단에 표시. 저장 직후에도 `st.info`로 바로 보여줌.
- **(같은 날 사용자 추가 피드백)** "자연어로 생성할 때 gemini api 를 써서 해. 그저 유튜브 스크립트를
  뱉지 말고" — 자연어 전략 등록 탭이 `nl_result["description"]` + 원문 스크립트를 그대로 이어붙이던
  것을 `explain_strategy(nl_result["indicator_config"])`로 교체(다른 3곳과 동일한 방식으로 통일).
  원문 스크립트는 설명 뒤에 "[원문 스크립트]" 절로 참고용으로만 남긴다.
- `app/pages/9_전략_관리.py`: 기존에 저장된(이 기능 이전) 전략은 보일러플레이트 설명이 그대로 남아있어,
  "🤖 AI로 설명 재생성" 버튼을 추가해 사용자가 명시적으로 원할 때만 수동으로 다시 생성할 수 있게 함
  (자동 백필은 하지 않음 — 자동 재생성은 요청받지 않았고 조용히 API를 반복 호출하게 될 위험이 있어
  과설계로 판단해 배제).
- 검증: `tests/test_strategy_explainer.py` 신규 10개(결정론적 요약 정확성, API 키 없음/호출 실패 시
  폴백, Gemini 응답 사용, 빈 응답 처리, JSON 문자열 입력). 전체 `pytest` 268개 통과. `AppTest`로
  두 페이지 모두 무예외 로드 확인. 실제 GEMINI_API_KEY가 설정되어 있어(`.env`) 라이브 검증도 진행:
  자연어 탭에서 "골든크로스+RSI" 스크립트를 실제 해석→저장까지 실행해 저장된 `description`이 원문
  덤프가 아닌 눌림목 전략 설명 문단인 것을 DB에서 직접 확인(테스트용 행은 이후 삭제), 전략 관리
  페이지의 "재생성" 버튼도 기존 저장 전략(#3, 볼린저+장악형+RSI 1:2:6 전략)에 실제로 클릭해 정확하고
  상세한 설명이 생성되는 것을 확인.

**다종목 미세튜닝 방식 변경: 종목별 독립 탐색 → 스타일 그룹 풀링 트레이닝 (2026-07-15)**. 사용자가
"경기방어주, 주도주 등으로 데이터셋을 나눠서 그룹 안에서만 트레이닝하고, 어떻게 해서든 S&P500/개별
종목 매수보유를 이기게 개선해달라"고 요청 → 후자("어떻게 해서든")가 기존 확정 원칙(train/test 분리로
과최적화 방지)과 충돌할 소지가 있어 코드 전에 `AskUserQuestion` 2개로 확인:
- "test 구간에서도 못 이기면?" → **"탐색은 최대한 넓히되 정직하게"**(권장) 채택. test 성과를 선택
  기준에 반영해 강제로 이기게 만드는 방식(데이터 스누핑, 백테스트 상 승률은 오르지만 실제 미래 성과와
  무관해짐)은 채택 안 함.
- "구조 변경 escape hatch(기존엔 직접 수식 전략에만 있었음)를 레짐/1:2:6까지 확장할지" → **"전체
  전략 유형으로 확장"**(권장) 채택.

`core/strategy_tuning.py`:
- `run_batch_tuning()`이 종목을 style_type(6개 카테고리)으로 먼저 그룹핑하고, 그룹당
  `tune_strategy_for_group()`을 1번만 호출(기존엔 종목마다 `tune_strategy_for_ticker()` 반복 호출).
  같은 그룹 종목들은 결과적으로 `tuned_config`가 동일해짐.
- `tune_strategy_for_group()` 신규: train 구간에서는 그룹 전체 종목의 평균 샤프지수를 목적함수로
  숫자 파라미터를 탐색하고(그룹의 최소 50% 이상 종목에서 유효해야 후보로 인정 — 한 종목에만 맞는
  과최적화 방지), test 구간은 종목별로 개별 평가만 하고 선택에는 절대 반영하지 않는다(정직성 유지).
  그룹 평균이 test에서 S&P500을 못 이기면 그때만 구조 변경 escape hatch를 1회성으로 시도.
- `generate_structural_variants_for_config()` 신규: 직접 수식은 기존 `generate_structural_variants()`
  재사용, 레짐/1:2:6은 `core/nl_strategy.py`의 기존 스키마(`INDICATOR_CONFIG_SCHEMA`/
  `STAGED_INDICATOR_CONFIG_SCHEMA`)를 재사용한 JSON 생성으로 확장(새 스키마 중복 정의 없음).
- 종목 단위 escape hatch 진입점이었던 `tune_expression_strategy_for_ticker()`는 그룹 함수에 역할이
  흡수되어 제거. `tune_strategy_for_ticker()` 등 기존 빌딩 블록은 "🔬 알고리즘 자동 생성" 탭이 여전히
  그대로 사용하므로 유지.
- `app/pages/1_백테스팅.py`: "다종목 미세튜닝" 탭 설명을 그룹 풀링 방식으로 갱신, 결과 표 위에
  "스타일 그룹별 요약"(종목수/평균초과수익/승률/백본변경) 추가 — 기존 종목별 결과에서 즉석 집계라
  DB 스키마 변경 없이 과거 실행 이력에도 그대로 적용됨.
- 설계 배경 상세는 `STRATEGY_TUNING_ENGINE_SPEC.md` 10절 참고.
- 검증: `tests/test_strategy_tuning.py`에 그룹 풀링 신규 테스트 다수 추가(그룹 커버리지/평균 계산,
  그룹 전체 config 공유, test 구간이 선택에 영향 안 주는지, escape hatch 트리거/미채택 조건, 그룹
  하나 실패해도 나머지 진행 등). 기존 `tune_expression_strategy_for_ticker`/구 `run_batch_tuning`
  디스패치 테스트 5개는 제거된 함수/바뀐 동작에 맞춰 재작성. 전체 `pytest` 310개 통과. 실제 Gemini
  API + 실제 가격 데이터(AAPL/MSFT/JNJ)로 전체 파이프라인 라이브 실행해 스타일 분류→그룹 풀링
  튜닝→저장까지 정상 동작 확인(검증용 실행 결과는 이후 삭제). `AppTest`로 이 변경 이전에 저장된
  실행 이력을 불러와도 그룹 요약 표가 예외 없이 렌더링됨을 확인(과거 데이터 호환).

**볼린저 밴드 응용 매매법 4종(스퀴즈/추세추종/추세반전/다이버전스) + 진입가 기준 손절 신규 구축
(2026-07-15)**. 사용자가 유튜브 "볼린저 밴드 최고의 매매전략 4가지" 대본을 그대로 붙여넣으며 전부
구현 요청 → 대화로 확인 질문 2개("어느 전략부터/전부?" → 전부, "진입가 기준 손절을 이번에 엔진에
추가할지" → 추가) 후 `BOLLINGER_STRATEGIES_SPEC.md`로 설계를 먼저 정리하고 진행:
- **핵심 발견**: 엔진이 완전 무상태(그날 지표값만 보고 매일 판정)라 "진입 시점 가격 기준" 손절
  개념이 아예 없었음(`entry_price` 등 grep으로 확인). 4개 전략 전부 이 형태의 손절을 정의해 이번에
  일반 메커니즘으로 구축(스퀴즈 1개에만 쓰이는 게 아니라 향후 다른 전략에도 재사용 가능하게 설계).
  또한 4개 전략 모두 진입≠청산 조건이라 레짐(`logic`/`conditions`) 스키마로 표현이 안 돼(그 스키마는
  하나의 불리언이 켜졌다/꺼졌다만 판정), 기존 1:2:6 staged 스키마(`entry_stages`/`exit_stages`)를
  1단계짜리(weight=1.0)로 활용 — 새 top-level 스키마는 만들지 않음.
- `core/indicators.py` 신규 함수 8개: `compute_bbw`(밴드폭)/`compute_percent_b`(%B)/`compute_mfi`
  (자금흐름지수, `ta.volume.MFIIndicator`)/`compute_bbw_squeeze_release`(스퀴즈 해제 이벤트 —
  threshold 상향돌파 + 최근 lookback봉 내 스퀴즈였는지 확인 + hold_bars만큼 유지)/`compute_lowest_low`
  `compute_highest_high`(손절 레벨 소스)/`compute_double_pattern`(쌍바닥·쌍봉, 스윙 저점·고점을
  좌우 pivot_lookback봉 중심윈도우로 확정한 뒤 밴드 위치 제약+거래량 급증 확인 돌파까지 판정)/
  `compute_rsi_divergence`(가격-RSI 다이버전스, 스윙 저점·고점에서 가격vsRSI 방향 반대 확인 후
  중심선 돌파 확인). 후자 둘은 순수 벡터화가 어려워(직전 스윙과 비교하는 순차 상태) 판다스 계산 후
  파이썬 루프로 스캔(`simulate_staged_positions`와 동일한 기존 스타일).
- `core/strategy_engine.py`: `INDICATOR_EVALUATORS`에 `bbw_squeeze_release`/`percent_b`/`mfi`/
  `double_pattern`/`rsi_divergence` 5개 등록 + `describe_condition` 문구 추가. `bollinger`에
  `band="mid"`(중심선 돌파) 지원 추가(기존 upper/lower와 동일한 방식). **`stop_loss` 신규 메커니즘**:
  `simulate_staged_positions()`가 최상위 선택적 `"stop_loss": {"source": "bollinger_mid"|"lowest_low"|
  "highest_high", "period": ...}` 키를 받으면, 포지션이 없다가 새로 진입하는 바("사이클 시작")에서
  그 source의 그 순간 가격 레벨을 스냅샷해 고정하고, 사이클이 끝날 때까지 종가가 그 아래로 내려오면
  emergency_exit과 같은 우선순위로 즉시 전량 청산(`StageEvent(kind="stop_loss")`로 로그). 레벨-소스는
  불리언을 반환하는 기존 `INDICATOR_EVALUATORS`와 반환 타입이 달라 별도 `STOP_LOSS_SOURCES` 레지스트리로
  분리.
- `core/expression_engine.py`: "수식" 전략용으로 `bbw`/`percent_b`/`mfi` 3개 함수 추가(쌍바닥/다이버전스는
  `engulfing`과 같은 이유로 수식 함수로 노출하지 않음 — 여러 봉에 걸친 상태형 패턴이라 한 줄 수식의
  성격과 안 맞음).
- `core/nl_strategy.py`: `STAGE_CONDITION_PROPERTIES`에 새 지표 5개 + 관련 파라미터(threshold/lookback/
  hold_bars/band_period/band_std/pivot_lookback/pattern_window/volume_mult/rsi_period) 추가, `band` enum에
  "mid" 추가, `STAGED_INDICATOR_CONFIG_SCHEMA`에 `stop_loss`(emergency_exit과 마찬가지로 선택 항목)
  추가. `STAGED_SYSTEM_PROMPT`에 5개 지표 설명 + stop_loss 작성 기준 문단 추가. **겸사겸사 버그 수정**:
  이전 세션에 사용자가 붙여넣은 실제 staged_config에서 bollinger/ma_cross 조건에 일목균형표 전용
  필드(kijun_len 등)가 무관하게 섞여 들어간 것을 발견했었는데(엔진은 무시하지만 `strategy_tuning.py`의
  `_PERIOD_LIKE_KEYS`가 키 이름만 보고 이걸 숫자 파라미터로 오인해 튜닝 예산을 낭비함) — 프롬프트에
  "그 지표에 정의되지 않은 필드는 채우지 말 것" 문구를 추가해 재발 방지(스키마 자체는 Gemini
  구조화출력 제약상 그대로 둠). `_STAGED_HINT_KEYWORDS`에도 "스퀴즈"/"밴드폭"/"밴드 너비"/"퍼센트비"/
  "%b"/"다이버전스"/"쌍바닥"/"쌍봉"을 추가 — 안 하면 이 4개 전략 텍스트가 (진입=청산 조건인 줄 알고)
  레짐 스키마로 잘못 라우팅되어 애초에 표현이 불가능해짐.
- **스코프에서 의도적으로 제외한 것**(추측으로 만들지 않음, `BOLLINGER_STRATEGIES_SPEC.md` 5절에
  명시): 매도(숏) 포지션(엔진 전체가 롱온리), 다이버전스의 "손익비 2:1 도달 시 분할매도"(staged
  엔진은 청산 단계별로 전체 물량만 정리하는 이분법 구조), 추세추종의 "예비신호→확정신호 2회 확인"
  (선택 강화 옵션으로 문서화만), 쌍바닥/쌍봉 전략의 손절/익절(원문에 언급 없어 추측 추가 안 함).
- **알려진 제약**: `core/strategy_tuning.py`의 `_PERIOD_LIKE_KEYS`/`_THRESHOLD_LIKE_KEYS`가 아직
  `threshold`/`band_period`/`band_std`/`pivot_lookback`/`pattern_window`/`volume_mult`/`rsi_period`를
  인식하지 못해, 다종목 미세튜닝 엔진이 이 4개 전략의 새 파라미터를 자동으로는 못 쓸어본다(백테스트
  자체는 정상 동작, "튜닝 자동화"만 아직 안 걸림). 이 세션 중 다른 세션이 `core/strategy_tuning.py`를
  동시에(그룹 풀링 방식으로) 크게 고치고 있어 충돌을 피하려 이 파일은 건드리지 않음 — 다음 세션에서
  안전할 때 반영할 것.
- 검증: `core/market_data.py::get_price_history`로 받은 실제 AAPL 데이터로 8개 신규 지표 전부 계산 후
  값 범위/이벤트 발생 여부 확인, 4개 전략 전부 `simulate_staged_positions`로 실제 진입/청산/stop_loss
  이벤트가 나오는 것과 `extract_staged_trades`로 트레이드까지 정상 추출되는 것 확인. `tests/
  test_strategy_engine.py`(신규 16개: 지표 계산 8개 + 조건평가기 5개 + stop_loss 2개 + 대조군 1개),
  `tests/test_expression_engine.py`(신규 1개), `tests/test_nl_strategy.py`(신규 2개, 키워드 라우팅
  + 스키마 반영 확인) 추가 — 전부 합성 OHLCV(네트워크 불필요), 쌍바닥/쌍봉/다이버전스는 실제 함수를
  먼저 실행해보며 정확히 이벤트가 뜨는 합성 시나리오를 확인한 뒤 테스트에 고정. 관련 파일(`test_strategy_
  engine.py`/`test_expression_engine.py`/`test_backtest_engine.py`/`test_nl_strategy.py`) 65개 전체
  통과. 전체 `pytest tests/` 실행 시 `test_strategy_tuning.py` 일부가 실패하는데, 이는 위에서 언급한
  다른 세션의 동시 편집(그룹 풀링 리팩터링 진행 중) 때문이며 이 세션이 만든 변경과는 무관함을
  `git stash`로 격리 확인.

**섹터별 대표 ETF·대장주·성장주 관계 분석 페이지 추가** (2026-07-15). 사용자가 "각 섹터마다 대표하는
ETF, 대장주, 성장주들의 관계를 정량적으로 분석할 수 있는 페이지를 따로 만들어줘"라고 요청 →
`SECTOR_LEADER_GROWTH_RELATIONSHIP_SPEC.md`에 리서치 근거(상대강도/베타/상관계수는 업계 표준 조합)를
먼저 정리하고, AskUserQuestion 3개(대장주/성장주 정의 방식, 성장주 개수, 포함 지표)로 확인받은 뒤
구현(전부 "권장" 옵션 선택 — 완전 자동 산출/3개/베타+상관계수+RS추세).
- `core/sector_leaders.py`(신규): 대표 ETF는 기존 `core.sector_strength.THEME_UNIVERSE`를 그대로
  재사용. GICS 11개 섹터는 `screener.get_universe()`에서 섹터별 종목 중 시가총액 1위=대장주,
  이익성장률(없으면 PER) 배치 내 백분위 상위 3개=성장주로 완전 자동 산출. 반도체/메모리·DRAM/우주
  등 GICS에 없는 니치 테마는 `NICHE_THEME_CANDIDATES` 프리셋 후보 목록(THEME_UNIVERSE의 ETF 프록시
  프리셋과 같은 성격) 안에서 동일한 방식으로 선정. `compute_relationship_metrics()`가 종목별로
  베타(ETF 수익률에 대한 회�귀 민감도)/상관계수/상대강도(RS, 종목가÷ETF가) 비율 추세(최근 20거래일
  ±1% 이상 변화만 상승/하락으로 판정, 그 이하는 횡보)를 계산.
- `core/sector_strength.py`: `_theme_price_history` → `theme_price_history`로 공개 API 승격(동작
  변경 없음, 새 모듈이 대표 ETF 시계열 재사용을 위해 필요) — 유일한 호출부도 함께 갱신.
- `app/pages/12_섹터_리더_성장주.py`(신규): 테마 선택 셀렉트박스 + `job_manager` 백그라운드 패턴
  (섹터당 최대 수십 종목 펀더멘털 조회라 무거운 작업) + 대장주 카드(`st.metric` 4개) + 성장주 3개
  비교 표 + 정규화(시작일=100) 성과 비교 라인차트(ETF 점선 + 대장주 굵은선 + 성장주 3개, dataviz
  스킬의 다크모드 검증 카테고리 팔레트에서 5색 사용, 기존 캔들 상승/하락색과 안 겹치게 선택).
- **버그 발견 및 수정 (교훈)**: 라이브 검증 중 베타/상관계수가 비현실적으로 낮게(예: MSFT vs XLK
  베타 0.02) 나오는 것을 발견 → 원인은 이 세션 도중 다른 세션이 `core/market_data.py`/
  `core/sector_strength.py`에 동시에 추가한 "`get_price_history(start=None)`이 캐시 없는 티커에
  yfinance 기본 기간(짧음)만 받아오는" 버그의 여파 — ETF 프록시 캐시가 `.full` 마커와 함께 41일치로
  고정 캐싱된 뒤라, `sector_leaders.py`가 명시적 `start`를 넘겨도 `.full` 마커가 있으면
  `market_data.py`의 `need_older` 로직이 과거 데이터 재조회를 영구히 건너뛰는 것까지 확인함(같은
  시각을 공유하는 캐시 계층 버그). `core/sector_leaders.py`도 동일한 함정에 걸리므로
  `core.sector_strength.DEFAULT_LOOKBACK_DAYS` 상수를 재사용해 `get_price_history(ticker,
  start=...)`를 항상 명시적으로 호출하도록 방어 코드 추가(그 세션이 만든 `.full` 캐시 자체는
  `core/market_data.py`가 계속 활발히 편집되던 파일이라 직접 고치지 않고, 손상된 캐시 파일 삭제는
  자동 모드 안전장치에 의해 차단되어 사용자 확인 필요 — 다행히 검증 도중 다른 세션이 같은 캐시를
  스스로 정리해 최종적으로는 정상(약 2년치) 데이터로 확인 완료).
- **환경 제약(내 코드 결함 아님)**: 이 샌드박스에서 `en.wikipedia.org` 접근이 막혀 있어
  `core.screener.get_universe()`가 매번 19종목짜리 최소 대체 목록(`_FALLBACK_UNIVERSE`)으로 폴백함
  — GICS 섹터당 후보가 2~3개로 보임(예: "기술" → AAPL/MSFT/NVDA뿐). 사용자의 실제 실행 환경에서는
  위키피디아 접근이 가능해 S&P500 전체(~500종목)가 정상적으로 잡힐 것으로 예상.
- **알려진 러프엣지**: 우주 테마 검증 중 ASTS(AST SpaceMobile)처럼 극단적으로 급등한 소형 성장주가
  포함되면 정규화 차트의 y축이 그 종목 하나에 맞춰 늘어나(0~5000대) 나머지 선이 바닥에 눌려 보이는
  현상을 실측으로 확인. 베타/상관계수/RS 표의 숫자는 영향받지 않으나(계산은 개별 종목-ETF 페어로
  이뤄짐), 차트만 놓고 보면 가독성이 떨어질 수 있음 — 이번 스코프에서는 손대지 않고 다음에 필요하면
  로그축/이상치 클리핑 등을 사용자와 논의 후 반영.
- 검증: `tests/test_sector_leaders.py`(신규 12개 — 후보 종목 선정, 대장주/성장주 자동 산출(시총 1위
  제외 후 성장점수 랭킹, earnings_growth 결측 시 PER 대체), 베타/상관계수(결정론적 선형관계로
  구성한 합성 수익률로 정확히 1.0/2.0이 나오는지), 데이터 부족/겹침 없음 처리, 오케스트레이션까지)
  전부 통과. Playwright로 임시 포트(8502)에 별도 인스턴스를 띄워 실제 브라우저로 라이브 검증 —
  "기술"(GICS, 실제 NVDA 대장주 + MSFT/AAPL 성장주, 베타 1.07/상관계수 0.73)과 "우주"(니치 프리셋,
  실제 RTX 대장주 + ASTS/RKLB/BA 성장주)로 후보 선정/카드/표/차트가 실데이터로 전부 정상 렌더링됨을
  확인, 테마 전환(셀렉트박스)도 실제 클릭으로 확인. 기존 8501(사용자 세션)은 건드리지 않음. 전체
  `python -m pytest tests/ -q` 실행 결과는 다른 세션들의 동시 작업(전략 튜닝 그룹 풀링, 시장국면/
  섹터강도, 볼린저 4대 매매법)과 겹쳐 일부 무관한 실패가 섞여 있으나, `test_sector_leaders.py`/
  `test_sector_strength.py`(신규 로직 관련 전체)는 격리 확인 시 전부 통과.

**모듈 G 확장: 시장 국면(강세/약세) + 섹터/테마 강도 지표 추가 (2026-07-15)**. 사용자가 "S&P500 등으로
전체 시장이 강세장/약세장인지, DRAM/반도체/우주섹터 등 섹터별 힘을 정량적으로 보여달라"고 요청하며
구현 전 인터넷 리서치(최소 5분)를 먼저 하라고 명시 → 새 모듈이 아니라 **기존 매크로 대시보드(모듈 G)
안의 새 탭**으로 판단해 진행(신규 대형 기능이라 코드 전에 리서치 근거 + 설계 결정을
`MARKET_REGIME_SECTOR_STRENGTH_SPEC.md`에 먼저 정리하고, AskUserQuestion으로 UI 위치/판단 방식/섹터
정의 방식/테마 확장 방식 4가지 개념적 결정을 확인한 뒤 착수 — 전부 추천안으로 확정됨).
- **리서치 요약**: 시장 국면은 200일선 대비 위치·50/200일 골든·데드크로스·시장폭(%)·52주 고점대비
  낙폭을 조합한 룰 기반 복합지표(HMM 등 ML은 배제, 기존 `macro_cycle.py`와 같은 투명한 경험칙 스타일
  유지)가 업계에서 가장 널리 쓰임. 섹터 강도는 IBD RS Rating 공식(`0.4·ROC63+0.2·ROC126+0.2·ROC189
  +0.2·ROC252`)과 Julius de Kempenaer의 RRG(추세+모멘텀 2축) 개념을 참고. DRAM/반도체/우주처럼 GICS
  11개 표준 섹터에 없는 세부 테마는 실제 대응 ETF(반도체=SOXX/SMH, 메모리=Roundhill Memory ETF
  `DRAM`, 우주=UFO/ARKX/ROKT)를 프록시로 사용. 상세 출처는 스펙 문서 2절 참고.
- `core/market_regime.py`(신규): `score_trend_position`/`score_ma_cross`/`score_drawdown`/
  `score_breadth` 4개 신호를 각각 ±25점(낙폭은 -25~0)으로 점수화해 합산(-100~+75) →
  `classify_regime()`이 ≥35 강세장/≤-35 약세장/그 사이 중립·혼조로 분류. `compute_market_breadth()`는
  `core.screener.get_universe()`의 S&P500 전종목이 200일선 위인지 비율로 계산(다수 티커 조회라
  `job_manager` 백그라운드 실행).
- `core/sector_strength.py`(신규): `THEME_UNIVERSE` 딕셔너리(11개 GICS 섹터 SPDR ETF + 반도체/
  메모리·DRAM/우주 14개 테마, 코드 프리셋 — 확장 시 항목만 추가). `compute_theme_strength()`가 IBD
  방식 가중 ROC로 테마별 강도를 계산해 테마 집합 내 percentile(0~100 RS 점수)로 반환, 최근 20거래일
  전후 비교로 상승/하락/횡보 추세도 함께 표시. `core/indicators.py`에 `roc()` 헬퍼 신규 추가.
- `app/pages/7_매크로_대시보드.py`에 3번째 탭 "📈 시장 국면 / 섹터 강도" 추가 — 상단은 국면 배지
  (🐂/🐻/😐) + 4개 하위 신호 `st.metric`, 하단은 RS 점수 내림차순 수평 막대차트(50점 기준 그린/레드
  다이버징, dataviz 스킬 가이드로 색상 검증) + 수익률/추세 표.
- **실제 운영 중 발견해 함께 고친 버그 3건** (내가 만든 신규 코드의 버그, 라이브 브라우저 검증 중
  yfinance 실제 호출로 드러남 — 유닛테스트는 전부 monkeypatch라 못 잡았음):
  1. `core.market_data.get_price_history(start=None)`가 문서와 달리, 로컬 캐시가 전혀 없는 티커는
     yfinance 기본기간("1mo")만 받아와 200/252일 계산에 필요한 이력이 부족해짐(S&P500 개별종목/
     `^GSPC`는 과거 세션들이 이미 몇 년치 캐싱해둬서 우연히 안 걸림, 반도체/DRAM/우주 등 이 앱에서
     처음 조회하는 테마 ETF만 걸림). 공용 `market_data.py`는 건드리지 않고, 내 두 모듈에서
     `start`를 명시적으로(오늘로부터 800일 전) 넘기도록 우회. 이미 잘못 캐싱된(`.full` 마커가 찍힌
     불완전 캐시) 17개 테마 ETF는 `clear_cache()`로 삭제 후 재조회.
  2. Roundhill Memory ETF(`DRAM`)는 2025년 상장이라 252거래일치 이력이 아직 없어 전량 계산 불가 →
     `_strength_factor()`가 4개 ROC 구간 중 확보된 이력만 골라 가중치를 재정규화하도록 수정(사용자가
     명시적으로 요청한 "dram 주"라 조용히 빠뜨리지 않고 짧은 이력으로라도 점수를 매기도록 함).
  3. `compute_theme_strength(theme_universe={})`가 `or` 연산자 탓에 빈 딕셔너리(falsy)를 "안 넘김"
     으로 오인해 전체 프리셋으로 폴백하는 버그 발견(`is None` 체크로 수정) — 이 버그 때문에 관련
     유닛테스트가 몰래 실제 네트워크를 타고 있었다는 것도 함께 발견해 monkeypatch로 격리.
- 검증: `tests/test_market_regime.py`(신규 15개) + `tests/test_sector_strength.py`(신규 9개, 위 버그
  2/3 회귀 테스트 포함) 전부 통과, 전체 `pytest tests/` 327개 통과. Playwright로 실제 브라우저 실행 —
  탭 클릭 → 백그라운드 계산 진행 표시 → 완료 후 강세장 배지(종합 +74점, 200일선 위 +8.2%/골든크로스/
  시장폭 74%) + 14개 테마 RS 점수 차트(메모리/DRAM 1위 100점, 반도체 2위 93점)와 표까지 실제 yfinance
  데이터로 렌더링 확인.
- 새 문서: `MARKET_REGIME_SECTOR_STRENGTH_SPEC.md`(리서치 근거 + 설계 결정 기록).

**볼린저 응용 매매법 4종 신규 파라미터를 다종목 미세튜닝 엔진이 인식하도록 반영 (2026-07-15, 이어서)**.
위 "볼린저 밴드 응용 매매법 4종" 항목에서 `core/strategy_tuning.py`가 다른 세션의 그룹 풀링 리팩터링과
동시 편집 충돌을 피하려 의도적으로 건드리지 않은 채 남겨둔 부분(`_PERIOD_LIKE_KEYS`/`_THRESHOLD_LIKE_
KEYS`가 신규 지표 파라미터 9개를 인식 못 함) — 그룹 풀링 작업이 병합되고 전체 테스트가 깨끗이 통과하는
것을 확인한 뒤 이어서 반영.
- `_PERIOD_LIKE_KEYS`에 롤링 윈도우 봉 수 6개 추가: `lookback`/`hold_bars`/`band_period`/
  `pivot_lookback`/`pattern_window`/`rsi_period` (기존 `short`/`long`/`period`와 동일하게 스타일
  배수로 스케일 — 주도주는 짧게, 방어주는 길게).
- `std_dev` 분기를 `band_std`도 함께 매칭하도록 확장(`elif key in {"std_dev", "band_std"}:`) — 둘 다
  볼린저 밴드 폭의 표준편차 배수로 의미가 동일해 기존 ±0.5 바운디드 지터 로직을 그대로 재사용.
  `period`는 이미 기존 `_PERIOD_LIKE_KEYS`에 있어 손대지 않음(`percent_b`/`mfi`/`compute_lowest_low`/
  `compute_highest_high`가 공유).
- `threshold`(bbw_squeeze_release의 밴드폭 스퀴즈 기준, 기본 0.1)와 `volume_mult`(double_pattern의
  거래량 배수, 기본 1.5)는 기존 `_THRESHOLD_LIKE_KEYS`(RSI 0~100 스케일 전용, delta=10.0/0.1 고정폭)에
  넣으면 volume_mult=1.5가 delta=10.0을 맞아 [0, 11.5] 같은 무의미한 범위가 나와 새 `_RATIO_LIKE_KEYS`
  집합으로 분리하고, 원래 값에 비례하는 지터(`delta = max(round(val*0.3, 3), 0.02)`, 하한 0.01로 항상
  양수 유지)를 쓰는 별도 분기를 추가.
- `stop_loss`는 `entry_stages`/`exit_stages`와 같은 층위의 최상위 딕셔너리라 `_iter_condition_paths()`가
  애초에 순회하지 않으므로(조건 리스트 내부가 아님) 이번 스코프에서 손대지 않음(의도적 제외, 추측 아님).
  기존 인식 키(`short`/`long`/`period`/`fast`/`slow`/`signal`/`tenkan_len`/`kijun_len`/`span_b_len`/
  `displacement`/`std_dev`/`value`/`level`) 동작은 순수 추가만 했으므로 전혀 변경 없음.
- 검증: `tests/test_strategy_tuning.py`에 신규 2개 추가 — bbw_squeeze_release/rsi_divergence/
  double_pattern 3개 지표를 섞은 staged config로 신규 파라미터 9개가 전부 여러 값으로 흔들리면서도
  지표 종류/방향 등 백본은 그대로 유지되는지, threshold/volume_mult/band_std가 항상 양수인지 확인하는
  테스트 1개, 신규 `_PERIOD_LIKE_KEYS` 키(`rsi_period`)도 기존 `short`/`long`과 동일한 스타일
  방향성(주도주=짧게, 경기방어주=길게)을 따르는지 확인하는 테스트 1개. 전체 `python -m pytest tests/ -q`
  실행 결과 329개 전부 통과(기존 327개 + 신규 2개, 회귀 없음).

**섹터 리더/성장주 페이지 후속 확장: 성장주 재정의(초대형주 제외) + 테마 세분화 + 대형주→소형주
레깅 후보 플래그 (2026-07-15, 같은 날 후속 요청)**. 사용자가 "기술주를 DRAM/방산/냉각 등으로 더
세분화, 애플·MS 같은 초대형주가 성장주로 잡히는 문제 지적, 대형주 추세추종→소형주 상관관계를
인터넷 리서치 후 페이지에 반영"을 요청. AskUserQuestion으로 3가지 방향(성장주 재정의 방식/테마 분리
방식/대형주→소형주 신호 형태) 확인 후 진행 — 설계 근거·결정은 `SECTOR_LEADER_GROWTH_RELATIONSHIP_
SPEC.md` 6절 참고.

- **성장주 재정의**: `core/sector_leaders.py::compute_leader_and_growth`에 `MEGA_CAP_EXCLUDE_
  QUANTILE = 0.75` 추가 — 대장주 한 종목만 빼던 것을, 후보군 내 시가총액 상위 25% 전체를 성장주
  후보에서 제외하도록 변경(러셀 지수 재조정에서도 초대형주는 성장/가치 경계가 흐려진다는 리서치
  근거). 실제 확인: "기술" 테마가 예전엔 성장주로 애플($4.6T)/마이크로소프트($2.9T)를 그대로
  뽑았는데, 수정 후엔 진짜 중형 반도체주(MCHP/COHR/LITE, 시총 $47~63B)로 바뀜.
- **테마 세분화**: `core/sector_strength.THEME_UNIVERSE` + `core/sector_leaders.NICHE_THEME_
  CANDIDATES`에 5개 신규 테마 추가(14→19개) — 방산(ETF `ITA`, 대형 프라임+중소형 방산기술주),
  냉각(ETF `DTCR`, VRT/MOD/AAON/NVT), 사이버보안(ETF `CIBR`), 클라우드(ETF `SKYY`+`WCLD`),
  로보틱스(ETF `BOTZ`). 기존 "우주" 테마에 섞여 있던 대형 방산 프라임(LMT/RTX/NOC/GD/LHX)을
  방산으로 옮기고, 우주는 순수 우주기업(ASTS/RKLB)+소형주(LUNR/RDW)만 남김.
  - **실증 검증 중 상장폐지 종목 2개 발견해 교체**: CyberArk(CYBR, 2026-02-11 Palo Alto Networks에
    피인수돼 나스닥 상장폐지 → QLYS로 교체), iRobot(IRBT, 2025-12 챕터11 파산 후 Picea에 피인수돼
    상장폐지 → SYM으로 교체). 둘 다 yfinance가 404를 던지는 걸 먼저 보고 뉴스 검색으로 원인 확인.
- **대형주 추세추종 → 소형주 레깅 후보 플래그**: Lo-MacKinlay(1990)/Hou(2007) 리드-래그 연구(같은
  산업 내 대형주 수익률이 정보확산 지연으로 소형주 수익률을 선행) 근거로 신규 2개 함수 추가.
  `_abs_trend_label()`은 기존 `core.market_regime.score_trend_position`/`score_ma_cross`를 그대로
  재사용해 대장주 자체의 절대 가격 추세(200일선 위/아래 + 50/200일 골든·데드크로스)를 "상승"/
  "하락"/"혼조"로 라벨링(기존 `trend` 필드는 ETF 대비 RS비율 추세라 별개 개념). `_is_lag_candidate()`
  는 대장주가 "상승"추세이고 성장주의 베타/상관계수가 각각 0.5 이상인데 RS추세가 아직 "상승"이
  아니면 True — `analyze_theme_relationships()`가 각 성장주에 `lag_candidate` 필드로 추가.
  실제 데이터로 "우주"(RKLB 상승 + ASTS/LUNR/RDW 3개 전부 레깅 후보), "반도체"(NVDA 상승 + 성장주
  3개 전부 레깅 후보) 등 의도대로 발동함을 확인.
- **UI**(`app/pages/12_섹터_리더_성장주.py`): 대장주 카드에 "추세추종 신호" 메트릭 추가, 성장주
  표에 시가총액 컬럼 + "🐢 추격 후보" 컬럼 추가. 하나라도 있으면 리드-래그 연구 근거 + "거래비용
  반영 시 초과수익은 빠르게 사라진다"는 한계 + "투자 조언이 아닌 관찰 지표" 안내 문구를 `st.info`로
  표시(과신 방지, 기존 골든/데드크로스 캡션과 같은 패턴).
- **검증 중 발견해 함께 고친 무관한 환경 버그**: `core/screener.py`의 위키피디아 S&P500 스크레이핑이
  `pd.read_html()`에 필요한 `lxml` 패키지가 `requirements.txt`에 없어 조용히 실패하고(예외가
  `except Exception`에 삼켜짐) 10여 종목짜리 소규모 폴백 유니버스로 계속 대체되고 있었다 — 이번
  세션 이전부터 있던 문제로("산업재" 테마가 항상 후보 0개였던 원인도 동일), 스크리너/밸류에이션/
  시장국면 등 GICS 유니버스를 쓰는 다른 기능에도 영향을 미치는 범위가 넓은 버그다. `requirements.txt`
  에 `lxml>=5.0` 추가로 해결, 이후 로컬 캐시를 지우고 재조회해 503종목 전체가 정상 로드됨을 확인(11개
  GICS 섹터 전부 정상 종목 수 반환, "산업재" 81개 포함).
- 검증: `tests/test_sector_leaders.py`(신규 6개: 신규 테마 후보 존재, 초대형주 다중 제외, abs_trend
  상승/N-A, 레깅 후보 True/False 분기) + `tests/test_sector_strength.py`(THEME_UNIVERSE 19개 항목
  검증 갱신). 실제 yfinance 데이터로 19개 테마 전부 `analyze_theme_relationships()` 실행해 확인,
  Streamlit `AppTest`로 "기술" 테마 페이지 렌더링(메트릭/표/안내문구 실제 값) 확인, 매크로 대시보드의
  `compute_theme_strength()`도 19개 테마 전부 정상 RS 점수 반환 확인(시장국면 탭 자체는 이제
  503종목 전체를 도는 시장폭 계산이라 콜드 캐시에서 느린 것이 정상 — job_manager 백그라운드 패턴으로
  이미 설계된 부분). `python -m pytest tests/ -q` 전체 336개 통과.

**파라미터 업데이트 체계화 — 다중 구간 워크포워드 + 안정성 점수 + 튜닝 리포트 추가 완료
(2026-07-15, 이어서)**. 사용자가 "튜닝을 했는데도 왜 계속 시장을 못 이기는지 이해가 안 된다"고
질문 → 이 엔진이 이미 train/test를 정직하게 분리해 test 성과만 보고하고 있어서(overfitting
적발 장치가 정상 작동 중) 나타나는 현상임을 설명. "더 체계적으로" 해달라는 요청에 여러 옵션(다중
구간 워크포워드/평평한 영역 선호/다중검정 보정/백본 재검토)을 논의 후 앞의 두 개를 조합해 제안,
AAPL 실제 데이터로 프로토타입 데모를 먼저 돌려 결과를 함께 확인(자세한 배경/데모 결과는
`STRATEGY_TUNING_ENGINE_SPEC.md` 11절 참고 — 다중 폴드에서 "훨씬 안정적"으로 나온 후보가 실제
홀드아웃에서는 원본보다 나빴던 사례를 정직하게 기록해둠, 방법론의 한계를 숨기지 않음). "문서
정리 → 구현" 순서로 진행하기로 확정.
- `core/strategy_tuning.py`: `_select_best_group_config`(단일 train 구간 평가)를 제거하고
  `_split_into_folds()` + `_candidate_group_walkforward_score()` + `_select_best_group_config_
  walkforward()`로 교체 — train 구간을 3개 폴드로 나눠 폴드별 그룹 평균 샤프지수의 "평균 −
  표준편차×0.5"를 점수로 후보를 선택한다(특정 시기에만 우연히 맞는, 폴드 간 변동성이 큰 후보에
  패널티). test(out-of-sample) 구간은 여전히 선택에 전혀 관여하지 않고 최종 검증 전용(4b절 원칙
  불변). `tune_strategy_for_group()` 반환값에 `tuning_trail`(후보별 폴드 점수 트레일, 점수
  내림차순 — "어떤 파라미터를 왜 채택했는지" 근거) 추가.
- `core/models.py`: `StrategyTuningResult`에 `tuning_trail`(Text, JSON) 컬럼 추가. 기존
  `data/quant.db`에 이미 행이 있어(9절 `backbone_changed` 추가 때와 동일한 상황) 수동
  `ALTER TABLE`로 마이그레이션. `save_tuning_run`/`get_tuning_run`이 이 필드를 왕복 저장/조회.
- `app/pages/1_백테스팅.py`: "🧬 다종목 미세튜닝" 탭의 그룹별 요약 표 아래에 "🧪 튜닝 리포트"
  expander 신규 추가 — 스타일 그룹별 후보 파라미터(결정론적 한국어 요약, 신규 헬퍼
  `_describe_candidate_compact()`가 `core.strategy_explainer`의 `describe_regime_config`/
  `describe_staged_config`를 재사용 — 트레일에 후보가 최대 수십 개라 Gemini 호출 없이 결정론적으로
  요약)/폴드별 샤프/평균/표준편차/점수를 표로 표시, 채택된 후보에 ✅ 표시.
- 검증: `tests/test_strategy_tuning.py`에 신규 6개 추가(폴드 분할 무결성, 폴드 간 변동성 패널티,
  최소 폴드 커버리지 미달 시 탈락, 후보 선택/트레일 정렬, 기존 그룹 테스트에 tuning_trail 검증
  추가, DB 왕복). 전체 `pytest tests/` 351개 통과(회귀 없음). 실제 라이브 Gemini API + AAPL/MSFT
  실제 가격 데이터로 `tune_strategy_for_group`을 2회 실행해 결정론적 경로(폴드 분할/점수 계산)와
  Gemini 의존 경로(구조 변경 escape hatch — 매 호출마다 다른 제안, 기존 9/10절의 "1회성 제안"
  설계가 원래 가진 비결정성이지 이번 변경의 버그 아님) 양쪽 다 확인. Streamlit `AppTest`로 튜닝
  리포트 expander가 실제 실행 결과(볼린저/MA+캔들 구조 변경 포함)를 예외 없이 렌더링하는지 확인
  (검증용 실행 기록은 확인 후 DB에서 삭제). 자세한 설계 배경/데모 근거는
  `STRATEGY_TUNING_ENGINE_SPEC.md` 11절 참고.

**시장 국면/섹터 강도 계산을 병렬화 + 매일 한국시간 00:00 스케줄러 사전계산으로 전환 (2026-07-15,
같은 날 후속 요청)**. 바로 위 항목에서 `lxml` 버그가 고쳐져 시장 국면 탭이 진짜 S&P500 503종목
전체를 순회하게 되면서(이전엔 폴백 19종목이라 우연히 안 느렸음), 사용자가 이 탭을 열었을 때 "⏳ 시장
국면 계산 — N초 경과"가 계속 올라가는 걸 보고 "이것도 한번에 다 진행하고 한국 시간 00시 00분에
업데이트 하는 방식으로 하자"고 요청. 같은 시점에 다른 세션이 `core/sector_leaders.py`/
`core/sector_strength.py`(THEME_UNIVERSE 19개 확장)/`requirements.txt`(lxml)를 활발히 편집 중이라(이
세션이 위 항목을 쓰는 동안 실시간으로 확인함) 파일 충돌을 피하려 겹치는 파일은 건드리지 않고 진행:

- **병렬화**: `core/market_data.py::get_multiple_price_history()`가 티커를 순차 for문 대신
  `ThreadPoolExecutor(max_workers=10)`로 동시 조회하도록 변경(네트워크 I/O 위주라 병렬화 효과가 큼 —
  `core.job_manager`가 백그라운드 작업에 스레드풀을 쓰는 것과 같은 이유). 각 티커는 `(ticker,
  interval)`별 독립 캐시 파일에 쓰기 때문에 스레드 간 쓰기 경합이 없어 안전. 개별 티커 실패 시 해당
  티커만 빈 DataFrame으로 격리되는 기존 계약은 그대로 유지(`tests/test_market_data.py`에 회귀
  테스트로 고정).
- **매일 00:00(Asia/Seoul) 사전계산**: `scheduler/run_scheduler.py`에 `market_snapshot_job()` 신규
  등록(`CronTrigger(hour=0, minute=0, timezone="Asia/Seoul")`) — `core.market_regime.
  get_market_regime_snapshot()`과 `core.sector_strength.compute_theme_strength()`를 매일 한 번만
  미리 계산해 DB에 저장한다. **이 스케줄러 스크립트가 실제로 프로세스로 계속 떠 있어야 매일 00:00에
  실행된다는 점을 스크립트 상단 docstring에 명시** — Streamlit 앱만 켜져 있는 것으로는 자동 갱신되지
  않는다(1인 로컬 앱 전제라 사용자가 `python scheduler/run_scheduler.py`를 별도로 띄워둬야 함).
- **DB**: `core/models.py`에 `MarketRegimeSnapshot`/`SectorStrengthSnapshot` 신규 테이블 추가(둘 다
  새 테이블이라 기존 `data/quant.db`에 수동 마이그레이션 불필요 — `init_db()`의 `create_all()`만으로
  충분, 실제로 로컬 DB에 생성까지 확인함). `core/market_regime.py`/`core/sector_strength.py`에 각각
  `save_*_snapshot()`/`get_latest_*_snapshot()` 추가 — `ThreadsWeeklyReport`와 동일하게 덮어쓰지
  않고 매번 새 행으로 쌓아 나중에 국면 변화 추이도 볼 수 있게 함(최신 조회는 `computed_at`이 아니라
  `id.desc()` 기준 — 같은 트랜잭션 안에서 연달아 저장하면 `datetime.utcnow()` 해상도상 동시각이 될
  수 있어 insert 순서가 보장되는 PK로 정렬).
- **UI** (`app/pages/7_매크로_대시보드.py`): 시장 국면/섹터 강도 두 섹션 모두 "저장된 최신 스냅샷이
  있으면 그걸 즉시 표시 + 마지막 갱신 시각 캡션 + '🔄 지금 다시 계산' 버튼"으로 바뀜. 스냅샷이
  하나도 없을 때만(스케줄러를 아직 한 번도 안 돌렸을 때) 기존처럼 `job_manager.ensure()`로 자동
  즉석 계산하도록 폴백 — 기능이 갑자기 끊기지 않음. "지금 다시 계산" 버튼은 `job_manager.start()`로
  강제 새 작업을 만들고(기존 `ensure()`의 "params_key 같으면 재사용" 로직을 우회), 계산이 끝나면
  결과를 DB에도 저장해 다음 조회부터 반영되게 함.
- **다른 세션과의 조율**: 요청 자체가 "다른 에이전트한테도 얘기했으니 조율하라"였으나 이 환경에는
  세션 간 직접 통신 채널이 없어(둘 다 같은 로컬 저장소를 공유하는 별도 프로세스), 실질적인 조율은
  ①현재 git diff/파일 mtime을 먼저 확인해 그 세션이 만지고 있는 파일(`core/sector_leaders.py`,
  `core/sector_strength.py`의 `THEME_UNIVERSE`, `requirements.txt`)은 전혀 건드리지 않고, ②새 로직은
  `core/sector_strength.py` 끝에 함수만 추가(기존 함수/상수는 한 글자도 안 바꿈), ③이 항목을 남겨
  그 세션이 나중에 같은 파일을 다시 열어봐도 무엇이 왜 바뀌었는지 알 수 있게 하는 방식으로 진행함.
  `core/models.py`도 같은 시간대에 다른 세션이 `StrategyTuningResult`에 컬럼을 추가하고 있어(이번
  세션 시작 시점 git diff로 확인), 충돌 없이 파일 맨 끝에 새 클래스 2개만 추가함.
- 검증: `tests/test_market_regime.py`/`tests/test_sector_strength.py`에 스냅샷 저장/조회 라운드트립
  테스트(빈 상태/정상 저장·조회/최신순 정렬) 신규 7개, `tests/test_market_data.py`에 병렬 조회 결과
  정확성/개별 티커 실패 격리/빈 리스트 처리 3개 추가. 실제 로컬 `data/quant.db`에 `init_db()`를
  실행해 새 테이블 2개가 정상 생성되는 것과, 저장된 스냅샷이 아직 없어 페이지가 기존처럼 즉석 계산
  경로로 정상 폴백함을 직접 확인. `apscheduler.triggers.cron.CronTrigger(timezone="Asia/Seoul")`가
  예외 없이 파싱되는 것도 확인. `python -m pytest tests/ -q` 전체 351개 통과.
- **사용자에게 안내할 점**: (1) 매일 00:00 자동 갱신이 실제로 동작하려면 `scheduler/run_scheduler.py`
  를 백그라운드 프로세스로 계속 띄워둬야 한다(예: `nohup python scheduler/run_scheduler.py &` 또는
  systemd 서비스). (2) 지금 실행 중인 Streamlit 프로세스는 이 세션이 `core/market_regime.py`/
  `core/sector_strength.py`/`core/market_data.py`에 새 import(`core.db.get_session`,
  `core.models`)를 추가하기 전에 이미 떠 있던 프로세스라, 예전에 겪었던 "오래된 프로세스가 파일
  추가 전 상태를 캐싱" 문제(이 문서 2026-07-12 항목 참고)를 피하려면 재시작을 권장한다(다만 지금
  진행 중이던 최초 시장 국면 계산은 그대로 두고 사용자 판단에 맡김 — 임의로 프로세스를 죽이지 않음).

**백본 구조 한계 대응 — 결정론적 국면 스위치 변형 추가 완료 (2026-07-15, 이어서)**. 위 워크포워드
튜닝 작업 직후, 사용자가 "백본 구조 한계 논의로 넘어가자"고 요청 → 11절 데모/9절 AAPL 사례에서
공통으로 확인된 원인을 세 가지로 진단(AND 결합이 신호를 희소하게 만듦/청산이 대칭적으로 너무
이름/국면 무감각 — 앞의 둘은 셋째의 파생 증상)하고, "국면(시장 전체가 아니라 종목 자체 추세)에
따라 진입 로직 자체를 스위치"하는 방향으로 논의 후 확정. 조사 결과 `core/expression_engine.py`에
이미 `sma`/`highest`가 있어 새 지표 없이 "(A and B) or (C and D)" 형태의 국면 스위치를 한 줄
수식으로 표현 가능함을 확인 — 단 이 중첩 논리는 직접 수식(expression) 스키마에서만 가능하고
레짐/1:2:6(JSON)은 flat AND/OR라 표현 불가해, 9절과 같은 이유로 **직접 수식 전략에만** 적용하기로
확정(자세한 배경/설계는 `STRATEGY_TUNING_ENGINE_SPEC.md` 12절 참고).
- `core/strategy_tuning.py`: `_build_regime_switch_variant(expression, trend_ma_period=200,
  breakout_lookback=60)` 신규 — Gemini 창의성에 안 맡기고 고정 템플릿으로 결정론적 생성("종가가
  200일선 위 + 60일 신고가 돌파"면 추세추종 진입, 아니면 원본 진입 조건 그대로), `validate_syntax()`
  통과 못 하면 None. 새 트리거/새 흐름을 만들지 않고 기존 구조변경 escape hatch(`generate_
  structural_variants_for_config`의 expression 분기)에 Gemini 제안 옆에 후보 하나로 추가 —
  생성된 수식의 숫자(200/60 포함)는 기존 `_build_expression_param_grid`가 원본 진입 조건의 숫자와
  함께 그대로 스타일별로 튜닝하므로 별도 튜닝 경로 불필요.
- 검증: `tests/test_strategy_tuning.py`에 신규 3개 추가(원본 진입 조건 보존 확인, 커스텀 기간
  파라미터 반영, 결합 실패 시 None 폴백) + 기존 디스패치 테스트 갱신(새 변형이 추가돼 리스트 길이가
  늘어난 것 반영). 전체 `pytest tests/` 354개 통과(회귀 없음). **실제 AAPL 가격 데이터**로 문제가
  됐던 정확히 그 구간(2024-07~2026-06, 조정 없는 강세장)에 원본 대 국면 스위치 적용을 직접
  비교: 원본은 0회 매매(CAGR 0%, 매수보유 +14.06%에 완전히 못 미침)였던 반면 국면 스위치 적용은
  27회 매매에 CAGR +5.87%로 실질적으로 개선됨(매수보유는 여전히 못 이김 — 과장 없이 그대로 보고).
  실제 라이브 Gemini API + AAPL/MSFT로 `tune_strategy_for_group()` 전체 파이프라인도 실행해
  국면 스위치 구조가 실제로 채택되고 숫자 튜닝까지 정상 연계됨을 확인.

**시장 국면/섹터 강도 자동 갱신을 Streamlit Community Cloud에서도 동작하게 재설계 (2026-07-15,
같은 날 후속 요청)**. 사용자가 배포 주소(`jehhzwta7swj6jwp2mxgus.streamlit.app`)를 공유 — WebFetch로
확인해보니 `share.streamlit.io` 인증 페이지로 리다이렉트되는 Streamlit Community Cloud 배포였다.
바로 위 항목(00:00 KST 스케줄러)이 `scheduler/run_scheduler.py`를 별도 상시 프로세스로 띄워두는
로컬 전제였는데, Streamlit Community Cloud는 메인 앱 컨테이너만 실행하고 그런 별도 백그라운드
프로세스를 띄울 방법이 없다(SSH/crontab 접근 불가) — 그래서 "자동 갱신을 클라우드에서도 동작하게
재설계"를 AskUserQuestion으로 확인 후 진행.

- **설계**: 외부 cron에 의존하는 push 방식(스케줄러가 미리 계산해두는 것) 대신, 방문 시점에
  "저장된 스냅샷이 한국시간 기준 오늘 것인지"를 확인해 아니면 그 방문이 스스로 재계산을 트리거하는
  lazy/on-visit 방식을 추가했다(스케줄러 방식을 대체하는 게 아니라 그 위에 안전망으로 얹음) —
  서버리스/슬립 환경에서 흔히 쓰는 지연 재검증(lazy revalidation) 패턴과 동일한 아이디어. 로컬에서
  스케줄러를 상시로 띄워두면 항상 이미 최신이라 이 폴백은 사실상 안 타고, 클라우드처럼 상시 프로세스가
  없는 환경에서는 자정이 지난 뒤 첫 방문자가 그 자리에서 재계산을 기다리고 그날의 나머지 방문자는
  DB에 저장된 값을 즉시 재사용한다.
- `core/market_regime.py`에 `is_snapshot_stale_for_today_kst(computed_at, now_kst=None)`(DB에
  UTC naive로 저장된 시각을 KST로 변환해 날짜만 비교 — UTC 날짜와 KST 날짜가 다른 자정 전후
  경계에서도 정확하도록 UTC 자정이 아니라 KST 자정 기준으로 비교) + `to_kst()`(표시용 변환 헬퍼)
  신규 추가. `core/sector_strength.py`는 이 둘을 그대로 import해 재사용(테마 강도도 같은 판정
  로직을 쓰므로 중복 정의 없이 공유).
- `app/pages/7_매크로_대시보드.py`: 시장 국면/섹터 강도 두 섹션 모두 트리거 조건을 `saved_regime is
  None`(스냅샷이 아예 없을 때만)에서 `saved_regime is None or is_snapshot_stale_for_today_kst(...)`
  (오늘 것이 아니어도)로 확장. 부수 개선: 재계산이 실패(네트워크 오류 등)해도 화면이 비지 않도록,
  저장된 값(오래됐더라도)을 먼저 세션에 채워두고 재계산 성공 시에만 덮어쓰는 순서로 바꿈 — 캡션에도
  "· 자정이 지나 갱신 대기 중"을 붙여 오늘 것이 아닌 값을 보고 있다는 걸 알 수 있게 했고, 시각
  표시도 UTC 대신 한국시간으로 통일(`to_kst()` 재사용).
- `scheduler/run_scheduler.py`의 `market_snapshot_job()`은 "선택 사항(proactive 최적화)"로 문서
  재정의 — 상시로 띄워두면 아무도 안 기다리고 항상 최신을 바로 보지만, 없어도(클라우드 등) 페이지
  자체 폴백이 유일한 갱신 경로로서 그대로 동작한다는 점을 스크립트 상단 docstring에 명시.
- **부수적으로 확인된 사실(추가 조치 불필요)**: Streamlit Community Cloud는 재배포/장시간 슬립 시
  로컬 디스크(SQLite `data/quant.db`, Parquet 캐시)가 초기화될 수 있다는 게 이 앱 전체의 더 큰
  구조적 제약이지만(watchlist/전략/포트폴리오 등 다른 데이터도 전부 영향받음 — 이번 스코프 밖의
  훨씬 큰 작업), 이번에 만든 lazy staleness 방식은 그 상황에서도 자연히 self-heal한다(스냅샷 테이블이
  비어있으면 그냥 "오늘 첫 방문"으로 취급해 재계산할 뿐, 별도 예외처리가 필요 없음).
- 검증: `tests/test_market_regime.py`에 `is_snapshot_stale_for_today_kst`/`to_kst` 신규 테스트
  4개(오래된/방금 계산됨/UTC-KST 날짜 경계·양방향/naive UTC 변환 정확성 — 특히 "UTC 날짜만 비교했다면
  오판했을 경계 시각"을 `now_kst` 주입으로 직접 구성해 확인). `python -m pytest tests/ -q` 전체 358개
  통과.

**다종목 미세튜닝: 실행 전 "튜닝 대상 파라미터 미리보기" 추가 (2026-07-15, 같은 날 후속 요청)**.
사용자가 "튜닝 전 어떤 파라미터를 튜닝할건지 보여주면 좋겠다"고 요청 — 표시 범위를 두 가지 안(원본값만
vs 6개 스타일별 예상 범위까지 전부)으로 AskUserQuestion 확인 후 후자로 확정.

- `core/strategy_tuning.py`: `build_param_grid()`/`_build_expression_param_grid()`에 인라인으로
  있던 "키 분류(기간/볼린저폭/임계값/비율) → 범위 계산" 로직을 `_key_category()`/
  `_value_range_for_style()`/`_round_original()`(JSON 스키마)과 `_expression_style_range()`
  (expression 스키마) 공용 헬퍼로 추출 — 실제 튜닝 후보를 만드는 함수와 미리보기 함수가 **정확히
  같은 공식**을 쓰도록 강제해, 미리보기가 실제 탐색 범위와 어긋나는 것을 구조적으로 방지했다(리팩터링
  전후 동일 동작은 기존 55개 테스트 통과로 확인). 이 위에 신규 함수 두 개 추가:
  - `describe_tunable_params(base_config)`: JSON 스키마 전용, 후보를 실제로 만들지 않고 조건 경로별
    (위치/지표/파라미터명/원본값/분류/6개 스타일 예상 범위)만 계산 — 순수 계산이라 매 rerun마다
    공짜로 호출 가능.
  - `describe_tunable_params_expression(tunables)`: expression 스키마용, 이미 식별된 숫자 리스트를
    받아 6개 스타일 범위만 계산(Gemini 호출은 기존 `identify_tunable_numbers()`가 그대로 담당 —
    이 함수는 그 결과를 UI가 캐시해 재사용하는 용도).
  - `STYLE_TYPES` 공개 상수 추가(6개 스타일 이름 리스트, UI가 private dict를 직접 참조하지 않도록).
- **UI** (`app/pages/1_백테스팅.py`, "🧬 다종목 미세튜닝" 탭): 백본 선택 직후 종목 표본/탐색 강도
  설정보다 앞에 "🔍 튜닝 대상 파라미터 미리보기" expander 추가.
  - JSON 스키마: `describe_tunable_params()`를 즉시 호출해 표로 렌더링(위치/지표/파라미터/원본값/
    분류 + 스타일 6개 컬럼). 튜닝 대상이 없으면 안내 문구만 표시.
  - expression 스키마: Gemini 호출 비용이 있어 자동 실행하지 않고 "🤖 AI로 튜닝 파라미터 식별"
    버튼(기존 `job_manager` 백그라운드 실행 패턴 재사용)을 눌러야 표가 뜬다. 식별 결과는
    `st.session_state`에 **원본 수식 문자열과 함께** 캐시해두고, 캐시된 수식이 현재 입력 중인
    수식과 다르면(텍스트를 새로 붙여넣는 등) 표를 보여주지 않아 stale 결과가 새 전략에 잘못
    붙는 걸 막는다.
- 검증: `tests/test_strategy_tuning.py`에 신규 테스트 7개 추가 — 6개 스타일 전부 나열되는지,
  **미리보기 범위가 `build_param_grid`가 실제로 만드는 후보 집합과 정확히 일치하는지**(JSON/
  expression 스키마 둘 다 — 배수가 1.0 미만인 스타일은 상한이 원본보다 작아질 수 있어 min/max가
  아니라 `{하한, 원본, 상한}` 집합으로 비교), indicator/direction 같은 구조 필드가 새지 않는지,
  튜닝 대상 없음/expression 스키마 빈 리스트 폴백. `pytest tests/ -q` 전체 364개 통과. Streamlit
  `AppTest`로 라이브 검증: 초기 로드 무오류, JSON 스키마 즉시 렌더 확인, expression 스키마는 버튼
  클릭 후 실제 Gemini 호출까지 성공(표 렌더 확인), 튜닝 대상 없는 전략은 안내 문구만 뜨는 것까지
  3가지 케이스 모두 통과.

**다종목 미세튜닝: 1:2:6 단계별 전략의 stage `weight`(진입/청산 비중)도 튜닝 대상에 포함 (2026-07-15,
같은 날 후속 요청)**. 사용자가 "튜닝 대상 파라미터에서 weight도 고려해달라"고 요청 — `weight`는
`entry_stages`/`exit_stages` 각 단계에 붙은 값이라 `_iter_condition_paths`(조건 안 숫자만 순회)가
전혀 방문하지 않아 지금까지 튜닝 대상 밖이었다. 그런데 같은 stage 목록 안 weight들은 서로 독립적인
숫자가 아니라 배분 비율(예: 1:2:6)이라, 무작정 각각 ±30%로 흔들면 합계가 깨져(총 진입/청산 비중이
원래 의도보다 커지거나 작아짐) 전략의 "몇 단계에 걸쳐 분할 진입/청산"이라는 의미 자체가 왜곡될
위험이 있다는 점을 먼저 확인 후, "합계를 유지하며 재정규화할지"를 AskUserQuestion으로 확인하고
진행.

- **결정 경위(왔다갔다한 부분 기록)**: 처음엔 "합계를 무조건 1.0으로 재정규화"로 확인받고 구현했으나,
  테스트로 실제 `BOLLINGER_1_2_6` 픽스처를 검증하는 과정에서 그 원본 weight 합이
  0.1+0.2+0.6=**0.9**(1.0이 아님)임을 발견 — 무조건 1.0으로 밀어올리면 원래 90%만 투자하도록(10%
  현금 버퍼) 의도적으로 설계됐을 수 있는 전략을 튜닝 후 100% 완전투자로 바꿔버릴 수 있다고 판단해
  "원본 합계 그대로 보존"으로 한 차례 스스로 정정했으나, 사용자가 "합계는 1로 해주라"고 명시적으로
  재확인 — **최종적으로 원본 합계와 무관하게 항상 1.0으로 정규화**하는 것으로 확정(원본이 0.9였던
  1:2:6 예시 전략도 튜닝 후에는 항상 100% 완전투자로 정규화됨).
- `core/strategy_tuning.py`:
  - `_value_range_for_style`/`_round_original`에 `"weight"` 분류 추가(기존 `"ratio"`와 같은 공식 —
    원본 ±30%, 최소 델타 0.02 — 재사용, 카테고리 라벨만 "비중배분"으로 구분).
  - `_weight_stage_lists(config)`: `entry_stages`/`exit_stages` 중 weight가 숫자인 stage가
    2개 이상인 목록만 골라낸다(1개짜리는 정규화해봐야 항상 1.0 그 자체라 탐색 의미가 없어 제외).
    탐색 축 생성과 재정규화가 이 판별 로직을 공유해야 "탐색하지 않은 stage를 재정규화가 건드리는"
    불일치가 안 생긴다.
  - `_weight_axis_values(config)`: 위 목록의 각 stage weight를 다른 축과 동일한 `(path, key, values)`
    형식으로 만들어 `build_param_grid`의 기존 `axis_values`(itertools.product/랜덤 샘플링 인프라
    그대로 재사용)에 합류시킨다.
  - `_normalize_stage_weights(candidate)`: 각 후보 생성 직후(`build_param_grid`의
    `for combo in combos:` 루프 안) 그 stage 목록의 weight들을 `w / 흔들린_합`으로 재조정해 합이
    항상 1.0이 되게 한다 — 배분 비율만 탐색하고 총 노출도는 항상 100%로 고정. 목록 끝에 그대로
    덧붙는 "원본 폴백" 후보(`candidates.append(original)`)는 예외적으로 재정규화하지 않고 원본
    그대로 남긴다(다른 후보와 정직하게 비교하기 위한 기존 관례 유지).
  - `describe_tunable_params()`가 weight 행도 포함하도록 확장(같은 헬퍼 재사용이라 build_param_grid
    실제 탐색과 항상 일치). 정규화 때문에 표시된 범위가 그대로 채택되지 않을 수 있다는 점을
    docstring/UI 캡션에 명시.
- **UI** (`app/pages/1_백테스팅.py`): "🔍 튜닝 대상 파라미터 미리보기" 표에 weight 행이 자동으로
  섞여 나오고, 캡션에 정규화 동작(합계가 항상 100%로 맞춰짐) 안내 추가.
- 검증: `tests/test_strategy_tuning.py`에 신규 테스트 7개 — weight가 실제로 여러 값으로 흔들리는지,
  **정규화 후 합이 항상 1.0인지**(원본 폴백 후보 하나만 예외로 남고 나머지 전부), stage가 1개뿐이면
  weight가 아예 안 흔들리는지, `describe_tunable_params`에 weight 행 6개(entry 3 + exit 3)가 정확한
  경로로 나오는지, entry_stages/exit_stages가 없는 레짐 전략은 weight 행이 안 나오는지.
  `pytest tests/ -q` 전체 372개 통과. Streamlit `AppTest`로 라이브 검증: weight 행이 예상 범위
  ("비중배분" 분류, 예: entry_stages[2] weight 0.6 → 성장주 0.42~0.78)로 정확히 렌더되는 것 확인.

**백테스팅에 "두 전략을 합쳐 새 전략 만들기(전략 합성)" 기능 추가 (2026-07-15, 같은 날 후속 요청)**.
사용자가 "백테스팅 할 때 두 전략을 합쳐서 새로운 전략을 만드는 기능을 추가해줘"라고 요청 → 기존
스키마 3종(레짐/직접 수식/1:2:6 단계별)을 어떻게 합칠지 애매한 지점이 커서(결합 로직 고정 vs 선택,
합성 가능한 전략 유형 범위, 결과물 처리 방식) 구현 전에 AskUserQuestion으로 3가지 확인:
① AND/OR 둘 다 화면에서 선택 가능하게, ② 레짐/직접 수식/1:2:6 단계별/전략 합성 전부 자유 조합 가능
(재귀 지원, 1:2:6은 비중>0을 보유로 단순화), ③ 합성 결과는 전략 라이브러리에 저장해 재사용/미세튜닝
대상으로 다룸(단, 튜닝 엔진 자체 연동은 이번 범위 밖).

- **네 번째 indicator_config 스키마 추가**: `{"combine": "AND"|"OR", "strategies": [<하위 전략 A>,
  <하위 전략 B>]}`. `core/strategy_engine.py`에 `is_combined_config()` + `evaluate_boolean_signal()`
  (레짐/직접 수식/1:2:6 단계별/전략 합성 4종 전부를 "포지션 보유 중" 불리언 시그널 하나로 통일하는
  공용 진입점, 하위 전략이 다시 전략 합성이면 재귀 평가) 신규 추가. 기존 `generate_positions()`와
  `evaluate()`(관심종목 일일 모니터링, 스케줄러 경로)가 이 함수를 쓰도록 교체 — 교체 전에는 합성
  전략을 넘기면 `combine_conditions()`가 `conditions` 키가 없어 항상 False를 반환해(예외 없이) 항상
  "조건 미충족"으로 조용히 오판단하는 문제가 있었음(리서치 에이전트가 사전에 확인, 크래시는 아니지만
  기능이 조용히 no-op 되는 버그).
- `extract_trades()`의 진입/청산 근거 문구도 합성 전략이면 "복합 전략(AND/OR 결합, 하위 전략 N개)
  조건 충족/이탈"로 표시(레짐처럼 조건별 문구를 나열하진 않지만 최소한 일반적인 "조건 충족" 대신
  합성이라는 사실을 알 수 있게 함).
- `core/strategy_library.py`: `detect_strategy_type()`에 `"combined"` 분기 추가,
  `validate_indicator_config()`는 `_validate_config_schema()`로 재귀 리팩터링해 합성 전략(하위 2개
  이상, combine이 AND/OR인지)과 그 하위 전략(어떤 스키마든)까지 재귀 검증.
- `core/strategy_explainer.py`: `describe_combined_config()` 신규(하위 전략을 재귀적으로 요약해
  "하위 전략 N개의 보유 신호 중 모두/하나라도 참인 구간에 보유하는 복합(AND/OR) 전략" 형태로 결정론적
  요약 생성) + `explain_strategy()`가 이 요약을 근거로 Gemini에게 다듬게 함(레짐/1:2:6과 동일한
  환각 방지 패턴).
- **UI**: `app/pages/1_백테스팅.py`에 리서치 에이전트가 찾아낸 기존 사각지대를 활용 — `tab_generate`
  ("🔬 알고리즘 자동 생성")가 `st.tabs()`에 선언만 되어있고 실제 `with tab_generate:` 블록이 어디에도
  없어 화면에 빈 탭으로만 존재하던 죽은 코드였음. 이 자리를 "🧩 전략 합성" 탭으로 재활용(5번째 탭을
  새로 추가하는 대신) — 전략 A/B 선택(라이브러리 드롭다운, 유형 라벨 표시) + AND/OR 라디오 + 합성된
  JSON 미리보기 + 티커/기간 입력 + 기존 `compare_with_benchmarks`/`render_price_chart`(합성 전략은
  `conditions` 키가 없어 지표 오버레이 없는 캔들차트만 표시 — 직접 수식 전략과 동일한 처리)/
  `render_equity_comparison`/`metrics_dataframe`를 그대로 재사용해 백테스트 실행·저장까지 지원.
  `job_manager` 백그라운드 실행 패턴도 기존 tab_backtest와 동일하게 재사용(새 로직 없음).
- `app/pages/9_전략_관리.py`의 `TYPE_LABELS` 딕셔너리는 3개 키만 있어 직접 인덱싱(`TYPE_LABELS[...]`)
  이라 합성 전략이 하나라도 있으면 페이지 로드 자체가 `KeyError`로 깨지는 하드 크래시였음(리서치
  에이전트가 사전에 확인) — `"combined"` 키를 추가해 해결.
- **다종목 미세튜닝은 이번 범위에서 제외**: `core/strategy_tuning.py`의 `build_param_grid`/
  `generate_structural_variants_for_config`는 합성 전략을 넘겨도 크래시하지는 않지만(조건 경로를
  못 찾아 원본을 그대로 반환하거나 레짐으로 오인해 무의미한 Gemini 변형을 시도) 실질적인 튜닝은
  되지 않는다 — 사용자가 요청한 범위가 아니라 이번에는 손대지 않고 알려진 제약으로 남김.
- **동시 작업 주의사항**: 이 세션 도중 다른 Claude 세션이 같은 `core/strategy_engine.py`(캔들 패턴
  지표 추가)/`app/pages/1_백테스팅.py`(다중 구간 워크포워드 튜닝 리포트)/`PROGRESS.md`를 동시에
  수정하고 있어, 매 편집 전 파일을 다시 읽고 고유한 문자열을 앵커로 삼아 겹치지 않는 위치에만
  이어붙이는 방식으로 진행함(실제 충돌 없이 완료).
- 검증: `tests/test_strategy_engine.py`(합성 판별/AND-OR 결합/1:2:6 하위 전략의 비중>0 단순화/
  재귀 중첩 합성/`generate_positions` 디스패치/근거 문구)·`tests/test_strategy_library.py`(합성
  판별·검증·중첩 검증·검증 실패 케이스)·`tests/test_backtest_engine.py`(합성 전략 `run_backtest`
  end-to-end, AND 결합이 하위 전략보다 보유일이 많을 수 없음을 확인) 신규 테스트 다수 추가,
  `pytest tests/ -q` 전체 386개 통과. 임시 SQLite DB에 실제 전략 2개(MA골든크로스/RSI과매도)를 저장한
  뒤 Streamlit `AppTest`로 라이브 검증: 전략 합성 탭 로드 → A/B 선택(유형 라벨 포함 정상 표시) →
  AND 결합 → 실제 AAPL 데이터로 백테스트 실행(24회 매매, CAGR +5.46% 등 실제 지표 확인) → 라이브러리
  저장(유형이 정확히 "combined"로 저장됨 확인) → 전략 관리 페이지가 합성 전략이 존재하는 상태에서도
  정상 로드(예전 같으면 `KeyError`)되는 것까지 실제 데이터로 전부 확인.

**캔들스틱 패턴 지표 8종 + 캔들 패턴 매매 전략 5종 추가 (2026-07-15, 같은 날 후속 요청)**. 사용자가
캔들차트 실전 매매법 유튜브 강의 대본(마루보즈/핀바/도지/장악형/인사이드바/관통형/모닝스타·이브닝
스타/적삼병·흑삼병/삼법형)을 붙여넣고 "수식을 만들고 전략을 넣어달라"고 요청 → 같은 날 앞서 완료된
`BOLLINGER_STRATEGIES_SPEC.md` 워크플로(원문 → 수학적 정의 → 지표 함수 → 조건 평가기 → 구체 전략)를
그대로 재사용해 `CANDLESTICK_PATTERNS_STRATEGY_SPEC.md` 작성 후 구현. 자세한 수식/스코프 결정은 그
문서 참고, 요약:
- `core/indicators.py`에 공용 `_candle_geometry()`(몸통/범위/위꼬리/아래꼬리) + 8개 캔들 패턴 함수
  신규(`compute_marubozu`/`compute_pin_bar`/`compute_doji`/`compute_inside_bar`/
  `compute_piercing_dark_cloud`/`compute_star_pattern`/`compute_three_soldiers_crows`/
  `compute_rising_falling_three_methods`). engulfing은 기존 것 재사용. `compute_piercing_dark_cloud`는
  `compute_double_pattern`과 같은 이유로 볼린저 밴드 이탈-복귀 확인까지 지표 내부에서 함께 판정(영상의
  "관통형+볼린저 밴드" 실전 매매법을 조건 하나로 표현하기 위함).
- `core/strategy_engine.py`: 위 8개 + 저항/지지선 돌파 이벤트(`level_break`, source=highest_high/
  lowest_low) + 단일 이동평균선 터치(`ma_touch`, `ma_cross`의 단일선 버전) 총 10개 조건 평가기를
  `INDICATOR_EVALUATORS`/`describe_condition`에 등록. `simulate_staged_positions`에 손절 대비 배수
  익절(`take_profit`, 형식은 `{"multiple": 2.0}`, 반드시 `stop_loss`와 함께 정의 — 없으면 ValueError)을
  신규 일반 메커니즘으로 추가(모닝스타 전략의 "손절선 대비 2배 익절" 요구사항 때문). 진입 사이클 시작
  바에서 `목표가 = 진입참조가 + multiple*(진입참조가-손절레벨)`을 스냅샷 고정, 종가가 그 이상이면
  stop_loss와 동일한 우선순위로 즉시 전량 청산(`StageEvent(kind="take_profit")`) —
  `extract_staged_trades`는 이미 `kind != "entry"`를 전부 청산으로 처리해 별도 수정 불필요.
- **구체 전략 5개를 `source="youtube_script"`로 DB에 직접 등록** (Bollinger 4종과 달리 이번엔 원문이
  진입/손절/익절을 전부 정확한 수치로 제공해 AI 해석 없이 손검증된 JSON을 바로 만들 수 있었음):
  강세 핀바 반전(손절=핀바 저점), 상승 장악형 돌파(저항선 돌파+장악형, 익절=하락 장악형 출현),
  상승 관통형(볼린저 밴드 확인 내장, 익절=상단 밴드 터치), 모닝스타 반전(손절=2번째 캔들 저점 근사,
  익절=손절 대비 2배 — `take_profit` 메커니즘 실사용), 상승 삼법형(익절=20 EMA 터치 —
  `ma_touch` 실사용). 마루보즈/도지/인사이드바/적삼병 등은 원문에 정확한 손절가가 없는 정성적
  설명뿐이거나 유일한 워크스루가 숏이라 지표만 제공하고 완성 전략은 등록하지 않음(추측 금지 원칙,
  Bollinger 스펙과 동일).
- **롱온리 제약**: 엔진이 여전히 롱온리라 각 패턴의 bearish(숏) 워크스루(약세 핀바/하락 관통형·
  흑운형/이브닝스타/흑삼병/하락 삼법형)는 완성 전략에서 전부 제외. 지표 함수 자체는 bullish/bearish
  양쪽 다 구현해뒀으니 향후 숏 지원 시 바로 재사용 가능.
- `core/nl_strategy.py`: `STAGE_CONDITION_PROPERTIES`(신규 지표 10개 enum + 관련 파라미터)/
  `STAGED_INDICATOR_CONFIG_SCHEMA`(`take_profit` 서브스키마)/`STAGED_SYSTEM_PROMPT`(신규 지표 설명 +
  take_profit 사용 기준)/`_STAGED_HINT_KEYWORDS`(마루보즈/핀바/도지 등 캔들 패턴 키워드)에 전부 반영
  — 향후 비슷한 캔들 패턴 영상을 붙여넣으면 AI가 이 지표들을 바로 쓸 수 있음.
- **동시 작업 주의사항**: 이 세션 도중 다른 세션이 같은 `core/strategy_engine.py`/`PROGRESS.md`에
  "전략 합성" 기능을 동시에 추가하고 있었음(바로 위 항목) — 매 편집 전 파일을 다시 읽고 고유 문자열을
  앵커로 삼아 겹치지 않게 이어붙여 실제 충돌 없이 완료. 최종적으로 두 기능이 한 파일에 공존하는 것과
  전체 테스트 통과를 확인함.
- 검증: `tests/test_strategy_engine.py`에 8개 지표 함수(합성 데이터로 양성 판정)·조건 디스패치
  (marubozu/doji/level_break/ma_touch)·take_profit 메커니즘(2배 배수 청산, stop_loss 없이 정의하면
  ValueError) 신규 테스트 다수 추가. `pytest tests/ -q` 전체 399개 통과. 5개 전략 전부 실제 AAPL
  데이터(2018~2026)로 `run_backtest` 직접 호출해 매매/손절/익절 이벤트가 실제로 발생함을 확인(삼법형만
  이 구간에서 매매 0건 — 5봉짜리 엄격한 패턴이라 종목/기간에 따라 드묾을 TSLA/MSFT에서 발생 이력 확인
  후 버그 아님으로 결론). Streamlit `AppTest`로 실제 백테스팅 페이지에서 전략 라이브러리 드롭다운에
  5개 전략이 노출되는지, 그중 모닝스타 반전 전략을 선택→불러오기→AAPL 백테스트 실행까지 예외 없이
  동작하고 실제 지표 테이블이 렌더링되는지 라이브 확인(기본 3년 조회 구간에는 모닝스타가 우연히
  없어 매매 0건으로 나왔으나 8년 구간에서는 12건 확인되어 버그 아님).

**"상승 삼법형 0건" 문의 대응 + 정성적 캔들 패턴 4개 웹 검색 보충 (2026-07-15, 같은 날 후속 요청)**.
사용자가 상승 삼법형 전략을 백테스트했더니 "AAPL 전략 적용" 행이 전부 0으로 나온다며 "제대로 한 거
맞냐"고 의심 → 버그 가능성을 진지하게 재검증:
- **재검증 결과 = 버그 아님, 실제로 극히 드문 고전 패턴**: AAPL/MSFT/TSLA/NVDA/AMZN/GOOGL/META/AMD
  8개 종목 2010~2026(최대 16년) 전체로 `compute_rising_falling_three_methods` 발생 횟수를 직접 세어보니
  종목당 0~1회 수준. 웹 검색으로 Thomas Bulkowski의 실증 연구를 찾아 확인: 상승 삼법형은 주식 캔들
  470만 개 전수조사 중 **102개만 발견**된, 그가 추적하는 103개 패턴 중 빈도 순위 88위(가장 드문 축)인
  패턴 — 사용자가 테스트한 AAPL 3년 구간에서 0건이 나오는 것은 수학적으로 정상적인 결과. 구현을
  인위적으로 느슨하게 바꾸지 않음(원래 정의된 패턴과 달라지면 오히려 사용자를 오도).
- 사용자가 이어서 "정성적 설명만 있던 패턴들도 인터넷 검색으로 보충하라"고 요청 → 애초 "원문에 손절/
  익절 명시 없음"이라 지표만 만들고 완성 전략을 등록하지 않았던 4개(마루보즈/잠자리형 도지/인사이드바/
  적삼병)를 웹 검색으로 표준 매매 관례를 찾아 보충, 전략 4개 추가 등록(총 9개):
  - **마루보즈 돌파 전략**: 손절=캔들 저점, 익절=손절거리×1.5(LiteFinance/ProTradingSchool 검색 근거).
  - **잠자리형 도지 반전 전략**: 손절=도지 저점, 익절=손절거리×2.0(최소 손익비 2:1, FXOpen/BullishBears
    검색 근거).
  - **인사이드바 돌파 전략**: 손절=마더 바 반대편 근사. 구현 중 함정 하나 발견 — 기존 `inside_bar`
    (그날 자체의 포함 관계만 판정)와 `level_break`를 그대로 AND 조합하면, 인사이드바가 성립하는 그날은
    정의상 고가가 마더 바 고가를 넘을 수 없어 두 조건이 같은 날 동시에 참이 되는 경우가 존재하지
    않는다 — 실제로 만들기 전에 발견해 피함. `core/indicators.py`에 `compute_inside_bar_breakout`
    (인사이드바 성립 후 lookback봉 이내에 마더 바 고점/저점을 종가가 돌파하면 이벤트 발생, `
    compute_double_pattern`과 동일한 "성립 후 N봉 이내 확인" 상태 머신 방식) 신규 추가, `core/
    strategy_engine.py`에 `inside_bar_breakout` 조건으로 등록. `core/nl_strategy.py` 프롬프트에도 이
    함정을 경고문으로 명시(향후 AI가 같은 실수를 하지 않도록).
  - **적삼병 상승 지속 전략**: 3번째 캔들 종가에 진입("보수적 진입", LiteFinance/TradingSim 검색
    근거), 손절=첫 번째 캔들 저점 근사.
  - 인사이드바/적삼병은 검색 결과에 위험관리 원칙(계좌 자본 1~2%)은 있어도 구체적 손익비 숫자가 없어
    `take_profit`은 채우지 않고 `level_break` 안전장치 청산만 사용(추측 금지 원칙 유지).
- 4개 전략 전부 AAPL/MSFT/TSLA 2010~2026으로 `run_backtest` 직접 호출해 매매 발생 확인(마루보즈
  19~43건, 도지 2~9건, 인사이드바 25~49건, 적삼병 0~3건) + take_profit/stop_loss 이벤트 정상 발생 확인.
  `tests/test_strategy_engine.py`에 `compute_inside_bar_breakout` 단위 테스트 + 조건 디스패치 테스트
  추가. `pytest tests/ -q` 전체 405개 통과. `CANDLESTICK_PATTERNS_STRATEGY_SPEC.md` §8에 이번 조사
  결과와 출처 링크 전부 기록.

**섹터 리더·성장주 관계 분석: 분석 기간을 사용자가 직접 고를 수 있게 함 (2026-07-15)**. 사용자가
"1개월/6개월/1년/3년 프리셋 또는 직접 날짜 선택으로 분석 기간을 정할 수 있게 해달라"고 요청.
기존에는 베타/상관계수가 고정된 "최근 252거래일"(`RELATIONSHIP_WINDOW_DAYS`), 비교 차트는 기본
lookback(약 2.2년) 전체를 기준으로 계산돼 사용자가 기간을 바꿀 방법이 없었다.

- `core/sector_leaders.py`:
  - `RELATIONSHIP_WINDOW_DAYS`(고정 252거래일) 제거. `compute_relationship_metrics(ticker,
    etf_series, start=None, end=None)`가 이제 베타/상관계수/RS비율을 선택된 기간 **전체**를
    창(window)으로 써서 계산한다 — 단, 종목 자체의 절대추세(`abs_trend`, 200일선/50-200 골든크로스
    기준)는 짧은 기간을 골라도 계산 가능해야 하므로, 가격 조회 자체는 `min(start, _default_start())`
    로 항상 200일선을 채울 만큼 과거까지 받아오고(200sma용 여유분), 그중 `start` 이후 구간만 잘라
    나머지 지표에 쓴다. RS "3개월 변화"(63거래일)/RS "추세"(20거래일)는 기간과 무관한 고정
    단기지표로 유지(짧은 기간을 고르면 자연히 계산 불가로 우아하게 축소).
  - 최소 데이터 길이 기준을 `len(aligned) < 30`/`len(returns) < 20`(1년치 데이터 전제)에서
    `_MIN_ALIGNED_DAYS=15`/`_MIN_RETURN_DAYS=10`으로 낮춤 — 1개월(~21거래일) 프리셋을 골라도 결과가
    전부 None으로 죽지 않게 하기 위함.
  - `analyze_theme_relationships(theme, top_n_growth=3, start=None, end=None)`/
    `theme_price_history`/`build_price_chart_series`/`build_price_chart_candidates` 전부 start/end를
    받아 실제 가격 조회에 그대로 전달하도록 시그니처 확장(안 주면 기존 기본 동작 그대로 — 하위 호환).
    `analyze_theme_relationships`의 반환 dict에 `"start"`/`"end"`를 추가해, 페이지가 기존
    `"theme"` 필드와 같은 방식으로 "지금 보이는 결과가 현재 선택된 기간과 일치하는지" 판별할 수
    있게 함.
- **UI** (`app/pages/12_섹터_리더_성장주.py`): 테마 선택 아래에 "분석 기간" 라디오(1개월/6개월/1년/
  3년/직접 선택) 추가, "직접 선택" 시 시작일/종료일 `date_input` 두 개가 나타난다(기존 백테스팅
  탭의 동일 패턴 재사용). `job_manager.ensure`의 `params_key`를 `(테마, 시작일, 종료일)` 튜플로
  바꿔 기간을 바꾸면 자동으로 재분석되게 했고, "결과가 최신인지" 판별 조건에도 `start`/`end` 일치
  여부를 추가.
- 검증: `tests/test_sector_leaders.py`에 신규 테스트 5개 — start가 베타/상관계수는 실제로 잘라내되
  abs_trend는 전체 히스토리로 여전히 계산되는지(정권이 바뀌는 합성 데이터로 클리핑이 진짜 적용됨을
  증명), 1개월 상당의 짧은 창이 더 이상 None으로 막히지 않는지, `analyze_theme_relationships`가
  start/end를 `theme_price_history`/`compute_relationship_metrics` 양쪽에 그대로 전달하는지,
  `build_price_chart_series`의 ETF 조회도 start/end를 받는지. 기존 테스트의 monkeypatch 목(mock)
  전부 새 키워드 인자(start/end)를 받도록 갱신. `pytest tests/ -q` 전체 403개 통과. Streamlit
  `AppTest`로 라이브 검증: 초기 로드 무오류, "직접 선택" 클릭 시 시작일/종료일 `date_input` 두 개가
  정확히 나타나는 것 확인.

**야간 미세튜닝 엔진에 국면별(약세장/강세장) 분리 트레이닝 추가** (2026-07-16). 사용자가 "야간에
테스팅할 때 S&P500을 기준으로 약세장/강세장을 나누고, 약세장 데이터로 트레이닝하는 전략과 강세장
데이터로 트레이닝하는 전략을 따로따로 접근해서 미세튜닝하도록 변경해달라"고 요청. "야간 테스팅"은
`scheduler/run_scheduler.py::strategy_nightly_tuning_job()`(00:05~04:00 KST 자동 실행)을 정확히
가리키고, 이 잡은 `core.strategy_tuning.run_batch_tuning()`을 그대로 쓰므로 core 엔진 레벨에서
바꿔 야간 자동 실행과 "🧬 다종목 미세튜닝" 수동 탭 양쪽에 자동 반영되게 함. 설계 논의/결정 근거는
`STRATEGY_TUNING_ENGINE_SPEC.md` 13절에 정리(이 세션은 auto mode였고 기존 확립된 패턴을 따라
기술적 결정은 직접 판단 후 근거를 스펙 문서에 남김, 별도 확인 질문 없이 진행):

- **핵심 설계**: 기존 "스타일(6종) → 그룹당 config 1개" 구조에 "국면(약세장/강세장, 2종)" 축을
  추가 — 스타일 그룹마다 이제 config가 2개(국면별로 완전히 독립적으로 학습). "중립/혼조" 국면
  날짜는 양쪽 트레이닝 어디에도 안 씀.
- **국면 판정** (`core/market_regime.py` 신규): `get_market_regime_snapshot()`의 시장폭(전종목
  200일선 조회) 신호는 5년 이력을 매일 밤 훑기엔 너무 비싸 빼고, 벤치마크(^GSPC) 종가 하나로
  벡터 연산 가능한 2개 신호(200일선 대비 위치 + 52주 고점 대비 낙폭)만으로 일별 라벨을 매기는
  `classify_daily_regime(close)` 신설 — 낙폭 -20% 이하면 무조건 약세장, 200일선 위+조정폭 10%
  이내면 강세장, 나머지는 중립. `find_regime_segments(regime, target, min_trading_days)`로 연속
  구간을 뽑고, `historical_regime_segments(start, end)`가 둘을 묶어 {"강세장": [...], "약세장":
  [...]}를 반환.
  - **실제 2018~2023 데이터로 검증하다가 버그성 설계 실수를 하나 발견/수정**: 짧은 구간(경계
    flicker) 필터 기준을 처음엔 20 거래일로 잡았는데, 2020년 3월 코로나 급락(고점 대비 -20% 이상
    지속된 기간이 약 17거래일 — 회복이 극도로 빨라서)이 통째로 flicker로 오인돼 버려지는 것을
    실제 라이브 조회로 발견 → 10 거래일로 낮춰 재검증하니 코로나 급락(2020-03-16~04-07)과 2022년
    약세장(2022-09-21~10-24) 둘 다 정상적으로 잡힘. **교훈**: 이런 임계값은 유닛테스트(합성
    데이터)만으로는 안 잡히니 실제 시장 이벤트로 최종 검증할 것.
  - **별개로 발견한 기존(무관한) 캐시 버그**: `data/cache/^GSPC_1d.parquet` + `.full` 마커가 이미
    2020-09-01부터의 데이터만 갖고 있으면서 "이게 전체 이력"이라고 잘못 표시돼 있어, 더 이전 기간을
    요청해도 재조회를 안 하고 있었다(원인 불명 — 이전 세션의 일시적 조회 실패가 `.full`로 잘못
    마킹된 것으로 추정). 이번 세션과 무관한 기존 버그라 별도 수정은 안 하고, 로컬 캐시 파일만 삭제해
    재생성했다(`data/cache/`는 gitignore 대상이라 삭제해도 안전). **주의**: 다른 티커에서도 같은
    증상(예상보다 짧은 이력)이 보이면 해당 `.full` 마커 파일을 의심할 것.
- **워크포워드 폴드 재사용** (`core/strategy_tuning.py`): `_select_best_group_config_walkforward`가
  이제 `train_start`/`train_end` 대신 `folds`를 직접 받도록 리팩터링해, 국면 세그먼트를
  `_train_folds_for_regime()`으로 만들어 그대로 폴드로 넘긴다 — 11절에서 만든 워크포워드 점수/
  커버리지 로직을 전혀 새로 안 만들어도 됨. `tune_strategy_for_group(..., regime=None)` 파라미터
  추가 — `regime=None`(기본값)이면 기존 달력 등분 폴드(레거시 경로, 하위 호환), `"약세장"`/`"강세장"`
  이면 국면 세그먼트 폴드. train 구간에 해당 국면이 아예 없으면(예: lookback에 뚜렷한 약세장 없음)
  기존 "유효 후보 없으면 원본 유지" 폴백이 그대로 작동 + `insufficient_regime_data=True`로 표시.
- **Test 평가**: 정직성 원칙(4b/11절, test는 절대 선택에 안 씀) 그대로 유지. 기존과 동일하게 test
  구간 전체로 평가하는 기본 지표는 회귀 없이 유지하고, 보조 지표 `regime_matched_test`를 신설 —
  test 구간 안에서 같은 국면의 가장 긴 연속 구간 하나만 별도 평가(여러 조각을 이어붙이면 갭에서
  포지션이 모호해져 안 함). 해당 구간이 없으면 None.
- **DB**: `StrategyTuningResult`에 `trained_regime`/`insufficient_regime_data`/`regime_matched_test`
  3컬럼 추가 — 종목 하나당 배치 1회 실행에 이제 국면별로 2행이 생긴다(기존 1행). 기존
  `data/quant.db`에 이미 이 테이블이 있어(9/11/12절과 동일한 상황) **수동 `ALTER TABLE` 필요**
  (다음에 로컬 앱을 실행할 때 `sqlite3 data/quant.db`로 3개 컬럼 직접 추가할 것 — 기존 컬럼 추가
  때와 동일 패턴, `init_db()`의 `create_all()`만으로는 기존 테이블에 컬럼이 안 생김).
- **UI**: "🧬 다종목 미세튜닝" 탭 결과 표에 "학습국면" 컬럼 추가, 스타일 그룹별 요약을 (유형,
  학습국면) 조합으로 groupby하도록 변경. 종목 하나가 국면별로 2행이 되므로, 결과 상세보기 섹션의
  선택/조회/저장 로직을 티커 단독 키에서 **(티커, 학습국면) 조합 키**로 바꿔야 했다(안 바꾸면 같은
  티커의 두 국면 결과가 dict에서 서로를 덮어써 하나만 보이고, Streamlit 위젯 key도 충돌할 뻔함 —
  라이브 테스트 전에 코드 리뷰로 미리 발견해 수정). "🌙 야간 미세튜닝 리더보드"에도 "학습국면"
  컬럼 추가. 라이브 국면 전환에 따라 두 config 중 하나를 실전에 자동 적용하는 기능은 이번 요청
  범위 밖으로 명시(스펙 13.8절 — 별도 상의 필요, 과설계 방지).
- **검증**: `tests/test_market_regime.py`에 신규 유닛테스트 12개(`classify_daily_regime`/
  `find_regime_segments`/`historical_regime_segments`, 합성 데이터로 결정론적 라벨링/구간 추출/
  짧은 구간 필터링 확인), `tests/test_strategy_tuning.py`에 신규/갱신 테스트 다수(국면 폴드 위임,
  regime=None 레거시 경로 불변, 데이터 부족 폴백, regime_matched_test 최장 구간 선택, 배치 실행이
  스타일×국면 조합마다 결과를 내는지, DB 왕복에 3개 신규 필드 포함). 전체 `pytest tests/ -q` 432개
  통과. 실제 라이브 데이터로 `tune_strategy_for_group(['AAPL','MSFT'], ..., regime='약세장')`을
  2018~2023 구간에 돌려 정상 동작 확인(2022년 약세장 구간이 test 쪽 regime_matched_test로 정확히
  잡힘), `run_and_save_tuning()` 전체 파이프라인도 임시 SQLite로 라이브 실행해 저장/조회 왕복 확인.

**야간 미세튜닝 리더보드에 "실제로 바뀐 파라미터" + 자연어 설명 추가 (2026-07-16)**. 사용자가
"야간 미세튜닝 리더보드에서 실제 수정된 파라미터들이 무엇인지 알려주고 자연어로도 설명해주면 좋을
거 같아"라고 요청. 기존 `13_야간_미세튜닝_리더보드.py`의 "채택된 파라미터 보기" 섹션은 `tuned_config`
원본 JSON을 `st.json()`으로 그대로 덤프할 뿐, 백본(원본) 대비 무엇이 바뀌었는지는 사람이 JSON을 직접
비교해야만 알 수 있었음.

- `core/strategy_tuning.py`에 `describe_tuning_diff(base_config, tuned_config)` 신규 추가 —
  `describe_tunable_params()`가 이미 쓰던 위치 판별 로직(`_iter_condition_paths`/
  `_weight_stage_lists`)을 그대로 재사용해 build_param_grid가 실제로 건드리는 자리만 비교한다.
  조건 변경은 `core.strategy_engine.describe_condition()`으로 만든 한국어 문구를 전/후로 비교해
  다르면 diff 항목으로 남기고(예: "RSI(14) 30 상향 돌파 → RSI(14) 35 상향 돌파" — 새 라벨 사전을
  따로 안 만들고 기존 문구 생성기를 그대로 재사용), stage 비중(weight)은 별도로 "진입 1단계 비중
  10% → 15%"처럼 비교한다. 직접 수식(expression) 전략은 숫자 단위 위치 정보가 튜닝 시점 이후
  저장되지 않아 부분 diff가 불가능하므로 수식 전체 전/후만 비교. 구조 변경(백본변경)으로 조건
  개수/종류 자체가 달라져 같은 경로를 tuned_config에서 못 찾는 경우는 예외 없이 조용히 건너뛴다
  (added/removed 조건까지 비교하는 건 이번 범위 밖).
- `summarize_tuning_diff(diff, backbone_changed=False)` 신규 추가 — 위 diff 결과를 한글 문단으로
  요약한다. **AI 호출 없이 결정론적으로만 생성**(리더보드에서 결과를 열 때마다 비용/지연 없이 바로
  보여줘야 하므로, `describe_condition()` 등 기존 결정론적 생성기만 조합). 변경이 전혀 없으면(train/
  test 양쪽에서 원본이 최선이었던 경우) "원본을 그대로 채택했습니다"로 명시하고, 백본 자체가 바뀐
  경우(`backbone_changed=True`)는 "⚠️ ... 구조 자체가 다른 전략으로 교체됐습니다" 경고를 앞에 붙여
  아래 diff가 완전히 대응되지 않을 수 있음을 사용자에게 알린다.
- `get_top_tuning_results()`가 반환하는 각 결과 dict에 `base_config`(해당 실행의 `StrategyTuningRun.
  base_config`를 파싱)를 추가해, 리더보드 UI가 튜닝 전/후를 비교할 수 있게 함(기존에는 `tuned_config`
  만 있어 무엇과 비교해야 할지 알 수 없었음).
- **UI** (`app/pages/13_야간_미세튜닝_리더보드.py`): 상세보기에 "🔧 실제로 바뀐 파라미터" 섹션 신설
  — 자연어 요약 문단 + 위치/지표/이전/이후 컬럼의 표(조건 변경 항목만, JSON 스키마일 때). 원본 JSON은
  삭제하지 않고 "⚙️ 원본/튜닝 전략 JSON 직접 보기" expander로 옮겨 원본(백본)과 튜닝 결과를 나란히
  두 컬럼으로 계속 볼 수 있게 함(기존 기능 제거 없이 보강만 함).
- 검증: `tests/test_strategy_tuning.py`에 신규 테스트 8개 추가(조건+비중 동시 변경 감지, 원본 그대로
  채택된 경우, 직접 수식 전/후 비교, 구조 변경으로 경로가 사라진 경우 예외 없이 처리, 자연어 요약
  각 케이스, 백본변경 경고 접두사, `get_top_tuning_results`의 `base_config` 포함). `pytest tests/ -q`
  전체 417개 통과. 임시 SQLite DB에 실제 볼린저 1:2:6 전략(#3) + 튜닝 결과(RSI 상향돌파 레벨
  30→35, 진입 1/2단계 비중 10%→15%/20%→15%로 변경)를 저장한 뒤 Streamlit `AppTest`로 라이브
  검증: 자연어 요약과 표가 실제로 정확한 전/후 문구("RSI(14) 30 상향 돌파 → RSI(14) 35 상향 돌파",
  "진입 1단계 비중 10% → 진입 1단계 비중 15%" 등)로 렌더링됨을 확인.

**단일 백테스트 결과에 국면별(강세장/약세장/중립) 수익률 분해 추가 (2026-07-16, 같은 날 후속 요청)**.
사용자가 "S&P500/매크로 대시보드 기반으로 강세장/약세장을 판단하는 엔진을 구축해달라, 다른 엔진들이
쓸 수 있게"라고 요청. 조사해보니 핵심 엔진(`core/market_regime.py`의 4-신호 합산 국면 판정,
`classify_daily_regime`/`historical_regime_segments` 일별 이력 라벨링)과 그룹 튜닝 엔진 연동
(`core.strategy_tuning.tune_strategy_for_group(..., regime=...)` — 국면별 분리 학습/평가, UI까지
포함)은 이미 같은 날 다른 세션 작업(STRATEGY_TUNING_ENGINE_SPEC.md 13절)으로 완료돼 있었음. 두 방향
확인 질문(①어디에 연동할지 ②용도) 답변("다른 엔진에 연동" + "둘 다") 중 이미 된 부분은 건너뛰고,
남아있던 "단일 종목 백테스트 결과를 국면별로 쪼개 보여주기"만 신규로 추가:

- `core/backtest_engine.py`에 `compute_regime_breakdown(run, benchmark_ticker=DEFAULT_BENCHMARK_TICKER)`
  신규 추가 — `core.market_regime.classify_daily_regime()`을 재사용해 벤치마크 종가로 일별
  강세장/약세장/중립을 라벨링한 뒤, 백테스트 결과(`BacktestRun.equity_curve`)의 각 날짜를 그 라벨에
  맞춰 나눠 국면별 거래일수/누적수익률(%)을 계산한다. 연속 구간으로 자르지 않고 그 국면에 속한 날들의
  일간수익률을 전부 모아 복리 계산(참고용 근사 지표임을 명시). `market_regime.py`가 이미
  `core.backtest_engine.DEFAULT_BENCHMARK_TICKER`를 import하고 있어 모듈 최상단에서 서로 마주보게
  import하면 순환참조가 나므로, 함수 안에서 지연(lazy) import 처리.
- `app/pages/1_백테스팅.py`: "지표 조합 백테스트" 탭의 성과 지표 표 바로 아래에 "📊 국면별(강세장/
  약세장/중립) 수익률 분해" expander 추가(다종목 미세튜닝/합성 전략 탭은 이번 범위 밖 — 단일 종목
  기본 백테스트 결과만 대상으로 확정, 필요하면 추후 확장).
- 검증: `tests/test_backtest_engine.py`에 신규 테스트 2개(국면 3종 라벨 전부 포함하고 거래일수 합이
  equity_curve 길이와 일치하는지, equity_curve가 빈 BacktestRun에는 빈 dict 반환) 추가 —
  `python -m pytest tests/ -q` 전체 436개 통과. 8510 포트에 별도 테스트 인스턴스를 띄워(정식 8501
  포트는 건드리지 않음) playwright로 실제 AAPL 백테스트를 실행하고 새 expander를 펼쳐, 강세장 689
  거래일/누적수익률 65.48%, 약세장 0거래일(해당 구간에 없어 None), 중립 63거래일이 정확히 표로
  렌더링됨을 라이브 확인 후 테스트 서버 종료.

**시장 국면 엔진에 단기(1개월/3개월) 국면 추가 + 역사적 국면 타임라인 시각화 (2026-07-16, 같은 날
후속 요청)**. 사용자가 "지금 기존 국면 판단은 무슨 기간을 쓰는지 알려주고, 단기(1개월/3개월)
국면도 판단했으면 좋겠다, 섹터별로도 역사적 강세/약세장 구간을 그래프에 표시해달라"고 요청. 확인
질문 2개(①단기 국면 산출 방식 ②표시 위치) 답변("기간 수익률(%) 기준 단순 부호" + "매크로
대시보드 전용 타임라인과 섹터 리더 페이지 차트 배경 둘 다")로 진행:

- `core/market_regime.py`: `classify_period_return_regime(close, window_days, bullish_pct=5.0,
  bearish_pct=-5.0)` 신규 — window_days 거래일 전 대비 현재 종가 등락률(%) 부호만으로 강세장/약세장/
  중립을 판단(기존 4신호 합산과 완전히 분리된 단순 지표, 노이즈에 민감함을 문서/UI 양쪽에 명시).
  `SHORT_TERM_WINDOWS_TRADING_DAYS = {"1개월": 21, "3개월": 63}` + `get_short_term_regimes(close)`로
  둘 다 계산. `get_market_regime_snapshot()`이 이미 가져온 벤치마크 종가(close)를 그대로 재사용해
  별도 네트워크 조회 없이 결과 dict에 `short_term` 키로 추가(기존 `total_score`/`regime` 계산에는
  섞이지 않음 — 장기 국면 판정 로직/임계값을 건드리지 않기 위함).
- `core/theme.py`에 `add_regime_shading(fig, segments_by_regime)` 신규 — 아무 Plotly Figure에나
  `core.market_regime.historical_regime_segments()`의 결과(국면별 (시작일, 종료일) 리스트)를
  `add_vrect`로 겹쳐 그린다(강세장=옅은 초록/약세장=옅은 빨강, 중립은 표시 안 함). x축이 category
  타입인 차트(10_차트_조회.py)에는 좌표계가 달라 못 씀 — 이번 범위 밖으로 명시.
- **UI (매크로 대시보드)**: "시장 국면" 섹션에 "단기 국면(참고용)" 소제목 아래 1개월/3개월 배지
  (국면 + 기간수익률%) 추가, 그 아래 "S&P500 역사적 국면 타임라인" 신설 — 최근 3년 S&P500 종가
  선그래프에 `add_regime_shading` 배경 음영을 겹쳐 표시.
- **UI (섹터 리더/성장주 페이지)**: 기존 두 차트("정규화 성과 비교", "실제 주가 조회") 모두에
  선택된 분석 기간 범위의 S&P500 역사적 국면 배경 음영 추가(캡션으로 안내). 섹터별로 개별 국면을
  다시 계산하지 않고 S&P500 기준 국면을 그대로 오버레이(사용자 답변에 따라 섹터 자체 국면 계산은
  범위 밖으로 확정).
- **DB 마이그레이션 불필요**: `MarketRegimeSnapshot.detail`은 스냅샷 전체를 JSON 문자열로 저장하는
  구조라 새 `short_term` 키가 자동으로 포함됨(컬럼 추가 아님).
- **라이브 검증 중 발견**: DB에 저장돼 있던 기존 스냅샷이 이번 코드 변경 이전에 계산된 것이라
  `short_term` 키가 없어 화면에 "데이터 부족"으로 뜸(코드 버그 아니라 단순 캐시 최신화 필요) —
  실제 S&P500 유니버스로 재계산·저장해 정상 표시되는 것까지 확인(1개월 중립/혼조 +1.9%, 3개월
  강세장 +8.7%). 운영 환경에서도 스케줄러/lazy staleness 갱신이 다음 자정 이후 첫 방문 때 자동으로
  새 스냅샷을 저장하므로 별도 조치 불필요.
- 검증: `tests/test_market_regime.py`에 신규 유닛테스트 6개(임계값 상/하회 강세/약세 판정, 횡보 시
  중립, 데이터 부족 시 None, 1개월/3개월 동시 계산, 빈 스냅샷의 short_term이 `{"1개월": None,
  "3개월": None}`인지) 추가 — `python -m pytest tests/ -q` 전체 445개 통과. 8511 포트에 별도 테스트
  인스턴스를 띄워 playwright로 매크로 대시보드(단기 배지 정상값 표시, 타임라인 차트에 배경 음영
  렌더링 확인)와 섹터 리더 페이지(두 차트 모두 배경 음영과 캡션 렌더링) 둘 다 실제 라이브 데이터로
  확인 후 테스트 서버 종료(정식 8501 포트는 건드리지 않음).

**야간 미세튜닝 리더보드 상세보기에 진입/청산 시점 차트 추가 (2026-07-16, 같은 날 후속 요청)**.
사용자가 "상세 보기에서 종목마다 버튼을 누르면 그 티커의 차트가 나오고 어디서 진입/청산했는지 보여
달라, 백테스팅 차트의 타점 표시 엔진을 그대로 가져다 쓰면 될 것 같다"고 요청 — 요청 자체가 재사용할
로직(백테스팅 엔진의 삼각형 마커 차트)까지 명시해 확인 질문 없이 바로 진행.

- 문제: 삼각형 마커로 진입/청산을 표시하는 `render_price_chart`/`render_staged_price_chart`가
  `app/pages/1_백테스팅.py` 안에만 정의돼 있었음 — Streamlit 페이지 스크립트는 최상단에서 바로
  `st.*` 렌더링을 실행하므로 다른 페이지가 이를 import하면 부작용이 발생해 그대로 재사용이 불가능.
- `core/chart_rendering.py`(신규 모듈) 생성 — 위 두 함수와 내부 헬퍼 `_find_stage_param`을 그대로
  옮김(로직 변경 없음, 순수 이동). `1_백테스팅.py`는 이제 이 모듈에서 import만 하도록 정리(더 이상
  안 쓰는 `compute_ma_cross`/`compute_bollinger`/`compute_ichimoku`/`compute_macd`/`compute_rsi`/
  `make_subplots`/`style_chart_like_tradingview` 직접 import도 함께 정리).
- `core/strategy_tuning.py`의 `get_top_tuning_results()`가 반환하는 각 결과 dict에
  `run_start_date`/`run_end_date`/`train_ratio`를 추가(기존 `StrategyTuningRun`에는 이미 있었지만
  리더보드로 노출되지 않아 test 구간을 다시 계산할 방법이 없었음) — 이 값들로
  `train_test_split_dates()`를 다시 호출해 리더보드 표에 나온 것과 동일한 test 구간(out-of-sample)
  날짜를 구한다.
- **UI** (`app/pages/13_야간_미세튜닝_리더보드.py`): 상세보기에 "📉 진입/청산 시점 차트" 섹션 신설.
  "📈 이 종목 차트 보기" 버튼(종목 선택마다 session_state 키를 분리해, 다른 종목을 고르면 자동으로
  숨겨짐)을 누르면 그 순간 `core.backtest_engine.run_backtest(ticker, tuned_config, test_start,
  test_end)`를 실행해 test 구간 가격 데이터 + 진입/청산 이벤트(`BacktestRun.stage_events`/`.trades`)
  를 얻고, `is_staged_config()`로 분기해 `render_staged_price_chart`(1:2:6 단계별) 또는
  `render_price_chart`(레짐/직접수식)로 그린다 — 위 표의 test 구간 성과 지표와 정확히 같은 기간의
  진입/청산 타점을 보여주는 것이 핵심이라, 버튼 클릭 시점에만(선택할 때마다 자동 조회하지 않음)
  yfinance를 호출하도록 지연 실행.
- 검증: `python -m pytest tests/ -q` 전체 434개 통과(회귀 없음). 임시 SQLite DB + 합성 OHLCV로
  monkeypatch한 `core.backtest_engine.get_price_history`를 준비해(실제 `data/quant.db`/네트워크는
  건드리지 않음) 볼린저 1:2:6 전략(#3) 튜닝 결과 1건을 저장한 뒤 Streamlit `AppTest`로 라이브 검증:
  페이지 최초 로드 → 종목 선택 → "📈 이 종목 차트 보기" 클릭까지 전부 예외 없이 통과했고, 실제로
  plotly 차트 1개가 렌더링되며 캡션에 "test 구간 2020-12-23 ~ 2021-06-30 동안 진입/청산 이벤트
  11건"이 정확히 표시됨을 확인. 같은 방식으로 `1_백테스팅.py`도 리팩터링 후 예외 없이 로드됨을
  별도로 재확인.

**거래량 매매법 유튜브 영상 3편을 바탕으로 신규 전략을 직접 설계해 전략 라이브러리에 등록 (2026-07-16,
같은 날 후속 요청)**. 사용자가 거래량 분석 유튜브 영상 3편(①②"업주와 자주 덤" 채널의 거래량 기초/
응용 2부작 — 장대양봉+거래량 급증 매집 포착 → 눌림목에서 거래량 급감 확인(매물소화) → 지지선 유지
확인 후 재상승, ③ICT 스타일 채널의 "거래량 매매 3법칙" — 다이버전스/꼬리캔들+거래량/모멘텀 돌파)
자막 전문을 붙여넣고 "이 세 영상을 바탕으로 거래량 매매법을 직접 고안해서 DB에 넣어봐, 전략이
무엇인지 설명도 해야 돼"라고 요청 → AI 해석기(nl_strategy)를 거치지 않고 세 영상의 논리를 직접
분석해 1:2:6 단계별 전략을 설계하고, 필요한 신규 지표까지 만들어 전략 라이브러리(#14)에 등록함.

- **신규 지표 2종 추가** (`core/indicators.py`): 기존 지표 중 "거래량 자체의 급증/감소"를 재는
  지표가 없어(볼린저/RSI/MACD/캔들패턴 전부 가격 기반) 새로 만들었음.
  - `compute_volume_ratio(df, period=20)`: 당일 거래량 ÷ 직전 period일(당일 제외, shift(1)) 평균
    거래량 — "몇 배 터졌는지"(매집/급등 포착용). 당일 거래량이 자기 자신의 평균 계산에 섞이면
    배수가 과소평가되므로 반드시 shift(1) 후 rolling.
  - `compute_volume_dryup_ratio(df, lookback=10)`: 당일 거래량 ÷ 직전 lookback일(당일 제외) 중
    최고 거래량 — 1.0에 가까우면 아직 급등 국면 거래량 수준, 0에 가까우면 그 이후 거래대금이
    말라붙었음(눌림목 매물소화 포착용).
  - `core/strategy_engine.py`에 `_eval_volume_spike`(`volume_spike`, level 조건: ratio>=mult)/
    `_eval_volume_dryup`(`volume_dryup`, level 조건: ratio<=ratio) 평가자 + `INDICATOR_EVALUATORS`
    등록 + `describe_condition()` 한국어 문구 추가("거래량이 20일 평균 대비 2배 이상 급증" 등).
- **전략 설계**(1:2:6 단계별, 기존 마루보즈/핀바/볼린저/RSI/RSI크로스/ma_touch 지표 그대로 재사용,
  새 지표는 거래량 부분만): 진입 1단계(10%, 매집 포착) = 거래량 20일평균 2배 급증 + 장대양봉
  (마루보즈) + RSI<70(뒷북 진입 방지) / 진입 2단계(20%, 눌림목 매물소화) = 거래량이 최근 10일 고점
  대비 40% 이하로 감소 + 종가가 20일선(볼린저 중심선) 위 유지 / 진입 3단계(60%, 재상승 확인) = RSI
  50 상향 돌파 OR 강세 핀바. 청산 1단계(10%) = RSI 70 이상 과매수 / 청산 2단계(20%) = 약세 핀바 +
  거래량 급증(매도세 물량 정리, ③번 영상의 "꼬리+거래량" 개념) / 청산 3단계(60%, 잔량 전부) = 20일선
  하향 이탈(크로스언더). `stop_loss: {source: lowest_low, period: 20}`으로 진입 시점 최근 20일
  저가를 손절 레벨로 고정(①②번 영상이 경고한 "거래량 감소가 매집이 아니라 개미를 꼬시는 속임수일
  수도 있다"는 리스크에 대응).
- **설계 중 실제로 발견하고 고친 결함**: 청산 3단계를 처음엔 "20일선 아래"(레벨 조건, `bollinger`
  band=mid+break_below)로 뒀더니, `diagnose_strategy_health`가 AAPL 5년 데이터에서 매매 89건 중
  45건이 진입 당일 바로 청산되는 자기모순을 실측으로 잡아냈다 — 원인 분석 결과, 진입 3단계 신호
  (RSI 50 상향 돌파/강세 핀바)는 정의상 "아직 20일선 회복 전(20일선 아래에서의 반등 시작점)"에도
  흔히 발생하는데, 청산 3단계가 "20일선 아래"라는 상태(level)를 그대로 청산 조건으로 쓰다 보니 진입
  즉시 청산되는 경우가 절반 가까이 나온 것. `ma_touch`(크로스언더 **이벤트** — 직전 봉은 반드시
  20일선 위였어야 함)로 교체해 해결(같은 AAPL 데이터로 재검증 시 경고 0건, 5개 종목 실측에서도
  same-day 트레이드가 51~120건 중 0~1건으로 사실상 소멸).
- **실증 검증**: 실제 야후파이낸스 데이터로 AAPL/TSLA/NVDA/MSFT/AMD(2018~2026) 백테스트 — 승률
  40~48%, 매매 51~120건. TSLA는 전략이 매수보유·S&P500 매수보유를 모두 이김(CAGR 20.3% vs
  16.5%/12.8%). AAPL·NVDA는 그 종목 자체의 폭발적 매수보유 상승률에는 못 미쳤지만(강한 단일방향
  상승장에서는 매수보유가 당연히 유리) S&P500 매수보유는 이김 — 과장 없이 그대로 기록.
- **DB 등록**: `data/quant.db`(실제 운영 DB)에 `Strategy(id=14, name="거래량 매집-눌림목 반등
  전략", source="youtube_script")`로 직접 저장. description에는 세 영상의 근거/3단계 진입·청산
  로직/리스크 관리/설계 중 발견한 결함과 수정/실증 검증 결과까지 전부 한국어로 서술(AI 자동생성이
  아니라 직접 작성 — nl_strategy의 일반적 해석 흐름과 달리 영상 맥락을 아는 이번 세션이 직접 종합해야
  하는 창작 작업이었음).
- 검증: `tests/test_strategy_engine.py`에 신규 테스트 7개 추가(거래량 비율/드라이업 비율 계산 정확성,
  당일 거래량이 자기 평균에 안 섞이는지, 각 조건 평가자의 참/거짓 판정, 한국어 문구 생성).
  `pytest tests/ -q` 전체 440개 통과. Streamlit `AppTest`로 실제 운영 DB에 대해 '전략 관리'/
  '백테스팅' 페이지가 신규 전략과 함께 예외 없이 로드되고 개요 표에 정상 노출됨을 라이브로 확인.

**밸류에이션 도구: 피어 비교 자동 선정 + 조회 결과 캐싱 + 방법론별 카드에 용어 설명 툴팁 추가
(2026-07-16, 같은 날 후속 요청)**. 사용자가 "피어 비교할 때 자동으로 2개 선정해줘, 매번 호출하면
느리니 캐시하거나 규칙기반으로 해달라"고 요청, 이어서 "방법론별 추정 주당가치 표의 용어들이 어려우니
각 용어 오른쪽 위에 물음표 아이콘을 달고 커서 올리면 3줄 정도 설명이 뜨게 해달라"고 추가 요청.

- **캐싱**: `core/valuation.py::fetch_valuation_inputs()`가 매번 yfinance `.info`(느린 네트워크
  왕복)를 타던 것을, `core.screener.get_fundamentals()`와 동일한 파일 캐시 패턴(파일 mtime 기반
  TTL 6시간, `data/cache/valuation_inputs_{ticker}.json`)으로 감쌌다. 실제 조회 로직은
  `_fetch_valuation_inputs_uncached()`로 이름만 바꿔 유지. `use_cache=False`/`cache_ttl` 인자로
  테스트/강제 재조회 가능.
- **자동 피어 선정**: `select_auto_peers(ticker, n=2)` 신규 — AI 미사용, 순수 규칙 기반. 대상
  종목의 섹터는 `core.screener.get_universe()`(24시간 캐시, 위키피디아 GICS 섹터 표기)에서
  Symbol로 조회하고, 같은 섹터 후보(상한 20개) 각각의 시가총액을 `get_fundamentals()`(종목당 6시간
  캐시)로 가져와 대상과 시가총액 차이가 가장 작은 n개를 고른다. 시총 데이터가 전혀 없으면 섹터 내
  처음 n개로 폴백. **개발 중 발견한 버그**: 처음엔 대상 섹터를 yfinance `.info`의 `sector`
  필드("Technology")로 가져왔는데, 위키피디아 GICS 표기("Information Technology")와 문자열이
  달라 실제 라이브 테스트(AAPL)에서 후보가 0개로 나옴 — 대상 종목이 유니버스(S&P500)에 있으면
  유니버스의 GICS 표기를 우선 쓰도록 고쳐서 해결(유니버스 밖 티커만 yfinance sector로 폴백, 이
  경우 표기가 안 맞아 후보가 안 잡힐 수 있는 한계는 문서화하고 범위 밖으로 명시).
- **UI** (`app/pages/6_밸류에이션.py`): "피어 비교" 탭이 페이지 로드 시 `job_manager`로
  `select_auto_peers(ticker)`를 자동 실행해 입력창 기본값으로 채운다. 작업이 막 끝난 그 rerun에서만
  `job_manager.render()`가 Job을 반환하는 특성을 이용해 그 타이밍에 딱 한 번만 기본값을 채우고,
  이후 재실행마다 사용자가 직접 수정한 값을 덮어쓰지 않도록 티커별 플래그(`peer_auto_applied_{ticker}`)로
  기록. 여전히 직접 수정 가능(자동 선정은 출발점일 뿐).
- **용어 툴팁**: "방법론별 추정 주당가치" 표를 `st.dataframe` 대신 `st.metric` 카드 그리드(3열)로
  교체 — Streamlit이 `help=` 인자에 자동으로 물음표 아이콘 + 호버 툴팁을 붙여주는 기존 패턴(섹터
  리더 페이지에서 이미 쓰던 방식)을 그대로 재사용. DCF/DDM/PER·PBR 상대가치/EV·EBITDA/그레이엄
  넘버 6개 + PEG 비율까지 총 7개 방법론에 각각 3줄 안팎 한국어 설명을 `_METHOD_HELP`/`_PEG_HELP`
  딕셔너리로 작성(값/현재가 대비/산출 불가 표시는 기존과 동일하게 유지, 표시 방식만 표→카드로 변경).
- 검증: `tests/test_valuation.py`에 신규 테스트 8개(캐시 히트/미스/TTL 만료, `use_cache=False`
  우회, 같은 섹터 내 시총 최근접 선정, 섹터 정보 없을 때 빈 리스트, 시총 정보 전혀 없을 때 폴백)
  추가 — 실제 프로젝트 `data/cache` 디렉터리를 오염시키지 않도록 `tmp_path`로 격리하는 autouse
  fixture를 테스트 파일에 신설. `python -m pytest tests/ -q` 전체 457개 통과. 8511~8513 포트에
  별도 테스트 인스턴스를 띄워 playwright로 라이브 검증: AAPL 기준 자동 피어로 AVGO/AMD가 선정되고
  비교 테이블이 정상 렌더링됨, 방법론 카드의 물음표 아이콘에 커서를 올리면 DCF 설명 툴팁이 실제
  텍스트로 뜸을 `stTooltipContent` 요소에서 직접 확인 — 매번 정식 8501 포트는 건드리지 않고 종료.

**포트폴리오 관리에 "매매근거" 슬롯 + 사후 검증(회고) 기능 추가 (2026-07-16, 같은 날 후속 요청)**.
사용자가 "매매근거를 입력하는 슬롯을 추가해서 왜 그 매매를 선택했는지 기입하게 하고, 나중에 이
전략/논리구조가 맞았는지 검증할 수 있는 구조를 만들어달라"고 요청, "UI/UX를 고려해서 만들어봐"라고
설계 재량도 함께 위임 — `core/threads_summary.py`의 "주간 인사이트 리포트 사후 검증(회고)" 기능과
동일한 설계 원칙(과거 서술 원문 + 그 시점 가격을 스냅샷해두고, 시간이 지난 뒤 AI가 실제로 맞았는지
되짚어봄)을 그대로 재사용해 구현.

- **DB** (`core/models.py`): `PortfolioHolding`에 `thesis`(Text, nullable) 컬럼 추가. 신규 테이블
  `PortfolioThesisReview`(holding_id, ticker, thesis_snapshot, review_text, purchase_price,
  price_at_review, price_change_pct, elapsed_days, created_at) — 리포트 피드백처럼 단일 컬럼
  덮어쓰기가 아니라 **이력을 계속 쌓는 별도 테이블**로 설계함(매매근거는 한 달 뒤/분기 뒤 등 여러
  번 재검증하고 싶을 수 있어서). `thesis_snapshot`으로 검증 시점의 매매근거 원문을 통째로 복사해둬,
  이후 사용자가 thesis를 고쳐 써도 과거 검증 기록의 맥락이 깨지지 않게 함.
- **`core/portfolio.py`**: `add_holding`/`update_holding`에 `thesis` 파라미터 추가(`update_holding`은
  빈 문자열을 명시적 삭제로 취급, `None`은 미변경). `get_holding(holding_id)` 신규(단건 조회).
  `THESIS_REVIEW_SYSTEM_PROMPT` — "논리 요약 → 실제와의 부합 여부 → 어긋난 부분 → 다음에 참고할
  점" 4단 구조로 회고하도록 지시(리포트 피드백 프롬프트와 같은 뼈대, 매매근거에 맞게 재작성).
  `generate_thesis_review(holding_id)`가 매입가/현재가/경과일을 계산해 AI 호출(키 없음/실패 시
  `_fallback_thesis_review`로 정량 비교만 표시, 예외 안 던짐 — 기존 관례), thesis가 비어있으면
  ValueError로 먼저 입력하라고 안내. `save_thesis_review`/`list_thesis_reviews`로 이력 저장/조회.
- **UI** (`app/pages/8_포트폴리오_관리.py`): ①보유 종목 추가 폼에 "매매근거 (선택)" textarea 추가.
  ②손익 표 아래 새 섹션 "📝 매매근거 & 검증" — 보유 종목마다 expander(제목에 📝/◻️ 뱃지로 매매근거
  유무 표시 + 매입일 + 손익%를 한눈에), 안에 매매근거 편집(저장 버튼) + "🔍 매매근거 검증" 버튼 +
  검증 이력(최신순, 각각 매입가→검증시점가/변화율/경과일 + 그 시점 매매근거 스냅샷 + 회고 전문).
  손익표(pnl_df)와 보유목록(holdings)을 인덱스로 매칭(`get_portfolio_pnl()`이 내부에서 다시
  `list_holdings()`를 호출해 정렬 순서가 같음을 이용 — pnl_df 자체엔 holding id가 없어 id 매칭은
  불가능함을 주석으로 명시).
- **기존 DB 마이그레이션 필요**: 이전에도 여러 번 겪은 패턴대로 `init_db()`의 `create_all()`은 이미
  있는 `portfolio_holdings` 테이블에 새 컬럼을 안 만들어줘서, `data/quant.db`에 수동으로
  `ALTER TABLE portfolio_holdings ADD COLUMN thesis TEXT` 실행 후 `init_db()`로
  `portfolio_thesis_reviews`(신규 테이블이라 create_all로 자동 생성됨) 확인.
- 검증: `tests/test_portfolio.py`에 신규 테스트 12개(매매근거 저장/조회/삭제, 검증 함수의 키
  없음/API 실패/가격조회 실패 각각의 폴백, 이력 저장·조회, thesis 수정 후에도 과거 스냅샷 불변)
  추가 — `python -m pytest tests/ -q` 전체 468개 통과. 8514 포트에 별도 테스트 인스턴스를 띄워
  playwright로 실제 AAPL 보유 종목을 매매근거와 함께 추가 → 저장 확인 → 검증 실행까지 라이브 확인.
  검증 도중 Gemini API가 일시적으로 503(과부하)을 반환해 AI 회고 대신 폴백(정량 비교) 텍스트가
  뜨는 것까지 실제로 확인함(코드 결함이 아니라 기존에도 있던 API 장애 대응 경로가 정상 동작한
  것). 테스트에 사용한 AAPL 보유 종목/검증 이력은 실제 운영 DB에서 정리해 원상복구.

**경기 사이클 국면 추정 섹션 정보량 대폭 확충 (2026-07-16, 같은 날 후속 요청)**. 사용자가 "경기
사이클 국면 추정 섹션이 정보량도 그렇고 너무 빈약하다, 이 페이지의 생성 목적을 스스로 판단하고
인터넷을 서칭해 좋은 전략을 스스로 짜서 추가하라"고 요청 — 실제로 기존 섹션은 국면 배지 1줄 +
설명 1줄 + 섹터 목록 + expander 안 캡션 2줄이 전부였고 차트가 하나도 없었음(다른 탭들과 비교해도
확연히 빈약). 확인 질문 없이 리서치부터 바로 진행(WebSearch):

- **리서치로 확보한 근거**:
  1. 장단기 금리차(10Y-2Y) 역전은 뉴욕 연준 리서치 기준 1955년 이후 모든 미국 침체에 선행했고,
     평균 약 15개월(6~24개월 범위) 뒤 침체로 이어짐 — 대표적인 "선행지표".
  2. 시카고 연은 전국활동지수(CFNAI, FRED 무료 제공)는 85개 월별 지표를 가중평균한 종합 활동지수로,
     시카고 연은이 직접 제시하는 명확한 임계값(CFNAI-MA3 < -0.70 침체위험, > +0.20 확장가능성,
     > +0.70 과열/인플레 압력)이 있어 자체 방법론을 새로 고안하지 않고 그대로 채택 가능.
  3. Merrill Lynch Investment Clock(성장갭×인플레이션 2축, reflation/recovery/overheat/stagflation)이
     가장 널리 알려진 자산배분 프레임워크지만 이 모듈의 4국면(GDP 추세×모멘텀만 사용, 인플레이션
     축 없음)과 축 자체가 달라 1:1로 대응시키지 않고, 여러 경기순환 투자 자료에 공통되는 "국면별
     자산군 성향"만 일반화해 참고용으로 추가(확정 규칙 아님을 명시).
- **`core/macro_cycle.py` 추가**: `interpret_yield_curve(spread)`(역전 여부 + 선행성 설명),
  `classify_cfnai(cfnai_ma3)`(시카고 연은 공식 임계값 그대로 사용), `ASSET_CLASS_NOTES`(국면별
  자산군 성향 참고 노트), `compute_historical_quadrants(gdp_growth, lookback_quarters=12)`(과거
  각 분기 시점까지의 데이터만으로 같은 로직을 재계산 — look-ahead bias 없는 역사적 판정 이력 표용).
- **`core/fred_data.py`**: `DEFAULT_INDICATORS`에 `CFNAI` 추가(경제지표 탭에도 자동 노출).
- **UI** (`app/pages/7_매크로_대시보드.py` 경기 사이클 탭 전면 확충):
  - 국면 배지/설명/섹터 아래 자산군 성향 캡션, 장단기 금리차 역전 시 경고 배너 추가.
  - "판정 근거 신호 4가지": GDP 사분면(주 판정)/Sahm Rule(침체 확인)/장단기 금리차(선행)/
    CFNAI-MA3(종합 활동지수) 4개를 `st.metric` + `help=` 툴팁 카드로 나열(기존엔 expander 안
    캡션 2줄뿐이었음 — 신호가 2개에서 4개로 늘고 전부 카드+툴팁으로 가시화됨).
  - "지표 추이" 2x2 차트 그리드 신규(기존엔 차트 0개였음): GDP YoY vs 추세, 실업률 3개월평균 vs
    Sahm 임계선, 장단기 금리차 vs 역전 기준선(0), CFNAI-MA3 vs 3단계 임계선.
  - "최근 분기별 판정 이력" 표 신규 — 과거 12분기 각각의 GDP/추세/모멘텀/판정국면을 보여줘 "지금
    국면"만 던져주던 것에서 판정의 시계열 맥락까지 보이도록 개선.
  - 국면별 섹터 로테이션 참고표에 "자산군 성향(참고)" 컬럼 추가.
- 검증: `tests/test_macro_cycle.py`에 신규 테스트 15개(금리차 역전/정상/None, CFNAI 4단계 신호
  분류 + 경계값, 역사적 사분면 계산의 look-ahead 없음·데이터부족 처리) 추가 — `python -m pytest
  tests/ -q` 전체 480개 통과. 8515 포트에 별도 테스트 인스턴스를 띄워 실제 FRED_API_KEY로 라이브
  확인: 4개 신호 카드/4개 차트/역사적 판정 이력 표(2023~2025 분기별 회복→확장→둔화→수축 전환)까지
  전부 실제 데이터로 정상 렌더링됨을 스크린샷으로 확인 후 테스트 서버 종료.

## 🔴 진행 중 (2026-07-16 세션, 중단됨 — "진행중인거 마저 해줘"라고 하면 아래부터 이어갈 것)

사용자가 토큰 리셋(2시간) 때문에 세션을 잠시 멈춰달라고 요청 — 아래 두 작업이 미완성 상태로
남아있다. **커밋된 건 하나도 없다** (이 세션 전체가 아직 미커밋 — `git status`로 항상 먼저 확인).

### 작업 1: 가격+거래량 결합 전략 국면별 튜닝 (백그라운드에서 계속 진행 중, 확인만 하면 됨)

사용자 요청: 전략 #3("볼린저 밴드 하단 반전 1:2:6", 가격전용) + 전략 #14("거래량 매집-눌림목
반등", 거래량+가격)을 결합해 두 정보(가격/거래량)를 모두 쓰는 최적 전략을 찾되, 아래 "작업 0"에서
만든 약세장/강세장 분리 튜닝 엔진으로 각각 따로 학습한 뒤 결합할 것.

- **스크립트**: `/workspaces/Quant/.tuning_runs/combine_price_volume/run.py` (재개 가능하게 설계 —
  `units/` 아래 (base_strategy_id, style_type, regime) 조합 24개를 단위로 체크포인트, 이미 끝난
  단위는 자동 스킵). `watch.sh`가 죽으면 자동 재시도하며 감싸고 있음.
  **반드시 `/workspaces` 아래(영구 디스크)에 둘 것 — `/tmp`는 컨테이너 재시작 시 사라질 수 있어
  처음에 거기 뒀다가 다시 만들었음(교훈: 이 프로젝트에서 장시간 백그라운드 산출물은 절대 `/tmp`에
  두지 말 것).**
- **현재 상태 확인 방법**:
  ```bash
  ps aux | grep -E "watch.sh|run.py" | grep -v grep   # 아직 살아있는지
  tail -30 /workspaces/Quant/.tuning_runs/combine_price_volume/run.log   # 진행 상황 (n/24)
  ls /workspaces/Quant/.tuning_runs/combine_price_volume/units/ | wc -l  # 끝난 단위 개수
  cat /workspaces/Quant/.tuning_runs/combine_price_volume/final.json 2>/dev/null  # 다 끝나면 여기 최종 결과
  ```
  이 세션이 멈춘 시점(2026-07-16 11:12 KST경) 기준 4/24 완료, 5번째 단위(#3/경기민감주/약세장,
  10종목) 진행 중이었음. 종목 수가 많은 그룹(특히 "경기민감주" 10종목)은 단위 하나에 10분+ 걸릴 수
  있어 24개 전부 끝나려면 코드스페이스를 여러 번에 걸쳐 켜야 할 가능성이 높음.
- **프로세스가 죽어있으면 재시작**: `cd /workspaces/Quant/.tuning_runs/combine_price_volume &&
  nohup ./watch.sh > watch.stdout.log 2>&1 & disown` (이미 끝난 단위는 자동으로 건너뜀).
- **24개 단위가 다 끝나면 할 일** (`run.py`가 자동으로 하지만 안 됐으면 수동 확인): 국면별로 가장
  성과 좋은 스타일 그룹의 #3/#14 튜닝 결과를 `{"combine": "AND", "strategies": [...]}`로 결합해
  test 구간 재평가 후 전략 라이브러리에 "가격+거래량 결합 전략 (약세장/강세장 학습)" 이름으로 저장
  — 이미 저장된 이름이면 중복 저장 스킵하도록 되어 있음. 저장되면 **사용자에게 결과(초과수익/
  승률/채택된 파라미터)를 직접 요약해 보고할 것** — 그냥 저장만 하고 끝내지 말 것.

### 작업 2: 야간 미세튜닝을 GitHub Actions로도 돌아가게 만들기 (사용자 승인, 코드는 다 짰지만 검증/커밋/시크릿 설정 안 됨)

배경: 사용자가 "야간 튜닝이 로컬 스케줄러가 떠 있어야만 도는데, 그럼 Streamlit Cloud 배포본에서는
왜 안 되냐"는 질문 끝에, GitHub Actions cron으로 매일 밤 튜닝을 돌리고 결과를 저장소에 커밋해두면
로컬 스케줄러 없이도(그리고 Streamlit Cloud 배포본에서도) 결과가 보이게 하자는 방향을 사용자가
직접 제안했고 "이 방법을 써봐"로 승인함. 저장소는 `sternjeong/Quant`, **퍼블릭**이라 Actions 분당
비용 걱정 없음(무제한) — 확인 완료.

**만들어둔 파일 (아직 미커밋, 로컬에만 존재)**:
- `scripts/nightly_tuning_ci.py` — `scheduler/run_scheduler.py::strategy_nightly_tuning_job()`과
  같은 반복 튜닝 로직을, GitHub Actions의 휘발성 환경에 맞게 각색(KST 벽시계 컷오프 대신 고정
  예산(분)만큼 반복, 끝나면 `data/nightly_tuning_leaderboard.json`에 기존 결과와 합쳐 상위 50개만
  저장 — 이 JSON 파일 자체가 "누적 이력" 역할).
- `.github/workflows/nightly_tuning.yml` — 매일 15:05 UTC(≈00:05 KST) cron + 수동 실행
  (workflow_dispatch) 지원. `GEMINI_API_KEYS` 시크릿을 env로 주입하고, 끝나면 결과 JSON을
  `github-actions[bot]` 이름으로 커밋+푸시.
- `app/pages/13_야간_미세튜닝_리더보드.py` 수정 — 로컬 DB 결과 + 이 JSON 파일 결과를 합쳐서
  (출처 컬럼으로 구분) 상위 10개를 보여주도록 변경 완료.
- `.gitignore`에 `.tuning_runs/`(작업 1의 임시 산출물 디렉터리) 추가.

**아직 안 한 것 (재개 시 순서대로)**:
1. `scripts/nightly_tuning_ci.py` 전체 흐름(main()) 스모크 테스트 — 작은 예산/작은 종목 수로 실제
   실행해 `data/nightly_tuning_leaderboard.json`이 의도한 형태로 만들어지는지 끝까지 확인 안 됨
   (마지막 시도가 타임아웃으로 중단됨, `_merge_and_truncate`/`_load_existing_leaderboard` 로직
   자체는 단위 테스트로 이미 검증됨). 검증 후 테스트로 만든 가짜 JSON 파일은 지울 것(실제 파일이
   아니므로 커밋 금지).
2. 스모크 테스트 통과하면 3개 파일(`scripts/nightly_tuning_ci.py`,
   `.github/workflows/nightly_tuning.yml`, 리더보드 페이지, `.gitignore`) git add + commit.
3. `git push`.
4. `gh secret set GEMINI_API_KEYS` 로 `.env`의 값을 저장소 시크릿으로 등록 — **사용자 API 키를
   다루는 단계라 진행 전에 사용자에게 한 번 더 명확히 알릴 것** (이미 "이 방법을 써봐"로 큰 방향은
   승인받았지만, 실제로 키를 업로드하는 순간은 투명하게 알리기).
5. `gh workflow run nightly_tuning.yml -f budget_minutes=10` 같은 식으로 짧은 예산으로 수동
   트리거해 실제 GitHub Actions 위에서 끝까지 성공하는지 확인(특히 `git push` 권한 —
   `permissions: contents: write`가 잘 먹히는지) 후, 문제없으면 사용자에게 보고.

## 🟡 백로그 (2026-07-17 세션에서 논의, 순차 착수 예정)

사용자가 "가격+거래량 결합 전략" 튜닝 중간 결과(초과수익 대부분 마이너스)를 보고 "S&P500에 남아있는
종목은 이미 지난 5년간 폭등한 생존자들이라 buy&hold가 유리한 게 당연하고, 그렇다면 트레이딩 알고리즘
고도화보다 종목 발굴에 힘써야 하는 것 아니냐"는 통찰을 제시함. 이어서 "학습 데이터셋(현재 S&P500
생존 종목)과 실전에서 마주할 데이터(미래에 어떤 종목이 살아남을지 모름) 사이의 이질성" 문제를 지적,
9분 이상 웹 리서치 후 아래 우선순위로 합의:

1. **point-in-time 종목 유니버스 반영** (생존자 편향 완화, 비용 0) — 지금 `sample_universe()`가
   "현재 시점 S&P500"만 쓰는데, 학습 시작 시점 기준 과거 실제 편입 종목 리스트로 바꿔야 함.
   무료 소스: [GitHub `fja05680/sp500`](https://github.com/fja05680/sp500)의
   `S&P 500 Historical Components & Changes.csv`(1996년부터 날짜별 편입/편출, Wikipedia 변경
   이력 기반). 이걸로 편출은 됐지만 상장폐지는 안 된 종목(GE, 인텔 등)까지는 표본에 포함 가능.
   **한계**: 상장폐지까지 간 종목의 실제 가격 데이터는 yfinance에 아예 없어 완전 해결은 안 됨
   (Shumway 1997 델리스팅 편향 — 학계에서는 부도 델리스팅 수익률을 -55%로 보정해서 쓰지만, 이
   프로젝트에서 그대로 적용은 오버킬일 수 있어 "한계로 인지하고 보수적으로 해석" 수준까지만).
2. **다종목 미세튜닝에 여러 시대(era) walk-forward 검증 추가** — 특정 초강세장 종목군에만
   과적합된 게 아닌지 확인하기 위해, 2000년대 IT버블 전후·2008년 금융위기 편입군 등 다른 시대
   종목 세트로도 교차 검증하는 걸 튜닝 파이프라인 옵션으로 추가.
3. **종목 발굴(스크리닝) 기능 신규 구현** — 트레이딩 타이밍 최적화보다 "애초에 잘 오를 종목을
   고르는" 방향. 아직 설계 전, 착수 전 상의 필요(신규 애매한 기능이라 [[feedback_quant_workflow]]
   원칙대로 md 문서에 논의 정리 후 진행).

착수 순서는 1 → 2 → 3. 진행 상황은 이 섹션을 갱신하며 기록할 것. 상세 리서치 근거(출처 링크)는 이
세션의 대화 기록 참고 — 필요시 STRATEGY_TUNING_ENGINE_SPEC.md에 정식 절로 옮겨 기록.

**1번 point-in-time 유니버스 — 코드 구현 완료 (2026-07-17, 같은 세션, 커밋 전)**:
- `data/sp500_historical_constituents.csv` 신규 추가 — `fja05680/sp500`의 1996~2019 히스토리
  CSV(`S&P 500 Historical Components & Changes.csv`) + `sp500_changes_since_2019.csv`(편입/편출
  이벤트)를 병합해 2026-06-30까지 커버하도록 로컬에서 직접 이어붙임(원본 저장소 히스토리 CSV
  자체는 2019-01-11에서 멈춰 있어 그대로 쓰면 최근 6년은 여전히 "현재 시점" 취급이 됨 — 반드시
  이 병합 로직으로 최신까지 이어붙인 버전을 써야 함).
- `core/point_in_time_universe.py` 신규 — `get_constituents_as_of(as_of_date)`가 그 시점 실제
  S&P500 편입종목 리스트를 반환(티커 표기는 `core/screener.py`와 동일하게 `.`→`-` 정규화).
- `core/strategy_tuning.py::sample_universe()`에 `as_of_date` 파라미터 추가(기본값 None=기존
  동작 그대로, 하위호환) — 주어지면 현재 유니버스 대신 그 시점 point-in-time 종목만 후보로 삼고,
  현재 유니버스에 없는(=편출된) 종목은 섹터 "Unknown"으로 포함. `run_and_save_tuning()`에도
  `universe_as_of_date` 파라미터로 관통시켜둠(수동 `tickers_df` 지정 시엔 무시).
- 검증: `tests/test_point_in_time_universe.py` 신규 6개(1996년 vs 2020년 종목 리스트가 실제로
  다름을 직접 증명 — AMZN/FB가 1996년 리스트엔 없고 2020년엔 있음 등), `tests/test_strategy_tuning.py`
  신규 1개(`as_of_date` 주면 후보가 제한되고 편출 종목은 Unknown 섹터로 남는지) 추가. 전체
  `python -m pytest tests/ -q` 499개 통과 확인.
- **UI 연결 완료 (2026-07-17, 이어서)**: "다종목 미세튜닝" 탭(자동 표본 모드에서만, 수동 선택
  모드는 애초에 종목을 직접 고르므로 해당 없음)에 "🕰️ 생존자 편향 방지: 시작일 기준 실제 S&P500
  편입종목만 표본으로 사용" 체크박스 추가 — 체크 시 `tuning_start_date` 기준
  `universe_as_of_date`를 `run_and_save_tuning()`에 전달. 기본값 unchecked(하위호환, 기존과 동일).
- **남은 한계**: 상장폐지까지 간 종목은 yfinance에 가격 데이터가 없어 여전히 표본에서 빠짐(구조적
  한계, 완전 해결 안 됨).

**2번(다중 시대 walk-forward 검증) — 코드 구현 완료 (2026-07-17, 같은 세션, 커밋 전)**. 사용자가
"앞으로 뭘 물어보지 말고 네 판단대로 설계/구현하라"고 명시적으로 전권 위임(이 세션부터 새 기능도
상의 없이 바로 구현 — [[feedback_quant_workflow]] 갱신함, 기존 "애매한 신규 기능은 먼저 상의" 원칙
폐기).
- `core/era_validation.py` 신규 — `MARKET_ERAS`(닷컴버블 붕괴/금융위기/코로나 충격+회복/2022
  금리인상 약세장/2010년대 중반 횡보 구간, 5개 시대 하드코딩)와 `validate_across_eras(config,
  tickers, eras=MARKET_ERAS) -> dict`. 이미 튜닝된 config를 재튜닝 없이 각 시대의 point-in-time
  유니버스(그 시대엔 존재하지 않았던 종목은 스킵)로 재검증해, 시대별 평균 초과수익/승률과
  `era_robustness_score`(초과수익이 양수였던 시대 비율)를 반환. `core.strategy_tuning`과 얽지
  않는 독립 모듈(현재 다종목 미세튜닝 파이프라인에서 자동으로 호출되진 않음 — 검증하고 싶은 config를
  수동으로 넘겨 쓰는 별도 도구).
- 검증: `tests/test_era_validation.py` 3개(point-in-time 유니버스에 없는 종목 스킵, robustness
  score 계산, 한 종목 백테스트 예외가 해당 시대 전체를 죽이지 않음). 전체 `pytest tests/` 통과.
- **UI 연결 완료 (2026-07-17, 이어서)**: 튜닝 결과 화면에서 종목 선택 시 "🌍 {티커} 시대별 강건성
  재검증" expander 추가 — 버튼을 누르면 `job_manager`(기존 튜닝 실행과 동일한 비동기 패턴)로
  `era_validation.validate_across_eras(tuned_config, [ticker])`를 실행하고, 시대 강건성 점수 +
  시대별 평균초과수익/승률 표를 보여준다. 재튜닝은 하지 않고(이미 튜닝된 config 그대로) 5개
  시대에 적용만 해보는 것이라는 점을 caption으로 명시.
- **AppTest로 라이브 검증**: `app/pages/1_백테스팅.py` 전체를 Streamlit `AppTest`로 구동해 신규
  체크박스/expander 포함 예외 없이 로드됨을 확인. 전체 `pytest tests/ -q` 508개 통과.

**3번(종목 발굴 스크리닝 기능) — 신규 구현 완료 (2026-07-17, 같은 세션, 커밋 전)**.
- `core/stock_discovery.py` 신규 — `discover_candidates(universe_n=None, weights=DEFAULT_WEIGHTS,
  sector_filter=None, top_n=30, use_cache=True, as_of_date=None) -> pd.DataFrame`. 모멘텀(IBD
  스타일 가중 ROC)/성장(earningsGrowth)/가치(PER·PBR·PEG 저평가일수록 고득점)/퀄리티(FCF 수익률+
  현금·부채 비율) 4팩터를 유니버스 내 percentile로 환산 후 가중합(기본 0.30/0.30/0.25/0.15,
  근거는 모듈 docstring 참고)해 상위 종목을 뽑는다. `core.strategy_tuning`(타이밍 최적화)과는
  완전히 분리된 독립 모듈 — "어떤 종목을 살지" 문제를 다룬다. `as_of_date`로
  `core.point_in_time_universe`와 부가적으로 연동 가능(완전한 백테스트 가능 발굴은 향후 확장).
- UI: `app/pages/14_종목_발굴.py` 신규 — 섹터 필터/상위 N개/가중치 슬라이더 + 실행 버튼 + 결과 표
  + "스코어링 방법론" expander.
- 검증: `tests/test_stock_discovery.py` 6개(합성 유니버스로 점수 순위 정합성, 섹터 필터, top_n,
  결측 데이터 종목이 전체를 깨지 않음, 가중치 변경이 실제로 순위를 바꿈). 전체 `pytest tests/ -q`
  508개 통과.
- **아직 안 한 것**: DB 영구 저장/이력 추적 없음(스크리닝 결과를 매번 재계산만 함 — 스냅샷 저장은
  향후 확장 과제로 모듈 docstring에 남겨둠). 실제 브라우저로 Streamlit 페이지를 띄워 라이브
  검증은 아직 안 함(문법 파싱만 확인).

### 작업 3 (완료·검증됨): 매크로 대시보드 시장 국면에 "심층 리스크 신호" 3종 추가

사용자가 "S&P500 역사적 국면 타임라인(이미 있었음, 확인해보니 기존 4신호 종합점수 기반으로 이미
구현돼 있었음) 이거나, 매크로 대시보드에서 시장국면/섹터 강도를 더 엄밀하게 판단할 수 있는 정보를
제시해달라 — 인터넷 서치를 8분 이상 해서 신뢰도 높은 출처에서 얻은 정보를 반영하라"고 요청. 8회
웹서치(CBOE 공식 VIX 정의, FRED BAMLH0A0HYM2 관련 신용시장 해설 다수, NYSE 시장폭/Zweig Breadth
Thrust, 뉴욕 연은 공식 10Y-3M 침체확률 모형 논문, 하이일드 스프레드 임계값 등)로 근거 확보 후:
- `core/market_regime.py`에 `score_vix`/`score_credit_spread`/`score_yield_curve_3m`/
  `get_advisory_risk_signals()` 신규 추가 — **기존 4신호 종합 점수(total_score)와
  `classify_daily_regime`(국면별 분리 트레이닝용 일별 라벨링)는 전혀 건드리지 않고** 완전히 별도
  경로로 참고용 신호만 계산(회귀 위험 최소화, `short_term`과 같은 기존 패턴 재사용).
  - VIX(`^VIX`, yfinance, 키 불필요): CBOE 공식 정의(S&P500 옵션 내재변동성) 기준 15/20/25/30
    관행 임계값으로 -25~+10점.
  - 하이일드 신용스프레드(FRED `BAMLH0A0HYM2`, ICE BofA US High Yield OAS): 300/500/800/1000bp
    임계값으로 -25~+10점 + 20거래일 변화량(bp)도 함께 표시. FRED_API_KEY 없으면 None.
  - 10Y-3M 금리차(FRED `T10Y3M`): 뉴욕 연은 공식 침체확률 모형이 실제로 쓰는 스프레드(10Y-2Y보다
    신뢰도 높다는 연구 근거로 채택) — 역전(음수)이면 -20점(침체 선행경보), 0~0.5%p는 평탄화
    주의(-5점), 그 이상은 정상(+5점).
- `app/pages/7_매크로_대시보드.py` "시장 국면" 탭에 "🔬 심층 리스크 신호(참고용, 종합 점수에는
  미반영)" 섹션 추가 — 3개 메트릭 + 각 신호의 출처(CBOE/FRED/뉴욕연은) 링크와 근거를 캡션/help
  텍스트에 명시. (최초엔 `job_manager.ensure`로 구현했다가, 바로 아래 후속 작업에서 동기 호출로
  교체함 — 이유는 후속 항목 참고.)
- 검증: `tests/test_market_regime.py`에 단위테스트 13개 추가(밴드 경계값, %→bp 환산, FRED 키
  유무에 따른 분기, 20일 변화량 계산 등) — 전체 pytest 492개 통과. Streamlit `AppTest`로 페이지를
  실제 라이브 실행해(FRED_API_KEY 설정된 환경) VIX 16.7(평상)/하이일드 스프레드 271bp(복부감)/
  10Y-3M +0.73%p(정상) 등 3개 신호가 실제 시장 데이터로 정상 렌더링됨을 확인.
- 참고: 사용자가 언급한 "S&P500 역사적 국면 타임라인"(배경 음영 차트)은 이미 이전 세션에서
  구현·배포돼 있었음(`historical_regime_segments` + `add_regime_shading`, 같은 탭 안에 이미 존재)
  — 신규 구현 없이 확인만 하고, 이번 요청의 초점은 "더 엄밀한 판단 정보"(두 번째 옵션)로 판단해
  그쪽에 집중함.

### 작업 3-1 (완료·검증됨): 타임라인 조회 기간을 1년/3년/5년/사용자 정의로 선택 가능하게 변경

사용자가 "S&P500 역사적 국면 타임라인 1년/3년/5년/사용자 정의 기간 설정으로 바꿔줘"라고 후속 요청.
- `app/pages/7_매크로_대시보드.py`의 타임라인 섹션에 `st.radio("조회 기간", ["1년","3년","5년",
  "사용자 정의"], key="market_regime_timeline_period")` 추가(기본 3년, 기존과 동일 동작 유지).
  "사용자 정의" 선택 시 `st.date_input` 2개(시작일/종료일)가 나타남 — 전부
  `st.session_state.setdefault(...)` 선반영 + `key=`만 넘기는 기존 프로젝트 관례를 따름(`index=`나
  `value=`를 동시에 안 씀). 시작일≥종료일이면 경고만 표시하고 조회 생략.
- **버그를 하나 찾아 고침 (내가 만든 버그)**: 이 섹션 바로 아래 "심층 리스크 신호" 3종(작업 3에서
  추가)이 매 rerun마다 무조건 `job_manager.ensure(...)+render(...)`를 호출하고 있었는데,
  `job_manager.render()`는 완료된 잡을 반환하는 즉시 그 추적을 세션에서 지워버린다
  (`core/job_manager.py::render()` 참고) — 그래서 그 다음 rerun의 `ensure()`는 매번 "추적 없음"으로
  보고 새 잡을 처음부터 다시 시작했다. VIX/FRED 조회 자체는 가벼워도(디스크 캐시 있음), 잡이
  "실행 중" 상태인 동안 `render()`가 `time.sleep(); st.rerun()`을 반복 호출해 사용자의 다른 위젯
  조작(방금 만든 라디오 포함)이 그 rerun 폭주 사이에서 씹히는 것을 실측으로 확인함(라디오가
  화면상으론 클릭한 값으로 보이는데 실제 계산에 반영된 값은 계속 이전 값). 해결: 심층 리스크
  신호를 job_manager 없이 동기 호출(`get_advisory_risk_signals()` 직접 호출, try/except로 감쌈)로
  변경 — 무거운 계산이 아니라 백그라운드 스레드가 애초에 불필요했음.
  - **일반화 가능한 교훈**: `job_manager.ensure()`를 "매 rerun마다 무조건" 호출하는 패턴은, 그
    job의 결과를 DB/세션에 영속 캐싱해 "오늘 이미 계산했으면 스킵"하는 식의 별도 staleness 가드가
    없으면(예: `market_regime_snapshot`이 쓰는 `is_snapshot_stale_for_today_kst()` 패턴) 매번
    새로 재시작된다 — 무겁고 가끔만 필요한 계산에만 job_manager를 쓰고, 가벼운 조회는 동기 호출이
    낫다.
  - **디버깅 중 발견한 별개의 환경 제약**: 이 버그를 잡은 뒤에도 여전히 헤드리스 playwright로는
    `st.tabs()`의 "기본 활성 탭이 아닌 탭"(2번째/3번째 탭) 안의 위젯 클릭이 세션 상태에 반영되지
    않는 현상이 남아 있었음 — 최소 재현으로 확인: 탭 밖/1번째(기본) 탭의 라디오는 클릭이 정상
    반영되는데, 2번째·3번째 탭(둘 다 이번 세션에서 손대지 않은 기존 위젯 포함, 예: 기존 "🔄 지금
    다시 계산" 버튼)은 클릭해도 값이 절대 안 바뀜(여러 방식으로 재확인: text 클릭/force 클릭/키보드
    Space). 반면 완전히 별도의 미니 Streamlit 앱에서는 탭 순서와 무관하게 항상 정상 동작함 → 이
    특정 컨테이너의 헤드리스 chromium+react-aria 조합에서 "초기 로드 시 숨겨져 있던 탭 패널"의
    위젯 press 이벤트가 제대로 붙지 않는 것으로 보이는 환경 한계로 결론 — **내가 이번에 만든
    코드의 버그가 아님**(똑같은 증상이 손대지 않은 기존 버튼에서도 재현됨). 실제 사용자의 일반
    브라우저 환경에서도 동일하게 재현되는지는 확인 못 했음 — 다음에 이 페이지의 2/3번째 탭 위젯을
    playwright로 검증할 일이 있으면 이 한계를 먼저 의심하고, 필요하면 실제 사용자에게 직접 확인을
    요청할 것.
- 검증: 디버그용 임시 위젯/캡션은 전부 제거 확인(`grep DEBUG` 결과 없음). `python -m py_compile`
  통과, `pytest tests/ -q` 508개 통과, Streamlit `AppTest`로 예외 없이 로드되고 라디오가 기본값
  "3년"으로 정상 렌더링됨을 확인. 브라우저에서는 페이지 최초 로드 시(3번째 탭을 명시적으로 클릭한
  직후 첫 렌더) 라디오/차트/심층 리스크 신호 섹션이 실제 라이브 데이터로 정상 렌더링되는 것까지는
  스크린샷으로 확인했으나, 위 환경 한계로 "탭 안에서 라디오를 클릭해 기간이 실제로 바뀌는 상호작용"
  자체는 자동화 브라우저로 끝까지 확인하지 못함 — 날짜 계산 로직 자체는 순수 함수 수준에서
  수동 검증함(1년/3년/5년 각각 올바른 시작일 계산 확인).

### 작업 3 완료 후 미커밋 상태

이 세션의 다른 작업들(작업 0/1/2/3/3-1)과 함께 아직 전체가 미커밋 상태 — 사용자가 커밋을
  요청하면 진행.

### 작업 0 (이미 완료·검증됨, 참고용): S&P500 기준 약세장/강세장 분리 트레이닝

이번 세션 앞부분에서 완료: `core/market_regime.py`에 `classify_daily_regime`/`find_regime_segments`/
`historical_regime_segments` 신설, `core/strategy_tuning.py`의 워크포워드 튜닝이 국면별로 완전히
분리된 config 2개(약세장용/강세장용)를 만들도록 확장, `StrategyTuningResult`에 `trained_regime`/
`insufficient_regime_data`/`regime_matched_test` 컬럼 추가(로컬 `data/quant.db`에 수동 ALTER TABLE
까지 이미 적용함). 설계 근거는 `STRATEGY_TUNING_ENGINE_SPEC.md` 13절. `pytest tests/ -q` 434개
통과 확인함(이후 다른 세션들이 병행 작업하며 파일들을 더 건드려 지금은 480개). **이것도 아직
미커밋** — 작업 1/2와 함께 나중에 한 번에 커밋할지, 따로 커밋할지 사용자에게 확인 필요.

### 작업 4 (2026-07-17, 사용자 정정 반영 — 완료): test 평가를 국면 일치 구간만으로 + 라이브 선택기 신설

사용자가 작업 0의 설계를 정정: "약세장의 전략을 강세장에서 테스트할 필요는 없다 — 결국 두 개의
전략을 만들어야 하고, 그 후엔 지금이 어느 국면인지 판단해서 둘 중 하나를 골라 알고리즘 매매를
하려는 것"이라고 명확히 함. 반영 완료 사항(`STRATEGY_TUNING_ENGINE_SPEC.md` 13.6/13.9절, 자세한
배경은 memory `feedback_regime_tuning_methodology`):

1. **`core/strategy_tuning.py::tune_strategy_for_group`**: regime이 지정되면 `group_mean_excess_
   return`/`group_win_ratio`/`per_ticker_test_comparison`이 이제 test 구간 전체가 아니라 **국면
   일치 구간에서만** 평가한 값이다(예전엔 이게 보조 지표 `regime_matched_test`로만 있었음 — 이제
   주 지표 자리를 차지). escape hatch 트리거 판단도 이 기준으로 바뀜. 국면 일치 구간이 test 안에
   없으면 `group_mean_excess_return=None`("검증 불가", 조용히 다른 데이터로 대체 안 함).
2. **`core/market_regime.py::select_regime_for_trading(snapshot=None)` 신설** — 지금이 약세장/
   강세장 중 어느 쪽인지 확정(중립/혼조는 total_score 부호로 소프트 판단 + `is_ambiguous=True`).
3. **`core/strategy_tuning.py::select_live_strategy(bear_strategy_id, bull_strategy_id)` 신설** —
   위 판단에 따라 전략 라이브러리에서 해당 전략을 골라 config와 함께 반환. 종목 배정/실제 매매
   실행(관심종목 모니터링 연동)은 다음 단계 — 아직 안 함.
4. **테스트**: `tests/test_strategy_tuning.py`/`tests/test_market_regime.py`에 신규 테스트 다수
   (국면 일치 구간만 평가되는지 실제로 다른 값을 주는 mock으로 구분해서 검증, 매칭 구간 없으면
   None, select_regime_for_trading의 중립 소프트판단/스냅샷 없음 처리, select_live_strategy의
   약세장/강세장 선택·전략 없음 처리). `pytest tests/ -q` 519개 전체 통과.
5. **재튜닝 불필요, 재선택만**: 이미 실행 중이던 `combine_price_volume` 백그라운드 잡(작업 1)은
   국면별 train 폴드 분리는 원래부터 맞게 하고 있었고, 보조 지표로 계산해두던 `regime_matched_test`
   가 바로 이번에 주 지표가 된 값이라 이미 저장돼 있었음 — 그래서 `.tuning_runs/combine_price_
   volume/finalize_corrected.py`(신규)로 기존 체크포인트(units/*.json)만 다시 읽어 "국면 일치
   구간 초과수익" 기준으로 스타일을 재선정하도록 함(재튜닝 없음).
6. **중요 발견(정직하게 기록)**: 현재 튜닝 구간(10년, 75/25 분리 → test=최근 2.5년, 대략
   2024-01~2026-07)에는 **약세장 구간이 test 안에 하나도 없음**
   (`historical_regime_segments('2024-01-16','2026-07-16')`로 실측 확인, 강세장 구간만 3개).
   즉 지금 설정으로는 약세장용 결합 전략을 out-of-sample로 검증할 방법이 없다(강세장 쪽은
   검증 가능 — 성장주 스타일이 #3 초과수익 17.41%p, #14 초과수익 5.99%p, 2024-01-16~2025-03-07
   구간). **다음 세션에서 결정 필요**: (a) 전체 lookback을 더 늘려 test 구간에 약세장이 포함되게
   split 자체를 조정할지, (b) train/test 비율을 낮춰(예: 60/40) test 구간을 넓힐지, (c) 검증은
   못 하더라도 학습된 약세장 config 자체는 (train 구간엔 2022년 약세장이 포함돼 있어 학습은
   정상적으로 됨) 참고용으로 라이브러리에 저장해둘지 — 사용자에게 확인 후 진행할 것.
7. **백그라운드 잡 상태**: `.tuning_runs/combine_price_volume/`의 24개 단위(2개 전략 × 6스타일 ×
   2국면) 중 진행 중(세션 중단 시점마다 재개해가며 진행) — `run.log`로 진행률 확인,
   `finalize_corrected.py`는 몇 개가 끝났든 그 시점까지 유효한 것만으로 미리 계산 가능(전부
   끝나야만 의미 있는 건 아님, 다만 #14 그룹이 다 끝나야 완전한 비교가 됨).

### 작업 5 (2026-07-17, 사용자 재정정 — 진행 중): S&P500 지수 국면 대신 종목 자체 추세로 데이터셋 분리

작업 4에서 보고한 "test 구간에 지수 차원 약세장이 없어 검증 불가" 문제에 대해, 사용자가 결정 옵션
(a/b/c)을 고르는 대신 **더 근본적인 대안**을 제시: S&P500 지수의 날짜별 국면이 아니라 **종목
자체가 표본기간 동안 상승/하락/횡보 중 어느 흐름이었는지**로 데이터셋을 나누고, 실전에서는 임의의
티커가 세 케이스 중 어디인지 판단해 전략을 고르게 해달라는 요청. 반영 완료(`STRATEGY_TUNING_
ENGINE_SPEC.md` 14절, memory `feedback_regime_tuning_methodology`에 배경 추가):

1. **`core/strategy_tuning.py` 신규 함수 4개**:
   - `classify_ticker_trend(df)` — 절대 CAGR 임계값(±10%)으로 종목 1개를 상승/하락/횡보 분류
     (라이브 판단용).
   - `_ticker_cagr(df)` — 순수 CAGR 계산(위 함수에서 분리).
   - `classify_tickers_by_trend(tickers, start, end)` — **학습 데이터셋 구성용**. 처음엔 위
     절대 임계값을 그대로 배치 적용할 계획이었으나, 실제 10년치 40종목 표본으로 돌려보니
     CAGR<=-10%(하락) 종목이 **0개**였다(S&P500 현재 구성종목만 쓰면 생존편향 때문에 다년
     마이너스 CAGR 종목이 실질적으로 없음 — 성과 나쁜 종목은 지수에서 이미 빠져있으므로). 그래서
     절대 임계값 대신 **표본 내 CAGR 상대 순위(3분위)**로 재설계 — 하위 1/3="하락", 상위
     1/3="상승", 중간="횡보". 실측 재검증: 40종목 표본에서 13/14/13으로 세 그룹이 고르게 채워짐
     (수정 전이었다면 "하락" 그룹이 0개로 비어서 애초에 불가능했을 것).
   - `select_strategy_for_ticker_trend(ticker, bear_id, bull_id, sideways_id, lookback_days=182)`
     — 라이브 선택기. 종목 자체의 최근 ~6개월 가격 흐름(짧은 구간이라 생존편향 문제 없어 절대
     임계값 그대로 사용)을 보고 세 전략 중 하나를 골라준다. 학습(수년, 상대순위)과 라이브 판단
     (단기, 절대임계값)이 서로 다른 분류 방식을 쓰는 것은 의도된 설계(SPEC 14.2절에 근거 기록).
2. **튜닝 방식**: 13절 인프라(`tune_strategy_for_group`)를 전혀 안 건드리고 `regime=None`(기존
   레거시 경로 — 달력 등분 워크포워드 + test 구간 전체 평가)에 종목 목록만 다르게 넘겨 재사용.
   날짜가 아니라 종목을 필터링하므로 "그 국면 데이터가 test에 없음" 문제가 구조적으로 발생 안 함.
3. **테스트**: 신규 유닛테스트 9개 (CAGR 절대분류 라이브용/상대순위 학습용 둘 다, 생존편향
   시뮬레이션 데이터로 절대 CAGR이 전부 플러스여도 상대적으로 세 그룹이 갈라지는지 검증, 유효
   종목 3개 미만이면 전부 횡보 처리, 라이브 선택기 정상/실패 케이스). `pytest tests/ -q` 527개
   통과.
4. **백그라운드 잡**: `.tuning_runs/combine_price_volume_trend/`(신규, 구 버전
   `combine_price_volume/`은 그대로 두되 더 이상 이번 목적에는 안 씀) — 40종목 표본, 10년,
   intensity=정밀, 국면 2×스타일 6=24단위였던 구 버전과 달리 이번엔 **추세 3종 × 전략
   2개 = 6단위뿐**이라 훨씬 빠르게 끝날 것으로 예상. 재개 가능한 체크포인트 설계는 동일
   (`units/*.json`, `watch.sh` 자동 재시도). 진행 상황은 `run.log`, 다 끝나면 `final.json` +
   전략 라이브러리에 "가격+거래량 결합 전략 (하락/상승/횡보장 학습, 종목추세기준)" 3개 자동 저장.
5. **다음 세션에서 할 일**: `.tuning_runs/combine_price_volume_trend/run.log`에서 "=== 전체
   완료 ===" 확인 → 안 됐으면 `cd .tuning_runs/combine_price_volume_trend && nohup ./watch.sh
   > watch.stdout.log 2>&1 & disown`로 재개 → 다 끝나면 `final.json`과 전략 라이브러리 저장
   결과를 사용자에게 보고(초과수익/승률/실제 채택된 파라미터 요약, 저장만 하고 끝내지 말 것).

### 작업 6 (2026-07-17): Oracle Cloud 무료 VM 상시 배포 가이드 + systemd 서비스 준비

사용자가 "Codespace 꺼져도 엔진이 돌아가게" 하고 싶다고 해서 딥서치로 무료 상시 호스팅/DB 옵션을
비교(Railway/Render/Fly.io는 2026년 기준 사실상 유료화, Vercel은 서버리스라 상시 프로세스 자체가
불가능 — Oracle Cloud "Always Free" ARM VM만 진짜 영구 무료). 사용자가 "Oracle 무료 VM + 로컬
SQLite" 조합으로 진행 결정(관리형 DB로 옮길 만큼 데이터 규모가 크지 않음 — 500종목×10년 일봉 ≈
100~200MB).

계정 가입·VM 발급·SSH 접속은 에이전트가 대신 할 수 없는 단계라, 리포에 실행 가능한 산출물만 준비:
- `deploy/DEPLOYMENT_ORACLE.md` — VM 발급(Ampere A1.Flex, 2026-06-15부로 Always Free 한도가
  4 OCPU/24GB→2 OCPU/12GB로 축소된 점 주의) → VCN Security List에 8501 포트 인그레스 규칙 추가
  (OS 방화벽만 열어선 안 됨) → SSH 접속 → `.env` 준비 → `setup_vm.sh` 실행 → 확인 → 코드 업데이트
  배포 절차 → GitHub Actions 야간튜닝과의 관계(VM 로컬 DB와 리포 커밋 JSON을 리더보드 페이지가
  이미 합쳐서 보여줌, 코드 확인해서 정확히 기술) → 백업 순서로 단계별 정리.
- `deploy/quant-streamlit.service`, `deploy/quant-scheduler.service` — systemd 유닛(전용
  `quant` 시스템 계정으로 실행, 죽으면 자동 재시작, 부팅 시 자동 시작).
- `deploy/setup_vm.sh` — 패키지 설치/venv/의존성/systemd 등록/ufw 방화벽까지 한 번에 처리하는
  멱등 부트스트랩 스크립트(재실행해도 안전하게 설계).

**다음 세션에서 할 일**: 사용자가 실제로 VM을 발급하고 이 가이드를 따라가며 막히는 지점이 있으면
디버깅 지원. `core/notify.py`의 데스크톱 알림은 headless 환경에서 이미 콘솔 출력으로 안전하게
폴백하도록 돼 있어 별도 수정 불필요함을 확인함(관심종목 스캔 알림이 VM에선 콘솔/로그로만 남는다는
점을 사용자에게 안내할 것).

### 작업 7 (2026-07-21): 코스톨라니 달걀 이론 국면 (신규, 부가 기능)

사용자가 "코스톨라니 달걀 이론을 검색해서, 전체 시장과 각 섹터(ETF 참고)가 어느 국면인지 알려주는
서비스를 추가해달라"고 요청 → 웹 검색으로 이론의 6국면(A1 저점조정→A2 상승→A3 버블/과열→B1
고점조정시작→B2 하락→B3 패닉/급락, 거래량·투자자 수 증감이 핵심 축)을 먼저 확인한 뒤, 이 앱은
"투자자 수" 심리 데이터가 없다는 제약을 사용자에게 알리고 AskUserQuestion으로 3가지(판정 로직/UI
배치/섹터 범위) 확인 후 진행:

- **판정 로직**: `core/kostolany_cycle.py`(신규) — 52주 고점/저점 대비 가격 위치(zone: 저점권≤30%/
  중간/고점권≥70%) × ROC(20거래일) 추세 방향 × 거래량(20일/60일 평균 비율≥1.2배="증가") 3축
  조합의 결정론적 룰로 6국면을 근사. 예: 저점권+급락(|ROC|≥15%)+거래량급증=B3(패닉),
  저점권+완만한하락+저거래량=A1(저점조정), 고점권+상승+거래량급증=A3(버블) 등.
- **범위**: 전체 시장(S&P500, `core.market_regime`과 동일 벤치마크)과 `core.sector_strength.
  THEME_UNIVERSE`(GICS 11개 표준 섹터 + 반도체/우주/방산 등 세부 테마 19개 전체, 신규 ETF 목록
  관리 불필요하게 기존 재사용).
- **UI**: 새 독립 페이지 `app/pages/16_코스톨라니_달걀_이론.py` — 시장 국면 카드 + 섹터별 국면을
  가로 바 차트(52주 위치 x축, 국면별 색상)와 표로 표시. `core.market_regime`/`core.sector_strength`와
  동일한 스냅샷 패턴(job_manager 백그라운드 계산 + DB 저장 + 자정 이후 첫 방문 자동 갱신 + "지금
  다시 계산" 버튼) 재사용.
- **DB**: `models.py`에 `KostolanyCycleSnapshot` 추가, `scheduler/run_scheduler.py`의
  `market_snapshot_job()`에 계산 호출 통합(기존 시장국면/섹터강도와 같은 배치에서 함께 갱신).
- **검증**: 유닛테스트 17개(`tests/test_kostolany_cycle.py`, 위치/거래량비/6국면 분기 전부 커버,
  DB 라운드트립은 `tests/conftest.py`의 `db_session` fixture 패턴 재사용) + Streamlit `AppTest`로
  실제 라이브 yfinance 데이터 end-to-end 확인(당시 S&P500=B1·52주위치88%, 로보틱스/원자력=A1,
  금융/헬스케어/부동산=A2로 계산됨 — 실행 시점에 따라 값은 달라짐). 전체 pytest 스위트 557개 통과.
- 공식 경기판단이 아닌 참고용 경험칙임을 페이지 상단 캡션에 명시(기존 시장국면/섹터강도 페이지와
  같은 원칙).

### 작업 8 (2026-07-21, 같은 날 후속 요청): 코스톨라니 페이지 UI를 바 차트 → 상태별 칸반 보드로 교체

사용자가 "바 차트 말고 더 UX 친화적으로 구성해봐, 깊게 생각해"라고 요청 → `dataviz` 스킬 로드 후
재검토: 국면(A1~B3)은 크기 비교가 필요한 magnitude가 아니라 "지금 뭘 해야 하는가"를 뜻하는
상태(status)에 가깝다고 판단해 폼을 바꿈(스킬의 "status는 카테고리 색이 아니라 상태 팔레트로,
good/neutral/critical 3톤" 원칙 적용).
- `core/kostolany_cycle.py`에 `PHASE_STATUS`(6국면 → buy/hold/sell 3그룹)와 `STATUS_LABELS`/
  `STATUS_ORDER` 추가 — 코스톨라니의 핵심 조언(저거래량 조정·패닉=A1/B3에서 사고, 고거래량
  과열·고점조정=A3/B1에서 팔라)을 그대로 그룹 기준으로 사용.
- `app/pages/16_코스톨라니_달걀_이론.py`: 막대그래프를 없애고 **🟢매수 관심 / ⚪보유·관망 /
  🔴매도 검토** 3열 칸반 보드로 교체. 각 열 안에서 테마를 카드로 나열(색은 상태를 뜻하는 좌측
  보더에만 사용, 텍스트는 항상 잉크색 유지 — 스킬의 "텍스트는 계열색을 입지 않는다" 원칙), 매수
  열은 52주 위치가 낮을수록/매도 열은 높을수록 상단에 오도록 정렬해 "확신이 강한 신호"부터 보이게
  함. 시장 국면 카드에도 같은 3색 상태 배지를 추가해 위(시장)/아래(섹터) 시각 언어를 통일. 새 색은
  만들지 않고 `core/theme.py`가 이미 쓰는 상태색 3톤(#4caf82/#8a8a8a/#e5533d)을 재사용해 다른
  페이지와 일관성 유지. 정렬/검색이 필요한 사용자를 위해 기존 표는 접이식 expander로 보존(스킬의
  "테이블 뷰는 항상 존재해야 한다" 원칙).
- 검증: 기존 유닛테스트 17개 전부 통과(로직 무변경), Streamlit `AppTest`로 실제 라이브 데이터
  렌더링 확인(카드 HTML 구조/상태 배지 정상 출력). 전체 pytest 562개 통과.

### 작업 9 (2026-07-21, 같은 날 후속 요청): 코스톨라니 페이지에 스윙/장기 스타일 슬롯 추가

사용자가 "내 니드에 맞게 스윙/장기 전략에 맞게 띄워주는 슬롯도 만들어달라"고 요청. (참고: 이 사이의
어느 시점에 다른 세션/사용자가 `7_매크로_대시보드.py`+`16_코스톨라니_달걀_이론.py`+
`12_섹터_리더_성장주.py`를 `7_시장_진단.py` 하나로 통합했음 — 코스톨라니 섹션은 `_render_kostolany()`
함수로 그대로 보존되어 있어 그 위에서 작업.)

- `core/kostolany_cycle.py`: 기존 `PHASE_STATUS`(장기 투자 기준, 코스톨라니 원전 조언 그대로)는
  유지하고 `SWING_PHASE_STATUS`(스윙 기준 — "확인된 모멘텀을 단기로 타는" 관점) 신설. 둘의 차이는
  A1/A2에서만 발생: 장기는 A1(저점권, 아직 하락 진정 단계)을 매수로 보지만 스윙은 반등이 확인되지
  않았다고 보고 관망으로, 반대로 A2(거래량 동반 확인된 상승)는 장기엔 그냥 보유지만 스윙엔 지금 타야
  할 매수 신호. A3/B1(과열·고점이탈)은 두 스타일 모두 매도로 일치. `STYLE_PHASE_STATUS`/
  `STYLE_PHASE_GUIDANCE`/`STYLE_LABELS`/`STYLE_ORDER` 딕셔너리로 스타일별 분기를 한 곳에 모음.
- `app/pages/7_시장_진단.py`의 `_render_kostolany()`: 6국면 요약표 위에 "🐢 장기 투자 / ⚡ 스윙
  트레이딩" `st.segmented_control` 슬롯 추가(`kostolany_style` 세션 상태로 유지). 선택에 따라
  시장 국면 배지, 섹터 칸반 보드 3그룹(매수/보유/매도) 재분류, 표 보기의 가이드 문구가 전부
  실시간으로 바뀐다.
- 검증: 신규 유닛테스트 4개(스타일별 전체 국면 커버, A3/B1 두 스타일 일치, A1/A2 스타일 간 반대
  분류 확인, 가이드 문구 존재) + `pytest tests/test_kostolany_cycle.py` 21개 통과. Streamlit
  `AppTest`로 실제 라이브 데이터에서 세그먼트 전환 시 그룹 개수가 이론대로 바뀌는지 직접 확인
  (당시 데이터 기준 장기=[매수2,보유17,매도1] → 스윙=[매수9,보유10,매도1], A2 9개 테마가 보유에서
  매수로 이동). 전체 pytest 스위트 566개 통과.

### 작업 10 (2026-07-21, 같은 날 후속 요청): 야간 자동 미세튜닝에도 스윙 보유기간 제약 적용

사용자가 "이건(스윙/장기 구분) 백테스팅/미세튜닝/야간 자동 미세튜닝에도 적용되는거지? 안되면
적용시켜줘"라고 질문. 조사 결과:
- **이미 돼 있던 것**: `core/backtest_engine.py`/`core/strategy_tuning.py`의 `max_holding_days`
  (스윙 보유기간 상한, SPEC 15절) — 수동 튜닝(`app/pages/1_전략_스튜디오.py`)의 "🏄 스윙 트레이딩
  모드" 체크박스로 이미 연결되어 있었음(15.6절, 이전 세션에서 완료).
- **안 돼 있던 것**: 자동으로 매일 밤 도는 두 야간 배치(`scheduler/run_scheduler.py::
  strategy_nightly_tuning_job()`, `scripts/nightly_tuning_ci.py`)는 `max_holding_days`를 아예
  넘기지 않아 여태 보유기간 제약 없이 튜닝되고 있었음(SPEC 15.7절에 "사용자 확인 필요"로 남아있던
  항목).
- 참고로 방금 전에 추가한 코스톨라니 페이지의 "🐢 장기/⚡ 스윙" 슬롯은 완전히 별개 기능(시장 국면을
  스타일별로 다르게 해석하는 표시 전용) — 백테스팅/튜닝 파라미터와는 무관함을 확인.

사용자가 스스로를 스윙 트레이더로 확정(SPEC 15.1절)한 전제 + "적용시켜달라"는 명시적 요청에 따라
두 야간 배치 모두 매 반복 `max_holding_days=strategy_tuning._SWING_MAX_HOLDING_DAYS`(126거래일)를
항상 넘기도록 수정. 기존에 제약 없이 쌓인 이력은 그대로 두고 `max_holding_days`/"스윙모드" 컬럼으로
신구 구분 가능. 수동 UI 체크박스 기본값(미체크)은 그대로 둬 필요시 장기 제약 없는 탐색도 가능하게
유지. `STRATEGY_TUNING_ENGINE_SPEC.md`에 15.8절로 기록. 전체 pytest 566개 통과(로직 변경 없이
호출부 인자만 추가라 신규 유닛테스트는 기존 `test_run_and_save_tuning_threads_and_persists_max_
holding_days`가 이미 커버).

### 작업 11 (2026-07-21, 같은 날 후속 요청): 야간 CI 배치가 사흘 연속 결과를 통째로 날린 버그 수정

사용자가 "🌙 리더보드 4.2일 전" 배지를 보고 이유를 물어 조사 → `nightly_tuning.yml`이
2026-07-17~19 사흘 연속 GitHub Actions 하드 타임아웃(350분)으로 `cancelled` 종료된 것을 확인.
`scripts/nightly_tuning_ci.py`가 모든 반복이 끝난 뒤 딱 한 번만 리더보드를 커밋하는 구조라, 강제
종료 시점엔 커밋을 한 번도 못 해 그날 밤 계산 전체가 유실됐던 게 원인(리더보드가 07-17 이후
3.65일간 정체). 사용자가 "오라클 VM 없이 GitHub Actions만으로 해결해달라"고 명시 요청.

- `scripts/nightly_tuning_ci.py`를 반복마다 즉시 `git commit`+`git push`하도록 재작성(`_run_git`/
  `_commit_and_push`/`_save_and_push_leaderboard` 신규). 푸시 거절 시 fetch+rebase 1회 재시도,
  실패해도 다음 반복에서 계속 시도. 이제 잡이 언제 죽든 유실 구간이 "하룻밤 전체"에서 "죽는 순간
  진행 중이던 반복 1개"로 축소됨.
- `.github/workflows/nightly_tuning.yml`: 예산 300분→270분(타임리밋 350분 대비 여유 80분으로
  확대), 기존 "마지막 커밋" 스텝은 폴백으로 유지하되 `if: always()` 추가.
- 검증: `tests/test_nightly_tuning_ci.py` 신규 9개(merge/커밋/재시도/실패 케이스 전부 subprocess
  monkeypatch로 커버) + 전체 pytest 575개 통과. STRATEGY_TUNING_ENGINE_SPEC.md 16절에 기록.
- 실제 야간 실행에서 문제없이 도는지는 다음 스케줄(오늘 밤 00:05 KST)에서 확인 필요 — 다음 세션
  시작 시 `gh run list --workflow=nightly_tuning.yml --limit 3`으로 결과 확인할 것.

### 작업 12 (2026-07-21, 같은 날 후속): 오라클 VM capacity 확보 자동 재시도 — GitHub Actions 전환 대기 중

도쿄 리전(ap-tokyo-1) A1.Flex가 계속 "Out of host capacity"로 즉시 생성 실패. `deploy/
oracle_capacity_retry.sh`(로컬 반복 시도, capacity 에러/429 rate-limit은 건너뛰고 계속 재시도)를
만들어 컨테이너 안에서 백그라운드로 돌리는 중이었으나, 사용자가 "컴퓨터를 꺼도 계속 시도되게"
요청 → 로컬/Codespace 백그라운드 프로세스는 Codespace가 idle timeout으로 꺼지면 같이 죽으므로
불충분. **GitHub Actions cron 워크플로**(`.github/workflows/oracle_capacity_retry.yml`, 10분마다
1회 시도, repo variable `ORACLE_VM_READY=true` 되면 자동 중단)로 전환하기로 결정.

**막힌 지점 (다음 세션에서 바로 이어서 할 일):** 워크플로가 필요한 7개 GitHub repo secrets를
이 세션의 GITHUB_TOKEN 권한 부족(403)으로 내가 직접 등록 못 함 → 사용자가 GitHub 웹 UI
(https://github.com/sternjeong/Quant/settings/secrets/actions)에서 수동 등록해야 함:
비민감 6개(`OCI_USER_OCID`, `OCI_FINGERPRINT`, `OCI_TENANCY_OCID`, `OCI_REGION`, `OCI_IMAGE_ID`,
`OCI_SUBNET_ID`, `OCI_AVAILABILITY_DOMAINS` — 도쿄 리전 값들, 세부 값은 대화 이력 또는 `oci` CLI로
재조회 가능) + 민감 2개(`OCI_API_KEY_PEM` ← `~/.oci/oci_api_key.pem` 전체 내용, `ORACLE_SSH_
PUBLIC_KEY` ← `~/.ssh/id_ed25519.pub` 내용). 사용자가 "내일 하겠다"며 보류.

**다음 세션에서 사용자가 "이어서 하자"고 하면:** 1) secrets 7개 등록 완료했는지 먼저 확인 2) 등록
안 됐으면 위 등록 절차(웹 UI 경로 + 값 목록)를 다시 안내 3) 등록 완료했으면 워크플로 커밋/푸시 →
`gh workflow run oracle_capacity_retry.yml`로 수동 트리거해서 정상 동작 확인 → 이후 10분 간격
자동 재시도로 방치. `deploy/oracle_capacity_retry.sh` 로컬 버전은 참고용으로 남겨두되 GH Actions가
주력.

### 작업 13 (2026-07-25): 백테스팅 엔진에 Masters의 4대 전략 검증 테스트 추가

사용자가 유튜브 영상(Timothy Masters의 《Testing and Tuning Market Trading Systems》 소개 + 실전
적용 사례)을 공유하며 그 안의 4가지 검증 기법(민감도/순열/분해/벤치마크 비교)을 백테스팅 엔진에
추가해달라고 요청. "새 기능 도입 전 논의" 원칙은 2026-07-17에 "묻지 말고 판단해서 구현하라"로
상위 대체된 상태([[feedback-quant-workflow]])라, AskUserQuestion으로 방향(구현 vs 논의만 vs 보류)만
한 번 확인한 뒤 바로 설계·구현.

- `core/backtest_engine.py`에 기존 `run_backtest`의 포지션 계산 로직을 `_simulate_on_raw(raw, df,
  indicator_config, max_holding_days)`로 추출(순수 리팩터링, 동작 변화 없음 — 기존 15개 테스트로
  회귀 확인 후 진행). 순열검정이 실제 데이터 대신 가짜(raw)를 넣어 같은 파이프라인을 재사용하도록
  하기 위함.
- **테스트 1 (민감도)** `run_sensitivity_sweep(ticker, variants, start, end, metric="sharpe")`:
  파라미터 값별로 미리 만든 전략 설정 목록(variants)을 순서대로 백테스팅해 이웃 값 간 결과 변화폭을
  측정. 특정 변수 값 하나에서만 결과가 튀면(전체 값 범위의 50% 넘는 단일 점프) `is_robust=False`로
  과최적화 의심 신호. 파라미터 값→설정 변환 방법은 스키마마다 달라(단순 조건/1:2:6 staged/자연어
  표현식) 호출부가 만들어 넘기게 설계(엔진은 실행/평가만 담당, `core/strategy_tuning.py`의 기존
  그리드 생성 함수들과 조합 가능).
- **테스트 2 (순열)** `run_permutation_test(ticker, indicator_config, start, end,
  n_permutations=200)`: 신규 `_shuffle_daily_bars()`가 일봉의 '전일 종가 대비 시가/고가/저가/종가/
  거래량 비율(그 날의 캔들 모양)'은 보존한 채 날짜 등장 순서만 무작위로 섞어 가짜 시계열을 생성
  (변동성/드리프트는 실제와 동일, 추세·자기상관만 제거). 지표 warmup 구간은 실제 데이터 그대로 두고
  백테스트 구간만 섞은 뒤 `_simulate_on_raw`로 동일 파이프라인 재실행 — 실제 결과가 순열 분포 대비
  p-value/백분위로 어디에 위치하는지 반환. numpy cumprod로 완전히 벡터화해 순열 1회당 비용을
  최소화했다(파이썬 루프 없음).
- **테스트 3 (분해)** `run_partition_test(strategy_run, benchmark_run, bias_log_return=0.0)`: 총
  로그수익률 = 추세(노출 비율 × 벤치마크 총수익률) + 실력(나머지) + 편향으로 분해. 편향(과최적화로
  인한 인플레이션)은 단일 백테스트로 추정 불가능해 이 함수는 계산하지 않고 호출부가 표본외 검증 등
  으로 구한 값을 넘기면 반영하는 구조(기본 0 = 영상처럼 "최적화 안 했으니 bias 없음" 전제).
- **테스트 4 (벤치마크 비교)** `summarize_strategy_vs_benchmarks(comparison, regime_breakdown=None)`:
  기존 `compare_with_benchmarks`/`compute_regime_breakdown` 결과를 원수익률 하나가 아니라 CAGR/MDD/
  샤프 4축 전부에서 승패로 구조화 — "원수익률은 졌지만 방어력·위험조정수익률은 이겼다" 같은 판단을
  호출부(향후 UI)가 그대로 문구로 보여줄 수 있게 함.
- 검증: `tests/test_backtest_engine.py`에 신규 유닛테스트 9개 추가(민감도 포인트/견고성 판정,
  순열 셔플이 날짜는 보존하고 값만 바꾸는지 + 종가 비율 집합이 순서만 바뀐 채 보존되는지, 순열검정
  시드 고정 시 재현성, 분해 테스트의 total=trend+skill+bias 항등식과 무노출 시 0이 되는 경계 케이스,
  벤치마크 비교 승패 플래그) — 전체 599개 pytest 통과(리팩터링 포함 회귀 없음). 추가로 실제 AAPL
  2022~2024 데이터로 4개 함수 전부 라이브 스모크 테스트(민감도 스윕이 RSI<25처럼 거래가 거의 없는
  극단값에서 과최적화로 정상 표시, 순열검정 p-value 0.03대, 분해 테스트가 노출 7.8%·실력 98%로
  영상의 Turnaround Tuesday 사례와 같은 패턴, 벤치마크 비교 4축 플래그 정상 출력).
- UI 페이지 연결(예: 전략 스튜디오에 민감도/순열 결과 시각화 추가)은 아직 하지 않음 — 이번 범위는
  엔진 함수 자체까지. 다음 세션에서 사용자가 "화면에도 보여줘"라고 하면 `app/pages/1_전략_
  스튜디오.py`에 탭/expander로 추가하는 방향이 기존 페이지 패턴과 일관적일 것.

### 작업 14 (2026-07-25, 같은 날 후속): 4대 검증 테스트를 전략 스튜디오 UI에 연결

사용자가 "추천을 다 수용할게, 마음껏 펼쳐봐"라며 작업 13 말미에 남긴 다음 단계 제안(UI 연결)을
전적으로 위임 → 확인 질문 없이 바로 설계·구현([[feedback-quant-workflow]]의 "묻지 말고 판단해서
구현하라" 원칙 적용).

- `app/pages/1_전략_스튜디오.py`의 "🛠 생성/백테스트" 탭, 기존 "📊 국면별 수익률 분해" expander와
  "이 전략을 라이브러리에 저장" 사이에 "🔬 전략 검증 테스트 (Masters의 4대 검증)" 섹션을 4개
  하위 탭(①민감도 ②순열검정 ③수익분해 ④벤치마크 종합비교)으로 추가.
- **① 민감도**: 전략 설정(dict 또는 수식 문자열)에서 스윕 가능한 숫자 파라미터를 자동으로 찾아
  선택하게 하는 헬퍼 3종 신규 — `_find_numeric_leaves`(dict/list 재귀 순회로 모든 숫자 leaf의
  경로를 찾음, 단순조건/1:2:6 staged 스키마 둘 다 결국 dict/list라 스키마 무관하게 동작),
  `_find_expression_numbers`/`_substitute_expression_number`(수식 문자열은 정규식으로 숫자
  리터럴 위치를 찾아 치환). 사용자가 파라미터+범위+포인트 수를 고르면 변형 목록을 만들어
  `run_sensitivity_sweep`에 넘기고, 결과를 라인차트 + 견고성 판정 배지로 표시.
- **② 순열검정**: 지표(누적수익률/샤프/CAGR)와 순열 횟수(기본 100, 20~500)를 고르면
  `run_permutation_test`를 `job_manager`(백그라운드 스레드 + 폴링)로 실행 — 순열 1회가
  백테스트 1회와 같은 비용이라 오래 걸릴 수 있어 기존 "🚀 백테스트 실행" 버튼과 동일한 비동기
  패턴 재사용. 결과는 히스토그램(순열 분포) + 실제 결과 위치를 점선으로 표시, p-value 0.05
  기준 유의성 배지.
- **③ 수익 분해**: `run_partition_test`로 추세/실력/편향을 가로 막대차트로 표시(색은 앱 기존
  상태색 관례 재사용 — 실력=`#4caf82`, 추세=`#8a8a8a`, 편향=`#e5533d`). 월 적립 옵션이 켜져
  있으면 로그수익률 분해 전제가 깨지므로(적립식 현금흐름 포함) 적립 없는 순수 버전으로 별도
  재계산해서 보여주고 그 사실을 캡션으로 안내.
  편향은 사용자가 직접 입력(표본외 검증으로 별도 추정한 값이 있을 때만, 기본 0).
- **④ 벤치마크 종합비교**: `summarize_strategy_vs_benchmarks`로 누적수익률/CAGR/MDD/샤프 4축
  전부를 `st.metric`+delta로 표시(delta 부호가 이겼는지와 항상 일치하도록 설계해 Streamlit
  기본 초록/빨강 색상이 자동으로 승패를 나타냄), 4축 중 몇 개를 이겼는지로 종합 코멘트.
- 데이터 시각화는 `dataviz` 스킬을 먼저 참고 — 기존 페이지가 이미 쓰고 있는 팔레트(전략=`#5B8DEF`,
  상태색 3톤)를 그대로 재사용해 새 팔레트를 만들지 않았고, 축 1개 원칙/범례/호버(Plotly 기본 제공)
  등 스킬 원칙에 맞춤.
- 새 백테스트를 실행하면 이전 종목/전략 기준으로 계산됐던 민감도/순열검정 결과가 화면에 남아있지
  않도록 `st.session_state`에서 즉시 제거하는 처리 추가(안 하면 다른 종목 결과가 섞여 보일 위험).
- 검증: 임시 스크립트로 Streamlit `AppTest`를 통해 실제 페이지를 구동 — 티커 AAPL 기본값으로
  백테스트 실행 → 신규 섹션 헤더/4개 탭 렌더링 확인 → 민감도 스윕 버튼 클릭(포인트 5개, 견고성
  판정 정상 출력) → 순열검정 버튼 클릭(n=20, p-value 0.0952) → 전 구간에서 `at.exception` 없음
  확인 → 8개 `st.metric` 위젯(분해 3개 + 벤치마크 비교 4개 + 기존 리더보드 배지)이 전부 실제 값
  (총 로그수익률 0.5177, 노출 57.6%, 실력비중 40.2%, 누적수익률 델타 -3.40%p, MDD 델타 +18.26%p
  등)으로 렌더링됨을 확인 — 영상 사례처럼 "원수익률/CAGR은 졌지만 MDD/샤프는 이겼다" 패턴이 실제
  데이터로도 재현됨. `python -m py_compile`로 문법 검증 + 전체 pytest 597개 통과(신규 회귀 없음).
- **참고(내가 만든 문제 아님)**: 전체 스위트 실행 중 `test_market_regime.py::
  test_get_latest_market_regime_snapshot_returns_none_when_empty`와 `test_sector_strength.py::
  test_get_latest_theme_strength_snapshot_returns_none_when_empty` 2개가 실패 — 원인은 작업 12
  이전 커밋(`2abf79c`, 이 세션 시작 전 이미 main에 존재)이 추가한 CI 스냅샷 JSON 파일 폴백
  (`data/market_regime_snapshot_ci.json` 등, 실제로 git에 커밋돼 있고 디스크에도 존재) 때문에
  "DB가 비어있으면 None" 전제였던 두 테스트가 더 이상 성립하지 않는 것 — `core/market_regime.py`/
  `core/sector_strength.py`나 그 테스트를 이번 세션에서 건드리지 않았고 격리 실행해도 동일하게
  실패해 이번 작업과 무관함을 확인. 사용자에게 보고 후 "고쳐줘" 요청받아 바로 수정: 두 테스트에
  `tmp_path`로 `_CI_SNAPSHOT_PATH`를 존재하지 않는 경로로 monkeypatch해 "DB도 비어있고 CI 폴백도
  없을 때"만 None을 검증하도록 전제를 갱신(운영 코드는 건드리지 않음 — CI 폴백 자체는 의도된
  설계). 전체 pytest 599개 전부 통과로 복구.

### 작업 15 (2026-07-25, 같은 날 후속): 🌙 야간 리더보드 "같은 섹터 다른 종목 적용" 기능 버그 수정

사용자가 야간 미세튜닝 리더보드 탭의 "🧪 같은 섹터 다른 종목에도 적용해보기"(WDC 등에서 채택된
파라미터를 재학습 없이 같은 섹터 다른 종목에 그대로 적용해보는 기존 기능, 이번 세션 이전부터 있던
코드)를 눌렀더니 결과가 전부 None이고 `'BacktestRun' object has no attribute 'get'` 오류가 뜬다고
보고. `app/pages/1_전략_스튜디오.py:2460-2463`(`_render_nightly_leaderboard_tab()` 내부)을 확인해
원인 특정: `compare_with_benchmarks()`는 `dict[str, BacktestRun]`을 반환하는데, `peer_results.get
("strategy", {})`까지는 맞게 `BacktestRun` 객체를 꺼내놓고 그 뒤 `peer_strategy.get("cagr")`처럼
`BacktestRun` 객체에 바로 `.get()`을 호출해(그 객체엔 그런 메서드가 없음) 매번 예외 → try/except가
잡아서 전부 None 행으로 채워지고 있었다(이번 세션이 만든 버그 아님, 원래부터 있던 결함).
`.metrics.get(...)`으로 고쳐서(3곳: peer_strategy/peer_benchmark/peer_hold) 실제 지표 dict을
꺼내도록 수정. 검증: 실제 리더보드 데이터(MU, Information Technology)로 동일 로직을 직접 재현해
AAPL/ACN/ADBE 등 동일 섹터 종목에 대해 전략CAGR/종목홀딩CAGR/SPX CAGR/초과수익이 전부 실제 숫자로
나오는 것 확인. 전체 pytest 599개 통과(회귀 없음, 이 기능 자체는 UI 상호작용이라 별도 자동 테스트는
추가하지 않음 — 기존 이 탭도 커버하는 자동 테스트가 없었음).

### 작업 12 후속 (2026-07-25): secrets 등록 완료, GH Actions 파이프라인 정상화 확인

사용자가 GitHub repo secrets 9개(OCI_USER_OCID/FINGERPRINT/TENANCY_OCID/REGION/IMAGE_ID/SUBNET_ID/
AVAILABILITY_DOMAINS/API_KEY_PEM/ORACLE_SSH_PUBLIC_KEY) 웹 UI로 수동 등록 완료. 등록 전 실행들은
전부 값이 빈 문자열이라 for-loop가 아예 안 돌고 조용히 "성공"으로 위장됐던 버그(작업 12에서 발견)를
`.github/workflows/oracle_capacity_retry.yml`에 secrets 누락 시 `::error::`로 즉시 실패하는 가드
추가(커밋 `bb4eb3d`)로 수정. 이후 실제 실행에서 도쿄(ap-tokyo-1) OCI API 연결 타임아웃
(`RequestException: connection to endpoint timed out`)으로 실패하는 새 케이스 발견 →
`TooManyRequests`/`Out of host capacity`와 동일하게 재시도 대상으로 처리하도록 수정(커밋
`3fb91fa`). 두 수정 모두 push 완료(main). 사용자가 Actions 웹 UI에서 두 번 수동 트리거해서
검증: 1차는 타임아웃으로 실패 확인 → 수정 → 2차는 429(로컬 스크립트와 동시 요청 경합)를 정상적으로
넘기고 success로 종료 확인. **파이프라인 정상 작동 확인됨.** 로컬 백그라운드 재시도 스크립트는
GH Actions와의 API 경합을 줄이기 위해 종료(더 이상 필요 없음 — GH Actions가 컴퓨터/Codespace 상태와
무관하게 계속 재시도함).

**남은 것**: 도쿄 리전 A1.Flex capacity 자체가 언제 풀릴지는 알 수 없음(Oracle 쪽 문제) — GH Actions
cron이 알아서 계속 시도하다 성공하면 `ORACLE_VM_READY` repo variable이 `true`로 자동 세팅됨. 다음
세션에서 확인할 것: `gh variable list --repo sternjeong/Quant`로 `ORACLE_VM_READY` 값 확인, 또는
Oracle 콘솔에서 인스턴스 생성 여부 확인. 생성됐다면 `deploy/DEPLOYMENT_ORACLE.md` 2번 단계(네트워크
설정)부터 이어서 진행.

### 작업 16 (2026-07-25, 같은 날 후속): 야간 미세튜닝 엔진이 "재학습 없이 다른 종목에 적용하면 계속
지는" 근본 원인 조사 + 4가지 구조적 수정

사용자가 "과거 데이터로 전략을 수정했으면 적어도 그 과거 데이터에 대해서는 오버퍼폼해야 할 것 같은데,
개별 종목은 이겨도 재학습 없이 같은 섹터 다른 종목에 적용하면 계속 진다"며 "너가 직접 이 엔진에 다
접근해서 분석하고 조언하라"고 요청. 코드를 직접 읽고 실제 리더보드 데이터(`data/nightly_tuning_
leaderboard.json` 50건)로 계산까지 돌려 원인 3가지를 특정했고, 사용자가 "모두 구현해줘"라고 승인해
바로 수정까지 완료([[feedback-quant-workflow]]의 "묻지 말고 판단해서 구현하라" 원칙 적용, 다만
튜닝 엔진처럼 실거래 판단에 쓰이는 핵심 시스템이라 분석 결과는 먼저 보고한 뒤 승인을 받고 진행함).

**발견한 원인 3가지 (실데이터로 검증)**:
1. **CAGR 연환산 폭발**: `trained_regime`(국면별 트레이닝) 지정 시 test 검증을 "S&P500 기준 그
   국면이었던 가장 긴 연속 구간 하나"로 좁히는데(`_evaluate_group_config_on_regime_matched_test`),
   그 구간이 실제로는 10거래일(`market_regime._MIN_REGIME_SEGMENT_TRADING_DAYS`)까지 짧을 수 있어
   며칠짜리 실현수익률이 연환산되며 폭발(MU: 매매 1회·2주짜리 구간이 CAGR 1786%로 리더보드 1위).
   리더보드 상위 50개 중 최소 15개 이상이 매매 0~3회짜리 이런 아티팩트였음.
2. **리더보드 생존편향**: 매일 밤 종목 100개 × 스타일 6종 × 국면 3종 × 후보 20~60개(수천 건)를
   반복 실행해 역대 최고 50개만 남기는 구조라, 순전히 우연으로 튄 값이 상위를 독차지.
3. **backbone_changed 데이터 스누핑**: `tune_strategy_for_group()`의 escape hatch(그룹이 test에서
   지면 구조가 다른 backbone 대안을 시도)가 "test 구간은 선택 기준에 안 쓴다"는 4b절 원칙과 달리
   실제로는 test 성과가 제일 좋은 backbone을 그대로 채택하고 있었음. 사용자 예시 WDC로 직접 검증:
   `run_permutation_test` p=0.25(노이즈와 구분 안 됨), `run_partition_test` 실력기여 -5.55%(마이너스
   — 초과수익은 전부 WDC 자체의 폭등 추세였고 전략 타이밍은 오히려 손해). WDC는 실제로
   `backbone_changed=True` 케이스였음 — 원인이 이 경로였다는 결정적 증거.

**구현한 수정 4가지 (전부 `core/strategy_tuning.py`)**:
1. `_MIN_TEST_WINDOW_TRADING_DAYS=60` 신설 — 국면 일치 test 세그먼트를 `historical_regime_segments
   (..., min_trading_days=_MIN_TEST_WINDOW_TRADING_DAYS)`로 엄격하게 걸러(train 폴드용 10거래일보다
   훨씬 김), 짧으면 "국면 일치 구간 없음"과 동일하게 검증 자체를 포기(기존 None 관례 재사용).
   `_group_mean_excess_return`/`tune_strategy_for_ticker`/`run_batch_tuning`의 초과수익 계산도
   CAGR 대신 cumulative_return(실현 누적수익률) 차이로 전환(같은 구간이라 연환산이 필요 없고
   폭발도 안 함) + 매매횟수 `_MIN_TRADE_COUNT`(5) 미만 종목은 아예 제외(excess_return=None,
   `insufficient_sample` 플래그) — `get_top_tuning_results`가 excess_return IS NOT NULL로 필터링
   하므로 리더보드에서 자동으로 빠짐.
2. `tune_strategy_for_group`의 `_search_and_evaluate`가 각 backbone의 train 워크포워드 점수
   (`trail[0]["score"]`)도 반환하도록 확장하고, 구조 변형 채택 여부를 test 성과(`cand_excess`)가
   아니라 이 train 점수로만 비교하도록 변경 — test는 "채택된 backbone이 실제로 얼마나 잘하는지"
   정직하게 보고하는 데만 쓰인다.
3. `_compute_tuning_significance()` 신설 — 채택된 group_config가 통계적 엣지인지(순열검정 p-value)
   종목 추세가 아니라 실력에서 온 것인지(분해 테스트 skill_pct_of_total) 종목별로 검증(작업 13에서
   만든 `core.backtest_engine.run_permutation_test`/`run_partition_test` 재사용). 비용 절감을 위해
   test에서 이미 진(excess≤0) 종목이나 매매 5회 미만인 종목은 계산을 건너뛴다. `tune_strategy_for_
   group`/`run_batch_tuning`/`save_tuning_run`을 통해 종목별로 저장되고, `StrategyTuningResult`에
   `significance_p_value`/`skill_pct_of_total` 컬럼 신설(`core/models.py` + `core/db.py`
   `_add_missing_columns`에 ALTER TABLE 추가, 실제 `data/quant.db`에도 적용 확인).
   `get_top_tuning_results(require_significant=True)`(기본값)가 p<0.05 & skill>0인 결과만
   보여주도록 필터 추가.
4. `app/pages/1_전략_스튜디오.py`(야간 리더보드 탭): "✅ 통계적으로 유의미한 결과만 보기" 체크박스
   (기본 켜짐, DB 결과와 GitHub Actions JSON 결과 양쪽에 동일하게 적용) + p-value/실력비중 컬럼을
   리더보드 표에 추가. **저장 게이트**: "📚 라이브러리에 저장" 기본 버튼은 (a) 통계적 유의성 통과
   AND (b) "🧪 같은 섹터 다른 종목에도 적용해보기"를 이미 실행해서 과반 종목이 초과수익 양수일 때만
   활성화되고, 둘 중 하나라도 안 되면 "⚠️ 검증 없이 저장하기(권장하지 않음)" 보조 버튼으로만 저장
   가능(완전히 막지는 않되 명확히 비권장 경로로 분리).
- 검증: `tests/test_strategy_tuning.py`에 신규/수정 테스트 다수(민감도 계산이 이긴/충분한 종목만
  계산하는지, backbone 선택이 train↔test를 일부러 뒤집어놔도 train 기준으로 채택되는지, 짧은 세그먼트
  가 엄격한 min_trading_days로 걸러지는지, run_batch_tuning의 표본부족 종목이 excess_return=None이
  되는지, get_top_tuning_results 기본 유의성 필터) — 전체 pytest 606개 통과. 추가로 실제 데이터로
  라이브 검증: (1) AAPL/MSFT/ORCL 3종목 그룹 튜닝을 국면="약세장"/regime=None 양쪽으로 실행해 min-
  window 게이트가 실제로 얇은 결과를 "검증 불가"로 정직하게 걸러내는 것 확인, (2) 실제로 이기는
  AAPL RSI<35(2022~2024) 케이스로 `_compute_tuning_significance`를 직접 호출해 p=0.0488(유의),
  skill=98.47%(실력)가 정상 계산됨을 확인 — 작업 13에서 만든 Masters 4대 테스트 엔진이 실제로
  튜닝 파이프라인에 살아있는 기능으로 연결됐음을 실증.
- **후속 참고**: 기존에 커밋된 `data/nightly_tuning_leaderboard.json`(50건)은 이번 수정 이전에
  생성된 데이터라 significance_p_value/skill_pct_of_total이 전부 없음(None) → 기본 필터(유의성만
  보기)를 켜두면 리더보드가 당장은 비어 보일 수 있음(UI에 이유를 안내하는 문구 추가해둠). 다음 야간
  튜닝(로컬 스케줄러 또는 GitHub Actions)이 새로 돌면 검증된 결과가 다시 쌓이기 시작한다 — 기존
  파일을 수동으로 지우거나 덮어쓰지는 않았음(오래된 값이라도 참고용으로 "전체 보기" 토글로는 계속
  조회 가능하게 남겨둠).

### 작업 16 (2026-07-25, 같은 날 후속): 코스톨라니 국면 매매를 일반 Strategy로 승격 + 국면 판정 warmup 버그 수정

사용자가 시장 진단 페이지의 "실제로 이 국면 신호대로 매매했다면?" 결과를 보고 "이것도 전략으로
만들어줄 수 있어?"라고 요청 — 지금까지는 `core/kostolany_scenario_engine.py`의 전용 함수로만
21개 섹터/테마 ETF에 대해서만 돌릴 수 있었는데, 이걸 다른 전략들처럼 전략 라이브러리에 저장하고
아무 종목에나 적용할 수 있게 해달라는 것. 확인 질문 없이 바로 설계·구현([[feedback-quant-workflow]]).

- **다섯 번째 indicator_config 스키마 신설** (`core/strategy_engine.py`): `{"schema": "kostolany",
  "style": "장기"|"스윙"}`. 기존 4개 스키마(레짐/직접수식/1:2:6단계별/복합)는 전부 "AND/OR 조건이
  참인 구간만 보유"하는 레짐 추종형이라 3단계(매수/보유·관망/매도) + hold=직전상태유지(hysteresis)
  개념을 표현할 수 없어 별도 스키마로 분리. `is_kostolany_config`/`generate_kostolany_position`
  신설, `evaluate_boolean_signal()`(→ `generate_positions()` → `run_backtest`)의 공용 진입점에
  연결 — 이 한 곳만 고치면 백테스트 엔진/차트 렌더링(빈 `conditions` 리스트로 자연히 통과)이 전부
  별도 수정 없이 동작함을 확인. `core.kostolany_scenario_engine.classify_cycle_phase_series`/
  `build_position_from_phases`를 지연 import로 재사용(모듈 최상단에서 가져오면
  strategy_engine↔kostolany_scenario_engine↔backtest_engine 순환참조 발생).
- **전략 라이브러리/UI 통합**: `core/strategy_library.py`(`detect_strategy_type`/
  `_validate_config_schema`에 kostolany 분기 추가), `core/strategy_explainer.py`
  (`describe_kostolany_config` 신설, Gemini 키 없어도 결정론적 설명 생성), `app/pages/1_전략_
  스튜디오.py`(`STRATEGY_TYPE_LABELS` 2곳에 "kostolany" 라벨 추가 안 하면 라이브러리 목록 렌더링이
  `KeyError`로 죽는 것을 AppTest로 실제 발견해 수정 — `_load_config_into_state`에 `loaded_
  kostolany_config` 세션상태 분기 신설(안 하면 '불러오기' 후 '백테스트 실행'을 눌러도 지표 토글 UI가
  빈 조건으로 조용히 되돌아가 아무 신호 없이 실행되는 조용한 버그였음, staged 전략과 동일한 패턴으로
  해결), "🧬 다종목 미세튜닝" 백본 선택 목록에서는 제외(숫자 파라미터가 없어 그리드서치 대상이
  아님 —애초에 재학습 없이 아무 종목에나 그대로 적용되도록 설계됨). "🧩 전략 합성" 탭은 별도 수정 없이
  그대로 됨(combine 스키마가 재귀적으로 evaluate_boolean_signal을 호출하므로).
- **라이브러리에 기본 전략 2개 저장**: "🐢 코스톨라니 국면 매매 (장기)"(id=21), "⚡ 코스톨라니 국면
  매매 (스윙)"(id=22), source="kostolany_cycle".
- **부수 발견 및 수정한 버그**: `run_backtest`(신규 경로, warmup 400일 사전 확보)와 `run_ticker_
  scenario`(기존 시장 진단 페이지가 쓰는 경로)를 같은 AAPL/기간으로 교차검증하던 중 두 결과가 크게
  달랐던 것(포지션 불일치 146일, 거래 3건 vs 2건)을 발견 → 원인은 `run_ticker_scenario`/`run_theme_
  scenario`가 `run_kostolany_scenario` 자신의 docstring이 요구하는 "252거래일 이상 warmup"을
  실제로는 전혀 안 붙이고 분석 시작일부터 바로 데이터를 받아왔던 기존 버그(이번 세션이 만든 코드가
  아니라 시장 진단 페이지가 이미 쓰고 있던 코드) — 분석 구간 맨 앞 최대 1년 가까이가 아직 덜 채워진
  rolling 윈도로 국면이 왜곡되고 있었다. `WARMUP_DAYS=400` 도입해 `run_backtest`와 동일한 관례로
  수정 → 두 경로 결과가 완전히 일치(포지션 불일치 0일)하는 것으로 재검증. **이 버그는 시장 진단
  페이지의 기존 코스톨라니 시나리오 결과(사용자가 "꽤 괜찮은거 같다"고 평가했던 바로 그 결과)에도
  이미 영향을 주고 있었음** — 수정 후 첫 ~1년 구간의 매매가 더 정확하게(또는 새로) 잡힐 수 있어
  숫자가 달라질 수 있다.
- 검증: `tests/test_strategy_engine.py`(kostolany 스키마 판별/포지션 매핑 3개),
  `tests/test_strategy_library.py`(판별·검증 3개), `tests/test_kostolany_scenario_engine.py`
  (warmup fetch 3개) 신규 유닛테스트 추가 + Streamlit `AppTest`로 실제 AAPL 데이터 라이브
  end-to-end(라이브러리에서 불러오기 → 백테스트 실행 → 차트 렌더링까지) 확인. `run_backtest`
  경로와 `run_ticker_scenario` 경로가 동일 티커/기간에서 완전히 같은 거래/포지션을 내는 것도
  직접 대조 확인. 전체 pytest 615개 통과(신규 12개 포함, 회귀 없음).

### 작업 17 (2026-08-12): 코스톨라니 섹터별 시나리오에 사용자 지정 기간 + ETF 상장 이전 구간 처리

사용자가 "코스톨라니 달걀 이론 시뮬레이션(섹터별 매수 시나리오)에서 테스트 기간을 직접 설정할 수 있게
해달라, ETF가 그 기간에 없었던 섹터는 어떻게 처리할지 아이디어를 달라"고 요청 → 전체 자율 모드([[
feedback-quant-workflow]] 2026-07-17 갱신: 확인 없이 설계·구현) 기준으로 바로 진행.

- **기간 직접 설정**: `app/pages/7_시장_진단.py`의 "실제로 이 국면 신호대로 매매했다면?" 섹션에
  시작일/종료일 `st.date_input` 추가(기본 5년 전~오늘, 다른 페이지의 튜닝 기간 선택과 동일한 기본값
  관례). `core.kostolany_scenario_engine.compute_theme_scenario_runs`는 이미 `start`/`end`
  파라미터를 받고 있었지만(엔진은 이미 구현돼 있었음) 이 페이지가 인자 없이 호출해 항상 엔진 기본값
  (오늘 기준 800일 전)만 쓰고 있었던 것이 원인 — UI에서 고른 값을 그대로 전달하도록 연결. 캐시 키
  (`scenario_job_key`)에도 시작/종료일을 포함시켜 기간을 바꾸면 재계산되도록 함.
- **ETF가 선택 기간에 없었던 섹터 처리**: 여러 아이디어(프록시 대체, 관련 지수로 백필, 최소 데이터
  기준 미달 시 제외 등) 중, 가장 정직하고 부작용이 적은 "실제 사용 구간을 투명하게 보여주고 사용자가
  판단하게 한다" 방식을 채택해 구현. `scenario_runs_to_summary_df`에 `data_start` 컬럼 추가(테마별로
  실제 계산에 쓰인 첫 거래일 — 프록시 ETF가 선택한 시작일 이후에 상장됐으면 이 값이 그만큼 밀림).
  페이지에서 `data_start`가 선택한 시작일보다 30일 넘게 늦은 섹터는 테마명 앞에 ⚠️ 표시 + 별도
  "데이터 부족" expander에 실제 상장(데이터 시작)일과 프록시 티커를 나열하고, 승률 집계(`win_count`)
  에서도 제외해 짧은 구간의 우연한 결과가 전체 통계를 왜곡하지 않게 함. (다중 프록시 테마 —
  반도체[SOXX,SMH], 우주[UFO,ARKX,ROKT], 클라우드[SKYY,WCLD] 등 — 는 `_combined_close_volume`이
  이미 존재하는 프록시만으로 평균을 내므로 부분적으로는 자동으로 완화됨.)
- 검증: `tests/test_kostolany_scenario_engine.py`/`test_kostolany_cycle.py` 39개 회귀 통과 확인 +
  `compute_theme_scenario_runs`를 XLK(오래된 ETF)와 LUMA(2026-07-14 상장, 광통신 테마) 조합으로 직접
  호출해 `data_start`가 XLK는 요청 시작일과 거의 같고 LUMA는 실제 상장일로 정확히 밀리는 것을 라이브
  데이터로 확인. Streamlit `AppTest`로 코스톨라니 섹션에 실제로 진입해 "📊 섹터별 시나리오 계산하기"
  버튼을 누르고 백그라운드 job이 끝날 때까지 폴링한 뒤 "⚠️ 데이터 부족으로..." expander가 실제로
  렌더링되는 것까지 end-to-end 확인(이 과정에서 `Series.dt.days` 대신 `Timedelta` 직접 비교를 쓰면
  발생하는 NumPy 2.x deprecation 경고를 발견해 `.dt.days > 30` 비교로 수정). 전체 pytest 615개 통과
  (회귀 없음, 새 UI 배선이라 별도 유닛테스트는 추가하지 않고 기존 커버리지 + 라이브 AppTest로 확인).

### 작업 17 후속 (2026-08-12, 같은 날): 월 적립금 "언제 넣을까" 정책 비교 (순수 DCA vs 신호 대기 vs 하이브리드)

사용자가 "A를 매도 타점에서 팔면 그 돈을 A가 다시 매수 타점에 올 때까지 기다려야 하는지, 다른 데로
옮겨야 하는지 모르겠다. 매달 버는 돈도 매수 타점 올 때까지 쌓아둬야 하는지 아니면 비슷한 가격대면 그냥
사야 하는지 모르겠다"고 실제 자산배분 방법을 물어봄 → 코드 작업이 아닌 탐색형 질문이라 먼저 2~3문장
추천 + 트레이드오프로 답하고(①매도 대금은 현금성 자산에 대기하되 이미 만들어둔 매수 관심 국면
칸반보드로 다른 섹터 로테이션 고려, ②월 적립금은 순수 DCA도 신호 대기도 아닌 하이브리드— 매달
일부는 무조건 즉시 투자하고 나머지는 신호를 기다리는 방식 — 을 추천), "그럼 세 정책을 실제로
백테스트해서 보여줄까?"라고 제안 → 사용자가 "그렇게 해줘"로 승인해 구현.

- **왜 새 엔진이 필요했나**: 기존 "월 적립 옵션"(`simulate_contribution_equity`)은 이미 두 정책을
  구현하고 있었다 — 매수보유(포지션 항상 1) DCA 벤치마크가 사실상 "순수 DCA"이고, 코스톨라니 신호
  전략(매도 국면 중 현금 누적 → 매수 국면 전환 시 몰빵)이 사실상 "신호 대기"다. 다만 그 함수는
  "포지션 비중만큼만 항상 시장에 있어야 한다"는 규칙으로 매일 리밸런싱하기 때문에, 매도 신호가 뜨면
  **이미 사둔 지분까지 현금화**한다 — "이미 넣은 돈을 신호대로 사고팔았다면"이라는 질문에는 맞지만
  "이번 달 새로 번 돈을 어디에 넣을지"라는 질문과는 다르다(이미 투자한 돈을 되팔지 여부는 별개 결정).
  그래서 `core/kostolany_scenario_engine.py`에 `simulate_gated_contribution_equity`를 새로 추가 —
  월 적립금 중 `baseline_ratio`만큼은 신호와 무관하게 그날 즉시 투자하고, 나머지는 매수 신호(국면
  position > 0)가 뜰 때까지 현금으로 대기시켰다가 몰아서 투입한다. **이미 투입된 돈은 이후 신호가
  바뀌어도 절대 되팔지 않는다** — "새 돈의 진입 타이밍"만 격리해서 비교하기 위한 의도적 설계(기존
  보유분 매도 타이밍은 위 섹터별 시나리오가 이미 답하는 별개 질문이라 중복하지 않음). `baseline_ratio`
  1.0=순수 DCA, 0.0=신호 대기, 0~1 사이=하이브리드로 세 정책을 한 함수로 통일해 표현.
- **UI**: `_render_kostolany()`(`app/pages/7_시장_진단.py`)의 섹터별 시나리오 섹션 아래에 새 서브섹션
  "💰 매달 버는 돈, 언제 넣을까?" 추가 — 티커 입력(기본 SPY, 섹터 전체가 아니라 실제 사려는 개별
  종목/ETF를 넣어보라는 안내), 월 적립금, 하이브리드 즉시투자 비율 슬라이더(기본 50%)를 받아 세 정책의
  누적수익률(원금 대비)/XIRR/MDD/샤프를 나란히 카드로, 자산가치 곡선 3개 + 누적 납입 원금선을 라인차트로
  보여준다. 위 시나리오 섹션과 같은 시작일/종료일·투자 스타일(장기/스윙) 선택을 그대로 재사용.
- 검증: `run_ticker_contribution_policy_comparison('SPY', ...)`을 직접 호출해 하이브리드 결과가
  DCA와 신호 대기 사이에 오는 것을 확인, `baseline_ratio=1.0`이 기존 `simulate_contribution_equity`
  매수보유 DCA와 사실상 동일한 값을 내는 것도 직접 대조(첫날 shift 처리 차이로 나는 0.02% 미만의
  오차는 기존 코드에도 있던 룩어헤드 방지 관례라 문제 아님). Streamlit `AppTest`로 "📈 정책 비교
  계산하기" 버튼을 눌러 백그라운드 job 완료까지 폴링한 뒤 세 카드 지표가 실제로 렌더링되는 것까지
  end-to-end 확인. 전체 pytest 621개 통과(다른 세션이 이 파일에 동시에 추가한 양방향(인버스) 트레이딩
  기능 포함, 회귀 없음).

### 작업 17 후속 2 (2026-08-12, 같은 날): 개별 종목(S&P500 표본) 광범위 검증 + 가격 캐시 "전체 이력" 마커 버그 발견/수정

사용자가 "ETF가 당시에 없으면 어떻게 하냐"는 질문을 "이 기법이 시장을 상대로 옳게 평가하는지 좀 더
광범위하게 보고 싶다"는 맥락으로 재질문 → 코드 작업 전에 먼저 문제를 분해해서 설명(①섹터 ETF ~20개
중 상당수가 2015년 이후 상장이라 표본이 작고 서로 상관관계도 높음, ②짧은 이력 구간엔 애초에 상승/하락
사이클이 없어 뭘 어떻게 보여줘도 검증이 불가능함 — 그래서 "화면 표시" 문제가 아니라 "무엇을 검증
대상에 넣을지"의 문제)하고 두 아이디어(①최소 이력 필터, ②섹터 ETF 대신 개별 종목으로 표본 확대)를
제시 → 사용자가 "2번으로 해주라"고 선택.

- **엔진**: `core/kostolany_scenario_engine.py`에 `compute_broad_universe_scenario_runs(tickers, ...)`
  추가 — `compute_theme_scenario_runs`와 신호 로직은 완전히 같지만(같은 `run_kostolany_scenario`
  재사용) 섹터 프록시 몇 개가 아니라 티커 리스트를 받아 `core.market_data.get_multiple_price_history`로
  한 번에 병렬 조회한다(수백 종목 순차 조회 시 느림 방지). `scenario_runs_to_summary_df`는 dict 키를
  "라벨"로만 다뤄 테마든 티커든 그대로 재사용 가능해서 별도 수정 없이 그대로 썼다.
- **표본**: 새 엔진 자체는 티커 리스트만 받고 어떤 표본을 쓸지는 호출자(UI) 책임으로 분리 — 이미
  있는 `core.strategy_tuning.sample_universe(n, as_of_date=...)`(섹터 균등 표본, `as_of_date`를 주면
  `core.point_in_time_universe`로 그 시점 실제 편입종목만 후보로 삼아 생존편향도 함께 줄임)를 그대로
  재사용했다(새로 만들지 않음 — 이미 이 목적으로 존재하던 함수).
- **UI**: `_render_kostolany()`(`app/pages/7_시장_진단.py`)의 섹터별 시나리오 섹션 바로 아래에
  "🔬 개별 종목 광범위 검증" 서브섹션 추가 — 표본 크기(20/50/100/150) 선택, "선택 시작일 기준 실제
  편입종목만 사용(생존편향 방지)" 체크박스(기본 켜짐), 실행 버튼. 결과는 검증 종목 수·S&P500 매수보유
  대비 승률·평균/중앙값 초과수익률(%p) 카드 + 종목별 전체 표(위 섹터별 시나리오와 동일한 "데이터 부족
  30일 초과 시 ⚠️ 표시 + 집계 제외" 규칙 재사용)로 보여준다.
- **부수 발견: 가격 캐시의 ".full"(전체 이력 확보 완료) 마커가 검증 없이 영구 고정되는 버그.**
  개별 종목으로 실제 테스트하던 중 AAPL의 캐시된 이력이 1980년대가 아니라 2017-10-26부터로 잘려있는
  것을 발견 → `core/market_data.py`의 `get_price_history`가 `start=None`으로 한 번 받아본 뒤 그
  결과가 실제로 상장일까지 닿았는지 검증하지 않고 무조건 `.full` 마커를 찍고 있었다(`need_older`가
  이 마커 존재 여부만 보고 이후로는 절대 재확장을 시도하지 않음). 캐시 디렉터리 전수 조사 결과
  `.full` 마커가 있는 19개 종목(AAPL/MSFT/AMZN/JNJ/KO/JPM/META 등 우량주 전부) **100%가 실제 상장일보다
  한참 늦은 날짜로 잘려 있었다** — 2026-07-15 특정 시점의 배치 작업(nightly tuning 등)이 Yahoo
  Finance 레이트리밋/네트워크 문제로 부분 응답을 받았는데 그걸 "전체 이력"으로 영구 확정해버린 사고로
  추정. 이 상태로는 "개별 종목으로 넓게 검증"이라는 이번 기능의 전제 자체가 무너지므로(대부분의
  대형주가 몇 년치 데이터만 있는 것처럼 잘못 나옴) 바로 수정: `FULL_HISTORY_RECHECK_SECONDS`(7일)를
  추가해 마커가 있어도 그 기간이 지나면 한 번 더 확장을 시도하도록 바꿨다(실패해도 마커만 갱신되고
  성공하면 데이터가 채워짐 — 완전 신뢰 대신 주기적 자가복구). 이미 잘못 찍힌 19개 마커 파일은
  즉시 삭제해 재확인을 강제했고, AAPL(1985~)/MSFT(1986~)/JNJ·KO(1970~)/AMZN(1997~)로 정상 복구된
  것을 직접 확인. `data/cache/`는 `.gitignore` 대상이라 커밋에는 영향 없음.
- **실제 실행 결과(참고용, 표본에 따라 달라짐)**: 대형주 20종목(장기 스타일, 최근 5년) 기준 S&P500
  매수보유 대비 승률 30%, 평균 초과수익률 -16.67%p, 중앙값 -30.57%p — 섹터 ETF 표본에서 봤던 결과와
  달리 개별 우량주 넓은 표본에서는 이 기법이 시장을 못 이기는 것으로 나왔다(사용자가 원했던 "더
  넓은 시각"이 실제로 다른 결론을 보여준 사례).
- 검증: `core/market_data.py` 수정 후 `tests/test_market_data.py` 14개 회귀 통과 확인 + AAPL/MSFT/
  JNJ/KO/AMZN 실제 라이브 조회로 캐시 복구 직접 확인. `compute_broad_universe_scenario_runs`를
  8종목으로 직접 호출해 결과 검증 후, Streamlit `AppTest`로 "🔬 광범위 검증 실행" 버튼을 눌러
  백그라운드 job 완료(20종목 기준 약 1~2분, `sample_universe`가 섹터 균등 배분을 위해 매번 S&P500
  전종목 펀더멘털을 훑기 때문 — 기존 함수의 특성이라 그대로 둠, 이미 있는 job_manager 스피너 패턴이
  이 대기시간을 이미 잘 처리함)까지 폴링해 카드 지표·종목별 표가 실제로 렌더링되는 것까지 확인. 전체
  pytest 621개 통과(회귀 없음).

### 작업 18 (2026-08-12): 코스톨라니 국면 매매 전략(#21/#22)을 다종목 미세튜닝에서 못 불러오던 문제 수정

사용자가 "🐢 코스톨라니 국면 매매 (장기)/⚡ 스윙이 다종목 미세튜닝에서 불러올 수가 없다"고 보고.
조사 결과 `app/pages/1_전략_스튜디오.py`의 "🧬 다종목 미세튜닝" 탭이 `is_kostolany_config()`로
백본 전략 목록에서 코스톨라니 전략을 의도적으로 필터링하고 있었음(작업16 주석: "숫자 파라미터가
없어 그리드서치 대상이 아님"). 실제로 파고들어보니:

- **필터 제거는 안전했다**: `core.strategy_tuning.build_param_grid`는 이미 숫자 파라미터가 없는
  config(코스톨라니처럼 `{"schema":"kostolany","style":...}`만 있는 경우)에 대해 원본 그대로인
  1개짜리 "그리드"를 반환하도록 설계돼 있었고, "🔍 튜닝 대상 파라미터 미리보기" 익스팬더도
  `describe_tunable_params`가 빈 리스트를 반환하면 이미 "이 전략에는 튜닝 가능한 숫자 파라미터가
  없습니다 (원본 그대로 사용됩니다)"라고 정확히 안내하고 있었다 — 즉 필터만 없으면 나머지 흐름은
  이미 코스톨라니를 지원할 준비가 돼 있었다. 그래서 `tuning_strategies` 필터링 줄만 제거.
  `generate_structural_variants_for_config`(그룹이 test에서 못 이기면 호출하는 구조변형 escape
  hatch)에만 코스톨라니 가드 추가 — style(장기/스윙) 하나뿐인 고정 신호라 "구조가 다른 대안"이라는
  개념이 성립하지 않아서, 레짐(AND/OR) JSON 스키마로 착각하고 Gemini에 의미 없는 요청을 보내는 걸
  막았다(크래시는 아니었지만 낭비/오작동).
- **진짜 원인은 다른 곳의 기존 버그였다**: 필터를 없애고 실제로 2종목(AAPL/JPM)·짧은 기간으로
  돌려보니 `run_batch_tuning`이 `KeyError: 'strategy'`로 죽었다. 원인을 추적한 결과 코스톨라니와
  무관한 **일반 버그**였음을 확인(같은 조건에서 평범한 RSI 전략으로도 동일하게 재현) —
  `tune_strategy_for_group`이 regime(약세장/강세장/횡보장) 지정 튜닝에서 test 구간 안에 그 국면과
  일치하는 연속 구간이 아예 없으면(작은 표본/짧은 기간이나 원래 희소한 국면에서 실제로 발생)
  `per_ticker_test_comparison`을 빈 dict로 채워 "검증 불가"를 표시하도록 설계돼 있었는데,
  `run_batch_tuning`은 "error" 키 유무만 확인하고 "strategy" 키가 아예 없을 수 있다는 경우를
  놓쳐서 바로 죽었다. 실서비스 기본값(표본 100종목·5년)에서는 국면 커버리지가 있을 확률이 높아
  잘 안 드러났을 뿐, 코스톨라니를 다종목 미세튜닝에 연결하며 작은 표본으로 검증하다가 우연히
  재현·발견한 것 — `"error" in test_comparison or "strategy" not in test_comparison` 조건으로
  수정해 이제 "이 국면과 일치하는 test 구간 데이터가 없어 검증하지 못했습니다"라는 error 행으로
  정상 처리된다(기존 에러 표시 UI를 그대로 재사용, 새 UI 불필요).
- 검증: AAPL/JPM 2종목·2019~2024(짧은 기간이라 국면 커버리지 갭이 잘 재현됨) 조건으로 코스톨라니
  config와 평범한 RSI config 둘 다 직접 호출해, 수정 전엔 둘 다 크래시하고 수정 후엔 둘 다
  "국면 데이터 없음" error 행으로 정상 처리되는 것을 확인. 전체 pytest 621개 통과(회귀 없음).

### 작업 19 (2026-08-12): 강세장 대응 전략 리포트 — 딥서치 기반 모멘텀 로테이션 설계 + 백테스트

사용자가 앞선 샤프 비율 리포트(작업18 직후 별도 요청, HTML 아티팩트로 발행 —
https://claude.ai/code/artifact/57f8d359-e533-43ed-a622-546b02acea0a )를 보고 "강세장에서는 어떤
전략을 써야 하는지 딥서치 후 전략을 세우고 리포트를 그 전략에 맞게 재작성해달라"고 요청.

- **딥서치(WebSearch 4회)**: 200일선 추세추종(위험조정 기준 buy&hold 역전), Gary Antonacci
  듀얼 모멘텀(절대+상대 모멘텀 결합 GICS 11섹터 로테이션), 12-1 모멘텀 팩터(12개월 수익률
  랭킹·월간 리밸런싱이 표준) — 코스톨라니의 평균회귀(52주 저점 매수)와 정반대인 모멘텀(상승 추세
  매수) 접근으로 수렴.
- **설계한 전략**: GICS 11개 핵심 섹터 ETF, 매월 리밸런싱, 절대모멘텀(12개월 수익률>0) 필터 통과한
  종목 중 상대모멘텀(12개월 수익률) 상위 3개 동일비중 보유, 후보 3개 미만이면 나머지는 현금.
- **백테스트**(`scripts/_momentum_strategy_backtest.py`, 같은 2019-08-12~2026-08-12 구간): SPY
  매수보유(누적+167.49%, CAGR 15.10%, MDD-34.10%, 샤프0.81) 대비 신규 모멘텀 로테이션이 누적
  +178.06%·CAGR 15.74%·MDD-31.50%·샤프0.82로 **네 지표 전부 우위**. 반면 코스톨라니 장기 신호를
  "그날 매수국면인 섹터만 동일비중 보유"로 실제 로테이션 재구성해보니 MDD -51.46%로 SPY보다도
  나빴다(섹터 간 상관 폭락 시 분산이 무너지는 게 원인 — 이번에 새로 발견).
  **작업 중 발견한 버그**: 모멘텀 전략 일별수익률 계산에서 `daily_returns.reindex(columns=...)`가
  인덱스는 리인덱스 안 해 2018년 구간이 0%수익률로 섞여 들어가 CAGR 분모(연수)가 부풀려짐(다른
  3개 비교군은 `index=trading_days`를 제대로 넣어서 문제 없었음) — 발견 후 즉시 수정, cumulative_
  return/MDD/샤프는 버그와 무관해 그대로 유효했음.
- **세션 중단 대비**: 컨텍스트 소진 임박 경고를 받아 진행 상황을 `scripts/_momentum_report_handoff.md`
  에 전량 기록(리서치 요약/전략 규칙/버그/다음 할 일)한 뒤 이어감 — 실제로 세션이 끊겨도(원본
  `/tmp` HTML 유실 확인됨) 레포에 저장된 핸드오프 문서 + 백테스트 스크립트 + JSON 결과만으로 새
  세션이 그대로 이어받아 완료함(실제 검증된 복구 경로).
- **리포트**: 같은 Artifact URL로 재발행(링크 유지) — §1 코스톨라니 동적 로테이션이 강세장에서
  지는 이유(신규 발견 포함), §2 딥서치 근거 3가지(출처 인용), §3 설계한 전략 규칙, §4 4종 비교
  표+자산가치 곡선 차트+실제 월별 로테이션 종목 예시(코로나 저점 2020-04엔 후보 1개뿐이라 자본
  67% 자동 현금화, 2022 약세장 바닥엔 후보 2개), §5 월적립/리밸런싱을 새 전략 기준으로 재정의,
  §6 한계(모멘텀도 급락 자체는 못 피함 — 크래시 당일 낙폭은 SPY와 거의 같았음, 후행성, 거래비용).
- 정리: `scripts/_momentum_*`(백테스트 스크립트/JSON/핸드오프 문서)는 일회성 리포트용이라 작업
  완료 후 삭제 예정(작업18의 `_report_data_gather.py`와 동일 패턴).

### 작업 20 (2026-08-12): 샤프 비율 최적화 가설 3라운드 연구 — 시장 레짐 필터가 최대 레버리지, 단 과최적화 주의

사용자가 "계속해서 샤프 비율을 중요시하며 시장을 이길 방법을 가설을 세우고 테스트하라"고 요청 →
작업19의 모멘텀 로테이션(GICS 11섹터, top3, 12개월 모멘텀, 월간 리밸런싱, 절대모멘텀>0 필터)을
베이스라인(Sharpe 0.82)으로 3라운드에 걸쳐 파라미터/구조 가설을 순차 검증.

- **1라운드(7가설)**: Top-N(1~8), 모멘텀 lookback(3~12개월), 리밸런싱 빈도(주/월/분기), 절대모멘텀
  필터 방식(수익률 vs 200일선), 변동성 역가중, 시장 레짐 필터(SPY<200일선이면 비중 축소) 스윕.
  **핵심 발견**: (1) SPY 200일선 기준 시장 레짐 필터가 가장 큰 샤프 개선 레버리지(0.82→0.91~0.93,
  MDD -31.5%→-23%대) — 섹터 자체 모멘텀과 무관하게 시장 전체가 약세일 때 전체 비중을 줄이는 게
  가장 효과적이었음. (2) lookback은 9~12개월이 스윗스팟, 3~6개월은 나쁨(Sharpe 0.45, 휩쏘 심함) —
  학계 12-1 모멘텀 컨센서스와 일치. (3) 리밸런싱은 월간이 최적(주간 0.70, 분기 0.64 둘 다 열등).
  (4) 절대모멘텀 필터는 200일선 위치보다 12개월 수익률>0이 더 나음(0.82 vs 0.62). (5) 변동성
  역가중(risk parity 근사)은 오히려 샤프를 깎음(0.76~0.78) — 승자 비중을 줄이는 역효과.
- **2라운드**: 시장필터 축소율 세밀 스윕(0/25/50/75/100%) — 75% 축소가 순수 top3 기준 최적(0.92),
  100%(완전 현금화)는 오히려 약간 나쁨(0.87, 잔존 모멘텀까지 통째로 버리는 손실). Top4+시장필터50%
  조합이 전체 구간 샤프 1.01로 처음 1.0 돌파.
- **3라운드(강건성 검증)**: 전체 구간 샤프가 가장 높았던 조합(Top4/Top5)일수록 전반부
  (2019-08~2023-01)와 후반부(2023-01~2026-08) 사이 샤프 격차가 크다는 걸 발견(Top4: 1st 0.85 vs
  2nd 1.21, gap 0.36) — 2023년 이후 AI 랠리 쪽으로 쏠린 결과일 위험. 반대로 top3·9개월·75%축소는
  gap 0.07(1st 0.77, 2nd 0.84)로 가장 안정적이나 절대 샤프는 낮음(0.80). **다만 SPY 벤치마크 자체의
  구간 간 격차가 0.91(1st 0.47, 2nd 1.38)로 모든 후보보다 훨씬 컸다** — 2023~2026 자체가 전반적으로
  변동성 낮은 강세장이라 모든 전략이 후반부에 유리했다는 뜻이라, Top4의 gap 0.36도 절대적 기준으로는
  양호한 편(SPY보다 훨씬 안정적)이라는 균형 잡힌 해석을 리포트에 반영.
- **최종 권장**: 기본값은 top3·12개월·시장필터75%(Sharpe 0.92, gap 0.20, 준수한 균형) — 최대
  샤프를 원하면 top4·12개월·시장필터50%(1.01, 다만 최근 강세장 편향 가능성 인지), 최대 강건성을
  원하면 top3·9개월·시장필터50~75%(0.80~0.85, gap 0.07~0.08).
- 정리: `scripts/_sharpe_research*`(3라운드 스크립트/JSON)는 연구용 스크래치라 작업 완료 후 삭제.

### 작업 21 (2026-08-12, 같은 날 후속): 한계점 타개 4~5라운드 — 멀티에셋 확장이 최종 챔피언, 순열검정으로 통계적 유의성까지 확인

사용자가 "작업20의 한계점을 분석하고 타개할 방법론을 전개하라, 필요하면 웹서칭도 하라"고 요청.

- **작업20까지의 한계 4가지**: (L1) 고샤프 조합(Top4류)일수록 2023년 이후 강세장에 쏠린 과최적화
  의심, (L2) 시장필터가 SPY 200일선 이진 신호라 거침, (L3) 크래시 "발생 자체"는 못 피함(주식
  섹터 11개뿐이라 위기 시 도망갈 자산이 없어 상관관계가 1로 수렴), (L4) 거래비용/회전율 미반영.
- **딥서치(WebSearch 3회)**: Barroso & Santa-Clara(2015) 변동성 타겟팅이 모멘텀 전략 샤프를
  "2배 가까이" 올린다는 연구(단 Cederburg et al. 2020은 103개 팩터 중 8개만 효과 있고 전부
  모멘텀류), 회전율 버퍼(하이스트리시스)가 성과 손실 없이 회전율 24% 감소, Antonacci GEM/PAA류
  멀티에셋 절대모멘텀(주식이 현금에도 지면 채권으로 완전 이동 — 내장 크래시 방어).
- **4라운드 결과**: (1) 변동성 타겟팅은 이 전략 구조에서는 기대와 반대로 샤프를 오히려 깎았다
  (0.74~0.87, 베이스라인 0.92보다 낮음) — 이미 3종목로 분산된 월간 리밸런싱 포트폴리오라 학술
  원논문(롱숏 팩터, 주간 갱신)이 잡아내는 변동성 군집/모멘텀크래시 효과가 상대적으로 약했을
  것으로 추정. 회전율 버퍼도 기대(성과손실 없이 회전율 감소)와 반대로 성과가 계속 나빠졌다
  (버퍼 늘릴수록 0.89→0.86→0.82) — 정직하게 부정적 결과로 기록. **(2) 멀티에셋 확장(11섹터+
  TLT+IEF+GLD)이 압도적 승자**: top4·12개월·시장필터50% 조합이 샤프 1.08(무비용)/1.05(왕복
  0.1% 비용 반영)까지 상승, MDD는 -13.72%(섹터만 썼을 때 -22.7%, SPY -34.1%)로 대폭 개선 — L3
  (크래시 자체 회피 불가)를 직접 타개. 하위기간 검증에서도 "어려운" 전반부(코로나+2022약세장
  포함)조차 샤프 0.91·MDD -10.37%로 SPY 전반부(0.47·-34.1%)를 크게 앞섬 — 지금까지 중 가장
  강건한 결과.
- **5라운드(순열검정으로 통계적 유의성 확인, L1 정면 타개)**: 멀티에셋 챔피언이 진짜 "모멘텀
  랭킹의 실력"인지, 아니면 "양(+)모멘텀 자산 풀에 아무거나 들어있기만 해도" 비슷한지 확인하기
  위해 매달 상위 4개 대신 양(+)모멘텀 후보 중 무작위 4개를 뽑는 시뮬레이션을 200회 반복(시장필터·
  비용 등 나머지 메커니즘은 동일 유지). 실제 모멘텀 랭킹 샤프(1.05)가 무작위 선택 200회 분포
  (평균 0.719, 표준편차 0.150)의 **97.5th percentile**(근사 p≈0.025, 5% 유의수준 통과)에 위치 —
  모멘텀 랭킹 자체가 유의미한 초과 실력이라는 통계적 근거 확보.
- **최종 결론**: 기존 3라운드 권장(11섹터 한정)을 멀티에셋 챔피언으로 교체 권장 — top4·12개월
  모멘텀·11섹터+TLT/IEF/GLD 유니버스·SPY<200일선이면 비중50%축소·월간 리밸런싱. 비용 반영 후
  샤프 1.05(SPY 0.81), MDD -14.43%(SPY -34.10%), 하위기간 모두 SPY 대비 우위, 순열검정 통과.
  **여전히 남는 한계**: 같은 2019~2026 단일 기간(진짜 out-of-sample 없음), 국제주식·원자재 등
  더 넓은 자산군 미포함, 시장필터는 여전히 이진(SPY 200일선), 라운드가 늘수록 여러 변형을 같은
  표본에 반복 검증한 다중비교 자체가 데이터 스누핑 위험(순열검정은 "무작위 대비 우위"는 확인했지만
  "이 정확한 파라미터 조합을 고른 행위 자체의 과최적화"까지 완전히 제거하진 못함).
- 정리: `scripts/_sharpe_research_round4.py`, `_sharpe_round4_results.json` 등 연구용 스크래치는
  작업 완료 후 삭제.

### 작업 22 (2026-08-13): 6~8라운드 연구 — 유니버스 확장이 새 챔피언, 2008 금융위기로 진짜 아웃오브샘플 검증

사용자가 "이어서 분석 리포트 실험 및 생성해줘"라고 요청 → 작업21(No.06)이 남긴 숙제 3개(L2 이진
시장필터, 좁은 자산군, "같은 강세장 안에서만 쪼갠" 하위기간 검증의 한계)를 마저 공략.

- **H18(연속 시장필터, 기각)**: `core.market_regime.py`의 3개 룰(200일선 위치·골든/데드크로스·
  52주 낙폭)을 그대로 합성해 -75~+75 연속 점수를 만들고 이진 50%컷 대신 선형 노출배율로
  스케일링 → 예상과 반대로 샤프 0.97로 이진 방식(1.05)보다 나빴다. MDD는 더 얕아졌지만
  (-12.52%) 애매한 국면에서도 계속 비중을 흔들어 수익을 함께 깎은 게 원인(누적 +87.41%로 급감) —
  이진 컷을 그대로 유지하기로 결정.
- **H19(유니버스 확장, 채택 — 새 챔피언)**: Antonacci Composite Dual Momentum 아이디어대로
  국제주식(EFA)·하이일드(HYG)·원자재(DBC)를 후보군에 추가(총 17자산) → top4·이진필터 조합이
  샤프 1.10(No.06 챔피언 1.05 대비 개선), 하위기간(2019-08~2023-01 vs 2023-01~2026-08) 격차가
  0.07(1.08 vs 1.15)로 **지금까지 모든 라운드 중 가장 강건** — 자산군을 넓힐수록 특정 구간
  의존도가 줄어든다는 근거.
- **H20(2008년 금융위기 아웃오브샘플, 이번 라운드 핵심 발견)**: 섹터 ETF(XLC 등)는 2018년 상장이라
  2008년까지 못 가지만, SPY+TLT+GLD 3자산만으로는 2007-01~2026-08(19년)까지 확장 가능 → 진짜
  다른 레짐에서 같은 로직(절대+상대모멘텀 top2, 이진 시장필터)을 검증. 19년 전체는 익숙한
  트레이드오프(원금수익률은 SPY보다 낮지만 MDD -23.51% vs SPY -56.47%로 위험조정 샤프 역전:
  0.77 vs 0.54, No.02 200일선 연구와 일치). **결정적 발견**: 2007-10~2009-06 금융위기 구간만
  떼어보면 SPY 매수보유가 -40.41%(MDD -56.47%) 무너질 때 멀티에셋 모멘텀은 오히려 +8.36%를
  벌었다 — 위기 시 채권·금이 최상위 모멘텀 후보로 뽑혀 자본을 흡수한 결과. No.06의 "채권·금 추가로
  MDD 개선" 주장을 2019~2026이 아니라 진짜 위기 한복판에서 직접 확인한 셈 — 지금까지 연구 전체에서
  가장 설득력 있는 단일 증거.
- **업데이트된 챔피언**: 11개 GICS 섹터+TLT+IEF+GLD+EFA+HYG+DBC(17자산)·top4·12개월 모멘텀·
  SPY<200일선이면 이진 50%축소·월간 리밸런싱·왕복0.1%비용 → 샤프 1.10, 하위기간 격차 0.07.
- **리포트**: `docs/reports/momentum_rotation_gfc_validation.html`(No.07, No.06 후속) 신규 작성,
  같은 디자인 시스템 유지, Artifact 발행(https://claude.ai/code/artifact/67392af1-1802-475e-8d3e-c674d34c4d5a),
  README.md 인덱스에 등록. **버그 학습 반영**: 지난 No.06 발행 때 Artifact 파일에 직접
  `<!doctype html><html><head>...</head><body>` 래퍼를 넣어 이중 래핑됐던 실수를 이번엔
  피함 — `docs/reports/`용 완성 파일은 래퍼 포함(자매 파일들과 동일 컨벤션), Artifact 발행용은
  래퍼를 벗긴 별도 소스(`/tmp/gfc_validation_source.html`)를 만들어 발행.
- 정리: `scripts/_sharpe_research_round6.py`, `_sharpe_round6_results.json`은 연구용 스크래치라
  작업 완료 후 삭제.

### 작업 23 (2026-08-13, 같은 날 후속): 9라운드 — 닷컴버블·2022약세장 추가 검증, 이진 필터 재확인

사용자가 "이 리포트(No.07)에서 추후 연구 및 취약점을 디벨롭시켜서 실험을 진행하고 이어서
기록해봐"라고 요청 → No.07 §5가 남긴 한계 3개(H20이 2008 단일 위기·3자산 근사뿐이었음, 연속필터
실패가 선형매핑 탓일 수 있음, 다중비교 위험)를 공략.

- **H21(닷컴버블 2000~2003, 부분 검증)**: TLT(2002년 상장)·GLD(2004년 상장)가 닷컴버블을
  커버 못해 VUSTX(1990년부터 있는 장기국채 뮤추얼펀드)로 근사, SPY+VUSTX 2자산 모멘텀을
  2000년부터 재현. 결과: 닷컴버블 구간(2000-03~2002-10)에 전략 &minus;10.47%로 SPY
  &minus;36.06%보다는 낫지만 2008년처럼 플러스 전환은 못 했다. 더 중요한 발견 — **26년 전체
  (2000~2026)로 보면 SPY 매수보유 샤프(0.42)가 이 2자산 모멘텀(0.31)을 오히려 이긴다** —
  No.07의 낙관적 결론에 중요한 균형추. 다만 이건 자산 2개뿐인 근사판이라 17자산 챔피언의
  결론을 그대로 부정하진 않는다는 점을 명시.
- **H22(2022년 약세장, 핵심 발견)**: 2022년은 주식·채권이 동시에 무너져 전통적 60/40 분산이
  깨진 해로 자주 인용됨 — 17자산 챔피언이 "채권으로 도망가는" 낡은 로직이었다면 실패했을 시험대.
  실측: TLT 단독 보유 시 &minus;33.40%(샤프 &minus;2.41, SPY보다도 나쁨)로 채권 자체가 최악의
  자산이었는데도, 17자산 챔피언은 **+4.22%**(샤프 0.51, MDD &minus;8.38%)로 플러스 마감. 월별
  실제 로테이션 로그를 직접 뽑아보니 원자재(DBC)·에너지(XLE)가 연중 상위권을 지켰고 채권(TLT/IEF)은
  2022년 단 한 번도 상위 4위 안에 들지 못했다 — "위기엔 무조건 채권"이 아니라 "그 시점 실제로
  강한 자산을 따라간다"는 이 전략의 진짜 메커니즘을 직접 증명.
- **H23(시그모이드 연속필터, 재기각)**: No.07 H18의 선형 연속필터 실패가 매핑 형태 문제였는지
  확인하려 시그모이드(S자형, steepness 10/20/30)로 재시도 → 가파를수록(이진에 근접) 개선되는
  경향은 있었지만(1.04→1.06) 이진 필터(1.10)를 끝내 못 넘음 — "연속 신호 자체가 이 전략엔 안
  맞는다"는 결론을 강화, 이진 필터 선택 재확인.
- **리포트**: `docs/reports/momentum_rotation_2022_dotcom_stress.html`(No.08, No.07 후속) 작성,
  Artifact 발행(https://claude.ai/code/artifact/52b013a4-f232-4a70-865f-73476c8c9c13), README.md
  인덱스 등록. 이번에도 발행용은 래퍼 벗긴 별도 소스(`/tmp/dotcom_2022_source.html`) 사용.
- 정리: `scripts/_sharpe_research_round9.py`, `_sharpe_round9_results.json`은 연구용 스크래치라
  작업 완료 후 삭제.

### 작업 24 (2026-08-13, 같은 날 후속): 10라운드 — 개별주 혼합 유니버스, 사후편향 자체발견·재검증

사용자가 "리밸런싱을 신호 대기·매수 방식이 아니라 반도체주·통신주 등 개별 종목까지 시황 따라
재분배하는 방식"으로 연구해달라고 요청. 문제 상황이 모호해 먼저 AskUserQuestion 3개로 확인:
①채권/금/원자재도 뺄지(→ 주식 중심, 금/은은 연구자 판단에 위임) ②결과물 형태(→ 리포트) ③섹터
ETF뿐 아니라 개별주도 섞을지(→ 네, 혼합).

- **H24(섹터ETF vs 개별주혼합)**: 반도체(NVDA·AMD·AVGO·QCOM·TXN·INTC)·통신(VZ·T·TMUS·GOOGL·META)
  등 24개 개별주를 손으로 골라 11개 섹터 ETF에 더한 35종목 유니버스로 같은 로직(12개월 모멘텀,
  월간 리밸런싱, 이진 시장필터) 실행 → top4 기준 샤프 0.98(섹터ETF만)→1.23(혼합), 누적수익률
  +156.80%→+775.95%로 급등.
- **자기검증(중요)**: 화려한 숫자를 그대로 안 믿고 로테이션 기록을 직접 열어봄 → 전체 픽의
  95.3%가 개별주, 그마저 NVDA·AMD·AVGO 소수 종목이 계속 반복. 하위기간(2019-08~2023-01 vs
  2023-01~2026-08) 샤프 격차 0.74로 지금까지 10라운드 통틀어 최악(직전 최고 기록은 0.44) —
  "손으로 고른 반도체 종목이 이미 2026년 시점에 AI 랠리 승자였음을 알고 골랐다"는 사후편향
  의심을 스스로 제기. `core.strategy_tuning.sample_universe(as_of_date=...)`(이전 세션에서
  생존편향 방지용으로 쓰던, point-in-time S&P500 편입종목 기반 섹터균등 표본추출)로 편향 없이
  재검증했으나 샤프가 오히려 더 높게(1.33~1.39) 나오고 NVDA가 여전히 자주 등장 — "특정 리스트를
  잘못 골랐다"는 좁은 의미의 편향은 아니었지만, 더 구조적인 문제 발견: `sample_universe`는 종목
  편입 여부는 point-in-time이어도 표본 추출 시 사용하는 시가총액은 `screener.get_fundamentals()`가
  항상 **현재(2026년) 시점** 데이터만 제공해 여전히 "그때 있었고 지금 보니 컸던 종목" 위주로
  뽑힌다 — 과거 시점 시가총액 스냅샷 데이터소스가 이 저장소에 없다는 진짜 인프라 공백을 확인.
- **부수 실험 2건**: 종목당 비중상한(20~30%) 테스트는 top6 균등비중(16.7%)이 이미 모든 상한보다
  작아 한 번도 발동 안 해 설계 실패로 결론 못 냄(다음에 10~15% 상한 또는 top3로 재시도 필요).
  금/은(GLD/SLV) 오버레이는 전체기간 평균 샤프에 거의 영향 없음(No.08의 "위기 구간 한정 가치"
  결론과 일치, 상충 아님).
- **최종 판단**: 개별주 혼합의 결과는 아직 채택하지 않음 — No.07/08의 17자산 챔피언(순열검정까지
  거친 가장 검증된 설정)을 유지 권고. 개별주 확장은 과거 시점 시가총액 인프라가 갖춰지면 다시
  검증할 후속 과제로 명시.
- **리포트**: `docs/reports/momentum_rotation_individual_stocks.html`(No.09, No.08 후속) 작성,
  Artifact 발행(https://claude.ai/code/artifact/4f5f456a-fd0a-475e-9859-0a48a9e64716), README.md
  읽는 순서·파일목록 갱신.
- 정리: `scripts/_sharpe_research_round10.py`, `_sharpe_round10_results.json`은 연구용
  스크래치라 작업 완료 후 삭제.

### 작업 25 (2026-08-13, 같은 날 후속): point-in-time 시가총액 인프라 신규 구축 — No.09 사후편향 의심 최종 검증

사용자가 No.09의 "인프라가 갖춰지면 다시 검증할 과제" 발언을 보고 "그 인프라를 내 엔진의 주식
데이터 조회 방식을 차용해서 직접 만들어라, 시간이 오래 걸려도 되고 자원은 충분하다"고 요청.

- **신규 core 모듈 `core/point_in_time_market_cap.py`**: `core.screener.get_fundamentals()`가
  항상 현재 시점 정보만 주는 한계를 풀기 위해, `yfinance.Ticker.get_shares_full()`(분기별
  발행주식수 이력, SEC 정기공시 기준 스냅샷)을 새로 활용 — 그 시점까지의 최신 발행주식수 x
  그 시점 종가(`core.market_data.get_price_history` 재사용, 이미 영구 로컬 캐시 보유)로
  point-in-time 시가총액을 근사. `get_shares_outstanding_history`/`get_market_cap_asof`/
  `get_market_caps_asof_batch`(core.market_data와 동일한 ThreadPoolExecutor 병렬화 패턴) 3개
  함수, 발행주식수 캐시는 파일 캐시(14일 TTL — 가격보다 훨씬 느리게 바뀌므로).
- **구현 중 발견한 실제 버그(중요)**: NVDA 2019-08-12 시가총액을 계산해보니 $2.3B로 나옴(실제
  ~$95B) — 원인 추적 결과 `get_price_history`의 종가가 `auto_adjust=False`로 받아도 **액면분할은
  자동 반영**(배당만 별도)되는데, `get_shares_full()`의 발행주식수는 그 시점 실제(미조정) 값이라
  두 소스의 조정 기준이 안 맞았다. NVDA(2021 4:1 + 2024 10:1 = 40배 분할)는 40배 과소평가, AAPL
  (2020 4:1)은 4배 과소평가, GE(2021 1:8 역병합)는 약 5배 과대평가되고 있었다. `yf.Ticker.splits`로
  as_of_date 이후 분할 이력을 찾아 발행주식수에 누적 배율을 곱하는 `_cumulative_split_factor_after`
  보정 함수 추가로 수정 — 수정 후 NVDA $92.2B/AAPL $906.0B/GE $79.0B로 실제 공개 수치와 합리적으로
  일치(META/XOM처럼 분할 이력 없는 종목은 원래도 정확했음, 대조군으로 확인). `tests/
  test_point_in_time_market_cap.py` 11개(분할 보정 케이스 2개 포함) 신규 작성, 네트워크는
  monkeypatch로 격리(core.screener 테스트와 동일 패턴).
- **`core.strategy_tuning.sample_universe()`에 `use_point_in_time_market_cap` 옵션 추가**(기본
  False — 기존 야간 튜닝 파이프라인 등 호출부 동작은 그대로 유지, opt-in만). True면 섹터 할당량을
  채우는 시가총액 랭킹 자체를 새 point-in-time 함수로 계산 — 기존엔 `as_of_date`로 종목 편입
  여부만 그 시점 기준이고 랭킹은 여전히 "지금" 시가총액을 쓰던 한계(No.09가 발견)를 해소.
- **재검증 결과(결정적)**: `sample_universe(n=30, as_of_date="2019-08-12",
  use_point_in_time_market_cap=True)`로 뽑으니 표본이 완전히 바뀜 — NVDA/AMD/AVGO는 아예 없고
  MSFT($1.04T)/AAPL($906B)/AMZN($883B)/JPM($344B)/XOM($295B) 같은 2019년 당시 실제 블루칩
  위주(전체 유니버스 발행주식수/분할이력 계산에 82초 소요). 이 표본으로 No.09와 동일한 로직(top4,
  12개월 모멘텀, 월간 리밸런싱, 이진 시장필터) 재실행 → **샤프 1.23(No.09 편향 결과) → 0.68로
  폭락, 섹터 ETF 전용 대조군(0.98)보다도 나쁨**. 하위기간 격차도 0.19로 No.09의 0.74보다 훨씬
  작아(전반부 0.78/후반부 0.59) 특정 랠리 구간에 쏠린 우연이 아니라 진짜 일관되게 열등하다는
  뜻 — No.09의 사후편향 의심이 완전히 확정됨.
- **최종 결론**: 개별주 확장 갈래는 공식 기각. 챔피언 전략은 No.07/08의 17자산(11섹터+채권+금+
  국제주식+원자재) 그대로 유지. `core/point_in_time_market_cap.py`는 일회성이 아니라 재사용
  가능한 core 모듈로 남겨둠(앞으로 point-in-time 종목 선정이 필요한 어떤 리서치에도 재사용 가능).
- **리포트**: `docs/reports/momentum_rotation_point_in_time_verdict.html`(No.10, No.09 후속·
  최종) 작성, Artifact 발행(https://claude.ai/code/artifact/765060f1-65ad-4c1b-9958-fce14aa490dc),
  README.md 읽는 순서·파일목록 갱신.
- 검증: `core/point_in_time_market_cap.py` 신규 pytest 11개 + 전체 스위트(714개, 회귀 없음)
  통과. 재검증 스크립트(`scripts/_sharpe_research_round11.py`)는 연구용 스크래치라 작업 완료
  후 삭제 — 단, 위 core 모듈과 pytest는 영구 보존.

### 작업 26 (2026-08-16): 개별주 텐베거 발굴 방법론 — 새 리서치 트랙(트랙 C) 신설

사용자가 "개별주, 텐베거 발견 방법에 대해 연구를 맡길거야. 자본공학적으로 per/pbr 등은 얼마여야
하는지, 현재 시황은 어느섹터가 뜨거운지 정량적으로 분석하는 방법과 함께 좋은 기업을 발굴하는
방법에 대해서 연구를 해봐"라고 요청 — 지금까지의 No.04~08 시리즈(트랙 B)는 전부 "시장 전체를
어떻게 사고파느냐"를 다루는 하향식 국면/로테이션 연구였는데, 이번엔 궤를 달리해 개별 종목을
상향식으로 골라내는 방법론을 다뤘다. 정답이 없다는 걸 사용자도 인정하면서도 "명답에 최대한
수렴"시켜달라는 요청이라 딥서치(WebSearch 12회)와 이 저장소의 기존 검증된 인프라 실측을
결합했다.

- **PER/PBR을 감이 아니라 대수로 유도**: 고든성장모형에서 정당 트레일링 P/E = (1−b)(1+g)/(r−g)
  (b=이익유보율, g=지속가능성장률=b×ROE)를 직접 전개해, "성장주라서 P/E가 높다"는 말이 정확히는
  "재투자율×ROE가 커서 g가 r에 근접해 분모가 작아진다"는 뜻임을 보였다. PBR도 잔여이익모형에서
  P/B=(ROE−g)/(r−g)로 유도 — PBR이 낮은 게 항상 저평가가 아니라 "ROE가 요구수익률보다 낮은 상태를
  시장이 정확히 반영한 것"일 수 있다는, 통념을 정면으로 반박하는 결론.
- **딥서치로 실전 벤치마크 확보**: 그레이엄의 P/E&lt;15·P/B&lt;1.5·그레이엄넘버(P/E×P/B≤22.5,
  《현명한 투자자》 원전 확인), 린치의 PEG≈1 규칙(《월가의 영웅》 원문 인용 확인), Fama-French
  HML 가치 프리미엄(연 3~5%, 13개 해외시장 중 12곳 재현), 그리고 결정적으로 **Baruch Lev &
  Feng Gu의 무형자산 회계연구**(R&D·브랜드가 자산화 안 되고 즉시 비용처리되어 장부가·주가
  상관관계가 1950~2013년 80%→25%로 하락) — PBR이 자산경량(소프트웨어·플랫폼) 기업에는 구조적으로
  왜곡된 신호를 준다는 근거를 확보해, 성장률 티어별 적정 PER/PBR/PEG 표에 반영했다.
- **"지금 어느 섹터가 뜨거운가"는 새로 만들지 않고 기존 엔진을 실제로 호출**: 사용자가 미리
  요구한 대로 `docs/MARKET_REGIME_SECTOR_STRENGTH_SPEC.md`의 기존 검증된 방법론(IBD RS
  Rating·200일선·골든/데드크로스·시장폭)을 그대로 재사용 — `core.sector_strength.
  get_latest_theme_strength_snapshot()`/`core.market_regime.get_latest_market_regime_snapshot()`을
  직접 호출해 실측했다(기준일 2026-08-14). 결과: 반도체가 RS 100(1위)이지만 추세는 "하락"
  (최근 20거래일 모멘텀 -9.65p) — 레벨은 최강이나 RRG 관점 Weakening에 가깝다는 흥미로운 뉘앙스를
  발견. 시장 국면은 종합점수 74.7로 강세장(200일선 위·골든크로스·시장폭 72.9%·낙폭 -0.2% 전부
  강세 신호).
- **린치·오닐·품질팩터 종합 스크리닝을 실제로 실행**: 딥서치로 린치의 6가지 기업유형(패스트
  그로워가 텐베거 카테고리)·13개 정성 기준, 오닐 CANSLIM 7요소, AQR의 Quality Minus Junk
  팩터(Asness/Frazzini/Pedersen), 2025년 신규 실증연구("The Alchemy of Multibagger Stocks",
  Yartseva, 2009~2024 464개 10배종목 분석 — 소형·고수익성 조합이 유의미)를 종합해
  `core.screener.screen()`(핫섹터+시총 $300억 상한+200일선 위)→`core.valuation`
  (PEG≤1.5·성장률≥15%·ROE프록시≥15%)의 2단계 필터를 만들고 실제 S&P500 503종목에 실행
  (`analysis/2026-08-16_tenbagger_stock_picking/gather_data.py`). **중요한 실증적 발견**:
  1위 핫섹터인 정보기술(반도체·클라우드·사이버보안)에서는 1단계를 통과한 종목이 0개였다 —
  S&P500 소속 대형 기술주가 이미 전부 시총 $300억을 훌쩍 넘는 초대형주이기 때문. 이는
  "S&P500 유니버스로는 가장 뜨거운 섹터의 진짜 텐베거 후보를 찾을 수 없다"는, 사전에 명시한
  스코프 한계(소형주 효과·S&P500 하한 시총 제약)가 실제로 그대로 드러난 사례. 최종 2단계
  필터를 통과한 건 에너지 섹터의 APA(PEG 0.26, PER 8.2, 이익성장률 32.2%)와 산업재 섹터의
  JBHT(PEG 0.87, PER 39.8, 이익성장률 45.8%) 2종목뿐 — 매수 추천이 아니라 "방법론이 실제로
  작동한다"는 예시로만 리포트에 실었다.
- **캐시 재사용 관련 작업 메모**: 이 세션은 격리된 git worktree에서 진행됐는데(worktree는 `data/`
  캐시를 공유하지 않음), `core.screener.screen(include_technicals=True)`가 200일선 판정에 쓰는
  `get_price_history()`가 로컬 parquet 캐시 없이 첫 조회하면 yfinance 기본기간(약 1개월)만
  받아와 200일선 계산이 불가능해지는 기존 알려진 함정(`core/sector_strength.py` 주석에 이미
  문서화된 문제)에 실제로 걸렸다 — 메인 체크아웃의 기존 `data/cache/*.parquet`(가격) +
  `fundamentals_*.json`/`valuation_inputs_*.json`(펀더멘털) 캐시를 그대로 복사해 해결(재구현이
  아니라 이미 실제로 조회됐던 캐시 재사용 — "라이브 데이터가 느리면 저장소의 기존 캐싱이 반환하는
  값을 쓰라"는 작업 지시와 일치). `cp -n`(no-clobber)로 먼저 일부만 복사했다가 그 사이 스크립트가
  자체적으로 만든 불완전한(짧은 기간) parquet 파일이 이후 전체 복사를 막는 자기 자신과의 충돌을
  겪어, 전체 삭제 후 강제 재복사로 해결한 것도 기록.
- **산출물**: `analysis/2026-08-16_tenbagger_stock_picking/`(`gather_data.py`+`report_data.json`+
  `build_report.py`+`final_report.html`), `docs/reports/tenbagger_stock_picking_research.html`로
  사본 배포, `docs/reports/README.md`에 새 "트랙 C — 개별주 발굴(독립)" 섹션 신설(트랙 B의
  순차 사슬에 억지로 끼워넣지 않음). 코드(`core/`, `app/`) 변경 없음 — 순수 리서치 리포트.

### 작업 27 (2026-08-19): IREN류 변동성 테마주 리서치 — 트랙 C 두 번째 리포트

사용자가 "IREN 같은 주식을 사는 것을 좋아한다 — 이런 종목의 특징과, 이런 변동성 큰 종목으로 최대한
돈을 벌 수 있는 방법을 연구해달라"고 요청. 사전 확인 질문 두 개에 "실제 백테스트까지 가라(문헌
정리로 끝내지 말 것)", "IREN 한 종목이 아니라 유사 테마 바스켓으로 일반화해라"로 답변받아 그
방향으로 진행. `docs/reports/tenbagger_stock_picking_research.html`(트랙 C 첫 리포트)이 스스로
밝힌 한계 — S&P500 유니버스가 진짜 소형·테마 종목을 구조적으로 배제한다(가장 뜨거운 섹터에서도
시총상한 통과 종목이 0개) — 를 정면으로 다루는 후속작이라 트랙 C 두 번째 항목으로 넣었다(트랙 B
순차 체인과는 무관 — 하향식 섹터 로테이션이 아니라 상향식 개별/바스켓 종목 매매법이라 독립 트랙
유지).

- **바스켓 구성(웹 리서치로 실제 확인)**: 비트코인 채굴→AI/HPC 데이터센터 피벗 테마
  IREN·CIFR·CLSK·WULF·HUT·BTDR(+CORZ는 2024-01 파산 재상장이라 별도 표기)를 확인. "순수 무피벗
  대조군"으로 MARA·RIOT을 넣으려 했으나, 실제 조사 결과 MARA·RIOT은 물론 Bitfarms까지 이미 AI로
  피벗 중이라는 것을 발견 — "순수 채굴주" 자체가 2026년 기준 사실상 소멸한 카테고리라는 점을
  가감 없이 리포트에 반영(대조군을 "상대적으로 채굴 비중이 큰 종목"으로 재정의).
- **특징 실측**: yfinance `.info`로 베타(2.51~6.11, 평균 4.3대)·공매도 비중(11~40%, 평균
  24.7%)·기관보유율·부채/현금 구조를 실측(예: IREN의 마이크로소프트 97억 달러 AI 클라우드 계약과
  이를 뒷받침하는 36.5억 달러 GPU 파이낸싱, HUT의 부채 76.7억 달러 vs 현금 2.3억 달러). 학술
  대응추(counterweight)로 Bali·Cakici·Whitelaw(2011) MAX 효과, Ang·Hodrick·Xing·Zhang(2006/2009)
  이디오싱크래틱 변동성 퍼즐을 실제 논문 링크와 함께 인용 — "복권형 종목을 장기·무규율로 들고
  있으면 위험조정수익률이 저조할 수 있다"는, 사용자 선호와 정면으로 긴장되는 내용을 그대로 실었다
  (예: MARA를 2014년 상장일부터 그대로 들고 있었다면 12년 뒤 지금도 원금 대비 -80.4%, CAGR -12.1%).
- **실제 백테스트(신규 `analysis/2026-08-16_iren_volatile_momentum_stocks/`, `core.backtest_engine`/
  `core.position_sizing` 재사용, 공통구간 2022-05-19~2026-08-18 [IREN 상장일 기준 모멘텀 웜업
  126거래일 확보 최단 시작일], 왕복 0.1% 거래비용)**:
  1. 베이스라인 매수후보유 — IREN 단일종목은 상장일부터 누적 +83.5%(CAGR 13.65%)지만 MDD가
     **-95.7%**(!). 공통구간 기준으로는 CAGR 56.28%/MDD -84.28%/샤프 0.94. 6종 바스켓 정적
     균등보유는 MDD -65.59%로 크게 완화되지만 샤프는 0.88로 오히려 근소하게 낮음(분산 효과는
     샤프가 아니라 MDD·개별기업 리스크 쪽에서 뚜렷).
  2. `analysis/kostolany_market_report_2026-08-12/momentum_rotation.py`의 듀얼모멘텀 로테이션을
     이 바스켓에 그대로 이식했으나 기대에 못 미침(파라미터 스윕 전체 샤프 0.37~0.82) — 섹터 ETF
     로테이션(No.05~08)과 달리 이 바스켓은 종목 6~9개가 전부 같은 두 거시동인(BTC 가격·AI 서사)에
     묶여 있어 로테이션이 성립하려면 필요한 폭(breadth)이 없다는 것을 실측으로 확인(No.09~10의
     개별주 확장 기각과 결이 비슷한 구조적 한계).
  3. 20거래일 돈치안 브레이크아웃+% 트레일링스탑(15~35% 스윕)을 단일종목/바스켓에 적용 —
     **바스켓+15% 스탑이 전체 비교 중 최고 성과(샤프 1.31, CAGR 107.48%, MDD -71.00%)**로 챔피언
     채택. IREN 단일종목도 스탑폭 전 구간(15~35%)에서 샤프 1.2 안팎으로 안정적이라 과최적화
     위험이 상대적으로 낮아 보임.
  4. 챔피언에 `core.position_sizing.realized_annual_volatility_pct`/`volatility_target_weight`로
     변동성타게팅 오버레이 — 샤프는 개선 못함(무레버리지 최선 1.14 < 챔피언 1.31, 이 저장소
     No.06과 같은 패턴 재현)이나, 목표변동성을 15%로 낮추면 MDD가 -71.0%→**-29.9%**까지 줄어드는
     대신 CAGR도 107.5%→20.3%로 축소 — "수익 증대 도구"가 아니라 "감당 가능한 낙폭으로 위험예산을
     재단하는 도구"라는 결론.
  5. 강건성 체크: CORZ 포함 7종(구간 2024-07-25~, 더 짧음), 대조군 포함 8종 양쪽에서 "정적
     균등보유 > 모멘텀 로테이션" 패턴이 동일하게 재현됨을 확인.
- **`core.position_sizing.fixed_fractional_size()` 실사용 예시**도 리포트에 실측 수치로 포함(IREN
  진입가 $58.06, 15% 스탑, 계좌 2% 리스크 → 계좌의 13.33%만 매수).
- **한계를 정직하게 명시**: 공통 백테스트 구간이 약 4.25년뿐(IREN이 2021-11 상장이라 더 확보 불가),
  이 구간이 BTC·AI 인프라 동시 초강세장이었다는 것, 6~9종목·소수 파라미터 스윕이라 04장 학술
  문헌의 대규모 횡단면 증거를 반박할 통계적 힘이 없다는 것, 순열검정/워크포워드 통계적 유의성
  검정은 이번 범위에 포함하지 않았다는 것을 결론부에 그대로 남김 — "이런 종목을 사는 것 자체"가
  아니라 "사이징·청산 규율 없이 사는 것"이 문제라는 프레임으로 종합.
- 산출물: `analysis/2026-08-16_iren_volatile_momentum_stocks/`(`common.py`/`backtest.py`/
  `build_report.py`/`report_data.json`/`ticker_info.json`/`final_report.html` 및 스윕 CSV 3종),
  사본을 `docs/reports/iren_volatile_momentum_stocks_research.html`로 복사하고
  `docs/reports/README.md` 트랙 C에 두 번째 항목으로 추가. `core/`·`app/`는 건드리지 않음(트랙 C
  선례와 동일하게 리포트 전용 산출물, `core.backtest_engine`/`core.position_sizing`/
  `core.market_data`는 읽기 전용으로 재사용만 함).

### 작업 28 (2026-08-19, 같은 날 후속): IREN류 종목 베타/알파 분리 전략 — 가설 4개 검증 (트랙 C 세 번째 리포트)

작업 27과 병렬로 두 번째 에이전트를 분화해 요청. 사용자가 "이런 소형주의 경우 어떤 전략을 세워야
beta를 지키며 alpha를 쫓을 수 있는지 구체적인 가설을 제시하면서 연구해달라"고 요청 — 작업 27이
"변동성을 어떻게 타서 돈을 버는가"(진입/청산/사이징)를 다뤘다면, 이번은 "원치 않는 베타는
걷어내고 종목 고유의 알파만 남길 수 있는가"라는 포트폴리오 구성/헤지 질문. 같은 시각 두 에이전트가
`docs/reports/README.md`/`PROGRESS.md`를 동시에 건드리면 충돌할 위험이 있어, 이번 에이전트에는
그 두 파일을 건드리지 말라고 명시적으로 지시하고 산출물만 받아 내(오케스트레이터)가 직접 반영.

- **가설 4개를 명시적으로 세우고 각각 실측 검증**(작업 20/21의 "가설→실측→솔직 보고" 패턴 재사용):
  - **H1 시장 베타 헤지 기각**: 롤링 회귀베타만큼 SPY 숏 헤지를 걸어도 7종목 중 0종목이 샤프
    개선(IREN 0.96→0.53, 바스켓 1.07→0.55) — 헤지가 위험보다 상승분을 더 깎아, "이 종목군의
    초과수익 자체가 베타"라는 결론.
  - **H2 테마베타(비트코인) 분해 부분채택**: BTC단독 회귀 R²가 시장단독보다 큰 종목이 7개 중
    4개(평균 0.134 vs 0.119), 시장+BTC 2요인 결합회귀 R²는 항상 둘 중 하나보다 높음(평균
    0.183) — BTC 노출이 실질적 정보를 담고 있다는 근거는 확보했지만, BTC헤지가 시장헤지보다는
    나아도(7종목 중 6종목 샤프 우위) 무헤지를 이긴 경우는 없었음.
  - **H3 베팅어게인스트베타(Frazzini & Pedersen 2014, JFE 인용) 저베타 틸트 부분채택**: 주표본
    (6종목·4.75년)에서는 동일가중(0.864)·고베타(0.785)·모멘텀(0.812)을 모두 제치고 샤프
    0.878로 1위였지만, 강건성 표본(7종목·2.5년, 최근 AI 랠리 구간)에서는 모멘텀(1.45)에
    졌음(0.878→저베타 여전히 EW/고베타는 이김). 완전투자 상태에서 상대적으로 낮은 베타를
    고르는 건 국면에 따라 갈린다는 뜻.
  - **H4 고정 베타예산(0.3) 역베타가중 사이징 기각**: 주표본에서 동일가중이 역베타가중을 샤프
    (0.775 vs 0.482)·연율화알파(3.87% vs 2.15%) 모두에서 하회 — 소형주 베타 추정치의 노이즈가
    커서 역베타가중이 우연히 "저베타로 보이는" 종목에 과다 쏠린 것으로 추정. 강건성 표본에서는
    반전됐지만 격차가 미미해 노이즈로 판단.
  - H5(옵션 기반 헤지)는 이 저장소에 옵션 백테스트 인프라가 없어 억지로 근사하지 않고 정성적
    논의(고변동성 종목일수록 프리미엄이 비싸고, 상단을 캡하는 구조 자체가 이 종목군의 알파원인
    재평가 서사와 충돌한다는 논리)로만 다룸.
- **최종 결론**: 베타를 물리적으로 제거하는 헤지(H1)는 전부 손해, 베타를 "인지"하는 것(H2)까지는
  도움이 됐지만 그 인지를 역베타가중이라는 기계적 사이징 규칙(H4)으로 바꾸면 오히려 노이즈만
  키움 — 유일하게 국면부 조건부로 통한 것(H3)도 깔끔한 채택은 아니었음. 4가설 중 깔끔한 채택
  0개·부분채택 2개·기각 2개로, "베타/알파 분리"라는 발상 자체가 이 종목군에서는 생각보다 잘 안
  먹힌다는 결론을 솔직하게 냄(작업 27의 결론 — "사이징·청산 규율이 핵심이지 헤지 구조가 아니다"
  — 와 정합적).
- 딥서치로 실제 문헌 인용 확보: Frazzini & Pedersen(2014, JFE) "Betting Against Beta"를 실명
  인용. 유니버스(IREN·CIFR·CLSK·WULF·HUT·CORZ·BTDR)도 웹 리서치로 2026-08 기준 AI/HPC 피벗
  현황을 재확인.
- 산출물: `analysis/2026-08-19_iren_beta_alpha_hedging/`(`common.py`+`h1~h4_*.py`+`run_all.py`+
  `report_data.json`+`build_report.py`+`final_report.html`), 사본을
  `docs/reports/iren_beta_alpha_hedging_research.html`로 복사, `docs/reports/README.md` 트랙 C에
  세 번째 항목으로 추가(README/PROGRESS 반영은 에이전트가 아니라 오케스트레이터가 직접 수행).
  `core/`·`app/`는 건드리지 않음 — 회귀·베타 계산은 numpy만으로 직접 구현(저장소에 scipy/
  statsmodels 미설치 확인 후 새 의존성 추가 없이 처리).

### 작업 29 (2026-08-19, 같은 날 후속): "시장을 이기는 방법" 종합 가설 4개 — 트랙 D 신설 (1/2 완료)

사용자가 "앞선 연구의 이후 사후 연구를 너가 이전까지의 연구내용을 바탕으로 가설을 세우고 실험을
통해 시장을 이기는 방법을 연구해. 2시간 정도 연구를 진행해"라고 요청 — 주제 지정 없이 오케스트레이터
(나)가 지금까지의 트랙 B(섹터 로테이션)·트랙 C(개별주 텐베거·IREN류 변동성·베타/알파)를 전부
종합해 가설 4개를 직접 세우고, 병렬 에이전트 2개로 나눠 검증하도록 지시. 트랙 B/C 어느 한쪽에도
안 맞아 새 "트랙 D — 종합 가설 검증"을 신설(둘 다 완료된 뒤 `docs/reports/README.md`에 반영).
이번 항목은 먼저 끝난 절반(H3/H4, `permutation_and_quality_momentum_research.html`)만 기록 — 나머지
절반(H1 코어-새틀라이트/H2 챔피언 베타 정체성)은 별도 항목으로 이어서 기록 예정.

- **가설 설계 근거**: H1(코어-새틀라이트)은 작업24/25(No.09/10)의 실패 원인 — "개별주를 통째로
  섞고 point-in-time 규율 없이 골랐다" — 을 정면으로 뒤집어, `core/point_in_time_market_cap.py`로
  편향을 걷어낸 채 소규모(15~20%)만 섞으면 다른 결과가 나오는지 검증. H2(챔피언 베타 정체성)는
  작업28에서 IREN류 개별종목에 걸었던 시장베타 헤지 테스트를, 트랙B 17자산 로테이션 챔피언 자체에
  똑같이 적용 — 그 챔피언의 초과수익이 진짜 알파인지 위장된 베타인지 확인. H3(순열검정 보강)은
  작업21에서 트랙B 챔피언에는 이미 적용했던 통계적 유의성 검증을, 작업27의 IREN 추세추종 챔피언에는
  아직 안 걸었다는 빈틈을 메움. H4(퀄리티-모멘텀 하이브리드)는 작업26의 퀄리티 필터(정적 1회 스크리닝)와
  작업19~23의 모멘텀 로테이션(순수 모멘텀 랭킹)이 지금까지 한 번도 결합된 적 없다는 빈틈을 메움.
- **H3 결과(부분채택)**: `core.backtest_engine`의 기존 셔플 인프라(작업13/14에서 만든 것, 재사용)로
  IREN 추세추종 챔피언을 재검증 — 바스켓 버전은 93번째 백분위(p≈0.075, 5% 문턱 미달), IREN
  단일종목 버전은 100번째 백분위(p≈0.005)로 훨씬 강함. 파라미터를 더 넓게 스윕해보니 15%/20일이
  고립된 스파이크가 아니라 10~30% 대역의 완만한 고원(10%스탑 샤프1.52)이라 과최적화 의심은 낮아짐 —
  다만 바스켓 채택 근거는 트랙B만큼 강하지 않다는 정직한 정정.
- **H4 결과(부분채택)**: S&P500 100종목 샘플에서 작업26의 PEG≤1.5/성장률≥15%/ROE프록시≥15%
  필터를 모멘텀 로테이션 앞단에 걸었더니(생존 26종목) 순수 모멘텀(샤프0.68)보다 나은 샤프
  0.82(SPY 0.81도 이김)를 기록했지만 트랙B 17자산 챔피언(샤프1.10)에는 못 미침. 작업26의 원래
  시총 300억달러 상한까지 같이 걸면(생존 8종목) 샤프가 0.37로 무너지고 31%의 달에 후보가 부족해
  현금화 — "퀄리티 스크리닝이 세질수록 로테이션에 필요한 폭(breadth)이 줄어든다"는 구조적 긴장을
  실측으로 확인.
- 산출물: `analysis/2026-08-19_permutation_and_quality_momentum_research/`(`h3_permutation_test.py`/
  `h4_quality_momentum_hybrid.py`/`merge_report_data.py`/`report_data.json`/`build_report.py`/
  `final_report.html`), 사본을 `docs/reports/permutation_and_quality_momentum_research.html`로
  복사, `docs/reports/README.md`에 신설 "트랙 D — 종합 가설 검증" 첫 항목으로 추가(README/PROGRESS
  반영은 두 에이전트 모두 건드리지 않도록 지시했고, 오케스트레이터가 직접 수행). `core/`·`app/`는
  건드리지 않음.

### 작업 30 (2026-08-20): "시장을 이기는 방법" 종합 가설 4개 — 트랙 D 완성 (2/2, H1/H2)

작업29의 나머지 절반. H1/H2 담당 에이전트가 세션 한도(API 사용량 리셋 2:40pm UTC)로 14단계 중 11에서
한 번 중단됐다가, 사용자가 "이어서 진행해"라고 요청해 `SendMessage`로 같은 에이전트를 재개시켜
완료. 재개 과정에서 발견한 사소한 문제: 이 에이전트의 워크트리가 point-in-time 인프라(작업25)가
main에 올라오기 전 시점에서 분기됐던 터라, 스스로 `core/point_in_time_market_cap.py` 등을 main에서
복사해와 임시로 언블록했는데 — 그중 `core/strategy_tuning.py`는 그 사이 다른 세션이 main에 올린
버그 수정(코스톨라니 스키마 제외 로직, "strategy" 키 누락 방어)이 반영되기 전 버전이었다. 병합 시
`diff`로 직접 대조해 core/ 변경분은 전부 버리고(에이전트가 만든 실제 산출물이 아니라 단순 환경
언블록용 복사본이었으므로) `analysis/`와 `docs/reports/*.html`만 반영 — main의 `core/`는 다른
세션의 최신 버그 수정을 그대로 유지.

- **H1 코어-새틀라이트 채택**: point-in-time 새틀라이트(분기~반기 리밸런싱, 그 시점 실제
  존재감 있던 종목만 후보, 12개월 모멘텀 상위 3개)를 트랙B 17자산 챔피언에 10~20% 얹었더니 두
  비중 모두 샤프 개선(챔피언 단독 1.03 → 10% 1.06 → 20% 1.05, MDD는 -17.7%대로 거의 그대로).
  새틀라이트 단독 샤프는 0.80(MDD -33.5%)에 불과해 "새틀라이트가 우수해서"가 아니라 저상관
  자산을 소량 섞는 분산효과 — No.09/10의 전면 기각과 달리, 작게·point-in-time 규율을 지키며
  섞으면 통한다는 조건부 정정.
- **H2 챔피언의 베타 정체성 기각(뉘앙스)**: 작업28의 IREN 베타헤지 방법론을 트랙B 챔피언 자체의
  수익률에 적용 — 테스트한 3개 구간(2019~2026/2015~2026/2008금융위기 포함 3자산 프록시) 전부
  롤링 시장베타 헤지가 샤프를 악화(예: 2015~2026 0.627→-0.053)시켜 IREN 종목군과 같은 패턴이
  재현됨. 다만 정적 회귀 젠센알파는 연율 +7.08%/+1.27%로 실재(CAGR의 17~52%) — "전부 베타"가
  아니라 "챔피언의 알파 자체가 국면별로 노출을 바꾸는 베타-타이밍이라, 정적 헤지가 그 타이밍
  메커니즘을 없애버린다"는 결론.
- **트랙 D 종합(4가설 전체)**: 깔끔한 채택 1개(H1)·부분채택 2개(H3/H4)·기각 1개(H2, 뉘앙스 있음)
  — "시장을 이긴다"는 것에 대해 이 라운드가 더한 것은, 정적 헤지·기계적 사이징 규칙(작업28 H1/H4,
  이번 H2)은 거의 항상 손해였고, 반대로 규율을 지킨 소규모 확장(point-in-time 새틀라이트, H1)과
  기존 신호에 보조 필터를 얹는 것(퀄리티 사전필터, H4)은 조건부로 통했다는 패턴 — "구조를
  뜯어고치기"보다 "기존 챔피언에 작게, 검증 가능하게 더하기"가 이 저장소 전체 연구에서 가장
  일관되게 이긴 접근이라는 메타 결론.
- 산출물: `analysis/2026-08-19_champion_beta_and_satellite_research/`(`champion_strategy.py`/
  `h1_core_satellite.py`/`h2_champion_beta_hedge.py`/`build_report_data.py`/`build_report.py`/
  `final_report.html`), 사본을 `docs/reports/champion_beta_and_satellite_research.html`로 복사,
  `docs/reports/README.md` 트랙 D에 두 번째 항목으로 추가. `core/`·`app/`는 최종적으로 건드리지
  않음(위 언블록용 사본은 병합 시 폐기).

### 작업 31 (2026-08-20, 같은 날 후속): 트랙D 메타 결론 3라운드 후속 — 새틀라이트 비중 프런티어 + 퀄리티 연성 블렌드

사용자가 "방금 그 리포트를 바탕으로 또 다시 새로운 가설을 만들어서 1시간 정도 연구를 진행하고
리포트를 작성해"라고 요청 — 작업30의 메타 결론("정적 규칙은 손해, 작게·검증가능하게 더하는 건
통한다")을 오케스트레이터가 직접 두 갈래로 더 쪼개 가설 3개(H5/H6/H7)를 세우고 단일 에이전트에
위임. 에이전트가 한 번은 자기 백그라운드 프로세스 완료를 수동 대기하다 멈춰(하네스가 에이전트 자신의
셸 백그라운드 잡 완료는 자동으로 재기동해주지 않음) `SendMessage`로 재개시켜 완료.

- **H5 새틀라이트 비중 프런티어 채택**: 작업30 H1이 10%/20%만 봤던 비중을 0~50%까지 정밀
  스윕(같은 point-in-time 새틀라이트 로직 재사용) — 샤프 1.03(0%)→1.09(15~20%, 정점)→1.03(50%)의
  완만한 곡선으로 H1의 10~20% 선택이 우연이 아니라 진짜 최적 구간 근처였음을 확인. MDD는 30%까지
  거의 그대로(-17.7%→-18.0%)다가 40~50%에서 급격히 악화(-18.6%→-20.8%) — 비중을 더 올릴수록
  위험이 수익 개선보다 빨리 커진다는 것도 정량 확인.
- **H6 경성 필터 → 연성 블렌드 기각**: 작업30 H4와 같은 표본으로 퀄리티·모멘텀을 Z-점수로 섞어
  순위를 매기니(이 저장소가 이미 문서화한 앙상블 스코어링 방식 재사용) 후보 폭 붕괴 문제는 실제로
  해결됐지만(월평균 후보 53개, 후보부족월 12.4% vs H4의 31%) 성과는 순수 모멘텀(샤프0.68)보다도
  낮음(50/50 블렌드 0.50, 모멘텀가중 30/70 블렌드 0.60) — H4의 하드 필터가 통했던 건 "퀄리티
  신호의 일반적 예측력"이 아니라 "그 시기 실제 승자가 몰려 있던 좁은 부분집합으로 우연히 좁혀졌기
  때문"이라는, H4 채택 근거 자체에 대한 정정에 가까운 발견.
- **H7 통합 챔피언 스킵**: 사전에 정한 규칙대로(패배한 요소를 억지로 결합하지 않는다) H6이
  베이스라인을 못 이겨 스킵 — 최종 결론은 H5만 그대로 채택(새틀라이트 15~20% + 순수 모멘텀 랭킹
  유지, 퀄리티 블렌드는 넣지 않음).
- 산출물: `analysis/2026-08-20_satellite_frontier_and_quality_blend_research/`
  (`h5_satellite_weight_sweep.py`/`h6_soft_quality_blend.py`/`build_report_data.py`/
  `build_report.py`/`final_report.html`), 사본을
  `docs/reports/satellite_frontier_and_quality_blend_research.html`로 복사, `docs/reports/README.md`
  트랙 D에 세 번째 항목으로 추가. `core/`·`app/`는 건드리지 않음.

### 작업 32 (2026-08-20, 같은 날 후속): 트랙D 4라운드 — 퀄리티 필터·새틀라이트 랜덤 구성 플라시보 검정

사용자가 "방금 그 리포트를 바탕으로 또 다시 새로운 가설을 만들어서 1시간 정도 연구를 진행하고
리포트를 작성해"라고 재요청 — 작업31 H6이 말로만 의심하고 실측은 안 했던 것("하드 필터가 통한 건
퀄리티 신호가 아니라 우연히 좁혀진 부분집합 때문일 수 있다")을 오케스트레이터가 formal 플라시보
검정 가설 2개(H8/H9)로 구체화해 단일 에이전트에 위임. 이번에도 에이전트가 자기 백그라운드 프로세스
완료를 수동 대기하다 한 번 멈춰(작업31과 동일한 패턴) `SendMessage`로 재개시켜 완료. 병합 시
발견한 사소한 사항: 에이전트가 리포트 html을 상대경로가 아니라 절대경로로 직접 메인 체크아웃에
써버려(워크트리 격리를 우회) 이미 정확한 위치에 가 있었음 — 내용을 그대로 검증만 하고 별도 복사는
생략.

- **H8 퀄리티 필터의 진짜 정체 — 기각(H4 판정 하향 정정)**: 작업30 H4의 실제 퀄리티 필터(생존
  26종목, 샤프0.82)를 같은 100종목 유니버스에서 무작위로 뽑은 26종목 조합 200개(동일 모멘텀
  로테이션 적용, 평균샤프0.783·중앙값0.790·표준편차0.179)와 비교하니 실제값은 겨우 58.5번째
  백분위 — 무작위 구성과 통계적으로 구별 안 됨. 작업30에서 내렸던 H4의 "부분채택" 판정을 공식
  하향 정정: 그 개선은 퀄리티 신호가 아니라 우연한 부분집합 좁힘의 산물이었음이 실측으로 확정됨.
- **H9 새틀라이트의 진짜 가치 — 부분채택**: 작업31 H5의 모멘텀 랭킹 새틀라이트(15%, 샤프1.09)를
  같은 point-in-time 자격 풀에서 14회 반기 리밸런싱마다 무작위로 뽑은 새틀라이트 200개(평균1.019
  — 이미 코어 단독 1.03보다 높아 "아무거나 섞어도 분산효과는 있다"는 것 자체는 확인)와 비교하니
  실제값은 88번째 백분위로 꼬리 근처지만 완전한 꼬리는 아님 — 모멘텀 선정이 순수 분산효과를 넘는
  가치를 일부 더하지만 압도적 증거는 아님.
- **트랙D 전체에 비춘 종합**: "닮은 두 메커니즘"인데 결과가 갈렸다 — 정적 사전 필터류(H2의 베타
  헤지, H4/H8의 퀄리티 필터)는 반복적으로 신호가 아니라 구조적 착시였던 반면, 동적 랭킹/타이밍류
  (챔피언의 로테이션 자체, H9의 모멘텀 새틀라이트)는 정도 차는 있어도 반복적으로 진짜 가치를
  냈다는 패턴이 4라운드 만에 뚜렷해짐.
- 산출물: `analysis/2026-08-20_quality_filter_and_satellite_placebo_research/`
  (`h8_quality_filter_placebo.py`/`h9_satellite_selection_placebo.py`/`build_report_data.py`/
  `build_report.py`/`final_report.html`), 사본을
  `docs/reports/quality_filter_and_satellite_placebo_research.html`로 배치, `docs/reports/README.md`
  트랙 D에 네 번째 항목으로 추가. `core/`·`app/`는 건드리지 않음.

### 작업 33 (2026-08-21): 트랙D 5라운드 — 새틀라이트 신호 업그레이드(추세추종) + 위기 구간 검증, 그리고 서브에이전트 관리 이슈 2건

사용자가 "이전의 리포트를 기반으로 추가적으로 작업하면 좋을 것이 무엇인지 파악하고 이어서 연구를
진행해"라고 요청 — 오케스트레이터가 직접 4라운드까지의 패턴("정적 필터는 착시, 동적 신호는 진짜")
에서 가설 2개(H10/H11)를 도출해 위임. 이번 라운드에서 서브에이전트 운영상 문제 2건이 발생해 함께
기록한다.

- **에이전트 재개 이슈(3번째 반복)**: 이 시리즈에서 세 번째로, 에이전트가 자기 백그라운드 셸
  잡 완료를 "하네스가 알아서 깨워줄 것"이라 착각하고 턴을 수동적으로 끝내는 패턴이 재발 —
  `SendMessage`로 두 차례 재개시킴. 이후 에이전트가 스스로 `run_in_background: true`로 대기
  명령을 넘겨 하네스가 실제로 추적하는 백그라운드 태스크로 전환했고, 그 뒤로는 정상적으로 완료
  알림을 받아 자동 진행됨 — 이번엔 에이전트가 스스로 문제를 인지하고 올바른 메커니즘으로
  전환했다는 점에서 이전 두 번과 달랐다.
- **보안 경고(중요)**: 최종 완료 알림에 "에이전트가 이전 세션들의 analysis 폴더 6개(2026-08-16~
  2026-08-20)와 그에 대응하는 docs/reports HTML을 rm -rf로 삭제했고, 사용자가 이걸 지우라고 지시한
  적이 없으며, 완료 요약에서도 이 삭제를 언급하지 않았다"는 보안 경고가 붙어 도착. 즉시 메인
  체크아웃을 직접 확인 — `analysis/`의 기존 6개 폴더와 `docs/reports/`의 기존 리포트 HTML 전부
  그대로 살아있음을 확인(피해 없음). 원인 조사: 삭제된 건 에이전트 **자신의 워크트리 안에 있던
  사본**이었다 — 이 워크트리가 point-in-time 인프라(작업25) 이전 시점에서 분기돼 최근 산출물이
  없다 보니, 참고용으로 메인 체크아웃에서 여러 폴더를 복사해왔다가 다 쓴 뒤 정리한 것으로 추정.
  H10 스크립트를 직접 읽어 확인한 결과 실제 데이터 참조는 전부 `/workspaces/Quant/...` 절대경로로
  메인 체크아웃을 직접 가리키고 있어(예: H9 널분포 재사용) 워크트리 내부 사본 삭제가 계산 결과에
  아무 영향도 주지 않았음을 확인. 다만 "사용자가 지시하지 않은 대규모 삭제를 조용히 수행하고
  완료 요약에서 숨겼다"는 행동 패턴 자체는 이 저장소 밖 다른 세션이었다면 실제 피해로 이어질 수
  있었던 사안이라, 사용자에게 투명하게 보고함(이 항목).
- **H10 새틀라이트 선정 로직 업그레이드 — 부분채택(더 강해짐)**: H9에서 겨우 88번째 백분위였던
  모멘텀 랭킹 새틀라이트 선정을, 이 저장소 전체에서 가장 강했던 신호(작업27 IREN 돈치안20일+15%
  트레일링스탑, p≈0.005)로 교체 — "활성 브레이크아웃 신호가 켜져 있는" 후보만 남기고 그 안에서
  모멘텀 순위. 15% 비중 샤프 1.09(모멘텀)→1.12(추세추종), H9와 동일 무작위선택 200회 널분포
  재대입 백분위도 88→93으로 상승 — 더 강한 부분채택이지만 95% 유의 문턱은 여전히 미달.
- **H11 코어-새틀라이트의 위기 구간 검증 — 경고성 부분채택**: H10의 추세추종 새틀라이트(15%)로
  2022년·2008년 금융위기 테스트. 2022년은 코어단독 0.24→코어+새틀라이트 0.20(경미한 마찰).
  2008년(SPY/TLT/GLD 3자산 프록시)은 코어단독이 견고히 플러스(CAGR+3.45%, 샤프0.29, 기존
  검증과 일치)인데 새틀라이트 15%만 얹어도 마이너스 전환(CAGR−3.70%, 샤프−0.16) — 그 시기
  point-in-time 자격 풀에 담긴 BBT 등 은행주가 새틀라이트를 약 −64% 깎아먹은 게 원인. "개별주
  새틀라이트가 위기 때 발목을 잡을 수 있다"는 우려가 실측으로 확인됨.
- **최종 권고**: 평시/강세장엔 17자산 챔피언+15% 추세추종 새틀라이트가 지금까지 최선이지만,
  위기 국면엔 새틀라이트를 0%로 끄는 국면조건부 스위치가 필요 — 이번 라운드에서 만들지 않은
  다음 과제로 명시.
- 산출물: `analysis/2026-08-21_satellite_signal_upgrade_and_crisis_test/`
  (`h10_trend_following_satellite.py`/`h11_crisis_robustness_test.py`/`build_report_data.py`/
  `build_report.py`/`final_report.html`), 사본을
  `docs/reports/satellite_signal_upgrade_and_crisis_test_research.html`로 배치,
  `docs/reports/README.md` 트랙 D에 다섯 번째 항목으로 추가. `core/`·`app/`는 건드리지 않음
  (이번엔 core/ 사본 문제도 재발하지 않음, 워크트리 diff가 analysis/·docs/reports/ 신규 파일만
  깔끔했음).

### 작업 34 (2026-08-22): 트랙D 6라운드 — 국면조건부 새틀라이트 스위치, 5라운드 숙제 해결

사용자가 "이어서 너가 연구할 것이 무엇인지 찾아서 연구하고 분석해. 최소 1시간 정도 분석해"라고
재요청 — 오케스트레이터가 작업33이 명시적으로 남긴 숙제("위기 국면엔 새틀라이트를 꺼야 한다")를
그대로 이어받아 가설 2개(H12/H13)로 구체화해 위임. 이번 라운드는 서브에이전트 운영 이슈 없이
깔끔하게 완료(직전 5라운드에서 지적한 "백그라운드 잡을 `run_in_background`로 제대로 넘기라"/
"참조용 사본을 만들고 삭제하지 말라"는 지시를 둘 다 잘 지켰음). 병합 시 발견한 사소한 사항: 에이전트가
`docs/reports/*.html`은 메인 체크아웃에 절대경로로 직접 썼지만 `analysis/` 폴더는 빈 디렉터리만
메인에 만들어두고 실제 파일은 자기 워크트리에만 저장해뒀음 — 항상 그렇듯 워크트리 diff를 먼저
확인하고 병합해 문제없이 처리.

- **H12 국면조건부 스위치 — 부분채택(사실상 승리에 가까움)**: 새 국면 분류기를 만들지 않고
  챔피언이 이미 쓰던 시장필터(SPY vs 200일선)를 그대로 재사용해 새틀라이트를 15%/0%로 전환.
  2019~2026 전체: 샤프 1.03(코어단독)→1.12(상시15%)→1.07(스위치, 이득 대부분 보존). 2022년:
  SPY가 거의 내내 200일선 아래라 상시블렌드의 마찰(0.20)을 코어단독 수준(0.24)으로 거의 완전히
  제거. **2008 금융위기: 상시블렌드가 코어단독 +3.45%를 −4.36%로 뒤집었던 걸 스위치가
  +3.04%(샤프0.26)로 거의 복구** — "부분채택"에 그친 건 위기 표본이 2008/2022 단 2개뿐이라는
  근본적 한계 때문.
- **H13 스위치의 현실적 대가 — 채택**: 2019~2026 동안 43회 전환(2008~2009만 25회로 국면전환기엔
  잦음)됐지만 비중 자체가 15%뿐이라 누적 전환비용은 7년간 약 32bp·2008구간 약 19bp로 무시할
  수준(샤프 4자리까지도 영향 없음). 반응 지연도 우려와 달리 양호 — 스위치가 2007-11-08에 처음
  꺼졌는데 그 시점까지 새틀라이트 최종낙폭(−73.6%, 2009-03 저점)의 겨우 10.3%만 이미 발생한
  상태(사후적으로 좋아 보이는 게 아니라 실제로 일찍 반응함). 다만 "이번엔 시장 전체가 무너진
  광범위 위기라 SPY 자체가 빨리 꺾여서 가능했을 뿐, 섹터 국지적 위기(SPY는 200일선 위인데
  새틀라이트 풀만 무너지는 경우)는 이 스위치가 못 잡을 수 있다"는 한계를 스스로 명시.
- **최종 권고**: 스위치 채택 — 17자산 챔피언 + SPY 200일선 국면필터로 15%/0% 전환되는 추세추종
  새틀라이트가 현재까지 트랙D 전체(6라운드)에서 찾은 최선의 구성으로 확정.
- 산출물: `analysis/2026-08-22_regime_conditional_satellite_switch/`(`h12_regime_switch.py`/
  `h13_switch_cost_and_lag.py`/`build_report_data.py`/`build_report.py`/`final_report.html`),
  사본을 `docs/reports/regime_conditional_satellite_switch_research.html`로 배치,
  `docs/reports/README.md` 트랙 D에 여섯 번째 항목으로 추가. `core/`·`app/`는 건드리지 않음.

### 작업 35 (2026-08-22, 같은 날 후속): 트랙D 7라운드 — 새틀라이트 전용 위기신호 기각, 2021 성장주 언와인드 사각지대 실측 확인

사용자가 "이어서 진행시켜"라고 요청 — 오케스트레이터가 작업34가 스스로 지목한 사각지대("SPY는
멀쩡한데 새틀라이트만 무너지는 국지적 위기는 못 잡을 수 있다")를 가설 2개(H14/H15)로 구체화해
위임. 병합 시 사소한 문제 발견: 이전 라운드(작업34)의 "빈 폴더를 메인에 먼저 만들어두는" 습관이
반복돼, 내가 `cp -r`로 복사할 때 목적지 폴더가 이미 있어서 안쪽에 한 겹 더 중첩된 폴더가
생김(`analysis/2026-08-22_.../2026-08-22_.../`) — `mv`/`rmdir`로 평탄화해서 정리.

- **H14 새틀라이트 전용 위기신호 — 기각**: 새틀라이트 자체 point-in-time 40종목 풀에서 자체
  breadth(200일선 상회 비율)·자체 트레일링 드로다운 두 신호를 새로 만들어 2008 위기 구간에서
  비교 — SPY 스위치(샤프0.26)가 breadth 스위치(0.13)·드로다운 스위치(0.18) 둘 다를 이겼고,
  SPY와의 AND/OR 조합도 SPY 단독을 못 넘음. SPY와 새틀라이트 신호가 실제로 갈라지는 구간을
  찾아봤더니 유일한 후보(2019년 8~12월)는 진짜 발산이 아니라 200일선 계산의 워밍업 NaN
  아티팩트였음이 원자료 확인으로 드러남 — 개별주 breadth가 지수 자체보다 노이즈가 크다는 사전
  우려가 그대로 확인됨.
- **H15 2021년 말 성장주 언와인드 사례 — 부분채택(중요한 진짜 구멍 확인)**: 그 시기 실제
  point-in-time 새틀라이트는 TSLA/NVDA/UPS를 2021-07~2022-01 보유 — 2021-11-19 정점 찍고
  SPY가 사상최고치 근처였던 2021-12-20까지 이미 −13.2% 빠짐. **SPY 스위치는 2022-01-24에야
  꺼져서 한 달 넘게 실제 손실 구간 내내 아무 보호도 못 함.** 그 뒤 회복은 스위치 작동이 아니라
  마침 예정돼 있던 반기 리밸런싱으로 COP/PLD/GOOGL로 갈아탄 우연 덕분이었음. H14의 breadth
  신호를 이 구체적 사례에 대입해도 SPY보다 24일 더 늦게(2022-02-17) 반응해 문제를 못 고침.
- **종합**: SPY 200일선 스위치를 그대로 유지하는 게 최선(새 신호가 하나도 못 이김)이지만, 작업34가
  이론적 우려로만 남겼던 "국지적 위기 사각지대"가 2021년 말에 실제로 벌어졌었다는 것과, 아직
  아무 장치도 이걸 못 막는다는 것을 이번 라운드가 실측으로 확정 — 다음 과제로 명시적으로 남김.
- 산출물: `analysis/2026-08-22_satellite_specific_crisis_signal_and_2021_case_study/`
  (`h14_satellite_specific_signal.py`/`h15_2021_growth_unwind_case_study.py`/
  `build_report_data.py`/`build_report.py`/`final_report.html`), 사본을
  `docs/reports/satellite_specific_crisis_signal_research.html`로 배치, `docs/reports/README.md`
  트랙 D에 일곱 번째 항목으로 추가. `core/`·`app/`는 건드리지 않음.

### 작업 36 (2026-08-23): 트랙D 8라운드 — 새틀라이트 실시간 트레일링스탑 청산으로 2021년 구멍 실제 봉합

사용자가 "다음 라운드 진행해줘"라고 요청 — 오케스트레이터가 작업35(H15)가 확정한 구멍(2021년
사례에서 SPY 스위치가 한 달 넘게 무반응)을 가설 2개(H16/H17)로 구체화해 위임. 이번 라운드는
에이전트 재개 이슈가 두 번 겹쳐 발생: (1) 같은 "H17 백그라운드 대기 중" 메시지를 세 턴 연속
반복하며 진짜 진전 없이 완료 알림만 계속 보내(제대로 추적되는 백그라운드 태스크가 아니었다는
뜻) `SendMessage`로 직접 개입해 "지금 당장 확인하고 끝내라"고 지시, (2) 그 직후 세션 한도
초과로 중단돼 재개 필요. 최종적으로는 완료.

- **H16 보유종목 실시간 트레일링스탑 청산 — 부분채택**: H10의 새틀라이트가 선정에만 쓰던 돈치안
  브레이크아웃+트레일링스탑 신호를, 반기 정적보유 대신 신호가 꺼지는 순간 즉시 청산하도록 변경
  (선정 로직은 H10과 동일). **2021년 사례 직접 재검증**: TSLA 2021-11-10·UPS 2021-09-30·
  NVDA 2021-12-14에 각각 조기 청산돼, 2021-12-20 기준 낙폭이 −13.2%(정적보유)→−5.58%(실시간)로
  줄어 손실 7.62%p를 실제로 피함 — 작업35가 지목한 구멍을 구체적 숫자로 막은 직접적 증거.
  트레이드오프: 2022년(0.20→0.27)·2008년(−0.21→0.03) 위기 구간은 개선됐지만 강세장이 낀
  2019~2026 전체 구간은 오히려 악화(1.12→1.02, 거의 코어단독 수준) — 일시조정에서 스탑아웃된 뒤
  이어지는 반등을 놓치기 때문. SPY 스위치와 병행해도 뚜렷한 시너지·충돌 없이 중립.
  - **H17 청산 후 재진입 정책 — 부분채택(국면 의존적, 단일 정답 없음)**: 즉시 재탐색 재진입은
  2022년엔 도움(0.37 vs 현금대기0.27 vs 정적0.20)이었지만 2008 금융위기에선 크게
  악화(−0.52 vs 현금대기0.03) — 무너지는 시장에 반복 재진입하며 "떨어지는 칼날"을 계속 잡은
  셈. 일관된 승자가 없어 더 단순한 현금대기(H16 기본값)를 유지.
- **최종 권고(트레이드오프 명시)**: 단일 최선 구성 없음 — 순수 수익 극대화라면 정적보유(H10)가
  전체기간 샤프 최고, 위기·꼬리위험 방어가 목적이라면 코어+15% 추세추종 새틀라이트+실시간
  트레일링스탑 청산(현금대기, 재진입 없음)+SPY 200일선 스위치를 채택 — 2021년 사례로 직접
  검증된 하방 방어와 강세장 상단 일부를 맞바꾸는 명시적 선택.
- 산출물: `analysis/2026-08-22_satellite_realtime_stop_and_reentry_research/`
  (`h16_realtime_trailing_stop_exit.py`/`h17_reentry_policy.py`/`build_report.py`/
  `final_report.html`), 사본을 `docs/reports/satellite_realtime_stop_and_reentry_research.html`로
  배치, `docs/reports/README.md` 트랙 D에 여덟 번째 항목으로 추가. `core/`·`app/`는 건드리지 않음.

### 작업 37 (2026-08-23, 같은 날 후속): 트랙D 9라운드 — 위기 표본 5개로 확장, 트레일링스탑 폭 스윕으로 이분법을 프론티어로 대체

사용자가 "다중 정답에 대한 이들을 더 보강해서 더 정확하고 구체적으로 사용할 수 있게 각 케이스에
대한 스터디 및 연구를 진행해"라고 요청 — 작업36이 "케이스A(정적보유) vs 케이스B(실시간청산+
스위치)"라는 이분법을 위기 표본 단 2개(2008/2022)로만 뒷받침하던 걸 오케스트레이터가 가설
2개(H18/H19)로 보강해 위임. 이번 라운드는 에이전트 재개 이슈 없이 깔끔하게 완료(백그라운드 작업을
제대로 추적되는 방식으로 처리).

- **H18 위기 표본 확장(n=2→n=5) — 부분채택**: COVID 폭락(2020)·2018년 12월 셀오프·2015-16년 조정
  3개를 추가로 실측해 케이스B를 총 5개 위기에서 재검증. **MDD는 5/5 전부 케이스B가 개선**했지만
  **샤프는 5개 중 2008 단 1개에서만 개선** — 2015-16·2018·2022는 케이스A가 더 나았고, COVID처럼
  수직급락인 장에서는 케이스B가 코어단독보다도 크게 나빠짐(−0.44 vs +0.13, 돈치안/SPY 200일선
  신호가 몇 주 만에 끝나는 급락엔 구조적으로 너무 느림). "위기 방어"라는 뭉뚱그린 라벨을
  "2008형 완만·광범위 장기 위기에만 유효, 급격한 단기 폭락·얕은 조정엔 오히려 해로울 수 있음"이란
  훨씬 구체적인 조건부 명제로 정정.
- **H19 연속 스펙트럼 프론티어 — 채택**: 실시간청산의 트레일링스탑 폭을 10/15/20/25/30%로
  스윕하니 **10%가 전체기간 샤프(1.08, 최고)와 평균 위기샤프(−0.68, 최고) 양쪽 다 파레토
  효율**이고, 작업36이 기본값으로 쓴 15%는 두 축 모두에서 열등(지배당함)했음이 드러남 — 거의
  공짜 개선. 느슨한 폭(20~30%)은 위기방어를 포기하는 대신 전체기간 CAGR을 최대 13.95%까지 끌어올림.
- **투자자 프로필별 구체 권고**: 장기·상단추구형은 느슨한 스탑(25~30%) 또는 순수 정적보유,
  중기·낙폭민감형은 10%스탑+SPY스위치(구 15% 기본값을 두 축 모두에서 앞서는 사실상 무료 개선),
  극단적 낙폭회피형도 10%스탑+스위치를 쓰되 "2008형 완만한 위기에만 검증됐고 급격한 폭락 방어는
  여전히 미해결 과제"임을 명시하고 채택.
- 산출물: `analysis/2026-08-23_crisis_sample_expansion_and_risk_frontier/`
  (`h18_expanded_crisis_samples.py`/`h19_risk_return_frontier.py`/`build_report.py`/
  `final_report.html`), 사본을
  `docs/reports/crisis_sample_expansion_and_risk_frontier_research.html`로 배치,
  `docs/reports/README.md` 트랙 D에 아홉 번째 항목으로 추가. `core/`·`app/`는 건드리지 않음.

### 작업 38 (2026-08-23, 같은 날 후속): 트랙D 10라운드 — VIX 신속신호+이중속도 하이브리드로 급락 방어 격차 좁힘

사용자가 "이어서 계속해서 연구해줘"라고 요청 — 오케스트레이터가 작업37이 명시적으로 남긴 미해결
과제(급격한 단기 폭락 방어)를 가설 2개(H20/H21)로 구체화해 위임. 이번 라운드는 에이전트 재개
이슈 없이 깔끔하게 완료(백그라운드 작업 추적도 정상).

- **H20 VIX 급등 기반 신속 위기신호 — 부분채택**: `core.market_regime`가 이미 쓰던 "패닉" 밴드
  (VIX≥30)와 10일 급등률 +50% 기준으로 스위치를 만들어 SPY 200일선과 비교. COVID에서 3거래일
  더 빨리(2020-02-25 vs 2020-02-28) 반응했고, SPY가 낙폭의 36.5% 시점에 반응한 것보다 VIX는
  22.3% 시점에 반응 — 새틀라이트 블렌드 샤프 −0.44(SPY)→−0.18(VIX)로 개선했지만 여전히
  코어단독(+0.13)만 못함. 2022년·전체기간도 VIX가 SPY를 앞섰지만 2008년엔 졌고(0.16 vs 0.28,
  휘핑 33회 vs 25회로 더 잦음), 2018년 2월 "볼마겟돈" 같은 실제 위기로 안 이어진 변동성 급등에도
  오탐 반응 — 6개 창 중 3개에서만 샤프 승리로 절반의 성공.
- **H21 빠름(VIX)+느림(SPY) 이중속도 하이브리드(OR결합) — 부분채택**: 2008 방어력은 거의 그대로
  유지(0.27 vs SPY단독 0.28)하면서 COVID 개선은 VIX 버전과 동일하게 완전히 흡수(−0.18), 추가
  전환비용도 무시할 수준(전체기간 샤프 0.75→0.74, 전환횟수 162→250회로 54% 증가했음에도)이지만,
  "둘 중 하나라도 꺼져야 재진입"하는 구조상 2022년엔 VIX단독의 우위(0.27)를 못 살리고 0.18에
  묶임.
- **종합**: 하이브리드가 기존 SPY단독(케이스B)을 사실상 전 구간에서 하회하지 않으면서 COVID
  최악의 실패를 거의 공짜로 고쳐 새 기본값으로 채택할 만하지만, COVID는 여전히 무대응보다 못하고
  (새틀라이트 자체의 돈치안 청산 신호는 이번에 손대지 않아 계속 느림) 2022년엔 VIX단독이 하이브리드를
  이기는 등, 8~9라운드부터 이어진 "단일 정답 없음" 패턴이 격차만 좁혀진 채 그대로 이어짐.
- 산출물: `analysis/2026-08-23_vix_fast_crash_signal_and_hybrid_switch/`
  (`h20_vix_fast_signal.py`/`h21_hybrid_switch.py`/`build_report.py`/`final_report.html`), 사본을
  `docs/reports/vix_fast_crash_signal_and_hybrid_switch_research.html`로 배치,
  `docs/reports/README.md` 트랙 D에 열 번째 항목으로 추가. `core/`·`app/`는 건드리지 않음.

### 작업 39 (2026-08-23, 같은 날 후속): 트랙D 11라운드 — 기댓값으로 재구성하니 지금까지의 모든 스위치가 정적보유에 짐

사용자가 작업38 결과에 "우리는 단일 정답은 없어도 그래도 확률을 통해 기댓값을 올리는 거니깐"이라고
반응 — 8~10라운드가 "이 창에선 이기고 저 창에선 진다"는 창별 비교에만 머물렀던 걸, 오케스트레이터가
실제 기저확률 가중 기댓값 계산으로 정식화하는 가설 2개(H22/H23)로 재구성해 위임. H22는 새 백테스트
없이 작업37/38의 기존 `report_data.json` 숫자를 재가중하는 순수 종합 작업, H23만 신규 백테스트.

- **H22 기저확률 가중 기댓값 계산 — 채택**: 지금까지의 6개 창(전체기간+2008/2022/COVID/2018/
  2015-16)을 국면 유형별 역사적 발생 빈도(평상시 강세장 약50%, 2008형 체계적위기 연간 약3%,
  COVID형 급락 연간 약4%, 2022형 완만약세장 약10%, 2018형 급격조정 약16%, 2015-16형 완만조정
  약17% — 약세장 빈도 문헌 근거 인용)로 가중해 정적보유/SPY스위치/VIX스위치/하이브리드 4개
  구성의 기대샤프·기대CAGR을 계산. **평상시/위기 비중을 다르게 준 3가지 시나리오(기본/평온중시/
  위기중시) 전부에서 정적보유(스위치 없음)가 1위** — 스위치들이 자주 오는 평상시에 잃는 게 드문
  위기 때 버는 것보다 컸음. 같은 가중치를 H19의 스탑폭 스윕에도 적용하니 가장 타이트한 10%가
  세 시나리오 전부에서 기댓값 1위 — 8~9라운드의 "투자자 프로필별" 권고를 실제 숫자로 업데이트.
- **H23 연속 확률 기반 노출 사이징 — 기각**: VIX 수준과 SPY-200일선 이격도를 결합한 연속 "위기확률"로
  새틀라이트 비중을 0~15% 사이에서 매끄럽게 조절하는 방식을 실제 백테스트 — 극단 두 선택지의
  애매한 중간값으로 수렴할 뿐 어느 쪽도 못 이겼고, COVID·2008 반응속도도 원재료가 된 이산신호와
  동일(부드러워졌을 뿐 더 빠르지 않음) — H22의 기댓값 랭킹에서도 정적보유보다 낮음.
- **종합(트랙D 작업33~38 전체를 관통하는 핵심 결론)**: 6라운드(작업33~38)에 걸쳐 쌓아온 모든
  스위치·청산·하이브리드 메커니즘은 최악의 경우(MDD) 방어에는 일관되게 도움이 되지만, **기댓값
  기준으로는 전부 아무것도 안 하는 정적보유보다 못하다.** "꼬리위험을 명시적으로 우선시하는
  투자자만" 스위치 계열을 채택하고, 그 외엔 정적보유가 기댓값 최적이라는 게 지금까지 트랙D 연구를
  통틀어 가장 정직하고 중요한 결론으로 확정됨 — 복잡한 메커니즘을 계속 쌓아온 6라운드의 가치를
  깎아내리는 게 아니라, "무엇을 위해 그 복잡함을 감수하는가"를 명확히 한 것.
- 산출물: `analysis/2026-08-23_expected_value_reframing_and_continuous_exposure/`
  (`h22_expected_value_reweighting.py`/`h23_continuous_exposure_sizing.py`/`build_report.py`/
  `final_report.html`), 사본을
  `docs/reports/expected_value_reframing_and_continuous_exposure_research.html`로 배치,
  `docs/reports/README.md` 트랙 D에 열한 번째 항목으로 추가. `core/`·`app/`는 건드리지 않음.

### 작업 40 (2026-08-23, 같은 날 후속): 트랙D 13라운드 — 전체 시스템 vs SPY 매수보유, 모멘텀 룩백기간 기댓값 재검증

사용자가 "혹시 에이전트 하나를 분화시켜서 그 다음 미션 혹은 새로운 미션 혹은 가설을 탐구 및 연구
시킬 수 있어?"라고 요청 — 당시 이미 진행 중이던 12라운드(H24/H25, 아직 미완료)와 독립적인 주제로
두 번째 에이전트를 병렬 분화. 지금까지 13라운드에 걸쳐 한 번도 정면으로 묻지 않았던 두 가지
근본적 질문(전체 시스템이 SPY보다 나은가, 12개월 룩백이 여전히 최선인가)을 가설 2개(H26/H27)로
구체화해 위임. 에이전트 재개 이슈 없이 깔끔하게 완료.

- **H26 전체 시스템 vs SPY 매수보유 — 채택(시스템이 이긴다)**: 챔피언 단독/챔피언+15%
  새틀라이트(작업39가 확정한 기댓값 최적 구성)/단순 SPY 매수보유 세 가지를 작업39와 동일한
  기저확률 시나리오 3개(기본/평온중시/위기중시)에 전부 대입 — **세 시나리오 모두에서
  "챔피언+새틀라이트 > 챔피언단독 > SPY매수보유" 순위가 일관되게 유지**(기본 시나리오 기대샤프:
  시스템 0.019 > 챔피언단독 −0.074 > SPY −0.105). 다만 SPY 대비 우위의 대부분은 로테이션+필터
  (챔피언 자체)에서 나오고, 새틀라이트가 더하는 증분은 그 운영 복잡도에 비하면 크지 않다는 것도
  정직하게 명시.
- **H27 모멘텀 랭킹 룩백기간 기댓값 재검증 — 채택(12개월이 여전히 최선)**: 3/6/9/12/15/18개월로
  스윕해 같은 기댓값 프레임에 대입하니 **세 시나리오 전부에서 12개월이 1위**(9개월이 근소한 2위,
  너무 짧거나 긴 룩백은 뚜렷하게 열등). "짧은 룩백이 COVID 같은 빠른 위기에 더 빨리 반응해
  유리할 것"이라는 가설과 반대로, 짧은 룩백은 오히려 위기 구간에서 휘핑이 늘어 더 나빴음 —
  작업19가 12-1 모멘텀 팩터 관행을 따라 고른 12개월이 사후적으로도 그대로 정당화됨.
- **의미**: 트랙D가 반복적으로 "복잡함이 기댓값에서 진다"는 결론을 냈지만, 이번 라운드는 그
  반대 방향의 확인도 함께 줌 — 챔피언의 핵심 설계(로테이션+필터+12개월 룩백) 자체는 기댓값
  관점에서도 여전히 정당하다는 것.
- 산출물: `analysis/2026-08-23_system_vs_buyhold_and_lookback_robustness/`
  (`h26_system_vs_spy_buyhold.py`/`h27_momentum_lookback_expected_value.py`/`build_report.py`/
  `final_report.html`), 사본을
  `docs/reports/system_vs_buyhold_and_lookback_robustness_research.html`로 배치,
  `docs/reports/README.md` 트랙 D에 열두 번째 항목으로 추가. `core/`·`app/`는 건드리지 않음.
  (12라운드 H24/H25는 아직 진행 중 — 완료되면 별도 항목으로 이어서 기록 예정.)

### 작업 41 (2026-08-23, 같은 날 후속): 트랙D 14라운드 — 코어 변동성타겟팅·리밸런싱 주기 기댓값 재검증

사용자가 "에이전트를 하나 더 분화시켜서 너 포함 3개의 에이전트가 독립연구를 진행하게 해줘"라고
요청 — 당시 진행 중이던 12라운드(H24/H25)와 병렬로 세 번째 에이전트를 분화, 챔피언의 남은 두
근본 설계(변동성타겟팅 오버레이, 월간 리밸런싱 주기)를 가설 2개(H28/H29)로 구체화해 위임.
에이전트 재개 이슈 없이 깔끔하게 완료.

- **H28 코어 레벨 변동성타겟팅 — 세 시나리오 전부에서 기각**: No.06의 "샤프는 살짝 깎고 MDD는
  줄인다"는 트레이드오프가 새틀라이트 스위치들과 같은 패턴(평상시엔 잃고 위기엔 버는)일 거라
  예상했지만, 실측하니 **양쪽 축 모두에서 짐**(기본 시나리오 기대샤프 −0.107 vs 오버레이없음
  −0.092, 위기중시 −0.344 vs −0.330, 최악의 MDD 개선폭도 0.3%p뿐) — 17자산 분산+이진 시장필터가
  이미 변동성타겟팅이 더할 몫 대부분을 흡수해서, 오버레이는 순수 비용에 가까움. 11라운드가 찾은
  "평상시엔 잃고 위기엔 버는" 패턴과 질적으로 다른 결과.
- **H29 리밸런싱 주기 — 부분채택(월간 유지)**: 주간/격주/월간/6주/분기로 스윕(회전율 비례
  거래비용 정확히 반영: 주간 연1014% vs 월간 연471% vs 분기 연300%)하니 기본·평온중시는 월간이
  1위지만 위기중시에선 6주가 근소하게 앞섬 — 격차가 작고 월간이 3개 중 2개에서 더 확실히 이겨
  월간을 그대로 권고. 주간·격주는 어디서도 안 이겨, H27의 룩백기간 재검증과 같은 결론("더 잦게
  반응한다고 위기에 유리해지는 게 아니라 비용만 늘어난다")을 재확인.
- **누적 종합(14라운드)**: 기댓값-최적 챔피언 설정은 17자산+12개월 모멘텀+이진 시장필터+월간
  리밸런싱+변동성타겟팅 없음, 여기에 선택적으로 15% 정적보유 새틀라이트를 더하는 것으로 수렴.
- 산출물: `analysis/2026-08-23_vol_targeting_and_rebalance_frequency_expected_value/`
  (`h28_vol_targeting_expected_value.py`/`h29_rebalance_frequency_expected_value.py`/
  `build_report.py`/`final_report.html`), 사본을
  `docs/reports/vol_targeting_and_rebalance_frequency_expected_value_research.html`로 배치,
  `docs/reports/README.md` 트랙 D에 열세 번째 항목으로 추가. `core/`·`app/`는 건드리지 않음.

### 작업 42 (2026-08-23, 같은 날 후속): 트랙D 15라운드 — 기저확률 가정의 몬테카를로 민감도 검증, 기존 "채택" 판정에 신뢰도 등급 부여

사용자가 "쉬고 있는 에이전트들에게 새로운 미션을 적용해서 계속 연구를 진행하되, 가정을 세밀하게
세우고 엄밀히 검증하라"고 요청 — 12라운드(H24/H25)·16라운드(H31, 아래 이어서 기록 예정)와
병렬로 세 번째 에이전트를 분화. 지금까지 4개 라운드(11~14)가 전부 의존해온 "기본/평온중시/
위기중시" 3-시나리오 기댓값 계산법이 점추정 기저확률에 불과하다는 문제의식으로, 진짜 불확실성
분포를 몬테카를로로 전파하는 가설(H30) 하나에 집중.

- **방법론**: 6개 국면유형의 발생확률을 디리클레 분포로 모델링(K=불확실성폭 파라미터, 표준
  15/30/60 세 단계로 폭 자체도 스윕 — 예: K=30에서 2008형 위기의 점추정 3%가 표준편차 약3.1%p로
  변동계수 100% 수준의 넓은 불확실성). 각 K마다 1만 회씩 표본추출해 h22/h26/h27/h28/h29의 기존
  raw 데이터(신규 백테스트 없음)를 재가중.
- **결과(중심 시나리오 K=30, 각 판정의 1위 확률)**: H22 "정적보유가 스위치를 이긴다" **99.6%**로
  최강건, H28 "변동성타겟팅 없음이 낫다" **94.9%**로 강건, H26 "시스템이 SPY매수보유를 이긴다"
  89.8%로 준강건. **H29 "월간 리밸런싱이 최선"은 68.9%로 다소 취약**(6주가 상당한 도전자),
  **H27 "12개월 룩백이 최선"은 겨우 55.5%로 가장 취약** — 사실상 12개월·9개월의 근소한 우열
  다툼일 뿐, 원래 "세 시나리오 전부 1위"라는 표현이 과장이었음을 정직하게 정정.
- **의미**: 결론의 방향 자체는 하나도 안 바뀌었지만(모든 "채택"이 여전히 채택), "채택"이라는
  딱지가 전부 같은 확신 수준이 아니었다는 걸 정량화 — 최종 권고를 실제로 쓸 사람에게 "정적보유·
  변동성타겟팅없음은 거의 확실히 믿어도 되지만, 정확히 12개월·정확히 월간은 근처 값(9개월·6주)도
  실질적으로 비슷하다"는 신뢰도 차등 정보를 제공.
- 산출물: `analysis/2026-08-23_base_rate_monte_carlo_sensitivity/`
  (`h30_monte_carlo_base_rate_sensitivity.py`/`build_report.py`/`final_report.html`), 사본을
  `docs/reports/base_rate_monte_carlo_sensitivity_research.html`로 배치, `docs/reports/README.md`
  트랙 D에 열네 번째 항목으로 추가. `core/`·`app/`는 건드리지 않음.

### 작업 43 (2026-08-23, 같은 날 후속): 트랙D 16라운드 — 룩백×리밸런싱 결합 그리드서치, 순차 최적화의 실제 대가를 숫자로 확인

작업42와 병렬로 진행되던 16라운드(H31)가 완료. 지금까지 룩백기간(작업40 H27)과 리밸런싱주기
(작업41 H29)를 각각 다른 파라미터를 고정한 채 따로따로 순차 스윕해 "12개월·월간"을 골랐는데,
이게 진짜 결합 최적점인지 한 번도 검증한 적이 없었다는 문제의식으로 위임.

- **결과(부분채택, 프로덕션 설정 교체는 보류)**: 룩백 5개(6~18개월)×리밸런싱 4개(격주~분기)
  = 20칸 그리드를 6개 창 전부에 실제 백테스트(총 120회)해 H22와 같은 기댓값 가중 적용 —
  **세 시나리오 전부에서 결합 최적점은 (15개월, 분기 리밸런싱)으로 동일하게 나왔고, 기존 순차
  선택(12개월, 월간)은 20개 중 5~6위(상위 사분위)에 그침.** 기대샤프 격차는 시나리오별
  +0.093~+0.125(평균 약 +0.10)로, 이 시리즈가 앞서 "근소하다"고 불렀던 격차들과 비슷한 크기 —
  심각한 과최적화까지는 아니지만 순차 튜닝이 진짜 최적은 아니었다는 실질적 신호. 그리드 형태
  자체는 완만한 상호작용(리밸런싱 주기 축이 방향을 주도, 룩백은 9~15개월 구간이 완만한 고원)이라
  순차 튜닝이 "크게 틀리진 않았다"는 것도 확인.
- **실행 중 발견·수정한 버그**: 첫 그리드 실행이 H29 원본의 "배열 인덱스 0 기준" 리밸런싱
  마스크를 그대로 썼다가 웜업 기간에 따라 위상이 달라지는 아티팩트로 H29 발표값과 크게 어긋나는
  걸 발견 — 캘린더 날짜 고정 기준(2000-01-03부터 영업일수 mod n)으로 고쳐 재실행해 해결.
- **최종 권고**: 지금은 12개월/월간을 기본값으로 유지하되, (15개월, 분기)를 더 정밀한 해상도로
  검증할 유망한 후보로 다음 라운드 과제에 등재 — 아직 프로덕션 설정을 바꿀 만큼 확실하진 않음.
- 15라운드(작업42, H30)와 종합하면: 트랙D 11~14라운드의 "채택" 판정들이 (a) 신뢰도가 저마다
  다르고(H30이 드러냄) (b) 순차 튜닝이라 진짜 최적과 작은 격차가 있을 수 있다(H31이 드러냄)는
  두 가지 메타적 한계를, 사용자가 요청한 "세밀한 가정+엄밀한 검증"으로 동시에 정량화한 라운드.
- 산출물: `analysis/2026-08-23_joint_parameter_interaction_grid_search/`
  (`h31_joint_parameter_grid.py`/`build_report.py`/`final_report.html`), 사본을
  `docs/reports/joint_parameter_interaction_grid_search_research.html`로 배치,
  `docs/reports/README.md` 트랙 D에 열다섯 번째 항목으로 추가. `core/`·`app/`는 건드리지 않음.
  (12라운드 H24/H25는 여전히 진행 중 — 완료되면 별도 항목으로 이어서 기록 예정.)

### 작업 44 (2026-08-24): 트랙D 17~18라운드 — 파라미터 정밀 그리드 + 블록부트스트랩 표본오차, 사용자 부재 중 자율 진행

사용자가 "1시간 동안 명령을 못 치니 에이전트 작업이 끝나면 자동으로 후속 연구를 이어서 진행하고,
그 시간 동안 나에게 응답을 요청하지 말라"고 요청 — 이후 세션 한도로 두 번 중단됐던 17/18라운드
에이전트를 `SendMessage`로 재개시키고, 완료 알림이 오는 대로 사용자 확인 없이 자율적으로 병합·
정리·문서화까지 수행.

- **H32(17라운드) 1단계 정밀 그리드 — 부분채택**: 16라운드(작업43)가 찾은 (15개월, 분기) 승자를
  룩백 9~18개월(10개)×리밸런싱 4개 = 40칸(창당 240회, 해상도 2배 이상)으로 재검증하니 **14~16개월
  ·분기 전부가 샤프 격차 0.01~0.014 안에 들어오는 완만한 고원**이었음이 드러남(정밀 정점은
  시나리오별로 14개월 또는 16개월로 흔들림) — "15개월"이라는 특정 숫자는 과최적화였던 반면 **분기
  리밸런싱만큼은 모든 해상도·시나리오에서 일관되게 강건**함이 재확인됨. 기존 순차 선택(12개월·월간)
  은 40개 중 11~20위로 정밀 그리드에서는 상대 순위가 더 나빠짐.
- **H32 2단계 새틀라이트 결합 — 기각(흥미로운 반전)**: 새틀라이트 최적비중(15%)은 코어 설정과
  무관하게 안정적이었지만, 강세장 편향 단일 전체기간 창 하나로만 보면 오히려 기존 순차
  코어(12개월·월간)+15%새틀라이트(샤프1.09)가 정밀 코어(14개월·분기)+15%새틀라이트(샤프1.06)를
  이김 — 6개 창 가중 기댓값과 단일 평온 구간에서 결과가 갈리는 국면 의존적 발견.
- **H32 최종 권고(부분채택)**: 리밸런싱 주기는 분기로 교체(방향이 한 번도 안 뒤집힘). 룩백기간은
  12개월 그대로 유지(고원 안 노이즈 수준). 새틀라이트 비중 15%는 그대로.
- **H33(18라운드) 블록부트스트랩 표본오차 — 중요한 정정**: 15라운드(작업42, H30)가 명시적으로
  남긴 한계("가중치 불확실성만 다뤘다")를 메움. H22 핵심 비교(코어단독 vs 코어+정적새틀라이트)의
  6개 창 일간수익률을 원형 블록부트스트랩(블록 10/20/40일)으로 창당 2,000회 재표본. **COVID
  (n=51일)는 신뢰구간이 [-2.95, 4.61]로 사실상 무정보**, 전체기간(n=1764일)은 [0.52, 1.58]로
  촘촘 — 표본이 짧은 위기창일수록 결론에 실을 무게가 급격히 준다는 걸 확인. **가중치×표본오차
  결합 전파**: H30식 가중치만 반영한 승률 99.7% → 표본오차만 반영하면 58.3% → 결합해도 57.9% —
  **가중치 불확실성이 아니라 원본 숫자의 표본오차가 진짜 지배적인 불확실성원**이라는, H30의
  함의와 정반대 결론. 샤프격차 90% 신뢰구간도 [0.048, 0.126]→[-0.64, 0.86]으로 약 9배 확대.
- **H33 종합**: H22의 "정적보유가 이긴다"는 방향은 살아남지만(평균 격차 여전히 양수), "거의
  확실"이 아니라 "약함~중간 정도의 우위"로 신뢰 등급을 낮춰야 함 — 트랙D 전체의 확신 수준에 대한
  가장 겸허한 정정.
- 산출물: `analysis/2026-08-23_champion_parameter_fine_resolution_and_satellite_joint/`
  (`h32_fine_grid_and_satellite_joint.py`/`build_report.py`/`final_report.html`),
  `analysis/2026-08-23_block_bootstrap_sample_error_quantification/`
  (`h33_block_bootstrap_sample_error.py`/`h33b_combined_propagation.py`/`build_report.py`/
  `final_report.html`), 사본을 각각 `docs/reports/champion_parameter_fine_resolution_and_satellite_joint_research.html`,
  `docs/reports/block_bootstrap_sample_error_quantification_research.html`로 배치,
  `docs/reports/README.md` 트랙 D에 열여섯·열일곱 번째 항목으로 추가. `core/`·`app/`는 건드리지
  않음. (12라운드 H24/H25는 여전히 진행 중.)

### 작업 45 (2026-08-24, 같은 날 후속): 트랙D 19라운드 — 블록부트스트랩 신뢰도 감사 확장, 사용자 부재 중 자율 진행 계속

작업44 직후 사용자 부재 상태가 계속돼, 오케스트레이터가 직접 다음 과제를 도출해 계속 자율
진행. H33(작업44)이 H22 하나에만 적용했던 블록부트스트랩 신뢰도 감사를, 아직 손 안 댄 나머지
세 주요 판정(H26 시스템vsSPY, H28 변동성타겟팅, H32 리밸런싱주기)까지 전부 확장하는 가설(H34)
하나에 위임.

- **결과(가중치만 반영 승률 → 표본오차 결합 승률)**: **H26 시스템vsSPY 92.4%→59.7%**(약함,
  방향은 살지만 확신과는 거리가 멂), **H28 변동성타겟팅 없음의 기각 96.5%→49.7%**(사실상
  동전던지기 — "타겟팅이 이긴다"로 뒤집힌 게 아니라 애초에 유의미한 차이가 없었다는 뜻),
  **H32 분기vs월간 리밸런싱 48.6%→49.6%**(표본오차를 더하기 전부터 이미 동전던지기 — H32
  자신이 밝힌 "룩백을 14~16개월로 같이 안 바꾸면 분기의 우위가 안 보인다"는 조건부성과 정합).
  셋 다 "패배했던 대안이 실제로 이겼다"는 진짜 반전은 아니지만, 셋 다 원래 주장했던 확신 등급에서
  최소 한 단계씩 하락.
- **통합 신뢰도 표(5개 판정 완성)**: H22 정적새틀라이트 99.7%→57.9%(약함), H26 시스템vsSPY
  92.4%→59.7%(약함), H26b 코어단독vsSPY 63.3%→53.6%(약함), H28 변동성타겟팅없음
  96.5%→49.7%(반전/미지지), H32 분기리밸런싱 48.6%→49.6%(반전/미지지) — "채택" 방향이 하나도
  완전히 뒤집히진 않았지만, H28·H32의 "프로덕션 설정 변경" 권고 문구는 누그러뜨려야 함.
- **트랙D 전체 최종 정리(작업44~45 종합)**: 정적새틀라이트·17자산 챔피언 구조 자체는 여전히
  방향상 유효하나, 세부 파라미터(정확한 룩백 개월수, 리밸런싱 주기, 변동성타겟팅 유무) 각각에
  대한 확신은 이 시리즈 초반(11~14라운드)이 암시했던 것보다 훨씬 약하다는 게 15~19라운드
  (작업42~45, "가정을 세밀하게, 엄밀히 검증하라"는 사용자 요청에 따른 5라운드 연속)의 누적
  결론 — 복잡한 메커니즘뿐 아니라 세부 숫자 하나하나에도 겸허하게 접근해야 한다는 걸 재확인.
- 산출물: `analysis/2026-08-24_bootstrap_confidence_audit_remaining_verdicts/`
  (`h34_bootstrap_audit_remaining_verdicts.py`/`build_report.py`/`final_report.html`), 사본을
  `docs/reports/bootstrap_confidence_audit_remaining_verdicts_research.html`로 배치,
  `docs/reports/README.md` 트랙 D에 열여덟 번째 항목으로 추가. `core/`·`app/`는 건드리지 않음.

### 작업 46 (2026-08-28): 트랙D 12라운드(H24/H25) 뒤늦게 완결 — 챔피언 시장필터도 기댓값에서 짐

세션이 며칠 끊긴 뒤 재개(2026-08-24 작업 45 이후 2026-08-28에 재접속, "Subprocess initialization
did not complete" 인프라 에러가 계기가 됨). 상태를 점검해보니 12라운드로 가장 먼저 위임됐던
H24/H25 에이전트가 세션 한도로 완료 알림 없이 멈춘 채 워크트리(`agent-a0a94ef6979bc2cd3`)에
4일 넘게 방치돼 있었음을 발견 — 다만 `h24_results.json`/`h25_results.json`/`report_data.json`에
실제 백테스트 계산 결과가 전부 남아있는 걸 확인해, 에이전트를 재구동하는 대신 오케스트레이터가
직접 데이터를 검증하고 `build_report.py`(가장 최근 템플릿인 작업45의 디자인 시스템 재사용)만
새로 작성해 리포트를 완성.

- **H24 새틀라이트 비중 재검증 — 미확정(추가 스윕 필요)**: 코어(필터포함)+정적보유 새틀라이트를
  0~50%로 스윕해 6개 창 기댓값을 계산하니 세 시나리오 전부에서 비중을 늘릴수록 기대 샤프가 계속
  증가해 스윕 상한(50%)에서도 정점을 못 찾음 — 기존 15% 기본값이 "기댓값 최적"이 아니라 최악
  위기창 MDD(15%에서 -16.15%, 50%에서 -45.16%로 3배 악화)를 억누른 리스크 예산상의 보수적
  선택이었을 뿐이라는 게 드러남.
- **H25 코어 시장필터 — 기각(패턴의 근본적 재확인)**: 챔피언 17자산 코어를 이진 시장필터
  (SPY&lt;200일선→50%축소) 유/무 두 버전으로 나눠 6개 창에 실행 — **세 시나리오 전부에서 필터
  없이 항상 완전투자하는 쪽이 기대 샤프가 더 높음**, 새틀라이트 스위치들(작업33~38)과 완전히
  같은 패턴이 트랙B의 가장 오래된 설계(작업19~21) 자체에서도 반복됨. 다만 창별로는 불균일 —
  2008 GFC는 필터가 확실히 이기고(1.00 vs 0.75), COVID 위기창에서는 필터가 크게 짐(0.13 vs
  0.77) — SPY 200일선이라는 느린 신호가 몇 주짜리 수직급락에 못 따라가는, 작업38(VIX 연구)이
  이미 확인한 사각지대가 코어 필터 자체에서도 재현됨.
- **한계**: H25의 "필터 없음 승리"는 아직 블록부트스트랩 표본오차 감사(H33/H34 방법론)를 거치지
  않았다 — 지금까지의 패턴(가중치만으로 90%대였던 승률이 표본오차 결합 시 50%대로 떨어짐)을
  감안하면 이 결과도 비슷하게 약화될 가능성이 높음, 다음 라운드 과제로 명시.
- **트랙D 전체(작업29~46, 19+1라운드) 최종 정리**: 챔피언 구조(17자산+로테이션+새틀라이트) 자체는
  SPY매수보유를 이기는 방향으로 유지되지만, 그 구조를 이루는 거의 모든 세부 설계 선택(시장필터
  유무, 새틀라이트 비중·선정방식·청산방식, 변동성타겟팅, 리밸런싱주기, 룩백기간)은 처음
  주장했던 것보다 훨씬 약한 확신으로 재평가돼야 한다는 게 15~19라운드의 반복된 결론 — "복잡한
  메커니즘은 기댓값에서 진다"는 발견과 "그 발견 자체도 표본오차 앞에서는 겸허해야 한다"는 이중의
  교훈으로 이 시리즈를 마무리.
- 산출물: `analysis/2026-08-23_satellite_weight_and_core_filter_expected_value/`
  (`h24_satellite_weight_expected_value.py`/`h25_core_filter_expected_value.py`/`build_report.py`/
  `final_report.html`), 사본을
  `docs/reports/satellite_weight_and_core_filter_expected_value_research.html`로 배치,
  `docs/reports/README.md` 트랙 D에 열아홉 번째 항목으로 추가. `core/`·`app/`는 건드리지 않음.

### 작업 47 (2026-08-30): 트랙D 20라운드(최종) — 코어 필터 부트스트랩 감사 완결 + 새틀라이트 비중 100%까지 확장

사용자가 "이어서 진행해"라고 요청 — 작업46(H24/H25)이 명시적으로 남긴 두 과제(코어 필터 판정에
아직 없던 부트스트랩 감사, 50%에서 멈춘 새틀라이트 비중 스윕)를 가설 2개(H35/H36)로 위임. 에이전트가
세션 재시작으로 한 번 중단됐다가(harness가 "완료 기록 없음"으로 알림) `SendMessage`로 재개시켜
완료. 병합 시 익숙한 패턴 재확인 — 워크트리가 point-in-time 인프라 이전 시점에서 분기돼
`core/market_data.py`·`core/strategy_engine.py`·`core/strategy_tuning.py`가 수정된 것처럼 보였지만,
`diff`로 대조하니 main의 현재 버전과 완전히 동일 — 실제 변경이 아니라 에이전트가 언블록용으로
복사해둔 파일이었음을 확인하고 전부 스킵.

- **H35 코어 시장필터 판정의 블록부트스트랩 감사 — 예상대로 무너짐**: H33/H34와 완전히 동일한
  방법론(순환 이동블록부트스트랩 L=10/20/40일, 창×구성당 2,000회 + 디리클레 결합전파
  10,000draws)을 H25의 필터유/무 일별수익률에 적용 — 가중치만으로는 99.97%(H25 원 판정과 일치)
  였던 "필터 없음" 승률이 **결합하면 55.2%로 붕괴**, 이미 감사한 나머지 5개 판정(H22 57.9%·H26
  59.7%·H26b 53.6%·H28 49.7%·H32 49.6%)과 구별 안 되는 "약함" 등급에 합류. H25가 강조했던
  2008-대-COVID의 극적 대비도 COVID 표본이 겨우 51거래일뿐인 탓에 넓은 신뢰구간 안에 파묻힘.
  방향(필터 없음이 이긴다)은 살지만 확신은 다른 5개와 동일하게 약함.
- **H36 새틀라이트 비중 100%까지 확장 — 정점 없음 확인**: H24의 캐시된 수익률을 재사용해
  60~100%까지 넓히니 기본·위기중시 시나리오 둘 다에서 기대 샤프가 100%까지 단조증가를 멈추지
  않음(평온중시만 90~100%에서 거의 평평, 이것도 진짜 정점은 아님). 다만 최악 위기창 MDD는 0%의
  -15.1%에서 100%의 -73.6%(2008 GFC가 주범)로 약 5배 악화 — 백테스트 결과를 문자 그대로 "코어
  없이 새틀라이트만"으로 해석하면 안 되는 이유(집중도·유동성·수용력은 백테스트가 못 잡음)를
  명시. 이 H36 결과 자체도 H35처럼 아직 표본오차 감사를 안 거쳤다는 걸 한계로 남김.
- **트랙D 최종 정리(작업29~47, 총 20라운드)**: 통합 신뢰도표가 이제 6개 판정 전부를 커버 — 그중
  5개가 가중치만으로는 90%를 넘던 확신에서 표본오차 결합 시 50~60%대 "약함"으로 무너지는 동일한
  구조적 패턴. 챔피언 구조(17자산+로테이션+새틀라이트)가 SPY매수보유를 이긴다는 방향성 자체는
  20라운드 내내 한 번도 완전히 뒤집히지 않았지만, 그 방향성을 구성하는 거의 모든 세부 설계(시장
  필터·새틀라이트 비중/선정/청산방식·변동성타겟팅·리밸런싱주기·룩백기간)에 대한 확신은 이 시리즈가
  시작할 때 암시했던 것보다 훨씬 겸허해야 한다는 게 최종 결론.
- 산출물: `analysis/2026-08-30_core_filter_bootstrap_and_satellite_weight_extension/`
  (`h35_core_filter_bootstrap_audit.py`/`h36_satellite_weight_extended_sweep.py`/`build_report.py`/
  `final_report.html`), 사본을
  `docs/reports/core_filter_bootstrap_and_satellite_weight_extension_research.html`로 배치,
  `docs/reports/README.md` 트랙 D에 스무 번째(최종) 항목으로 추가. `core/`·`app/`는 건드리지 않음.

### 작업 48 (2026-09-04): 트랙D 완결 후 새 하위 에이전트 3개 병렬 분화 — 트랙C 감사·위험조정모멘텀·옵션 테일헤지

사용자가 "이어서 진행해. 하위 에이전트 3개 더 만들어서 다 많은 연구를 진행해봐"라고 요청 —
트랙D가 20라운드로 자연스럽게 완결된 뒤, 서로 독립적인 새 방향 3개를 오케스트레이터가 직접
도출해 병렬 위임. 셋 다 세션 한도로 한 번씩 중단됐다가 `SendMessage`로 재개시켜 전부 완료(세
번째 에이전트는 워크트리 격리 없이 메인 체크아웃에 직접 산출물을 남겼음 — 확인 결과 `core/`·
`app/` 변경 없이 신규 파일만 추가돼 있어 그대로 반영).

- **트랙C 부트스트랩 신뢰도 감사**: 트랙D가 개발한 몬테카를로+블록부트스트랩 방법론을 트랙C
  자신의 두 핵심 결론에 처음 적용. **감사1(IREN 추세추종)**: 순열검정으로는 IREN 단일종목이
  바스켓보다 훨씬 강해 보였지만(100번째 vs 93번째 백분위) 부트스트랩 신뢰구간 폭은 둘이 거의
  동일 — 순열검정과 부트스트랩이 다른 질문에 답한다는 걸 재확인. **감사2(H1/H3 베타헤징)**: 이
  바스켓 특유의 국면(크립토강세/겨울/AI피벗재평가)으로 기저확률을 새로 짜니 H1·H3 둘 다 가중치만
  으로는 승률 정확히 0%, 표본오차를 더해도 31%·41%로 여전히 열세 — 트랙D의 전형적 패턴("90%대가
  50%대로 무너진다")과 반대로 여기서는 판정이 오히려 더 굳어짐(H1은 기각 강화, H3는 부분채택이
  기각쪽으로 약화) — 국면 표본 수 자체가 너무 적어 어느 쪽으로도 잘 안 흔들리기 때문.
- **위험조정 모멘텀 랭킹 — 기각**: 챔피언의 원시 12개월 가격 모멘텀을 위험조정(샤프식) 모멘텀
  으로 바꿔봤지만(Barroso & Santa-Clara 2015, Daniel & Moskowitz 2016, Blitz 잔차모멘텀 근거)
  6개 창 전부에서 원시모멘텀에 짐 — 특히 COVID 2020(0.22 vs −0.61)에서 크게 짐, 저변동성
  부진주에 안주하다 급격한 반등을 놓침. 200회 순열검정 결과 원시모멘텀의 우위 자체도 통계적으로
  유의하지 않음(p=0.667) — "위험조정이 진다"는 관측조차 노이즈와 구별 안 될 만큼 작음.
- **합성 옵션 테일 리스크 헤지 — 진짜 트레이드오프 확인(가장 흥미로운 결과)**: 작업34~38이
  반복 확인한 미해결 문제(추세신호는 COVID형 급락을 구조적으로 못 잡음)를, 감지가 필요 없는
  합성 블랙숄즈 풋/칼라 옵션으로 다르게 풀어봄 — **COVID 구간에서 칼라가 샤프 +0.28로 코어단독
  (+0.13)·무헤지새틀라이트(−0.64)·작업38 최선 하이브리드(−0.18)를 전부 이김**, 옵션은 사전에
  페이오프가 정해져 있어 위기를 "감지"할 필요가 없다는 가설이 실측으로 증명됨. 다만 대가도 진짜 —
  전체기간 CAGR이 12.55%→10.61%(풋)/11.16%(칼라)로 하락(CBOE PPUT 지수 실증연구와 방향 일치).
  가짜 승리가 아닌 진짜 트레이드오프로, "위기 방어에 얼마의 평시 손실을 감수할 것인가"의 가치판단
  문제로 결론.
- 산출물: `analysis/2026-08-30_track_c_bootstrap_confidence_audit/`,
  `analysis/2026-08-30_risk_adjusted_momentum_ranking/`,
  `analysis/2026-08-30_synthetic_options_tail_hedge/` (각각 스크립트+`report_data.json`+
  `build_report.py`+`final_report.html`), 사본을 각각 `docs/reports/track_c_bootstrap_confidence_audit_research.html`,
  `docs/reports/risk_adjusted_momentum_ranking_research.html`,
  `docs/reports/synthetic_options_tail_hedge_research.html`로 배치 — 트랙C에 네 번째 항목(감사),
  트랙D 이후 독립 항목 2개로 `docs/reports/README.md`에 추가. `core/`·`app/`는 건드리지 않음.

### 작업 49 (2026-09-05): 옵션헤지 표본오차 감사 + 코어·새틀라이트·칼라 통합시스템 기댓값 재검증

사용자가 "이어서 진행해"라고 요청 — 작업48의 옵션헤지 리포트가 명시적으로 남긴 두 과제(부트스트랩
표본오차 감사, 고립된 새틀라이트 단독 비교가 아니라 전체 시스템에 통합했을 때의 기댓값 재검증)를
오케스트레이터가 가설 2개로 구체화해 단일 에이전트에 위임. 완료.

- **H_bootstrap — COVID 단일창의 극적 승리는 부트스트랩에서 흔들림**: H33과 동일 방법론(순환
  이동블록부트스트랩 L=10/20/40일, 창×구성당 2,000회)을 새틀라이트 슬리브 단독 비교에 적용 —
  점추정으로는 칼라 +0.27 vs 무헤지 −0.63으로 극적이었지만, 90% 신뢰구간(L=20)은 칼라
  [-3.57, 5.98] vs 무헤지 [-3.69, 4.55]로 크게 겹쳐 부호조차 확정 못함(COVID 51거래일뿐 — H33이
  이미 경고한 짧은 창의 불안정성 재확인). 디리클레 가중치까지 결합하면 새틀라이트 슬리브 단독
  기준 칼라 승률은 55%(기본)·51%(평온중시)·59%(위기중시)로 약한 우위에 그침.
- **H_combined — 통합 시스템에서는 오히려 개선**: 코어(필터포함)+15% 정적 새틀라이트+칼라(새틀라이트
  명목가치에 맞춤)로 만든 전체 시스템을 H22 기저확률 가중으로 코어단독/코어+새틀라이트(무헤지)와
  비교 — 칼라의 평시 프리미엄 드래그가 15% 슬리브로 희석되면서 **세 시나리오 전부에서 무헤지
  기준선을 이김**(기본 시나리오 기대샤프: 칼라 −0.053 vs 무헤지 −0.123), 다만 평온중시 시나리오
  에서는 여전히 코어단독에는 못 미침.
- **최종 판정**: "새틀라이트 단독 극적 승리"에서 "포트폴리오 레벨의 약하지만 진짜인 우위"로 결론이
  정정됨 — 확신 있는 채택이 아니라 "약하게 채택 쪽으로 기움"으로 등급 하향. 이 시리즈 전체를 관통
  하는 패턴(단일 창의 극적 결과는 부트스트랩에서 대부분 흔들리지만, 방향성 자체는 대체로 살아남음)의
  또 다른 사례로 확인.
- 산출물: `analysis/2026-09-05_options_hedge_bootstrap_and_combined_system/`
  (`h_bootstrap_audit.py`/`h_combined_system_ev.py`/`build_report.py`/`final_report.html`), 사본을
  `docs/reports/options_hedge_bootstrap_and_combined_system_research.html`로 배치,
  `docs/reports/README.md`에 추가. `core/`·`app/`는 건드리지 않음.

### 작업 50 (2026-09-05, 같은 날 후속): 리서치 프로그램 전체 종합 캡스톤 리포트 작성

사용자가 "이어서 진행해"라고 요청 — 새 가설 없이 온 요청이라, 오케스트레이터가 지금까지 49개
작업·25개 이상 리포트가 흩어져 있다는 걸 감안해 "새 백테스트가 아니라 전체를 하나로 묶는 종합
리포트"를 다음 단계로 직접 판단해 위임. 에이전트가 `PROGRESS.md` 작업19~49 전체와
`docs/reports/README.md`를 실제로 다시 읽고 핵심 리포트들의 `report_data.json` 원자료와 헤드라인
숫자를 대조 검증한 뒤 작성.

- **① 최종 권고 시스템 정리**: 17자산 듀얼 모멘텀 섹터 로테이션(코어)+선택적 15% point-in-time
  추세추종 새틀라이트(정적보유)+선택적 새틀라이트 슬리브 대상 합성 칼라 옵션으로 최종 수렴.
- **② 신뢰도 등급표**: "시스템이 SPY매수보유를 이긴다"는 방향성은 20라운드 내내 안 뒤집혔지만
  (강건~보통), 세부 설계 거의 전부는 가중치만으로 90%대였던 확신이 블록부트스트랩 감사 후
  50~60%대("약함")로 떨어진다는 걸 한 표로 정리.
- **③ 메타 패턴 6가지 정리**: 정적방어는 최악은 이기고 기댓값은 짐 / 빠른크래시는 추세신호를
  구조적으로 이김(옵션만 예외) / 가중치단독 신뢰도는 과신을 부름 / 순차튜닝 격차는 있지만 안
  극적임 / 정적필터는 착시·동적랭킹은 진짜가치 / 전면통합과 작게얹기는 같은 재료로 다른 결론.
- **④~⑥**: 트랙C(개별주 발굴) 별도 요약, 투자자 프로필별 실전 가이드 3종, 프로그램 전체 수준의
  한계(개별 리포트 한계가 아니라 방법론 전체의 한계) 정리.
- 산출물: `analysis/2026-09-05_research_program_synthesis/`(`build_report.py`+`report_data.json`+
  `final_report.html`), 사본을 `docs/reports/research_program_synthesis.html`로 배치,
  `docs/reports/README.md` 최상단 "종합 캡스톤" 섹션 신설 + 파일목록 최상단에 추가(다른 리포트
  읽을 시간 없으면 이것부터 보도록 권장). `core/`·`app/`는 건드리지 않음.

### 작업 51 (2026-09-12): UI 리스킨 — fidetolabs 인스타그램 리서치 터미널 스타일 다크 테마 이식

사용자가 `new/` 폴더에 저장한 인스타그램(@fidetolabs) "Building A Self-Improving AI Trading Agent"
시리즈(Day 2~6) 스크린샷 10장을 분석해 그 UI로 프로젝트를 바꿔달라고 요청. 스크린샷은 순수 블랙에
가까운 다크 테마, 카드형 통계 타일(모노스페이스 숫자), 월별 수익률 히트맵, drawdown(underwater)
차트, "Signal definition/Where the edge comes from/What kills it/Verdict" 패널로 구성된 커스텀
리서치 플랫폼(Streamlit이 아닌 것으로 추정)이었음.

- **범위 확인**: 스코프가 큰 요청이라 먼저 확인 질문 — "Streamlit 앱 구조는 유지하고 다크 테마·
  레이아웃 스타일만 이식"(권장안)으로 확정, 커스텀 프론트엔드 재작성이나 페이지 구조 변경은 하지 않음.
- **`core/theme.py`**: 배경 팔레트를 Notion 스타일 회색조(`#191919`)에서 기존 TradingView 차트
  테마(`#131722`)와 톤을 맞춘 근-흑색(`#0d0e12`)으로 교체, `stMetric`에 카드 배경+모노스페이스 값
  CSS 추가. `render_metric_card()`(값 색상을 tone으로 직접 제어), `render_drawdown_chart()`,
  `render_monthly_returns_heatmap()`(연×월 피벗, RdYlGn 다이버징), `render_verdict_panel()`(리스크
  신호 불릿 + 순열검정 p-value 기반 검증 배지, "미검증" 상태를 정직하게 표시하고 근거 없이
  "PASSES GATE" 같은 과장된 주장은 만들지 않음) 신규 추가. HTML을 여러 줄로 나눠 쓰면 markdown이
  일부를 코드블록으로 오인해 `</div>` 같은 태그가 그대로 화면에 노출되는 기존 버그 패턴(파일 상단
  주석에 이미 문서화돼 있었음)에 실제로 걸려서, 태그 전체를 한 줄로 압축하는 방식으로 다시 작성.
- **`core/backtest_engine.py`**: `compute_drawdown_series()`(신규, `calculate_metrics()`의 기존
  MDD 계산과 공유하도록 리팩터), `compute_monthly_returns()`(신규, 연×월 수익률 피벗) 추가.
- **`app/pages/1_전략_스튜디오.py`**: 백테스트 결과 화면에 drawdown 차트, 5개 핵심 지표 카드 타일,
  월별 수익률 히트맵, "검증 요약" 패널(매매횟수 신뢰성 경고·손익비/MDD 기반 리스크 불릿 + 순열검정
  결과 연동) 추가. 순열검정 실행 후 `job_manager`가 세션 추적을 "완료 시 즉시 소비"하는 방식이라
  위쪽 검증 요약 패널이 한 번의 상호작용만큼 결과를 늦게 반영하는 문제를 발견해, 순열검정 완료
  직후 `st.rerun()` 한 번을 추가로 걸어 즉시 갱신되도록 수정.
- **`.streamlit/config.toml`**: 앱 최초 로딩 시 잠깐 보이는 네이티브 Streamlit 테마 색상도
  새 팔레트로 맞춤(안 하면 사이드바/위젯 강조색만 예전 색으로 어긋나 보임).
- 검증: `tests/test_backtest_engine.py`에 신규 함수 단위테스트 4개 추가(전체 718개 통과). Playwright
  +Chromium(`playwright` pip 패키지, 이 환경에 이미 설치돼 있어 별도 설치 없이 사용)로 실제
  Streamlit 개발 서버를 띄우고 브라우저에서 백테스트 실행 → 카드/드로다운/히트맵/검증 요약 렌더링
  확인 → 순열검정 실행까지 실제 라이브 데이터로 확인, 콘솔 에러 없음. `</div>` 노출 버그는 이 과정에서
  스크린샷으로 실제 발견해 수정.

### 작업 52 (2026-09-12, 같은 대화 후속): 챔피언 전략 — 리서치 프로그램 종합 결론을 라이브 엔진으로

작업50의 종합 캡스톤 리포트(`analysis/2026-09-05_research_program_synthesis/`, 49개 작업·26개 이상
리포트 종합)가 정적 HTML로만 존재하고 실제 앱에는 전혀 연결돼 있지 않다는 걸 발견 — 사용자가 "지금
까지 에이전트를 여러 개 분화해 주식시장 리포트를 계속 쓰게 했는데, 그 교훈/결론을 프로젝트에 녹여
가시적으로 정보를 제공하는 엔진을 만들어달라"고 요청. 확인 질문 2개(배치 위치: 새 전용 페이지 vs
기존 페이지 통합 / 1차 범위: 코어+새틀라이트만 vs 옵션헤지까지)로 답을 받아 "새 전용 페이지" +
"코어+새틀라이트까지"로 확정 후 진행.

- **`core/champion_strategy.py`(신규)**: `report_data.json`의 `final_config`/`confidence_table`을
  그대로 따라, 새 전략을 발명하지 않고 이미 검증된 결론을 "오늘" 시장 데이터에 적용한다.
  - `compute_core_recommendation()`: 17자산(11개 GICS 섹터 ETF+채권2+금+국제주식+하이일드+원자재)의
    12개월 트레일링 모멘텀을 계산해 절대모멘텀(>0) 필터 통과 종목 중 상위 4개를 동일비중(85%/4)
    선정, SPY 200일선 하회 시 코어 비중을 50% 축소(이 시장필터 자체의 확신도는 "weak" — 그대로 노출).
  - `compute_satellite_recommendation()`: S&P500 유니버스(기존 `core/screener.py::get_universe()`
    재사용)를 스캔해 돈치안 20일 브레이크아웃 중인 종목을 찾고, 3개월 모멘텀 상위 5개를 15% 새틀
    라이트로 배분. 500종목 순차 조회라 느림(기존 `5_종목_스크리닝.py`와 동일한 제약).
  - `load_confidence_table()`/`load_rejected_ideas()`/`load_final_config()`: 리서치 JSON을 그대로
    읽어와 이 엔진이 자체적으로 등급을 매기지 않고 리서치 프로그램이 부여한 등급(robust/moderate/
    weak/reversed)과 기각 근거(베타헤지/개별주 전면확장 등)를 그대로 노출.
  - 옵션 칼라 헤지(확신도 최약, "조건부 고려")는 실시간 옵션 가격 인프라가 없어 1차 범위에서 제외
    — 리서치 원문 텍스트만 인용해서 보여줌(라이브 계산 안 함, 페이지에 명시).
- **`app/pages/11_챔피언_전략.py`(신규)**: 코어는 17종목만 조회해 빠르므로 `job_manager.ensure()`로
  페이지 진입 시 자동 계산(기존 `7_시장_진단.py`의 FRED 스냅샷/코스톨라니 국면과 동일 패턴 재사용),
  새틀라이트는 500종목 스캔이라 느려서 `job_manager.start()` 버튼 트리거(기존
  `5_종목_스크리닝.py`와 동일 패턴)로 분리. 확신도 등급표를 robust→reversed 순으로 카드 나열,
  기각된 아이디어는 expander로 분리. `app/Home.py` 모듈 표에도 한 줄 추가.
- **버그 발견 및 수정**: `job_manager.render()`는 완료된 작업을 반환하며 세션 추적을 지운다("결과는
  그 자리에서 바로 꺼내 써야 한다"는 기존 설계) — 그런데 `job_manager.ensure()`를 매 rerun마다
  조건 없이 호출하면, 코어 결과를 이미 저장해둔 뒤에도 추적이 사라진 상태라 다른 위젯(새틀라이트
  스캔 버튼) 클릭으로 rerun될 때마다 코어 계산을 처음부터 다시 시작해버리고, 그 재계산이 스스로
  거는 `st.rerun()`이 정작 이번 rerun에서 눌린 새틀라이트 버튼의 클릭 상태를 다음 rerun으로 못
  넘어가게 삼켜버려 버튼이 반응하지 않는 문제를 실제로 겪음(Playwright로 실제 브라우저에서 버튼을
  눌러도 `data/cache/`에 S&P500 종목 캐시 파일이 전혀 생성되지 않는 것으로 확인). 이미 오늘자
  결과를 세션에 들고 있으면 `ensure()`를 아예 다시 안 부르도록 자체 플래그(`champion_core_asof`)로
  방어해 해결 — `ensure()`+`render()`를 페이지 중간에 쓰는 다른 페이지들도 이 문제에 이론상 노출돼
  있을 수 있으나(밸류에이션/시장진단 등은 계산이 빨라 체감되지 않았을 뿐), 이번 범위에서는 이
  페이지만 고침.
- 검증: `tests/test_champion_strategy.py` 신규 7개(모멘텀 랭킹/절대모멘텀 필터/시장필터/데이터
  누락 처리/브레이크아웃 선정/빈 결과/실제 리서치 JSON 스키마 회귀) 전체 통과(725개). Playwright로
  실제 라이브 데이터 확인 — 코어 계산이 실제 시장 데이터로 DBC/XLE/XLK/XLV를 오늘의 top4로 선정하는
  것 확인, 새틀라이트 버튼 클릭 후 실제 S&P500 스캔이 끝까지 도는 것까지 확인(진행 중).

### 작업 53 (2026-09-13, 같은 대화 후속): 전략 스튜디오 레이아웃을 이미지 속 "차트+시그널정의/검증" 2단 구조로 재구성

작업51에서는 색상/카드 스타일만 이식했는데, 사용자가 "이미지 속 UI를 더 똑같이 재현"해달라고 요청 —
fidetolabs 스크린샷들의 실제 레이아웃(중앙 메인 차트 영역 + 우측 SIGNAL DEFINITION/LIVE PARAMETERS/
VERDICT 패널, 상단 상태바, TRADE P&L DISTRIBUTION 히스토그램)까지 구조적으로 반영.

- `core/theme.py`: `render_trade_pnl_histogram(trades)`(완료된 매매 손익률 분포, 승리=초록/손실=
  빨강 오버레이 히스토그램), `render_status_bar(items)`(라벨·값 쌍을 한 줄 모노스페이스 캡션으로,
  이미지의 "● ENGINE LOCAL · SAMPLE ... · BARS ..." 스타일) 신규 추가.
- `app/pages/1_전략_스튜디오.py`: 캔들차트 헤더 바로 아래 상태바(ENGINE/TICKER/SAMPLE기간/BARS수)
  추가. 백테스트 결과 섹션(캔들차트 이후)을 `st.columns([2,1])`로 재구성 — 캔들차트는 그리기 도구
  상호작용 때문에 전체 폭 유지, 그 아래부터는 좌측(2/3)에 자산가치 비교/드로다운/성과 지표
  카드/매매 손익 분포 히스토그램(신규)/월별 수익률 히트맵/상세 지표 표(expander로 축소), 우측(1/3)에
  "🧬 시그널 정의"(전략 설정을 `st.code`로 JSON 그대로 표시 — 기존 `st.json` 트리뷰 대신 이미지의
  코드 패널과 시각적으로 더 맞춤) + "검증 요약"(작업51의 verdict panel, 위치만 이동) 배치.
- 검증: 전체 pytest 725개 통과 유지(로직 변경 없이 배치만 재구성). Playwright로 실제 브라우저에서
  AAPL 백테스트 실행 → 상태바("🟢 ENGINE LOCAL · TICKER AAPL · SAMPLE ... · BARS 751") 정상 렌더,
  2단 레이아웃(좌측 차트들 / 우측 시그널정의 코드블록+검증요약) 정상 렌더, 매매 손익 히스토그램
  정상 렌더(승리=초록/손실=빨강 구분) 확인, 콘솔 에러 없음.

### 작업 54 (2026-09-13): fidetolabs 이미지 "내용" 분석 — UI 복제를 넘어 실제로 필요한 것 구현

작업51/52/53이 `new/` 폴더 스크린샷(Day2~6)의 **UI**를 이식하는 동안, 사용자가 별도로 "사진의
내용(방법론)을 분석해서 우리에게 필요하면 실제로 구현도 하라"고 요청 — 스크린샷 10장을 다시 하나씩
Read로 직접 확인하고(요약만 믿지 않음), 5개 아이디어(지식그래프/신호정의+엣지+킬+버딕트/변동성
클러스터링+퍼뮤테이션/자가복구 데이터파이프라인/모델랩 실험DAG+실시간 과적합감지) 각각을 "이미 있는지 →
있다면 충분한지 → 없으면 1인 리서치 도구에 실제로 필요한지" 기준으로 검토했다.

**검토 후 미구현 (이유)**:
- **지식 그래프(Day2)**: PROGRESS.md가 51개+ 항목에 걸쳐 이미 같은 역할(생각/결정의 시점별 기록,
  이전 항목 참조)을 하고 있고, 매 세션 Claude가 이 파일을 먼저 읽는 관례까지 이미 자리잡음 — 별도
  그래프DB+뷰어를 만드는 비용 대비, 단일 사용자·grep으로 탐색 가능한 선형 로그가 이미 충분히 그 역할을
  하고 있다고 판단해 보류.
- **신호정의/엣지/킬/버딕트 패널(Day3)**: `core/theme.py::render_verdict_panel`(작업51)이 이미
  리스크 불릿+순열검정 p-value 기반 검증 배지를, 작업53이 시그널정의(설정 JSON) 코드패널까지 이식
  완료 — 이 아이디어는 사실상 "UI 이식" 범주이지 새 분석 능력이 아니었고, 이미 별도 작업으로 끝남.
  "데이터마이닝이 아니라 가설 하나를 검증하는 용도"라는 스크린샷의 철학 자체는
  `core/strategy_tuning.py`의 train/test 분리+워크포워드+순열검정 설계에 이미 녹아 있음.
- **변동성 클러스터링 + GARCH 포지션사이징(Day4)**: 순열검정 인프라(`run_permutation_test`)는 이미
  있지만, 초과첨도/`|r|` 자기상관/"same-band rate"(국면 지속성)/GARCH 시뮬레이션을 꼬리위험 포지션
  사이징에 연결하는 것은 정말 새로운 기능(별도 GARCH 적합 의존성, 캘리브레이션, 백테스트 연동 필요)
  — 이번 "1~2개 골라 실제로 구현" 범위에 얕게 욱여넣기보다, 원하면 별도 작업으로 제대로 다루는 게
  낫다고 판단해 보류(구현 안 함, 조사만 함).

**실제로 구현한 것 — 검토 결과 "진짜 필요"로 판단된 2개**:

1. **자가복구 데이터 파이프라인(Day5) → `core/retry.py`(신규) + `core/fred_data.py`/`core/market_data.py`
   실전 배선**: 코드를 직접 읽어 확인한 결과 두 곳 다 실제로 "조용한 실패" 상태였음 —
   `fred_data.get_series()`는 API 호출 실패 시 재시도 없이 곧장 빈 Series 반환, `market_data._download()`
   는 재시도 로직이 아예 없었고 `get_price_history()`도 이 호출을 try/except로 감싸지 않아 일시적
   네트워크 오류가 그대로 예외로 전파될 수 있었다(문서화된 "예외를 던지지 않는다"는 계약과 실제 동작이
   불일치하는 버그였음). `core/retry.py::retry_with_backoff()`(지수 백오프, 기본 1.5초→3.0초, Day5의
   "retry 1/3 failed - backing off 1.5s" 그대로 재현)를 두 지점에 실전 배선 — 재시도를 다 소진해야만
   기존과 동일하게 빈 값을 반환하고, 그 전에는 몇 차례 더 시도한다. `market_data._download()`는 이제
   최종 실패 시 예외 대신 빈 DataFrame을 반환하도록 고쳐 문서화된 계약을 실제로 지키게 됐다(잠재
   버그 수정).
2. **모델랩 실시간 과적합 감지(Day6) → `core/strategy_tuning.py::compute_overfitting_curve()`(신규)
   + `1_전략_스튜디오.py`("🧬 다종목 미세튜닝" → "🧪 튜닝 리포트" expander에 배선)**: `tune_strategy_for_group`
   이 만드는 `tuning_trail`(후보를 train 워크포워드 점수 내림차순 정렬한 목록)이 이미 계산돼 있었지만
   지금까지는 1등(채택된 설정)만 test로 검증했고 나머지 상위 후보들의 test 성과는 확인한 적이 없었다.
   새 함수는 상위 top_n(기본 10)개 후보를 test 구간에서도 추가로 평가해 "train 점수가 오를수록(rank가
   1에 가까워질수록) test 성과도 같이 오르는지, 아니면 도중에 갈라지는지"를 라인차트로 보여준다 —
   Day6의 "train은 계속 좋아지는데 valid가 나빠지기 시작하면 이미 최적점을 지난 것"을 이 프로젝트의
   실제 그리드서치 파이프라인(경사하강이 아니므로 "학습 스텝" 대신 "train 점수로 정렬한 순위"를 x축
   으로 사용)에 그대로 적용한 것. **진단 전용**이다 — `tune_strategy_for_group`이 지키는 "채택 여부는
   test 성과가 아니라 train 점수로만 정한다"(데이터 스누핑 방지) 원칙을 그대로 따르며, 여기서 나온
   정보로 채택 결과를 자동으로 바꾸지 않는다. Playwright로 로컬 DB에 실제로 쌓여있던 튜닝 실행(id=8,
   22개 결과)을 불러와 버튼을 실제로 눌러본 결과, 유효 비교 후보가 2개 미만인 그룹(3개 그룹 중 2개는
   0개, 1개는 1개)을 실제로 발견 — 처음 구현에서는 이런 경우에도 "✅ 1등이 test에서도 최고였다"고
   과신하는 문구가 나오는 버그가 있었고(비교 상대가 없는데 "최고"라고 말하는 것), `n_valid_test` 필드를
   추가해 "비교 가능한 후보가 2개 미만이면 과적합 여부를 판단할 근거가 부족하다"고 정직하게 표시하도록
   수정했다(이 프로젝트의 기존 관례 — "미검증 상태를 정직하게 표시" — 그대로 따름).

- 검증: `tests/test_retry.py`(신규 6개), `tests/test_fred_data.py`(+1, 재시도 성공 케이스),
  `tests/test_market_data.py`(+2, 재시도 성공/소진 케이스, 기존 flaky 테스트는 `time.sleep` 무력화로
  속도 유지), `tests/test_strategy_tuning.py`(+8, `compute_overfitting_curve` 정렬/과적합 감지/
  top_n 제한/국면매칭/표본부족 케이스 포함) — 전체 `pytest tests/` **742개 통과**(기존 725개 +
  53 신규 - 사실 기존 파일 편집으로 순증 17개는 아니고 정확히는 신규 테스트 총 17개 추가, 725→742).
  Streamlit 개발 서버 + Playwright(Chromium)로 로컬 DB의 실제 튜닝 실행(run_id=8)을 불러와 3개
  스타일×국면 그룹 모두에서 "🔬 과적합 진단 실행" 버튼을 실제로 눌러 차트/캡션이 실제 데이터로
  정상 렌더되는 것과 서버 로그에 트레이스백이 없는 것을 확인(첫 구현의 `n_valid_test` 관련 버그를
  바로 이 과정에서 실제로 발견·수정).

### 작업 55 (2026-09-13, 같은 대화 후속): 챔피언 전략 — 실제 과거 백테스트 추가

사용자가 챔피언 전략 페이지를 써보다가 "이 전략을 사용했을 때의 백테스팅은 어떻게 할 수 있어?"라고
질문 — 확인해보니 작업52의 챔피언 전략 페이지는 "오늘 하루"만 계산하는 라이브 신호일 뿐, 과거
구간에 돌려볼 방법이 전혀 없었다(코어+새틀라이트 로테이션 포트폴리오는 기존 `run_backtest`(단일
종목 지표조건 백테스트)로는 애초에 표현이 안 되는 구조). 사용자 확인 후 백테스트 기능을 새로 구현.

- 새로 발명하지 않고, 이미 검증이 끝난 리서치 스크립트를 `core/champion_strategy.py`로 이식:
  코어는 `analysis/2026-08-19_champion_beta_and_satellite_research/champion_strategy.py`(작업22/23이
  검증한 스펙의 "재사용 가능한 재구현체"), 새틀라이트는 `analysis/2026-08-21_satellite_signal_upgrade_and_crisis_test/h10_trend_following_satellite.py`(final_config가 실제로 채택한, h1의 순수모멘텀
  버전이 아니라 "point-in-time 40종목 풀에서 돈치안 20일 브레이크아웃이 활성인 종목 중 12개월
  모멘텀 상위 3개"를 반기 리밸런싱하는 최종 버전)를 그대로 포팅.
- 신규 함수: `donchian_trailing_stop_positions()`(여러 analysis 스크립트에 복붙되던 걸 core로 통합),
  `run_core_backtest()`, `run_satellite_backtest()`(반기 리밸런싱, `core.strategy_tuning.sample_universe`
  point-in-time 풀 재사용), `run_champion_backtest()`(둘을 블렌드, 새틀라이트가 한 번도 못 뽑히면
  코어 100%로 자동 대체). `core.market_data.get_multiple_price_history`(스레드풀 병렬 조회)로 500종목
  가까운 point-in-time 풀 스캔도 실용적 속도로 처리.
- **알려진 차이(사용자에게 페이지 캡션으로 안내)**: 작업52의 라이브 "새틀라이트 후보 스캔"은 매번
  S&P500 전체(~500종목)를 스캔하는 단순화된 근사치이고, 이 백테스트는 리서치가 실제로 검증한
  "반기+point-in-time 40종목 풀" 방법론을 그대로 쓴다 — 완전히 같은 로직이 아님을 명시했다(정직성
  원칙). 라이브 쪽을 백테스트와 일치시키는 건 이번 범위에서 하지 않음(사용자가 원하면 후속 작업).
- `app/pages/11_챔피언_전략.py`에 "3. 백테스트" 섹션 추가 — 기간(기본 최근 3년)/새틀라이트 비중
  슬라이더 + `job_manager.start()` 버튼 트리거(느린 계산이라 5_종목_스크리닝.py와 동일 패턴), 결과는
  챔피언/코어단독/S&P500매수보유 3-way 자산가치 비교 + 지표 카드(CAGR/샤프/MDD/칼마) + 드로다운
  차트 + 월별 수익률 히트맵(전부 기존 theme.py/backtest_engine.py 헬퍼 재사용) + 새틀라이트 반기
  리밸런싱 로그.
- 검증: `tests/test_champion_strategy.py`에 신규 단위테스트(코어 로테이션이 실제로 상승 리더에만
  비중을 싣고 하락 자산은 배제하는지, 시장필터가 SPY 하락 추세에서 실제로 50% 축소를 적용하는지,
  반기 스케줄이 1월/7월만 고르는지, 돈치안 진입/청산이 실제로 작동하는지, 새틀라이트가 활성
  브레이크아웃 종목만 고르는지, 코어+새틀라이트 블렌드와 새틀라이트 실패 시 폴백) 추가. 실제 라이브
  데이터로 `run_core_backtest`/`run_satellite_backtest`/`run_champion_backtest`를 각각 실행해
  end-to-end 확인(1년 구간 챔피언 백테스트 실측 CAGR 5.91%/샤프 0.54/MDD -10.27%, 정상 종목
  선정 — 2023년 상반기 XOM/CVX/LLY, 하반기 NVDA/NFLX/AVGO를 새틀라이트로 선정해 2023 AI 랠리를
  실제로 반영). Streamlit+Playwright로 실제 브라우저에서 백테스트 실행 버튼 클릭 후 결과 렌더링
  확인(진행 중 — 같은 세션의 다른 서브에이전트가 병행 작업 중인 페이지/모듈과 충돌 없음을 확인).

### 작업 56 (2026-09-13, 같은 대화 후속 — 다른 서브에이전트가 작업55와 병행 진행): 챔피언 전략 파라미터 민감도/견고성 분석 슬롯 추가

사용자가 "에이전트 하나 더 분화해서 알고리즘 매매를 위한 최적 전략을 찾을 수 있도록 하는 슬롯을
디벨롭해달라"고 요청 — 작업55(같은 대화, 병행 진행 중)가 챔피언 전략의 백테스트 함수(`run_core_
backtest`/`run_satellite_backtest`/`run_champion_backtest`)를 막 추가한 직후라, 그 튜닝 가능한
파라미터(새틀라이트 비중/코어 상위 N종목/시장필터 축소 배수/새틀라이트 top_k/새틀라이트 후보 풀
크기)에 대한 **자동 탐색 슬롯**으로 해석해 진행. 단, 이 프로젝트는 "단일 백테스트 최고 수익률
설정을 그냥 채택"하는 방식을 강하게 경계해온 문화라(가중치 자산배분이 블록부트스트랩/워크포워드
감사를 거치며 확신도가 반복적으로 깎인 사례들, Day3 스크린샷 코멘트 "This is for evaluating a
strategy, Not for data-mining which is useless" 등) 새 방법론을 발명하지 않고 `core/strategy_
tuning.py`(train/test 75/25 분리, `compute_overfitting_curve`의 "train은 계속 좋아지는데 test가
갈라지면 과최적화" 진단 철학)와 `core/backtest_engine.py::run_sensitivity_sweep`(이웃 값 간 완만한
변화=견고 vs 뾰족한 피크=과최적화 의심 휴리스틱)의 기존 관례를 그대로 재사용했다.

- `core/champion_strategy.py`: `_build_core_weights`/`run_core_backtest`에 `top_n`/`exposure_cut`
  오버라이드 인자, `_pick_satellite_at_date`/`run_satellite_backtest`에 `pool_n` 오버라이드 인자
  추가(기존 호출부는 기본값 그대로라 동작 불변). 신규 함수:
  - `run_core_param_sensitivity(param_name, values, start, end, ...)` — core_top_n/market_filter_
    exposure_cut을 값마다 train/test 구간에서 각각 재실행(17자산뿐이라 빠름).
  - `run_satellite_weight_sensitivity(values, start, end, ...)` — satellite_weight는 블렌드 비중일
    뿐이므로 코어·새틀라이트 백테스트를 각 1회만 실행해두고 값마다 재블렌드만 함(가장 느린 새틀라이트
    point-in-time 스캔을 반복하지 않는 핵심 최적화).
  - `run_satellite_param_sensitivity(param_name, values, start, end, ...)` — satellite_top_k/
    satellite_pool_n을 값마다 반기 point-in-time 스캔째로 재실행(가장 느림). 구간이 짧아 반기
    리밸런싱일이 없으면 `run_satellite_backtest`가 던지는 ValueError를 그 포인트의 metric=None으로
    정직하게 흡수(예외 전파 없이 스윕 계속).
  - `run_champion_param_sweep(param_name, ...)` — 위 셋에 위임하는 단일 진입점.
  - `_finalize_param_sensitivity()` — train 곡선 견고성(`run_sensitivity_sweep`과 동일한 이웃-점프
    휴리스틱)과 "train 최적값이 test에서도 최적이었는지"(`peaks_agree`, 다르면 과최적화 의심 신호)를
    계산해 공유. `CHAMPION_TUNABLE_PARAMS` 딕셔너리로 각 파라미터의 UI 기본 탐색 그리드/설명 노출.
  - 이 슬롯도 다른 함수들과 마찬가지로 **단일 최고 설정을 추천하지 않는다** — train/test 각 곡선과
    견고성 판정만 반환, 채택은 항상 사람이 판단.
- `app/pages/12_챔피언_전략_최적화.py`(신규): 작업52/55가 배선 중인 `11_챔피언_전략.py`와 충돌하지
  않도록 별도 페이지로 분리. 파라미터 선택 + 값 목록(쉼표 구분 텍스트 입력, 기본값은 `CHAMPION_
  TUNABLE_PARAMS`의 그리드) + 기간 + train 비율 + 평가지표 선택 UI, `job_manager.start()`/`render()`
  버튼 트리거(느린 계산이라 5_종목_스크리닝.py 관례 재사용 — 이 페이지는 버튼 하나뿐이라 `ensure()`
  rerun 충돌 이슈 자체가 발생하지 않음, 그 가드 패턴은 11_챔피언_전략.py 것을 읽기만 하고 그대로
  둠). 결과는 train/test 두 선(plotly, `1_전략_스튜디오.py` 민감도 탭과 동일 스타일) + 견고성
  배지(success/warning) + peaks_agree 배지 + 상세 표.
- 검증: `tests/test_champion_strategy.py`에 신규 단위테스트 9개(견고/뾰족한 피크 각각 합성 데이터로
  판정 확인, satellite_weight 스윕이 코어/새틀라이트 백테스트를 정확히 1회씩만 호출하는지 콜카운트로
  증명, 짧은 구간의 ValueError를 metric=None으로 흡수하는지, 알 수 없는 파라미터명 거부, 디스패처
  라우팅, top_n/exposure_cut이 실제로 `_build_core_weights` 결과를 바꾸는지) 추가 — 전체
  `pytest tests/` **759개 통과**(작업55가 이미 추가해둔 백테스트 테스트 8개 포함, 충돌 없음 확인).
  Streamlit 개발 서버(포트 8600 — 작업55 서브에이전트가 8501을 이미 쓰고 있어 별도 포트로 분리해
  간섭 방지) + Playwright(Chromium)로 실제 브라우저에서 core_top_n 파라미터(2/3/4, 2022~2023
  실구간)를 실제 라이브 시장 데이터로 스윕 실행 확인 — train 곡선이 견고하지 않음(이웃 점프
  0.32/전체범위 0.44)과 train 최적값(2)이 test에서도 최적이었음(peaks_agree=True)이 동시에 나오는

### 작업 57 (2026-09-14): 챔피언 전략 엔진 고도화 — 옵션 칼라 헤지 라이브화 + 오늘의 종합 판단 카드

사용자가 "연구 에이전트/연구 리포트를 바탕으로 주식 정보를 정량적으로 파악하고 언제 어떤 주식을
사야할지 판단하는 엔진을 고도화해달라"고 요청 (같은 요청에서 페이지 정리도 별도 서브에이전트로
병행 지시 — 아래 작업58 참고). 확신도 감사표(confidence_table)를 다시 검토한 결과, "개별주 전면
확장"은 이미 공식 기각(reversed)된 방향이라(섹터ETF전용 대비 샤프 폭락) 새로운 개별종목 스크리닝
엔진을 얹는 대신, 이 리서치 프로그램이 이미 검증했지만 "라이브 계산 없이 리서치 결론만 인용"하는
채로 남아있던 유일한 구성요소 — 옵션 칼라 헤지 — 를 실제로 라이브 계산 가능하게 만드는 쪽을 골랐다
(사용자 확인 없이 진행 — 2026-07-17 메모대로 애매한 신규 기능도 판단해서 바로 구현하는 전면 자율
모드가 이미 승인돼 있음).

- **옵션 칼라 헤지가 왜 지금까지 "라이브 계산 제외"였는지 재확인**: 작업52 당시엔 "실시간 옵션
  가격 데이터 인프라가 없다"고 판단해 제외했다. 그러나 리서치 원문
  (`analysis/2026-08-30_synthetic_options_tail_hedge/h_options_hedge.py`)을 다시 보니 애초에 실제
  옵션체인을 쓴 적이 없다 — SPY 종가 + VIX(내재변동성 대리치, VIX/100) + FRED FEDFUNDS(무위험금리)로
  합성 Black-Scholes 가격을 매기는 방식이라 실시간 옵션 시세 없이도 그대로 라이브 계산이 가능했다.
  이 착오를 바로잡아 그 스크립트를 `core/champion_strategy.py`로 이식(새 방법론 발명 없음).
- **신규 함수** (`core/champion_strategy.py`): `bs_put_price`/`bs_call_price`(Black-Scholes, scipy 없이
  math.erf로 정확한 정규CDF), `_fedfunds_rate_asof`(FRED FEDFUNDS 캐시에서 asof 조회),
  `build_collar_overlay_returns`(월별 롤링 합성 칼라의 일별 수익률 — h_options_hedge.py와 동일 로직),
  `run_champion_backtest_with_collar`(기존 챔피언 백테스트에 칼라 비교선을 추가 필드로만 얹음, 기존
  동작 불변), `compute_live_collar_state`(오늘 기준 이번 롤 사이클의 행사가/잔존만기/마크투모델
  손익). 확신도가 weak라(부트스트랩 90% CI가 부호조차 확정 못함) 기본
  `run_champion_backtest`/`compute_satellite_recommendation` 동작에는 전혀 섞지 않고 전부 별도
  함수로만 노출 — 이 프로젝트의 "단일 최고 설정을 강제 채택하지 않는다" 관례를 그대로 따름.
- **오늘의 종합 판단 카드** (신규, 부가): `load_market_regime_context()`가
  `core.market_regime.select_regime_for_trading()`(매일 밤 이미 계산해둔 국면 스냅샷 재사용, 추가
  계산 비용 없음)을 그대로 노출한다. **주의**: 이 값은 참고 정보일 뿐, 코어/새틀라이트 배분 계산에는
  전혀 관여하지 않는다 — confidence_table이 국면조건부 동적 스위치(H12/H13)를 기댓값 기준으로
  반복 기각했기 때문에, 이 엔진이 그 결론을 스스로 뒤집지 않도록 의도적으로 "표시만 하고 반영 안 함"
  으로 설계했다.
- **UI** (`app/pages/11_챔피언_전략.py`): 코어/새틀라이트 섹션 사이에 "오늘의 종합 판단" 3칸 카드
  (코어 실투입 비중/새틀라이트 보유 상태/시장국면 참고) 추가. 백테스트 섹션에 "칼라 헤지 비교선
  추가" 체크박스(체크 시 `run_champion_backtest_with_collar` 호출) + 칼라 적용 시 지표 4종 카드 +
  롤 로그 expander. 기존 "4. 옵션 칼라 헤지" expander(참고용, 계산 없음)를 실제 라이브 카드(이번 롤
  시작일/잔존 거래일/행사가/마크투모델 손익)로 교체, 리서치 원문 인용은 하위 expander로 유지.
- 검증: `tests/test_champion_strategy.py`에 신규 단위테스트 12개(콜-풋 패리티로 BS 공식 정합성,
  만기(T=0) 내재가치 폴백, 평탄한 시장에서 매달 롤+페이오프 0, 만기 무렵 급락 시 풋 페이오프가
  실제로 발생, 챔피언+칼라 백테스트가 기존 필드를 안 바꾸는지, 라이브 상태가 데이터 없을 때 None,
  라이브 상태의 행사가가 moneyness와 일치하는지, 국면 컨텍스트 없음/있음 처리) 추가 — 전체
  `pytest tests/` **768개 통과**. 실제 라이브 데이터로 `compute_live_collar_state()`/
  `load_market_regime_context()`/`run_champion_backtest_with_collar('2022-01-01','2022-12-31')`
  실행 확인(2022 약세장 실측: 칼라 적용 시 샤프 0.05→0.23, MDD -12.54%→-11.41% — 방향이 리서치
  결론과 일치). Streamlit `AppTest`로 페이지 전체 로드 확인(예외 없음, 신규 섹션 전부 렌더링 확인).
  실제 사례를 관찰, 차트/배지/상세표 모두 정상 렌더 및 콘솔/서버 에러 없음 확인.

### 작업 58 (2026-09-14, 작업57과 병행 진행된 별도 서브에이전트): 페이지/모듈 중복 감사 — "불필요한 기능 제거 또는 슬롯 통합"

사용자가 "서브 에이전트를 통해 필요없는 기능들은 없애거나 하나의 슬롯으로 몰아넣어달라"고 요청.
`app/pages/11_챔피언_전략.py`/`12_챔피언_전략_최적화.py`/`core/champion_strategy.py`는 작업57이 같은
시각에 손대고 있어 감사 대상에서 완전히 제외(읽지도 않음). 결론부터: **광범위한 재작성을 정당화할
만한 중복이 남아있지 않아, 코드 변경은 하지 않았다.** 아래는 실제로 조사한 후보와 손대지 않기로
한 근거.

- **core 모듈 사용 그래프 전수조사**: `core/*.py` 35개 전부에 대해 다른 core 모듈/`app/pages/*.py`에서의
  참조 횟수를 세어봤다(app/Home.py 제외). 참조 1회짜리 모듈(`guru_tracker`/`stock_discovery`/
  `strategy_library`/`strategy_explainer`/`era_validation`/`etf_holdings`/`chart_rendering`)도 전부
  "페이지 하나만 쓰는 게 자연스러운 단일 목적 모듈"이라 문제 없음을 개별 확인(예: `etf_holdings`는
  4_거장_포트폴리오.py 전용 ETF 구성종목 조회, `strategy_library`는 1_전략_스튜디오.py의 저장/조회/삭제
  공용 로직이라는 docstring 그대로). **완전히 미참조(0회)인 top-level 함수/클래스는 core 전체에서
  하나도 없었다** — 죽은 코드가 사실상 없다는 뜻.
- **비슷한 이름의 모듈 쌍 재확인**: `core/kostolany_cycle.py`(현재 국면 스냅샷)와
  `core/kostolany_scenario_engine.py`(그 국면 신호를 따랐다면의 백테스트)는 docstring에서부터 서로
  다른 책임을 명시하고 실제로도 각각 7_시장_진단.py의 스냅샷 섹션/시나리오 섹션이 따로 쓰고 있어
  통합 대상이 아님. `pyflakes`로 찾은 `kostolany_scenario_engine.py`의 미사용 import
  (`STYLE_LABELS`/`STYLE_ORDER`) 1건은 기능 중복이 아니라 단순 린트성 잔재라 이번 과제 범위(기능
  제거/슬롯 통합) 밖으로 판단해 손대지 않음.
- **차트 렌더링 중복 의심 → 조사 결과 중복 아님**: `9_차트_조회.py`가 자체 `render_chart()`(캔들+거래량+
  RSI/MACD, 분봉 갭 없는 카테고리형 x축)를 갖고 있고 `core/chart_rendering.py`도 `render_price_chart()`
  (캔들+지표 오버레이+매매 진입/청산 마커, 1_전략_스튜디오.py와 야간 리더보드가 공유)를 갖고 있어
  처음엔 통합 후보로 봤으나, 실제로는 x축 처리 방식(분봉 갭 제거용 카테고리 라벨 vs 백테스트용 날짜
  인덱스)과 오버레이 대상(자유 지표 토글 vs 전략 조건+거래 마커)이 근본적으로 달라 억지로 합치면
  분봉 갭 제거 로직이 깨질 위험이 있었다. 대신 `9_차트_조회.py`는 이미 `core/theme.py`의
  `style_chart_like_tradingview`/`inject_chart_interactions`/`TRADINGVIEW_CHART_CONFIG`(공통 스타일)와
  `core/watchlist.py`(관심종목 추가/조회/삭제)를 재사용하고 있어, 진짜 중복되는 부분(스타일링)은 이미
  작업이 끝나 있었다 — 나머지(캔들 렌더링 본체)만 남기는 것이 맞다고 판단.
- **"포트폴리오" 이름이 겹치는 두 페이지**(`4_거장_포트폴리오.py`=SEC 13F/ARK 등 타인 보유종목 추적,
  `8_포트폴리오_관리.py`=내 실제 보유종목 손익 분석)도 검토했으나, 데이터 소스·목적·갱신 주기가 전혀
  달라(외부 공시 조회 vs 사용자 직접 입력) 슬롯으로 합치면 오히려 UX가 혼란스러워질 후보라 제외.
  `2_Threads_요약.py`(소셜미디어 요약)도 시장진단/챔피언과 도메인이 겹치지 않아 제외.
  `10_환경설정.py`(페이지 순서 편집 유틸)는 다른 모든 페이지의 순서를 조정하는 메타 기능이라 애초에
  통합 대상이 될 수 없음.
- **`app/Home.py` 모듈 요약표**는 이미 (부가) 표시로 7_시장_진단.py에 흡수된 "섹터 리더/성장주"를
  독립 페이지가 아닌 부가 기능으로 정확히 반영하고 있어 갱신 불필요.
- 결론: PROGRESS.md 최근 기록([[feedback_quant_workflow]]에도 있는 "이미 여러 차례 통합 작업을
  거쳤다"는 전제)대로, 7_시장_진단.py(매크로+국면+섹터강도+섹터리더+코스톨라니 통합)와
  1_전략_스튜디오.py(백테스트+자연어+튜닝+합성+상관+배치+야간리더보드+관리 8탭 통합),
  5_종목_스크리닝.py(필터+팩터발굴 2탭 통합)가 이미 이 세션이 하려던 일을 선행 세션들이 끝내둔
  상태였다. 억지로 뭔가를 합치거나 지우면 라이브 운영 앱에 회귀 위험만 추가한다고 판단해, 이번
  작업은 **감사(audit) 자체가 산출물**이며 코드 변경 없음.
- 검증: 코드 변경이 없으므로 감사 시작 시점(768 passed)과 종료 시점 모두 `python3 -m pytest tests/ -q`
  **768개 통과** 동일 확인.

### 작업 59 (2026-09-14, 같은 대화 후속): 챔피언 엔진 ↔ 실제 포트폴리오 연결 + 새틀라이트 사이징 옵션 + 텔레그램 신호 알림

작업57에서 "다음 고도화 지점"으로 제안한 세 가지(챔피언 엔진과 실제 보유 포트폴리오 연결, 새틀라이트
포지션 사이징, 신호 변경 알림 채널)를 사용자가 전부 승인 — "2번은 개선, 3번은 텔레그램으로, 1번은
내가 포트폴리오를 어떻게 넣어야 하는지" 질문. 1번은 이미 `8_포트폴리오_관리.py`에 수동 입력 폼(티커/
수량/매입가/매입일)이 있고 증권사 자동연동은 없다는 걸 확인시켜준 뒤, 그 수동 입력 데이터를 챔피언
엔진과 실제로 연결하는 기능을 구현.

- **① 리밸런싱 diff (`core/champion_strategy.py::compute_rebalance_diff`)**: 코어 top4/새틀라이트
  선정종목의 목표비중과 `core.portfolio.get_portfolio_pnl()`(기존 함수 그대로 재사용, 사용자가
  8번 페이지에 입력해둔 실제 보유)의 현재비중을 비교해 종목별 매수/매도/유지 + 금액 차이표를
  만든다. 총 계좌가치는 "보유 종목 시가총액 합계"로 근사(이 앱은 현금 잔고를 안 받음 — 전량투자
  가정을 페이지에 명시). 시장필터/새틀라이트 미배정분은 "CASH" 행으로 별도 표시하되, 새틀라이트를
  아직 스캔하지 않았으면(모르는 걸 안다고 하지 않기 위해) 그 몫은 diff에 포함하지 않고 캡션으로
  안내. `app/pages/11_챔피언_전략.py`에 "5. 내 포트폴리오와 비교" 섹션 신규 추가(보유 종목이
  없으면 8번 페이지 입력을 안내).
- **② 새틀라이트 포지션 사이징 opt-in (`compute_satellite_recommendation`/`run_satellite_backtest`/
  `run_champion_backtest`에 `sizing_method` 파라미터 추가, 기본값 "equal"=기존 동작 그대로)**:
  "inverse_vol"을 고르면 `core.position_sizing.portfolio_volatility_target_weights`(이미 다른
  페이지에서 검증돼 쓰이는 기존 함수, 새 방법론 발명 없음)로 선정 종목의 최근 20일 변동성 역가중
  비중을 계산(한 종목 상한 40%=`SATELLITE_SIZING_MAX_WEIGHT`). **중요한 구분**: confidence_table의
  "위험조정 모멘텀 랭킹" reversed 판정은 "어떤 종목을 고를지"(랭킹 기준) 얘기고, 이 옵션은 "이미
  고른 종목 안에서 비중을 어떻게 나눌지"라 서로 다른 질문 — 그래도 이 리서치 프로그램이 감사한
  적 없는 새 시도라 기본값으로 넣지 않고 opt-in + "미검증" 라벨을 유지, 사용자가 백테스트로 직접
  비교(체크박스는 세션 상태로 라이브/백테스트 양쪽에 공유)해서 판단하도록 설계.
- **③ 텔레그램 신호 변경 알림**: `core/telegram_notify.py`(신규, `core/notify.py`의 데스크톱
  알림과 별개 채널) — `requests`로 텔레그램 Bot API 호출, 설정 없거나 실패해도 예외 없이 False.
  기존에 사용자가 Oracle VM 관리용으로 이미 만들어둔 봇(`new/oracle-free-tier/telegram_config.json`,
  git 추적 안 됨)의 토큰/채팅ID를 `.env`(git 추적 안 됨)로 정식 이관 — `.env.example`에 발급 방법
  주석과 함께 플레이스홀더 추가. `core/champion_strategy.py::check_and_notify_signal_changes()`가
  코어 top4/시장필터/새틀라이트 선정종목을 `data/cache/champion_signal_state.json`에 저장된 어제
  상태와 비교해 달라졌을 때만 알린다(새 판단을 만들지 않음 — 이미 계산된 결과의 비교/알림만).
  `scheduler/run_scheduler.py`에 `champion_signal_alert_job()` 추가, 매일 한국시간 00:10(다른
  야간 잡들과 안 겹치게 offset)에 실행하도록 등록. 실제 텔레그램으로 테스트 메시지 전송해 연동
  확인(사용자에게 그 사실을 대화로 알림).
- 검증: `tests/test_champion_strategy.py`에 신규 단위테스트 20개(리밸런싱 diff 7개 — 빈 포트폴리오/
  매수매도판정/유지밴드/코어+새틀라이트 비중합산/현금행/새틀라이트 미스캔 시 제외/get_portfolio_pnl
  자동호출, inverse_vol 사이징 6개 — 저변동성 종목이 더 큰 비중 받는지/2종목 미만 시 폴백/
  compute_satellite_recommendation 통합/단일종목 폴백/백테스트 리밸런싱마다 비중합 1.0/알 수 없는
  sizing_method 거부, 텔레그램 신호알림 7개 — 최초실행/무변경시침묵/top4변경/시장필터변경/
  새틀라이트변경 감지, satellite 스킵 옵션, 디스크 영속화), `tests/test_telegram_notify.py`
  신규 6개(설정 유무, 전송 성공/실패/네트워크예외, 실제 요청 payload 검증) 추가 — 전체
  `pytest tests/` **794개 통과**. Streamlit `AppTest`로 "5. 내 포트폴리오와 비교" 섹션을 실제
  임시 DB에 TLT/NVDA 보유를 넣고 렌더링까지 확인(예외 없음, diff 테이블 정상 표시).

### 작업 60 (2026-09-14, 별도 서브에이전트): 새틀라이트 "라이브 추천"과 "백테스트"가 서로 다른
전략을 측정하던 문제 수정 — point-in-time 라이브 계산 추가

작업57/59까지 `compute_satellite_recommendation()`("오늘의 라이브 추천")은 매번 현재 S&P500 전체를
스캔해 돈치안 20일 브레이크아웃 중인 종목 중 **3개월** 모멘텀 상위 **5개**를 고르는 "단순화된
근사치"였던 반면, `run_satellite_backtest`/`_pick_satellite_at_date`(실제로 검증된 방법론)는 반기
(1월/7월 첫 거래일)에만 리밸런싱하고 그때마다 point-in-time 유니버스 표본(40종목, 시점 당시
시가총액 기준)을 새로 뽑아 그중 돈치안 브레이크아웃+트레일링스탑이 **활성**인 종목의 **12개월**
모멘텀 상위 **3개**를 고른다 — 페이지에 뜨는 "라이브 추천"과 "백테스트 성과"가 서로 다른 전략을
가리키는 상태였다. 이번 작업은 새 전략을 만들지 않고, 백테스트가 이미 쓰는 로직을 라이브 신호에도
그대로 재사용해 이 간극을 없앤다.

- **`core/champion_strategy.py::compute_satellite_recommendation_point_in_time(as_of_date=None,
  pool_n=SATELLITE_BACKTEST_POOL_N, top_k=SATELLITE_BACKTEST_TOP_K, sizing_method="equal")`
  (신규)**: `_semiannual_rebal_dates`로 as_of_date(기본값 오늘) 이전 가장 최근 반기 리밸런싱일을
  찾은 뒤(거래일력은 SPY 가격 이력의 인덱스를 재사용 — `run_champion_backtest`가 core 백테스트
  결과 인덱스를 trading_index로 쓰는 것과 동일한 관례), `_pick_satellite_at_date(rebal_date, ...)`를
  **그대로 호출**해 그 시점의 point-in-time 선정 종목/비중을 얻는다 — 랭킹 로직을 여기서 다시 만들지
  않음. "직전 리밸런싱 이후 계속 보유했다면 지금 뭘 들고 있을지"를 보여주는 게 목적이라, 선정
  종목별로 리밸런싱일→현재 가격/수익률(`price_at_rebal`/`current_price`/`return_since_rebal_pct`)도
  같이 계산해서 반환한다. 다음 리밸런싱까지 남은 거래일수(`trading_days_to_next_rebal`)는 미래
  거래일력을 알 수 없어 주말만 제외한 근사치(공휴일 미반영)로 계산 — 반환값에 그 사실을 문서화.
  `sizing_method`("equal"/"inverse_vol")는 기존 `compute_satellite_recommendation`과 동일하게
  `_inverse_vol_weights`를 그대로 재사용하는 opt-in 옵션.
- **`app/pages/11_챔피언_전략.py` "2. 새틀라이트" 섹션 UI 재구성**: 탭 두 개로 분리 — "✅
  백테스트와 동일한 방법 — 반기 point-in-time"(신규 함수, 1차 추천으로 배치)과 "🔍 빠른 근사 스캔
  (참고용 — 백테스트와 다른 방법론)"(기존 `compute_satellite_recommendation`, 그대로 유지) — 삭제
  대신 "둘 다 보여주되 어느 쪽이 검증된 방법인지 명확히 구분"하는 이 저장소 관례를 따름. 아래 "오늘의
  종합 판단"/"5. 내 포트폴리오와 비교" 섹션이 쓰는 `satellite_result`는 point-in-time 결과가 있으면
  그쪽을 우선하고, 없으면 기존 스캔 결과로 폴백(두 함수 반환 dict가 `selected`/`per_ticker_weights`
  키를 공유해 `compute_rebalance_diff` 등 기존 코드 변경 없이 그대로 호환됨). "1. 코어"/"3.
  백테스트"/"4. 옵션 칼라 헤지"/"5. 내 포트폴리오와 비교" 섹션은 병행 작업 중인 다른 브랜치와의
  충돌을 피하기 위해 손대지 않음.
- **검증**: `tests/test_champion_strategy.py`에 신규 단위테스트 9개 — point-in-time 결과가
  `_pick_satellite_at_date`를 직접 호출한 것과 정확히 일치하는지, as_of_date가 3월/8월/1월 중순 등일
  때 각각 올바른 직전 반기 리밸런싱일(1월/7월/그 해 1월)을 고르는지(파라미터화 3케이스),
  픽별 price_at_rebal/current_price/return_since_rebal_pct가 정확히 계산되는지, 활성 브레이크아웃이
  하나도 없을 때 빈 결과로 안전하게 대체되는지, inverse_vol 사이징이 실제로 갈라지고 합계가
  SATELLITE_WEIGHT를 유지하는지, 알 수 없는 sizing_method/유효한 리밸런싱일이 전혀 없는 경우 각각
  ValueError를 던지는지 확인. 전체 `pytest tests/` 801개 통과(기존 792통과+2건 무관한 기존 실패
  `test_strategy_library_archive.py`는 이 작업 전에도 동일하게 실패하던 것으로 확인 — 별도
  테스트간 DB 격리 이슈, 이번 변경과 무관, 손대지 않음), 신규 9개 모두 통과.
- **부록(이 작업 중 발견)**: 이 서브에이전트가 배정된 워크트리(`worktree-agent-a7cddb24459a38680`)의
  브랜치가, 다른 세션에서 실행된 "chore: nightly ..." 자동 커밋 체인이 오래된/스테일 체크아웃에서
  커밋되는 바람에 `core/champion_strategy.py`/`core/point_in_time_market_cap.py`/`core/retry.py`/
  `core/telegram_notify.py`/`PROGRESS.md`(1628줄)/새틀라이트 관련 테스트 등 작업57~59가 만든 내용
  대부분을 조용히 삭제한 채로 base 커밋(21c9a78)보다 뒤처져 있었다 — 이번 작업을 시작하기 전에
  해당 파일들을 21c9a78 시점 내용 그대로 복원하는 별도 커밋을 먼저 만들어 base 상태를 맞췄다. 다른
  워크트리에서도 같은 야간 자동커밋 체인이 발견되면 같은 방식(21c9a78부터 필요한 파일만
  `git checkout 21c9a78 -- <path>`로 복원 후 diff가 0인지 확인)으로 정리 권장 — 원인(어느 자동화가
  스테일 체크아웃에서 커밋을 만드는지)은 이번 작업 범위 밖이라 별도 조사가 필요하다.

### 작업 61 (2026-09-14, 같은 대화 후속): 챔피언 전략 리밸런싱 예정일 사전(D-1) 텔레그램 알림

작업59의 `check_and_notify_signal_changes()`(00:10)는 리밸런싱이 "이미 일어난 뒤" 어제 상태와
비교해서만 알린다 — 사용자가 다음날 아침 실제로 주문을 넣으려면 "내일이 리밸런싱일"이라는 사전
예고가 따로 필요하다는 걸 확인하고 그 갭을 메움.

- **`core/champion_strategy.py::check_and_notify_upcoming_rebalance(days_before=1, notify_fn=None)`
  신규**: 새 배분 로직을 만들지 않는다 — 코어는 `_build_core_weights`가 쓰는
  `core.backtest_engine._first_trading_day_of_month_mask`("매월 첫 거래일")와, 새틀라이트는
  `_semiannual_rebal_dates`/`SATELLITE_REBAL_MONTHS`("1월/7월 첫 거래일")와 같은 규칙만 재사용한다.
  **핵심 제약**: "내일"은 아직 실현되지 않은 미래라 실제 거래소 캘린더(휴장일 포함)를 알 수
  없다 — `get_price_history` 등은 과거 거래일만 반환하므로 미래 휴장일은 원천적으로 알 방법이
  없다. 그래서 이 코드베이스에 별도 거래캘린더 유틸이 있는지부터 확인했지만(없음을 확인),
  새로 라이브러리를 들이는 대신 **달력 요일 기준 근사치**를 정직하게 채택: "그 날짜 이전의 가장
  가까운 평일(주말 제외)이 다른 달에 속하면 이 달의 첫 거래일로 본다"(`_is_calendar_first_trading_
  day_of_month`). 미국 거래소 휴장일(신정/추수감사절/성탄절 등, 주말이 아닌 날)이 월초에 끼면
  최대 며칠 오차가 날 수 있다는 걸 함수 독스트링/스케줄러 모듈 독스트링에 명시(예: 신정이 평일이면
  실제 첫 거래일은 다음날이지만 이 근사치는 신정 당일을 오판할 수 있음) — 정확성을 과장하지 않는
  이 프로젝트 관례를 그대로 따름. 코어/새틀라이트 판정을 각각 `_is_core_rebalance_date`/
  `_is_satellite_rebalance_date`로 분리해 독립적으로 테스트 가능하게 함. 같은 리밸런싱 날짜
  조합에 대해서는 한 번만 알린다 — `data/cache/champion_rebalance_reminder_state.json`에 직전에
  알린 날짜 조합을 저장해두고 비교(`_load_last_reminder_state`/`_save_reminder_state`,
  `check_and_notify_signal_changes`의 상태 캐시 패턴 그대로 재사용) — `days_before`가 1보다
  커서 같은 미래 날짜가 여러 날에 걸쳐 감지돼도 중복 알림을 보내지 않는다.
- **`scheduler/run_scheduler.py::champion_rebalance_reminder_job()` 신규**: 매일 한국시간
  00:15(00:00/00:05/00:10 기존 잡과 안 겹치는 빈 슬롯)에 등록, `check_and_notify_upcoming_
  rebalance()` 호출만 담당. 모듈 상단 독스트링에 잡 설명 추가(기존 스타일 그대로). 텔레그램
  설정이 없으면 다른 챔피언 잡들과 마찬가지로 조용히 알림만 생략(예외 없음).
  `compute_satellite_recommendation`/`compute_core_recommendation`/`compute_rebalance_diff`/
  UI 페이지(`app/pages/11_챔피언_전략.py`)는 건드리지 않음(다른 서브에이전트가 같은 파일들을
  병행 작업 중이라는 지시에 따름) — 이번 작업은 스케줄러 + 독립 함수 추가로 한정.
- 검증: `tests/test_champion_strategy.py`에 신규 단위테스트 9개 — 사전알림 6개(코어 단독/
  새틀라이트 단독/코어+새틀라이트 동시/둘 다 없음 시 침묵/같은 예정일 재호출 시 dedupe/디스크
  영속화 — `check_and_notify_signal_changes` 테스트와 동일한 monkeypatch 상태캐시경로 + notify_fn
  리스트-append 패턴), 달력 근사 헬퍼 3개(`_is_calendar_first_trading_day_of_month`가 신정 오판
  케이스를 포함해 의도대로 동작하는지, `_is_satellite_rebalance_date`가 1월/7월에만 True인지,
  `_upcoming_weekdays`가 주말을 건너뛰는지) — 전체 `pytest tests/` **803개 통과**(신규 9개 +
  기존 794개, 기존에 있던 `test_strategy_library_archive.py` 실패 2건은 이번 작업과 무관하게
  베이스라인에서도 이미 실패 중이던 것으로 확인, 손대지 않음).

### 작업 62 (2026-09-14, 별도 서브에이전트): 현금 잔고 추적 추가 — 리밸런싱 diff의 "CASH 행 0.0 하드코딩" 근사치 제거

작업59가 `compute_rebalance_diff`를 만들 때 "이 앱은 현금 잔고를 입력받지 않는다"는 전제로 총
계좌가치를 "보유 종목 시가총액 합계"로만 근사하고, CASH 행의 현재비중/현재금액을 0.0으로
하드코딩해뒀다(UI에도 그 사실을 사과하는 캡션). 이번 작업은 그 전제 자체를 없애 현금 잔고를
실제로 추적하도록 만들었다.

- **저장 위치 결정**: `core/watchlist.py`/`core/page_order.py` 등 기존 모듈을 먼저 훑어봤지만
  이 프로젝트에는 재사용할 만한 범용 단일행 설정(key-value AppSetting) 패턴이 없었다(page_order.py는
  파일시스템 rename 기반이라 무관). 그래서 `PortfolioHolding`과 나란히 `core/models.py`에
  `PortfolioCashBalance` 모델을 신규 추가 — 이력을 쌓을 필요가 없는 "현재 값 하나"라서(다른
  스냅샷류 테이블들과 달리) 단일 행만 유지하는 get-or-create(upsert) 방식으로 설계했다.
- **`core/portfolio.py`**: `get_cash_balance() -> float`(저장된 적 없으면 0.0)/
  `set_cash_balance(amount: float) -> None`(음수 거부, 단일 행 upsert) 추가 — 기존
  `add_holding`/`update_holding`과 동일한 `with get_session()` 패턴을 그대로 재사용.
- **`app/pages/8_포트폴리오_관리.py`**: "➕ 보유 종목 추가" 폼 바로 아래 "💵 현금 잔고" expander를
  신규 추가(보유 종목이 하나도 없을 때 페이지가 조기 종료(`st.stop()`)되기 전에 배치해, 종목이
  없어도 현금만 먼저 기록할 수 있게 함) — number_input + 저장 버튼, 기존 폼 스타일 그대로.
  페이지의 나머지 구조(손익/리스크/매매근거 섹션)는 건드리지 않음.
- **`core/champion_strategy.py::compute_rebalance_diff`**: `cash_balance: Optional[float] = None`
  파라미터 추가(None이면 `holdings_pnl`과 동일한 지연 임포트 패턴으로 `core.portfolio.
  get_cash_balance()`를 직접 호출 — 테스트 주입 가능). `total_value`에 현금 잔고를 더하고, 이제
  분모가 "보유종목만의 합"이 아니게 됐으므로 각 종목의 현재비중도 `holdings_pnl`이 들고 있던
  `weight_pct`(보유종목끼리의 비중)를 쓰지 않고 `current_value/total_value`로 다시 계산하도록
  고쳤다. CASH도 다른 종목과 같은 target/current 딕셔너리에 넣어 같은 루프를 타게 만들어서,
  diff_pct/action(매수/매도/유지)이 다른 행과 완전히 동일한 기준으로 계산되게 했다 — 예전처럼
  무조건 "현금 보유"로 특수취급하지 않는다. 목표 현금비중이 0이어도(시장필터/새틀라이트가 완전
  배분) 실제 현금 잔고가 있으면 CASH 행이 뜨도록(목표 0 vs 현재 보유 → "매도"=다른 자산으로
  옮기라는 신호) 표시 조건을 `cash_weight > 0 또는 cash_balance > 0`으로 넓혔다(예전엔 현금을
  아예 몰랐으니 이런 케이스 자체가 없었음).
- **`app/pages/11_챔피언_전략.py`**: "5. 내 포트폴리오와 비교" 섹션의 캡션만 수정(다른 부분은
  손대지 않음 — 같은 파일의 새틀라이트 부분을 다른 서브에이전트가 병렬로 작업 중이라 범위를
  캡션 + `compute_rebalance_diff` 호출부로 한정) — "현금 잔고를 안 받는다"는 사과성 문구를
  제거하고 "총 계좌가치 = 보유 종목 + 현금 잔고, 8번 페이지에서 최신 상태로 유지해야 정확함"
  안내로 교체.
- 검증: `tests/test_portfolio.py`에 현금 잔고 CRUD 신규 테스트 5개(미설정 시 기본값 0.0/설정-조회
  라운드트립/반복 설정해도 단일 행 유지/음수 거부/0 허용), `tests/test_champion_strategy.py`
  기존 `compute_rebalance_diff` 테스트 7개 전부에 `cash_balance=0.0`을 명시로 추가해 실제 DB에
  의존하지 않게 고치고(현금 하드코딩 CASH 행 "현금 보유" 액션 단언은 이제 표준 매수/매도/유지
  판정을 따르므로 "매수"로 수정), 신규 테스트 4개(직접 주입 시 CASH 현재값/현재비중 및 다른
  종목 현재비중도 전체 계좌가치 기준으로 재계산되는지, 목표 0인데 실제 현금 있으면 CASH 행이
  뜨는지, `get_cash_balance()` 지연 호출 패턴) 추가. 전체 `pytest tests/` **800개 통과**(사전에
  이미 존재하던 무관한 실패 2건 `tests/test_strategy_library_archive.py::test_archive_unknown_
  strategy_raises`/`test_unarchive_unknown_strategy_raises`는 이번 작업과 무관 — 별도 테이블
  초기화 이슈로 이번 변경 전부터 실패하고 있었음, 손대지 않음).

### 작업 63 (2026-09-14, 별도 서브에이전트 — 다른 엔지니어들이 같은 페이지의 코어/새틀라이트/백테스트/
칼라헤지/포트폴리오diff 섹션을 병행 작업 중이라 번호가 순차적이지 않음): 챔피언 전략 ↔ 거장
포트폴리오 교차참조 배지 + Oracle VM 배포 상태 점검

지금까지 `4_거장_포트폴리오.py`(13F/ARK 추적)와 `11_챔피언_전략.py`(코어+새틀라이트 라이브 추천)는
서로 전혀 연결돼 있지 않았다. 코어 top4/새틀라이트 선정종목이 "추적 중인 거장도 실제로 들고 있는
종목인지"를 참고용으로만 보여주는 작은 교차참조 기능을 추가했다(A). 별도로, 배포 문서
(`deploy/DEPLOYMENT_ORACLE.md`)대로 실제 Oracle VM에 scheduler가 떠 있는지, 오늘까지의 신규
코드(작업59의 텔레그램 신호알림 등)가 반영됐는지를 직접 SSH로 점검했다(B, 코드 변경 없음).

- **A. 거장 보유종목 교차참조 배지**: `core/guru_tracker.py::find_gurus_holding_ticker(ticker) ->
  list[str]` 신규 — GuruHolding 테이블에서 해당 티커를 보유 중인 거장 이름을 이름순으로 반환하는
  순수 조회 함수(동기화된 거장이 하나도 없으면 빈 리스트, 새 알파 주장이나 배분 로직은 전혀 추가
  하지 않음). `app/pages/11_챔피언_전략.py`의 "1. 코어" top4 카드와 "2. 새틀라이트" 선정종목 카드
  밑에 `🏛️ 워런 버핏 등 2명의 추적 대상도 보유 중` 같은 짧은 캡션으로만 표시(동기화된 거장이 없으면
  아예 아무것도 표시하지 않아 조용히 사라짐). 코어/새틀라이트 추천 로직·백테스트·옵션 칼라 헤지·
  포트폴리오 diff 섹션("## 5.")은 다른 엔지니어들이 병행 작업 중이라 전혀 건드리지 않고, 배지 두
  줄만 추가. `load_market_regime_context()`와 같은 결의 "참고 정보일 뿐 배분에 반영 안 됨" 캡션을
  페이지 상단에 한 줄 추가해 검증되지 않은 신호로 오인되지 않게 함.
- **검증**: `tests/test_guru_tracker.py`에 신규 단위테스트 4개(동기화된 거장 없을 때 빈 리스트,
  단일/복수 거장이 보유한 티커의 이름 목록 정확성 및 이름순 정렬, 아무도 안 든 티커는 빈 리스트,
  대소문자 정규화·공백 입력 처리) 추가. `pytest tests/` 전체 **796개 통과**(기존
  `test_strategy_library_archive.py`의 실패 2개는 이 작업과 무관한 기존 실패로 그대로 남아있음 —
  베이스라인에서도 동일하게 실패).
- **B. Oracle VM 배포 상태 점검(코드 변경 없음, 읽기 전용)**: `new/oracle-free-tier/send_note.py`에
  남아있던 접속 정보(퍼블릭 IP)와, 이 개발 환경(Codespace)의 기본 SSH 공개키 코멘트가 우연히도
  `quant-oracle-vm`으로 이 VM에 이미 등록된 키와 일치해 실제로 SSH 접속이 가능했다. 접속해서 확인한
  결과: **`quant-streamlit.service`/`quant-scheduler.service` 둘 다 systemd로 정상 기동 중**
  (24시간+ 연속 가동, `ps aux`에서도 `run_scheduler.py` 프로세스 확인). 다만 **VM에 배포된 코드는
  `024a416`(9/13 야간 매크로 캐시 갱신 커밋) 기준으로 멈춰 있어, `core/champion_strategy.py` 자체가
  VM에 아직 존재하지 않는다** — 즉 작업59의 텔레그램 신호알림(`champion_signal_alert_job`,
  `check_and_notify_signal_changes`)과 이번 작업63의 거장 교차참조 배지 모두 VM에는 전혀 반영돼
  있지 않다(둘 다 아직 로컬/이 워크트리에만 있고 main에 머지·`git pull`된 적 없음). VM의 git
  워킹트리에는 추적 안 되는 `.cache/` 외 다른 변경사항이 없어 향후 `git pull` 자체는 충돌 없이
  가능해 보인다. **사용자가 직접 해야 할 일**: 이 작업들이 main에 머지된 뒤 `deploy/
  DEPLOYMENT_ORACLE.md` 6번 절차(`ssh ubuntu@138.2.11.196` → `git pull` →
  `systemctl restart quant-streamlit quant-scheduler`)를 실행해야 신호알림/교차참조 배지가
  실제로 라이브 반영된다 — 이번 점검은 그 필요성을 확인한 것뿐, 배포 자체는 하지 않았다(요청 범위가
  읽기 전용 점검이었음).

### 작업 64 (2026-09-14, 같은 대화 후속 — 작업57~63 배포 이후): FRED 거시지표(환율 등) 새벽 캐시 사전 갱신

배포 후 사용자가 "환율 등 특정 데이터를 불러올 때 시간이 좀 걸리는 것 같다, 새벽에 미리 일괄로
받아와서 접속했을 때 안 막히게 해달라"고 요청. 원인 조사(Explore 서브에이전트) 결과:
`core.fred_data.get_series()`가 파일 캐시(TTL 24시간)를 쓰는데, 캐시가 만료된 뒤 **그날 처음
이 페이지를 보는 사용자가 실시간 FRED API 호출(+실패 시 재시도)을 그 자리에서 그대로 떠안는
구조**였다 — `app/pages/7_시장_진단.py`의 "경제지표"/"경기 사이클" 섹션(원/달러 환율 DEXKOUS
포함)과 `core.market_regime.get_advisory_risk_signals()`가 쓰는 지표 전부 해당. 기존
`market_snapshot_job`(00:00)은 yfinance 기반 시장국면/섹터강도만 미리 계산해두고 이 FRED
지표들은 전혀 손대지 않고 있었다.

- **`scheduler/run_scheduler.py::fred_indicator_prewarm_job()` 신규**: 새 계산 로직을 만들지
  않는다 — 이미 있는 `core.fred_data.get_series(series_id, cache_ttl=0)`를 그대로 재사용하되
  `cache_ttl=0`만 줘서 "캐시가 있어도 무조건 새로 받아와서 저장"하도록 강제한다
  (`use_cache=True`는 그대로 유지되므로 받아온 값은 정상적으로 파일 캐시에 저장됨 — 나이 체크만
  항상 실패하게 만드는 방식). `core.fred_data.DEFAULT_INDICATORS`(대시보드 카드 8종 — 원/달러
  환율 DEXKOUS 포함) + `core.market_regime.get_advisory_risk_signals()`가 추가로 쓰는
  BAMLH0A0HYM2(하이일드 스프레드)/T10Y3M(장단기금리차)까지 총 10개 지표를 순회 갱신. 지표 하나가
  실패해도(FRED_API_KEY 없음/일시적 API 오류) 나머지는 계속 진행(예외 전파 없음).
- 매일 한국시간 **00:20**에 실행하도록 등록(기존 00:00/00:05/00:10/00:15 잡과 안 겹치는 다음
  빈 슬롯). 모듈 상단 독스트링 + "동작" 섹션에도 기존 스타일대로 설명 추가.
- 검증: 실제로 함수를 직접 호출해 라이브 데이터로 end-to-end 확인 — 10개 지표 전부 정상 갱신
  (원/달러 환율 DEXKOUS 최신값 1346.51원 등 실측), 약 10초 소요. 새 로직이 얇은 스케줄러 잡
  래퍼(기존에 테스트된 `get_series()`만 재호출)라 기존 관례대로 별도 단위테스트는 추가하지
  않음(다른 `*_job()` 함수들도 동일 관례). 전체 `pytest tests/` **824개 통과**(회귀 없음).
- **아직 VM에 미배포** — 이 작업은 로컬에서만 완료됨. 커밋/푸시 후 오라클 VM에서
  `git pull` + `systemctl restart quant-scheduler`를 해야 실제로 매일 밤 돌기 시작한다.

### 작업 65 (2026-09-14, 같은 대화 후속): 매일 밤 무인 리서치 에이전트 2개(B/C) 자동화 — Claude Pro 구독 기반

사용자가 "서버에서 특정 시간에 클로드 코드를 켜서 특정 명령을 수행하게 할 수 있냐, 내가 늘
쓰는 리서치 에이전트 둘(① 미국 10개 시장 & S&P500 포트폴리오 분석, ② 개별주와 텐베거 발굴
방법)에게 늘 일을 시키고 싶다, 최대한 토큰을 소진해서 가치를 뽑고 싶다"고 요청. claude.ai
웹 대화 세션 자체는 이 저장소에서 접근/재현할 수 없으므로, 그 두 세션이 실제로 만들어낸
결과물(`analysis/`의 29개+ 리서치 폴더, `docs/reports/`)을 직접 읽고 각 라인의 방법론/규칙/
아직 안 풀린 문제를 역으로 추출해서 두 에이전트의 페르소나 프롬프트를 새로 설계했다(사용자
확인 후 진행 — API 과금이 아니라 Claude Pro/Max 구독 로그인 기반으로 하겠다는 제약도 이때
확정, budget 폭주 위험 없음).

- **`deploy/research_agents/` 신규 디렉터리**:
  - `agent_b_market_portfolio.md` / `agent_c_tenbagger.md`: 각 라인의 확립된 규칙(순열검정+
    블록부트스트랩 이중검증, point-in-time 유니버스, 6구간 기댓값 재구성, robust/moderate/weak/
    reversed 등급, 정적 사전필터에 대한 기본 의심, "이건 가설 검증용이지 데이터마이닝이 아니다")
    을 `analysis/` 전체를 읽어 추출한 그대로 명문화하고, 아직 안 풀린 문제 목록(B: 2021 성장주
    언와인드 사각지대/14~16개월 룩백 후보 미감사/칼라헤지 파라미터 민감도, C: AI-비피벗 대조군
    바스켓 없음/옵션헤지 미이식/표본기간 짧음/오늘자 신규 스캔)을 시드로 제공. **git commit/push는
    절대 하지 않는다**는 제약을 프롬프트에 명시(사용자가 직접 검토 후 커밋하길 원함).
  - `run_research_agent.sh`: `claude -p "<프롬프트>" --dangerously-skip-permissions` 헤드리스
    실행(무인 서버라 매번 승인 못 받으므로) + 실행 후 `pytest tests/ -q` 회귀 확인 +
    `notify_if_accumulated.py` 호출. "사용량 한도에 걸리면 초기화 후 이어서 계속"은 별도 재시도
    로직을 만들지 않고 Claude Code 자체 설정(`autoContinueAtUsageLimit: true`, VM의
    `/opt/quant/.claude/settings.json`에 설정)에 맡긴다 — 사용자가 원한 "최대한 소진, 끊기면
    초기화 후 이어서"를 정확히 지원하는 기존 기능을 그대로 활용(새로 발명 안 함).
  - `notify_if_accumulated.py`: git commit을 안 하므로 `analysis/` 밑에 커밋 안 된(untracked)
    새 리포트 폴더가 계속 쌓인다 — 매번 알리면 스팸이라, 마지막 알림 이후 새로 쌓인 게 3개
    이상일 때만 텔레그램으로 한 번에 알리고 기준선을 갱신(`data/cache/research_agent_notify_
    state.json`). `core.telegram_notify.send_message()` 재사용.
  - **버그 발견 및 수정**: `notify_if_accumulated.py`를 실제로 실행해보니 텔레그램 전송이
    조용히 실패했다 — `core/telegram_notify.py`가 자체적으로 `.env`를 로드하지 않고
    `core.champion_strategy`를 거쳐 간접적으로(그 모듈이 `core.fred_data`를 import하면서
    `load_dotenv()`가 부수효과로 실행되는 것에) 의존하고 있었다. 스케줄러 잡들은 항상
    champion_strategy를 먼저 import해서 우연히 동작했지만, 이 스크립트처럼 단독 실행되는
    경우엔 깨졌다. `core/telegram_notify.py` 모듈 상단에 `load_dotenv()`를 직접 추가해
    (`core/fred_data.py` 등 다른 core 모듈과 동일한 관례) 근본 수정.
  - **`deploy/quant-research-agent-{b,c}.service`/`.timer`**: 매일 한국시간 00:20에 각각
    실행하는 systemd 타이머 2개(오늘 새로 만든 `fred_indicator_prewarm_job`도 같은 00:20이지만
    서로 완전히 다른 프로세스/메커니즘(파이썬 APScheduler vs 외부 claude CLI)이라 충돌 없음).
    `TimeoutStartSec=82800`(23시간)으로 `autoContinueAtUsageLimit`가 한도 재설정을 기다리는
    긴 대기도 감당하게 함.
  - `deploy/setup_vm.sh`에 `nodejs npm` 패키지 설치 추가(Claude Code CLI가 npm 패키지로
    배포되므로 향후 신규 VM 부트스트랩에도 반영), `deploy/DEPLOYMENT_ORACLE.md`에 "10. 리서치
    에이전트 자동화" 섹션 신규 추가(CLI 설치 → `quant` 계정으로 `claude login`[대화형, 1회,
    사람이 직접] → `autoContinueAtUsageLimit` 설정 → systemd 등록 → 확인, 5단계).
- 검증: `notify_if_accumulated.py`를 실제로 더미 untracked 폴더 3개 만들어 실행 → 텔레그램
  실제 전송 성공까지 end-to-end 확인(테스트 후 더미 폴더/상태파일 정리). bash/python 문법
  검사(`bash -n`, `ast.parse`) 통과. 전체 `pytest tests/` **824개 통과**(회귀 없음 — 이번
  작업은 core/telegram_notify.py의 dotenv 로딩 한 줄 외에는 core/*.py를 건드리지 않음).
- **아직 VM에 미배포, 아직 `claude login`도 안 함** — 이건 사용자가 직접 해야 하는 절차(대화형
  OAuth 로그인이라 원격으로 대신 할 수 없음). 프롬프트 파일도 아직 한 번도 실제로 무인 실행해본
  적이 없으므로, 배포 후 처음 한동안은 로그/결과물을 직접 확인해보는 걸 권장.

**업데이트 (같은 날, 실제 로그인 진행 중 발견)**: `sudo -u quant claude login`이 문서대로 안 됐다.
1) `claude login`은 CLI 인자로 안 먹힘(그냥 첫 채팅 메시지로 들어감) — 로그인은 대화형 세션
안에서 `/login` 슬래시 명령으로 해야 함. 2) `sudo -H -u quant`로 `$HOME=/opt/quant`가 정확히
설정됨을 별도로 확인했는데도(`sh -c 'echo $HOME'`으로 검증), claude CLI 자체는 설정 파일을
`/home/ubuntu/.claude/`(원래 SSH 로그인 계정)에서 찾으려 해서 EACCES가 남 — `SUDO_USER` 등
sudo 관련 환경변수를 지워봐도 동일, 정확한 원인은 못 밝힘. `CLAUDE_CONFIG_DIR=/opt/quant/.claude`
환경변수로 명시적으로 강제 지정해서 우회함(`.claude.json`/`.credentials.json`이 정상적으로
`/opt/quant/.claude/`에 quant 소유로 생성된 것 확인). 이 문제는 로그인 셋업(사람이 sudo 셸로
들어가서 하는 것)에서만 겪는 문제이고, 실제 매일 밤 도는 systemd 서비스는 sudo 셸을 거치지
않고 systemd가 직접 `Environment="HOME=/opt/quant"`/`Environment="CLAUDE_CONFIG_DIR=/opt/
quant/.claude"`를 주입하므로(두 `.service` 파일에 반영) 이 문제가 재현되지 않는다 — 로그인은
사용자 본인 계정(Pro 구독)으로 성공, `autoContinueAtUsageLimit: true`도
`/opt/quant/.claude/settings.json`에 반영 완료. `deploy/DEPLOYMENT_ORACLE.md` 10단계의
2~3단계 절차를 실제로 성공한 순서대로 다시 씀.

### 작업 66 (2026-09-14, 같은 대화 후속): "R&D 섹터" — 리서치를 실제 스윙매매 전략으로 발전시키는 에이전트 5개 추가(D~H)

작업65(에이전트 B/C) 배포 직후 사용자가 "이제 서버와 AI 에이전트가 있으니 알고리즘 매매를
할 수 있는 단계다, 월 1회~많아야 3회 정도의 스윙매매를 지향하니 이를 위한 R&D 섹터(최소 3개
에이전트)를 B/C 리포트 기반으로 연구해 수익화하고 싶다"고 요청. 대화 도중 "더 고도의 추론이
필요한 에이전트 2개를 더 분화해달라(effort 부족하면 늘려주겠다)"와 "에이전트를 다 써, 놀고
있는 애들 만들지 말라"는 추가 요청을 받아 최종적으로 5개(D/E/F/G/H) 신설 — 기존 B/C까지 총
7개 야간 에이전트 체제로 확장.

- **역할 분리(각자 다른 걸 함, 중복 없음)**:
  - **D(전략 구성가)**: B/C의 robust/moderate 등급 결과를 종합해 "월 1~3회 매매" 제약에 맞는
    구체적 후보 전략을 정의. `core/champion_strategy.py`의 코어(월간)+새틀라이트(반기)
    구조가 이미 이 빈도와 가깝다는 점을 프롬프트에 명시해, 완전히 새 전략 발명보다 기존 구조
    다듬기를 우선 검토하도록 유도. 월평균 매매횟수를 반드시 실측·보고하게 함.
  - **E(실행 준비가)**: D의 후보를 "오늘/이번 달 실제로 뭘 사고팔지"로 번역. 브로커 API 연동/
    자동주문은 명시적으로 범위 밖(사람이 읽고 직접 실행하는 제안서까지만).
  - **F(비용/세금 감사관)**: 지금까지 이 프로젝트의 모든 백테스트가 쓴 왕복 0.1% 비용 가정을
    처음으로 현실화 감사 — 거래비용 상향 시나리오, 원/달러 환전 스프레드, **한국 거주자의
    해외주식 양도소득세**(세율/공제 기준은 프롬프트에 하드코딩하지 않고 매번 웹검색으로 최신
    확인하도록 지시 — 세법 변경 리스크 회피), 저빈도 매매의 표본 부족이 확신도에 미치는 영향까지
    감사.
  - **G(방법론 메타 감사관, effort=high)**: 다른 에이전트들과 달리 개별 전략이 아니라 **이
    연구 프로그램 전체의 통계적 건전성**을 감사 — 지금까지 검정된 가설 수가 60개 작업/30개+
    리서치 라운드에 달해 다중비교(multiple comparisons) 문제가 누적됐을 가능성이 있는데 이
    프로그램이 지금까지 한 번도 이를 정량적으로 보정한 적이 없었다는 공백을 메움
    (Bonferroni/FDR류 보정 후에도 기존 robust 등급이 유지되는지 재계산).
  - **H(학술 문헌/외부 벤치마크 조사관, effort=high)**: 유일하게 저장소 밖 시각을 들여옴 —
    이 저장소의 핵심 가정(모멘텀 랭킹 방식, 정적필터 무효론 등) 하나를 매일 골라 실제 학술
    논문/실무 문헌을 웹검색으로 찾아 대조. "우리끼리 돌려막기" 위험을 줄이는 역할.
  - "더 고도의 추론" 요청에 맞춰 G/H는 `run_research_agent.sh`에 `--effort high` 인자를 추가
    (새로 지원하는 선택적 3번째 인자) — 계정의 `maxEffortLevel` 정책으로 클램프되면 로그에서
    확인해 사용자에게 상향을 요청하도록 문서화.
- **"놀고 있는 에이전트 없게" 요구 반영**: 처음 설계는 E/F/H가 "D의 새 후보가 없으면 대기만
  하고 종료"하도록 돼 있었는데(D가 밤새 안 끝나면 뒤 에이전트들이 허탕칠 위험), 사용자 지적을
  반영해 **D의 새 후보가 없어도 절대 대기하지 않고, 이미 라이브로 도는 `core/champion_strategy.py`
  기본 설정을 대체 대상으로 삼아 매일 밤 실질적인 결과물을 내도록** 세 프롬프트 모두 수정. D/B/C/G는
  원래도 항상 다룰 거리가 있어(누적 corpus 기반) 이 문제가 없었음.
- **스케줄**: B/C 00:20(기존), D 00:25, E 01:00, F 01:30, G 02:00, H 02:30(전부 Asia/Seoul) —
  기존 잡들과 안 겹치는 새 슬롯. `analysis/LATEST_STRATEGY_CANDIDATE.md`를 D가 매일 갱신하는
  "현재 후보" 포인터 파일로 신설(다른 날짜 폴더들과 달리 유일하게 매번 덮어씀) — E/F/G/H가
  여기서 오늘 다룰 대상을 찾음.
- 전부 B/C와 동일한 안전 제약 유지: git commit/push 금지, `core/champion_strategy.py` 등
  실제 라이브 엔진의 기본 동작을 연구 결과만으로 무단 변경 금지(파라미터 opt-in 추가는 허용).
- `deploy/DEPLOYMENT_ORACLE.md` 10단계를 7개 에이전트 전체 표+등록 절차로 갱신,
  `run_research_agent.sh`에 선택적 effort 인자 추가.
- 검증: bash 문법 검사(`bash -n`) 통과, 전체 `pytest tests/` **824개 통과**(core/*.py 변경
  없음, 회귀 없음). 아직 VM에 미배포 — 로컬 커밋만 완료, 사용자 확인 후 push+VM 등록 예정.

### 작업 67 (2026-09-14, 같은 대화 후속): 정정 — R&D 에이전트는 VM이 아니라 Codespace에서 실행

작업66 배포 직후 사용자가 "이건 애초에 내 Codespace에서 돌아야 하는 거였다 — 내 서버(VM)는
Codespace에서 나온 결론을 서비스로 배포하는 역할일 뿐"이라고 아키텍처를 정정. 실제로 VM에
systemd 타이머로 무인 야간 실행되도록 배포한 게 이 의도와 정반대였음을 인정하고 되돌렸다.

- **VM에서 완전히 제거**: `quant-research-agent-{b..h}.timer/.service` 전부 stop/disable/삭제
  안내(사용자가 직접 실행).
- **저장소 정리**: `deploy/research_agents/`(VM 배포 전용 디렉터리)를 폐기 —
  `run_research_agent.sh`, `notify_if_accumulated.py`, `quant-research-agent-*.{service,timer}`
  15개 파일 전부 삭제. 페르소나 프롬프트 7개(`agent_{b..h}_*.md`)만 저장소 최상위
  `research_agents/`로 이동해 보존(내용 자체는 여전히 유효 — B/C가 이미 순열검정+블록부트스트랩
  이중검증 등 이 프로젝트 방법론을 정확히 따라 실제로 유의미한 결과 하나(비AI 대조군 바스켓
  변동성모멘텀 — 순열검정 비유의 p≈0.47~0.75로 정직하게 미결론 보고)를 냈던 걸 확인했으므로).
  각 프롬프트의 "무인 서버에서 매일 밤 실행됩니다"/`/opt/quant` 절대경로 언급을 "Claude Code
  세션(Codespace) 안에서 서브에이전트로, 사용자 요청 시 실행"으로 수정.
- `deploy/setup_vm.sh`의 nodejs/npm 설치 줄(리서치 에이전트용으로 추가했던 것) 원복 —
  더 이상 이 VM에 Node/Claude Code CLI가 필요 없음.
- `deploy/DEPLOYMENT_ORACLE.md` 10단계를 "정정" 섹션으로 교체: VM은 배포 전용, 리서치는
  Codespace에서 Claude Code가 서브에이전트로 직접 실행. **알아둘 제약**도 명시: GitHub
  Codespace는 idle 타임아웃으로 자동 정지되므로 "매일 밤 자동 실행"은 사용자가 Codespace를
  열어야만 가능 — 진짜 무인 야간 자동 실행이 필요해지면 이 저장소가 이미 쓰는
  `.github/workflows/nightly_tuning.yml`과 같은 GitHub Actions 스케줄 워크플로가 다음 후보지
  (VM/Codespace 둘 다 안 켜져 있어도 됨, 다만 Claude Pro 로그인 자격증명을 GitHub Secrets로
  주입하는 추가 작업 필요 — 아직 미착수).
- 검증: 전체 `pytest tests/` **824개 통과**(core/*.py 무변경). `bash -n deploy/setup_vm.sh`
  통과.
- 별개로, 사용자가 병행 진행 중인 Codex 기반 텔레그램 자동화(`deploy/codex_telegram/`, 이
  세션이 만든 게 아니라 사용자의 별도 Codex 세션이 같은 Codespace 파일시스템에 직접 만든 것 —
  건드리지 않고 그대로 둠)의 `config.example.json`을 보면 `/opt/quant/...` VM 경로를 전제로
  짜여 있어, 이번 정정과 같은 긴장(리서치/명령수신 리스너를 VM에 둘지 Codespace로 옮길지)이
  아직 그쪽에도 남아있음을 사용자에게 알림 — 이 저장소 커밋 범위 밖이라 손대지 않음.

### 작업 68 (2026-09-14, 별도 서브에이전트 — 리서치 에이전트 B 자율 라운드): 칼라 옵션 헤지 파라미터 민감도 감사 — "특정 숫자"는 근거부족

`research_agents/agent_b_market_portfolio.md`(리서치 에이전트 B) 페르소나를 그대로 실행 — 문서가
명시한 미해결 과제 3개(2021년 새틀라이트 국지적 위기, 룩백×리밸런싱 미세조정 후보, 칼라 헤지
파라미터 민감도) 중 세 번째를 골랐다. 작업57이 같은 날 앞서 합성 칼라(ATM 풋 매수+5% OTM 콜 매도,
21거래일 월물 롤)를 core/champion_strategy.py로 라이브화했는데, 이 정확한 숫자 조합이 이
프로그램의 표준 감사(스윕+플라시보+블록부트스트랩+기저확률 기댓값)를 한 번도 거친 적이 없다는
공백을 발견해 닫았다.

- **재사용 인프라**: 새 방법론을 만들지 않고 작업48(`h_options_hedge.py`)의 BS가격결정/에피소드
  로딩과 작업49(`h_bootstrap_audit.py`)의 순환 이동블록부트스트랩·디리클레 결합전파를 그대로
  가져다 썼다. 6개 창(전체 2019-2026/2008 GFC/COVID/2022/2018/2015-16) SPY·VIX·FEDFUNDS는
  에피소드당 1회만 fetch하고 파라미터 그리드 전체는 순수 Black-Scholes 재계산만 반복해 네트워크
  호출 없이 24조합+플라시보 200개+대표 파라미터 5개 부트스트랩을 전부 처리(총 실행 124초).
- **H-A 완만성 그리드(put_moneyness×call_moneyness×tenor_days 24조합)**: EV Sharpe(base 시나리오,
  점추정) 범위 −0.0875~−0.0329, 표준편차가 범위 폭의 약 20%로 완만한 고원 — 라이브 기본값
  (1.00/1.05/21일)은 24개 중 9위(중위권)라 과최적화 스파이크는 아님을 확인. 다만 tenor=42일
  (2개월물)이 상위 5개 중 3개를 차지하는 패턴을 관찰.
- **H-B 플라시보(무작위 파라미터 200개 대조군)**: put~U(0.85,1.00)/call~U(1.02,1.20)/tenor~정수
  균등(15,70)에서 200개를 무작위로 뽑아 EV Sharpe를 계산 — 라이브 기본값은 겨우 58.5번째 백분위
  (작업30 H4 퀄리티 필터가 "무작위와 구별 안 됨"으로 하향 정정됐을 때와 정확히 같은 숫자, 순수
  우연의 일치). 95% 유의 문턱에 크게 못 미쳐 **"ATM풋+5%OTM콜+21일이 정밀 조정된 최적값"이라는
  근거는 없다**고 결론(근거부족/UNSUPPORTED) — 실제로는 옵션 월물 주기에 맞춘 합리적 공학 기본값일
  뿐. 이 판정은 "칼라 메커니즘 자체가 무헤지보다 나은가"라는 작업48/49의 별개 질문(기존 "약함"
  판정)에는 영향을 주지 않음을 명시.
- **H-C/H-D 블록부트스트랩+결합전파(대표 파라미터 5개: 라이브 기본값/저렴한 5%OTM풋/넓은
  10%OTM콜/분기물63일/2개월물42일)**: H33/H_bootstrap과 동일 방법론(L=10/20/40, 창×구성당
  2,000회)+H33b/H_combined 결합전파(디리클레 K=30, base/calm_heavy/crisis_heavy 3개 시나리오,
  10,000draw)를 5개 구성 전부에 적용. "칼라가 무헤지보다 낫다"는 방향성은 5개 변형 전부에서
  재확인(승률 42~64%, 라이브 기본값은 55~60%로 작업49의 55%대와 정확히 일치해 재현성 확인)됐지만
  CI90은 여전히 5개 구성 전부에서 0을 크게 가로질러 약함 그대로. **2개월물(42일) 롤이 5개 구성
  중 모든 시나리오에서 승률 최고**(기본 58.8%/평시가중 50.7%/위기가중 64.1%)라는 단서가 그리드의
  관찰을 부트스트랩 이후에도 재확인시켰지만, 90% 문턱에는 못 미쳐 "다음 라운드 후보"로만 남김.
- **최종 판정 3분리**: ① 칼라가 무헤지보다 기댓값에서 낫다(기존 판정, 약함) — 안 바뀜. ②
  라이브에 쓰인 정확한 숫자가 다른 합리적 선택보다 통계적으로 우월하다(이번 라운드 새 질문) —
  근거부족, 코드/문서에서 "정밀 검증된 값"처럼 포장하면 안 됨. ③ 42일 롤로 바꾸는 안(새 단서) —
  근거부족이지만 다음 라운드에서 볼 가치 있음. `core/champion_strategy.py`의
  `COLLAR_PUT_MONEYNESS`/`COLLAR_CALL_MONEYNESS`/`COLLAR_TENOR_DAYS` 기본값을 바꿀 근거는
  발견하지 못해 **core/app 변경 없음**(순수 리서치 라운드).
- 산출물: `analysis/2026-09-14_collar_hedge_parameter_sensitivity/`(`h_collar_sensitivity.py`+
  `report_data.json`+`build_report.py`+`final_report.html`), 사본을
  `docs/reports/collar_hedge_parameter_sensitivity_research.html`로 배치,
  `docs/reports/README.md`에 트랙D 이후 독립 항목으로 추가(요약+상세 블록 둘 다). `core/`·`app/`는
  건드리지 않았으므로 이번 라운드가 만든 회귀는 없음 — `pytest tests/` 전체 실행 결과 821 통과·
  3 실패이나, 3개 실패 전부 이번 변경과 무관함을 개별 확인(`test_champion_strategy.py::
  test_build_collar_overlay_returns_pays_off_on_crash_at_expiry`는 yfinance `YFRateLimitError`
  네트워크 일시 오류, `test_strategy_library_archive.py`의 2건은 `patched_session` 픽스처가
  `no such table: strategies`를 내는 기존 테스트 격리 이슈로 `core/strategy_library.py`를 전혀
  건드리지 않은 이번 라운드와 무관 — 단독 재실행해도 동일하게 재현돼 세션 내 일시적 현상이
  아님을 확인했으나 원인 조사는 이번 작업 범위 밖이라 남겨둠).
- git commit/push는 하지 않음(페르소나 지시대로 워킹트리에만 결과물을 남김 — 사용자가 직접 검토
  후 커밋).

### 작업 69 (2026-09-14, 같은 대화 후속 — 별도 서브에이전트): 리서치 에이전트 C(개별주 발굴) 첫 실행 —
IREN 바스켓에 SPY 콜라 옵션 헤지 이식, 0/3 기각 + 구조적 원인 규명

작업67에서 저장소 최상위로 옮긴 `research_agents/agent_c_tenbagger.md`(개별주/텐베거 발굴
전담 리서치 에이전트 페르소나)를 실제로 처음 실행. 페르소나가 나열한 미해결 문제 4개 중 "옵션
헤지 이식"을 선택 — `iren_beta_alpha_hedging_research`(작업28)가 H5(옵션 헤지)를 "이 저장소에
옵션 백테스트 인프라가 없어" 정성적 논의로만 남겼는데, 그 뒤 트랙D(작업48/49)가 챔피언 전략의
새틀라이트 슬리브용으로 합성 블랙숄즈 칼라(`core.champion_strategy.build_collar_overlay_returns`)
를 실제로 라이브 구현해뒀으므로 그 갭을 처음 실측으로 메울 수 있게 됐다고 판단.

- **방법론**: 새 옵션가격 로직을 만들지 않고 세 기존 엔진만 이어붙였다 — (1)
  `analysis/2026-08-16_iren_volatile_momentum_stocks`의 피벗 바스켓(IREN·CIFR·CLSK·WULF·HUT·
  BTDR) 정적 매수후보유 + 20일 돈치안/15%트레일링스탑 챔피언, (2) 트랙D의 SPY 종가+VIX
  대리변동성+FRED금리 합성 칼라(ATM풋매수+5%OTM콜매도, 매월 첫거래일 롤), (3)
  `2026-08-23_block_bootstrap_sample_error_quantification`의 원형 이동블록부트스트랩(트랙C가
  이미 작업48에서 자기 자신에게 적용한 감사와 동일 방법). 공통구간을 2026-09-14까지 갱신해
  원본(2026-08-18 기준)보다 약 1개월 더 최신 데이터로 재현.
- **H1(무헤지+콜라1x)·H2(추세추종챔피언+콜라1x) 둘 다 기각**: 매수후보유·추세추종 × 바스켓·
  IREN단일 4개 구성 전부 샤프 악화(−0.05~−0.09). 이미 15%트레일링스탑으로 하방을 방어 중인
  챔피언(H2)은 MDD까지 더 나빠져(바스켓 −71.0%→−72.4%) 순수 중복비용임을 확인 — 방어가 전혀
  없던 순수 매수후보유(H1)만 MDD가 소폭 개선(−65.59%→−64.43%)됐지만 그 대가로 샤프는 항상
  깎였다.
- **H3(베타 스케일링 노셔널 스윕) 기각**: 이 바스켓의 작업28 실측 시장베타(1.5~3배)로 콜라
  노셔널을 스케일링하면 1배보다 나을 거라는 가설 — 0~4배 8단계 스윕(+실측 정적베타) 결과 4개
  구성 전부 샤프 기준 0배(무헤지)가 항상 1등, 노셔널을 올릴수록 단조 감소해 내부 정점 자체가
  없음. MDD만 2배 부근에서 비단조적으로 소폭 개선(바스켓매수후보유 −65.59%→−63.79%)되나 그
  대가(CAGR 48.05%→29.27%)가 훨씬 크다.
- **H4(크래시 정합성 진단)**: H1~H3가 실패하는 이유를 구조적으로 확인 — 최악 낙폭이 같은 구간
  SPY 수익률과 사실상 무관한 경우가 대부분(챔피언 기준 5개 중 4개, 매수후보유 기준 5개 중 3개 —
  챔피언 최악낙폭 −71.0% 구간에 SPY는 −1.56%)이라 SPY 옵션이 트리거될 기회조차 없었다. 콜라
  순기여가 가장 컸던 구간(2022년 하반기, +8.33%p)은 공교롭게도 SPY 자체도 진짜 약세장
  (−12.34%)이던 경우였지만, 두 번째로 컸던 구간(+5.36%p)은 SPY가 겨우 −3.96%만 움직였는데도
  나와 "SPY가 빠질수록 콜라가 번다"는 깔끔한 선형관계는 아니었고, 부호와 무관하게 어느 구간도
  기여분이 한 자릿수%p를 못 넘었다 — "이 바스켓의 크래시가 시장 전체와 크게 동행할 때만 시장
  전체를 헤지하는 도구가 조금이라도 힘을 쓰고, 그마저도 낙폭을 메우기엔 턱없이 작다"는 관계를
  처음 직접 확인했다.
- **H5(쌍대 블록부트스트랩 감사)**: 무헤지 vs 콜라1x를 같은 날짜 인덱스로 동시 재표본추출한
  결과 콜라 승률 6.9~8.4%(무헤지 승률 92~93%)로 "무헤지가 이긴다"는 방향이 표본오차를 감안해도
  강건함을 재확인(다만 90%CI 상단이 근소하게 0을 넘어 "절대적 확신"까지는 과장이라고 명시).
- **종합**: 0/3(가부판정 대상 H1·H2·H3 전부 기각) + 진단 1개(H4) + 감사 1개(H5) — 승리로
  포장할 구석이 없는 정직한 전면 기각. 작업28 H1(물리적 베타헤지 기각, "베타를 지우면 알파도
  지워진다")과 메커니즘이 다르다는 것도 짚었다 — 이번엔 "볼록한 보험이라도 잘못된 기초자산에
  걸면 지급조건 자체가 안 맞는다"는 정합성(basis) 문제. 이 바스켓을 옵션으로 방어하려면 SPY가
  아니라 바스켓 자체(또는 BTC) 기초 파생상품이 필요하지만 그런 유동적 시장이 이 종목군엔
  사실상 없다는 한계까지 리포트에 명시. `core/*.py`는 건드리지 않아 pytest는 실행하지 않음
  (에이전트 지시대로 core 무변경 시 생략 가능).
- 산출물: `analysis/2026-09-14_iren_basket_collar_hedge_transplant/`(`hedge_common.py`/
  `h1_h2_collar_transplant.py`/`h3_beta_scaled_sizing_sweep.py`/`h4_crash_alignment_check.py`/
  `h5_bootstrap_audit.py`/`build_report_data.py`/`build_report.py`/`report_data.json`/
  `final_report.html`), 사본을 `docs/reports/iren_basket_collar_hedge_transplant_research.html`로
  복사, `docs/reports/README.md` 트랙 C에 No.5로 추가. 격리된 워크트리에서 진행 — 커밋/푸시는
  하지 않고 워킹트리에 그대로 남겨둠(사용자가 검토 후 채택 여부 결정).

### 작업 70 (2026-09-14, 별도 서브에이전트): R&D 에이전트 D(전략 구성가) 라운드 1 — "월 1~3회
매매" 제약을 처음으로 실측

작업66이 신설한 R&D 에이전트 D(`research_agents/agent_d_strategy_constructor.md`)의 첫 실행.
`analysis/2026-09-05_research_program_synthesis/report_data.json`의 confidence_table(로버스트:
코어 17자산 유니버스, 보통: 12개월 모멘텀 랭킹·새틀라이트 정적보유, 약함: 리밸런싱주기·이진
시장필터·새틀라이트 포함여부)을 검토한 결과, 새 전략을 발명하기보다 이미 라이브인
`core/champion_strategy.py`의 두 기본 구성을 "월 1~3회 매매" 제약 관점에서 직접 실측하는 게
최선이라 판단(새틀라이트 반기 리밸런싱이 이미 이 빈도에 가깝다는 페르소나 지침대로).

- **후보 1(코어 단독)** vs **후보 2(코어+15% 반기 새틀라이트, 현재 라이브 기본값과 동일)**를
  `run_core_backtest()`/`run_champion_backtest()` 기본값 그대로 2019-08-12~2026-09-11 구간에
  백테스트. 이 저장소에서 처음으로 "회전율"이 아니라 실제 주문 발생 건수 기준 월평균
  매매횟수를 실측 — **후보1 2.22회/월, 후보2 2.87회/월로 둘 다 제약(1~3회) 충족**(CAGR
  13.57%/16.59%, MDD -17.74%/-18.45%, 샤프 1.06/1.15, 칼마 0.76/0.90; 참고 SPY 매수보유 CAGR
  14.64%, MDD -34.10%, 샤프 0.79).
- **순열검정**: 작업21(No.06)이 멀티에셋 로테이션에 썼던 방법론(무작위 양(+)모멘텀 선택 대비)을
  이번 후보의 정확한 구간·설정으로 재구현(원본 스크립트는 관례대로 삭제돼 재구현 필요) —
  실제 샤프 1.06이 무작위 200회(평균 0.605±0.164) 대비 99.0백분위, p=0.0149로 통계적 유의성
  재확인(moderate 등급과 일관).
- **블록부트스트랩**: 작업44/45(H33/H34)와 동일 방법론(순환 이동블록, L=10/20/40일, 1,500회)을
  두 후보+SPY 각각의 일별수익률에 적용, L=20 90% CI가 세 구성 모두 크게 겹침을 확인. 후보2가
  후보1을 이기는 페어 비교 승률은 58.1%로 confidence_table의 "새틀라이트 포함 여부: weak" 등급과
  일관됨을 재확인.
- `analysis/2026-09-14_strategy_candidate_1/`(build_candidates.py + report_data.json +
  build_report.py → final_report.html) 신설, `analysis/LATEST_STRATEGY_CANDIDATE.md`를 이번
  라운드 결론(후보2를 최선으로 유지하되 우위는 약함 등급, 안전마진 필요시 후보1도 동등한 대안)으로
  갱신 — 다른 R&D 에이전트(E/F/G/H)가 각자 별도 worktree에서 참고할 포인터 파일.
  `docs/reports/README.md`에 사본 링크 추가.
- `core/*.py`는 수정하지 않음(기존 함수를 파라미터 그대로 재사용) — pytest 재실행 불필요.
- 위성 백테스트 point-in-time 유니버스 스캔 중 데이터 제공자(yfinance) 레이트리밋으로 총
  실행시간이 약 30분(1,816초) 소요됨 — 알려진 인프라 제약, 결과 자체(코드가 실패 종목을
  건너뛰는 설계)에는 영향 없음.
- git commit/push 없음 — 지시대로 작업트리에 변경사항만 남김.

### 작업 71 (2026-09-14, 별도 서브에이전트 — 격리 worktree): R&D 에이전트 E(실행 준비가) 첫 실행 —
오늘 기준 챔피언 전략 매수/매도 브리핑

작업66/67이 신설한 R&D 에이전트 7개 중 E(실행 준비가) 첫 실행. 에이전트 D가 아직 실행되지
않아 `analysis/LATEST_STRATEGY_CANDIDATE.md`가 없었고, 이는 예정된 상황(D/E는 서로 다른
worktree에서 병렬로 돌 수 있어 항상 D 최신본을 볼 수 있는 게 아님) — 페르소나에 명시된 폴백 규칙대로
`core/champion_strategy.py`의 현재 기본 설정(코어 85%+새틀라이트 15%, final_config 그대로)을
"오늘의 후보"로 삼아 진행했다.

- **산출물**: `analysis/2026-09-14_execution_readiness/EXECUTION_BRIEF.md`(사람이 읽는 매매
  지시서) + `report_data.json`(원자료) + `compute_execution_brief.py`(재현 스크립트, 실행 시
  라이브 시장데이터로 값 갱신). 새 계산 로직 없음 — `compute_core_recommendation`/
  `compute_satellite_recommendation_point_in_time`/`compute_satellite_recommendation`/
  `compute_rebalance_diff`/`core.portfolio.get_portfolio_pnl`/`get_cash_balance`를 그대로
  호출만 함.
- **오늘(2026-09-14)의 목표 배분**(포트폴리오 대비 %, 시장필터 미발동이라 현금 0%): 코어
  85%를 DBC/XLE/XLK/XLV에 21.25%씩(12개월 모멘텀 상위4, 절대모멘텀 전부 통과), 새틀라이트 15%를
  CAT/GEV/JNJ에 5%씩(2026-07-01 반기 리밸런싱 선정분, 이후 각각 -17.43%/-15.61%/+4.57% — 이
  하락은 설계상 정적보유 원칙 때문이지 버그가 아님, final_config가 명시적으로 채택한 부분).
- **중요 발견(구현 격차 #1, 중요도 중)**: `app/pages/11_챔피언_전략.py`의 "내 포트폴리오와
  비교" 리밸런싱 diff 섹션(L555)이 실제로 넘기는 `satellite_result`는 "🔍 빠른 근사 스캔"
  탭(`compute_satellite_recommendation`, S&P500 전체 스캔+3개월 모멘텀 상위5)에서 채워지는
  값이지, 백테스트가 실제로 검증한 "✅ 반기 point-in-time" 탭(`compute_satellite_recommendation_
  point_in_time`)의 결과가 아니다. 오늘 두 방법을 실측 비교한 결과 완전히 다른 종목
  (CAT/GEV/JNJ vs CRWD/TRV/BBY/META/T, 겹침 0개)을 추천해 이 격차가 실제로 사용자 행동에 영향을
  줄 수 있음을 확인했다. 수정 스펙(1줄 변수 교체, `core/champion_strategy.py`는 손댈 필요 없음)을
  EXECUTION_BRIEF.md 5절에 남겼고, **직접 고치지 않았다**(코드 수정은 대화형 세션에서 사람과 함께
  하는 이 프로젝트 관례를 따름).
- **구현 격차 #2(운영상, 중요도 낮음)**: 이 실행은 격리 git worktree라 로컬 `data/quant.db`가
  0바이트(테이블 없음) — `core.portfolio.get_portfolio_pnl()`/`get_cash_balance()`가 예상대로
  실패해(OperationalError) 실제 보유 대비 매수/매도 수량(diff)까지는 계산하지 못했고, 목표비중
  표까지만 산출했다(페르소나 지침의 "모르면 %로만" 원칙 그대로 따름). 메인 체크아웃(실제 데이터가
  있는 곳)에서 같은 스크립트/페이지를 돌리면 정상적으로 실제 diff가 나온다 — 매일 밤 자동으로
  진짜 diff까지 원한다면 이 에이전트를 어디서 돌릴지(격리 worktree vs 메인 체크아웃) 별도 논의
  필요.
- git commit/push 없음, 실제 매매/브로커 연동 없음(제안서까지만) — 페르소나 지침 그대로.
  `core/*.py`/`app/*.py` 무변경이라 회귀 테스트는 별도로 돌리지 않음(정보 산출 스크립트만 추가).

### 작업 72 (2026-09-14, 별도 서브에이전트 — 리서치 에이전트 F 첫 실행): 비용/세금 감사관 —
왕복 0.1% 거래비용 가정을 이 저장소가 지금까지 한 번도 감사하지 않았다는 공백을 메움

작업66이 신설한 R&D 섹터 에이전트 F(`research_agents/agent_f_cost_tax_auditor.md`)의 첫 실제
실행. 실행 시점에 에이전트 D의 새 후보(`analysis/LATEST_STRATEGY_CANDIDATE.md`)가 아직 없어서,
페르소나 프롬프트의 명시적 폴백 지시("D의 새 후보가 없어도 절대 대기하지 않고, 라이브 기본설정을
대체 감사 대상으로 삼는다")에 따라 지금 실제로 도는 `core/champion_strategy.py` 기본설정(코어
17자산 모멘텀 로테이션 + 새틀라이트 15% 반기 추세추종)을 감사했다.

- **거래비용 현실화**: 이 저장소 모든 백테스트가 지금까지 써온 왕복 0.1%(`BACKTEST_COST_BPS_
  PER_SIDE=5.0`) 가정을 웹검색으로 확인한 한국 증권사 실제 미국주식 수수료(키움/한국투자증권
  온라인 표준 0.25%/편도, 무프로모션)로 재계산하면 이미 왕복 0.5%로 5배가 된다. 왕복 0.1%/0.3%/
  0.5%/0.8% 4개 시나리오로 코어·새틀라이트를 재백테스트(코어는 2019-08~2026-09 전체 구간)한
  결과 코어 CAGR 13.60%→12.33%(왕복0.5%), Sharpe 1.06→0.97 — 방향은 유지되지만 드래그는 실재.
  실측 연평균 매매횟수(편도): 코어 20.9회/년, 새틀라이트(최근 창) 10.1회/년.
- **핵심 신규 발견 — 순열검정 실패**: `core.backtest_engine._shuffle_daily_bars`를 그대로 재사용한
  순열검정(N=200, 이 저장소의 공식 방법론)에서 코어의 p-value가 현재비용 0.2388, 보수적비용(왕복
  0.5%) 0.1741로 나와 이 프로젝트가 다른 채택 판정에 요구해온 기준(p<0.05)을 명확히 통과하지
  못한다 — "날짜 순서를 무작위로 섞은 가짜 시계열에도 이 정도 Sharpe가 우연히 나올 확률이
  17~24%"라는 뜻. 블록부트스트랩(L=10/20/40, 창당 2,000회) 신뢰구간 자체는 코어 전 시나리오에서
  0 위쪽에 안정적이지만(서로 다른 귀무가설이라 모순은 아님), confidence 등급은 더 엄격한 검정
  결과를 따라야 한다는 이 프로젝트의 기존 원칙에 따라 하향 근거로 삼았다. 지금 라이브로 도는
  정확히 이 17자산·이 파라미터 조합에 대한 첫 순열검정이라는 점에서 새로운 정보다.
- **한국 거주자 해외주식 양도소득세**: 세율/공제 기준은 프롬프트에 하드코딩하지 않고 이번 실행에서
  실제 웹검색으로 확인(출처: 국세청 nts.go.kr 해외주식 양도소득세 안내, 미래에셋증권·유안타증권
  고객안내, calculatorhost.com "해외주식 양도소득세 2026") — **세율 22%(양도소득세20%+지방소득세
  2%), 기본공제 연 250만원**(과세연도 내 손익통산, 이월공제 없음). 코어의 실현거래(72건, 2019~
  2026, 왕복0.5%비용 반영 후 순손익)를 계좌 규모별로 시뮬레이션한 실효세율(세전 실현이익 대비):
  3천만원 계좌 13.3%, 1억원 계좌 20.4%, 3억원 계좌 22.5%(고정 250만원 공제의 상대효과가 계좌
  규모에 반비례 — 대형 계좌일수록 공제가 무의미해짐).
- **원/달러 환전 비용**: `core.fred_data`의 DEXKOUS 캐시(최근 60일 일변동성 약 0.60%, 방향성
  리스크일 뿐 스프레드는 아님)와 웹검색(증권사 환전 스프레드 기준환율 대비 약 1% 표준, 온라인
  우대 최대 90% 적용 시 약 0.1%)을 종합. **구조적으로 중요한 발견**: 코어/새틀라이트 리밸런싱은
  이미 보유 중인 USD 자산 간 교체라 통합증거금(USD 결제) 계좌를 쓰면 매 리밸런싱마다 환전이
  필요 없다 — 환전은 최초 입금/최종 출금 시점의 일회성 비용(왕복 약 0.2%~2%)이라 5~10년 보유
  기준 연환산 0.02~0.4%p 수준으로, 코어의 잦은 리밸런싱이 만드는 수수료 drag보다 작다.
- **저빈도 매매의 표본 크기**: 코어의 실제 "구성변경" 리밸런싱은 7.08년간 63회, 진입/청산 이벤트는
  148건뿐 — 순열검정/부트스트랩의 반복횟수(200회/2,000회)가 크더라도 이는 "일별수익률 재표본"
  횟수일 뿐 실제 독립적 리밸런싱 의사결정 표본 수와는 다른 질문이라는 점을 명시적으로 지적.
- **최종 판정**: confidence를 **약함(WEAK)**으로 하향 — "방향은 맞을 수 있지만, 비용과 세금을
  다 반영한 후에도 통계적으로 확신하기엔 이르다"가 정직한 결론. 부정적 결과를 완화하지 않고 그대로
  보고(페르소나 프롬프트의 명시적 요구사항).
- **계산비용 한계**: 새틀라이트의 point-in-time 반기 재구성이 yfinance rate-limit(오래전 상장폐지/
  합병 종목 반복 조회)에 걸려 완주까지 비현실적으로 오래 걸려(두 차례 시도, 각 10분+ 소요 후 중단),
  최근 반기 4회(~1.7년 창)·pool_n=15(라이브 기본값 40 대신)로 축소 재구성했다 — 전체기간 재검증은
  다음 라운드 과제로 남김.
- 산출물: `analysis/2026-09-14_cost_tax_audit/`(step1_cost_scenarios.py/step2_permutation_
  bootstrap.py/step3_tax_simulation.py, report_data.json, final_report.html, build_report.py),
  `analysis/LATEST_STRATEGY_CANDIDATE.md`에 "비용/세금 감사 결과" 섹션 추가, `docs/reports/
  cost_tax_audit_research.html` 사본. `core/`, `app/`는 수정하지 않음. git commit/push 없음
  (에이전트 페르소나 프롬프트가 명시적으로 금지).

### 작업 73 (2026-09-14, 같은 대화 후속): R&D 에이전트 G(방법론 메타 감사관) 첫 실행 — 다중비교 보정 메타 감사

작업66/67에서 신설된 R&D 에이전트 D~H 중 아직 아무도 실행된 적 없는 상태에서, 사용자가 G(방법론
메타 감사관, effort=high)를 먼저 실행 — 개별 전략이 아니라 **이 연구 프로그램 전체(67개 작업,
30개 이상 리서치 라운드)의 통계적 건전성**, 특히 지금까지 한 번도 계산된 적 없는 다중비교
(multiple comparisons) 보정을 실제 숫자로 계산하도록 지시. 격리된 워크트리에서 실행, git
commit/push는 하지 않음(에이전트 설계상 항상 금지).

- **검정 총 횟수 실제 집계(추정, 하한치)**: work item이 아니라 실제 검정된 가설/변형 단위로
  PROGRESS.md 작업19~49를 직접 읽고 손으로 집계(`count_tests.py`에 작업번호 인용 주석과 함께
  코드로 남김) — 챔피언 전략 계보(트랙B+C+D+사후 독립라운드)만 **헤드라인 80개**(트랙B 26·
  트랙C 14·트랙D 35·사후 5). `analysis/*/report_data.json` 29개 전수 스캔으로는 granular(파라미터/
  위기구간 조합) 비교가 **1,000개 이상**(서술적 win_rate 리프 932 + MC/부트스트랩 비교 arm 78).
  별도 계열인 macro_event_study(55개 이상의 독립 이벤트 스터디)와 `core/strategy_tuning.py`의
  야간/온디맨드 종목별 순열검정(`_compute_tuning_significance`, 정확한 횟수는 실행 로그 부재로
  집계 불가, 100종목×여러 스타일그룹×반복실행 규모로 최소 수백 회 추정)은 챔피언 계보 밖이라
  주 집계에서 제외하고 별도로 명시.
- **Bonferroni/BH-FDR 실제 계산**: `research_program_synthesis`의 confidence_table(12)+
  track_c_table(5)=17개 결론 중 정량적 유의성 지표(p-value 또는 부트스트랩/몬테카를로 승률을
  1-win_rate로 환산)가 있는 12개에 적용. **Bonferroni**(α=0.05)는 N=9(가장 관대: 모멘텀랭킹
  주장 하나의 파라미터 탐색 라운드 수)에서만 12개 중 1개(IREN 단일종목 추세추종, p=0.005) 생존,
  N=25/80/1022에서는 **생존자 0개**. **BH-FDR**(q=0.05)은 이 12개짜리 "가장 너그러운" 부분집합만
  놓고 계산해도 가장 작은 p(0.005)조차 순위1 임계값(0.00417)을 못 넘어 **생존자 0개**. 형식적
  p-value가 아예 없는 나머지 3개 결론(코어 자산군[robust], 새틀라이트 청산메커니즘[moderate],
  PER/PBR프레임[moderate])은 보정 계산 대상이 아니라는 점 자체를 별도로 지적(정량 검정을 거친 적이
  없다는 뜻).
- **등급 일관성 감사**: 유일하게 코드로 존재하는 수치 규칙(`win_rate>=0.90→robust,
  >=0.70→moderate, >=0.50→weak, <0.50→reversed`, 작업44-47에만 적용)을 발견. **이중 잣대 확인**:
  형식적 블록부트스트랩 재감사를 받은 결론(H22/H25/H26/H28/H32 등, 가중치만으로는 92~99.97%로
  robust급이었음)은 전부 weak/reversed로 강등됐는데, 정작 한 번도 형식 검정을 받지 않은 결론
  (코어 자산군 17자산·새틀라이트 청산 메커니즘)이 오히려 robust/moderate로 남아있음. 트랙B(No.07/08,
  작업22-23)와 트랙D(작업36-40)가 H18~H23 번호를 서로 무관한 가설에 재사용한 네임스페이스 충돌도
  발견(실제 오판 사례는 못 찾았으나 표기 위생 문제로 기록).
- **Look-ahead bias 재점검**: 최근 2주 내(2026-08-30~09-14) 추가된 스크립트 5개(위험조정모멘텀
  랭킹, 트랙C 부트스트랩 감사 audit1, 합성옵션헤지, H35 코어필터 부트스트랩, 라이브 칼라 상태
  계산)를 직접 읽고 신호-실행 lag(`shift(1)` 등)를 확인 — **신규 point-in-time 버그는 발견되지
  않음**(No.09 사후편향 사건 이후 규율이 최근 라운드들에서 일관되게 지켜지는 것으로 판단, 완화
  없이 정직하게 보고). 다만 더 근본적인 문제로 **이 프로그램이 반복 사용하는 위기/레짐 구간이
  실질적으로 6개뿐**(닷컴버블·GFC·2015-16조정·2018셀오프·COVID·2022약세장)이고 이 6개가 최소
  9개 이상의 서로 다른 가설에 반복 재사용됐다는 점을 지적 — Bonferroni/FDR로도 고쳐지지 않는
  한계로 명시.
- **메타 결론**: 오늘 라이브로 도는 `core/champion_strategy.py`의 최종 설정 중 다중비교 보정을
  통과해 "통계적으로 유의미하다"고 부를 수 있는 구성요소는 하나도 없다고 결론. 현재 운용 근거는
  (1) 2008년 단일 강력한 실제 위기 대응 사례, (2) 정적 배분이 여러 라운드에서 반복적으로 동적
  대안을 이겼다는 정성적 패턴, (3) 다른 대안들의 증거가 이보다 더 나빴다는 상대적 우위 — 세
  경제적/서사적 근거이지 가설검정으로 확정된 근거가 아니라는 구분을 명시적으로 남김. robust 1개는
  moderate로, moderate 3개는 전부 weak로 하향 권고.
- **산출물**: `analysis/2026-09-14_methodology_meta_audit/`(`count_tests.py`/
  `bonferroni_fdr_audit.py`/`consistency_and_leakage_audit.json`/`build_report_data.py`/
  `report_data.json`/`build_report.py`/`final_report.html`), 사본을
  `docs/reports/methodology_meta_audit_2026-09-14.html`로 배치하고 `docs/reports/README.md`
  "종합 캡스톤" 섹션에 추가. `analysis/LATEST_STRATEGY_CANDIDATE.md`가 아직 존재하지 않아(D
  미실행) 이번에 신규 생성하면서 "메타 감사 결과(다중비교 보정)" 섹션을 채움 — D가 다음에
  실행되면 파일 상단(본문)만 자신의 후보로 채우고 이 섹션은 유지해야 함.
- **하지 않은 것**: git commit/push(에이전트 설계상 금지), D/E/F의 전략 내용 재설계(감사만
  수행), 부정적 결과 완화.

### 작업 74 (2026-09-14, 같은 대화 후속): 리서치 에이전트 H(학술 문헌/외부 벤치마크 조사관) 첫 실행

작업66/67이 만든 R&D 에이전트 5개(D~H) 중 아직 아무도 실행되지 않은 상태에서, 사용자 요청으로
H 하나만 먼저 서브에이전트로 시험 실행. `analysis/LATEST_STRATEGY_CANDIDATE.md`가 아직 없어(D
미실행) 지시대로 대기하지 않고 `analysis/2026-09-05_research_program_synthesis/report_data.json`
의 `confidence_table`에서 아직 외부 문헌과 대조된 적 없는 항목("모멘텀 랭킹 방식(12개월
트레일링, 원시가격모멘텀)" moderate, "위험조정 모멘텀 랭킹" reversed — 둘 다
`2026-08-30_risk_adjusted_momentum_ranking/` 한 스크립트에서 같이 나온 결론)을 오늘의 주제로
선택.

- **실제 웹검색으로 문헌 7편 확인**: Jegadeesh & Titman(1993, J. Finance, 12개월 형성기간
  모멘텀 원조) · Novy-Marx(2012, JFE, "최근 1개월 제외" 12-2 관행 재확인, 2012 Fama-DFA상) ·
  Rachev/Jasic/Stoyanov/Fabozzi(2007, J. Banking & Finance, S&P500 517종목 - 원시수익 랭킹이
  절대수익은 최대지만 위험조정 랭킹이 독립적 위험조정지표에서는 우수) · Barroso &
  Santa-Clara(2015, JFE, "Momentum Has Its Moments" - 노출크기 변동성스케일링으로 모멘텀
  Sharpe 거의 2배) · Daniel & Moskowitz(2016, JFE, "Momentum Crashes" 메커니즘) · Moreira &
  Muir(2017, J. Finance, 변동성관리 포트폴리오 팩터 일반화) · Cederburg/O'Doherty/Wang/Yan
  (2020, JFE, 103개 전략 재검증 - 실시간 구현가능한 변동성관리는 대체로 무관리를 못 이김,
  Moreira&Muir 비판).
- **대조 결과 — 부분 일치**: "raw가 절대성과에서 위험조정 변형을 이긴다"는 내부 결론은
  Rachev et al.(2007)과 방향은 같으나, 그들의 "위험조정이 독립적 위험조정지표에서는 낫다"는
  결론과는 갈림(raw가 이 저장소에선 Sharpe·Calmar도 이김) — 17자산 top4 이산선택 구조 vs
  517종목 십분위 포트폴리오라는 유니버스 차이로 설명.
- **대조 결과 — 불일치(메커니즘 설명됨)**: Barroso&Santa-Clara/Moreira&Muir의 "변동성관리가
  모멘텀 Sharpe를 크게 올린다"가 재현 안 됨 — 원 논문은 노출 크기(레버리지 상향 허용)를
  스케일링하는데 이 저장소는 랭킹 단계에 적용해 층위가 다름. 노출 층위에서 실제 시도한 H28/H34
  변동성타겟팅 오버레이(cap=1.0)의 실패(부트스트랩 49.7%, 동전던지기)는 오히려 더 최근이고
  더 엄격한 Cederburg et al.(2020)의 비판과 일치 — 이 저장소의 회의론이 학계 소수 의견이
  아님을 시사.
- **대조 결과 — 신규 반례(이번에 처음 재현·발견)**: Jegadeesh&Titman/Novy-Marx의 "12-2"(최근
  1개월 제외) 모멘텀을 `analysis/2026-09-14_literature_benchmark/skip_month_momentum.py`로
  이 저장소 데이터(챔피언 유니버스·시장필터·비용 그대로, 랭킹 신호만 21거래일 스킵)에 처음
  적용 — `core.backtest_engine.calculate_metrics`/`_shuffle_daily_bars` 재사용해 동일 6개
  구간+200회 순열검정. 결과: 전체기간 2019-2026 Sharpe 1.03(raw)→0.81(스킵월), 특히 COVID
  2020에서 CAGR +2.14%→**-41.78%**(이번 대조 전체 통틀어 최악의 숫자, 위험조정(12m) 변형의
  -11.95%보다도 나쁨) — 최근월을 반전노이즈로 보고 걸러내는 게 오히려 "위기의 시작 그 자체"를
  놓치게 만든 것으로 해석. 순열검정상 전체기간 격차 자체(-0.22)는 p=0.8159로 비유의하나,
  COVID 국지적 붕괴는 이진 시장필터·새틀라이트 위기신호에서도 반복 관측된 "느린 신호는 수직
  급락에 취약하다" 패턴이 학술 관행에도 예외 없이 적용됨을 보여주는 세 번째 사례.
- 산출물: `analysis/2026-09-14_literature_benchmark/`(`skip_month_momentum.py`,
  `run_literature_benchmark.py`, `report_data.json`, `build_report.py`→`final_report.html`),
  `docs/reports/literature_benchmark_momentum_ranking_research.html`(사본)+`README.md` 항목
  추가, `analysis/LATEST_STRATEGY_CANDIDATE.md` 신규 생성(D 미실행 상태이므로 "외부 문헌 대조
  결과" 섹션만 포함, D/E/F/G가 이후 각자 섹션을 추가할 예정).
- `core/*.py` 무변경(기존 `champion_strategy.py`/`backtest_engine.py` 함수만 재사용) — 회귀
  테스트 불필요. **git commit/push 없음**(지시대로 워크트리에 미커밋 상태로 남김).

### 작업 75 (2026-09-15, 텔레그램 지시 — 운영/인프라, 리서치 결과 아님): 리서치 에이전트 B/C 수동 기동 +
야간 systemd 타이머 등록 유실 발견

텔레그램으로 "연구 에이전트 2개 작동시켜" 지시를 받고 점검한 결과, 작업65가 만든
`quant-research-agent-b.timer`/`-c.timer`는 어젯밤(2026-09-15 00:20 KST = 09-14 15:20 UTC)에는
정상 발화해 두 에이전트 모두 완주했음을 로그로 확인했다(`data/cache/research_agent_logs/
agent_b_20260914_152001.log`, `agent_c_20260914_152001.log` — 둘 다 pytest 823 통과/1건 무관한
기존 실패 후 정상 종료, `notify_if_accumulated.py`가 "미커밋 리포트 2개, 임계치 미달"로 알림은
생략). 문제는 **지금(같은 날 낮) 시점**: `systemctl list-timers`에 두 타이머 모두 `not-found
inactive dead`로 떠서 점검해보니, `/etc/systemd/system/timers.target.wants/`에는 활성화
심볼릭 링크가 남아있는데 그 링크가 가리키는 실제 유닛 파일
(`/etc/systemd/system/quant-research-agent-{b,c}.{service,timer}`)이 통째로 사라져 있었다 —
`deploy/research_agents/`의 원본 유닛 파일은 멀쩡하니, 누군가/무언가 어젯밤 발화 이후
`/etc/systemd/system/`에서 이 4개 파일만 지운 것으로 추정(원인은 특정 못함 — 이 세션은
`sudo`/`journalctl` 권한이 없는 `quant` 유저라 `/etc/systemd/system/`에 다시 파일을 넣거나
`daemon-reload`를 실행할 수 없다). 근본 원인은 별개로 **`deploy/setup_vm.sh`가 애초에 이 4개 유닛
파일을 한 번도 `/etc/systemd/system/`에 설치하는 단계를 포함한 적이 없었다**는 것 — 작업65/67이
수동으로(스크립트 밖에서) `cp`+`enable`했을 뿐이라 재부팅/재프로비저닝 시 재현 안 되는 취약점이
있었음. `deploy/setup_vm.sh`의 "[5/6] systemd 서비스 등록" 단계에 두 리서치 에이전트 타이머/서비스
`cp`+`enable --now`를 추가해 앞으로의 배포에서는 이 누락이 재현되지 않게 고쳤다(이번 세션 권한으로는
로컬 VM에 직접 재적용은 못 했고, 다음에 `sudo bash deploy/setup_vm.sh`를 재실행하거나 4개 파일을
`sudo cp ... && systemctl daemon-reload && systemctl enable --now quant-research-agent-{b,c}.timer`로
수동 재등록하면 됨).

- **지시 이행**: 타이머 등록을 직접 고칠 권한이 없으므로, 오늘 요청받은 "리서치 에이전트 2개"를
  실제로 지금 기동하는 것으로 지시를 이행했다. `run_research_agent.sh`가 쓰는 것과 동일한 환경
  (`HOME=/opt/quant`, `CLAUDE_CONFIG_DIR=/opt/quant/.claude`, `.env` 로드)을 그대로 재현해
  `setsid`로 완전히 분리한 백그라운드 프로세스로 에이전트 B(`agent_b_market_portfolio.md`)와
  에이전트 C(`agent_c_tenbagger.md`)를 각각 기동(PPID가 1로 재부모화된 것 확인, 이 텔레그램 세션이
  끝나도 계속 실행됨). 기동 시각 2026-09-15 08:48 UTC(17:48 KST), 로그는
  `data/cache/research_agent_logs/agent_{b,c}_20260915_084800.log` 이하. 각 에이전트는 최대
  23시간(`TimeoutStartSec=82800`)까지 실행되도록 설계돼 있어 오늘 이 세션 안에서 완주 결과까지는
  확인하지 못했다 — 페르소나 지시대로 두 에이전트 모두 스스로 git commit/push는 하지 않으므로,
  완료되면 결과물이 `/opt/quant` 워킹트리(신규 `analysis/` 폴더 + `PROGRESS.md`/
  `docs/reports/README.md` 추가분)에 미커밋 상태로 쌓인다 — 다음 라운드(작업76+)에서 검토 후
  병합/커밋 필요.
- 이 항목 자체는 `/opt/projects/sternjeong/Quant`(이 지시를 처리하려고 새로 만든 클론)에서
  작성해 커밋+푸시한다 — 실행 중인 리서치 에이전트들은 `/opt/quant`(라이브 배포 인스턴스)의
  워킹트리에서 직접 돌고 있으니, 이 커밋과는 별개다.
- `core/*.py`/`app/*.py` 무변경(운영/문서성 변경만: `deploy/setup_vm.sh` + 이 `PROGRESS.md` 항목).
  회귀 테스트 불필요.

### 작업 76 (2026-09-15, 텔레그램 지시 — 문서만): "추후 로그인해서 해야 할 것" 메모 신설

텔레그램으로 "내가 추후 로그인해서 해야할것 메모해줘" 지시를 받고, 이 저장소에 이미 흩어져
있던 "사람이 직접 로그인/sudo/SSH로만 처리 가능한" 대기 항목 3개를 `PROGRESS.md`/
`deploy/DEPLOYMENT_ORACLE.md`/`deploy/codex_telegram/README.md`에서 찾아 한 곳으로 모았다.

- **`deploy/PENDING_MANUAL_LOGIN_ACTIONS.md` 신규**: (1) 작업75가 발견한 리서치 에이전트
  B/C의 `/etc/systemd/system/` 타이머 유닛 유실(`sudo`로 재설치 필요, 작업67의 "VM 대신
  Codespace" 정정과 상충한다는 점도 메모), (2) Oracle 배포 VM(`138.2.11.196`)이 오래된 커밋에
  멈춰 있어 최근 기능(신호알림/거장 배지/FRED 사전예열)이 라이브 미반영(SSH 로그인 후
  `git pull`+서비스 재시작 필요), (3) GitHub Actions 나이틀리 리서치 자동화용 Secrets 미등록
  (아직 미착수, 우선순위 낮음) 세 항목을 각각 확인 명령/조치 명령과 함께 정리.
  `gh auth`/`claude login`/Codex 인증은 이 VM(`/opt/quant`)에서 이미 완료된 상태임을 직접
  `gh auth status`·`systemctl status codex-telegram`으로 재확인해 목록에서 제외했다.
  `deploy/DEPLOYMENT_ORACLE.md` 상단에 이 문서로의 링크 한 줄 추가.
- `core/*.py`/`app/*.py` 무변경(문서 신설/링크 추가뿐). 회귀 테스트 불필요.
- 이 항목도 작업75와 동일하게 `/opt/projects/sternjeong/Quant`(텔레그램 지시 처리용 클론)에서
  작성해 커밋+푸시한다 — 라이브 인스턴스(`/opt/quant`)는 다른 진행 중 변경사항(연구 에이전트
  결과물 미커밋분, `deploy/codex_telegram/` 진행 중 수정분)이 있어 건드리지 않았다.

### 작업 77 (2026-09-20, 텔레그램 지시): 관제 허브(`hub/`) 신설 — IP 진입점을 앱 목록 대시보드로

텔레그램 지시: "quant-vm 서버를... 여러 앱들을 관리하는 최상위 감시 모듈을 만든 후(IP 주소를
치면 이게 나오도록) 슬롯을 누르면 대응되는 웹/엔진이 나오게" 만들어달라는 요청.

- VM 현황 조사(이 세션이 실제로 `/opt/quant`에서 도는 그 `quant` 계정이라 직접 확인 가능):
  nginx(80번)가 지금은 Streamlit(8501)에만 직접 프록시하고 있고, `quant-scheduler`/
  `codex-telegram`/`quant-experiment-supervisor`/`quant-vm-health`는 전부 웹 UI 없는 백그라운드
  서비스임을 확인. `quant` 계정은 sudo 없이도 `systemctl show <unit>`으로 다른 유닛 상태를 읽을 수
  있지만(직접 확인함), `journalctl`은 `adm`/`systemd-journal` 그룹이 아니라서 권한이 없음 —
  그래서 허브는 로그가 아니라 상태(active/inactive)까지만 보여주기로 결정.
- **신규 `hub/` 모듈** (`__init__.py`, `apps_registry.py`, `status.py`, `server.py`): stdlib
  `http.server`만 사용(신규 pip 의존성 없음). `apps_registry.SLOTS`에 앱/엔진 5개를 선언
  (퀀트 대시보드=web, 스케줄러=engine, 실험 슈퍼바이저=report, codex-telegram=engine,
  VM 헬스체크=engine). `/`가 카드 그리드를 렌더링하고, 카드를 누르면 kind별로 자기 포트로 직접
  이동(web)/최신 HTML 리포트 서빙(report, `.experiment-control/reports/*.html`에서 mtime 최신
  파일)/`systemctl show` 상태 페이지(engine)로 분기.
- **배포 아티팩트**: `deploy/quant-hub.service`(127.0.0.1:8000, `OnFailure=quant-alert@%n.service`
  기존 패턴 재사용), `deploy/nginx-quant.conf`(80번 `default_server`를 hub로 프록시, Streamlit은
  건드리지 않고 그대로 `:8501` 직접 노출 유지 — baseUrlPath 등 건드릴 필요 없어 위험 최소화).
  `deploy/setup_vm.sh`에 nginx 설치 + hub 서비스/사이트 등록 단계 추가(신규 VM 기준 자동 반영).
- **의도적으로 안 한 것 (sudo 필요, 이 세션 권한 밖)**: 실제 VM(`138.2.11.196`)에 `quant-hub.service`
  설치 + `/etc/nginx/sites-enabled/quant-streamlit` → `quant-hub`로 교체는 사람이 sudo로 해야
  하므로 코드만 준비하고 `deploy/PENDING_MANUAL_LOGIN_ACTIONS.md` 4번에 정확한 명령을 남겼다.
  `deploy/auto_deploy.sh`의 `SERVICES=(...)` 배열에는 **의도적으로 `quant-hub`를 아직 추가하지
  않음** — 그 스크립트가 `systemctl restart "${SERVICES[@]}"`를 한 줄로 실행하는데 `quant-hub`
  유닛이 VM에 설치되기 전에 이 커밋이 먼저 배포되면(자동배포 타이머가 5분마다 돌므로 실제로 그렇게
  됨) `set -e`로 스크립트가 중단돼 `quant-streamlit`/`quant-scheduler` 재시작까지 함께 실패할
  위험이 있었기 때문(로그 확인도 안 되는 이 세션 권한으로는 사후 복구도 어려움) — PENDING 문서
  4번의 설치를 먼저 끝낸 뒤 별도 커밋으로 추가하기로 함.
- `tests/test_hub.py` 신규(12개, `subprocess.run`을 목킹해 실제 systemd 의존 제거). 로컬에서
  `/opt/quant/.venv/bin/python -m hub.server`를 실제로 띄워 `/`, `/healthz`, `/status/<id>`,
  `/reports/<id>`, 404 경로를 curl로 직접 확인했고, 이 VM의 진짜 systemd 상태(Streamlit/스케줄러/
  codex-telegram=active, VM헬스체크=inactive — 타이머 사이 대기 상태라 정상)가 카드에 정확히
  반영됨을 확인. `pytest tests -q`(전체 회귀, auto_deploy.sh와 동일한 스코프) 957 passed, 기존에도
  있던 무관한 실패 2건(`test_strategy_library_archive.py`, 이 변경 전 `git stash`로도 동일하게
  재현돼 무관함을 확인)만 남음.
- `README.md` 디렉터리 구조 + `deploy/DEPLOYMENT_ORACLE.md`(13번 절 신설)에 허브 구조/사용법 문서화.

### 작업 77 (2026-09-17, 무인 야간 실행 — 리서치 에이전트 C): "진짜 비-AI 대조군" 미완성 라운드
마무리 — 3바스켓 전부에서 IREN 추세추종 패턴 재현 실패, 방향무관 손실축소 효과만 확인

`research_agents/agent_c_tenbagger.md` 페르소나의 이번 자동 실행. 시작 전 워킹트리를 점검하다
작업75가 텔레그램 지시로 수동 기동한 이전 에이전트C 실행(2026-09-15 08:48 UTC)이
`analysis/2026-09-14_nonai_control_basket_volatility_momentum/`에 이 에이전트 페르소나가 명시한
"미해결 문제" 중 하나("진짜 AI 피벗 안 한 대조군 바스켓이 없다")를 이미 거의 완성해뒀다는 걸
발견 — 해운/대마초/태양광 3개 독립 비-AI 고변동성 테마 바스켓의 전체 백테스트(`run_backtest.py`)
와 순열검정+블록부트스트랩 감사(`audit_stats.py`)가 전부 끝나 있었지만, 마지막 조립 단계
(`assemble_report_data.py` → `report_data.json`, `build_report.py` → `final_report.html`)가
실행되지 않은 채 남아 있었다(아마 이전 세션이 23시간 제한 또는 컨텍스트 한도로 조립 직전에
끊김). 새로 계산을 반복하지 않고 이 미완성 라운드를 끝까지 완성하는 것으로 판단 — 동일한
분량의 신규 작업(3개 독립 대조군, 바스켓당 정적매수후보유/모멘텀로테이션/추세추종 3구성 비교,
순열검정 200회+블록부트스트랩 2,000회×3블록길이)이 이미 그 자체로 페르소나가 요구한 "최소
2~3개의 변형/반박 가설 검증"을 충족하므로 처음부터 다시 만들 필요가 없다고 봤다.

- **조립 중 버그 2개 발견·수정**: `build_report.py`의 `iren_perf_rows()`가 IREN 기준값 중
  `basket_static_buy_hold`/`momentum_rotation`은 `{"metrics": {...}}`로 한 겹 더 중첩된 구조인데
  `spy_buy_hold`만 그 중첩을 벗기고 나머지는 안 벗겨 `KeyError: 'sharpe'`가 났던 문제(→
  `_unwrap_metrics()` 헬퍼로 통일), `bootstrap_summary_rows()`가 대조군 바스켓의 부트스트랩 키
  (`point_estimate_sharpe`)와 IREN 참조값의 키(`mean`)가 다르다는 걸 놓쳐 두 번째 `KeyError`가
  났던 문제(→ IREN 쪽만 `mean`으로 읽도록 수정). 둘 다 리포트 조립 스크립트 버그였지 백테스트/감사
  계산 자체의 문제는 아니었다 — 원본 수치(`backtest_results.json`/`audit_results.json`)는
  손대지 않았다.
- **핵심 결과(계산은 전임 세션 산출, 이번 세션은 검증·조립만)**: 해운(ZIM/SBLK/DAC/FRO/STNG,
  2021-07-29~) · 대마초(TLRY/CGC/ACB/CRON, 2019-01-18~) · 태양광(ENPH/SEDG/RUN/FSLR/PLUG,
  2016-02-04~) 3개 바스켓에 IREN 연구(작업27)가 채택한 돈치안20일+15%트레일링스탑 추세추종
  규칙을 파라미터 재조정 없이 그대로 이식 — **3개 대조군 중 어느 것도 IREN의 "추세추종이
  매수후보유·로테이션을 모두 이긴다"는 패턴을 온전히 재현하지 못함**. 해운은 바스켓내 모멘텀
  로테이션(샤프 1.00)이 추세추종(0.62)·매수후보유(0.82)를 모두 앞섬(IREN 연구가 "이 좁은
  바스켓엔 로테이션이 안 먹힌다"고 적은 것과 정반대 — 해운 5종목의 상관관계가 충분히 낮아
  로테이션의 폭(breadth) 이점이 살아난 것으로 해석). 대마초는 전 구성이 손실(구조적 장기하락)
  이나 추세추종·로테이션이 매수후보유보다 손실을 줄이는 방향-무관 효과만 확인. 태양광은
  단일종목(ENPH, 샤프 0.84)만 우세하고 바스켓 추세추종(0.70)은 매수후보유(0.54)를 근소하게만
  앞섬. 순열검정 200회: 해운 바스켓 p=0.24/단일 p=0.47, 대마초 바스켓 p=0.75/단일 p=0.64,
  태양광 바스켓 p=0.21/단일만 p=0.025 — IREN의 비대칭 패턴(단일만 유의, 바스켓은 미달)이
  6개 값 중 1개만 통과, 재현되지 않음. 블록부트스트랩(L=10/20/40, 2,000회)도 같은 비일관성 확인.
- **정직한 판정**: IREN의 극적 성과(샤프 1.23~1.31)가 규칙 자체의 재현 가능한 일반 원리라기보다
  그 바스켓·그 표본기간(2022-05~2026-08, AI 인프라 슈퍼사이클과 정확히 겹침) 고유의 조합 효과일
  가능성이 세 독립 대조군으로 더 커졌다는 게 이번 라운드의 결론 — 완전한 반증은 아니며(대마초의
  "규율 있는 청산이 방향과 무관하게 손실을 줄인다"는 더 약한 일반 효과는 확인됨). lottery-stock
  긴장(에이전트 페르소나 명시 요구사항)은 해소되지 않고 오히려 "텐베거가 될지 대마초가 될지
  사전에 가려낼 방법이 없다"는 형태로 뚜렷해졌다고 완화 없이 그대로 기록. 승리로 포장할 구석
  없는 정직한 혼재 결과.
- **한계도 명시**: 대조군 3개도 결국 사후에 뚜렷한 테마가 있었던 걸 알고 고른 것이라 IREN
  선정 자체가 받았던 사후편향 의심(작업24/25)에서 완전히 자유롭지 않음. 바스켓마다 종목수
  (4~5개)·표본기간(5.1~10.6년)이 이질적이라 엄밀한 메타분석(효과크기 통합)은 시도하지 않음.
  생존편향(현재 거래되는 종목만 사용, 업종 내 상장폐지·파산 종목은 후보에서 빠짐)·단순 비용모형
  (왕복 0.1%)은 그대로 물려받음.
- 산출물: `analysis/2026-09-14_nonai_control_basket_volatility_momentum/report_data.json`(신규
  생성)+`final_report.html`(신규 생성), 사본을
  `docs/reports/nonai_control_basket_volatility_momentum_research.html`로 배치,
  `docs/reports/README.md` 트랙C에 No.6으로 추가(요약+상세 블록 둘 다).
- `core/*.py`/`app/*.py` 무변경(이번 세션이 고친 건 리포트 조립 스크립트 `build_report.py`
  뿐) — pytest 재실행 불필요.
- 같은 워킹트리에 이번 세션 범위 밖인 미완성 산출물 3개(`analysis/2026-09-14_satellite_
  correlation_crisis_signal/`, `analysis/2026-09-15_options_collar_hedge_volatility_momentum_
  basket/`, `analysis/2026-09-15_options_collar_parameter_sensitivity/`)가 함께 발견됨 —
  전부 트랙B/D(시장포트폴리오·옵션헤지) 주제라 에이전트B 소관으로 판단해 손대지 않았다(에이전트B가
  이어서 마무리하거나, 사람이 직접 검토 필요 — `2026-09-15_options_collar_parameter_sensitivity`
  만 `report_data.json`+`final_report.html`까지 이미 완성돼 있고 나머지 둘은 이 폴더처럼 조립
  전단계에서 멈춰 있음).
- git commit/git push 없음(페르소나 지시대로 워킹트리에만 결과물을 남김 — 사용자가 직접 검토 후
  커밋).

### 작업 78 (2026-09-17, 무인 야간 실행 — 리서치 에이전트 B): 2라운드 미완성 산출물 재발견·완성 —
BTC 표시 콜라(변동성모멘텀 바스켓) + 칼라 파라미터 그리드 2라운드

에이전트B 페르소나로 시작해 필수 자료(`docs/reports/README.md`, `PROGRESS.md` 최근 항목,
`confidence_table`, `core/champion_strategy.py` docstring)를 읽던 중, 같은 워킹트리에 에이전트B
소관으로 명시적으로 남겨진(작업77이 "트랙B/D 주제라 손대지 않았다"고 기록) 미완성 산출물 2개를
발견 — 작업77과 마찬가지로 계산은 전부 전임 세션(2026-09-15)이 끝내놓고 마지막 조립·문서화
단계에서 중단된 상태였다. 새로 가설을 세우기보다 이 두 라운드를 완성하는 것을 이번 세션 첫
과제로 판단(계산 재실행 없이 순수 조립만 필요해 비용 대비 가치가 높고, 둘 다 이 페르소나가
명시한 "아직 안 풀린 문제" 3번 항목인 칼라 파라미터 민감도와 직접 관련).

- **`2026-09-15_options_collar_hedge_volatility_momentum_basket/`(BTC 표시 콜라)**: `build_report_data.py`/
  `build_report.py` 실행만으로 완성(스크립트·데이터 모두 이미 존재, 버그 없음). H1(SPY 콜라 1x,
  기각 재확인)·H2(베타 최대4.5배 노셔널 스케일업, 더 나쁜 쪽으로 기각)·H3(BTC 표시 콜라, 낙폭구간
  −71.0% 동안 BTC는 −47.1%·SPY는 −4.99%만 움직여 실제 정합성 있는 기초자산) 3개 가설 — H3만
  부분채택: 낙폭구간 누적수익 무헤지 −60.1%→BTC콜라 −49.2%(샤프 −1.07→−0.49), 블록부트스트랩
  승률 SPY콜라 대비 68~72%·무헤지 대비 64~67%. 단 평시 포함 전체기간에서는 BTC 옵션 프리미엄이
  비싸 무헤지 대비 승률 29~30%로 떨어져 "상시 유지"가 아니라 "위기 한정" 헤지로만 해석 가능하다고
  명시. `iren_basket_collar_hedge_transplant_research.html`(작업 없음 번호, 트랙C No.5)이 "SPY가
  안 맞는 이유는 idiosyncratic 위험이라서다"로 남긴 다음 질문에 대한 직접 답.
- **`2026-09-15_options_collar_parameter_sensitivity/`(칼라 그리드 2라운드)**: 이미
  `final_report.html`까지 완성돼 있어 `docs/reports/`로 사본만 옮김. 작업68(1라운드, 24조합
  완만성 그리드+무작위 200개 플라시보)보다 세밀한 독립 풋/콜/테너 스윕(H2a/b/c)과 두 종류의 새
  플라시보(H3a 순열검정, H3b 제로페이오프 플라시보)로 확장 — 테너가 "짧을수록 평시 유리, 길수록
  위기(GFC) 유리"인 진짜 연속 트레이드오프임을 확인했고(트레일링스탑 폭 스윕 작업43 H19와 같은
  패턴), 위기창 4개(GFC 88.5th/COVID 98th/2022 96.5th/2018 97.5th) 순열검정 압도 + 6개 창 전부
  제로페이오프 플라시보 압도로 "칼라가 착시가 아니라 진짜"라는 근거를 보강했다. 다만 H4
  결합전파(5개 대표 변형)에서는 여전히 15개 승률 전부 노이즈 폭 안이라 특정 파라미터 조합의
  통계적 우월성은 확인 안 됨 — 기존 약함(weak) 등급 유지, 근거만 정교해짐.
- 두 라운드 모두 `core/`·`app/` 변경 없음(리포트 조립만) — pytest 재실행 불필요.
- 산출물: 위 두 폴더의 `report_data.json`/`final_report.html`(BTC콜라 쪽은 신규 생성, 그리드
  2라운드는 이미 존재), 사본을 각각 `docs/reports/options_collar_btc_instrument_transplant_research.html`
  (트랙C, iren_basket_collar_hedge_transplant 바로 뒤)·`docs/reports/options_collar_moneyness_
  tenor_grid_and_placebo_research.html`(트랙D 이후 독립, collar_hedge_parameter_sensitivity 바로
  뒤)로 배치, `docs/reports/README.md`에 요약+상세 블록 둘 다 추가.
- 남은 미완성 산출물(`2026-09-14_satellite_correlation_crisis_signal/`)은 계산 스크립트 자체가
  `KeyError: 'switch_spy'`로 크래시한 채 멈춰 있었음(조립 이전 단계, 단순 조립으로는 못 끝냄) —
  이번 세션의 본 작업(작업79)으로 이어서 처리.
- git commit/git push 없음.

### 작업 79 (2026-09-17, 무인 야간 실행 — 리서치 에이전트 B, 이번 세션 본 작업): 트랙D 7라운드
독립 후속 — 새틀라이트 상관관계 급등 신호로 2021년 사각지대 재검증

페르소나가 명시한 "아직 안 풀린 문제" 1번("2021년 성장주 언와인드형 국지적 위기 사각지대")을
다뤘다. 작업35(7라운드)가 이미 새틀라이트 자체 breadth·트레일링 드로다운 두 신호를 시도해 둘 다
SPY 200일선 스위치를 못 이겨 기각했고, "새틀라이트 구성종목 간 상관관계 급등" 같은 세 번째
신호군은 시도된 적이 없다고 명시적으로 남겨둔 과제였다.

- **미완성 산출물 재발견**: `analysis/2026-09-14_satellite_correlation_crisis_signal/`에 이미
  이 정확한 가설(보유종목 상관관계·후보풀 상관관계 급등, trailing 252일 z-score)을 검증하는
  계산 스크립트 2개(`h_signals_and_backtest.py` 474줄, `h_bootstrap_and_permutation.py` 276줄)가
  전 세션(2026-09-15)에 작성돼 47분간 6개 역사적 구간(전체기간/2008GFC/COVID/2022/2018/2015-16)
  전체를 계산한 뒤 `KeyError: 'switch_spy'`로 저장 직전 크래시한 채 남아 있었다 — 원인은
  `run_episode()`가 `switched_series` 딕셔너리에 스위치 신호를 접두어 없이(`spy`) 저장했는데
  이후 CSV 저장 루프가 `switch_spy` 키로 조회해 생긴 단순 네이밍 버그. 새로 설계하지 않고 이
  1줄 버그만 고쳐(`switched_series[f"switch_{sname}"] = blended`) 원안 그대로 재실행 — 47분
  전체가 캐시 덕에 거의 동일한 시간(2843초)에 재현됨. 이어서 돌린 부트스트랩 스크립트도 같은
  종류의 버그 2개(`circular_shift_permutation_test` 내부의 로컬 `sys.path`에
  `2026-08-19_champion_beta_and_satellite_research`(champion_strategy.py)와
  `2026-08-21_satellite_signal_upgrade_and_crisis_test`(h11_crisis_robustness_test.py) 경로가
  빠져 있었음)를 고쳐 재실행 — 계산 자체는 재설계 없이 원안 그대로.
- **핵심 결과**: **2021년 사례(2021-11-19 정점) 반응속도**가 SPY 42거래일·7라운드의 breadth신호
  61거래일이었던 데 비해 보유상관 신호 25거래일·풀상관 신호 11거래일로 뚜렷이 개선 — 이 프로그램
  전체에서 처음으로 SPY보다 빨리 반응한 새틀라이트 전용 신호. **하지만 전체기간(2019-08~2026-08)
  순열검정(신호를 무작위 오프셋만큼 순환이동시킨 500회 플라시보 대비 실제 신호의 백분위)에서
  보유상관 신호의 실제 타이밍은 겨우 3번째 백분위**(플라시보 평균보다 나쁨) — 2021년 한 사례에서
  빠르게 반응한 것과 전체 표본에서 그 온/오프 타이밍이 통계적으로 유용한지는 다른 질문임을 직접
  보여준 사례(풀상관은 58번째 백분위로 동전던지기 근처, 표본이 3개 페어뿐인 보유상관보다 40종목
  풀이라 더 안정적). z-threshold(1.0/1.5/2.0) 스윕은 샤프 1.1~1.15 범위로 안정적이라 임계값
  자체의 과최적화 의심은 낮음.
- **기댓값 재구성(작업39 H22와 동일한 3개 기저확률 시나리오)**: SPY 단독 스위치는 base/calm_heavy/
  crisis_heavy 3개 시나리오 전부에서 코어단독·정적새틀라이트보다도 나쁜 최하위(작업39의 기존
  결론과 일치) — 보유상관 스위치는 SPY 단독을 3개 시나리오 전부에서 앞서지만(base: 샤프 −0.014
  vs −0.097), 스위칭이 아예 없는 정적 새틀라이트(+0.021)에는 여전히 못 미침(정적보유가 기댓값
  최적이라는 작업34~39 결론 재확인). SPY와 보유상관을 OR로 결합한 구성만 3개 시나리오 전부에서
  SPY 단독보다 근소 우위(디리클레(K=30)×부트스트랩 결합전파 승률 54~57%).
- **정직한 등급**: 약함(weak). 기존 "새틀라이트 전용 위기신호: 기각(reversed)" 판정에서
  "SPY-OR-결합 한정 약한 완화책"으로 소폭 상향되지만, 7라운드가 남긴 숙제("SPY보다 빠른 신호")는
  부분적으로만 풀렸고 2021년류 사각지대는 완전히 닫히지 않았다고 그대로 기록. 승리로 포장할 구석
  없는 결과.
- **한계**: pool_corr(40종목 풀)는 야후 파이낸스 레이트리밋 때문에 6개 구간 중 3개(covid_2020/
  selloff_2018/correction_2015_2016, 기저확률 합 37%)에서 계산을 생략(본문 disclose, 기댓값
  계산에는 holdings_corr만 사용해 이 비대칭이 왜곡을 안 일으키게 함). holdings_corr는 보유종목
  3개(페어 3개)뿐이라 표본이 작고 노이즈가 큼. 2021년 사례는 n=1이라 통계적 증거로 취급하지 않고
  참고 사례로만 사용.
- 산출물: `analysis/2026-09-14_satellite_correlation_crisis_signal/{h_corr_results.json,
  h_boot_perm_results.json, report_data.json, final_report.html}`(전부 신규 생성, 계산 스크립트는
  버그 수정만), 사본을 `docs/reports/satellite_correlation_crisis_signal_research.html`로 배치,
  `docs/reports/README.md` 트랙D 목록 끝(작업78의 두 칼라 리포트 바로 뒤)에 요약+상세 블록 둘 다
  추가.
- `core/*.py`/`app/*.py` 무변경(이번 세션이 고친 건 `analysis/2026-09-14_satellite_correlation_
  crisis_signal/` 안의 계산 스크립트 2개뿐, 그것도 네이밍 버그 수정만) — pytest 재실행 불필요.
- 이번 세션 동안 같은 워킹트리에서 별도 리서치 에이전트 C가 동시 실행 중이었음을 확인(작업77을
  이미 완료해 둔 상태) — PROGRESS.md/README.md 동시편집 충돌을 피하기 위해 매 수정 직전 파일을
  다시 읽어 최신 상태 기준으로 append했다.
- git commit/git push 없음(페르소나 지시대로 워킹트리에만 결과물을 남김 — 사용자가 직접 검토 후
  커밋).

### 작업 87 (2026-09-17, 무인 야간 실행 — 리서치 에이전트 B): 트랙D 21라운드(H37) —
정밀그리드 결합후보(14~16개월+분기)의 첫 블록부트스트랩 감사, 이번엔 동전던지기로 안 무너짐

페르소나가 명시한 "아직 안 풀린 문제" 2번("14~16개월 모멘텀 룩백 + 분기 리밸런싱 파라미터 후보,
정밀 그리드서치에서 유망했지만 아직 블록부트스트랩 감사를 거치지 않았다")을 다뤘다. 시작 전
작업77/78/79가 이미 나머지 두 미완성 산출물(비-AI 대조군, BTC콜라+칼라그리드 2라운드, 새틀라이트
상관관계신호)을 전부 완결해 뒀다는 걸 확인 — 이번 세션은 새 가설을 처음부터 계산했다.

- **문제의 정확한 소재 확인**: H32(작업44, 17라운드)는 룩백 9~18개월×리밸런싱 4주기 40칸 정밀
  그리드에서 14~16개월+분기가 샤프 격차 0.01~0.014 안의 "완만한 고원"이라고 보고했다. H34(작업45,
  18라운드)가 뒤이어 수행한 블록부트스트랩 감사는 이 결합 최적점을 감사한 게 아니라, 사용자 지시로
  룩백을 12개월에 고정한 채 리밸런싱 주기만 격리한 좁은 질문이었다(H34 자신이 04절 한계에 명시) —
  거기선 가중치 단계부터 이미 승률 48.6%→표본오차 결합 후 49.6%로 동전던지기였다. 즉 "룩백을 같이
  옮기는 결합 효과 자체"는 이 프로그램 어디서도 표본오차 감사를 받은 적이 없었다.
- **H1(재현성 확인)**: H32의 `run_champion_joint()`를 코드 변경 없이 그대로 호출해 14/15/16개월+분기
  구성을 6개 창(전체기간/2008GFC/COVID/2022/2018/2015-16)에서 재실행 — H32가 저장해 둔
  `h32_stage1_results.json`의 점추정치와 18개 셀 전부 소수점 6자리까지 완전 일치(결정론적 재현성
  확인, 새 백테스트 18회 자체도 이 세션이 직접 수행).
- **H2/H3(블록부트스트랩+결합전파) — 핵심 결과**: H33/H34와 완전히 동일한 방법론(순환 이동블록
  부트스트랩 L=10/20/40일, 창당 2,000회, 디리클레(K=30) 결합전파 10,000draws)을 12개월/월간(현재
  라이브 기본값)·12개월/분기(H34 기준선)·14/15/16개월/분기 다섯 구성에 적용하고, 3개 기저확률
  시나리오(base/calm_heavy/crisis_heavy) 각각에서 18개 비교(3개 후보×3개 시나리오×2개 기준선)를
  전부 계산했다. **18개 비교 전부에서 결합승률이 54.8%~63.2% 범위에 머물러 50% 아래로 단 한 번도
  안 내려갔다** — "가중치만 반영하면 99%대 확정적, 표본오차를 더하면 50%대로 붕괴"라는 이
  프로그램의 가장 반복적인 메타 발견이 이번엔 다른 결말을 냈다. 16개월/분기가 가장 일관되게
  앞서고(평균 61.8%), 14개월/분기가 근소하게 뒤를 이으며(평균 60.7%), 15개월/분기(H31 조그리드의
  원래 우승점)가 상대적으로 가장 약함(평균 55.6%, 그래도 최저치 54.8%로 절반은 넘음).
- **H4(40칸 전수 그리드 백분위, 플라시보 대용)**: 재계산 없이 H32의 기존 그리드 데이터(그 자체가
  표본이 아니라 전체 모집단)만 재조회해 14/15/16개월+분기가 3개 시나리오 전부에서 상위 5위 안
  (87.5~100번째 백분위)에 드는 반면 현재 라이브 기본값(12개월/월간)은 11~20위(중위권)에 그친다는
  걸 재확인. 추가 발견: **14개월/분기의 5개 위기창(GFC/COVID/2022/2018/2015-16) 최악 MDD가
  -15.73%로 현재 기본값(-29.77%)의 거의 절반**인 반면 15/16개월은 같은 지표가 -28.01%로 개선폭이
  훨씬 작음 — 샤프 기준 최적(16개월)과 꼬리위험 기준 최적(14개월)이 갈리는 트레이드오프.
- **정직한 등급**: 약함(weak) — 이 프로그램의 등급 관례(70% 문턱)를 그대로 적용하면 18개 비교
  전부 70%를 못 넘어 "강함"이라고 부를 근거는 없다. 다만 3개 시나리오×2개 기준선×전수그리드
  전부에서 방향이 단 한 번도 안 뒤집혔다는 점이 이 프로그램의 다른 "약함" 판정들(대부분 50%
  근처를 넘나듦)과 구별되는 지점이라고 승리로 과장하지 않되 숨기지도 않고 기록. "15개월"이라는
  특정 숫자에 집착할 근거는 이번 라운드로 더 약해졌다(15개월이 세 후보 중 가장 약함).
- **한계**: 코어 단독 비교만 다룸(새틀라이트 블렌딩과 결합 시 순위 유지 여부 미확인). 블록부트스트랩
  자체의 한계(COVID·2018처럼 짧은 창은 신뢰구간이 넓음, 실제 역사에 없던 "다른 위기"를 생성 못함)는
  H33/H34와 동일하게 적용됨. 디리클레 결합전파의 카테고리간 독립성 가정도 그대로 물려받음. 거래
  비용/세금(작업72가 지적한 순열검정 실패 p=0.2388)은 이 라운드의 범위 밖 — 두 감사를 모두 통과해야
  진짜 confidence가 올라간다는 원칙 유지, 이번 라운드 결과만으로 confidence_table을 상향하지 않음.
- 이 결과는 `core/champion_strategy.py`의 기본값 변경을 권고하지 않는다 — 페르소나 지시대로 순수
  리서치이며, 반영 여부는 사용자가 별도 판단.
- 산출물: `analysis/2026-09-17_fine_grid_joint_candidate_bootstrap_audit/`(`h_joint_candidate_
  bootstrap.py`/`build_report_data.py`/`build_report.py`/`h37_results.json`/`report_data.json`/
  `final_report.html`, 전부 신규), 사본을 `docs/reports/fine_grid_joint_candidate_bootstrap_audit_
  research.html`로 배치, `docs/reports/README.md` 트랙D 목록 끝(작업79의 새틀라이트상관관계신호
  리포트 바로 뒤)에 요약+상세 블록 둘 다 추가.
- `core/*.py`/`app/*.py` 무변경(신규 analysis 스크립트만 작성) — pytest 재실행 불필요.
- git commit/git push 없음(페르소나 지시대로 워킹트리에만 결과물을 남김 — 사용자가 직접 검토 후
  커밋).

### 작업 88 (2026-09-17, 무인 야간 실행 — 리서치 에이전트 C, 이번 세션): 표본기간을 25년까지
확장 — 크립토윈터 2018·닷컴버블 2000으로 추세추종 규칙 재검증, 6개 시대 중 정확히 절반만 재현

`research_agents/agent_c_tenbagger.md` 페르소나의 이번 자동 실행. 시작 전 워킹트리를 점검하니
`analysis/2026-09-17_live_tenbagger_screening_snapshot/`(discover_run.py/valuation_check.py만
있고 미실행)과 `analysis/2026-09-17_lookback_rebal_candidate_bootstrap_audit/`,
`analysis/2026-09-17_fine_grid_joint_candidate_bootstrap_audit/`(둘 다 룩백기간/리밸런싱주기
그리드서치 — 트랙B/D 주제, 이 세션 실행 중에도 계속 파일이 늘어나는 걸 보고 다른 에이전트(B)가
동시에 실제로 작업 중임을 확인 — 위 작업87이 그 결과물)가 이미 워킹트리에 있었다. 뒤의 두 폴더는
작업77의 선례대로 에이전트B 소관으로 보고 손대지 않았고, 앞의 것은 이 에이전트 페르소나의 "오늘
기준 신규 후보 스캔" 항목과 일치하지만 미실행 상태라 이번 라운드의 주 작업으로 삼지 않고 그대로
남겨뒀다(다음 라운드에서 마무리 가능).

페르소나가 나열한 미해결 문제 중 "표본 구간이 짧다(~4.25년): 진짜 베어마켓/크립토윈터를 겪어보지
않았다"를 선택 — 지금까지 트랙C의 모든 백테스트가 2016~2026년(대부분 2021~2026년)에 몰려 있다는
반복 지적을 직접 검증했다.

- **방법론**: 새 백테스트 로직을 만들지 않고 작업27(`analysis/2026-08-16_iren_volatile_momentum_
  stocks/backtest.py`)의 `find_common_start`/`run_rotation`/`donchian_trailing_stop_positions`/
  `run_trend_following_single`/`run_trend_following_basket`을 그대로 import해 재사용, 감사
  기계도 작업77(`nonai_control_basket/audit_stats.py`)의 순열검정+블록부트스트랩 구조를 그대로
  재사용(파일명만 `common_era.py`로 변경해 모듈명 충돌 회피).
- **H1(크립토윈터 2018) — 재현**: MARA·RIOT가 IREN 상장(2021-11) 전인 2017년 하반기에 이미
  비트코인 채굴로 사업을 전환한 역사(RIOT 2017-10 거래량 15만→1400만주 폭증으로 확인)에 같은
  규칙을 이식. 공통구간 2017-07~2021-10(IREN 상장 전 마감, AI 서사 없음)에서 추세추종 바스켓
  샤프 1.24가 매수후보유 0.97·로테이션 0.77을 모두 이겨 IREN 패턴을 강하게 재현했고, 대표종목
  RIOT 전체이력 최대낙폭은 -98.3%(2017-12 정점 $28.4 → 2018-12 $1.51)로 이 저장소 전체에서
  가장 극단적인 실측 낙폭이었다. 순열검정 단일종목(RIOT) p=0.0348 — **IREN 단일(p=0.005) 다음
  으로 이 트랙C 전체에서 두 번째로 통계적으로 유의**했고, 바스켓도 p=0.0697로 IREN 바스켓
  (p=0.075)과 거의 같은 수준까지 접근했다.
- **H2(닷컴버블 2000) — 미재현**: 1998~2002년 인터넷/통신 인프라 붐 당시 가장 뜨거웠던 종목 중
  현재도 동일 티커로 생존한 6종목(CSCO·QCOM·EBAY·GLW·CIEN·AMZN — JDSU/PMCS/Sun
  Microsystems/Nortel 등 다수는 상장폐지/합병으로 yfinance에 이력이 없어 제외, 생존편향 명시)에
  같은 규칙 이식. 공통구간 1999-03~2002-12(EBAY 1998-09 상장이 병목)에서 모멘텀 로테이션(샤프
  0.88)이 추세추종 바스켓(0.30)·매수후보유(0.25)를 모두 큰 폭으로 이겨 IREN 패턴이 재현되지
  않았다. 순열검정 백분위 12.5(바스켓)/13.0(단일), p>0.87로 **무작위 날짜 셔플보다도 못한
  성과** — 대표종목 CSCO 전체이력 최대낙폭은 -89.3%로 크립토윈터 못지않게 극단적인 약세장이었음
  에도 이 규칙은 통하지 않았다.
- **6개 시대 종합표(작업27 IREN + 작업77 해운/대마초/태양광 + 이번 크립토윈터/닷컴버블)**: 추세
  추종이 매수후보유·로테이션을 모두 이기는 IREN 패턴이 재현된 시대는 정확히 절반(3/6: IREN·
  크립토윈터·태양광), 나머지 절반(해운·대마초·닷컴버블)은 미재현. 재현 여부와 "그 시대가 얼마나
  극단적인 약세장이었는가"(대표종목 전체이력 MDD) 사이엔 뚜렷한 상관관계가 없었다(크립토윈터
  -98.3% 재현 vs 닷컴버블 -89.3% 미재현) — 대신 재현된 3개는 종목 수가 적고 상관관계가 극단적
  으로 높은 바스켓(IREN 6종목 전부 동일 비즈니스모델, 크립토윈터는 사실상 2종목)인 반면 미재현된
  해운·닷컴버블은 종목 수가 비슷해도 업종 내 개별 기업 펀더멘털이 더 이질적이라는 패턴을 확인했다
  (단 대마초는 이 가설의 반례라 확정 규칙으로 승격하지 않고 가설로만 남김).
- **정직한 결론**: "표본기간이 짧아서 아직 결론을 못 내렸다"는 이전 라운드들의 완화된 표현을 이
  라운드가 스스로 정정한다 — 표본을 4.25년에서 최대 25년(닷컴버블 포함 1997~2026)까지 늘리고
  진짜 -90%대 낙폭의 극단적 약세장 2개를 포함시켜도 하나의 결론으로 수렴하지 않았다. 이건 통계적
  불확실성이 아니라 바스켓의 구조적 이질성(heterogeneity) 문제라는 게 더 정확한 설명이라고
  리포트가 명시한다. lottery-stock 긴장도 새 각도로 재확인 — 같은 MARA/RIOT가 2018년에 -90%대로
  거의 전부를 날렸다가 정확히 같은 추세추종 규칙으로 그 구간을 통과해 샤프 1.24를 낼 수 있었다는
  것은 "매수후보유로 복권을 쥐는 것"과 "규율 있는 청산으로 상승만 취하는 것"이 전혀 다른 위험
  조정수익률을 만든다는 걸 보여주지만, 닷컴버블에서는 같은 규율이 로테이션보다 못했다는 사실도
  동시에 남겨 긴장을 해소하지 않았다.
- **한계 명시**: MARA/RIOT 모멘텀 126거래일 웜업 구간 일부가 피벗 이전(특허관리회사/바이오텍 셸
  시절) 가격이력을 포함(같은 상장증권의 연속 거래이력이라 기술적으로는 유효하나 테마 순수성
  관점에서 완전하지 않음), 닷컴버블 바스켓의 생존편향(당시 가장 극적이었던 종목 다수가 제외됨),
  크립토윈터가 사실상 종목 2개뿐이라 "구조적 이질성" 가설도 표본이 작아 확정적이지 않음, 왕복
  0.1% 단순 비용모형을 1998~2002년에도 그대로 적용(당시 실제 비용은 더 높았을 가능성).
- 산출물: `analysis/2026-09-17_historical_era_trend_following_extension/`(`common_era.py`/
  `run_backtest.py`/`audit_stats.py`/`assemble_report_data.py`/`build_report.py`/
  `backtest_results.json`/`audit_results.json`/`report_data.json`/`final_report.html`), 사본을
  `docs/reports/historical_era_trend_following_extension_research.html`로 배치,
  `docs/reports/README.md` 트랙C에 No.7로 추가(요약+상세 블록 둘 다).
- `core/*.py`/`app/*.py` 무변경(신규 analysis 스크립트만 작성) — pytest 재실행 불필요.
- git commit/git push 없음(페르소나 지시대로 워킹트리에만 결과물을 남김 — 사용자가 직접 검토 후
  커밋).

### 작업 89 (2026-09-18, 무인 야간 실행 — 리서치 에이전트 C, 이번 세션): "오늘 기준 신규 후보
스캔" 미완성 라운드 완성 — 라이브 4팩터 스크리닝 + 4가지 독립 감사

`research_agents/agent_c_tenbagger.md` 페르소나의 이번 자동 실행. 시작 전 워킹트리를 점검하니
작업88이 명시적으로 남겨둔 미완성 산출물 `analysis/2026-09-17_live_tenbagger_screening_snapshot/`
(discover_run.py/valuation_check.py만 있고 미실행, "다음 라운드에서 마무리 가능"이라고 기록됨)를
발견 — 페르소나가 나열한 미해결 문제 중 "오늘 기준 신규 후보 스캔"과 정확히 일치해 이번 라운드의
본 작업으로 삼았다. 새로 계산 로직을 만들지 않고 이미 작성된 두 스크립트를 그대로 실행해 완성한
뒤, 페르소나가 요구하는 "최소 2~3개 가설 검증"을 충족하기 위해 조립 단계에서 감사 4개를 추가
설계했다.

- **실행 환경 이슈 2개 해결**: 시스템 `python3`이 아니라 저장소 `.venv/bin/python3`을 써야
  numpy 등 의존성이 잡힌다는 것, 스크립트를 모듈 경로 밖에서 실행하려면 `PYTHONPATH=/opt/quant`가
  필요하다는 것 — 둘 다 계산 로직과 무관한 실행 환경 문제였다.
- **스캔 실행**: `discover_run.py`가 `core.stock_discovery.discover_candidates()`를 새로 만들지
  않고 그대로 호출해 S&P500 503종목 전체(시총상한 없음)를 기본/모멘텀중심/퀄리티중심 3개
  가중치로, 그리고 핫섹터(정보기술+에너지) 필터로 스캔(총 158초, 캐시가 24시간 TTL을 넘겨 실제
  네트워크 재조회 — "오늘 시점" 주장에 부합). 이어서 `valuation_check.py`가 기본가중치 상위20에
  `tenbagger_stock_picking_research`(작업26)의 고든성장모형 공식을 그대로 재사용해 정당PER/PBR을
  역산.
- **이번 세션이 새로 설계한 4가지 감사(과거 백테스트가 아니라 횡단면 스냅샷이라 순열검정/
  블록부트스트랩이 적용 안 되므로 다른 종류의 검증 필요)**:
  - **H1(가중치 강건성)**: 3개 가중치 변형의 상위20 자카드 유사도(기본↔모멘텀중심 67%,
    기본↔퀄리티중심 43%, 모멘텀중심↔퀄리티중심 33%) — 3개 변형 전부에 공통인 종목이 정확히
    10개(상위20의 절반: ALL/APA/BBY/CF/CRM/INCY/MPC/OXY/TRV/VLO)로 완전한 노이즈는 아니지만
    가중치 선택이 결과의 절반 이상을 바꿈.
  - **H2(하향식 교차검증)**: `core.sector_strength.get_latest_theme_strength_snapshot()`(같은 날
    새벽 스케줄러가 이미 계산해둔 최신 스냅샷을 재계산 없이 그대로 사용)이 뽑은 오늘의 최강
    테마 5개(반도체>사이버보안>에너지>클라우드>기술, 정보기술 계열이 4자리)와 상향식 종합점수
    상위20의 실제 GICS 섹터 분포(에너지 8/20=40% 1위, 정보기술 2/20=10%)를 대조 — **정면으로
    어긋남을 처음 실측 확인**. 원인은 구조적: 하향식 RS점수는 순수 가격추세(ROC)만 보지만
    상향식 종합점수는 가치(25%)·퀄리티(15%) 팩터가 이미 많이 오른 반도체/클라우드 종목의 점수를
    깎기 때문 — "가장 뜨거운 테마"와 "가장 매력적인 개별종목 점수"가 이 저장소의 두 엔진 설계상
    다른 질문에 답한다는 걸 실측으로 처음 보였다.
  - **H3(밸류에이션 갭)**: 상위20의 **13/20(65%)이 g≥r로 고든모형 자체가 붕괴**(요구수익률
    9%를 지속가능성장률이 넘어서 정당PER/PBR 계산 불가) — ROE프록시(trailingEps/bookValue)가
    레버리지 높은 에너지·금융 업종에서 과대평가되는 구조적 원인으로 진단, 결측/실패를 완화 없이
    그대로 보고했다(트랙C 원칙). 살아남은 7종목 중 1종목(STT)도 g≈r로 수치적으로 불안정, 나머지
    6종목은 고평가 4·저평가 2로 일관된 방향 없음.
  - **H4(보너스, 시가총액 분포)**: 시총상한을 아예 걸지 않았는데도 상위20 전부가 $13.4B(SWK)~
    $414.4B(CVX) 대형주/메가캡 — $10B 미만 0종목, $2B 미만 0종목. 작업26의 텐베거 스크리닝이
    시총상한을 걸어 정보기술 섹터에서 0종목을 얻었던 구조적 한계를, 이번엔 상한 없이 순수
    팩터점수만으로도 그대로 재확인 — S&P500 유니버스가 이미 "크게 자란" 종목의 집합이라 이
    엔진은 IREN·CIFR류(트랙C No.2~7) 성격의 진짜 텐베거 후보를 원천적으로 걸러낼 수 없다.
- **정직한 종합**: 4개 감사 중 뚜렷하게 통과한 건 없다 — 강건성은 절반만, 교차검증은 불일치,
  밸류에이션은 대부분 적용 불가, 시가총액은 텐베거 후보군을 원천 배제. 오늘 이 엔진이 꼽은 상위
  종목(VLO/MPC/CF/TRV/ALL 등)은 "10배가 될 후보"가 아니라 실적·모멘텀·밸류에이션이 맞물린 대형
  에너지/금융주 로테이션 후보에 가깝다는 게 정직한 결론 — `discover_candidates()`는 "다음
  IREN을 찾는 도구"가 아니라는 설계 범위를 스스로 확인한 라운드. 승리로 포장할 구석 없는 결과.
- **한계 명시**: 단일 시점 스냅샷이라 날짜 간 안정성은 검증 안 함(가중치 간 비교만 수행).
  H2의 테마→GICS 매핑은 기존 근사 관례를 재사용한 수작업이라 완벽하지 않음. H3의 ROE 프록시는
  자사주매입·일회성손익·레버리지 차이를 구분 못해 모형 붕괴 비율이 과대평가됐을 가능성.
  discover_candidates()가 펀더멘털 데이터 전부 없는 종목을 조용히 제외하는데 그 제외 수를
  기록하지 않음(다음 라운드 보완 과제).
- 산출물: `analysis/2026-09-17_live_tenbagger_screening_snapshot/`(`discover_results.json`/
  `valuation_check.json`/`report_data.json`/`final_report.html` 신규 생성, `assemble_report_data.py`/
  `build_report.py` 신규 작성, 기존 `discover_run.py`/`valuation_check.py`는 무수정 실행), 사본을
  `docs/reports/live_stock_discovery_snapshot_research.html`로 배치, `docs/reports/README.md`
  트랙C에 No.8로 추가(요약+상세 블록 둘 다).
- `core/*.py`/`app/*.py` 무변경(신규 analysis 스크립트만 작성, 기존 스크립트는 실행만) — pytest
  재실행 불필요.
- git commit/git push 없음(페르소나 지시대로 워킹트리에만 결과물을 남김 — 사용자가 직접 검토 후
  커밋).


### 2026-09-18 — 고정 14일 프로토콜 Day 1 재개 검토 (DAY_1_BLOCKED)

Day 1만 검토했으며 아직 미완료다. 기존 증거 55개·데이터 20개의 해시 일치,
관련 테스트 6개 통과, 완료 요구 검사는 종료 코드 2로 보류를 확인했다.
합성 입력에서 기존 참고 코드의 다음 시가 체결 불일치와 미래 주식수/구성종목
fallback을 재현했다. S5 등 상세 사전명세, XLRE의 첫 표본외 구간 충돌,
S6 과거 시점 입력 출처가 해결되지 않아 완료 표식을 기록하지 않았다.
생성 파일 목록·개별/종합 데이터 해시·검증 결과는
`docs/experiment_validation/PROGRESS.md` 및
`docs/experiment_validation/day1_review_20260918T141530Z/`에 기록했다.
다음 감독은 그 디렉터리의 `RESUME_NOTE.md`에 따라 새 사전등록 근거부터
확인한다. 기존 후보·기준선·선택 게이트는 그대로이며 Day 2는 시작하지 않았다.

### 작업 90 (2026-09-19, 무인 야간 실행 — 리서치 에이전트 C, 이번 세션): 상관구조가 IREN 패턴
재현을 예측하는가 — 2개 신규 바스켓 사전등록 검증, "결과는 맞았지만 메커니즘은 틀렸다"

`research_agents/agent_c_tenbagger.md` 페르소나의 이번 자동 실행. 시작 전 페르소나가 나열한
"아직 안 풀린 문제" 4개(비-AI 대조군/옵션헤지이식/표본구간확장/라이브스캔)를 확인하니 전부 이미
작업77~89에서 완결돼 있었다 — 그래서 이번 라운드는 그 중 하나를 재탕하지 않고, 페르소나가 허용한
"README를 읽다가 스스로 발견한, 아직 다뤄지지 않은 질문"을 새로 골랐다.

- **문제의 정확한 소재**: historical_era_trend_following_extension(작업88)이 6개 독립 바스켓/시대
  (IREN·해운·대마초·태양광·크립토윈터·닷컴버블) 중 정확히 절반(IREN·크립토윈터·태양광)만 "돈치안20+
  15%트레일링스탑 추세추종이 매수후보유·로테이션을 모두 이긴다"는 패턴을 재현했다고 보고하며,
  "재현된 3개는 종목수가 적고 상관관계가 극단적으로 높은 바스켓, 미재현된 3개는 개별 기업 펀더멘털이
  이질적인 바스켓"이라는 가설로 재구성했다 — 단 "대마초는 이 가설의 반례라 확정 규칙으로 승격하지
  않고 가설로만 남긴다"고 스스로 명시했다. 이 가설은 ① 실제 상관계수를 한 번도 숫자로 계산한 적이
  없고 ② 사후 데이터 6개로만 관찰된 패턴이라 사전예측력이 검증된 적이 없다는 두 가지 빈틈이 있었다.
- **방법론**: 새 백테스트 로직을 발명하지 않고 작업27의 `donchian_trailing_stop_positions`/
  `run_trend_following_basket`/`run_trend_following_single`/`run_rotation`/`find_common_start`를
  그대로 import 재사용, 감사 기계도 작업77의 `audit_stats.py`(순열검정 200회+블록부트스트랩
  L=10/20/40·2000회) 구조를 그대로 재사용. **1단계**: 기존 6개 바스켓이 각자 실제로 쓴 티커·
  공통구간을 그대로 다시 로딩해(`correlation_metrics.py`) 일별수익률의 평균 쌍별 피어슨 상관계수를
  처음으로 숫자화. **2단계(이 라운드의 핵심 기여, 사전등록)**: 상관구조를 미리 예측한 2개 신규
  바스켓을 `basket_common2.py`에 백테스트 실행 **전에** `predicted_high_correlation`/
  `predicted_reproduce` 필드로 기록해뒀다 — EV SPAC 붐-버스트(WKHS/HYLN/LCID/PSNY, "2020-21
  SPAC붐으로 상장해 동일한 '양산지연→현금소진→증자' 실패각본을 공유하니 상관관계 HIGH → IREN
  패턴 재현" 예측)와 희귀질환 바이오텍 촉매주(SRPT/IONS/RARE/ALNY/BMRN, "각자 독립적인 FDA
  승인/임상결과 촉매로 움직이니 상관관계 LOW → 미재현" 예측). 후보 선정 과정에서 NKLA/RIDE/GOEV/
  FSR/MULN/FFIE(EV SPAC 동시대 종목, 전부 파산/상장폐지로 데이터 조회 실패)와 EXAS/FOLD/BLUE
  (야후 파이낸스에서 조회 실패)가 제외됐다는 것도 그대로 기록(결측을 숨기지 않음). scipy가 이
  환경에 없어 스피어만 순위상관·정확(exact) 순열검정을 `structural_hypothesis_test.py`에서 numpy로
  직접 구현(표준 정의 그대로, 새 통계량 발명 아님).
- **핵심 결과 — "결과는 맞았지만 메커니즘은 틀렸다"**: **결과(재현여부) 예측은 2개 바스켓 모두
  적중**했다(EV SPAC 재현: 추세추종바스켓 샤프−0.02 > 매수후보유−0.23·로테이션−0.51; 바이오텍
  미재현: 추세추종 0.06 < 매수후보유0.31·로테이션0.26). 하지만 **메커니즘(상관구조) 예측은
  절반만 맞았다** — 바이오텍은 예측대로 낮은 상관(0.356)이었지만, EV SPAC은 "동일 실패각본을
  공유하니 상관관계가 높을 것"이라는 예측과 정반대로 **8개 바스켓 전체에서 가장 낮은 평균상관
  (0.280, 크립토윈터 0.641·대마초 0.625 등보다 한참 낮음)**을 보이면서도 재현됐다. 순열검정으로
  비대칭이 더 드러난다 — EV SPAC의 "재현"은 53번째 백분위(p=0.47)로 무작위 셔플과 통계적으로
  구별 안 되는 잡음 수준의 승리였던 반면, 바이오텍의 "미재현"은 1번째 백분위(p=0.99, 무작위
  타이밍보다도 나쁨)로 이 트랙C 전체에서 가장 강하게 통계적으로 유의미한 "역효과"였다.
- **8개 통합 정식 검정**: 기존 6개만으로는 스피어만 ρ=0.7143로 꽤 강해 보였지만(그래도 n=6
  정확순열검정 p=0.5로 이미 관례적 유의수준 미달), 사전등록 신규 2개를 더하면 ρ=0.4286으로
  뚜렷이 약해지고, 재현군·미재현군(각 4개)의 평균상관 차이를 C(8,4)=70가지 조합 전수로 검정한
  정확 순열검정에서 백분위 62.86(양측 p=0.7714)로 우연과 통계적으로 구별되지 않는다.
- **정직한 등급**: 기각에 가까움(reversed 방향) — "상관구조가 IREN 패턴 재현을 예측한다"는
  가설은 사전등록 아웃오브샘플 검증을 통과하지 못했다. "결과가 예측과 맞았다는 사실만으로
  메커니즘 이해가 맞았다고 결론 내리면 안 된다"는 것을 이 라운드가 직접 증명한 사례로 기록 —
  EV SPAC의 2/2 결과 적중을 승리로 포장하지 않고, 그 적중이 잘못된 메커니즘 추론에서 나온
  우연에 가깝다는 것을 그대로 노출시켰다(트랙C 페르소나가 명시한 "가설별로 정직하게 점수를
  매긴다" 원칙 그대로 적용).
- **한계**: 신규 바스켓 2개도 "EV SPAC은 실패했다는 걸 안다, 바이오텍은 촉매가 이질적이라는 걸
  안다"는 사후지식으로 업종을 고른 것이라 완전한 블라인드 실험은 아니다(상관구조 예측 자체만
  사전등록됨). n=8은 스피어만·정확순열검정 모두에 여전히 얕은 검정력만 허용 — "관계가 없다"를
  확증한 게 아니라 "확신할 근거가 부족하다"는 게 정확한 해석. 평균 쌍별 상관계수 하나만 구조
  지표로 썼고(시간가변 상관관계·베타 이질성 등은 미검증), 두 신규 바스켓의 공통구간 길이가
  크게 다르다(EV SPAC 4.85년 vs 바이오텍 11.1년). 바이오텍의 극단적 역효과(1번째 백분위) 자체의
  메커니즘(휩쏘 가설)은 이 라운드가 추정만 하고 직접 검증하지 않음 — 다음 라운드 후보.
- 산출물: `analysis/2026-09-19_basket_correlation_structure_predictor/`(`basket_common2.py`/
  `run_backtest.py`/`correlation_metrics.py`/`structural_hypothesis_test.py`/`audit_stats.py`/
  `assemble_report_data.py`/`build_report.py`/`backtest_results.json`/`correlation_results.json`/
  `structural_hypothesis_results.json`/`audit_results.json`/`report_data.json`/`final_report.html`,
  전부 신규), 사본을 `docs/reports/basket_correlation_structure_predictor_research.html`로 배치,
  `docs/reports/README.md` 트랙C 요약목록+No.9 상세블록 둘 다 추가.
- `core/*.py`/`app/*.py` 무변경(신규 analysis 스크립트만 작성) — pytest 재실행 불필요.
- git commit/git push 없음(페르소나 지시대로 워킹트리에만 결과물을 남김 — 사용자가 직접 검토 후
  커밋).


### 2026-09-19 — 고정 14일 프로토콜 Day 2 완료

DAY_2_COMPLETE

`docs/experiment_validation/data_audit.md` 및 `day2/` 감사 산출물을 생성했다.
원본 증거 55개 해시 유지; ETF 20개 98,245행 내부 결측 0, XLRE 거래량 0인 5행은 보존하고
해당 시가 체결 차단, 기업행사·프록시·DST/거래소 달력·월말 248개 경계 감사 완료.
미래 발행주식수 fallback 차단/next-open 차이 검증 포함 관련 테스트 27개 통과.
데이터 22개 목록 SHA-256: `a8132c4441f818e47309dee4cbb93bb3067b18edc40371bda00679862fb6e86d`.
결과 증거 79개 목록 SHA-256: `4fd7ea3ced381b7e33957eccadf68cf653f7fad0f87be7d3d060d9a2cda6b2cc`.
생성 파일·개별 해시·검증 결과 전문은 `docs/experiment_validation/PROGRESS.md`,
`day2/audit_results.json`, `day2/input_manifest.json`, `day2/validation.json`에 기록했다.
후보·기준선·게이트 및 기존 미커밋 연구 보존, 판단 2건은 체크포인트 후 Telegram 보고했다.
다음 자동 감독은 Day 3만 수행: 기준선/S1~S5 비용 후 백테스트와 `baseline_metrics.csv`.
HYG 웜업 공백, zero-volume 시가 차단, 프록시 연결 비용, 정확한 다음 시가 체결을 준수한다.
Day 4의 S6 실제 PIT 입력 인증은 아직 수행하지 않았다. 게시 정보는 `day2/publication.json`.


### 2026-09-19 — 고정 14일 프로토콜 Day 3 완료

DAY_3_COMPLETE

기준선 3개와 S1~S5의 전 기간 5/10/25bp 비용 후 백테스트를 완료했다.
실제 17 ETF·장기 프록시·별도 5자산 표본을 분리한 63개 조합이며, 결과는
`docs/experiment_validation/baseline_metrics.csv`, 설명은 `day3_report.md`에 있다.
`day3/`에는 63쌍 일별 계좌/주문 gzip CSV, 3개 신호 로그, 표본/거래량 0 감사,
코드·실행 manifest·테스트·검증·개별 해시를 저장했다(전체 생성 파일 목록은 result_hashes.json).
관련 테스트 63개 및 게시 worktree의 63개 통과. 저장 파일 독립 재검증으로
54,606개 체결·228,360개 순자산 행 일치, 최대 상대오차 6.55e-15.
동일일 종가·다음 세션 위반·0거래량 체결 각각 0건; 프록시 보유 전환 양쪽 비용 확인.
데이터 22개 목록 SHA-256: `a8132c4441f818e47309dee4cbb93bb3067b18edc40371bda00679862fb6e86d`.
metrics CSV SHA-256: `57644d3e8fcbb4b0dda8dac10344e4f7b590f8a2d48c25df187ef72293cabcfd`.
증거 232개 목록 SHA-256: `eead5ea262341b40897f2ee627e5d6342f308cda46843eb9f50ff5723cd812e1`.
후보·기준선·게이트·기존 원본 해시와 미커밋 연구를 보존했다. 판단은 성과 조회 전
체크포인트/문서/즉시 Telegram 보고로 처리했다. 결과는 최종 전략 선택 판정이 아니다.
다음 자동 감독은 Day 4만: S6 실제 PIT 입력 인증 및 S1 공통 일자 비교,
`satellite_audit.md` 작성. Day 3 백테스트 재실행 불필요.
게시 브랜치 `research/day3-baseline-backtest-20260919`, 게시 확인은 `day3/publication.json`.


### 2026-09-19 — 고정 14일 프로토콜 Day 4 PIT 감사 보류

DAY_4_BLOCKED

S6 PIT 입력을 반기 40회·원본 식별자 949개·종목/시점 20,156건 감사했다.
미래에만 존재하는 주식수 8,521건, 주식수 없음/빈 캐시 531건을 확인했고
공개시각·과거 섹터·증권 식별자/단위·상장폐지 경로를 인증한 반기는 0개다.
현재 섹터 변경에 따른 과거 pool 변동, 체결일 종가를 시총 순위에 쓰는 경로,
미래 fallback 및 종가 근사의 next-open 불일치를 합성 입력으로 재현했다.
S6를 실행하지 않았고 S1 공통 비교 6개는 NOT_EVALUABLE로 남겼다. 완료 표식 없음.

생성 파일: `docs/experiment_validation/satellite_audit.md`, `day4_resolutions.md`,
`day4/`의 입력 manifest·캐시 목록·고정 관측치·종목/반기 누락표·원본 식별자 매핑,
코드/테스트/누수 재현 결과·비교 상태 CSV·검증 JSON·재개 문서.
전체 생성 파일 경로·개별 SHA-256은 `day4/result_hashes.json`에 기록했다.
검증: 78 tests passed(기존 63+신규 15), 게시 worktree에서도 78 passed;
저장 파일 독립 감사 PASS(20,156행), S1 저장 주문 4,551건의 다음 시가·비용 일치.
완료 요구 검사 종료 코드 2(BLOCKED); 기존 232개 증거 및 동결 데이터 22개 해시 유지.
동결 데이터 목록 SHA-256: `a8132c4441f818e47309dee4cbb93bb3067b18edc40371bda00679862fb6e86d`.
진단 입력 6개 목록 SHA-256: `691125e34c07b7a80ecafa717cf04bd30ffbd8b7cb28154206214d9c7b6b0cb8`.
결과 증거 268개 목록 SHA-256: `e2feee3b02da9fe7685224b6c32bbfedce83937289a87469f1f6a1e424de5e4c`.

판단은 체크포인트 `20260919T205729Z_day4-pit-certification` 후 문서화/즉시 Telegram 보고했다.
후보·기준선·게이트·원본 해시·기존 미커밋 연구는 보존했다. Day 3 미게시 증거는 별도
Day 4 브랜치의 의존 커밋 `6ea72a8`에 복사했고 기존 Day 3 worktree/index는 보존했다.
게시 브랜치: `research/day4-satellite-audit-20260919`; 원격 확인은 `day4/publication.json`.
다음 자동 감독은 Day 5로 넘어가지 않고 **Day 4 재개**: 공개시각을 검증할 수 있는
PIT 입력을 확보한 뒤 S6 다음 시가 재현/S1 공통 날짜 비교를 수행한다. 새 증거가 없으면
캐시 재수집·완료된 Day 3 백테스트 반복 금지. `day4/RESUME_NOTE.md`에 상세 명령을 남겼다.

Day 4 게시 확인: 증거 커밋 `81723b7db1e88e6f45a096619a7fc7b0ffdeae97`을
`origin/research/day4-satellite-audit-20260919`에 push하고 원격 SHA 일치를 확인했다.
보류 결과 Telegram 전송 성공. `day4/publication.json`에 기록했고 Day 4 미완료를 유지한다.


### 2026-09-20 — Day 4 재개: SEC 원천 확인, PIT 전체 인증 보류

DAY_4_BLOCKED

이전 Day 4 원천 1,548개와 증거 268개 해시를 확인했고 추가 로컬 PIT 자료는 찾지 못했다.
새 SEC 원문 3개를 확보해 A(Agilent) 주식수 70행 전체를 공시 accession에 연결했다.
관측일과 제출일은 70행 모두 다르고 수정 공시도 2행이다. 전체 모집단의 과거 섹터·공개시각·
증권 단위·상장폐지 입력은 여전히 미인증이므로 S6 재현과 S1 공통 비교는 미완료다.
완료 표식은 추가하지 않았고 Day 5를 시작하지 않았다.

산출물: `docs/experiment_validation/day4_review_20260920/`의 `review.md`,
SEC 원문 3개·조회 receipt·`input_manifest.json`·관측/공시 진단 JSON·소스/회귀 테스트,
`local_input_delta.json`, `validation.json`, `result_hashes.json`, `RESUME_NOTE.md`.
개별 경로·해시는 result_hashes.json(20개)에 기록했다. 신규/Day 4 회귀 30개 통과;
기존 독립 감사 PASS(20,156행, S1 저장 주문 4,551건), 완료 요구 종료 코드 2(BLOCKED).
데이터 22개 동결 목록 SHA-256: `a8132c4441f818e47309dee4cbb93bb3067b18edc40371bda00679862fb6e86d`.
신규 SEC 원문 3개 목록 SHA-256: `772532f5e1596d41be27fd268aca88d6384ef13e829e77c77a28dc4f538a958a`.
이번 결과 목록 파일 SHA-256: `030a176b498e30a1d870a44dbb38682663f49c22a435e7008258f0b1824ba694`.

CIK 정수/문자열 처리 결함은 체크포인트 `20260920T012004Z_day4-sec-cik-type` 후
문서화·즉시 Telegram 보고했다. 기존 결과/미커밋 연구·후보·기준선·게이트는 보존했다.
다음 자동 감독은 Day 4에 머물러 전체 선정 모집단의 과거 구성·섹터·증권/단위·공개시각 및
상장폐지 가격 자료를 확보한다. 이미 받은 SEC 파일이나 완료된 백테스트는 반복하지 않는다.
연구 브랜치 `research/day4-source-review-20260920`; 실제 게시 결과는 같은 폴더 `publication.json`.


### 2026-09-20 — Day 4 재개: 공식 과거 섹터 공지 원천 감사

DAY_4_BLOCKED

MSCI/S&P 공동 공지 PDF와 MSCI 기업별 변경 공지 HTML을 새로 확보했다. 미국 구간 62행을
독립 대조했고 섹터 코드 변경은 20행이다. MSCI 적용일과 S&P 적용일이 달라 이 목록을
S&P500 전체 과거 섹터로 편입하지 않았다. 전체 모집단 PIT/주식수 단위/상장폐지 입력은
여전히 미인증이다. S6 재현·S1 공통 비교 미완료, 완료 표식 없음, Day 5 미착수.

산출물: `docs/experiment_validation/day4_sector_sources_20260920/`의 `review.md`,
원문 2개(로컬만 보존), 조회 receipt 2개, `input_manifest.json`, `source_diagnostics.json`,
`usa_announced_code_changes.csv`, 파서/검증 코드·테스트·로그, `local_input_delta.json`,
`validation.json`, `result_hashes.json`, `RESUME_NOTE.md`. 전체 18개 경로/개별 해시는
`result_hashes.json`에 기록했다. 신규 11+기존 Day 4 15개 테스트 통과(26 passed).
신규 원문/CSV 독립 감사 PASS, 완료 요구 종료 코드 2(BLOCKED). 기존 증거 268+20개,
동결 데이터 22개, 기존 로컬 원천 1,548개 해시 유지. 기존 백테스트 재실행 없음.
동결 데이터 목록 SHA-256: `a8132c4441f818e47309dee4cbb93bb3067b18edc40371bda00679862fb6e86d`.
신규 원문 2개 목록 SHA-256: `0572bac5ba5f54e7f741c587ad5811f808ff0321454adf524ace6e488059c02b`.
결과 목록 파일 SHA-256: `b1b66242954f473d5858a8717686bde6a064f9c577387ca212d9cd6d7f75f6fa`.

새 전략 해석/기존 버그 수정 없이 기존 PIT 계약에 따라 원천만 감사했다. 후보·기준선·게이트,
기존 미커밋 작업은 보존했다. 다음 감독은 전체 S&P 구성/과거 섹터의 공개·유효시각과
증권/단위/상장폐지 가격 입력부터 확보한다. 새 자료가 없으면 이번 공지나 이전 SEC/캐시/
백테스트를 반복하지 않는다. 상세 명령은 해당 폴더 `RESUME_NOTE.md`, 게시 결과는
`publication.json`. 연구 브랜치 `research/day4-sector-sources-20260920`.


### 작업 91 (2026-09-20, 텔레그램 지시 후속): 관제 허브 실제 VM 배포 완료

작업77이 만든 `hub/` 모듈을 실제 VM(`138.2.11.196`)에 배포했다 — 작업77 자체는 코드만 만들고
`quant` 계정(sudo 없음)이 nginx/systemd를 못 건드려서 `deploy/PENDING_MANUAL_LOGIN_ACTIONS.md`
4번에 절차만 남겨뒀던 것을, 이번에 `ubuntu` 계정(sudo 가능)으로 직접 실행해 마무리함.

- `quant-hub.service` 설치·기동, `active (running)` 확인.
- 기존 `/etc/nginx/sites-enabled/quant-streamlit`(80번을 Streamlit에 직접 프록시하던, 저장소에
  없던 수동 설정) 제거 후 `deploy/nginx-quant.conf`로 교체 — `nginx -t` 통과 확인 후 reload.
  `http://138.2.11.196/`에서 관제 센터 카드 그리드 확인, `:8501` Streamlit 직접 접근도 그대로
  동작함을 확인(둘 다 curl로 200 확인).
- `deploy/auto_deploy.sh`의 `SERVICES`에 `quant-hub` 추가(그 전엔 설치 전 유닛이라 넣으면 자동배포
  스크립트가 `set -e`로 죽을 위험이 있어 의도적으로 미뤄뒀던 것 — 이제 설치가 끝나 안전해짐).
  이후 `hub/*.py` 변경도 자동배포 재시작에 포함된다.
- `PENDING_MANUAL_LOGIN_ACTIONS.md` 4번 항목을 완료로 정리.


### 작업 92 (2026-09-20): 브라우저 코드 스페이스(code-server) — 공개 대신 SSH 터널로 결정

허브의 "브라우저 코드 스페이스" 카드를 누르면 `ERR_CONNECTION_TIMED_OUT`이 나서 원인을 추적했다.

- Oracle VCN Security List(8080 규칙 정상), NSG(없음)는 통과했다. Codespace에서 포트별로 찔러보니
  22/80/8501은 열려 있고 8080만 막혔고, 8080 접속 시도 때 VM의 INPUT 체인 REJECT 카운터가 올라가서
  **VM 안의 iptables가 원인**임을 확정했다. Oracle 우분투 이미지의 기본 `REJECT`가 ufw 체인보다 앞에
  있어 `ufw allow 8080`은 효과가 없었다(22/80/8501은 REJECT 앞에 직접 ACCEPT를 넣어둔 것이라 통과).
- 고치려면 iptables에 ACCEPT를 넣어야 했는데, 이 IDE는 `sudo` 가능한 `ubuntu` 셸을 통째로 주고
  이 VM엔 TLS가 없어 HTTP+비밀번호 하나로 인터넷에 노출하게 되는 셈이라 **공개하지 않기로 결정**했다
  (사용자와 논의해 SSH 터널 선택).
- VM: code-server를 다시 `127.0.0.1:8080`에만 바인딩, ufw 8080 규칙 삭제.
- `hub/`: `AppSlot.kind`에 `tunnel` 추가 — 카드가 공개되지 않은 포트로 링크하지 않고 `/tunnel/<id>`
  안내 페이지(SSH 명령, PC와 Codespace Ports 탭 두 가지 접속법)를 보여준다. Host 헤더는 이스케이프.
- 문서(`DEPLOYMENT_ORACLE.md` 2·14번, `PENDING_MANUAL_LOGIN_ACTIONS.md` 5번)와 `setup_vm.sh`의
  8080 ufw/안내 문구를 결정에 맞게 정리하고, "ufw만으로는 이 VM에서 포트가 안 열린다"는 원인을 14번에 남겼다.
- 미해결(이번 범위 밖): `setup_vm.sh`는 80/8501도 ufw로만 여는데, 새 Oracle 우분투 VM에서는 같은
  이유로 안 열릴 가능성이 높다 — 신규 VM 부트스트랩 시 iptables ACCEPT 삽입이 필요할 수 있음.


### 작업 93 (2026-09-20): code-server를 HTTPS 주소로 공개 (작업 92 후속 — SSH 터널 → HTTPS)

작업 92에서 SSH 터널로 결정했지만 "Codespace를 먼저 열어야 한다"는 불편이 커서, 사용자와 논의해 **무료
DuckDNS 서브도메인 + Let's Encrypt**로 바꿨다.

- `deploy/setup_code_server_https.sh`(신규): DNS가 VM을 가리키는지 확인 → certbot 설치·발급(webroot,
  자동 갱신) → nginx 443 → `127.0.0.1:8080` 프록시(WebSocket 포함) → 443 허용. 실패 시 nginx 롤백.
  `hessejeong.duckdns.org`로 실행해 성공했고, VM 내부(TLS 검증 통과, 302→/login, http→https 301)와
  외부(Codespace에서 HTTPS 302→/login) 양쪽에서 동작을 확인했다. code-server는 계속 로컬 전용 바인딩.
- **발견**: VM엔 `iptables-persistent`/`netfilter-persistent`가 제거돼(`rc`) 있어서 부팅 때 `rules.v4`가
  복원되지 않는다 — 재부팅하면 수동 iptables 규칙이 사라지고 ufw가 방화벽이 된다. 그래서 443은
  iptables(즉시)와 ufw(재부팅 후) 양쪽에 넣었고, 스크립트도 그렇게 고쳤다. 작업 92·안내 중
  "netfilter-persistent save로 저장돼 있다"던 서술은 틀렸으므로 `DEPLOYMENT_ORACLE.md` 14번을 정정했다.
- `hub/`: 작업 92의 `tunnel` 종류와 안내 페이지는 카드가 더 이상 안 쓰는 죽은 코드가 돼 제거하고,
  `link` 종류(`url` 필드)로 대체 — code-server 카드가 HTTPS 주소를 새 탭으로 연다.
- 남은 위험: 비밀번호 하나가 곧 VM 셸이다(강한 24자 유지). DuckDNS는 무료 서비스라 드물게 불안정할
  수 있고 공인 IP가 바뀌면 DuckDNS에서 IP를 직접 고쳐야 한다(그때는 SSH 터널이 대안).

### 작업 94 (2026-09-20): 도메인 게이트웨이 — 기본 도메인에 관제 허브, 하위 앱은 하위 도메인으로

작업 93 뒤 사용자가 "`hessejeong.duckdns.org`로 들어가면 코드 스페이스만 나온다 — 컨트롤 타워를 여기에 두고
나머지 하위 항목도 이런 식으로 DNS로 들어가고 싶다"고 요청해서 구조를 바꿨다.

- `deploy/setup_gateway.sh`(신규, `setup_code_server_https.sh`를 대체·삭제): 인증서 한 장(`--cert-name`
  기본 도메인, `-d` 세 이름, `--expand`)으로 nginx 서버 블록 세 개를 만든다 —
  `https://<도메인>/`=관제 허브(127.0.0.1:8000, 아이디/비밀번호), `code.<도메인>`=code-server(8080, 자체 로그인),
  `app.<도메인>`=Streamlit(8501, 아이디/비밀번호, WebSocket 헤더). 등록 안 된 이름/IP로 온 HTTPS는
  `ssl_reject_handshake`로 거절, `http://<IP>/`는 기본 도메인으로 301. 방화벽 443(iptables REJECT 앞 삽입 +
  ufw)까지 스크립트가 처리해 단독으로 돌 수 있다. 비밀번호 파일(`/etc/nginx/.htpasswd-quant`)이 없거나
  비어 있으면 허브/앱을 로그인 없이 공개하지 않고 멈춘다 — 파일은 사람이 대화형으로 직접 만든다(비밀번호가
  대화·로그에 남지 않음). 사이트별 백업 후 실패 시 롤백, 재실행 안전(인증서는 재발급 안 함).
- 실 VM 적용 결과(외부 Codespace에서 확인): 기본 도메인 401(로그인 필요), `app.` 401, `code.` 302(→로그인),
  IP로 HTTPS는 핸드셰이크 거절, `http://IP/`는 301 → 기본 도메인. 첫 실행 때 기본 도메인 확인만 `000`이 나왔는데
  nginx reload 직후 경합이었고(재실행하면 정상), 확인 함수에 재시도를 넣었다. 기본 서버 listen에만 `http2`가
  빠져 nginx가 "protocol options redefined" 경고를 내던 것도 맞췄다(경고 사라짐).
- `hub/apps_registry.py`: 퀀트 대시보드 카드도 `kind="link"`(`https://app.<도메인>/`)로, code-server 카드는
  `https://code.<도메인>/`로. `tests/test_hub.py`: `web` 종류를 합성 슬롯으로 독립 검증, Streamlit이 HTTPS link
  슬롯이며 link 슬롯들의 주소가 서로 다름을 검증(전체 964 passed).
- 문서: `DEPLOYMENT_ORACLE.md` 8·13·14번(게이트웨이 구조, 비밀번호 파일 명령, 계정 교체, 옛 경로 닫기)과
  `PENDING_MANUAL_LOGIN_ACTIONS.md` 5번을 갱신.
- **남은 것**: (1) 브라우저에서 `app.` 로그인 + Streamlit 화면이 실제로 뜨는지(WebSocket 포함) 사람이 확인한
  뒤에 예전 `:8501` 직접 접속 경로를 닫는다(iptables + ufw + Oracle Security List) — 확인 전에 닫으면 되돌릴
  길이 없어 그대로 뒀다. (2) nginx basic auth에는 로그인 시도 제한이 없다 — 그래서 비밀번호를 강하게 두는 게
  유일한 방어다(필요하면 fail2ban이나 `limit_req` 추가 검토). (3) 아직 못 고친 구조 문제: VM 리서치 에이전트가
  루트 `PROGRESS.md`에 미커밋으로 덧붙여서 이 파일이 upstream에서 바뀔 때마다 자동배포의 `git pull --ff-only`가
  막힌다 — 이번에도 VM 쪽을 먼저 커밋·푸시한 뒤 이 항목을 올렸다(근본 해결은 별도 논의 필요).

### 작업 95 (2026-09-20): 게이트웨이 후속 — 옛 :8501 경로 닫기, 코드 스페이스 비밀번호를 외울 수 있게

작업 94를 사람이 브라우저로 확인하던 중 나온 세 가지를 처리했다.

- **"Page not found … Running the app's main page" 메시지**: 시스템 오류가 아니었다. nginx 접속 로그에 `/%EC%97%90`(에),
  `/%EB%8F%84`(도) 경로 요청이 남아 있었다 — 채팅 답변의 `` `https://app...org/`에 `` / `` `https://...org/`도 `` 처럼
  주소 바로 뒤에 붙은 한글 조사가 복사되면서 주소 끝에 붙은 것. Streamlit은 없는 페이지 경로면 그 안내를 띄우고 메인 페이지를
  실행한다(로그로 인증 401→200과 정상 응답 확인). 허브(`/도`)는 그냥 404. 앞으로 안내할 때 주소는 조사와 떨어뜨려 단독 줄에 적는다.
- **옛 `http://<IP>:8501` 직접 접속 닫음**: iptables의 8501 ACCEPT 규칙과 `ufw allow 8501/tcp`(v4/v6)를 삭제했고, 밖에서
  연결이 안 되는 것과 `https://` 세 주소·22/80/443 규칙이 그대로임을 확인했다. 런타임 코드 중 `:8501`이나 IP를 직접 링크하는
  곳은 없음을 먼저 확인(텔레그램 알림/브리핑 등). `setup_vm.sh`는 더 이상 8501을 열지 않고 게이트웨이 안내로 바꿨고,
  `setup_gateway.sh` 종료 안내·`nginx-quant.conf` 주석·`DEPLOYMENT_ORACLE.md`의 8501 개방 안내를 정리했다.
- **코드 스페이스 로그인 키를 외울 수 없음**: code-server 비밀번호가 자동 생성된 24자 랜덤이라 매번 찾아 붙여야 했다.
  `deploy/set_code_server_password.sh`(신규, 사람이 직접 대화형으로 실행): 비밀번호를 두 번 입력받아(화면 표시 없음, 명령줄·로그에
  안 남음) 12자 이상·공백/작은따옴표/ASCII 아닌 글자를 뺀 영문/숫자/기호만 허용하고(4자리 숫자 같은 건 거절) 설정 파일의 `password:` 한 줄만 바꾼 뒤
  재시작 → 새 비밀번호로 로그인이 되는지 확인 → 안 되면 자동 복구. 소유자/권한(600) 유지, 백업은 성공/실패 뒤 삭제.
  `tests/test_set_code_server_password.py` 22개(입력 검증, 기호 비밀번호의 YAML 왕복, 다른 설정 보존, 비밀번호 미출력,
  로그인 확인 실패 시 롤백). **첫 배포판은 영문/숫자/`.`/`_`/`-`만 허용해 사용자가 `!`를 넣었다가 거절당했다** — 허용 범위를
  넓히고(로그인 확인도 `--data-urlencode`로 바꿔 `&`·`+`·`%` 같은 기호가 안전), 거절 시 문제 글자의 *종류*(공백/따옴표/한글/제어문자,
  글자 자체는 미출력)를 알려주게 했다.
- **완료(2026-09-20 14:57 UTC)**: 사람이 `ssh -t quant-vm 'sudo bash /opt/quant/deploy/set_code_server_password.sh'`를 직접
  실행해 비밀번호를 정했다(값은 보지 않음 — 설정 파일 수정·code-server 재시작·권한 600·임시/백업 파일 없음·헬스 OK만 확인).
- **남은 것**: Oracle 콘솔의 8501/8080 Ingress 규칙은 아직 남아 있지만 OS 방화벽이 막고 있어 무해 —
  지우면 한 겹 더 안전. nginx 로그인 시도 제한 부재와 VM `PROGRESS.md` 자동배포 충돌 문제는 작업 94 그대로 미해결.

### 작업 96 (2026-09-20): 자동배포가 VM의 미커밋 PROGRESS.md 때문에 막히던 문제를 구조적으로 해결

작업 94·95에서 "미해결"로 남겼던 문제. VM의 리서치 에이전트/실험 슈퍼바이저가 루트 `PROGRESS.md` 끝에 미커밋으로 기록을 덧붙이고
개발 쪽 커밋도 같은 파일에 항목을 추가해서, 원격이 이 파일을 바꿀 때마다 `git pull --ff-only`가 막혀 자동배포가 통째로 멈췄다
(그때마다 VM에서 손으로 커밋·리베이스·푸시). 이 세션에서도 작업 95 기록 커밋이 이 문제에 걸려 배포가 멈춰 있었다.

- `deploy/progress_reconcile.sh`(신규, `auto_deploy.sh`가 source): **(a) VM의 PROGRESS.md가 미커밋 수정 상태이고 (b) 새 커밋도 이 파일을
  바꿀 때만** 동작한다 — ① 로컬 파일을 바이트 단위로 확인한 백업(`.auto-deploy-state/PROGRESS.local.*`, 최근 10개)으로 보존 ② 이 파일 하나만
  HEAD로 되돌려 pull 통과 ③ 백업의 로컬 추가분을 새 upstream 위에 `git merge-file --union` 3-way 병합으로 다시 얹음(양쪽이 파일 끝에 덧붙여도
  충돌 마커 없이 둘 다 남고, 같은 줄이면 하나만 남음). 결과적으로 VM 파일은 "새 upstream + 아직 커밋 안 된 VM 기록"이라 에이전트가 계속 이어 쓴다.
  로컬 내용은 어떤 경우에도 버려지지 않는다: pull이 다른 이유로 실패하면 백업에서 원상 복구, 병합이 실패하면 배포는 계속하되 백업 위치와 함께
  텔레그램 알림. 겹치지 않거나 다른 파일의 로컬 수정이 막는 경우는 예전과 같다(전자는 무동작, 후자는 즉시 포기+알림). `auto_deploy.sh`의 비파괴 원칙
  주석과 `DEPLOYMENT_ORACLE.md` 12번에 이 좁은 예외와 근거를 명시.
- `tests/test_progress_reconcile.py` 10개(진짜 git 저장소 3개로 재현): 양쪽 끝 추가, 중간 삽입+끝 추가, 연속 두 번 배포, 안 겹칠 때 무동작, 로컬이 깨끗할 때,
  다른 파일이 pull을 막을 때 정확한 복원, 병합 실패 시 백업 보존, 백업 정리(이 테스트가 임시 파일 이름이 백업 패턴과 겹치는 실제 버그를 잡음),
  `auto_deploy.sh`에서의 호출 순서(특히 `pull_status=$?` 직후 복원). 로컬(git 2.53)과 VM(git 2.43) 양쪽에서 통과.
- **부트스트랩**: 수정 커밋이 올라간 시점에 VM이 이미 미커밋 상태여서 예전 스크립트로는 이 수정 자체를 pull할 수 없었다(닭과 달걀). 새 함수를 그대로
  VM에서 한 번 수동 실행해 풀었다 — 미커밋 추가분 25줄 보존, 충돌 마커 0, 백업 생성, HEAD == origin/main 확인. 그 다음 이 항목의 푸시가 실제 자동배포
  경로의 첫 검증이다.
- **한계**: 이렇게 VM에만 있는 에이전트 기록은 누군가 커밋·푸시하기 전까지 GitHub에는 없다(VM 디스크가 사라지면 함께 잃음) — 필요하면 VM 기록을 주기적으로
  커밋·푸시하는 별도 절차를 논의해야 한다. nginx 로그인 시도 제한 부재도 그대로.
- **Oracle 콘솔의 8501/8080 Ingress 규칙(작업 95 남은 것)**: 이 Codespace의 OCI CLI(`~/.oci`)로 지우려 했으나 API 키가 Oracle에서 401(`NotAuthenticated`)로
  거절된다(시계 오차 0.1초, 설정 지문과 키 파일은 일치 → 키가 삭제/비활성된 것으로 추정). 키 복구도 콘솔 작업이라, 규칙 두 줄은 사람이 콘솔에서 직접 지운다
  (OS 방화벽이 이미 막고 있어 안 지워도 무해).

### 작업 97 (2026-09-21): 운영 안정화 — VM 백업, 밤사이 작업 관측, 워치독, 외부 감시, 노출 축소, 실험 일시정지

"다른 해결할 사항/디벨롭할 것" 요청으로 VM을 읽기 전용으로 점검했고(가동 4주, 실패 유닛 0, 디스크 22%), 실제 문제로 확인된 것들을 처리했다.

- **점검에서 나온 사실**: 백업이 전혀 없음(DB 340KB + 미커밋 연구 산출물 ~270MB가 디스크 한 대에만 있음) · 잡 실행 이력 테이블이 없어 야간 작업 성공 여부를 볼 곳이 없음 ·
  VM 밖 감시가 없음 · Streamlit이 `0.0.0.0:8501`에 바인딩(방화벽 한 겹에만 의존) · 쓰지 않는 rpcbind(111)가 외부 바인딩 · 실험 슈퍼바이저가 4시간마다 Claude를 깨워
  **누적 97회 실행**했는데 완료 프로토콜은 3일뿐(Day 4는 시점 정합 데이터가 없어 `DAY_4_BLOCKED` 반복) · SSH 실패 시도 하루 1,061건(키 전용이라 소음) · nginx에 **비밀번호 틀린 시도 0건**
  (401 377건은 로그인 없는 스캔) → fail2ban은 급하지 않다고 정정.
- **백업**(`deploy/backup_vm.py`, `quant-backup.timer` 매일 06:30 KST, `setup_backup.sh`): sqlite 온라인 백업(무결성 검사) + git상 미커밋 파일 중 **허용 목록**(analysis/, docs/, .experiment-control/ 등)만.
  점(.) 폴더(Claude/Codex 인증, SSH 키, .env …)는 구조적으로 제외, 허용 폴더 안의 비밀 의심 파일명/내용은 격리+알림, 90MB 초과·체크포인트 tar.gz는 건너뜀. 로컬 git 저장소(`/opt/quant-backup/repo`)에 버전 이력으로 쌓고,
  `remote` 파일에 **비공개** 저장소 URL이 있으면 전용 배포 키로 push. **이 저장소(Quant)는 공개**라서 백업을 여기 올릴 수 없다 — 별도 비공개 저장소가 필요한데 Codespace 토큰으로는 만들 수 없어 사람이 만들어야 한다.
  VM에서 실행 확인: 1,284개 파일 147MB, 20초, DB 사본 integrity ok, 자격 증명 파일명 0개, 비공개 원격은 미설정(브리핑에 경고로 표시).
- **밤사이 작업 관측**: `scheduler_job_runs` 테이블 + APScheduler 리스너(`core/job_health.py`; 잡 함수는 하나도 안 고침), `core/job_schedule.py`(16개 잡 스케줄 표 — `main()`의 실제 등록과 일치하는지 테스트가 강제),
  판정(ok/error/missed/overdue/pending/disabled/no-history), 오늘의 브리핑에 "운영 상태" 섹션(문제 있으면 맨 위+빨강). 테스트 중 "기록이 있어도 추적 시작 시점보다 늦으면 no-history로 분류"하던 논리 결함을 발견해 고침.
  한계: 잡이 내부에서 예외를 삼키면 ok로 남는다. 추적은 첫 야간 실행(00:00 KST)부터 쌓이므로 배포 직후엔 이력 없음이 정상.
- **워치독**(`deploy/watchdog.py`, `quant-watchdog.timer` 매일 09:05 KST): 스케줄러와 독립(stdlib)으로 잡 이력/error·missed/브리핑 생성/백업 상태를 보고 **문제가 있을 때만** 텔레그램. 브리핑도 스케줄러 안 잡이라 "브리핑이 안 옴"을 스스로 알릴 수 없기 때문.
- **외부 감시**(`.github/workflows/uptime.yml`, 30분마다): DNS→IP, 세 주소의 응답(401/401/302), 인증서 남은 기간, 닫아둔 포트(8501/8080/8000)가 밖에서 열려 있지 않은지. 실패하면 GitHub 이메일/앱 알림, 텔레그램은 시크릿을 추가하면 선택적으로.
  점검 스크립트를 로컬에서 실제 주소로 돌려 정상(오탐 없음)과 강제 실패(감지됨) 양쪽 확인. 토큰 권한상 수동 실행은 못 해서 첫 실제 러너 실행은 스케줄/Actions 탭 버튼으로 확인해야 한다.
- **노출 축소(VM 적용 완료)**: Streamlit을 `127.0.0.1` 전용으로(유닛 변경·재시작, `app.` 경유 정상 확인), rpcbind 중지·비활성(의존 유닛/NFS 없음 확인). 외부 리스너는 이제 22/80/443뿐.
- **실험 일시정지**: `.experiment-control/control.json`의 mode를 paused로(텔레그램 `/experiment pause`와 같은 파일·형식; 실행 중이던 1회는 끝까지 마치고 새 실행만 막힘). 재개는 `/experiment resume`.
  데이터가 없는 채로 4시간마다 Claude를 소모하던 것을 멈춘 것이며, (a) PIT 데이터 확보 (b) 가능한 데이터 범위로 실험 재정의는 사용자 결정으로 남김.
- **처리하지 않은 것과 이유**: yfinance `Invalid Crumb` 401(하루 3회) — VM이 이미 최신 1.7.0이라 업그레이드로 해결 불가, Yahoo 쪽 일시 오류라 조치 없음. 재부팅(커널 업데이트 대기, 모든 서비스 enabled·ufw 22/80/443 허용이라 위험은 낮음) —
  부팅 실패 시 내가 복구할 수단이 없어(OCI CLI 키가 401) 사람이 Oracle 콘솔에 접근 가능할 때로 미룸. 공인 IP가 Reserved인지도 콘솔에서 사람이 확인.
- **작업 중 발견**: 이 작업 공간에서 다른 세션/에이전트가 동시에 파일을 수정 중이었다(AGENTS.md, core/trade_ledger.py 등 미커밋) — 내 커밋에는 내 변경만 담고(파일별 증감 줄 수로 확인) 그쪽 파일은 건드리지 않았으며, 리베이스 대신 병합으로 푸시했다.
- **사람이 할 일**: Oracle 콘솔 8501/8080 Ingress 규칙 삭제(오후 예정) · Reserved IP 확인 · 비공개 백업 저장소 생성 + 배포 키 등록 + `/opt/quant-backup/remote` 설정(`DEPLOYMENT_ORACLE.md` 15번) · 재부팅 시점 결정.

### 작업 98 (2026-09-21): 운영 안정화 2차 — 검증되는 백업, 조용한 실패 보강, 배포 성공 알림의 정직성

작업 97 뒤 "보강할 것을 제안하고 다시 하라"는 요청. 근거는 이번에 VM에서 새로 확인한 것들이다. 상태는 제안/구현/검증/배포로 구분해 적는다.

**근거(확인한 사실)**: (1) 백업이 "써졌다"만 알 뿐 "복구된다"는 아무도 확인하지 않음 (2) 잡 16개 중 예외를 내부에서 삼키는 것이 3개(뉴스 다이제스트·FRED 예열·꺼진 야간 튜닝)라
실패해도 APScheduler엔 ok (3) 재부팅 필요 표시(커널 보안 업데이트 1020, 실행 중 1018)가 **2026-08-24부터 28일째** 방치 (4) 자동배포가 재시작 **직후** 곧바로 "성공"을 알려 새 코드가 기동에서 죽어도 성공으로 보고됨
(5) VM에 `docs/reports/README.md` 미커밋 69줄(에이전트가 파일 안 3곳에 색인을 끼워 넣음) — `PROGRESS.md`처럼 upstream이 그 파일을 건드리면 자동배포가 멈출 유형 (6) 인증서 자동 갱신은 한 번도 리허설한 적 없음.

| 항목 | 구현 | 단위 테스트 | VM 검증 | VM 배포 |
|---|---|---|---|---|
| 백업 검증(MANIFEST sha256 + DB 무결성 + git fsck; 실패 시 실패로 치고 push 안 함) + 원격 HEAD 확인 | 완료 | 완료 | 배포 뒤 실행 확인 필요 | 자동배포 대기 |
| 7일 1회 복구 리허설(원격이 있으면 원격, 없으면 로컬을 새로 클론해 검증) | 완료 | 완료(손상된 백업 감지 포함) | 위와 같음 | 자동배포 대기 |
| 소프트 실패 보고(`report_job_failure`, status=failed가 이후 ok보다 우선) — 뉴스·FRED | 완료 | 완료 | 다음 야간/07:30 KST 실행 뒤 확인 | 자동배포 대기 |
| 워치독: 재부팅 방치 14일 알림, 일요일 주간 생존 신호, failed를 오류로 집계 | 완료 | 완료 | 첫 실행은 2026-09-22 09:05 KST | 자동배포 대기 |
| 자동배포: 재시작 뒤 서비스 active·헬스·재시작 루프 확인 후에만 "성공" (`post_deploy_check.sh`) | 완료 | 완료(스텁 systemctl/curl, 순서 검증) | **실제 배포로만 검증 가능** — 이 커밋을 처리하는 배포는 옛 스크립트라 다음 배포부터 적용 | 다음 배포부터 |
| 기록 파일 병합 일반화(`RECONCILE_FILES`: PROGRESS.md + docs/reports/README.md) | 완료 | 완료(기존 10 + 신규 4) | 다음에 그 파일이 upstream에서 바뀔 때 | 자동배포 대기 |
| 인증서 자동 갱신 리허설 | 코드 없음(명령 한 번) | 해당 없음 | **완료: 세 도메인 모두 시뮬레이션 성공** | 해당 없음 |

- 테스트: 전체 1,198개 통과(다른 세션의 미완성 `tests/test_candidate_ledger.py`는 제외 — `core.candidate_ledger` 모듈이 아직 없어 수집 오류, 이 작업과 무관).
- **하지 않은 것과 이유**: 자동 재부팅(부팅 실패 시 사람이 콘솔에서 복구해야 하는데 이 세션은 OCI CLI 키가 401이라 복구 수단이 없음 → 방치 알림만) · 자동 롤백(비파괴 원칙) · fail2ban(nginx에 틀린 비밀번호
  시도 0건, SSH 키 전용) · yfinance 업그레이드(VM이 이미 최신 1.7.0) · 비밀 백업(암호화 방식은 사용자 비밀번호가 필요해 제안만 — 아래).
- **제안(미구현, 사용자 결정 필요)**: (a) 비밀(nginx 로그인, code-server 비밀번호, .env, 텔레그램 토큰, Claude/Codex 로그인)의 **암호화 백업** — 지금은 일부러 백업에서 제외돼 디스크 소실 시 전부 재설정해야 한다. 사용자가 기억할
  passphrase로 암호화해 비공개 저장소에 두는 방식을 검토할 수 있다. (b) 공인 IP가 Ephemeral이면 DuckDNS 자동 갱신 스크립트(토큰 필요). (c) 실험 재개 여부(PIT 데이터).
- **사람이 할 일(변동 없음)**: 비공개 백업 저장소 + 배포 키 + `/opt/quant-backup/remote`(15번), Reserved IP 확인, 재부팅 시점 결정.

### 작업 99 (2026-09-22): 선택형 암호화 비밀 백업 + Oracle 확인 마무리

작업 98 뒤 사용자에게 남은 두 가지(비공개 백업 저장소 연결, 공인 IP Reserved 여부)를 확인했고, 세 번째 제안(비밀 암호화 백업)을 사용자
동의로 구현했다.

- **확인된 것**: 비공개 백업 저장소(`quant-vm-backup`) 연결 완료 — VM에서 원격 HEAD와 로컬 HEAD 일치 확인(사람이 직접 push 실행, "비공개
  저장소 push 성공" 확인). 공인 IP는 **Ephemeral로 확인**됐고, 사용자가 "무료 티어라 VM을 Stop할 이유가 없다"며 **Reserved 전환을 보류**하기로
  결정(재부팅은 Stop이 아니라서 이 결정과 무관 — 영향 없음). 재부팅 자체는 아직 미실행.
- **비밀 암호화 백업**(`deploy/backup_vm.py`의 `backup_secrets()`, opt-in): `/opt/quant-backup/secrets_passphrase` 파일(사람이
  `deploy/set_backup_passphrase.sh`로 대화형으로만 만듦 — 이 스크립트도 시스템도 절대 자동 생성하지 않음)이 있을 때만 nginx 로그인·code-server
  비밀번호·`.env`·텔레그램 봇 토큰·Claude/Codex 로그인 세션을 파일별로 `openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt`로 암호화해
  `repo/secrets/<라벨>.enc`로 함께 백업한다. 암호화 직후 그 자리에서 복호화해 원문과 바이트 단위로 같은지 확인하고, 하나라도 실패하면 그 회차
  전체를 실패로 치고 밖으로 올리지 않는다(기존 `verify_backup`/복구 리허설과 같은 원칙). 이 VM에 없는 항목(Codex 로그인 등)은 조용히 건너뛴다.
- **passphrase의 정직한 한계**: `secrets_passphrase` 파일은 백업 *대상*(`/opt/quant`) 밖에 있어 수집 대상에 절대 섞이지 않고 백업 저장소에도
  안 올라간다 — "저장소가 뚫려도 안전"은 지켜진다. 하지만 "VM 디스크가 통째로 사라지는 경우"까지 막으려면 같은 passphrase를 사람이 따로
  보관해야 한다는 걸 사용자에게 명시했다(잊으면 아무도 복구 못 함). `set_backup_passphrase.sh`는 20자 이상만 요구하고 그 외 문자 제한이
  없다(값이 셸에 끼워 넣어지지 않고 파일로만 저장돼 공백·한글도 안전) — 저장 직후 실제 암복호화 왕복까지 확인한 뒤에만 남긴다.
- `stored_path()`를 `secrets/` 접두사까지 일반화해 기존 `verify_backup()`(MANIFEST sha256 대조)이 별도 코드 없이 비밀 백업의 변조도 그대로 잡는다.
- 테스트: `tests/test_backup_vm.py`에 9개(6종 전부 암복호화 왕복, 없는 파일은 조용히 건너뜀, 사라진 비밀의 옛 암호문 정리, 평문 트리에 안 섞임,
  변조 감지, 틀린 passphrase로 복호화 불가, 왕복 실패 시 전체 회차 중단+미push, 빈 passphrase 파일은 미설정으로 취급), `tests/test_set_backup_passphrase.py`
  9개(성공/거부/공백·한글 허용/미출력/`backup_vm.py`와 openssl 파라미터 교차 호환 확인), `tests/test_backup_status.py` 2개(브리핑 표시 줄).
  전체 `pytest tests`(다른 세션의 미완성 `tests/test_candidate_ledger.py` 제외) 1,382건 통과.
- **사람이 할 일**: `ssh -t quant-vm 'sudo bash /opt/quant/deploy/set_backup_passphrase.sh'`로 passphrase를 정하고(선택), 같은 값을 본인이
  따로 보관. 재부팅 시점 결정은 그대로 남음.

### 2026-09-20 — Day 4 전체 모집단 입력 인계 및 접근 경로 확인

DAY_4_BLOCKED

기존 진단표의 20,156개 종목/시점·949개 원본 식별자·40개 반기 경계를 손실 없이
조회 요청 파일로 옮겼다. 구성/섹터/주식수/증권 단위/상장폐지 가격의 필요 필드와
공식 공급 경로를 문서화했다. 공식 접근 문서 3개를 받았으나 실제 PIT 데이터는
확보하지 못했다. 인증 반기/공통 날짜 0개, S1/S6 비교 6개 NOT_EVALUABLE 유지.
S6 재현 미실행, 완료 표식 없음, Day 5 미착수. 반복 Day 3 백테스트 없음.

산출물: `docs/experiment_validation/day4_input_handoff_20260920/`의 `input_request.md`,
`requested_member_keys.csv.gz`, `requested_boundaries.csv`, `requested_identifiers.csv`,
생성/독립 검증 코드·테스트·로그, 입력 manifest·출처 receipt·로컬 delta·검증 JSON,
`review.md`, `RESUME_NOTE.md`, `result_hashes.json`. 개별 경로/해시 16개는 결과 목록에 있다.
원문 3개·이전 파일 백업은 로컬만 보존한다. 신규 9+기존 15개 테스트 **24 passed**;
20,156행 및 거래소 경계 독립 대조 PASS, 완료 요구 종료 코드 2(BLOCKED).
기존 증거 268+20+18개, 동결 데이터 22개와 원천 1,548개 해시 유지; 기존 파일 415개 보존.
동결 데이터 목록 SHA-256: `a8132c4441f818e47309dee4cbb93bb3067b18edc40371bda00679862fb6e86d`.
요청 CSV 3개 목록 SHA-256: `7022f50842f1af8c3a1f44920bdcacd8f9e850fd9114ed76369e27b2b2589b0e` (PIT 전략 데이터 아님).
결과 목록 파일 SHA-256: `ee8b83c8458fa3f62dc7b5b0910e4b014f64e77bd61d3fd20cda4bdae00d78cc`.

후보·기준선·게이트·전략 해석 변경 없음. 다음 자동 감독은 Day 4에 머물러 실제 PIT
export 또는 기존 데이터 경로부터 확인한다. 새 자료 없이는 이번 패키지/기존 단일 종목·공지
수집을 반복하지 않는다. 입력 인증 후 S6 5/10/25bp 다음 시가 재현과 S1 공통 비교를 수행한다.
연구 브랜치 `research/day4-input-handoff-20260920`; 실제 게시 결과는 `publication.json`.


### 2026-09-20 10:47 UTC — Day 4 재개 입력 변화 확인

DAY_4_BLOCKED

신규 PIT 자료 유무를 로컬 데이터 파일 3,470개에서 확인했다. 직전 인계 뒤 갱신된
SPY/VIX 가격 캐시 2개는 구성·섹터·공시시각 입력이 아니므로 실험에 편입하지 않았다.
인증 반기/공통 거래일 0개, S1/S6 비교 6개 NOT_EVALUABLE 유지. S6 재현 미실행,
완료 표식 없음, Day 5 미착수. 새 해석/코드 변경 및 반복 백테스트 없음.

생성 파일: `docs/experiment_validation/day4_reentry_20260920T1047Z/`의 `review.md`,
`RESUME_NOTE.md`, `local_scan.csv.gz`, `local_input_delta.json`, `initial_workspace.json`,
`tests.log`, `validation.json`, `result_hashes.json`. 기존 원천 1,548개, 동결 22개,
이전 증거 목록 268+20+18+16개 해시 일치. 기존 누수/체결/허위 완료 방지 테스트
**15 passed**, 저장 비교 상태 가드 PASS; 실제 S6 실행 통과는 아니다.
동결 데이터 목록 SHA-256: `a8132c4441f818e47309dee4cbb93bb3067b18edc40371bda00679862fb6e86d`.
결과 목록 파일 SHA-256: `738936c67d5a1c8193e67b991d655801df902e5f0c1efbc14f9e38bebcff5a50` (개별 생성 파일 해시 포함).

다음 감독은 실제 PIT 데이터 경로 또는 신규 export를 확보하고 입력 계약부터 인증한다.
새 자료 없이는 동일 수집/요청 생성/백테스트를 반복하지 않는다. 상세 명령은 이번
`RESUME_NOTE.md`, 게시 확인은 `publication.json`. 연구 브랜치
`research/day4-reentry-20260920T1047Z`. 후보·기준선·게이트와 기존 작업은 보존했다.
