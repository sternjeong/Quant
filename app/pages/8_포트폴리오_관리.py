"""모듈 H: 포트폴리오 관리 페이지.

실제 보유 종목/수량/매입가를 등록하면 실시간 손익, 리스크(변동성/상관관계/섹터 집중도)를 계산하고
AI 코멘트를 생성한다.
"""

import sys
from datetime import date
from pathlib import Path

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 (app/pages/*.py 공통 규칙) ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.db import init_db
from core import job_manager
from core.portfolio import (
    add_holding,
    generate_portfolio_comment,
    generate_thesis_review,
    get_portfolio_pnl,
    get_portfolio_risk,
    list_holdings,
    list_thesis_reviews,
    remove_holding,
    save_thesis_review,
    update_holding,
)
from core.theme import apply_theme

init_db()

st.set_page_config(page_title="포트폴리오 관리", page_icon="💼", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()
st.title("💼 포트폴리오 관리")
st.caption("실제 보유 종목을 등록하면 손익, 리스크(변동성/상관관계/섹터 집중도)를 분석하고 AI 코멘트를 생성합니다.")

with st.expander("➕ 보유 종목 추가"):
    with st.form("add_holding_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns(4)
        new_ticker = c1.text_input("티커")
        new_qty = c2.number_input("수량", min_value=0.0, step=1.0)
        new_price = c3.number_input("매입 단가($)", min_value=0.0, step=1.0)
        new_date = c4.date_input("매입일", value=date.today(), max_value=date.today())
        new_thesis = st.text_area(
            "매매근거 (선택)",
            placeholder="왜 이 매매를 선택했는지 적어두면, 나중에 '매매근거 검증'에서 논리가 실제로 맞았는지 되짚어볼 수 있습니다.",
            height=80,
        )
        add_submitted = st.form_submit_button("추가")

    if add_submitted:
        try:
            add_holding(new_ticker, new_qty, new_price, new_date, thesis=new_thesis)
            st.toast(f"{new_ticker.strip().upper()} 추가 완료.", icon="✅")
            st.rerun()
        except ValueError as e:
            st.error(str(e))

holdings = list_holdings()
if not holdings:
    st.info("아직 등록된 보유 종목이 없습니다. 위에서 추가해주세요.")
    st.stop()

holdings_key = tuple(sorted(id_ for id_ in (h["id"] for h in holdings)))
job_manager.ensure("portfolio_pnl", holdings_key, get_portfolio_pnl, label="실시간 가격 조회")
pnl_job = job_manager.render("portfolio_pnl", running_label="실시간 가격을 가져오는 중")
pnl_df = pnl_job.result

# ============================================================================
# 손익 요약
# ============================================================================
st.markdown("### 보유 종목 손익")

total_value = pnl_df["market_value"].sum(skipna=True)
total_cost = pnl_df["cost_basis"].sum(skipna=True)
total_pnl = total_value - total_cost if total_value else None
total_pnl_pct = (total_pnl / total_cost * 100) if total_pnl is not None and total_cost else None

m1, m2, m3 = st.columns(3)
m1.metric("총 평가금액", f"${total_value:,.0f}")
m2.metric("총 매입금액", f"${total_cost:,.0f}")
m3.metric(
    "총 평가손익",
    f"${total_pnl:,.0f}" if total_pnl is not None else "-",
    delta=f"{total_pnl_pct:+.1f}%" if total_pnl_pct is not None else None,
)

display_df = pnl_df.rename(
    columns={
        "ticker": "티커",
        "quantity": "수량",
        "purchase_price": "매입단가",
        "current_price": "현재가",
        "cost_basis": "매입금액",
        "market_value": "평가금액",
        "pnl": "평가손익",
        "pnl_pct": "손익률(%)",
        "weight_pct": "비중(%)",
    }
)
st.dataframe(display_df, use_container_width=True, hide_index=True)

id_by_ticker = {h["ticker"]: h["id"] for h in holdings}
delete_target = st.selectbox("삭제할 티커 선택", list(id_by_ticker.keys()))
if st.button("🗑️ 선택한 종목 삭제"):
    remove_holding(id_by_ticker[delete_target])
    st.toast(f"{delete_target} 삭제 완료.", icon="🗑️")
    st.rerun()

# ============================================================================
# 매매근거 & 사후 검증
# ============================================================================
st.divider()
st.markdown("### 📝 매매근거 & 검증")
st.caption(
    "매매 시점에 '왜 이 매매를 선택했는지'를 적어두고, 시간이 지난 뒤(예: 한 달 뒤, 분기 뒤 등) "
    "'매매근거 검증'을 누르면 매입가 대비 현재가 변화와 함께 그 논리가 실제로 맞았는지 AI가 "
    "회고해줍니다. 여러 번 검증해도 이전 회고 기록은 그대로 남습니다."
)

for i, h in enumerate(holdings):
    thesis_state_key = f"thesis_edit_{h['id']}"
    st.session_state.setdefault(thesis_state_key, h["thesis"] or "")

    # pnl_df는 get_portfolio_pnl()이 내부에서 다시 list_holdings()를 호출해 만든 것이라 순서가
    # 같아(둘 다 purchase_date desc 정렬), 같은 인덱스로 안전하게 대응시킬 수 있다 — 단, pnl_df 자체에
    # holding id가 없어(compute_pnl이 티커 단위로만 계산) id로 직접 매칭할 수는 없다.
    pnl_row = pnl_df.iloc[i] if i < len(pnl_df) else None
    pnl_suffix = ""
    if pnl_row is not None and pd.notna(pnl_row.get("pnl_pct")):
        pnl_suffix = f" · 손익 {pnl_row['pnl_pct']:+.1f}%"
    thesis_badge = "📝" if h["thesis"] else "◻️"
    expander_label = f"{thesis_badge} {h['ticker']} · 매입 {h['purchase_date']:%Y-%m-%d}{pnl_suffix}"

    with st.expander(expander_label):
        st.text_area(
            "매매근거",
            key=thesis_state_key,
            height=80,
            placeholder="왜 이 매매를 선택했는지 적어주세요 (나중에 검증할 때 이 원문을 근거로 삼습니다).",
        )
        if st.button("💾 매매근거 저장", key=f"save_thesis_{h['id']}"):
            update_holding(h["id"], thesis=st.session_state[thesis_state_key])
            st.toast("매매근거를 저장했습니다.", icon="✅")
            st.rerun()

        st.divider()
        st.markdown("#### 🔍 사후 검증 이력")
        if not h["thesis"]:
            st.info("매매근거를 먼저 저장해야 검증할 수 있습니다.")
        else:
            review_slot = f"thesis_review_{h['id']}"
            if st.button("🔍 매매근거 검증", key=f"verify_{h['id']}"):
                job_manager.start(review_slot, generate_thesis_review, h["id"], label=f"{h['ticker']} 매매근거 검증")

            review_job = job_manager.render(review_slot, running_label="현재가를 조회하고 매매근거를 검증하는 중")
            if review_job is not None:
                if review_job.status == "error":
                    st.error(f"검증 중 오류가 발생했습니다: {review_job.error}")
                else:
                    save_thesis_review(h["id"], h["ticker"], review_job.result)
                    st.toast("매매근거 검증을 저장했습니다.", icon="✅")
                    st.rerun()

            past_reviews = list_thesis_reviews(h["id"])
            if not past_reviews:
                st.caption("아직 검증 이력이 없습니다. 위 버튼을 눌러 첫 검증을 만들어보세요.")
            for rv in past_reviews:
                price_line = (
                    f"매입가 {rv['purchase_price']:,.2f} → 검증 시점 {rv['price_at_review']:,.2f} "
                    f"({rv['price_change_pct']:+.1f}%, {rv['elapsed_days']}일 경과)"
                    if rv["price_at_review"] is not None
                    else f"현재가 조회 실패 ({rv['elapsed_days']}일 경과)"
                )
                st.markdown(f"**{rv['created_at']:%Y-%m-%d %H:%M} 검증** · {price_line}")
                st.caption(f"당시 매매근거: {rv['thesis_snapshot']}")
                st.markdown(rv["review_text"])
                st.divider()

# ============================================================================
# 리스크 분석
# ============================================================================
st.divider()
st.markdown("### 리스크 분석")

job_manager.ensure("portfolio_risk", holdings_key, get_portfolio_risk, pnl_df=pnl_df, label="리스크 지표 계산")
risk_job = job_manager.render("portfolio_risk", running_label="리스크 지표를 계산하는 중 (최근 1년 가격 데이터 조회)")
risk = risk_job.result

r1, r2 = st.columns(2)
with r1:
    st.metric(
        "연환산 변동성 (최근 1년)",
        f"{risk['volatility']:.1f}%" if risk["volatility"] is not None else "산출 불가",
    )

    st.markdown("**섹터 집중도**")
    if risk["sector_concentration"]:
        fig_sector = go.Figure(
            data=[go.Pie(labels=list(risk["sector_concentration"].keys()), values=list(risk["sector_concentration"].values()))]
        )
        fig_sector.update_layout(height=350)
        st.plotly_chart(fig_sector, use_container_width=True)
    else:
        st.caption("섹터 데이터를 계산할 수 없습니다.")

with r2:
    st.markdown("**종목 간 상관관계**")
    if not risk["correlation"].empty:
        fig_corr = go.Figure(
            data=go.Heatmap(
                z=risk["correlation"].values,
                x=risk["correlation"].columns.tolist(),
                y=risk["correlation"].index.tolist(),
                zmin=-1,
                zmax=1,
                colorscale="RdBu_r",
            )
        )
        fig_corr.update_layout(height=350)
        st.plotly_chart(fig_corr, use_container_width=True)
    else:
        st.caption("상관관계를 계산할 만큼 종목이 충분하지 않습니다 (2종목 이상 필요).")

# ============================================================================
# AI 코멘트
# ============================================================================
st.divider()
st.markdown("### 🤖 AI 코멘트")
if st.button("코멘트 생성"):
    job_manager.start("portfolio_comment", generate_portfolio_comment, pnl_df, risk, label="포트폴리오 AI 코멘트")

comment_job = job_manager.render("portfolio_comment", running_label="포트폴리오를 분석하는 중")
if comment_job is not None:
    if comment_job.status == "error":
        st.error(f"코멘트 생성 중 오류가 발생했습니다: {comment_job.error}")
    else:
        st.session_state["portfolio_comment"] = comment_job.result

if "portfolio_comment" in st.session_state:
    st.info(st.session_state["portfolio_comment"])
