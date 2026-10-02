"""챔피언 전략 페이지 (신규, 2026-09-12).

`analysis/2026-09-05_research_program_synthesis/`가 49개 작업·26개 이상의 리포트(순열검정/블록
부트스트랩/국면분해/워크포워드 등으로 감사됨)를 종합해 도출한 코어+새틀라이트 자산배분 결론을,
그동안 정적 HTML 리포트 안에만 머물러 있던 것에서 꺼내 "오늘 기준" 라이브 추천으로 보여준다.

핵심 로직(랭킹/시장필터/브레이크아웃 스캔)은 core/champion_strategy.py, 이 파일은 화면 구성만 담당.
새 전략을 여기서 만들지 않는다 — 확신도가 낮은(weak/reversed) 구성요소도 숨기지 않고 그대로 노출한다.
"""

import sys
from datetime import date
from pathlib import Path
from typing import Optional

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 (app/pages/*.py 공통 규칙) ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import champion_recommendation as cr
from core import job_manager
from core.backtest_engine import compute_drawdown_series, compute_monthly_returns
from core.champion_strategy import (
    CORE_UNIVERSE,
    CORE_WEIGHT,
    SATELLITE_DONCHIAN_STOP_PCT,
    SATELLITE_DONCHIAN_WINDOW,
    SATELLITE_WEIGHT,
    compute_champion_correlation,
    compute_core_recommendation,
    compute_live_collar_state,
    compute_satellite_recommendation,
    compute_satellite_recommendation_point_in_time,
    get_current_holdings,
    get_upcoming_earnings,
    list_champion_correlation_snapshots,
    load_confidence_table,
    load_final_config,
    load_rejected_ideas,
    load_research_meta,
    run_champion_backtest,
    run_champion_backtest_with_collar,
    save_champion_correlation_snapshot,
    send_weekly_report,
)
from core.db import init_db
from core.guru_tracker import find_gurus_holding_ticker, get_synced_guru_names
from core.market_data import get_price_history
from core.portfolio import get_cash_balance, get_portfolio_pnl
from core.theme import (
    apply_theme,
    render_drawdown_chart,
    render_metric_card,
    render_monthly_returns_heatmap,
    render_status_bar,
    style_chart_like_tradingview,
)
from core.ui_status import render_status_header

init_db()

st.set_page_config(page_title="챔피언 전략", page_icon="🏆", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()

st.title("🏆 챔피언 전략")
render_status_header("champion")

meta = load_research_meta()
st.caption(
    f"이 저장소가 지금까지 진행한 리서치 프로그램({meta.get('n_work_items', '?')}개 작업, "
    f"{meta.get('n_reports', '?')}개 이상 리포트)을 종합해 도출한 코어+새틀라이트 배분을 '오늘' "
    "시장 데이터에 그대로 적용한 라이브 추천입니다. 새 전략을 여기서 만들지 않습니다 — 확신도가 "
    "낮은(weak/reversed) 구성요소도 숨기지 않고 그대로 보여줍니다."
)
render_status_bar(
    [
        ("ENGINE", "LOCAL"),
        ("AS OF", date.today().isoformat()),
        ("CORE UNIVERSE", f"{len(CORE_UNIVERSE)} ASSETS"),
        ("SATELLITE UNIVERSE", "S&P500"),
    ]
)

# ----------------------------------------------------------------------------
# 거장 포트폴리오 교차참조 배지 (2026-09-14 추가) — 순수 참고 정보, 새 신호가 아니다.
#
# [4_거장_포트폴리오]에서 추적 중인 투자자/펀드가 코어 top4/새틀라이트 추천 종목과 같은 종목을
# 들고 있으면 캡션 하나로만 알려준다. 이 종목이 좋다는 뜻도, 이 엔진의 배분 근거도 아니다 —
# core/guru_tracker.find_gurus_holding_ticker()가 순수 조회만 하고 배분 로직은 건드리지 않는다.
# 동기화된 거장이 하나도 없으면(get_synced_guru_names() 비어있음) 아무것도 표시하지 않는다.
# ----------------------------------------------------------------------------
_SYNCED_GURU_COUNT = len(get_synced_guru_names())


def _guru_cross_ref_caption(ticker: str) -> Optional[str]:
    if _SYNCED_GURU_COUNT == 0:
        return None
    gurus = find_gurus_holding_ticker(ticker)
    if not gurus:
        return None
    if len(gurus) == 1:
        return f"🏛️ {gurus[0]}도 보유 중"
    return f"🏛️ {gurus[0]} 등 {len(gurus)}명의 추적 대상도 보유 중"


if _SYNCED_GURU_COUNT > 0:
    st.caption(
        "🏛️ 배지: [4_거장_포트폴리오]에서 추적 중인 투자자/펀드도 같은 종목을 보유 중이라는 "
        "참고 정보입니다 — 이 종목이 좋다는 뜻이 아니며 배분에도 반영되지 않습니다."
    )

_GRADE_BADGE = {"robust": "🟢 robust", "moderate": "🔵 moderate", "weak": "🟡 weak", "reversed": "🔴 reversed"}


def _page_link(path: str, label: str) -> None:
    """st.page_link — 내비게이션 밖(AppTest 등)에서 실행되면 링크 대신 안내 문구만 남긴다
    (app/pages/14_챔피언_성과.py 의 같은 헬퍼와 동일)."""
    try:
        st.page_link(path, label=label, width="stretch")
    except Exception:  # noqa: BLE001 - 내비게이션 컨텍스트가 없을 때(KeyError/StreamlitAPIException)
        st.caption(label)


# 차트 색 — app/pages/14_챔피언_성과.py 와 같은 팔레트(다크 표면용 범주 팔레트)를 그대로 쓴다.
_C_STRATEGY = "#3987e5"
_C_SPY = "#d95926"
_C_SAT = "#d55181"
_C_REF = "#9aa0a6"  # 참고선(12개월 전 가격) — 중립 회색


# ----------------------------------------------------------------------------
# 종목 차트 (2026-10-02 추가) — '지금 할 일' 카드에서 종목을 누르면 그 종목만 가격을 받아 그린다.
# 이 전략에는 지정가·목표 매수가가 없다. 규칙이 쓰는 기준값만 선으로 긋고 '몇 불에 사라'는 만들지 않는다.
# ----------------------------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner=False)
def _chart_history(ticker: str, as_of: str) -> Optional[pd.DataFrame]:
    """as_of 는 캐시 키용(날짜가 바뀌면 새로 받는다). 실패하면 None — 예외는 캐시되지 않는다."""
    return cr.fetch_chart_history(ticker, today=date.fromisoformat(as_of))


def _render_ticker_chart(ticker: str, *, sleeve: str, plan_row: Optional[dict],
                         evidence_row: Optional[dict], evidence_as_of: Optional[str]) -> None:
    with st.spinner(f"{ticker} 가격을 불러오는 중..."):
        df = _chart_history(ticker, date.today().isoformat())
    if df is None:
        st.info(f"{ticker} 가격 데이터를 불러오지 못했습니다(네트워크·데이터 소스 문제일 수 있습니다). 잠시 뒤 다시 눌러 보세요.")
        return
    lv = cr.entry_chart_levels(df["Close"], sleeve, evidence_row=evidence_row, evidence_as_of=evidence_as_of)
    view = df.tail(252)  # 약 1년만 그린다(기준값 계산은 받은 전체로)

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=view.index, open=view["Open"], high=view["High"], low=view["Low"], close=view["Close"],
        name=ticker, increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        hovertemplate="%{x|%Y-%m-%d}<br>종가: $%{close:,.2f}<extra></extra>",
    ))
    _line_style = {
        "last": (_C_STRATEGY, "solid"), "breakout": (_C_SAT, "dash"),
        "stop": (_C_SPY, "dot"), "momentum_ref": (_C_REF, "dash"),
    }
    for level in lv["levels"]:
        color, dash = _line_style.get(level["key"], (_C_REF, "dot"))
        fig.add_hline(
            y=level["price"], line=dict(color=color, width=1.4, dash=dash),
            annotation_text=f"{level['label']} ${level['price']:,.2f}", annotation_position="top left",
            annotation_font=dict(color=color, size=11),
        )
    fig.update_layout(
        height=360, margin=dict(l=8, r=8, t=28, b=8), showlegend=False,
        xaxis_rangeslider_visible=False, yaxis_title="가격($)",
        title=dict(text=f"{ticker} 일봉(약 1년) · {sleeve}", font=dict(size=13)),
    )
    style_chart_like_tradingview(fig)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False},
                    key=f"champion_todo_chart_{ticker}")

    lines = [f"**현재가 ${lv['last_close']:,.2f}** ({lv['last_date']} 종가)"]
    if plan_row is not None and lv["last_close"]:
        amt = abs(float(plan_row["delta_value"]))
        est = cr.estimate_shares(amt, lv["last_close"])
        if plan_row["action"] == "유지":
            lines.append("주문 목록상 지금 사고팔 것 없음(목표와 1%p 이내).")
        elif est["shares"] == 0:
            lines.append(
                f"{plan_row['action']} 금액 ${amt:,.0f} 가 1주 가격보다 적어 정수 주로는 살 수 없습니다 "
                "(소수점 주문이 되는지는 증권사에서 확인하세요)."
            )
        else:
            lines.append(
                f"{plan_row['action']} 금액 ${amt:,.0f} ÷ 현재가 ${lv['last_close']:,.2f} → **약 {est['shares']}주** "
                f"(≈ ${est['cost']:,.0f}, 남는 돈 ${est['leftover']:,.0f})"
            )
    if lv["breakout_level"] is not None:
        lines.append(
            f"{SATELLITE_DONCHIAN_WINDOW}일 돌파선 ${lv['breakout_level']:,.2f} = 직전 "
            f"{SATELLITE_DONCHIAN_WINDOW}거래일 최고 종가(새틀라이트 진입 조건이 넘었는지 보는 선)."
        )
    if lv["stop_headroom_pct"] is not None:
        if lv["stop_headroom_pct"] >= 0:
            lines.append(
                f"현재가가 트레일링스탑 기준(${lv['trailing_stop']:,.2f}, 진입 후 최고 종가 × "
                f"{1 - SATELLITE_DONCHIAN_STOP_PCT:.2f})보다 **{lv['stop_headroom_pct']:.1f}%** 위에 있습니다 — "
                "매수 신호가 아니라, 이만큼 내려가면 규칙상 추세가 끝난 것으로 보는 위험 참고값입니다."
            )
        else:
            lines.append(
                f"⚠️ 현재가가 트레일링스탑 기준(${lv['trailing_stop']:,.2f}) 아래입니다 — 추천 계산 이후 추세가 "
                "꺾였을 수 있으니 1단계(다시 추천)부터 확인하세요."
            )
    if lv["momentum_ref"] is not None:
        lines.append(
            f"12개월 전 가격 ${lv['momentum_ref']:,.2f} → 지금까지 {lv['momentum_12m_pct']:+.1f}% "
            "(코어가 순위를 매기는 12개월 모멘텀의 기준점)."
        )
    st.markdown("\n".join(f"- {line}" for line in lines))
    st.caption(
        "몇 불에 사야 하나: 이 전략에는 지정가·목표 매수가가 없습니다. 백테스트는 리밸런싱일 **종가(그날 시장가)**에 "
        "그대로 샀고, 더 싼 가격을 기다렸다 사는 방식은 검증하지 않았습니다. 차트의 선은 규칙이 쓰는 기준값일 뿐 "
        "지지·저항선이나 '좋은 매수가'가 아닙니다. 주 수는 정수 내림이며 주문 직전 가격은 달라질 수 있습니다."
    )

# ----------------------------------------------------------------------------
# 코어: 17자산 모멘텀 랭킹 + 시장필터 (17종목만 조회하므로 빠름 — 페이지 진입 시 자동 계산)
# ----------------------------------------------------------------------------
today_str = date.today().isoformat()
# job_manager.render()는 완료된 작업을 반환하며 세션 추적을 지운다("바로 꺼내 써야 한다") — 그래서
# ensure()를 매 rerun마다 조건 없이 부르면, 결과를 이미 저장해둔 뒤에도(예: 아래 새틀라이트 버튼
# 클릭 등 다른 위젯 조작으로 rerun될 때마다) 추적이 사라진 상태라 매번 새로 계산을 시작해버리고,
# 그 재계산의 "실행 중" 상태가 자체적으로 거는 st.rerun()이 정작 이번 rerun에서 눌린 다른 위젯의
# 클릭 상태를 다음 rerun으로 못 넘어가게 삼켜버린다(직접 겪어서 확인함 — 새틀라이트 스캔 버튼이
# 반응하지 않던 원인). 이미 오늘자 결과를 세션에 들고 있으면 아예 다시 부르지 않도록 방어한다.
if st.session_state.get("champion_core_asof") != today_str:
    job_manager.ensure("champion_core", today_str, compute_core_recommendation, label="코어 모멘텀 랭킹 계산")
    core_job = job_manager.render("champion_core", running_label="코어 17자산 모멘텀 계산 중...")
    if core_job is not None:
        if core_job.status == "error":
            st.error(f"코어 계산 중 오류가 발생했습니다: {core_job.error}")
        else:
            st.session_state["champion_core_result"] = core_job.result
            st.session_state["champion_core_asof"] = today_str

core_result = st.session_state.get("champion_core_result")

# ----------------------------------------------------------------------------
# 0. 지금 기준 재추천 (2026-09-28 추가)
#
# 버튼 한 번으로 "지금 무엇을 들고 있어야 하나 / 과거 같은 길이 구간에서 어떤 범위가 나왔나 /
# 왜 이걸 믿어야 하나 / 지금 바꿀 것이 있나"를 한 화면에 채운다. 계산은 전부
# core/champion_recommendation.py 가 기존 검증된 함수를 조합해서 하고, 이 절은 표시만 한다.
#
# job_manager.ensure()는 쓰지 않는다 — 매 rerun 마다 부르면 다른 위젯 클릭을 삼킨다(아래 코어 절
# 주석 참고). 버튼으로만 start() 하고, 자체 세션 플래그(_REC_PENDING)가 켜져 있을 때만 render()를
# 불러 폴링 rerun 이 다른 버튼 클릭을 먹지 않게 한다.
# ----------------------------------------------------------------------------
_REC_SLOT = "champion_recommendation"
_REC_PENDING = "champion_rec_pending"
_REC_RESULT = "champion_rec_result"

_rec = st.session_state.get(_REC_RESULT)
if _rec is None:
    _rec = cr.load_latest_cached()
    if _rec is not None:
        st.session_state[_REC_RESULT] = _rec

# ----------------------------------------------------------------------------
# ✅ 지금 할 일 (2026-10-02 추가) — "그래서 지금 뭘 하면 되나"를 화면 맨 위 한 장으로 답한다.
#
# ① 추천이 지금 써도 되는 상태인가(낡았으면 다시 계산 버튼) ② 목표 포트폴리오 한 표
# ③ 내 보유와 비교한 매도/매수 목록(보유 미등록이면 '처음 매수') ④ 다음에 다시 볼 날.
# 새 신호를 만들지 않는다 — 아래 재추천 결과(core/champion_recommendation.py)와 '포트폴리오'
# 화면에 입력한 보유를 합치기만 한다. 근거·과거 범위·확신도는 그 아래 접힌 칸으로 내렸다.
# ----------------------------------------------------------------------------
_live_top4 = list(core_result["top4"]) if core_result else None
_fresh = cr.freshness(_rec, live_core_top4=_live_top4)

st.markdown("## ✅ 지금 할 일")
with st.container(border=True):
    # --- 1단계: 추천이 최신인가 ---
    if _fresh["ok"]:
        (st.success if _fresh["level"] == "fresh" else st.info)(f"**추천 상태:** {_fresh['reason']}")
    else:
        st.warning(f"**1단계 — 추천부터 다시 계산하세요.** {_fresh['reason']}")
    _rec_sizing = st.session_state.get("champion_satellite_sizing_method", "equal")
    if st.button("🔄 지금 기준으로 다시 추천", type="secondary" if _fresh["ok"] else "primary",
                 key="champion_rec_button"):
        st.session_state[_REC_PENDING] = True
        job_manager.start(
            _REC_SLOT, cr.compute_recommendation, date.today(),
            sizing_method=_rec_sizing, label="지금 기준 재추천 계산",
        )
    st.caption("수 분 걸립니다. 백그라운드에서 돌고 다른 화면으로 옮겨도 계속됩니다. 주문은 하지 않습니다.")

if st.session_state.get(_REC_PENDING):
    _rec_job = job_manager.render(
        _REC_SLOT,
        running_label=(
            "재추천 계산 중 — 새틀라이트 point-in-time 스캔을 두 번(규칙 보유분 + 오늘 기준) 돌리고 "
            "분포용 백테스트 캐시를 확인합니다. 수 분 걸릴 수 있고 다른 화면으로 이동해도 계속 진행됩니다"
        ),
    )
    if _rec_job is not None:
        st.session_state[_REC_PENDING] = False
        if _rec_job.status == "error":
            st.error(f"재추천 계산 중 오류가 발생했습니다: {_rec_job.error}")
        else:
            st.session_state[_REC_RESULT] = _rec_job.result
            st.rerun()  # 맨 위 카드를 새 결과로 다시 그린다

if _rec is None:
    st.info("아직 추천을 계산하지 않았습니다. 위 '🔄 지금 기준으로 다시 추천'을 누르면 계산을 시작합니다.")
else:
    _act = _rec.get("action") or {}
    _core = _rec.get("core") or {}
    _sat = _rec.get("satellite") or {}
    _dist = _rec.get("distributions") or {}
    _refs = _rec.get("references") or {}
    _rec_when = str(_rec.get("computed_at", ""))[:16].replace("T", " ")

    _targets = cr.target_allocation(_rec)
    _holdings_pnl = get_portfolio_pnl()
    _held = ({} if _holdings_pnl.empty else
             {r["ticker"]: float(r["market_value"] or 0.0) for _, r in _holdings_pnl.iterrows()})
    _cash_balance = get_cash_balance()
    _has_holdings = any(v > 0 for v in _held.values()) or _cash_balance > 0

    with st.container(border=True):
        # --- 2단계: 목표 포트폴리오 ---
        st.markdown(f"**2단계 — 목표 포트폴리오** · 기준일 {_rec.get('as_of')} (계산 {_rec_when} UTC)")
        _filter_line = {
            "above": "SPY 가 200일선 위라 코어 85%를 전부 투자합니다.",
            "below": "SPY 가 200일선 아래라 코어를 절반만 투자하고 나머지는 현금으로 둡니다.",
            "unknown": "SPY 데이터가 없어 시장필터를 판정하지 못했습니다 — 신규 주문을 보류하세요.",
        }.get(_core.get("market_filter_status"), "")
        if _core.get("market_filter_status") == "unknown":
            st.error(_filter_line)
        elif _filter_line:
            st.caption(_filter_line)

        _capital = 10_000.0
        if not _has_holdings:
            _capital = st.number_input(
                "투자할 금액($)", min_value=100.0, max_value=100_000_000.0, value=10_000.0, step=1_000.0,
                format="%.0f", key="champion_todo_capital",
            )
        _plan = cr.order_plan(_targets, _held, _cash_balance, _capital)
        st.dataframe(
            pd.DataFrame([
                {"종목": "현금" if r["ticker"] == cr.CASH_TICKER else r["ticker"], "구분": r["sleeve"],
                 "목표 비중": f"{r['weight'] * 100:.1f}%", "목표 금액": f"${r['weight'] * _plan['total']:,.0f}"}
                for r in _targets
            ]),
            use_container_width=True, hide_index=True,
        )

        # --- 3단계: 주문 목록 ---
        st.markdown("**3단계 — 주문 목록**")
        if _plan["basis"] == "fresh":
            st.caption(
                "보유 종목이 등록돼 있지 않아 '처음부터 매수' 기준으로 계산했습니다. 이미 갖고 있는 종목이 있으면 "
                "포트폴리오 화면에 입력하세요 — 그러면 실제로 사고팔 것만 남습니다."
            )
            _page_link("pages/8_포트폴리오_관리.py", "💼 포트폴리오에 보유 입력하기")
        else:
            st.caption(f"포트폴리오 화면에 입력한 보유 기준(현금 포함 총 ${_plan['total']:,.0f}). 입력이 낡으면 이 목록도 틀립니다.")
        _trades = [r for r in _plan["rows"] if r["action"] != "유지"]
        if not _trades:
            st.success("지금 사고팔 것 없음 — 보유가 목표와 1%p 이내입니다.")
        else:
            st.dataframe(
                pd.DataFrame([
                    {"순서": i, "할 일": r["action"], "종목": r["ticker"], "금액": f"${abs(r['delta_value']):,.0f}",
                     "현재 → 목표": f"${r['current_value']:,.0f} → ${r['target_value']:,.0f}"}
                    for i, r in enumerate(_trades, start=1)
                ]),
                use_container_width=True, hide_index=True,
            )
            if any(r["action"] in ("매도", "전량 매도") for r in _trades):
                st.caption("매도를 먼저 하고 그 돈으로 매수하는 순서입니다.")
        _keep = [r["ticker"] for r in _plan["rows"] if r["action"] == "유지"]
        if _keep:
            st.caption(f"그대로 두면 되는 종목: {', '.join(_keep)}")
        if _plan["target_cash"] > 0.5:
            st.caption(f"현금으로 남겨 둘 금액: ${_plan['target_cash']:,.0f}")
        if not _fresh["ok"]:
            st.warning("⚠️ 추천이 낡아 이 주문 목록도 낡았을 수 있습니다 — 1단계(다시 추천)를 먼저 하세요.")

        # --- 종목 차트: 누른 종목 하나만 가격을 받아 그린다(페이지 진입 시 전 종목을 조회하지 않음) ---
        _chart_choices = cr.chart_tickers(_targets)
        if _chart_choices:
            _chart_pick = st.pills(
                "📈 종목 차트 — 종목을 누르면 가격 차트와 '지금 사면 몇 주'가 열립니다",
                options=_chart_choices, selection_mode="single", default=None, key="champion_todo_chart_ticker",
            )
            if _chart_pick:
                _render_ticker_chart(
                    _chart_pick,
                    sleeve={r["ticker"]: r["sleeve"] for r in _targets}.get(_chart_pick, ""),
                    plan_row=next((r for r in _plan["rows"] if r["ticker"] == _chart_pick), None),
                    evidence_row=next((r for r in (_sat.get("evidence") or []) if r.get("ticker") == _chart_pick), None),
                    evidence_as_of=str(_rec.get("as_of") or "") or None,
                )

        # --- 4단계: 다음에 다시 볼 날 ---
        _cp = cr.next_checkpoints()
        st.markdown("**4단계 — 다음에 다시 볼 날**")
        st.markdown(
            f"- **코어**: 매달 첫 거래일에 다시 봅니다 → 다음 **{_cp['core_next']}**\n"
            f"- **새틀라이트**: 오늘 사면 **{_cp['satellite_next']}**(매수일 + 6개월)까지 그대로 둡니다. "
            "그 사이에 목록이 바뀌어도 교체하지 않는 것이 이 전략의 규칙입니다."
        )
        st.caption(
            "이 화면은 주문하지 않습니다 — 증권사에서 직접 주문하거나 paper 계좌는 scripts/champion_paper_trade.py 를 씁니다. "
            "확신도가 약한(weak) 구성요소가 있으며 미래 수익을 보장하지 않습니다(아래 '근거와 확신도')."
        )

    # ---------------- 추천 상세 (접힘) — 맨 위 카드의 근거 ----------------
    st.markdown("#### 추천 상세 — 근거가 궁금할 때만 보세요")
    _tab_pick, _tab_range, _tab_why = st.tabs([
        "🔎 왜 이 종목인가", "📊 과거 같은 길이 구간의 수익 범위", "🧪 근거와 확신도",
    ])
    with _tab_pick:
        for _item in _act.get("items") or []:
            if "트레일링스탑" in (_item.get("text") or ""):
                st.caption(f"⚠️ {_item['text']}")
        _filter_text = {
            "above": "SPY 200일선 위 — 코어 비중 그대로",
            "below": "SPY 200일선 아래 — 코어 비중 절반으로 축소",
            "unknown": "SPY 데이터 없음 — 시장필터 판정불가, 신규 주문 보류",
        }.get(_core.get("market_filter_status"), "판정불가")
        st.markdown(
            f"**코어 {CORE_WEIGHT * 100:.0f}%** — 실투입 {_core.get('invested_weight_pct', 0):.1f}% "
            f"(현금 {float(_core.get('cash_weight_from_filter') or 0) * 100:.1f}%) · {_filter_text}"
        )
        _core_rows = [r for r in (_core.get("evidence") or []) if r.get("in_top4")]
        if not _core_rows:
            st.warning("절대모멘텀(>0)을 통과한 코어 자산이 없습니다 — 코어 비중이 사실상 전액 현금입니다.")
        else:
            st.dataframe(
                pd.DataFrame([
                    {"종목": r["ticker"], "12개월 모멘텀": f"{r['momentum_12m_pct']:+.1f}%" if r["momentum_12m_pct"] is not None else "—",
                     "순위": r["rank"], "비중": f"{r['weight_pct']:.1f}%"}
                    for r in _core_rows
                ]),
                use_container_width=True, hide_index=True,
            )

        _rule = _sat.get("rule") or _sat.get("if_bought_at_last_rebal") or {}
        _today_sat = _sat.get("today") or {}
        _next_resel = _sat.get("next_reselection_if_bought_today") or {}
        st.markdown(f"**새틀라이트 {SATELLITE_WEIGHT * 100:.0f}%** — 오늘 기준으로 다시 뽑은 결과입니다.")
        with st.container(border=True):
            st.markdown("**오늘 기준 재선정 — 지금 매수한다면 이 종목**")
            st.caption(
                f"기준일 {_today_sat.get('as_of')} · 후보 풀 {_today_sat.get('pool_size')}종목 중 "
                f"활성 추세 {_today_sat.get('n_active_trend')}개"
            )
            if not _today_sat.get("picks"):
                st.info("오늘 기준으로 조건을 만족하는 종목이 없습니다 — 새틀라이트 비중이 사실상 현금입니다.")
            else:
                _sleeve = _today_sat.get("sleeve_weights") or {}
                st.dataframe(
                    pd.DataFrame([
                        {"종목": t, "슬리브 내 비중": f"{_sleeve.get(t, 0.0) * 100:.1f}%",
                         "전체 비중": f"{_sleeve.get(t, 0.0) * SATELLITE_WEIGHT * 100:.1f}%"}
                        for t in (_today_sat.get("picks") or [])
                    ]),
                    use_container_width=True, hide_index=True,
                )
                if _next_resel.get("date"):
                    st.caption(
                        f"오늘 매수하면 다음 재선정일은 **{_next_resel.get('date')}** 입니다"
                        f"(매수일 + {_next_resel.get('months')}개월). 반기 주기는 그대로이고 시작점만 매수일에 맞춥니다."
                    )
        st.caption(f"ℹ️ {_sat.get('diff_note')}")
        st.caption(_sat.get("timing_note") or cr.TIMING_NOTE)

        with st.expander(f"참고: {_rule.get('rebal_date') or '직전 반기 리밸런싱일'}에 매수했다면 지금 들고 있을 종목", expanded=False):
            st.caption(
                "그때 실제로 매수한 경우에만 의미가 있습니다. 같은 선정 함수에 날짜만 직전 반기 리밸런싱일로 "
                f"바꿔 계산한 것입니다 · 후보 풀 {_rule.get('pool_size')}종목 중 활성 추세 "
                f"{_rule.get('n_active_trend')}개 · {_rule.get('allocation_reason')}"
            )
            if not _rule.get("picks"):
                st.info("그날 기준으로 뽑힌 종목이 없습니다.")
            else:
                st.dataframe(
                    pd.DataFrame([
                        {"종목": r["ticker"],
                         "비중": f"{(_rule.get('per_ticker_weights') or {}).get(r['ticker'], 0.0) * 100:.1f}%",
                         "리밸런싱 이후": (f"{r['return_since_rebal_pct']:+.1f}%"
                                      if r.get("return_since_rebal_pct") is not None else "—")}
                        for r in (_rule.get("picks_table") or [])
                    ]),
                    use_container_width=True, hide_index=True,
                )

    with _tab_range:
        if not _dist.get("available"):
            st.info(
                "분포를 만들 백테스트 캐시가 없습니다"
                + (f" ({_dist.get('error')})" if _dist.get("error") else "")
                + ". 주간 추적 잡(champion_tracking_weekly)이 캐시를 만들면 여기에 표시됩니다."
            )
        else:
            st.caption(
                f"라이브 시작({_dist.get('live_start')}, {_dist.get('live_start_note')}) 이전 백테스트 "
                f"{_dist.get('backtest_start')}~{_dist.get('backtest_end')} 구간에서 같은 길이 구간을 모두 겹쳐 모았습니다."
            )
            st.caption(f"⚠️ {_dist.get('warning')}")
            for _h in ("63", "126"):
                _hd = (_dist.get("by_horizon") or {}).get(_h)
                if not _hd:
                    continue
                with st.container(border=True):
                    st.markdown(f"**{_hd.get('label')}** — 겹치는 구간 {_hd.get('n_windows')}개")
                    if not _hd.get("enough_windows"):
                        st.caption("⚠️ 구간 수가 적어(50개 미만) 범위를 넓게만 읽어야 합니다.")
                    _s = _hd.get("strategy") or {}
                    _x = _hd.get("excess_spy") or {}
                    _m = _hd.get("max_drawdown") or {}
                    _beat = _hd.get("beat_spy_share")
                    _ww = _hd.get("worst_window") or {}
                    _worst_txt = cr.fmt_pct(_s.get("worst"))
                    if _ww:
                        _worst_txt += f" ({_ww.get('start')}~{_ww.get('end')})"
                    _beat_txt = f"{_beat * 100:.0f}%" if _beat is not None else "—"
                    st.markdown(
                        f"- 전략 수익: {cr.fmt_range(_s)}\n"
                        f"- 최악 구간: {_worst_txt}\n"
                        f"- 구간 내 최대낙폭: {cr.fmt_range(_m)}\n"
                        f"- SPY 대비 초과수익: {cr.fmt_range(_x)}\n"
                        f"- **SPY 를 이긴 구간 비율: {_beat_txt}**"
                    )
                    _vals = _hd.get("excess_spy_values") or []
                    if _vals:
                        _fig = go.Figure()
                        _fig.add_trace(go.Histogram(
                            x=[v * 100 for v in _vals], nbinsx=40, marker=dict(color=_C_STRATEGY),
                            name="SPY 대비 초과수익", hovertemplate="%{x:.1f}%p: %{y}개 구간<extra></extra>",
                        ))
                        _fig.add_vline(x=0, line=dict(color=_C_SPY, width=2))
                        _fig.update_layout(
                            height=230, margin=dict(l=8, r=8, t=28, b=8), showlegend=False,
                            xaxis_title="SPY 대비 초과수익(%p) — 0 선 왼쪽은 SPY 에 진 구간",
                            yaxis_title="구간 수", bargap=0.04,
                        )
                        st.plotly_chart(_fig, use_container_width=True, config={"displayModeBar": False})

            _curves = _dist.get("curves") or {}
            if _curves.get("dates") and _curves.get("strategy"):
                st.markdown("**과거 자산곡선 — 전략 vs S&P500**")
                _rec_capital = st.number_input(
                    "초기 금액($) — 저장된 결과는 배수라서 금액을 바꿔도 다시 계산하지 않습니다",
                    min_value=100.0, max_value=100_000_000.0, value=10_000.0, step=1_000.0, format="%.0f",
                    key="champion_rec_capital",
                )
                _eq = go.Figure()
                for _key, _name, _color in (("strategy", "챔피언(코어+새틀라이트)", _C_STRATEGY),
                                            ("spy", "S&P500(SPY) 매수보유", _C_SPY),
                                            ("satellite", "새틀라이트 단독", _C_SAT)):
                    _series = _curves.get(_key)
                    if not _series:
                        continue
                    _eq.add_trace(go.Scatter(
                        x=_curves["dates"], y=[None if v is None else v * _rec_capital for v in _series],
                        name=_name, mode="lines", line=dict(width=2 if _key == "strategy" else 1.4, color=_color),
                        hovertemplate=f"{_name}: $%{{y:,.0f}}<extra></extra>",
                    ))
                _eq.update_layout(
                    height=280, margin=dict(l=8, r=8, t=30, b=8), yaxis_title="계좌 금액(가상, $)",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=11)),
                )
                st.plotly_chart(_eq, use_container_width=True, config={"displayModeBar": False})
                st.caption(f"자산곡선 출처: {_curves.get('source')} · 가상 결과이며 실제 주문 기록이 아닙니다.")

            _sleeve = _dist.get("satellite_sleeve")
            if _sleeve:
                st.markdown("**새틀라이트 슬리브만의 SPY 대비 초과수익 분포**")
                for _h, _row in (_sleeve.get("by_horizon") or {}).items():
                    _sb = _row.get("beat_spy_share")
                    st.markdown(
                        f"- {_row.get('label')}: {cr.fmt_range(_row)} · SPY 를 이긴 구간 "
                        + (f"{_sb * 100:.0f}%" if _sb is not None else "—")
                        + f" (구간 {_row.get('n')}개)"
                    )
                st.caption(
                    "새틀라이트 15%만 떼어 본 것이라 전체 포트폴리오 성과가 아닙니다. 숫자가 음수면 그 구간들에서 "
                    "이 슬리브가 SPY 에 뒤졌다는 뜻이며, 그대로 표시합니다."
                )
            else:
                st.caption("새틀라이트 슬리브 단독 분포는 '챔피언 성과' 화면의 계산 결과가 저장돼 있을 때만 표시됩니다.")

            for _line in _rec.get("limitations") or []:
                st.caption(f"· {_line}")

    with _tab_why:
        st.caption("아래 등급은 이 엔진이 스스로 매긴 것이 아니라 리서치 프로그램의 감사 결과입니다. 약한 것은 약하다고 그대로 표시합니다.")
        for _title, _key in (("코어를 만든 결정", "core_confidence"), ("새틀라이트를 만든 결정", "satellite_confidence")):
            _rows = _refs.get(_key) or []
            if not _rows:
                continue
            st.markdown(f"**{_title}**")
            for _row in _rows:
                st.markdown(f"- {_GRADE_BADGE.get(_row['grade'], _row['grade'])} {_row['component']}")
                st.caption(f"　{_row['note']} (근거: {_row['source']})")

        _ev = _sat.get("evidence") or []
        if _ev:
            st.markdown("**새틀라이트 종목별 근거**")
            st.dataframe(
                pd.DataFrame([
                    {"종목": r["ticker"], "섹터": r.get("sector") or "—",
                     "돌파 발생일": r.get("breakout_date") or "—",
                     "12개월 모멘텀": f"{r['momentum_12m_pct']:+.1f}%" if r.get("momentum_12m_pct") is not None else "—",
                     "후보 중 순위": r.get("rank_among_breakouts") or "—",
                     "현재가": f"${r['current_price']:,.2f}" if r.get("current_price") is not None else "—",
                     "트레일링스탑": f"${r['trailing_stop']:,.2f}" if r.get("trailing_stop") is not None else "—",
                     "스탑까지 여유": f"{r['stop_headroom_pct']:+.1f}%" if r.get("stop_headroom_pct") is not None else "—",
                     "추세 활성": "예" if r.get("trend_active") else "아니오"}
                    for r in _ev
                ]),
                use_container_width=True, hide_index=True,
            )
        with st.expander("코어 17자산 전체 모멘텀 순위 (이번 추천의 근거)"):
            st.dataframe(
                pd.DataFrame([
                    {"순위": r["rank"], "종목": r["ticker"],
                     "12개월 모멘텀": f"{r['momentum_12m_pct']:+.1f}%" if r["momentum_12m_pct"] is not None else "—",
                     "절대모멘텀 통과": "예" if r["passes_absolute_momentum"] else "아니오",
                     "top4": "예" if r["in_top4"] else "아니오",
                     "비중": f"{r['weight_pct']:.1f}%"}
                    for r in (_core.get("evidence") or [])
                ]),
                use_container_width=True, hide_index=True,
            )

        st.caption(f"📄 근거 문서: `{_refs.get('synthesis_report')}` (리서치 프로그램 전체 종합 리포트)")
        _rejected = _refs.get("rejected_ideas") or []
        if _rejected:
            with st.expander(f"이미 검토했지만 채택하지 않은 아이디어 ({len(_rejected)}개)"):
                for _row in _rejected:
                    st.markdown(f"- {_GRADE_BADGE.get(_row['grade'], _row['grade'])} {_row['component']}")
                    st.caption(f"　{_row['note']}")
        st.markdown("**아직 검증 중인 것**")
        st.caption(_refs.get("research_note"))
        for _job in _refs.get("research_jobs") or []:
            if _job.get("verdicts"):
                _v = ", ".join(f"{k}={v}" for k, v in _job["verdicts"].items())
                st.caption(f"· {_job['title']} — {_v} (결과 research/results/{_job['id']}/)")
            else:
                st.caption(f"· {_job['title']} — {_job.get('status')}")
        for _line in _rec.get("unverified_notes") or []:
            st.caption(f"· 검증 안 됨: {_line}")


st.divider()
st.markdown("### 아래는 세부 계산입니다")
st.caption("위 '지금 할 일'만으로 충분합니다. 아래는 코어·새틀라이트를 따로 계산하거나 백테스트·헤지를 직접 확인할 때 씁니다.")

st.markdown("## 1. 코어 — 섹터 로테이션 모멘텀 (85%)")
st.caption("17자산(11개 GICS 섹터 ETF + 채권2 + 금 + 국제주식 + 하이일드 + 원자재) 중 12개월 모멘텀 상위 4개, 동일비중 · 월간 리밸런싱.")

if core_result is None:
    st.info("코어 계산 결과를 불러오는 중입니다...")
else:
    filter_cols = st.columns(4)
    above = core_result["above_200dma"]
    with filter_cols[0]:
        spy_price = core_result["spy_price"]
        render_metric_card("SPY 현재가", f"${spy_price:,.2f}" if spy_price is not None else "N/A")
    with filter_cols[1]:
        spy_sma = core_result["spy_sma200"]
        render_metric_card("SPY 200일선", f"${spy_sma:,.2f}" if spy_sma is not None else "N/A")
    with filter_cols[2]:
        if above is None:
            render_metric_card("시장필터", "판정불가")
        else:
            render_metric_card("시장필터", "200일선 위" if above else "200일선 아래", tone="good" if above else "bad")
    with filter_cols[3]:
        render_metric_card(
            "코어 실투입 비중", f"{core_result['exposure_multiplier'] * 0.85 * 100:.1f}%",
            sublabel=f"현금 {core_result['cash_weight_from_filter'] * 100:.1f}%" if core_result["cash_weight_from_filter"] > 0 else None,
        )
    st.caption(
        "⚠️ 이 시장필터(SPY 200일선 하회 시 코어 비중 50% 축소) 자체의 확신도는 **weak**입니다 — "
        "방향(무필터가 더 낫다)은 살아있지만 블록부트스트랩 감사에서 통계적으로 약해졌습니다 "
        "(아래 '확신도' 표 참고)."
    )

    st.markdown("#### 오늘의 코어 top4")
    top4 = core_result["top4"]
    if not top4:
        st.warning("절대모멘텀(>0) 조건을 통과한 자산이 없습니다 — 코어 비중 전체가 사실상 현금입니다.")
    else:
        card_cols = st.columns(len(top4))
        ranked = core_result["ranked"]
        for col, ticker in zip(card_cols, top4):
            row = ranked[ranked["ticker"] == ticker].iloc[0]
            with col:
                render_metric_card(
                    ticker, f"{row['momentum_pct']:+.1f}%", tone="good",
                    sublabel=f"비중 {core_result['per_ticker_weight'] * 100:.1f}%",
                )
                guru_caption = _guru_cross_ref_caption(ticker)
                if guru_caption:
                    st.caption(guru_caption)

    with st.expander("전체 17자산 랭킹 보기"):
        st.dataframe(
            core_result["ranked"][["ticker", "momentum_pct", "passes_absolute_momentum", "in_top4", "last_close"]],
            use_container_width=True, hide_index=True,
        )
    st.caption(f"기준일: {core_result['as_of']}")

# ----------------------------------------------------------------------------
# 새틀라이트: point-in-time(백테스트와 동일한 방법) + 참고용 전체 S&P500 스캔
# (2026-09-14 작업 60: 라이브 추천이 백테스트와 다른 방법론을 쓰던 것을 정정 — 두 값을 함께
#  보여주되 어느 쪽이 실제로 검증된 방법인지 명확히 구분한다.)
# ----------------------------------------------------------------------------
st.markdown("## 2. 새틀라이트 — 돈치안 20일 브레이크아웃 (15%)")
st.caption(
    "코어의 15%를 돈치안 20일 브레이크아웃(직전 20일 고가를 종가가 돌파) 추세추종 종목으로 구성합니다. "
    "아래 두 탭은 서로 다른 방법론입니다 — 실제로 매매 판단을 내릴 때는 반드시 '① point-in-time' "
    "탭을 기준으로 하세요(아래 '3. 백테스트'가 측정하는 것이 바로 이 방법입니다)."
)

satellite_sizing_method = st.radio(
    "종목 간 비중 배분 방식", options=["equal", "inverse_vol"],
    format_func=lambda v: "균등가중 (기본, 검증됨)" if v == "equal" else "🧪 변동성 역가중 (실험적, 미검증)",
    horizontal=True, key="champion_satellite_sizing_method",
)
if satellite_sizing_method == "inverse_vol":
    st.caption(
        "⚠️ 이 옵션은 '어떤 종목을 고를지'가 아니라 '고른 종목 안에서 비중을 어떻게 나눌지'만 "
        "바꿉니다 — 이 리서치 프로그램이 아직 감사하지 않은 새 시도라 확신도 등급이 없습니다. "
        "아래 백테스트에서 균등가중과 비교해본 뒤 채택 여부를 직접 판단하세요."
    )

sat_tab_pit, sat_tab_scan = st.tabs([
    "✅ 백테스트와 동일한 방법 — 반기 point-in-time",
    "🔍 빠른 근사 스캔 (참고용 — 백테스트와 다른 방법론)",
])

with sat_tab_pit:
    st.caption(
        "직전 반기 리밸런싱일(1월/7월 첫 거래일)에 point-in-time 유니버스 표본(40종목)을 뽑아 돈치안 "
        "브레이크아웃+트레일링스탑이 활성인 종목 중 12개월 모멘텀 상위 3개를 골랐다면, 그 이후 계속 "
        "보유했을 때 '지금' 들고 있을 종목입니다 — 새 랭킹 로직이 아니라 백테스트가 실제로 검증한 "
        "로직(_pick_satellite_at_date)을 그대로 재사용합니다. point-in-time 유니버스 표본추출 + 가격 "
        "조회가 필요해 아래 '빠른 근사 스캔'만큼 시간이 걸릴 수 있습니다."
    )
    if st.button("📌 point-in-time 새틀라이트 계산"):
        job_manager.start(
            "champion_satellite_pit", compute_satellite_recommendation_point_in_time,
            sizing_method=satellite_sizing_method, label="새틀라이트 point-in-time 계산",
        )

    satellite_pit_job = job_manager.render(
        "champion_satellite_pit", running_label="point-in-time 유니버스 표본 + 브레이크아웃 스캔 중 (수 분 걸릴 수 있습니다)"
    )
    if satellite_pit_job is not None:
        if satellite_pit_job.status == "error":
            st.error(f"point-in-time 계산 중 오류가 발생했습니다: {satellite_pit_job.error}")
        else:
            st.session_state["champion_satellite_pit_result"] = satellite_pit_job.result

    satellite_pit_result = st.session_state.get("champion_satellite_pit_result")
    if satellite_pit_result is None:
        st.caption("아직 계산하지 않았습니다.")
    else:
        pit_selected = satellite_pit_result["selected"]
        pit_weights = satellite_pit_result.get("per_ticker_weights", {})
        st.caption(
            f"직전 리밸런싱일: {satellite_pit_result['rebal_date']} · 다음 리밸런싱까지 약 "
            f"{satellite_pit_result['trading_days_to_next_rebal']}거래일(공휴일 미반영 근사치) · "
            f"후보 풀 {satellite_pit_result['pool_size']}종목 중 활성 추세 {satellite_pit_result['n_active_trend']}개 · "
            f"사이징 방식: {satellite_pit_result.get('sizing_method', 'equal')}"
        )
        if not pit_selected:
            st.info("직전 리밸런싱 시점에 활성 브레이크아웃 종목이 없었습니다 — 새틀라이트 비중(15%)이 사실상 현금입니다.")
        else:
            pit_cols = st.columns(len(pit_selected))
            picks_df = satellite_pit_result["picks"]
            for col, ticker in zip(pit_cols, pit_selected):
                row = picks_df[picks_df["ticker"] == ticker].iloc[0]
                with col:
                    render_metric_card(
                        ticker, f"{row['return_since_rebal_pct']:+.1f}%", tone="good",
                        sublabel=f"비중 {pit_weights.get(ticker, 0.0) * 100:.1f}% · 리밸런싱 이후 수익률",
                    )
                    guru_caption = _guru_cross_ref_caption(ticker)
                    if guru_caption:
                        st.caption(guru_caption)
            with st.expander("point-in-time 종목 상세 보기"):
                st.dataframe(picks_df, use_container_width=True, hide_index=True)

with sat_tab_scan:
    st.caption(
        "현재 S&P500 유니버스 전체를 매번 스캔해 돈치안 브레이크아웃 중인 종목을 3개월 모멘텀 상위 "
        "5개로 고르는 단순화된 근사치입니다 — 반기 point-in-time 방법론과 다르므로 위 백테스트 성과와 "
        "직접 비교하지 마세요. 전체 스캔은 종목 수만큼 순차 조회가 필요해 수 분 걸릴 수 있습니다."
    )
    if st.button("🔍 새틀라이트 후보 스캔 실행"):
        job_manager.start(
            "champion_satellite", compute_satellite_recommendation,
            sizing_method=satellite_sizing_method, label="새틀라이트 후보 스캔",
        )

    satellite_job = job_manager.render(
        "champion_satellite", running_label="S&P500 스캔 중 (수 분 걸릴 수 있습니다)"
    )
    if satellite_job is not None:
        if satellite_job.status == "error":
            st.error(f"새틀라이트 스캔 중 오류가 발생했습니다: {satellite_job.error}")
        else:
            st.session_state["champion_satellite_result"] = satellite_job.result

    satellite_result = st.session_state.get("champion_satellite_result")
    if satellite_result is None:
        st.caption("아직 스캔하지 않았습니다.")
    else:
        selected = satellite_result["selected"]
        per_ticker_weights = satellite_result.get("per_ticker_weights", {})
        st.caption(
            f"스캔 {satellite_result['scanned_count']}종목 중 브레이크아웃 후보 {len(satellite_result['candidates'])}개, "
            f"기준일 {satellite_result['as_of']}, 사이징 방식: {satellite_result.get('sizing_method', 'equal')}"
        )
        if not selected:
            st.info("현재 브레이크아웃 중인 종목이 없습니다 — 새틀라이트 비중(15%)이 사실상 현금입니다.")
        else:
            sat_cols = st.columns(len(selected))
            for col, ticker in zip(sat_cols, selected):
                row = satellite_result["candidates"][satellite_result["candidates"]["ticker"] == ticker].iloc[0]
                with col:
                    render_metric_card(
                        ticker, f"{row['momentum_3m_pct']:+.1f}%", tone="good",
                        sublabel=f"비중 {per_ticker_weights.get(ticker, 0.0) * 100:.1f}%",
                    )
                    guru_caption = _guru_cross_ref_caption(ticker)
                    if guru_caption:
                        st.caption(guru_caption)
            with st.expander("브레이크아웃 후보 전체 보기"):
                st.dataframe(satellite_result["candidates"], use_container_width=True, hide_index=True)


# ----------------------------------------------------------------------------
# 백테스트 — "오늘 신호"가 아니라 "과거에 이 전략을 실제로 썼다면 어땠을지"
# ----------------------------------------------------------------------------
st.markdown("## 3. 백테스트")
st.caption(
    "위 코어/새틀라이트 로직을 과거 구간에 그대로 실행합니다. 코어는 매달, 새틀라이트는 반기(1월/7월)마다 "
    "리밸런싱하며, 새틀라이트는 매 반기 point-in-time 유니버스 표본(40종목)을 다시 뽑고 그중 돈치안 "
    "브레이크아웃이 활성인 종목을 스캔하므로 기간이 길수록(반기 수만큼) 오래 걸립니다 "
    "(실측 기준 1년≈2분 안팎 — 기간을 늘리면 비례해서 늘어납니다)."
)
_page_link("pages/14_챔피언_성과.py", "📒 언제 사고 팔아 얼마를 벌었나(거래 내역·SPY 비교) → 챔피언 성과")

bt_col1, bt_col2, bt_col3 = st.columns(3)
with bt_col1:
    bt_start = st.date_input("시작일", value=date.today().replace(year=date.today().year - 3))
with bt_col2:
    bt_end = st.date_input("종료일", value=date.today())
with bt_col3:
    bt_satellite_weight = st.slider("새틀라이트 비중", min_value=0.0, max_value=0.3, value=SATELLITE_WEIGHT, step=0.05)

bt_apply_collar = st.checkbox(
    "🛡️ 옵션 칼라 헤지 비교선 추가 (확신도 weak — 아래 '4. 옵션 칼라 헤지' 참고)",
    value=False,
)
bt_sizing_method = st.session_state.get("champion_satellite_sizing_method", "equal")
if bt_sizing_method == "inverse_vol":
    st.caption("🧪 위에서 고른 '변동성 역가중' 사이징으로 새틀라이트를 재계산합니다 (미검증 opt-in).")

if st.button("📊 백테스트 실행"):
    if bt_apply_collar:
        job_manager.start(
            "champion_backtest", run_champion_backtest_with_collar,
            bt_start.isoformat(), bt_end.isoformat(), satellite_weight=bt_satellite_weight,
            satellite_sizing_method=bt_sizing_method,
            label="챔피언 전략 백테스트 (칼라 헤지 포함)",
        )
    else:
        job_manager.start(
            "champion_backtest", run_champion_backtest,
            bt_start.isoformat(), bt_end.isoformat(), satellite_weight=bt_satellite_weight,
            satellite_sizing_method=bt_sizing_method,
            label="챔피언 전략 백테스트",
        )

backtest_job = job_manager.render(
    "champion_backtest", running_label="백테스트 실행 중 (코어는 빠르지만 새틀라이트는 반기마다 point-in-time 스캔이 필요해 오래 걸릴 수 있습니다)"
)
if backtest_job is not None:
    if backtest_job.status == "error":
        st.error(f"백테스트 중 오류가 발생했습니다: {backtest_job.error}")
    else:
        st.session_state["champion_backtest_result"] = backtest_job.result

backtest_result = st.session_state.get("champion_backtest_result")
if backtest_result is None:
    st.caption("아직 백테스트를 실행하지 않았습니다.")
else:
    equity = backtest_result["equity_net"]
    spy_bench = get_price_history("SPY", start=backtest_result["start"], end=backtest_result["end"])
    spy_equity = (spy_bench["Close"] / spy_bench["Close"].iloc[0] * 100.0) if not spy_bench.empty else None

    eq_fig = go.Figure()
    eq_fig.add_trace(go.Scatter(x=equity.index, y=equity.values, name="챔피언(코어+새틀라이트)", line=dict(width=2, color="#5B8DEF")))
    if backtest_result["satellite_weight_applied"] > 0:
        core_equity = (1 + backtest_result["core"]["ret_net"]).cumprod() * 100.0
        eq_fig.add_trace(go.Scatter(x=core_equity.index, y=core_equity.values, name="코어만(새틀라이트 제외)", line=dict(width=1.5, color="#8a8a8a", dash="dot")))
    if spy_equity is not None:
        eq_fig.add_trace(go.Scatter(x=spy_equity.index, y=spy_equity.values, name="S&P500 매수보유", line=dict(width=1.5, color="#F2994A")))
    if "collar_equity_net" in backtest_result:
        collar_equity = backtest_result["collar_equity_net"]
        eq_fig.add_trace(go.Scatter(x=collar_equity.index, y=collar_equity.values, name="챔피언+칼라헤지", line=dict(width=2, color="#2ecc71", dash="dash")))
    eq_fig.update_layout(
        height=380, yaxis_title="자산가치 (시작=100)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=10, r=10, t=30, b=10),
    )
    st.plotly_chart(eq_fig, use_container_width=True)

    bm = backtest_result["metrics"]
    metric_cols = st.columns(5)
    with metric_cols[0]:
        render_metric_card("누적수익률", f"{bm.get('cumulative_return', 0):+.1f}%", tone="good" if bm.get("cumulative_return", 0) >= 0 else "bad")
    with metric_cols[1]:
        render_metric_card("CAGR", f"{bm.get('cagr', 0):+.1f}%", tone="good" if bm.get("cagr", 0) >= 0 else "bad")
    with metric_cols[2]:
        render_metric_card("MDD", f"{bm.get('mdd', 0):.1f}%", tone="bad" if bm.get("mdd", 0) < -20 else "neutral")
    with metric_cols[3]:
        render_metric_card("샤프지수", f"{bm.get('sharpe', 0):.2f}", tone="good" if bm.get("sharpe", 0) >= 1 else "neutral")
    with metric_cols[4]:
        render_metric_card("칼마지수", f"{bm.get('calmar', 0):.2f}")

    if "collar_metrics" in backtest_result:
        cm = backtest_result["collar_metrics"]
        st.caption("🛡️ 칼라 헤지 적용 시 (SPY 합성 ATM풋+5%OTM콜, 새틀라이트 노셔널만 방어):")
        collar_cols = st.columns(4)
        with collar_cols[0]:
            render_metric_card("CAGR (칼라)", f"{cm.get('cagr', 0):+.1f}%")
        with collar_cols[1]:
            render_metric_card("MDD (칼라)", f"{cm.get('mdd', 0):.1f}%")
        with collar_cols[2]:
            render_metric_card("샤프 (칼라)", f"{cm.get('sharpe', 0):.2f}")
        with collar_cols[3]:
            render_metric_card("칼마 (칼라)", f"{cm.get('calmar', 0):.2f}")
        with st.expander("칼라 헤지 월별 롤 로그"):
            st.dataframe(pd.DataFrame(backtest_result["collar_roll_log"]), use_container_width=True, hide_index=True)

    st.plotly_chart(render_drawdown_chart(compute_drawdown_series(equity)), use_container_width=True)

    monthly = compute_monthly_returns(equity)
    if not monthly.empty:
        st.plotly_chart(render_monthly_returns_heatmap(monthly), use_container_width=True)

    if backtest_result["satellite_weight_applied"] == 0.0:
        st.warning("이 구간에는 새틀라이트가 한 번도 종목을 고르지 못해 코어 100%로 대체되었습니다 (기간을 늘려보세요).")
    else:
        with st.expander("새틀라이트 반기 리밸런싱 로그"):
            st.dataframe(pd.DataFrame(backtest_result["satellite"]["rebal_log"]), use_container_width=True, hide_index=True)

    st.caption(
        "⚠️ 이 백테스트는 왕복 0.1% 거래비용만 반영하며(세금/슬리피지 등은 미포함), 리서치가 실제로 검증한 "
        "방법론(코어: 17자산 월간 로테이션, 새틀라이트: 반기 point-in-time 40종목 풀+돈치안 브레이크아웃 "
        "상위3)을 그대로 재현합니다 — 위 '오늘의 코어 top4'/'새틀라이트 후보 스캔'(라이브 추천)과는 "
        "새틀라이트 스캔 방식이 다릅니다(라이브는 매번 S&P500 전체를 스캔하는 단순화된 근사치)."
    )

# ----------------------------------------------------------------------------
# 옵션 칼라 헤지 — 라이브 계산 (2026-09-14부터: SPY 종가+VIX 대리변동성+FRED 금리로 합성
# Black-Scholes 가격을 매기므로 실제 옵션 시세 없이도 계산 가능. 확신도는 여전히 weak.)
# ----------------------------------------------------------------------------
st.markdown("## 4. 옵션 칼라 헤지 (새틀라이트 15% 노셔널 방어 — 확신도 weak)")
st.caption(
    "새틀라이트 노셔널(15%)만큼을 SPY 합성 칼라(ATM 풋 매수 + 5%OTM 콜 매도, 매월 첫 거래일 롤)로 "
    "방어한다고 가정했을 때 '지금 이 순간'의 헤지 상태입니다. 실제 옵션 시세가 아니라 Black-Scholes "
    "합성가격(내재변동성 대리치=VIX/100, 무위험금리=FRED FEDFUNDS)이며, 위 백테스트의 '칼라 헤지 "
    "비교선'과 동일한 방식입니다. 확신도는 **weak**(부트스트랩 90% 신뢰구간이 부호조차 확정 못함, "
    "슬리브 단독 승률 55~59%) — 기본 배분에는 반영되지 않는 참고용 오버레이입니다."
)
collar_state = compute_live_collar_state()
if collar_state is None:
    st.info("SPY/VIX 데이터를 불러오지 못해 계산할 수 없습니다.")
else:
    collar_live_cols = st.columns(4)
    with collar_live_cols[0]:
        render_metric_card("이번 롤 시작일", collar_state["roll_date"])
    with collar_live_cols[1]:
        render_metric_card("만기까지 거래일", f"{collar_state['days_remaining']}일")
    with collar_live_cols[2]:
        render_metric_card("풋 행사가 / 콜 행사가", f"${collar_state['put_strike']:,.0f} / ${collar_state['call_strike']:,.0f}")
    with collar_live_cols[3]:
        pnl = collar_state["mark_to_model_pnl_pct_of_satellite_notional"]
        render_metric_card(
            "이번 사이클 마크투모델 손익", f"{pnl:+.3f}%p",
            sublabel="포트폴리오 전체 비중 기준", tone="good" if pnl >= 0 else "bad",
        )
    st.caption(
        f"SPY {collar_state['spy_at_roll']:,.2f} (롤 시점) → {collar_state['spy_now']:,.2f} (현재), "
        f"내재변동성(VIX/100) {collar_state['implied_vol_at_roll']:.1%} → {collar_state['implied_vol_now']:.1%}."
    )

final_config = load_final_config()
options_overlay = final_config.get("options_overlay", {})
if options_overlay:
    with st.expander("리서치 원문 결론 (report_data.json::options_overlay)"):
        st.markdown(f"- **적용 범위**: {options_overlay.get('inclusion', 'N/A')}")
        st.markdown(f"- **수단**: {options_overlay.get('instrument', 'N/A')}")
        st.markdown(f"- **결론**: {options_overlay.get('verdict', 'N/A')}")

# ----------------------------------------------------------------------------
# 보유종목 상관관계 + 새틀라이트 실적 발표 예정 (2026-09-18 추가)
#
# core.portfolio(내 실제 보유종목)/core.backtest_engine(전략 라이브러리 간)이 이미 하는 상관관계
# 계산을 그대로 재사용한다 — "지금 챔피언 전략이 추천 중인" 코어+새틀라이트가 실제로 분산돼
# 있는지는 이 엔진 자체에서는 아직 아무도 확인할 방법이 없었다. get_current_holdings()는 새로
# 스캔하지 않고 스케줄러가 매일 00:10에 저장해둔 신호 캐시만 읽으므로 페이지 로드가 무겁지 않다.
# ----------------------------------------------------------------------------
st.markdown("## 5. 보유종목 상관관계 & 새틀라이트 실적 발표")

_current_holdings = get_current_holdings()
if _current_holdings is None:
    st.caption(
        "⚠️ 아직 신호 캐시가 없습니다 — 서버의 champion_signal_alert_job(매일 00:10 KST)이 최소 "
        "한 번 실행된 뒤에 확인할 수 있습니다."
    )
else:
    corr_col, earnings_col = st.columns(2)

    with corr_col:
        st.markdown("**보유종목 간 상관관계 (최근 1년 일간수익률)**")
        st.caption(f"코어 {_current_holdings['core_top4']} + 새틀라이트 {_current_holdings['satellite_selected']}")
        corr_result = compute_champion_correlation()
        if corr_result["correlation"].empty:
            st.caption("상관관계를 계산할 만큼 종목이 충분하지 않습니다 (2종목 이상 필요).")
        else:
            fig_champion_corr = go.Figure(
                data=go.Heatmap(
                    z=corr_result["correlation"].values,
                    x=corr_result["correlation"].columns.tolist(),
                    y=corr_result["correlation"].index.tolist(),
                    zmin=-1, zmax=1, colorscale="RdBu_r",
                )
            )
            fig_champion_corr.update_layout(height=350, margin=dict(l=10, r=10, t=10, b=10))
            st.plotly_chart(fig_champion_corr, use_container_width=True)
            if st.button("💾 이 상관관계를 이력에 저장", key="save_champion_corr"):
                save_champion_correlation_snapshot(corr_result["correlation"])
                st.toast("상관관계 스냅샷을 저장했습니다.", icon="✅")
                st.rerun()

        champion_corr_history = list_champion_correlation_snapshots()
        if champion_corr_history:
            st.caption("이력 (서버가 매일 00:11 KST에 자동으로도 저장합니다 — 이번 달만 보고 판단하지 마세요)")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "체크 시각": h["computed_at"], "종목 수": len(h["labels"]),
                            "평균 상관관계": h["avg_correlation"], "최대 상관관계": h["max_correlation"],
                        }
                        for h in champion_corr_history
                    ]
                ),
                use_container_width=True, hide_index=True,
            )

    with earnings_col:
        st.markdown("**새틀라이트 실적 발표 예정 (5거래일 이내)**")
        st.caption("코어는 전부 ETF라 개별 기업 실적이 없습니다 — 대상은 새틀라이트 종목뿐입니다.")
        if not _current_holdings["satellite_selected"]:
            st.caption("현재 새틀라이트 보유 종목이 없습니다.")
        else:
            upcoming_earnings = get_upcoming_earnings(_current_holdings["satellite_selected"], within_days=5)
            if not upcoming_earnings:
                st.caption("5거래일 이내 예정된 실적 발표가 없습니다.")
            else:
                st.dataframe(
                    pd.DataFrame(upcoming_earnings).rename(columns={"ticker": "티커", "earnings_date": "실적 발표 예정일"}),
                    use_container_width=True, hide_index=True,
                )
                st.caption("yfinance 제공 예정일 — 기업이 발표 전 날짜를 바꿀 수 있습니다. 서버가 매일 00:16 KST에도 확인해 텔레그램으로 미리 알립니다.")

    st.divider()
    st.markdown("**주간 보고**")
    st.caption("서버가 매주 일요일 20:20(America/New_York)에 자동으로 보내는 것과 같은 HTML 보고서를 지금 바로 받아볼 수 있습니다.")
    if st.button("📨 지금 주간 보고 보내기", key="send_champion_weekly_report"):
        report_result = send_weekly_report()
        if report_result["sent"]:
            st.toast("텔레그램으로 주간 보고를 보냈습니다.", icon="✅")
        else:
            st.warning("텔레그램 전송에 실패했습니다 (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID 설정을 확인하세요). "
                       f"보고서 파일은 저장됐습니다: {report_result['path']}")

# ----------------------------------------------------------------------------
# 확신도 등급 + 기각된 아이디어
# ----------------------------------------------------------------------------
st.markdown("## 확신도 — 이 시스템의 각 결정이 얼마나 검증됐는가")
st.caption("이 엔진이 스스로 매긴 등급이 아니라, 리서치 프로그램이 순열검정·블록부트스트랩·국면 분해 감사를 거쳐 부여한 등급입니다.")

confidence_table = load_confidence_table()
if confidence_table:
    grade_order = {"robust": 0, "moderate": 1, "weak": 2, "reversed": 3}
    for row in sorted(confidence_table, key=lambda r: grade_order.get(r["grade"], 9)):
        with st.container(border=True):
            st.markdown(f"**{_GRADE_BADGE.get(row['grade'], row['grade'])} — {row['component']}**")
            st.caption(row["note"])
            st.caption(f"근거: {row['source']}")

rejected_ideas = load_rejected_ideas()
if rejected_ideas:
    with st.expander(f"이미 검토했지만 채택하지 않은 아이디어 ({len(rejected_ideas)}개)"):
        st.caption("베타헤지/개별주 전면확장 등 — 이 엔진이 왜 그런 기능을 추천하지 않는지의 근거입니다.")
        for row in rejected_ideas:
            st.markdown(f"**{_GRADE_BADGE.get(row['grade'], row['grade'])} — {row['component']}**")
            st.caption(row["note"])

st.caption(
    "더 자세한 근거는 `docs/reports/research_program_synthesis.html`(리서치 프로그램 전체 종합 리포트)을 참고하세요."
)
