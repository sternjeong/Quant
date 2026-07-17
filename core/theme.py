"""Notion 스타일 다크 테마(CSS) 주입.

앱의 모든 페이지 파일에서 `st.set_page_config()` 직후에 `apply_theme()`을
호출해야 페이지 이동 시에도 배경/글자색이 끊기지 않는다.

라이트 모드는 지원하지 않는다 — 항상 다크모드로 고정한다(사용자 요청).
"""

import html
import json

import streamlit as st
import streamlit.components.v1 as components

_DARK = {
    "bg": "#191919",
    "bg_secondary": "#202020",
    "text": "#e9e9e7",
    "border": "#2f2f2f",
    "accent": "#529cca",
}

_FONT = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, '
    '"Apple SD Gothic Neo", "Noto Sans KR", Arial, sans-serif'
)


def apply_theme() -> None:
    c = _DARK

    st.markdown(
        f"""
        <style>
        .stApp {{
            background-color: {c['bg']};
            font-family: {_FONT};
        }}

        /* 최상단 헤더/툴바(streamlit 기본 크롬)도 다크로 강제 */
        header[data-testid="stHeader"], div[data-testid="stAppHeader"],
        div[data-testid="stToolbar"], div[data-testid="stAppToolbar"],
        div[data-testid="stDecoration"] {{
            background-color: {c['bg']} !important;
        }}

        div[data-testid="stMainMenu"] svg,
        div[data-testid="stAppDeployButton"] svg,
        div[data-testid="stToolbar"] svg,
        div[data-testid="stAppToolbar"] svg {{
            fill: {c['text']} !important;
        }}

        .stApp, .stApp p, .stApp li, .stApp label, .stApp span,
        h1, h2, h3, h4, h5, h6 {{
            color: {c['text']} !important;
        }}

        section[data-testid="stSidebar"] {{
            background-color: {c['bg_secondary']};
            border-right: 1px solid {c['border']};
        }}

        a {{ color: {c['accent']} !important; }}

        div[data-testid="stMetric"], div[data-testid="stDataFrame"],
        div[data-testid="stExpander"] {{
            border: 1px solid {c['border']};
            border-radius: 8px;
        }}

        hr {{ border-color: {c['border']}; }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    render_gemini_usage_badge()


def render_gemini_usage_badge() -> None:
    """우측 상단에 Gemini API 키 설정 여부/오늘 사용량을 작은 배지로 표시한다.

    Google 무료 티어는 "남은 할당량"을 조회하는 API를 제공하지 않는다 — 그래서 정확한 잔여 한도
    대신, core.gemini_client.generate_content()가 시도할 때마다 스스로 기록해온(GeminiCallLog)
    오늘의 시도/성공/한도초과(429) 횟수를 근사치로 보여준다. apply_theme()에서 자동 호출되므로
    페이지마다 따로 부를 필요는 없다.
    """
    from core import gemini_client

    if not gemini_client.has_api_key():
        label = "🔑 Gemini 키 없음"
        color = "#8a8a8a"
        tooltip = "GEMINI_API_KEY(S)가 설정되지 않았습니다 — 자연어 전략 해석 등은 키워드 기반 대체 로직으로만 동작합니다."
    else:
        usage = gemini_client.get_usage_today()
        if usage["last_status"] == "quota_exceeded":
            label = f"⚠️ Gemini 오늘 {usage['total']}회 (한도 근접)"
            color = "#e5533d"
        elif usage["quota_exceeded"] > 0:
            label = f"🔑 Gemini 오늘 {usage['total']}회 (한도초과 {usage['quota_exceeded']}건)"
            color = "#d9a441"
        else:
            label = f"🔑 Gemini 오늘 {usage['total']}회"
            color = "#4caf82"
        tooltip = (
            f"설정된 키 {usage['configured_keys']}개 · 성공 {usage['ok']} · "
            f"한도초과(429) {usage['quota_exceeded']} · 기타오류 {usage['error']}\n"
            "Google 무료 티어는 정확한 잔여 한도를 조회할 수 없어, 이 앱이 자체 기록한 오늘 시도 "
            "횟수를 근사치로 보여줍니다."
        )

    # 마크다운의 HTML 블록 인식은 여는 태그 자체가 한 줄에 있어야 안정적으로 동작한다 — style/title
    # 속성이 여러 줄에 걸치면(들여쓰기 있는 줄은 markdown이 코드블록으로 오인) 브라우저에 아예
    # 렌더링되지 않는 경우가 있어(AppTest에선 정상, 실제 브라우저에선 DOM에 아예 안 잡힘, 확인됨),
    # 태그 전체를 한 줄로 압축하고 tooltip의 개행도 HTML 개행 엔티티로 치환한다.
    badge_style = (
        f"position:fixed;top:0.6rem;right:7.5rem;z-index:999999;"
        f"background:rgba(32,32,32,0.9);border:1px solid {color};color:{color};"
        f"font-size:0.72rem;padding:2px 9px;border-radius:10px;"
        f"font-family:{_FONT};white-space:nowrap;cursor:default;"
    )
    safe_tooltip = html.escape(tooltip).replace("\n", "&#10;")
    st.markdown(
        f'<div title="{safe_tooltip}" style="{badge_style}">{html.escape(label)}</div>',
        unsafe_allow_html=True,
    )


# TradingView 다크 테마 팔레트 (차트 전용). 캔들 색(#26a69a/#ef5350)은 각 페이지의
# go.Candlestick 트레이스에서 이미 이 값을 쓰고 있으므로 여기서는 배경/그리드/모드바만 다룬다.
TRADINGVIEW_CHART_BG = "#131722"
TRADINGVIEW_CHART_GRID = "#2a2e39"
TRADINGVIEW_CHART_TEXT = "#d1d4dc"
TRADINGVIEW_ACCENT = "#2962ff"

# 추세선/사각형/원/자유선 등 도형 그리기 버튼 + 데이터 선택용(box/lasso select, OHLC와 무관) 버튼 제거.
# scrollZoom=True 는 휠 확대/축소용 (dragmode="pan"과 별개로 항상 켜둠).
# edits.shapePosition=True 는 dragmode가 "pan"이어도(그리기 도구를 다시 켜지 않아도) 이미 그린 도형을
# 클릭해 꼭짓점을 드래그로 옮기거나 크기를 바꿀 수 있게 한다. 클릭으로 선택된 도형은 Delete/Backspace
# 키로 삭제할 수 있다(Plotly 내장 동작).
TRADINGVIEW_CHART_CONFIG = {
    "scrollZoom": True,
    "displaylogo": False,
    "modeBarButtonsToAdd": [
        "drawline",
        "drawopenpath",
        "drawclosedpath",
        "drawcircle",
        "drawrect",
        "eraseshape",
    ],
    "modeBarButtonsToRemove": ["lasso2d", "select2d"],
    "edits": {"shapePosition": True},
}


def style_chart_like_tradingview(fig):
    """캔들차트의 배경/그리드/폰트/모드바를 TradingView 다크 테마와 비슷하게 맞춘다.

    `TRADINGVIEW_CHART_CONFIG`와 함께 `st.plotly_chart(fig, config=TRADINGVIEW_CHART_CONFIG)`로 써야
    도형 그리기 버튼(추세선 등)까지 완성된다 (config는 fig가 아니라 st.plotly_chart 호출 시 별도 인자).
    """
    fig.update_layout(
        paper_bgcolor=TRADINGVIEW_CHART_BG,
        plot_bgcolor=TRADINGVIEW_CHART_BG,
        font=dict(color=TRADINGVIEW_CHART_TEXT, family=_FONT),
        modebar=dict(
            orientation="v",
            bgcolor="rgba(30,34,45,0.85)",
            color=TRADINGVIEW_CHART_TEXT,
            activecolor=TRADINGVIEW_ACCENT,
        ),
        newshape=dict(line_color=TRADINGVIEW_ACCENT, line_width=1.5),
    )
    fig.update_xaxes(
        gridcolor=TRADINGVIEW_CHART_GRID, zerolinecolor=TRADINGVIEW_CHART_GRID, linecolor=TRADINGVIEW_CHART_GRID,
        # 주말엔 거래가 없어 봉이 비므로, 토/일 구간을 아예 축에서 건너뛰어 빈 공백이 안 보이게 한다.
        rangebreaks=[dict(bounds=["sat", "mon"])],
    )
    fig.update_yaxes(gridcolor=TRADINGVIEW_CHART_GRID, zerolinecolor=TRADINGVIEW_CHART_GRID, linecolor=TRADINGVIEW_CHART_GRID)
    return fig


# core.market_regime.historical_regime_segments()의 결과를 아무 Plotly Figure에나 겹쳐 그리기 위한
# 배경색(반투명) — 국면 판단 자체과 무관한 순수 표시용 색이라 캔들 상승/하락색(#26a69a/#ef5350)과
# 톤은 맞추되 투명도를 낮게(0.10~0.14) 줘서 위에 그려지는 선/캔들을 가리지 않게 함.
REGIME_SHADE_COLORS = {"강세장": "rgba(38,166,154,0.10)", "약세장": "rgba(239,83,80,0.14)"}


def add_regime_shading(fig, segments_by_regime: dict) -> None:
    """국면별(강세장/약세장) 연속 구간을 배경 음영(add_vrect)으로 겹쳐 그린다.

    x축이 일반 날짜 타입(date/datetime)인 차트에만 쓸 수 있다 — 10_차트_조회.py처럼 x축을
    category(문자열 라벨)로 바꾼 차트는 vrect 좌표계가 달라 그대로 못 쓴다(이번 범위 밖).
    segments_by_regime은 core.market_regime.historical_regime_segments()의 반환값 형태
    ({"강세장": [(시작일, 종료일), ...], "약세장": [...]})를 그대로 받는다. "중립" 구간은 표시하지
    않는다(항상 존재해 화면이 지저분해지는 것을 피하기 위함).
    """
    for label, color in REGIME_SHADE_COLORS.items():
        for seg_start, seg_end in segments_by_regime.get(label, []):
            fig.add_vrect(x0=seg_start, x1=seg_end, fillcolor=color, line_width=0, layer="below")


# 커스텀 Streamlit 컴포넌트 없이 st.components.v1.html의 srcdoc iframe으로 우회해 그리기 도구를
# TradingView처럼 보강한다. 이 iframe의 sandbox 속성에 allow-same-origin이 포함돼 있어(streamlit
# 프론트엔드 번들 IFrameUtil에서 직접 확인) `window.parent.document`/`window.parent.Plotly` 접근이
# 가능하고, `window.Plotly`가 부모 창에 전역 노출되는 것도 PlotlyChart 번들에서 확인했다.
# 이 스크립트가 하는 일 3가지:
#   1) 도형(추세선 등)을 다 그리면 dragmode를 자동으로 "pan"으로 되돌린다 — Plotly는 그리기 도구를
#      쓰면 dragmode가 그 도구로 고정돼 하나 그린 뒤에도 계속 그리기 모드로 남는데, TradingView는
#      하나 그리면 자동으로 커서/이동 모드로 돌아온다. `plotly_relayout` 이벤트에서 dragmode가
#      "draw"로 시작하면서 실제로 도형이 생겨난(이벤트 키가 "shapes"로 시작) 경우에만 되돌린다 —
#      기존 도형의 꼭짓점을 드래그하는 동작(edits.shapePosition)은 dragmode가 이미 "pan"인 채로
#      일어나므로 이 조건에 걸리지 않아 서로 간섭하지 않는다.
#   2) 그린 도형을 티커별로 브라우저 localStorage에 저장해뒀다가, 봉 주기·지표 변경 등으로 Streamlit이
#      매번 도형 없는 새 figure를 서버에서 만들어 보낼 때 자동으로 복원한다. x축이 갭 없는 카테고리
#      축(주말/공휴일/장외시간 제거용)이라 Plotly는 도형의 x0/x1을 실제 날짜가 아니라 "몇 번째
#      카테고리인지"를 나타내는 정수 인덱스로 관리한다 — 이 인덱스는 봉 주기가 바뀌면(카테고리 배열
#      자체가 통째로 바뀌므로) 완전히 다른 날짜를 가리키게 된다. 그래서 저장할 때는 인덱스를 그
#      시점의 실제 카테고리 라벨(날짜 문자열)로 변환해 저장하고, 복원할 때는 그 날짜 문자열을 현재
#      차트의 카테고리 배열에서 가장 가까운 날짜의 인덱스로 다시 찾아 변환한다 — 이렇게 해야 봉
#      주기가 바뀌어도 도형이 실제 날짜/가격 기준으로 올바른 자리에 나타난다(요청한 "스케일에 맞춰
#      유지"). y0/y1(가격)은 애초에 인덱스가 아닌 실제 값이라 변환이 필요 없다. 복원 조건은 "현재
#      차트에 도형이 0개이고 저장된 도형이 있을 때"뿐이라 사용자가 직접 전부 지운 경우(저장소도 즉시
#      빈 배열로 갱신됨)와 충돌하지 않는다. path 타입(자유 곡선) 도형은 x0/x1이 아니라 SVG path
#      문자열을 쓰므로 이 변환 대상이 아니다(추세선/사각형/원만 정확히 재배치됨).
#   3) 도형을 클릭하면 차트 좌하단에 작은 원형 색상 선택기를 띄워 그 도형의 선 색을 바로 바꿀 수 있게
#      한다. "클릭된 도형이 몇 번째인지"는 Plotly의 내부 상태(`_activeShapeIndex` 등)로는 알 수 없다
#      — 실제로 확인해보니 이 앱이 쓰는 Plotly 버전은 도형을 클릭해도 그 값이 갱신되지 않는다(반면
#      꼭짓점 드래그 자체는 내부 상태 없이도 잘 동작함, 독립적인 minimal Plotly 재현으로 직접 확인).
#      대신 Plotly가 모든 편집 가능한 도형마다 항상 그려두는, 클릭 판정 전용 투명 오버레이
#      `<g drag-helper="true" data-index="N">`를 document 클릭 이벤트에서 직접 찾아 그 도형의
#      인덱스를 읽는다 — 이건 비공식 내부 필드가 아니라 항상 렌더링되는 DOM 구조라 Plotly 버전이
#      바뀌어도 상대적으로 안정적이다. 색상 선택기 DOM은 안정적인 id로 재사용해(스크립트가 리런마다
#      다시 실행돼도) 중복 생성되지 않게 한다.
_CHART_INTERACTIONS_JS = """
<script>
(function() {
  var doc = window.parent.document;
  var storageKey = "qtv_chart_shapes_" + __TICKER_JSON__;

  function categoryLabels(gd) {
    return (gd._fullLayout && gd._fullLayout.xaxis && gd._fullLayout.xaxis._categories) || [];
  }
  function parseLabel(label) {
    var t = new Date(String(label).replace(" ", "T")).getTime();
    return isNaN(t) ? null : t;
  }
  function indexToLabel(gd, idx) {
    var cats = categoryLabels(gd);
    if (!cats.length) return idx;
    var i = Math.max(0, Math.min(cats.length - 1, Math.round(idx)));
    return cats[i];
  }
  function labelToIndex(gd, label) {
    var cats = categoryLabels(gd);
    var target = parseLabel(label);
    if (!cats.length || target === null) return null;
    var bestIdx = 0, bestDiff = Infinity;
    for (var i = 0; i < cats.length; i++) {
      var t = parseLabel(cats[i]);
      if (t === null) continue;
      var diff = Math.abs(t - target);
      if (diff < bestDiff) { bestDiff = diff; bestIdx = i; }
    }
    return bestIdx;
  }
  function toPortable(gd, shapes) {
    return (shapes || []).map(function(shape) {
      var copy = Object.assign({}, shape);
      if (typeof copy.x0 === "number") copy.x0 = indexToLabel(gd, copy.x0);
      if (typeof copy.x1 === "number") copy.x1 = indexToLabel(gd, copy.x1);
      return copy;
    });
  }
  function fromPortable(gd, shapes) {
    return (shapes || []).map(function(shape) {
      var copy = Object.assign({}, shape);
      if (typeof copy.x0 === "string") { var i0 = labelToIndex(gd, copy.x0); if (i0 !== null) copy.x0 = i0; }
      if (typeof copy.x1 === "string") { var i1 = labelToIndex(gd, copy.x1); if (i1 !== null) copy.x1 = i1; }
      return copy;
    });
  }

  function loadShapes() {
    try {
      var raw = window.parent.localStorage.getItem(storageKey);
      return raw ? JSON.parse(raw) : [];
    } catch (e) { return []; }
  }
  function saveShapes(shapes) {
    try {
      window.parent.localStorage.setItem(storageKey, JSON.stringify(shapes || []));
    } catch (e) {}
  }

  var picker = null;
  function ensurePicker() {
    if (picker) return picker;
    picker = doc.getElementById("qtv-shape-color-picker");
    if (picker) return picker;
    picker = doc.createElement("input");
    picker.type = "color";
    picker.id = "qtv-shape-color-picker";
    picker.title = "선택한 도형의 선 색상 변경";
    var s = picker.style;
    s.position = "fixed"; s.zIndex = "999999"; s.width = "26px"; s.height = "26px";
    s.border = "2px solid #2962ff"; s.borderRadius = "50%"; s.cursor = "pointer";
    s.padding = "0"; s.display = "none"; s.boxShadow = "0 1px 4px rgba(0,0,0,0.5)";
    doc.body.appendChild(picker);
    return picker;
  }

  function showColorPicker(gd, idx) {
    var shapes = gd.layout.shapes || [];
    if (!shapes[idx]) return;
    var p = ensurePicker();
    var rect = gd.getBoundingClientRect();
    p.style.left = (rect.left + 12) + "px";
    p.style.top = (rect.bottom - 40) + "px";
    p.style.display = "block";
    var color = (shapes[idx].line && shapes[idx].line.color) || "#2962ff";
    if (/^#[0-9a-fA-F]{6}$/.test(color)) p.value = color;
    p.oninput = function() {
      var update = {};
      update["shapes[" + idx + "].line.color"] = p.value;
      window.parent.Plotly.relayout(gd, update);
    };
  }
  function hideColorPicker() {
    if (picker) picker.style.display = "none";
  }

  // Plotly가 도형 클릭 시 내부적으로 노출하던 "활성 도형 인덱스" 상태(예: _activeShapeIndex)는
  // 버전마다 있다가 없다가 하는 비공식 내부 필드라 신뢰할 수 없다(실제로 이 앱이 쓰는 Plotly
  // 버전에서는 클릭해도 값이 갱신되지 않음을 직접 확인함 — 대신 꼭짓점 드래그는 내부 상태 없이도
  // 잘 동작함). 그 대신 Plotly가 각 도형마다 항상 그려두는, 클릭 판정용 투명 오버레이
  // `<g drag-helper="true" data-index="N">`를 클릭 시점에 DOM에서 직접 찾아 그 도형의 인덱스를
  // 알아낸다 — 이 마크업은 Plotly 내부 상태가 아니라 항상 렌더링되는 실제 DOM 구조라 더 안정적이다.
  // 이 iframe(및 그 안의 클로저)은 봉 주기·티커 등을 바꿔 Streamlit이 리런할 때마다 통째로
  // 새로 만들어졌다가 버려진다 — 그런데 "이미 설치했는지" 플래그를 parent document 쪽에 남겨두는
  // 방식(예: doc.__qtvClickBound = true 후 다시는 안 붙임)으로 짜면, 리스너 자체는 iframe이
  // 사라질 때 브라우저가 자동으로 떼어내 버리는데 플래그만 살아남아 "이미 붙어있다"고 착각해
  // 다음 리런에서 재설치를 건너뛰는 버그가 생긴다(직접 겪어서 확인함 — 클릭 이벤트가 조용히
  // 아무 반응이 없었음). 그래서 매번 이전 리스너를 명시적으로 떼어내고 새로 붙인다.
  function installClickHandler() {
    if (doc.__qtvClickHandler) {
      doc.removeEventListener("click", doc.__qtvClickHandler, true);
    }
    var handler = function(e) {
      if (picker && e.target === picker) return;
      var helper = e.target && e.target.closest && e.target.closest("g[drag-helper]");
      if (helper) {
        var gd = helper.closest(".js-plotly-plot");
        var idx = parseInt(helper.getAttribute("data-index"), 10);
        if (gd && !isNaN(idx)) { showColorPicker(gd, idx); return; }
      }
      hideColorPicker();
    };
    doc.__qtvClickHandler = handler;
    doc.addEventListener("click", handler, true);
  }

  function bind(gd) {
    if (!gd || typeof gd.on !== "function" || gd.__qtvBound) return;
    gd.__qtvBound = true;
    gd.on("plotly_relayout", function(eventData) {
      if (!eventData) return;
      var dragmode = gd.layout && gd.layout.dragmode;
      var isDrawMode = typeof dragmode === "string" && dragmode.indexOf("draw") === 0;
      var touchesShapes = Object.keys(eventData).some(function(k) { return k.indexOf("shapes") === 0; });
      if (isDrawMode && touchesShapes) {
        window.parent.Plotly.relayout(gd, {dragmode: "pan"});
      }
      saveShapes(toPortable(gd, gd.layout.shapes || []));
    });
  }

  function tick() {
    doc.querySelectorAll(".js-plotly-plot").forEach(function(gd) {
      bind(gd);
      if (!gd.layout || !categoryLabels(gd).length) return;
      var current = gd.layout.shapes || [];
      if (current.length === 0) {
        var saved = loadShapes();
        if (saved.length > 0) {
          window.parent.Plotly.relayout(gd, {shapes: fromPortable(gd, saved)});
        }
      }
    });
  }

  installClickHandler();
  tick();
  setInterval(tick, 400);
})();
</script>
"""


def inject_chart_interactions(ticker: str) -> None:
    """차트 그리기 도구 인터랙션 보강: 그리기 후 자동 pan 복귀 + 도형 localStorage 영속화(티커별) +
    선택한 도형의 선 색상 변경용 플로팅 컬러피커.

    `st.plotly_chart(fig, config=TRADINGVIEW_CHART_CONFIG)` 호출 직후에, 그 차트가 표시 중인 티커를
    넘겨서 호출해야 한다.
    """
    script = _CHART_INTERACTIONS_JS.replace("__TICKER_JSON__", json.dumps(ticker))
    components.html(script, height=0)
