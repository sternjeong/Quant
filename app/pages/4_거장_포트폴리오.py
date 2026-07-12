"""모듈 D: 거장 포트폴리오 추종 페이지.

- 탭1: SEC EDGAR 13F 공시(캐시 우드는 ARK 일별 CSV) 기반으로 유명 펀드매니저의 보유 종목을 추적하고,
  여러 거장을 선택하면 공통으로 보유한 종목(교집합)을 보여준다.
- 탭2: 미국 ETF(SPDR 계열) 구성종목을 자동 연동으로 조회한다.
- 탭3: 자동 연동이 안 되는 ETF(iShares 등)나 국내(한국) ETF/펀드는 CSV/엑셀 파일을 업로드해서 본다.
"""

import sys
from pathlib import Path

# --- sys.path 부트스트랩: 프로젝트 루트를 추가해 core.* 임포트 가능하게 함 (app/pages/*.py 공통 규칙) ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import streamlit as st

from core.db import init_db
from core.etf_holdings import fetch_spdr_etf_holdings, parse_uploaded_holdings
from core import job_manager
from core.guru_tracker import (
    add_custom_guru,
    get_all_gurus,
    get_common_holdings,
    get_guru_holdings,
    get_last_sync_info,
    is_custom_guru,
    remove_custom_guru,
    sync_guru_holdings,
)
from core.theme import apply_theme
from core.watchlist import add_to_watchlist

init_db()

st.set_page_config(page_title="거장 포트폴리오 추종", page_icon="🧠", layout="wide")
apply_theme()
job_manager.render_active_jobs_sidebar()
st.title("🧠 거장 포트폴리오 추종")
st.caption(
    "SEC EDGAR 13F 공시(분기 지연 공시)를 기반으로 유명 펀드매니저의 보유 종목을 추적합니다. "
    "캐시 우드(ARK)는 13F 대신 매일 공개되는 보유내역 CSV를 사용해 더 정밀하게 추적합니다."
)

tab_guru, tab_etf, tab_upload = st.tabs(["🧑‍💼 거장 포트폴리오", "📊 미국 ETF 구성종목", "📁 파일 업로드 (ETF/국내펀드)"])

