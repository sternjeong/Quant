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
