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
from core import portfolio as portfolio_module
from core.portfolio import (
    add_holding,
    aggregate_pnl_by_ticker,
    generate_portfolio_comment,
    generate_thesis_review,
    get_cash_balance,
    get_portfolio_pnl,
    get_portfolio_risk,
    get_recommended_weights,
    get_regime_conditional_correlation,
    list_holdings,
    list_portfolio_correlation_snapshots,
    list_thesis_reviews,
    remove_holding,
    save_portfolio_correlation_snapshot,
    save_thesis_review,
    set_cash_balance,
    update_holding,
    update_holdings,
)
from core.theme import apply_theme
from core.ui_status import render_status_header

init_db()

st.set_page_config(page_title="포트폴리오 관리", page_icon="💼", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()
st.title("💼 포트폴리오 관리")
render_status_header("portfolio")
if not hasattr(portfolio_module, "get_holding_review_actions") or not hasattr(portfolio_module.PortfolioHolding, "strategy_role"):
    st.info("포트폴리오 업데이트를 반영 중입니다. VM 배포 완료 후 새로고침해주세요.")
    st.stop()
get_holding_review_actions = portfolio_module.get_holding_review_actions
STRATEGY_ROLES = portfolio_module.STRATEGY_ROLES
st.caption("실제 보유 종목을 등록하면 손익, 리스크(변동성/상관관계/섹터 집중도)를 분석하고 AI 코멘트를 생성합니다.")

class _SyncEmpty(Exception):
    pass


with st.expander("📋 잔고 한 번에 맞추기 (증권사 앱 잔고 그대로 붙여넣기 — 추천)", expanded=not portfolio_module.list_holdings()):
    st.caption("증권사 앱 잔고 화면의 종목·수량·평균단가와 달러 예수금을 그대로 적으면 보유 기록 전체를 그 상태로 바꿉니다. "
               "적지 않은 종목은 삭제되고, 같은 종목이 여러 줄이면 한 줄로 합쳐집니다(중복 입력 방지). 평균단가는 생략하면 기존 기록을 씁니다.")
    _cur = portfolio_module.list_holdings()
    _qty: dict[str, float] = {}
    for _h in _cur:
        _qty[_h["ticker"]] = _qty.get(_h["ticker"], 0.0) + float(_h["quantity"])
    if _qty:
        st.caption("지금 기록(참고용 — 이 숫자가 아니라 증권사 앱의 실제 수량을 적으세요): "
                   + ", ".join(f"{t} {q:g}주" for t, q in sorted(_qty.items())))
    sync_text = st.text_area("증권사 앱의 실제 종목 수량 [평균단가] — 한 줄에 한 종목", value="", height=160,
                             placeholder="XLK 1 201.30\nXLE 3\nXLV 1 167.91")
    sync_cash = st.number_input("달러 예수금(현금, $)", min_value=0.0, step=10.0, value=float(get_cash_balance()), key="sync_cash")
    try:
        if not sync_text.strip():
            st.info("증권사 앱 잔고 화면을 보고 실제 종목·수량을 위 칸에 적으면 바뀔 내용이 미리 보입니다.")
            raise _SyncEmpty
        _rows = portfolio_module.parse_balance_text(sync_text)
        _plan = portfolio_module.plan_balance_sync(_rows, _cur)
        _changes = [p for p in _plan if p["action"] != "유지"]
        st.dataframe(pd.DataFrame([{"종목": p["ticker"], "할 일": p["action"],
                                    "지금 기록": f"{p['quantity_before']:g}주 ({p['rows_before']}줄)" if p["rows_before"] else "—",
                                    "바꿀 수량": f"{p['quantity_after']:g}주" if p["quantity_after"] else "—"} for p in _plan]),
                     use_container_width=True, hide_index=True)
        _dups = [p["ticker"] for p in _plan if p["rows_before"] > 1]
        if _dups:
            st.warning(f"같은 종목이 여러 줄로 입력돼 있습니다: {', '.join(_dups)} — 저장하면 한 줄로 합칩니다. 수량이 실제와 맞는지 확인하세요.")
        if st.button("✅ 이대로 맞추기", type="primary", disabled=not _changes and abs(sync_cash - get_cash_balance()) < 0.005):
            portfolio_module.sync_balance(_rows, sync_cash)
            st.toast("보유와 현금 잔고를 맞췄습니다. 챔피언 전략 주문 목록도 이 기준으로 다시 계산됩니다.", icon="✅")
            st.rerun()
    except _SyncEmpty:
        pass
    except ValueError as _e:
        st.error(str(_e))

with st.expander("➕ 보유 종목 추가"):
    with st.form("add_holding_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns(4)
        new_ticker = c1.text_input("티커")
        new_qty = c2.number_input("수량", min_value=0.0, step=1.0)
        new_price = c3.number_input("매입 단가($)", min_value=0.0, step=1.0)
        new_date = c4.date_input("매입일", value=date.today(), max_value=date.today())
        new_role = st.selectbox("운용 구분", ["자동 분류", *STRATEGY_ROLES],
                                help="자동 분류는 코어 ETF만 코어로 분류합니다. 새틀라이트 매입은 직접 새틀라이트를 선택하세요.")
        new_thesis = st.text_area(
            "매매근거 (선택)",
            placeholder="왜 이 매매를 선택했는지 적어두면, 나중에 '매매근거 검증'에서 논리가 실제로 맞았는지 되짚어볼 수 있습니다.",
            height=80,
        )
        add_submitted = st.form_submit_button("추가")

    if add_submitted:
        if new_ticker.strip().upper() in {h["ticker"] for h in portfolio_module.list_holdings()}:
            st.warning(f"{new_ticker.strip().upper()} 는 이미 보유 기록이 있어 수량이 합산됩니다. 같은 매수를 두 번 넣은 게 아니라면 괜찮고, "
                       "헷갈리면 위 '📋 잔고 한 번에 맞추기'로 실제 잔고를 맞추세요.")
        try:
            add_holding(new_ticker, new_qty, new_price, new_date, thesis=new_thesis,
                        strategy_role=None if new_role == "자동 분류" else new_role)
            st.toast(f"{new_ticker.strip().upper()} 추가 완료.", icon="✅")
            st.rerun()
        except ValueError as e:
            st.error(str(e))

with st.expander("💵 현금 잔고"):
    st.caption("계좌에 남아있는 현금 잔고를 입력하면, 챔피언 전략 페이지의 리밸런싱 비교에서 총 계좌가치에 반영됩니다.")
    with st.form("cash_balance_form"):
        new_cash_balance = st.number_input(
            "현금 잔고($)", min_value=0.0, step=100.0, value=get_cash_balance()
        )
        cash_submitted = st.form_submit_button("저장")

    if cash_submitted:
        try:
            set_cash_balance(new_cash_balance)
            st.toast(f"현금 잔고를 ${new_cash_balance:,.0f}로 저장했습니다.", icon="✅")
            st.rerun()
        except ValueError as e:
            st.error(str(e))

holdings = list_holdings()
if not holdings:
    st.info("아직 등록된 보유 종목이 없습니다. 위에서 추가해주세요.")
    st.stop()

st.markdown("### 보유 종목")
st.caption("6개월 재선정 알림을 받으려면 해당 매입 기록의 운용 구분을 '새틀라이트'로 지정하세요. 일반 종목은 '직접 관리'로 유지합니다.")
st.caption("표의 셀을 직접 고친 뒤 '💾 표 수정 저장'을 누르세요. 5개를 넘는 기록은 표 안에서 스크롤해 볼 수 있습니다. 매매근거와 과거 검증 이력은 유지됩니다.")
holdings_by_id = {h["id"]: h for h in holdings}
table = pd.DataFrame(holdings).set_index("id")[["ticker", "quantity", "purchase_price", "purchase_date", "strategy_role"]]
table["cost_basis"] = table["quantity"] * table["purchase_price"]
table_version = st.session_state.get("holding_table_version", 0)
with st.form("holding_table_form"):
    edited = st.data_editor(
        table, use_container_width=True, hide_index=True, num_rows="fixed",
        height=38 + 35 * min(len(table), 5), row_height=35,
        key=f"holding_table_{table_version}", disabled=["_index", "cost_basis"],
        column_config={
            "ticker": st.column_config.TextColumn("티커", required=True),
            "quantity": st.column_config.NumberColumn("수량", required=True, min_value=0.0),
            "purchase_price": st.column_config.NumberColumn("매입 단가($)", required=True, min_value=0.0),
            "purchase_date": st.column_config.DateColumn("매입일", required=True, max_value=date.today()),
            "strategy_role": st.column_config.SelectboxColumn("운용 구분", options=list(STRATEGY_ROLES), required=True),
            "cost_basis": st.column_config.NumberColumn("매입금액($)", format="%.2f"),
        },
    )
    edit_submitted = st.form_submit_button("💾 표 수정 저장")
if edit_submitted:
    try:
        changes = []
        for id_, row in edited.iterrows():
            original = holdings_by_id[id_]
            record = {c: row[c] for c in ("ticker", "quantity", "purchase_price", "purchase_date", "strategy_role")}
            if any(record[c] != original[c] for c in record):
                changes.append({"id": int(id_), **record})
        if changes:
            update_holdings(changes)
            st.session_state.pop("portfolio_comment", None)
            st.session_state.pop("_job_slot::portfolio_comment", None)
            for row in changes:
                st.session_state.pop(f"_job_slot::thesis_review_{row['id']}", None)
            st.session_state["holding_table_version"] = table_version + 1
            st.toast(f"{len(changes)}개 보유 기록을 수정했습니다.", icon="✅")
            st.rerun()
        else:
            st.info("변경한 내용이 없습니다.")
    except ValueError as e:
        st.error(str(e))

st.markdown("### ⏰ 매입일 기준 재선정·매도 확인")
_due_actions = get_holding_review_actions()
if not _due_actions:
    st.caption("코어·새틀라이트로 지정한 매입 기록 중 현재 재선정 기한이 도래한 기록은 없습니다.")
for _due in _due_actions:
    st.warning(f"{_due['title']} — {_due['detail']}")
    if _due["action"] == "보유 재검토":
        if st.button("리밸런싱·보유 유지 확인", key=f"holding_review_{_due['holding_id']}"):
            update_holding(_due["holding_id"], review_date=date.today())
            st.rerun()
st.caption("보유 유지 확인은 매입일을 바꾸지 않고 다음 재선정 주기만 시작합니다. 매도 체결 후에는 수량을 수정하거나 해당 매입 기록을 삭제하세요.")

with st.expander("🗑️ 보유 기록 삭제"):
    selected_id = st.selectbox(
        "삭제할 보유 기록", list(holdings_by_id),
        format_func=lambda id_: (
            f"{holdings_by_id[id_]['ticker']} · 매입 {holdings_by_id[id_]['purchase_date']:%Y-%m-%d}"
            f" · {holdings_by_id[id_]['quantity']:g}주 · 기록 #{id_}"
        ),
    )
    if st.button("🗑️ 선택한 종목 삭제"):
        remove_holding(selected_id)
        st.session_state["holding_table_version"] = table_version + 1
        st.toast("보유 기록을 삭제했습니다.", icon="🗑️")
        st.rerun()

holdings_key = tuple(sorted((h["id"], h["ticker"], h["quantity"], h["purchase_price"], h["purchase_date"]) for h in holdings))
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

st.caption("같은 티커의 매입 기록을 합산합니다. 매입단가는 수량 가중평균입니다.")
display_df = aggregate_pnl_by_ticker(pnl_df).rename(
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
# 국면별(강세장/약세장/횡보장) 상관관계 — "상관관계 붕괴" 점검
# ============================================================================
st.divider()
st.markdown("### 🌪️ 국면별 상관관계 (상관관계 붕괴 점검)")
st.caption(
    "평상시엔 낮아 보이는 종목 간 상관관계도 약세장(스트레스 이벤트) 때는 다 같이 무너지며 급등할 "
    "수 있습니다 — 위 '종목 간 상관관계'는 전체 기간 평균일 뿐이라 이 현상을 못 잡아냅니다. "
    "약세장 상관관계가 다른 국면보다 뚜렷하게 높다면, 지금 포트폴리오의 다각화가 정작 필요한 "
    "순간(하락장)에는 제대로 작동하지 않을 수 있다는 뜻입니다."
)
regime_correlation = get_regime_conditional_correlation(risk)
if not regime_correlation:
    st.caption("국면별 상관관계를 계산하려면 2종목 이상의 가격 데이터가 필요합니다.")
else:
    regime_cols = st.columns(3)
    for regime_col, regime_label in zip(regime_cols, ("강세장", "약세장", "횡보장")):
        with regime_col:
            st.markdown(f"**{regime_label}**")
            regime_df = regime_correlation.get(regime_label)
            if regime_df is None or regime_df.empty:
                st.caption("데이터 부족")
            else:
                fig_regime_corr = go.Figure(
                    data=go.Heatmap(
                        z=regime_df.values, x=regime_df.columns.tolist(), y=regime_df.index.tolist(),
                        zmin=-1, zmax=1, colorscale="RdBu_r",
                    )
                )
                fig_regime_corr.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig_regime_corr, use_container_width=True)

# ============================================================================
# 상관관계 이력
# ============================================================================
st.markdown("#### 📈 상관관계 이력")
st.caption(
    "이번 달만 보고 종목을 정리하지 마세요 — 최소 2~3개월치 이력을 보고 판단하는 걸 권합니다. "
    "확인할 때마다 아래 버튼으로 저장해 추이를 쌓아보세요."
)
if not risk["correlation"].empty:
    if st.button("💾 이 상관관계를 이력에 저장", key="save_portfolio_corr"):
        save_portfolio_correlation_snapshot(risk["correlation"])
        st.toast("상관관계 스냅샷을 저장했습니다.", icon="✅")
        st.rerun()

portfolio_corr_history = list_portfolio_correlation_snapshots()
if portfolio_corr_history:
    portfolio_history_df = pd.DataFrame(
        [
            {
                "체크 시각": h["computed_at"],
                "종목 수": len(h["labels"]),
                "평균 상관관계": h["avg_correlation"],
                "최대 상관관계": h["max_correlation"],
            }
            for h in portfolio_corr_history
        ]
    )
    st.dataframe(portfolio_history_df, use_container_width=True, hide_index=True)
else:
    st.caption("아직 저장된 이력이 없습니다.")

# ============================================================================
# 포지션 사이징 (변동성 타겟팅 추천 비중)
# ============================================================================
st.divider()
st.markdown("### 💰 추천 비중 (변동성 타겟팅)")
st.caption(
    "종목별 최근 1년 변동성의 역수(inverse-volatility)로 비중을 산정합니다 — 변동성이 큰 종목의 "
    "비중을 낮추고 낮은 종목의 비중을 높여 종목 간 리스크 기여도를 비슷하게 맞추는 방식입니다. "
    "현재 실제 비중과 비교해 참고만 하시고, 투자 조언이 아닙니다."
)
max_weight_pct = st.slider("종목당 최대 비중(%)", min_value=10, max_value=100, value=100, step=5, key="max_weight_pct")
recommended_weights = get_recommended_weights(risk, max_weight=max_weight_pct / 100.0)
if not recommended_weights:
    st.caption("추천 비중을 계산하려면 2종목 이상의 가격 데이터가 필요합니다.")
else:
    current_weights = {
        row["ticker"]: row["weight_pct"] for _, row in pnl_df.iterrows() if pd.notna(row["weight_pct"])
    }
    compare_df = pd.DataFrame(
        [
            {
                "티커": ticker,
                "현재 비중(%)": round(current_weights.get(ticker, 0.0), 1),
                "추천 비중(%)": round(weight * 100, 1),
            }
            for ticker, weight in recommended_weights.items()
        ]
    )
    st.dataframe(compare_df, use_container_width=True, hide_index=True)

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