# ============================================================================
# 탭 1: 거장 포트폴리오 추적 + 공통 매수 종목
# ============================================================================
with tab_guru:
    all_gurus = get_all_gurus()
    last_sync = get_last_sync_info()

    st.markdown("### 추적 거장 목록")
    st.caption("동기화 버튼을 누르면 SEC EDGAR(또는 ARK)에서 최신 보유 종목을 가져와 저장합니다. 13F는 분기마다 지연 공시됩니다.")

    for guru_name, info in all_gurus.items():
        cols = st.columns([2.2, 3, 1.6, 1.2, 0.8])
        cols[0].markdown(f"**{guru_name}**" + (" 🆕" if is_custom_guru(guru_name) else ""))
        cols[1].caption(info["fund_name"] + (" (ARK 일별 CSV)" if info.get("source") == "ark_daily" else " (13F)"))
        sync_date = last_sync.get(guru_name)
        cols[2].caption(f"최근 동기화: {sync_date}" if sync_date else "동기화 안 됨")

        sync_slot = f"guru_sync_{guru_name}"
        if cols[3].button("🔄 동기화", key=f"sync_{guru_name}"):
            job_manager.start(sync_slot, sync_guru_holdings, guru_name, label=f"{guru_name} 동기화")

        sync_job = job_manager.render(sync_slot, running_label=f"{guru_name} 보유 종목을 가져오는 중")
        if sync_job is not None:
            if sync_job.status == "error":
                st.toast(f"{guru_name} 동기화 실패: {sync_job.error}", icon="❌")
            else:
                result = sync_job.result
                st.toast(
                    f"{guru_name}: {result['holding_count']}개 종목 "
                    f"(티커 확인 {result['resolved_ticker_count']}개), 공시일 {result['filing_date']}",
                    icon="✅",
                )
            st.rerun()

        if is_custom_guru(guru_name):
            if cols[4].button("🗑️", key=f"del_guru_{guru_name}", help="추적 목록에서 제거"):
                remove_custom_guru(guru_name)
                st.rerun()

    with st.expander("➕ 다른 펀드매니저 직접 추가 (SEC EDGAR CIK 번호 필요)"):
        st.caption(
            "SEC EDGAR([sec.gov/cgi-bin/browse-edgar](https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany))에서 "
            "운용사명으로 검색하면 CIK 번호를 확인할 수 있습니다."
        )
        with st.form("add_custom_guru_form", clear_on_submit=True):
            c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
            new_name = c1.text_input("거장/펀드매니저 이름")
            new_cik = c2.text_input("CIK 번호", placeholder="예: 0001067983")
            new_fund = c3.text_input("운용사명", placeholder="선택 입력")
            c4.write("")
            c4.write("")
            add_submitted = c4.form_submit_button("추가")
        if add_submitted:
            try:
                add_custom_guru(new_name, new_cik, new_fund)
                st.toast(f"{new_name} 추가 완료.", icon="✅")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    st.divider()

    # ------------------------------------------------------------------
    # 개별 거장 보유 종목
    # ------------------------------------------------------------------
    synced_gurus = [g for g in all_gurus if last_sync.get(g)]

    st.markdown("### 개별 거장 보유 종목")
    if not synced_gurus:
        st.info("아직 동기화된 거장이 없습니다. 위에서 '동기화' 버튼을 눌러주세요.")
    else:
        selected_guru = st.selectbox("거장 선택", synced_gurus)
        holdings = get_guru_holdings(selected_guru)
        if not holdings:
            st.caption("보유 종목 데이터가 없습니다.")
        else:
            df = pd.DataFrame(
                [
                    {
                        "티커": h["ticker"] or "-",
                        "종목명": h["issuer_name"] or "-",
                        "비중(%)": round(h["weight_pct"], 2) if h["weight_pct"] is not None else None,
                        "보유수량": h["shares"],
                        "공시일": h["filing_date"].isoformat() if h["filing_date"] else "-",
                    }
                    for h in holdings
                ]
            )
            st.dataframe(df, use_container_width=True, hide_index=True)

            unresolved = sum(1 for h in holdings if not h["ticker"])
            if unresolved:
                st.caption(f"⚠️ {unresolved}개 종목은 티커를 자동으로 찾지 못해 종목명만 표시됩니다 (우선주/워런트/회사채 등).")

    st.divider()

    # ------------------------------------------------------------------
    # 공통 매수 종목 (교집합)
    # ------------------------------------------------------------------
    st.markdown("### 🔗 공통 매수 종목 (교집합)")
    st.caption("2명 이상의 거장을 선택하면, 선택한 모든 거장이 공통으로 보유한 종목을 보여줍니다.")

    if len(synced_gurus) < 2:
        st.info("교집합을 보려면 최소 2명 이상의 거장을 동기화해주세요.")
    else:
        selected_for_common = st.multiselect(
            "비교할 거장 선택 (2명 이상)", synced_gurus, default=synced_gurus[: min(2, len(synced_gurus))]
        )
        if len(selected_for_common) >= 2:
            common = get_common_holdings(selected_for_common)
            if not common:
                st.warning("선택한 거장들이 공통으로 보유한 종목이 없습니다.")
            else:
                rows = []
                for c in common:
                    rows.append(
                        {
                            "티커": c["ticker"],
                            "보유 거장 수": c["guru_count"],
                            "보유 거장": ", ".join(sorted(c["gurus"].keys())),
                            "합산 비중(%)": round(c["total_weight"], 2),
                        }
                    )
                common_df = pd.DataFrame(rows)
                st.dataframe(common_df, use_container_width=True, hide_index=True)

                add_ticker = st.selectbox("관심 티커에 추가", [c["ticker"] for c in common], key="common_add_ticker")
                if st.button("➕ 관심 티커에 추가", key="common_add_btn"):
                    try:
                        add_to_watchlist(add_ticker, memo=f"거장 공통 보유: {', '.join(selected_for_common)}")
                        st.toast(f"{add_ticker} 관심 티커에 추가 완료.", icon="✅")
                    except ValueError as e:
                        st.error(str(e))
        else:
            st.caption("2명 이상 선택해주세요.")

