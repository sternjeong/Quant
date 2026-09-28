"""포트폴리오 비교 추적 페이지 (2026-09-28 추가).

"내 선택을 고집했으면 지금 얼마인가"와 "그냥 SPY를 샀으면"을 나란히 저장해 두고 시간이 지난 뒤 비교한다.
계산은 core/portfolio_compare.py에 있고 이 파일은 화면만 담당한다 (docs/PORTFOLIO_COMPARISON_SPEC.md).

기존 '포트폴리오 관리'(실제 보유 1벌의 손익·리스크)와 다른 화면이다 — 저쪽은 "지금 들고 있는 것",
여기는 "비교하려고 얼려둔 여러 선택지"다.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 (app/pages/*.py 공통 규칙) ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import portfolio_compare as pc
from core.db import init_db
from core.market_data import get_price_history
from core.theme import apply_theme

init_db()

st.set_page_config(page_title="포트폴리오 비교", page_icon="⚖️", layout="wide")
apply_theme()
st.title("⚖️ 포트폴리오 비교")
st.caption("여러 선택지를 저장해 두고 시간이 지난 뒤 어느 쪽이 나았는지 봅니다. "
           "내 실제 매수와 '그냥 SPY를 샀다면' 같은 가정을 나란히 둘 수 있습니다.")


@st.cache_data(ttl=600, show_spinner="시세를 불러오는 중…")
def _evaluate_all_cached(_cache_key: str) -> list[dict]:
    return pc.evaluate_all()


def _refresh() -> None:
    _evaluate_all_cached.clear()


def _fmt(value, suffix: str = "", digits: int = 2) -> str:
    return "—" if value is None else f"{value:,.{digits}f}{suffix}"


results = _evaluate_all_cached(str(date.today()))

# ---- 요약 표 -------------------------------------------------------------------------------------

if not results:
    st.info("아직 저장된 포트폴리오가 없습니다. 아래 **새 포트폴리오**에서 만들어 보세요.")
else:
    currency = st.radio("기준 통화", ["달러", "원화"], horizontal=True, key="currency")
    is_krw = currency == "원화"
    unit, digits = ("원", 0) if is_krw else ("$", 2)

    rows = []
    for item in results:
        rows.append({
            "이름": item["name"],
            "구분": pc.KIND_LABELS.get(item["kind"], item["kind"]),
            "시작일": item["started_on"],
            "종목": ", ".join(item["tickers"]) or "—",
            f"평가액({unit})": item["value_krw" if is_krw else "value_usd"],
            f"투입원금({unit})": item["cost_krw" if is_krw else "cost_usd"],
            "수익률(%)": item["return_pct_krw" if is_krw else "return_pct_usd"],
            "시간가중(%)": item["twr_pct_krw" if is_krw else "twr_pct_usd"],
            "문제": item["error"] or "",
        })
    table = pd.DataFrame(rows)
    st.dataframe(
        table.style.format({
            f"평가액({unit})": lambda v: _fmt(v, digits=digits),
            f"투입원금({unit})": lambda v: _fmt(v, digits=digits),
            "수익률(%)": lambda v: _fmt(v, "%"),
            "시간가중(%)": lambda v: _fmt(v, "%"),
        }),
        width="stretch", hide_index=True,
    )

    ranked = [r for r in results if r["error"] is None
              and r["twr_pct_krw" if is_krw else "twr_pct_usd"] is not None]
    if len(ranked) >= 2:
        key = "twr_pct_krw" if is_krw else "twr_pct_usd"
        best = max(ranked, key=lambda r: r[key])
        worst = min(ranked, key=lambda r: r[key])
        st.success(f"현재 1등 **{best['name']}** ({best[key]:+.2f}%) · "
                   f"꼴등 **{worst['name']}** ({worst[key]:+.2f}%) · "
                   f"차이 {best[key] - worst[key]:.2f}%p")

    # ---- 비교 그래프 ---------------------------------------------------------------------------

    curves = {r["name"]: r["curve_krw" if is_krw else "curve_usd"] for r in results
              if r["error"] is None and not (r["curve_krw" if is_krw else "curve_usd"]).empty}
    if curves:
        chosen = st.multiselect("그래프에 표시할 포트폴리오", list(curves), default=list(curves))
        figure = go.Figure()
        for name in chosen:
            series = curves[name]
            figure.add_trace(go.Scatter(x=series.index, y=series.values, mode="lines", name=name))
        figure.add_hline(y=0, line_dash="dot", line_color="#888")
        figure.update_layout(height=430, margin=dict(l=10, r=10, t=30, b=10),
                             yaxis_title=f"수익률(%) · {currency} 기준", xaxis_title=None,
                             legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(figure, width="stretch")
        st.caption("각 포트폴리오의 **자기 시작일을 0%로** 놓고 그립니다. 시작일이 다르면 기간도 다르니 위 표의 시작일을 함께 보세요.")

st.caption("⚠️ 배당은 반영하지 않습니다(가격만 봅니다) — SPY처럼 배당이 있는 쪽은 실제보다 낮게 보입니다. "
           "수수료·세금은 입력한 값만 반영합니다.")

st.divider()

# ---- 새 포트폴리오 -------------------------------------------------------------------------------

with st.expander("➕ 새 포트폴리오 만들기", expanded=not results):
    tab_manual, tab_quick = st.tabs(["직접 입력", "그냥 ~를 샀다면"])

    with tab_manual:
        with st.form("create_manual"):
            name = st.text_input("이름", placeholder="예: 내 실제 포트폴리오")
            columns = st.columns(2)
            started_on = columns[0].date_input("시작일", value=date.today() - timedelta(days=30))
            kind = columns[1].selectbox("구분", pc.KINDS,
                                        format_func=lambda k: pc.KIND_LABELS[k])
            note = st.text_input("메모(선택)", placeholder="왜 이렇게 담았는지")
            st.caption("아래에 종목을 적습니다. 주수는 매수 양수 · 매도 음수, 단가는 **달러** 기준입니다.")
            seed = st.data_editor(
                pd.DataFrame([{"티커": "", "날짜": started_on, "주수": 0.0, "단가(USD)": 0.0, "수수료(USD)": 0.0}]),
                num_rows="dynamic", width="stretch", key="seed_rows",
                column_config={"날짜": st.column_config.DateColumn(format="YYYY-MM-DD")},
            )
            if st.form_submit_button("만들기", type="primary"):
                try:
                    valid = [r for _, r in seed.iterrows()
                             if str(r["티커"]).strip() and float(r["주수"] or 0) != 0]
                    if not valid:
                        raise ValueError("종목을 한 줄 이상 채우세요(티커와 주수).")
                    portfolio_id = pc.create_portfolio(name, started_on, kind, note)
                    for row in valid:
                        pc.add_trade(portfolio_id, row["티커"], row["날짜"], float(row["주수"]),
                                     float(row["단가(USD)"]), float(row["수수료(USD)"] or 0))
                    _refresh()
                    st.success(f"'{name}' 저장했습니다.")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001 — 입력 오류를 그대로 보여준다
                    st.error(str(exc))

    with tab_quick:
        st.caption("금액만 주면 그날 종가로 주수를 계산해 넣습니다. 'SPY를 그냥 샀다면' 같은 비교용입니다.")
        with st.form("create_quick"):
            columns = st.columns(2)
            quick_ticker = columns[0].text_input("티커", value="SPY").strip().upper()
            quick_amount = columns[1].number_input("투자 금액(USD)", min_value=1.0, value=10000.0, step=100.0)
            quick_date = st.date_input("매수일", value=date.today() - timedelta(days=30), key="quick_date")
            quick_name = st.text_input("이름(비우면 자동)", placeholder=f"그냥 {quick_ticker}")
            if st.form_submit_button("만들기", type="primary"):
                try:
                    history = get_price_history(quick_ticker, start=(quick_date - timedelta(days=10)).isoformat(),
                                                end=(quick_date + timedelta(days=10)).isoformat())
                    if history is None or history.empty:
                        raise ValueError(f"{quick_ticker} 시세를 받지 못했습니다.")
                    index = pd.to_datetime(history.index).tz_localize(None)
                    on_or_after = index[index >= pd.Timestamp(quick_date)]
                    if len(on_or_after) == 0:
                        raise ValueError("그 날짜 이후 시세가 없습니다(미래 날짜인지 확인하세요).")
                    fill_day = on_or_after[0]
                    price = float(history.loc[history.index[index == fill_day][0], "Close"])
                    shares = pc.shares_for_amount(price, quick_amount)
                    label = quick_name.strip() or f"그냥 {quick_ticker}"
                    portfolio_id = pc.create_portfolio(label, quick_date, "benchmark",
                                                       f"{quick_amount:,.0f}달러를 {quick_ticker}에 넣었다면")
                    pc.add_trade(portfolio_id, quick_ticker, fill_day.date(), shares, price)
                    _refresh()
                    st.success(f"'{label}' 저장했습니다 — {fill_day.date()} 종가 ${price:,.2f} 기준 {shares:g}주")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))

# ---- 거래 추가·관리 -------------------------------------------------------------------------------

if results:
    st.divider()
    names = {r["name"]: r["id"] for r in results}
    picked = st.selectbox("포트폴리오 선택", list(names), key="manage_pick")
    picked_id = names[picked]

    left, right = st.columns([3, 2])
    with left:
        st.markdown("**거래 내역**")
        trades = pc.list_trades(picked_id)
        if trades:
            st.dataframe(pd.DataFrame([{
                "티커": t["ticker"], "날짜": t["trade_date"],
                "주수": t["shares"], "단가(USD)": t["price_usd"], "수수료": t["fee_usd"], "메모": t["note"] or "",
            } for t in trades]), width="stretch", hide_index=True)
            removable = {f'{t["trade_date"]} {t["ticker"]} {t["shares"]:+g}주': t["id"] for t in trades}
            to_remove = st.selectbox("삭제할 거래", ["(선택 안 함)"] + list(removable), key="trade_delete")
            if to_remove != "(선택 안 함)" and st.button("이 거래 삭제"):
                pc.delete_trade(removable[to_remove])
                _refresh()
                st.rerun()
        else:
            st.info("거래가 없습니다.")

    with right:
        st.markdown("**거래 추가**")
        with st.form("add_trade"):
            add_ticker = st.text_input("티커").strip().upper()
            add_date = st.date_input("날짜", value=date.today())
            add_shares = st.number_input("주수 (매수 +, 매도 −)", value=0.0, step=1.0, format="%.4f")
            add_price = st.number_input("단가(USD)", min_value=0.0, value=0.0, step=1.0, format="%.4f")
            add_fee = st.number_input("수수료(USD)", min_value=0.0, value=0.0, step=0.1, format="%.2f")
            if st.form_submit_button("추가"):
                try:
                    pc.add_trade(picked_id, add_ticker, add_date, add_shares, add_price, add_fee)
                    _refresh()
                    st.success("추가했습니다.")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))

        st.markdown("**목록에서 내리기**")
        st.caption("지우지 않고 숨깁니다 — 기록을 남겨두는 게 이 화면의 목적입니다.")
        if st.button("이 포트폴리오 보관"):
            pc.archive_portfolio(picked_id)
            _refresh()
            st.rerun()

    archived = [p for p in pc.list_portfolios(include_archived=True) if p["archived_at"]]
    if archived:
        with st.expander(f"보관함 ({len(archived)}개)"):
            for item in archived:
                columns = st.columns([4, 1])
                columns[0].write(f'{item["name"]} · 시작 {item["started_on"]}')
                if columns[1].button("되돌리기", key=f'unarchive_{item["id"]}'):
                    pc.archive_portfolio(item["id"], archived=False)
                    _refresh()
                    st.rerun()