# ============================================================================
# 탭 2: 미국 ETF 구성종목 (자동 연동, SPDR 계열)
# ============================================================================
with tab_etf:
    st.markdown("### 미국 ETF 구성종목 자동 조회")
    st.caption(
        "SPDR(State Street) 계열 ETF는 매일 공개되는 구성종목 파일을 자동으로 받아옵니다 "
        "(예: SPY, XLK, XLF, XLE, XLV 등 SPDR 섹터 ETF). "
        "iShares/Invesco 등 다른 운용사는 봇 차단 정책 때문에 자동 연동이 어려워, "
        "'파일 업로드' 탭에서 직접 다운로드한 CSV/엑셀 파일로 확인해주세요."
    )

    etf_ticker = st.text_input("ETF 티커", placeholder="예: SPY, XLK, XLF").strip().upper()
    if st.button("🔍 구성종목 조회", disabled=not etf_ticker):
        job_manager.start("etf_holdings", fetch_spdr_etf_holdings, etf_ticker, label=f"{etf_ticker} 구성종목 조회")

    etf_job = job_manager.render("etf_holdings", running_label=f"{etf_ticker} 구성종목을 가져오는 중")
    if etf_job is not None:
        if etf_job.status == "error":
            st.error(f"구성종목 조회 중 오류가 발생했습니다: {etf_job.error}")
        elif etf_job.result.empty:
            st.error(
                f"{etf_ticker}의 구성종목을 자동으로 가져오지 못했습니다. "
                "SPDR 계열 ETF가 아니거나(iShares/Invesco 등) 일시적인 오류일 수 있습니다. "
                "'파일 업로드' 탭을 이용해주세요."
            )
        else:
            st.session_state["etf_df"] = etf_job.result
            st.session_state["etf_ticker_shown"] = etf_ticker

    etf_df = st.session_state.get("etf_df")
    if etf_df is not None and not etf_df.empty:
        st.caption(f"{st.session_state.get('etf_ticker_shown')} 구성종목 (상위 비중순, 총 {len(etf_df)}개)")
        display_df = etf_df.rename(
            columns={"ticker": "티커", "name": "종목명", "weight_pct": "비중(%)", "shares": "보유수량", "sector": "섹터"}
        )
        st.dataframe(display_df, use_container_width=True, hide_index=True)

# ============================================================================
# 탭 3: 파일 업로드 (자동 연동 안 되는 ETF + 국내 ETF/펀드)
# ============================================================================
with tab_upload:
    st.markdown("### CSV/엑셀 파일로 구성종목 확인")
    st.caption(
        "국내(한국) ETF/펀드는 무료 API가 마땅치 않아 CSV/엑셀 파일을 직접 업로드하면 파싱해서 보여드립니다. "
        "iShares 등 자동 연동이 안 되는 미국 ETF도 운용사 홈페이지에서 holdings 파일을 받아 여기에 업로드하면 됩니다. "
        "종목코드/종목명/비중/보유수량 컬럼(한글/영문 모두 지원)을 자동으로 인식합니다."
    )

    uploaded = st.file_uploader("파일 선택 (CSV, XLSX, XLS)", type=["csv", "xlsx", "xls"])
    if uploaded is not None:
        try:
            parsed_df = parse_uploaded_holdings(uploaded.getvalue(), uploaded.name)
        except ValueError as e:
            st.error(str(e))
            parsed_df = None

        if parsed_df is not None:
            if parsed_df.empty:
                st.warning("파일은 읽었지만 표시할 데이터가 없습니다.")
            else:
                st.success(f"{len(parsed_df)}개 종목을 인식했습니다.")
                display_df = parsed_df.rename(
                    columns={
                        "ticker": "티커",
                        "name": "종목명",
                        "weight_pct": "비중(%)",
                        "shares": "보유수량",
                        "sector": "섹터",
                    }
                )
                st.dataframe(display_df, use_container_width=True, hide_index=True)
                st.caption("자동 인식이 틀렸다면 원본 파일의 컬럼명을 표준 이름(티커/종목명/비중/보유수량)에 가깝게 바꿔서 다시 올려보세요.")
