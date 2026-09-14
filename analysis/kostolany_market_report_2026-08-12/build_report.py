#!/usr/bin/env python3
"""report_data.json (+ 있으면 hyperparam_grid_results.csv)을 읽어 최종 HTML 리포트를 만든다."""
import json
import os

OUT_DIR = "/workspaces/Quant/analysis/kostolany_market_report_2026-08-12"

with open(f"{OUT_DIR}/report_data.json", encoding="utf-8") as f:
    R = json.load(f)

SECTOR_ORDER = list(R["meta"]["sectors"].keys())
STYLES = ["장기", "스윙"]
GEN_DATE = R["meta"]["generated"]
START_DATE = R["meta"]["start"]

grid_csv_path = f"{OUT_DIR}/hyperparam_grid_results.csv"
HAS_GRID = os.path.exists(grid_csv_path)

import pandas as pd
grid_df = pd.read_csv(grid_csv_path) if HAS_GRID else None


def fnum(v, digits=2, signed=False):
    s = f"{v:,.{digits}f}"
    if signed and v > 0:
        s = "+" + s
    return s


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ---------------------------------------------------------------------------
# 1) 유니버스 표 (10섹터 x 5종목 + S&P500)
# ---------------------------------------------------------------------------
universe_rows = []
for sector in SECTOR_ORDER:
    tickers = R["meta"]["sectors"][sector]
    universe_rows.append(
        f'<tr><td class="sector-name">{esc(sector)}</td>'
        f'<td class="tickers">{" · ".join(f"<span class=\'tk\'>{esc(t)}</span>" for t in tickers)}</td></tr>'
    )
universe_table_html = "\n".join(universe_rows)

# ---------------------------------------------------------------------------
# 2) 전체 종목 데이터 표 (스타일별)
# ---------------------------------------------------------------------------
def build_ticker_table(style):
    rows = []
    for r in R["styles"][style]["tickers"]:
        delta_cls = "pos" if r["excess_cagr"] >= 0 else "neg"
        beat_bh = "●" if r["beats_bh"] else "—"
        beat_bench = "●" if r["beats_bench"] else "—"
        data_attrs = (
            f'data-ticker="{esc(r["ticker"])}" data-cagr="{r["cagr"]}" data-bh_cagr="{r["bh_cagr"]}" '
            f'data-excess_cagr="{r["excess_cagr"]}" data-mdd="{r["mdd"]}" data-bh_mdd="{r["bh_mdd"]}" '
            f'data-sharpe="{r["sharpe"]}" data-bh_sharpe="{r.get("bh_sharpe", 0)}" '
            f'data-trade_count="{r["trade_count"]}" data-beats_bh="{1 if r["beats_bh"] else 0}" '
            f'data-beats_bench="{1 if r["beats_bench"] else 0}"'
        )
        rows.append(
            f"<tr {data_attrs}>"
            f'<td class="tk-cell"><span class="tk-name">{esc(r["ticker"])}</span>'
            f'<span class="tk-sector">{esc(r["sector"])}</span></td>'
            f'<td class="num">{fnum(r["cagr"])}%</td>'
            f'<td class="num">{fnum(r["bh_cagr"])}%</td>'
            f'<td class="num delta {delta_cls}">{fnum(r["excess_cagr"], signed=True)}%p</td>'
            f'<td class="num">{fnum(r["mdd"])}%</td>'
            f'<td class="num">{fnum(r["bh_mdd"])}%</td>'
            f'<td class="num">{fnum(r["sharpe"])}</td>'
            f'<td class="num">{fnum(r.get("bh_sharpe", 0))}</td>'
            f'<td class="num">{r["trade_count"]}</td>'
            f'<td class="ctr">{beat_bh}</td>'
            f'<td class="ctr">{beat_bench}</td>'
            "</tr>"
        )
    return "\n".join(rows)


ticker_table_jangi = build_ticker_table("장기")
ticker_table_swing = build_ticker_table("스윙")

# ---------------------------------------------------------------------------
# 3) 하이퍼파라미터 그리드서치 표 (있으면)
# ---------------------------------------------------------------------------
best_ticker_path = f"{OUT_DIR}/best_combo_per_ticker.csv"
HAS_BEST_TICKER = os.path.exists(best_ticker_path)
best_ticker_df = pd.read_csv(best_ticker_path) if HAS_BEST_TICKER else None

grid_section_html = ""
if HAS_GRID:
    baseline_row = grid_df[
        (grid_df["zone_low"] == 30.0) & (grid_df["zone_high"] == 70.0) &
        (grid_df["vol_ratio_high"] == 1.2) & (grid_df["position_lookback"] == 252)
    ].iloc[0]
    best_row = grid_df.sort_values("mean_sharpe", ascending=False).iloc[0]
    top5 = grid_df.sort_values("mean_sharpe", ascending=False).head(5)

    grid_rows = []
    for _, g in top5.iterrows():
        is_best = g["mean_sharpe"] == best_row["mean_sharpe"]
        grid_rows.append(
            f'<tr class="{"best-row" if is_best else ""}">'
            f'<td class="num">{fnum(g["zone_low"],0)}–{fnum(g["zone_high"],0)}</td>'
            f'<td class="num">{fnum(g["vol_ratio_high"],1)}x</td>'
            f'<td class="num">{int(g["position_lookback"])}일</td>'
            f'<td class="num strong">{fnum(g["mean_sharpe"],3)}</td>'
            f'<td class="num">{fnum(g["mean_cagr"])}%</td>'
            f'<td class="num delta {"pos" if g["mean_excess_cagr_vs_bench"]>=0 else "neg"}">{fnum(g["mean_excess_cagr_vs_bench"],2,True)}%p</td>'
            f'<td class="num">{fnum(g["win_rate_vs_bench_pct"],1)}%</td>'
            f'<td class="num">{fnum(g["index_cagr"])}%</td>'
            f'<td class="num delta {"pos" if g["index_excess_vs_bench"]>=0 else "neg"}">{fnum(g["index_excess_vs_bench"],2,True)}%p</td>'
            "</tr>"
        )
    grid_table_html = "\n".join(grid_rows)

    sharpe_delta = best_row["mean_sharpe"] - baseline_row["mean_sharpe"]
    winrate_delta = best_row["win_rate_vs_bench_pct"] - baseline_row["win_rate_vs_bench_pct"]

    grid_section_html = f"""
    <section class="section" id="tuning">
      <h2><span class="sec-no">06</span> 하이퍼파라미터 튜닝 — 바꾸면 시장을 이길 수 있는가</h2>
      <p class="lede">기본값(52주 위치·저점/고점 30/70·거래량 1.2배)이 구조적 성장주를 너무 일찍 판다는
      가설을 검증하기 위해, 국면 판정 임계값 4개를 {len(grid_df)}가지 조합으로 스윕했다({esc(START_DATE)}~{esc(GEN_DATE)},
      장기 스타일, 유니버스 50종목 + S&amp;P500 동일).</p>

      <div class="callout">
        <div class="callout-title">탐색 결과 요약</div>
        <p>기본값(고점권 임계 70%, 거래량 1.2배, 52주 lookback) 평균 샤프비율
        <strong class="mono">{fnum(baseline_row['mean_sharpe'],3)}</strong> →
        최적 조합(고점권 임계 <strong>{fnum(best_row['zone_low'],0)}/{fnum(best_row['zone_high'],0)}</strong>,
        거래량 <strong>{fnum(best_row['vol_ratio_high'],1)}배</strong>,
        lookback <strong>{int(best_row['position_lookback'])}일</strong>) 평균 샤프비율
        <strong class="mono delta {'pos' if sharpe_delta>=0 else 'neg'}">{fnum(best_row['mean_sharpe'],3)}
        ({fnum(sharpe_delta,3,True)})</strong>로 개선.
        S&amp;P500 대비 승률은 {fnum(baseline_row['win_rate_vs_bench_pct'],1)}% →
        <strong class="mono delta {'pos' if winrate_delta>=0 else 'neg'}">{fnum(best_row['win_rate_vs_bench_pct'],1)}%
        ({fnum(winrate_delta,1,True)}%p)</strong>,
        S&amp;P500 지수 자체 초과 CAGR은 {fnum(baseline_row['index_excess_vs_bench'],2,True)}%p →
        <strong class="mono delta {'pos' if best_row['index_excess_vs_bench']>=0 else 'neg'}">{fnum(best_row['index_excess_vs_bench'],2,True)}%p</strong>로 변화했다.</p>
      </div>

      <div class="table-wrap">
        <table class="data-table grid-table">
          <thead><tr>
            <th>저점/고점권 임계</th><th>거래량 배수</th><th>lookback</th>
            <th>평균 샤프</th><th>평균 CAGR</th><th>평균 초과CAGR<br><span class="th-sub">vs S&amp;P500</span></th>
            <th>승률<br><span class="th-sub">vs S&amp;P500</span></th>
            <th>S&amp;P500 지수<br><span class="th-sub">전략 CAGR</span></th>
            <th>S&amp;P500 지수<br><span class="th-sub">초과CAGR</span></th>
          </tr></thead>
          <tbody>{grid_table_html}</tbody>
        </table>
      </div>
      <p class="fig-caption">상위 5개 조합(평균 샤프비율 기준) — 강조된 행이 최적 조합. 전체 {len(grid_df)}개 조합 결과는
      부록 데이터 참고.</p>

      <h3>왜 이 조합이 통하는가</h3>
      <p>코스톨라니 국면 중 <span class="mono">A3</span>(52주 고점권에서 상승 + 거래량 급증)는 원전 그대로
      "매도 검토"로 분류된다 — 그런데 반도체·빅테크처럼 수년간 구조적으로 우상향하는 종목은 대부분의
      기간을 "52주 고점 부근에서 거래량을 동반해 오르는" 상태로 보낸다. 즉 기본 임계값에서는 진짜 과열이
      아니라 "정상적으로 잘 가는 중"인 국면까지 A3로 잡혀 조기에 팔게 된다. 고점권 임계값을 70%→
      {fnum(best_row['zone_high'],0)}%로 올리고 거래량 조건을 1.2배→{fnum(best_row['vol_ratio_high'],1)}배로
      높이면 "진짜 극단적 과열"만 매도 신호로 걸러져, 구조적 상승 구간에서는 계속 보유하게 된다.
      lookback을 {int(best_row['position_lookback'])}일로 늘린 것도 같은 방향 — 52주(약 252일)보다 긴
      구간의 최고가를 기준으로 삼으면 상승 추세 중에도 "고점권"으로 판정되는 빈도 자체가 줄어든다.</p>

      <p class="caveat">⚠️ 주의: 이 최적 조합은 2015~2026년, 특히 2023년 이후 AI 랠리가 포함된 이 표본
      기간에 대한 <strong>사후 최적화(in-sample) 결과</strong>다. 임계값 4개를 {len(grid_df)}가지로
      돌려 그 중 가장 좋은 것을 골랐으므로, 다중 비교에 따른 과적합(overfitting) 위험이 이론적으로
      존재한다 — 별도의 미표본(out-of-sample) 구간이나 다른 자산군에서 재검증하기 전까지는 "이 조합이
      최선"이 아니라 "이 방향(고점권 기준을 더 엄격하게, 거래량 필터를 더 까다롭게)이 유효하다"는
      가설 확인 수준으로 해석해야 한다.</p>
    </section>
    """

    if HAS_BEST_TICKER:
        semi = best_ticker_df[best_ticker_df["sector"] == "반도체"].sort_values("tuned_sharpe", ascending=False)
        semi_rows = []
        for _, s in semi.iterrows():
            semi_rows.append(
                "<tr>"
                f'<td class="tk-cell"><span class="tk-name">{esc(s["ticker"])}</span></td>'
                f'<td class="num">{fnum(s["baseline_cagr"])}%</td>'
                f'<td class="num strong">{fnum(s["tuned_cagr"])}%</td>'
                f'<td class="num">{fnum(s["bh_cagr"])}%</td>'
                f'<td class="num">{fnum(s["baseline_sharpe"])}</td>'
                f'<td class="num strong">{fnum(s["tuned_sharpe"])}</td>'
                f'<td class="num delta {"pos" if s["tuned_excess_vs_bh"]>=0 else "neg"}">{fnum(s["tuned_excess_vs_bh"],2,True)}%p</td>'
                "</tr>"
            )
        semi_table_html = "\n".join(semi_rows)
        qcom = best_ticker_df[best_ticker_df["ticker"] == "QCOM"].iloc[0]
        nvda = best_ticker_df[best_ticker_df["ticker"] == "NVDA"].iloc[0]

        grid_section_html += f"""
        <h3>실제로 뒤집힌 사례 — 반도체 섹터</h3>
        <p>가장 크게 망가졌던 반도체 섹터에 최적 조합을 적용하면 평균 샤프비율이
        <strong class="mono">0.57 → 0.87</strong>로 뛴다. 개별 종목 단위로 보면:</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>종목</th><th>CAGR<br><span class="th-sub">기본값</span></th>
            <th>CAGR<br><span class="th-sub">튜닝 후</span></th><th>CAGR<br><span class="th-sub">매수보유</span></th>
            <th>샤프<br><span class="th-sub">기본값</span></th><th>샤프<br><span class="th-sub">튜닝 후</span></th>
            <th>매수보유 대비<br><span class="th-sub">튜닝 후 초과CAGR</span></th></tr></thead>
            <tbody>{semi_table_html}</tbody>
          </table>
        </div>
        <p><strong class="mono delta pos">QCOM은 튜닝 후 실제로 매수보유를 이긴다</strong>
        (CAGR {fnum(qcom['baseline_cagr'])}% → {fnum(qcom['tuned_cagr'])}%, 매수보유는 {fnum(qcom['bh_cagr'])}%,
        초과 {fnum(qcom['tuned_excess_vs_bh'],2,True)}%p) — 51개 자산 중 파라미터를 원전 그대로 썼을 때는
        지지 않았던 몇 안 되는 종목이 튜닝 후 격차를 더 벌린 사례다. NVDA는 여전히 매수보유
        ({fnum(nvda['bh_cagr'])}%)에는 못 미치지만 CAGR {fnum(nvda['baseline_cagr'])}% →
        <strong class="mono">{fnum(nvda['tuned_cagr'])}%</strong>, 샤프비율
        {fnum(nvda['baseline_sharpe'])} → <strong class="mono">{fnum(nvda['tuned_sharpe'])}</strong>로
        이 리포트 전체를 통틀어 가장 큰 개선폭을 보였다 — "매도 신호를 더 신중하게" 만든 방향이 옳았다는
        뜻이지만, 11년간 68%를 복리로 낸 자산을 상대로는 잠깐이라도 현금으로 비켜서는 순간 그 자체가
        손해라는 한계도 동시에 보여준다.</p>
        """
else:
    grid_section_html = """
    <section class="section" id="tuning">
      <h2><span class="sec-no">06</span> 하이퍼파라미터 튜닝</h2>
      <p class="lede">그리드서치 실행 결과를 기다리는 중입니다.</p>
    </section>
    """

# ---------------------------------------------------------------------------
# 3.5) 확장 실험 — 추세 필터(trend-gate) + 부분 비중조절(sell_weight) 결합
#      (사용자 추가 요청: "제안한 것들도 반영해서 최대한 시장을 이기는 방법을 계속 찾아봐")
# ---------------------------------------------------------------------------
combined_section_html = ""
HAS_VOL_TARGET = False
tg_summary_path = f"{OUT_DIR}/trend_gate_step2_summary.json"
sw_csv_path = f"{OUT_DIR}/sell_weight_sweep.csv"
final_pt_path = f"{OUT_DIR}/final_recommended_per_ticker.csv"
port_result_path = f"{OUT_DIR}/portfolio_level_result_final.json"
port_curve_path = f"{OUT_DIR}/portfolio_equity_curves_final.json"

HAS_COMBINED = all(os.path.exists(p) for p in [tg_summary_path, sw_csv_path, final_pt_path, port_result_path, port_curve_path])

if HAS_COMBINED:
    with open(tg_summary_path, encoding="utf-8") as f:
        tg = json.load(f)
    sw_df = pd.read_csv(sw_csv_path)
    final_pt = pd.read_csv(final_pt_path)
    with open(port_result_path, encoding="utf-8") as f:
        port = json.load(f)
    with open(port_curve_path, encoding="utf-8") as f:
        port_curve = json.load(f)

    baseline_row3 = grid_df[
        (grid_df["zone_low"] == 30.0) & (grid_df["zone_high"] == 70.0) &
        (grid_df["vol_ratio_high"] == 1.2) & (grid_df["position_lookback"] == 252)
    ].iloc[0]
    tuned_row3 = grid_df.sort_values("mean_sharpe", ascending=False).iloc[0]
    sw_recommended = sw_df[sw_df["sell_weight"] == 0.5].iloc[0]
    sw_max = sw_df[sw_df["sell_weight"] == 0.75].iloc[0]

    ablation_rows_data = [
        ("E0", "기본값 그대로", baseline_row3["mean_sharpe"], baseline_row3["win_rate_vs_bench_pct"],
         baseline_row3["mean_excess_cagr_vs_bench"], baseline_row3["index_cagr"], baseline_row3["index_excess_vs_bench"], False),
        ("E1", "임계값만 튜닝(06장)", tuned_row3["mean_sharpe"], tuned_row3["win_rate_vs_bench_pct"],
         tuned_row3["mean_excess_cagr_vs_bench"], tuned_row3["index_cagr"], tuned_row3["index_excess_vs_bench"], False),
        ("E2", "추세게이트만(기본 임계값+gate)", tg["gate_only"]["mean_sharpe"], tg["gate_only"]["win_rate_vs_bench_pct"],
         tg["gate_only"]["mean_excess_cagr_vs_bench"], tg["gate_only"]["index_cagr"], tg["gate_only"]["index_excess_vs_bench"], False),
        ("E3", "결합(튜닝+게이트)", tg["combined"]["mean_sharpe"], tg["combined"]["win_rate_vs_bench_pct"],
         tg["combined"]["mean_excess_cagr_vs_bench"], tg["combined"]["index_cagr"], tg["combined"]["index_excess_vs_bench"], False),
        ("E4", "결합+비중조절 50% (권장 최종안)", sw_recommended["mean_sharpe"], sw_recommended["win_rate_vs_bench_pct"],
         sw_recommended["mean_excess_cagr_vs_bench"], sw_recommended["index_cagr"], sw_recommended["index_excess_vs_bench"], True),
        ("E4′", "(참고) 비중조절 75% 상한", sw_max["mean_sharpe"], sw_max["win_rate_vs_bench_pct"],
         sw_max["mean_excess_cagr_vs_bench"], sw_max["index_cagr"], sw_max["index_excess_vs_bench"], False),
    ]
    ablation_rows_html = []
    for tag, label, sharpe, winb, mexc, idxc, idxexc, is_final in ablation_rows_data:
        ablation_rows_html.append(
            f'<tr class="{"best-row" if is_final else ""}">'
            f'<td class="tk-cell"><span class="tk-name">{tag}</span> <span class="tk-sector">{esc(label)}</span></td>'
            f'<td class="num">{fnum(sharpe,3)}</td>'
            f'<td class="num">{fnum(winb,1)}%</td>'
            f'<td class="num delta {"pos" if mexc>=0 else "neg"}">{fnum(mexc,2,True)}%p</td>'
            f'<td class="num">{fnum(idxc)}%</td>'
            f'<td class="num delta {"pos" if idxexc>=0 else "neg"}">{fnum(idxexc,2,True)}%p</td>'
            "</tr>"
        )
    ablation_table_html = "\n".join(ablation_rows_html)

    final_sector_only = final_pt[final_pt["sector"] != "S&P500"]
    sector_agg3 = final_sector_only.groupby("sector").agg(
        cagr=("cagr", "mean"), sharpe=("sharpe", "mean"), excess_vs_bench=("excess_vs_bench", "mean"),
    ).round(2).sort_values("excess_vs_bench", ascending=False)
    sector3_rows = []
    for sector, row in sector_agg3.iterrows():
        sector3_rows.append(
            "<tr>"
            f'<td class="tk-cell"><span class="tk-name">{esc(sector)}</span></td>'
            f'<td class="num">{fnum(row["cagr"])}%</td>'
            f'<td class="num">{fnum(row["sharpe"])}</td>'
            f'<td class="num delta {"pos" if row["excess_vs_bench"]>=0 else "neg"}">{fnum(row["excess_vs_bench"],2,True)}%p</td>'
            "</tr>"
        )
    sector3_table_html = "\n".join(sector3_rows)

    semi3 = final_sector_only[final_sector_only["sector"] == "반도체"].sort_values("cagr", ascending=False)
    semi3_rows = []
    for _, s in semi3.iterrows():
        semi3_rows.append(
            "<tr><td class=\"tk-cell\"><span class=\"tk-name\">" + esc(s["ticker"]) + "</span></td>"
            f'<td class="num">{fnum(s["cagr"])}%</td>'
            f'<td class="num">{fnum(s["sharpe"])}</td>'
            f'<td class="num delta {"pos" if s["excess_cagr"]>=0 else "neg"}">{fnum(s["excess_cagr"],2,True)}%p</td>'
            f'<td class="ctr">{"●" if s["beats_bh"] else "—"}</td>'
            "</tr>"
        )
    semi3_table_html = "\n".join(semi3_rows)

    ps, pb, sp = port["portfolio_strategy"], port["portfolio_bh"], port["sp500_bh"]

    # --- H5: 포트폴리오 레벨 변동성 타게팅 (무레버리지) — 사용자 추가 요청("샤프비율을 중요시하며
    # 계속 방법을 찾아봐")에 따른 후속 실험. 개별 종목에 걸면(H1) 평균이 나빠지지만, 이미 분산된
    # 포트폴리오 수익률 자체에 걸면(표준적인 적용 지점) 결과가 완전히 달라진다.
    vt_result_path = f"{OUT_DIR}/vol_target_final_result.json"
    HAS_VOL_TARGET = os.path.exists(vt_result_path)
    vol_target_subsection_html = ""
    if HAS_VOL_TARGET:
        with open(vt_result_path, encoding="utf-8") as f:
            vtr = json.load(f)
        vt_m, no_m, sp_m = vtr["vol_targeted"], vtr["no_overlay"], vtr["sp500_bh"]
        vol_target_subsection_html = f"""
        <h3>포트폴리오 자체에 변동성 타게팅을 걸면 — 레버리지 없이도 시장을 이긴다</h3>
        <p>개별 종목 하나하나에 변동성 타게팅(20일 실현변동성 대비 목표변동성 비율로 비중 조절)을
        걸어봤더니 평균이 오히려 나빠졌다 — NVDA처럼 원래도 고변동성인 구조적 성장주의 노출을
        획일적으로 깎아버려서다. 하지만 <b>이미 50종목으로 분산된 포트폴리오의 일별 수익률 자체</b>에
        같은 기법을 걸면(리스크패리티 펀드들이 실제로 쓰는 표준적인 적용 지점) 전혀 다른 결과가
        나온다. 목표변동성 {fnum(vtr['params']['target_vol'],0)}%, 상한 {fnum(vtr['params']['cap'],1)}배
        (=<b>레버리지 전혀 없음</b>, 실현변동성이 목표보다 낮을 때만 비중을 100%까지 채우고 높을 때는
        줄이기만 함)로 설정하면:</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프비율</th></tr></thead>
            <tbody>
              <tr><td class="tk-cell"><span class="tk-name">변동성타게팅 적용(최종안)</span></td>
                <td class="num strong">{fnum(vt_m['cagr'])}%</td><td class="num strong">{fnum(vt_m['mdd'])}%</td>
                <td class="num strong">{fnum(vt_m['sharpe'])}</td></tr>
              <tr><td class="tk-cell"><span class="tk-name">적용 전(07장 E4 포트폴리오)</span></td>
                <td class="num">{fnum(no_m['cagr'])}%</td><td class="num">{fnum(no_m['mdd'])}%</td>
                <td class="num">{fnum(no_m['sharpe'])}</td></tr>
              <tr><td class="tk-cell"><span class="tk-name">S&amp;P500 매수보유</span></td>
                <td class="num">{fnum(sp_m['cagr'])}%</td><td class="num">{fnum(sp_m['mdd'])}%</td>
                <td class="num">{fnum(sp_m['sharpe'])}</td></tr>
            </tbody>
          </table>
        </div>
        <div class="chart-card">
          <h3>변동성 타게팅 적용 전/후 자산곡선(로그축)</h3>
          <p class="chart-desc">기준 100 · {esc(START_DATE)} ~ {esc(GEN_DATE)}</p>
          <div class="legend">
            <span class="lg-item"><span class="lg-swatch" style="background:var(--blue)"></span>변동성타게팅 적용</span>
            <span class="lg-item"><span class="lg-swatch" style="background:var(--orange)"></span>적용 전(E4 포트폴리오)</span>
            <span class="lg-item"><span class="lg-swatch" style="background:var(--aqua)"></span>S&amp;P500 매수보유</span>
          </div>
          <div id="chart-vol-target-equity"></div>
        </div>
        <p><b>CAGR은 S&amp;P500과 거의 같은데({fnum(vt_m['cagr'])}% vs {fnum(sp_m['cagr'])}%) 샤프비율은
        거의 두 배({fnum(vt_m['sharpe'])} vs {fnum(sp_m['sharpe'])}), MDD는 절반 이하
        ({fnum(vt_m['mdd'])}% vs {fnum(sp_m['mdd'])}%)다.</b> 레버리지를 전혀 쓰지 않고도(상한 1.0배)
        위험조정수익 기준으로는 명확히 시장을 이긴 셈이다 — 지금까지의 실험 중 가장 방어하기 쉬운
        "시장을 이겼다"는 결과다.</p>
        <p class="caveat">⚠️ 다만 이번에도 정직하게 짚을 것: 같은 변동성타게팅을 <b>코스톨라니 신호
        없이 그냥 50종목 매수보유 포트폴리오</b>에 걸어도 거의 동일한 결과가 나온다(CAGR·샤프 차이
        1%p 안쪽). 즉 이 승리의 공로는 <b>"분산 + 변동성 관리"라는 포트폴리오 구성 기법에 있고,
        코스톨라니 국면 매매 신호는 여기에 거의 아무것도 더해주지 않는다</b>(오히려 근소하게 깎아먹는다:
        {fnum(vt_m['cagr'])}% vs 매수보유 버전 CAGR). 이 리포트 전체를 통틀어 내린 가장 중요한 결론은
        <b>"코스톨라니 이론이 시장을 이긴 게 아니라, 표준적인 포트폴리오 리스크관리 기법이 시장을
        이겼다"</b>는 것이다.</p>
        """

    combined_section_html = f"""
    <section class="section" id="combined">
      <h2><span class="sec-no">07</span> 확장 실험 — 추세 필터 + 비중조절을 더하면</h2>
      <p class="lede">09장(구 결론)이 제안한 "구조적 성장주는 매수보유, 박스권 업종은 국면 매매"라는
      하이브리드 아이디어를 실제 규칙으로 구현해 검증했다: <b>장기(252일) ROC로 "이미 강한 추세가
      확정된 구간"을 감지해, 상승 추세 중엔 매도 신호를, 하락 추세 중엔 매수 신호를 무시</b>하고(추세
      게이트), 매도 신호가 떠도 전량 현금화 대신 <b>비중의 절반만 축소</b>하는(부분 비중조절) 두 규칙을
      06장의 튜닝된 임계값 위에 얹었다. 국면 판정에 쓰는 20일 ROC(단기 방향)와는 별개로, 이 게이트는
      252일 ROC(장기 구조적 추세)를 본다 — 서로 다른 시간축의 지표라 중복이 아니다.</p>

      <div class="callout">
        <div class="callout-title">단계별 개선 경로 (ablation)</div>
        <p>기본값 → 임계값 튜닝(06장) → 추세게이트 → 결합 → 비중조절까지 하나씩 더할 때마다
        평균 초과CAGR이 <strong class="mono delta neg">{fnum(baseline_row3['mean_excess_cagr_vs_bench'],2,True)}%p</strong>에서
        <strong class="mono delta pos">{fnum(sw_recommended['mean_excess_cagr_vs_bench'],2,True)}%p</strong>까지 올라오며
        <b>E3 단계에서 처음으로 플러스 전환</b>됐다. S&amp;P500 대비 승률도 10%→{fnum(sw_recommended['win_rate_vs_bench_pct'],1)}%로
        4배 뛰었다.</p>
      </div>

      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>단계</th><th>평균 샤프</th><th>승률<br><span class="th-sub">vs S&amp;P500</span></th>
          <th>평균 초과CAGR<br><span class="th-sub">vs S&amp;P500</span></th>
          <th>S&amp;P500 지수<br><span class="th-sub">전략 CAGR</span></th>
          <th>S&amp;P500 지수<br><span class="th-sub">초과CAGR</span></th></tr></thead>
          <tbody>{ablation_table_html}</tbody>
        </table>
      </div>
      <p class="fig-caption">강조된 행(E4)이 권장 최종안(비중조절 50%). 75%까지 올릴수록(E4′) 계속
      좋아지는 단조 추세가 나오지만, 100%에 가까워질수록 "매도 신호를 사실상 무시하고 최초 매수 후
      영구 보유"에 수렴해 코스톨라니 국면 매매라는 정체성 자체가 사라진다 — 그래서 이론의 전술적
      성격을 지나치게 희석하지 않는 50%를 최종안으로 택했다.</p>

      <p><b>다만 평균은 소수의 대형 승자가 끌어올린 결과다.</b> E4 기준 51개 자산의 <i>중앙값</i>
      초과CAGR은 여전히 <span class="mono delta neg">{fnum(sw_recommended['median_excess_cagr_vs_bench'],2,True)}%p</span>로
      음수다 — "평균적으로 시장을 이긴다"와 "대다수 종목에서 시장을 이긴다"는 다른 말이며, 이 결과는
      전자에 해당한다.</p>

      <h3>반도체 섹터, 이번엔 진짜로 뒤집혔다 — 그런데 이유가 중요하다</h3>
      <p>반도체 섹터 평균 초과CAGR이 06장의 -28.53%p(원전)에서 이번엔
      <strong class="mono delta pos">+26.93%p</strong>로 완전히 뒤집혔다. 종목별로 보면:</p>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>종목</th><th>최종 CAGR</th><th>최종 샤프</th><th>매수보유 대비<br><span class="th-sub">초과CAGR</span></th>
          <th>매수보유<br><span class="th-sub">이겼나</span></th></tr></thead>
          <tbody>{semi3_table_html}</tbody>
        </table>
      </div>
      <p class="caveat">⚠️ 정직하게 짚어야 할 점: NVDA·AMD·TSM 등은 표에서 매수보유 대비 초과CAGR이
      정확히 0에 가깝다 — <b>사이클 매매가 똑똑해져서 이긴 게 아니라, 추세 게이트가 "이 종목은 계속
      오르는 중이니 팔지 마라"고 매도 신호를 거의 다 무력화해서 사실상 매수보유로 수렴한 것</b>이다.
      즉 이 반전은 "국면 매매의 승리"가 아니라 "국면 매매가 자기 한계를 인식하고 올바르게 양보한
      결과"에 가깝다. 실제로 국면 신호가 여전히 능동적으로 작동하는 에너지·리츠·필수소비재 섹터는
      이 결합 전략에서도 초과CAGR이 여전히 음수다(아래 섹터별 표).</p>

      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>업종</th><th>평균 CAGR</th><th>평균 샤프</th><th>평균 초과CAGR<br><span class="th-sub">vs S&amp;P500</span></th></tr></thead>
          <tbody>{sector3_table_html}</tbody>
        </table>
      </div>
      <p class="fig-caption">최종 결합 전략(E4, 비중조절 50%) 기준 업종별 평균. 반도체·임의소비재·SW는
      플러스로 전환됐지만, 에너지·리츠·필수소비재·산업재는 여전히 음수 — 진짜 박스권/경기민감 업종에서는
      추가 튜닝으로도 시장을 이기지 못했다.</p>

      <h3>또 다른 방향: 한 종목이 아니라 포트폴리오로 넓히면</h3>
      <p>지금까지는 종목 하나하나에서 "전략이 그 종목의 매수보유를 이기는가"를 물었다. 관점을 바꿔
      "50종목에 똑같이 나눠 투자하고 각자 신호대로 매매하면, 포트폴리오 전체는 어떨까"를 계산해봤다
      (동일가중, 일별 리밸런싱 근사).</p>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프비율</th></tr></thead>
          <tbody>
            <tr><td class="tk-cell"><span class="tk-name">50종목 포트폴리오 · 전략</span></td>
              <td class="num">{fnum(ps['cagr'])}%</td><td class="num">{fnum(ps['mdd'])}%</td><td class="num strong">{fnum(ps['sharpe'])}</td></tr>
            <tr><td class="tk-cell"><span class="tk-name">50종목 포트폴리오 · 매수보유</span></td>
              <td class="num">{fnum(pb['cagr'])}%</td><td class="num">{fnum(pb['mdd'])}%</td><td class="num strong">{fnum(pb['sharpe'])}</td></tr>
            <tr><td class="tk-cell"><span class="tk-name">S&amp;P500 매수보유</span></td>
              <td class="num">{fnum(sp['cagr'])}%</td><td class="num">{fnum(sp['mdd'])}%</td><td class="num">{fnum(sp['sharpe'])}</td></tr>
          </tbody>
        </table>
      </div>
      <div class="chart-card">
        <h3>50종목 동일가중 포트폴리오 자산곡선(로그축)</h3>
        <p class="chart-desc">기준 100 · {esc(START_DATE)} ~ {esc(GEN_DATE)}</p>
        <div class="legend">
          <span class="lg-item"><span class="lg-swatch" style="background:var(--blue)"></span>포트폴리오 전략</span>
          <span class="lg-item"><span class="lg-swatch" style="background:var(--orange)"></span>포트폴리오 매수보유</span>
          <span class="lg-item"><span class="lg-swatch" style="background:var(--aqua)"></span>S&amp;P500 매수보유</span>
        </div>
        <div id="chart-portfolio-equity"></div>
      </div>
      <p><b>분산하면 타이밍 비용이 거의 사라진다.</b> 종목 단위에서는 전략이 매수보유에 뚜렷이 못
      미치는 경우가 많았지만, 50종목에 나눠 적용하면 포트폴리오 전체 CAGR({fnum(ps['cagr'])}% vs
      {fnum(pb['cagr'])}%)과 샤프비율({fnum(ps['sharpe'])} vs {fnum(pb['sharpe'])})이
      <b>사실상 동률</b>이다 — 종목마다 이탈 타이밍이 달라 손실이 서로 상쇄되기 때문이다.</p>
      <p class="caveat">⚠️ 이 포트폴리오가 S&amp;P500(CAGR {fnum(sp['cagr'])}%, 샤프 {fnum(sp['sharpe'])})을
      크게 앞서는 것은 <b>전략의 성과가 아니라 종목 선정 효과다</b> — 2026년 현재 기준으로 각 업종의
      "대표주"를 골랐기 때문에 NVDA·TSLA 같은 초대형 승자가 동일가중으로 편입돼 있다(생존편향과 같은
      맥락, 11장 한계 참고). 즉 "이 바스켓이 시장을 이겼다"이지 "코스톨라니 매매가 시장을 이겼다"가
      아니다 — 전략의 실제 기여는 "매수보유와 거의 같은 성과를 훨씬 얕은 심리적 부담으로 낼 수 있다"는
      점이다.</p>

      {vol_target_subsection_html}
    </section>
    """

# ---------------------------------------------------------------------------
# JSON 데이터 (JS 차트용)
# ---------------------------------------------------------------------------
if HAS_COMBINED:
    R["portfolio_equity"] = port_curve
if HAS_VOL_TARGET:
    vt_curve_path = f"{OUT_DIR}/vol_target_equity_curves.json"
    if os.path.exists(vt_curve_path):
        with open(vt_curve_path, encoding="utf-8") as f:
            R["vol_target_equity"] = json.load(f)

overall_j = R["styles"]["장기"]["overall"]
overall_s = R["styles"]["스윙"]["overall"]

# ---------------------------------------------------------------------------
# 4) KPI row + 스타일 비교 카드
# ---------------------------------------------------------------------------
oj, os_ = overall_j, overall_s
mdd_improve = round(oj["avg_strategy_mdd"] - oj["avg_bh_mdd"], 2)  # 양수 = 낙폭 완화

def kpi_tile(label, value, value_cls, sub):
    return (f'<div class="kpi-tile"><div class="kpi-label">{esc(label)}</div>'
            f'<div class="kpi-value {value_cls}">{value}</div>'
            f'<div class="kpi-sub">{sub}</div></div>')


kpi_row_html = "\n".join([
    kpi_tile("매수보유 대비 승률 (장기)", f'{fnum(oj["win_rate_vs_bh_pct"],0)}%', "neg",
             f'{int(round(oj["win_rate_vs_bh_pct"]/100*oj["n"]))} / {oj["n"]} 종목'),
    kpi_tile("S&P500 대비 승률 (장기)", f'{fnum(oj["win_rate_vs_bench_pct"],0)}%', "neg",
             f'{int(round(oj["win_rate_vs_bench_pct"]/100*oj["n"]))} / {oj["n"]} 종목'),
    kpi_tile("평균 CAGR 격차", f'{fnum(oj["mean_excess_cagr"],2,True)}%p', "neg",
             f'전략 {fnum(oj["avg_strategy_cagr"])}% · 매수보유 {fnum(oj["avg_bh_cagr"])}%'),
    kpi_tile("S&P500 지수 자체 초과 CAGR", f'{fnum(oj["index_excess_cagr"],2,True)}%p', "neg",
             f'전략 {fnum(oj["index_cagr_strategy"])}% · 매수보유 {fnum(oj["index_cagr_bh"])}%'),
    kpi_tile("평균 MDD 개선폭", f'{fnum(mdd_improve,2,True)}%p', "pos",
             f'전략 {fnum(oj["avg_strategy_mdd"])}% · 매수보유 {fnum(oj["avg_bh_mdd"])}%'),
    kpi_tile("평균 샤프비율", f'{fnum(oj["avg_strategy_sharpe"])}', "neg",
             f'매수보유 평균 {fnum(oj["avg_bh_sharpe"])}'),
])


def style_card(name, ov, pill_note):
    return f"""<div class="style-card">
      <h4>{esc(name)} <span class="style-pill">{esc(pill_note)}</span></h4>
      <div class="style-metric-row"><span>매수보유 대비 승률</span><span class="v">{fnum(ov['win_rate_vs_bh_pct'],1)}%</span></div>
      <div class="style-metric-row"><span>S&amp;P500 대비 승률</span><span class="v">{fnum(ov['win_rate_vs_bench_pct'],1)}%</span></div>
      <div class="style-metric-row"><span>평균 CAGR</span><span class="v">{fnum(ov['avg_strategy_cagr'])}%</span></div>
      <div class="style-metric-row"><span>평균 샤프비율</span><span class="v">{fnum(ov['avg_strategy_sharpe'])}</span></div>
      <div class="style-metric-row"><span>S&amp;P500 지수 CAGR</span><span class="v">{fnum(ov['index_cagr_strategy'])}%</span></div>
    </div>"""


style_compare_html = style_card("장기 투자", oj, "원전 그대로") + style_card("스윙 트레이딩", os_, "모멘텀 추종")

# ---------------------------------------------------------------------------
# 5) 코스톨라니 달걀 다이어그램 (SVG)
# ---------------------------------------------------------------------------
import math as _math

def _pt(cx, cy, rx, ry, deg):
    r = _math.radians(deg)
    return cx + rx * _math.cos(r), cy + ry * _math.sin(r)

_cx, _cy, _rx, _ry = 150, 125, 104, 86
_nodes = [
    ("B3", 90, "패닉 저점", "end", 12, 18),
    ("A1", 150, "저점 조정", "end", -8, 4),
    ("A2", 210, "상승 동행", "end", -8, -4),
    ("A3", 270, "고점 과열", "middle", 0, -14),
    ("B1", 330, "고점 이탈", "start", 8, -4),
    ("B2", 30, "하락 동행", "start", 8, 4),
]
_egg_parts = [
    f'<ellipse cx="{_cx}" cy="{_cy}" rx="{_rx}" ry="{_ry}" fill="none" stroke="var(--hairline)" stroke-width="2"/>'
]
for code, deg, kr, anchor, dx, dy in _nodes:
    x, y = _pt(_cx, _cy, _rx, _ry, deg)
    is_a = code.startswith("A")
    color = "var(--accent)" if is_a else "var(--accent-2)"
    lx, ly = x + dx, y + dy
    _egg_parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6.5" fill="{color}" stroke="var(--surface)" stroke-width="2"/>')
    _egg_parts.append(
        f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" font-size="12.5" font-weight="700" fill="var(--ink)">{code}</text>'
    )
    ly2 = ly + 13
    _egg_parts.append(
        f'<text x="{lx:.1f}" y="{ly2:.1f}" text-anchor="{anchor}" font-size="10.5" fill="var(--ink-muted)">{kr}</text>'
    )
egg_svg = (
    f'<svg viewBox="0 0 300 258" width="260" height="224" role="img" aria-label="코스톨라니 달걀 이론 6국면 순환도">'
    + "".join(_egg_parts)
    + '<text x="150" y="252" text-anchor="middle" font-size="10.5" fill="var(--ink-muted)">'
    "저점(B3)→A1→A2→상승 후 고점(A3)→B1→B2→저점, 시계 반대 방향으로 순환"
    "</text></svg>"
)

# ---------------------------------------------------------------------------
# 6) 결론 서술
# ---------------------------------------------------------------------------
best_grid_note = ""
if HAS_GRID:
    best_row2 = grid_df.sort_values("mean_sharpe", ascending=False).iloc[0]
    best_grid_note = (
        f"06장의 튜닝 결과가 보여주듯 국면 판정 임계값을 조정하면(고점권 기준 70%→{fnum(best_row2['zone_high'],0)}%, "
        f"거래량 조건 1.2배→{fnum(best_row2['vol_ratio_high'],1)}배) 평균 샤프비율이 "
        f"{fnum(overall_j['avg_strategy_sharpe'])}→{fnum(best_row2['mean_sharpe'],2)}로, S&amp;P500 대비 승률이 "
        f"{fnum(overall_j['win_rate_vs_bench_pct'],1)}%→{fnum(best_row2['win_rate_vs_bench_pct'],1)}%로 뚜렷이 개선된다. "
        f"다만 이 튜닝 후에도 평균 초과 CAGR은 여전히 {fnum(best_row2['mean_excess_cagr_vs_bench'],2,True)}%p로 음수다 — "
        f"즉 <b>\"판정을 더 신중하게 만들수록 나아지는 것은 확실하지만, 평균적으로 시장을 이기는 수준까지 개선되지는 않는다\"</b>가 "
        f"더 정확한 요약이다. 다만 QCOM처럼 개별 종목 단위에서는 튜닝 후 실제로 매수보유를 이기는 사례도 확인했다."
    )


# ---------------------------------------------------------------------------
# 7) 크로스전략 검증 — No.05 리포트("강세장엔 평균회귀가 아니라 추세추종")의 듀얼 모멘텀 섹터
# 로테이션을 재구현하고, 07장에서 검증한 변동성타게팅을 이 다른 전략에도 적용해본다(사용자 요청:
# "분산+변동성관리를 기점으로 연구를 이어서").
# ---------------------------------------------------------------------------
mom_verify_path = f"{OUT_DIR}/momentum_rotation_vol_target_final.json"
mom_11etf_results_path = f"{OUT_DIR}/momentum_rotation_vol_target_results.csv"
mom_50u_results_path = f"{OUT_DIR}/momentum_rotation_50universe_results.csv"
HAS_MOMENTUM = all(os.path.exists(p) for p in [mom_verify_path, mom_11etf_results_path, mom_50u_results_path])

momentum_section_html = ""
if HAS_MOMENTUM:
    with open(mom_verify_path, encoding="utf-8") as f:
        mom_final = json.load(f)
    mom11_df = pd.read_csv(mom_11etf_results_path)
    mom50_df = pd.read_csv(mom_50u_results_path)
    mvt, mno, msp = mom_final["vol_targeted"], mom_final["no_overlay"], mom_final["sp500_bh"]

    unbiased_results_path = f"{OUT_DIR}/momentum_rotation_unbiased_results.csv"
    HAS_UNBIASED = os.path.exists(unbiased_results_path)
    unbiased_html = ""
    if HAS_UNBIASED:
        unbiased_df = pd.read_csv(unbiased_results_path)
        with open(f"{OUT_DIR}/momentum_rotation_unbiased_curves.pkl", "rb") as f:
            import pickle
            unbiased_meta = pickle.load(f)

        u_top10 = unbiased_df[(unbiased_df["top_n"] == 10) & (unbiased_df["overlay"] == "none")].iloc[0]
        u_top15 = unbiased_df[(unbiased_df["top_n"] == 15) & (unbiased_df["overlay"] == "none")].iloc[0]
        n_ok, n_sample = len(unbiased_meta["ok_tickers"]), len(unbiased_meta["sample"])

        unbiased_html = f"""
        <h3>실제로 검증해보기 — 사후편향을 뺀 표본이면 얼마나 남는가</h3>
        <p>말로만 caveat하지 않고 직접 확인했다: 2026년 결과를 보고 고른 게 아니라, <b>2015-01-01
        시점에 실제로 S&amp;P500에 속해 있던 {len(unbiased_meta['sample'])}개 종목을 무작위로 뽑아
        (미래 성과와 무관하게, 시드 고정 재현 가능)</b> 같은 로테이션을 그대로 돌렸다. 표본에는
        이후 상장폐지·인수합병된 종목(AVP·WFM·RHT·CBS·WIN 등)도 그대로 포함되며, 이런 종목은
        인수 이후 가격이 동결된 것으로 근사해(실제 인수 프리미엄 등은 반영 못 함) 매매 신호에서
        자연히 배제되게 했다. 가격 데이터가 끝까지 확보된 {n_ok}/{n_sample}종목으로 계산한 결과:</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프비율</th></tr></thead>
            <tbody>
              <tr><td class="tk-cell"><span class="tk-name">Top10, 편향제거 {n_ok}종목</span></td>
                <td class="num">{fnum(u_top10['cagr'])}%</td><td class="num">{fnum(u_top10['mdd'])}%</td>
                <td class="num strong">{fnum(u_top10['sharpe'])}</td></tr>
              <tr><td class="tk-cell"><span class="tk-name">Top15, 편향제거 {n_ok}종목</span></td>
                <td class="num">{fnum(u_top15['cagr'])}%</td><td class="num">{fnum(u_top15['mdd'])}%</td>
                <td class="num strong">{fnum(u_top15['sharpe'])}</td></tr>
              <tr><td class="tk-cell"><span class="tk-name">(참고) 사후편향 50종목, Top10</span></td>
                <td class="num">29.11%</td><td class="num">-29.88%</td><td class="num">1.15</td></tr>
              <tr class="best-row"><td class="tk-cell"><span class="tk-name">S&amp;P500 매수보유</span></td>
                <td class="num">{fnum(msp['cagr'])}%</td><td class="num">{fnum(msp['mdd'])}%</td>
                <td class="num">{fnum(msp['sharpe'])}</td></tr>
            </tbody>
          </table>
        </div>
        <div class="chart-card">
          <h3>편향제거 표본 Top15 모멘텀 로테이션 vs S&amp;P500(로그축)</h3>
          <p class="chart-desc">기준 100 · {esc(START_DATE)} ~ {esc(GEN_DATE)} · 오버레이 없음</p>
          <div class="legend">
            <span class="lg-item"><span class="lg-swatch" style="background:var(--blue)"></span>Top15 모멘텀 로테이션(편향제거)</span>
            <span class="lg-item"><span class="lg-swatch" style="background:var(--aqua)"></span>S&amp;P500 매수보유</span>
          </div>
          <div id="chart-momentum-unbiased-equity"></div>
        </div>
        <p><b>결론: 사후편향을 빼면 우위가 사라진다 — 오히려 진다.</b> CAGR 29.11%(편향 O) →
        {fnum(u_top15['cagr'])}%(편향 제거)로 주저앉고, 이제는 S&amp;P500({fnum(msp['cagr'])}%)에도
        못 미친다. MDD({fnum(u_top15['mdd'])}%)도 S&amp;P500({fnum(msp['mdd'])}%)보다 얕지 않고,
        샤프비율({fnum(u_top15['sharpe'])} vs {fnum(msp['sharpe'])})도 낮다 — CAGR·MDD·샤프
        세 지표 모두에서 진다. 이 편향제거 검증은 이 리포트가 자체 발견한 버그를 고친 뒤의 재계산
        결과이기도 하다 — 처음 이 절을 작성했을 때는 "우위가 절반쯤 남는다"고 잘못 결론 내렸는데,
        원인은 표본 종목 중 하나(2021년 파산 후 재상장한 NE)가 그 시점부터만 데이터가 있어 전체
        백테스트 구간이 2015년이 아니라 2021-06부터로 통째로 잘려나간 구현 버그였다(늦게 상장/
        재상장한 종목 하나 때문에 나머지 67종목의 구간까지 함께 잘리는 문제). 버그를 고쳐 진짜
        2015~2026 전체 구간으로 다시 돌리자 결론이 뒤집혔다. <b>즉 08장 앞부분의 극적인 성과(CAGR
        29%)는 (1) 유니버스를 사후에 승자 위주로 고른 편향과 (2) 계산 구간이 우연히 유리한 시기로
        축소돼 있던 버그, 두 가지가 겹쳐서 만든 결과였고 — 둘 다 제거하면 이 유니버스에서 모멘텀
        로테이션이 시장을 이긴다는 근거는 남지 않는다.</b> (표본 100종목 무작위 추출, 시드 고정 —
        재현 가능. 매달 유니버스를 다시 구성하는 완전한 시점별 추적은 아니고 시작 시점 스냅샷
        기준이라는 한계는 남는다.)</p>
        """

    unbiased_port_summary_path = f"{OUT_DIR}/unbiased_kostolany_portfolio_summary.json"
    unbiased_port_final_path = f"{OUT_DIR}/unbiased_portfolio_final_result.json"
    HAS_UNBIASED_PORTFOLIO = os.path.exists(unbiased_port_summary_path) and os.path.exists(unbiased_port_final_path)
    unbiased_portfolio_html = ""
    if HAS_UNBIASED_PORTFOLIO:
        with open(unbiased_port_summary_path, encoding="utf-8") as f:
            up_summary = json.load(f)
        with open(unbiased_port_final_path, encoding="utf-8") as f:
            up_final = json.load(f)
        up_sp = up_summary["sp500_bh"]
        up_strat_eq = up_summary["no_overlay_equal_strategy"]
        up_final_m = up_final["final"]
        up_final_bh = up_final.get("final_bh")
        up_final_static = up_final.get("final_static_lookahead_reference")
        up_params = up_final.get("params", {})

        unbiased_portfolio_html = f"""
        <h3>07장의 헤드라인 발견도 생존편향이었나 — 직접 검증</h3>
        <p>07장의 가장 자랑스러운 결과("50종목 포트폴리오 + 변동성타게팅 = 레버리지 없이 샤프비율로
        시장을 이긴다, CAGR 12.93% vs 12.08%, 샤프 1.14 vs 0.73")도 그 50종목 유니버스 자체가
        2026년 기준 승자 위주로 골라진 것이었다. 그렇다면 이 발견도 08장 앞부분의 모멘텀 로테이션처럼
        생존편향의 산물이었을 뿐인가? 같은 편향제거 {up_summary['n_tickers']}종목 유니버스에 07장과
        완전히 동일한 파이프라인(E4 코스톨라니 전략 → 포트폴리오 구성 → 변동성타게팅)을 그대로
        걸어 직접 확인했다. 추가로 <code>core.position_sizing.portfolio_volatility_target_weights</code>
        (이 저장소에 이미 구현된 inverse-vol 리스크패리티 가중 함수)로 동일가중을 위험균등가중으로
        바꾸고, 실현변동성 계산에 쓰는 룩백 기간(20일 → {fnum(up_params.get('window', 5), 0)}일)도
        스윕해 더 빠르게 반응하는 쪽이 낫다는 걸 확인했다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프비율</th></tr></thead>
            <tbody>
              <tr><td class="tk-cell"><span class="tk-name">동일가중, 오버레이 없음</span></td>
                <td class="num">{fnum(up_strat_eq['cagr'])}%</td><td class="num">{fnum(up_strat_eq['mdd'])}%</td>
                <td class="num">{fnum(up_strat_eq['sharpe'])}</td></tr>
              <tr class="best-row"><td class="tk-cell"><span class="tk-name">리스크패리티 + 변동성타게팅(최선, 코스톨라니 신호)</span></td>
                <td class="num">{fnum(up_final_m['cagr'])}%</td><td class="num">{fnum(up_final_m['mdd'])}%</td>
                <td class="num strong">{fnum(up_final_m['sharpe'])}</td></tr>
              <tr><td class="tk-cell"><span class="tk-name">리스크패리티 + 변동성타게팅(같은 설정, 신호 없이 매수보유만)</span></td>
                <td class="num">{fnum(up_final_bh['cagr']) if up_final_bh else '—'}%</td>
                <td class="num">{fnum(up_final_bh['mdd']) if up_final_bh else '—'}%</td>
                <td class="num">{fnum(up_final_bh['sharpe']) if up_final_bh else '—'}</td></tr>
              <tr><td class="tk-cell"><span class="tk-name">S&amp;P500 매수보유</span></td>
                <td class="num">{fnum(up_sp['cagr'])}%</td><td class="num">{fnum(up_sp['mdd'])}%</td>
                <td class="num">{fnum(up_sp['sharpe'])}</td></tr>
              <tr><td class="tk-cell"><span class="tk-name">(참고) 07장 사후편향 50종목 최선안</span></td>
                <td class="num">12.93%</td><td class="num">-15.97%</td><td class="num">1.14</td></tr>
            </tbody>
          </table>
        </div>
        <div class="chart-card">
          <h3>편향제거 68종목 · 리스크패리티+변동성타게팅 vs S&amp;P500(로그축)</h3>
          <p class="chart-desc">기준 100 · {esc(START_DATE)} ~ {esc(GEN_DATE)}</p>
          <div class="legend">
            <span class="lg-item"><span class="lg-swatch" style="background:var(--blue)"></span>편향제거 최선안</span>
            <span class="lg-item"><span class="lg-swatch" style="background:var(--aqua)"></span>S&amp;P500 매수보유</span>
          </div>
          <div id="chart-unbiased-portfolio-equity"></div>
        </div>
        <p><b>정답: 생각보다 더 맞았다 — 다만 신호는 여전히 무관하다.</b> 실현변동성 룩백을
        {fnum(up_params.get('window', 5), 0)}일로 줄이면(변동성 급변에 더 빨리 반응) 편향 없는
        유니버스에서도 07장과 거의 같은 결과가 나온다: CAGR은 S&amp;P500({fnum(up_sp['cagr'])}%)과
        거의 같은 <strong class="mono">{fnum(up_final_m['cagr'])}%</strong>인데, MDD는 절반
        수준({fnum(up_final_m['mdd'])}% vs {fnum(up_sp['mdd'])}%), 샤프비율은
        <strong class="mono delta pos">{fnum(up_final_m['sharpe'])}</strong>로 뚜렷이 높다 —
        "CAGR은 그대로, 샤프만 대폭 개선"이라는 07장의 공짜 점심이 생존편향과 무관하게 실재한다.</p>
        <p class="caveat">⚠️ 다만 세 가지는 짚어야 한다. 첫째, <b>이번에도 코스톨라니 신호는
        결과에 거의 기여하지 않는다</b> — 신호 없이 매수보유만 같은 리스크패리티+변동성타게팅에
        넣어도 통계적으로 동일하다(CAGR {fnum(up_final_bh['cagr']) if up_final_bh else '—'}%, 샤프
        {fnum(up_final_bh['sharpe']) if up_final_bh else '—'} — 신호가 없는 쪽이 오히려 근소하게
        낫다). 둘째, 룩백을 20일→{fnum(up_params.get('window', 5), 0)}일로 줄인 것은 이 특정
        표본·기간에서 사후에 스윕해서 찾은 값이다 — 룩백이 짧을수록 변동성 추정이 노이즈에
        민감해지고, 노출 비중을 매일 더 자주 조정해야 해서(실질적으로 포트폴리오 레버리지/현금
        비중을 하루 단위로 리밸런싱) 여기서는 반영하지 않은 거래비용이 실전에서는 더 크게 깎일 수
        있다. 셋째, <code>portfolio_volatility_target_weights</code>는 원래 그 시점의 실시간 추천용
        함수라 전체 구간 데이터를 한 번에 넣는 게 정상 용법인데, 백테스트에 그대로 쓰면 2015년
        비중을 정하는 데 2026년까지의 변동성 정보가 섞이는 룩어헤드가 된다 — 분기마다 트레일링
        1년치로만 재계산하는 롤링 방식으로 다시 확인한 값이 위 표의 최종 수치다(원래 정적 계산은
        샤프 {fnum(up_final_static['sharpe']) if up_final_static else '—'}로 소폭 더 높게 나왔었다 —
        차이는 크지 않지만 이 표는 룩어헤드 없는 더 보수적인 값을 쓴다). 즉 <b>"분산+변동성관리가 위험조정
        수익을 개선한다"는 방향은 이 리포트가 시도한 모든 변형에서 일관되게 살아남은 유일한 결론이고,
        코스톨라니 달걀 이론이 그 개선에 기여한 몫은 처음부터 끝까지 확인되지 않았다.</b> 이 리포트
        전체에서 가장 압축된 결론: <b>사이클을 읽는 재주보다 위험을 분산하고 관리하는 규율이 시장을
        상대로 더 오래 통했다.</b></p>
        """

    bear_summary_path = f"{OUT_DIR}/bear_market_robustness_summary.json"
    bear_results_path = f"{OUT_DIR}/bear_market_robustness_results.csv"
    HAS_BEAR_MARKET = os.path.exists(bear_summary_path) and os.path.exists(bear_results_path)
    bear_market_html = ""
    if HAS_BEAR_MARKET:
        with open(bear_summary_path, encoding="utf-8") as f:
            bear_summary = json.load(f)
        bear_df = pd.read_csv(bear_results_path)
        bear_best = bear_df.sort_values("sharpe", ascending=False).iloc[0]
        bear_sp = bear_summary["sp500_bh"]
        bear_equal = bear_summary["equal_no_overlay"]
        bear_rp = bear_summary["riskparity_no_overlay"]

        bear_market_html = f"""
        <h3>다른 시대에도 통하나 — 닷컴버블과 금융위기가 낀 2000~2012년</h3>
        <p>지금까지의 모든 검증은 2015~2026년(코로나 급락을 빼면 대체로 강세장)에 국한돼 있었다 —
        10장 한계에서부터 지적해 온 표본 기간 편향이다. 마지막으로 이걸 직접 없앴다:
        <b>2000-01-01 시점 실제 S&amp;P500 구성종목</b>(생존편향 없음, 08장과 같은 방법)에서
        무작위로 뽑은 {bear_summary['n_tickers']}종목으로 <b>닷컴버블 붕괴(2000~2002)와
        글로벌 금융위기(2007~2009)가 모두 포함된 2000~2012년</b>을 검증했다. 이 13년은 S&amp;P500이
        사실상 원금도 못 지킨 "잃어버린 10여 년"이다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프비율</th></tr></thead>
            <tbody>
              <tr><td class="tk-cell"><span class="tk-name">S&amp;P500 매수보유</span></td>
                <td class="num">{fnum(bear_sp['cagr'])}%</td><td class="num">{fnum(bear_sp['mdd'])}%</td>
                <td class="num">{fnum(bear_sp['sharpe'])}</td></tr>
              <tr><td class="tk-cell"><span class="tk-name">동일가중 매수보유, 오버레이 없음</span></td>
                <td class="num">{fnum(bear_equal['cagr'])}%</td><td class="num">{fnum(bear_equal['mdd'])}%</td>
                <td class="num">{fnum(bear_equal['sharpe'])}</td></tr>
              <tr><td class="tk-cell"><span class="tk-name">리스크패리티 가중, 오버레이 없음</span></td>
                <td class="num">{fnum(bear_rp['cagr'])}%</td><td class="num">{fnum(bear_rp['mdd'])}%</td>
                <td class="num">{fnum(bear_rp['sharpe'])}</td></tr>
              <tr class="best-row"><td class="tk-cell"><span class="tk-name">리스크패리티 + 변동성타게팅(최선)</span></td>
                <td class="num">{fnum(bear_best['cagr'])}%</td><td class="num">{fnum(bear_best['mdd'])}%</td>
                <td class="num strong">{fnum(bear_best['sharpe'])}</td></tr>
            </tbody>
          </table>
        </div>
        <div class="chart-card">
          <h3>2000~2012년 · 리스크패리티+변동성타게팅 vs S&amp;P500(로그축)</h3>
          <p class="chart-desc">기준 100 · 2000-01 ~ 2012-12 · 닷컴버블(2000~02)·금융위기(2007~09) 포함</p>
          <div class="legend">
            <span class="lg-item"><span class="lg-swatch" style="background:var(--blue)"></span>리스크패리티+변동성타게팅</span>
            <span class="lg-item"><span class="lg-swatch" style="background:var(--aqua)"></span>S&amp;P500 매수보유</span>
          </div>
          <div id="chart-bear-market-equity"></div>
        </div>
        <p><b>이 리포트에서 가장 극적인 격차다.</b> S&amp;P500은 13년간 사실상 제자리(CAGR
        {fnum(bear_sp['cagr'])}%, 그마저도 마이너스)인 반면, 그냥 동일가중으로 나눠 담기만 해도
        CAGR {fnum(bear_equal['cagr'])}%를 냈다 — 닷컴버블이 대형 기술주에 집중된 붕괴였던 만큼,
        시가총액가중 지수(S&amp;P500)가 유독 크게 다친 시기였기 때문이다. 여기에 리스크패리티+
        변동성타게팅까지 더하면 MDD가 {fnum(bear_rp['mdd'])}%(오버레이 없음)에서
        {fnum(bear_best['mdd'])}%까지 얕아진다(S&amp;P500은 {fnum(bear_sp['mdd'])}%). <b>즉
        "분산 + 변동성관리" 조합은 강세장(2015~2026)에서는 위험조정수익을 개선하는 조용한 효과였지만,
        약세장이 낀 구간(2000~2012)에서는 그 자체로 생존 여부를 가르는 압도적인 효과로 나타난다</b> —
        이 리포트가 시도한 모든 검증을 통틀어 가장 강력하고 일관된 결론이다.</p>
        <p class="caveat">⚠️ 이번에도 코스톨라니 신호는 아예 넣지 않았다(순수 매수보유 기준) —
        지금까지 반복 확인된 대로 신호 자체는 결과에 유의미하게 기여하지 않을 것으로 예상되기
        때문이다. 또한 100종목 중 실제 가격 데이터가 끝까지 확보된 건 {bear_summary['n_tickers']}개뿐
        (1990~2000년대 인수합병·상장폐지가 유독 많은 시기라 08장의 68/100보다 유실률이 높다) — 표본
        축소가 결과에 미친 영향은 별도로 통제하지 않았다.</p>
        """

    bear_signal_path = f"{OUT_DIR}/bear_market_signal_comparison.json"
    practical_path = f"{OUT_DIR}/practical_etf_strategy_results.json"
    HAS_PRACTICAL = os.path.exists(practical_path)
    practical_html = ""
    if HAS_PRACTICAL:
        with open(practical_path, encoding="utf-8") as f:
            prac = json.load(f)
        bear_signal_note = ""
        if os.path.exists(bear_signal_path):
            with open(bear_signal_path, encoding="utf-8") as f:
                bsig = json.load(f)
            bear_signal_note = (
                f"참고로 코스톨라니 신호 자체도 이 2000~2012년 구간에 직접 돌려봤다 — 리스크패리티+"
                f"변동성타게팅과 결합했을 때 신호 버전 CAGR {fnum(bsig['vol_target']['w20_tv20.0']['strategy']['cagr'])}%"
                f"/샤프 {fnum(bsig['vol_target']['w20_tv20.0']['strategy']['sharpe'])}, 신호 없는 매수보유 버전 CAGR "
                f"{fnum(bsig['vol_target']['w20_tv20.0']['bh']['cagr'])}%/샤프 {fnum(bsig['vol_target']['w20_tv20.0']['bh']['sharpe'])}"
                f"로, 여기서도 신호가 있는 쪽이 근소하게 더 나쁘다 — 지금까지의 모든 검증과 같은 결론이다."
            )

        p_bull = prac["2015_2026"]
        p_bear = prac["2000_2012"]
        spy_bull_best = max(p_bull["spy_vol_target"].values(), key=lambda m: (m["sharpe"], m["cagr"]))
        etf_bull_best = max(p_bull["sector_vol_target"].values(), key=lambda m: (m["sharpe"], m["cagr"]))
        spy_bear_best = max(p_bear["spy_vol_target"].values(), key=lambda m: (m["sharpe"], m["cagr"]))
        etf_bear_best = max(p_bear["sector_vol_target"].values(), key=lambda m: (m["sharpe"], m["cagr"]))

        practical_html = f"""
        <h3>실전 적용 — 채권 없이 현금 + ETF만으로</h3>
        <p>여기까지의 결론(리스크패리티+변동성타게팅)은 채권을 전혀 쓰지 않는다 — 노출을 줄일 때
        가는 곳은 항상 현금이지 채권이 아니다. 그래서 "채권은 거의 안 사고 현금이나 주식/ETF만
        산다"는 제약과 원래 잘 맞는다. 다만 55~68개 개별 종목에 리스크패리티로 나눠 담는 건
        개인이 실전에서 관리하기 어렵다 — 실제로 살 수 있는 소수의 유동적인 ETF만으로도 같은 효과가
        나는지 두 가지 버전으로 검증했다: <b>(A) SPY 하나 + 현금</b>(가장 단순, 자산 1개만 관리)과
        <b>(B) GICS 섹터 ETF 9~11개 리스크패리티 가중 + 현금</b>(매매는 ETF만, 개인도 충분히
        관리 가능한 수준).</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>구간</th><th>구성</th><th>CAGR</th><th>MDD</th><th>샤프비율</th></tr></thead>
            <tbody>
              <tr><td class="tk-cell"><span class="tk-name">2015~2026(강세장)</span></td>
                <td class="tk-cell">S&amp;P500 매수보유</td>
                <td class="num">{fnum(p_bull['sp500_bh']['cagr'])}%</td><td class="num">{fnum(p_bull['sp500_bh']['mdd'])}%</td>
                <td class="num">{fnum(p_bull['sp500_bh']['sharpe'])}</td></tr>
              <tr class="best-row"><td class="tk-cell"></td>
                <td class="tk-cell"><b>(A) SPY + 현금 (변동성타게팅)</b></td>
                <td class="num">{fnum(spy_bull_best['cagr'])}%</td><td class="num">{fnum(spy_bull_best['mdd'])}%</td>
                <td class="num strong">{fnum(spy_bull_best['sharpe'])}</td></tr>
              <tr><td class="tk-cell"></td>
                <td class="tk-cell">(B) 섹터ETF 리스크패리티 + 현금</td>
                <td class="num">{fnum(etf_bull_best['cagr'])}%</td><td class="num">{fnum(etf_bull_best['mdd'])}%</td>
                <td class="num">{fnum(etf_bull_best['sharpe'])}</td></tr>
              <tr><td class="tk-cell"><span class="tk-name">2000~2012(약세장 포함)</span></td>
                <td class="tk-cell">S&amp;P500 매수보유</td>
                <td class="num">{fnum(p_bear['sp500_bh']['cagr'])}%</td><td class="num">{fnum(p_bear['sp500_bh']['mdd'])}%</td>
                <td class="num">{fnum(p_bear['sp500_bh']['sharpe'])}</td></tr>
              <tr><td class="tk-cell"></td>
                <td class="tk-cell">(A) SPY + 현금 (변동성타게팅)</td>
                <td class="num delta neg">{fnum(spy_bear_best['cagr'],2,True)}%</td><td class="num">{fnum(spy_bear_best['mdd'])}%</td>
                <td class="num">{fnum(spy_bear_best['sharpe'])}</td></tr>
              <tr class="best-row"><td class="tk-cell"></td>
                <td class="tk-cell"><b>(B) 섹터ETF 리스크패리티 + 현금</b></td>
                <td class="num">{fnum(etf_bear_best['cagr'])}%</td><td class="num">{fnum(etf_bear_best['mdd'])}%</td>
                <td class="num strong">{fnum(etf_bear_best['sharpe'])}</td></tr>
            </tbody>
          </table>
        </div>
        <div class="sm-grid">
          <div class="sm-panel">
            <h4>2015~2026(강세장)</h4>
            <p class="sm-sub">SPY+현금 vs 섹터ETF+현금 vs S&amp;P500(로그축)</p>
            <div id="chart-practical-bull"></div>
          </div>
          <div class="sm-panel">
            <h4>2000~2012(약세장 포함)</h4>
            <p class="sm-sub">SPY+현금 vs 섹터ETF+현금 vs S&amp;P500(로그축)</p>
            <div id="chart-practical-bear"></div>
          </div>
        </div>
        <p class="legend">
          <span class="lg-item"><span class="lg-swatch" style="background:var(--blue)"></span>(A) SPY+현금</span>
          <span class="lg-item"><span class="lg-swatch" style="background:var(--orange)"></span>(B) 섹터ETF 리스크패리티+현금</span>
          <span class="lg-item"><span class="lg-swatch" style="background:var(--aqua)"></span>S&amp;P500 매수보유</span>
        </p>
        <p><b>핵심 트레이드오프: 단순함(A) vs 강건함(B).</b> 강세장(2015~2026)에서는 자산 하나(SPY)만
        변동성타게팅해도 CAGR {fnum(spy_bull_best['cagr'])}%로 S&amp;P500({fnum(p_bull['sp500_bh']['cagr'])}%)을
        오히려 이기면서 MDD는 절반 이하다 — 섹터로 나눈 (B)보다도 낫다(집중된 대형 기술주 랠리를
        지수 하나가 더 잘 담기 때문). 그런데 약세장이 낀 2000~2012년에서는 완전히 뒤집힌다 — (A)
        SPY+현금은 아무리 변동성을 잘 관리해도 CAGR이 여전히 마이너스({fnum(spy_bear_best['cagr'],2,True)}%,
        S&amp;P500 자체가 안 오르니 타이밍만으론 답이 없다)인 반면, <b>(B) 섹터ETF로 나눠 담은 쪽은
        CAGR {fnum(etf_bear_best['cagr'])}%로 플러스를 지켰다</b> — 닷컴버블처럼 특정 섹터(기술주)에
        집중된 붕괴에서는 "여러 섹터에 나눠 담는 것" 자체가 핵심 방어선이지, 변동성타게팅은 그 위에
        더하는 보조 장치일 뿐이라는 뜻이다.</p>
        <p class="caveat">⚠️ {esc(bear_signal_note)} <b>실전 결론:</b> 자산 하나만 관리하고 싶다면
        (A)로 충분히 시장을 이길 수 있지만 그건 "이 강세장에 잘 맞았다"는 것이지 보장이 아니다.
        진짜 강건함(어느 시대에도 방어)을 원한다면 <b>(B) 소수의 섹터 ETF(9~11개) + 현금을
        리스크패리티로 나눠 담고 변동성타게팅으로 노출을 조절하는 쪽</b>이 이 리포트가 검증한
        범위에서는 가장 합리적인 실전 구성이다 — 개별 종목 55~68개를 관리할 필요 없이 ETF만으로
        같은 원리를 구현할 수 있다. 코스톨라니 신호(또는 어떤 매매 타이밍 신호든)를 여기에 얹는 것은,
        이 리포트가 시도한 모든 검증에서 도움이 되지 않았다. (B)의 리스크패리티 비중은 위
        생존편향 재검증에서와 같은 이유로 분기마다 트레일링 1년 데이터만으로 재계산하는 롤링
        방식(룩어헤드 없음)으로 다시 확인한 값이다 — 전체 구간을 한 번에 쓰는 정적 계산과 결과
        차이는 크지 않았다.</p>
        """

    regime_results_path = f"{OUT_DIR}/regime_conditional_results.json"
    HAS_REGIME = os.path.exists(regime_results_path)
    regime_html = ""
    if HAS_REGIME:
        with open(regime_results_path, encoding="utf-8") as f:
            regime = json.load(f)
        r_bull, r_bear = regime["2015_2026"], regime["2000_2012"]
        r_bull_dist = r_bull["regime_distribution"]
        r_bull_total = sum(r_bull_dist.values())

        regime_html = f"""
        <h3>사용자 가설 검증 — 시장을 국면으로 나누고 국면별로 다르게 대응하면?</h3>
        <p>"최근엔 반도체를 사는 게 무조건 유리했다 — 이런 상황을 국면(예: 특정 섹터 쏠림)으로
        식별해 그에 맞는 전략을 쓰면 되지 않나"라는 질문을 검증했다. <b>중요한 전제: "반도체가
        좋았다"는 사후 관찰이다.</b> 진짜 검증이 되려면 그 국면을 그 시점에 이미 알 수 있었던
        정보만으로, 그리고 사후에 스윕한 임계값이 아니라 원칙적인 기준으로 판정해야 한다. 그래서
        매 거래일, 섹터별 트레일링 12개월 수익률의 <b>횡단면 z-점수</b>(그날까지의 데이터만 사용)를
        계산해 국면을 3가지로 분류했다: 어떤 섹터든 z-점수가 1(표준적인 "1-시그마 이상치" 기준,
        사후 조정 없음) 이상이면서 시장 전체가 오르는 중이면 <b>"상승-쏠림"</b>, 오르는 중인데
        고르게 오르면 <b>"상승-분산"</b>, 그 외는 <b>"하락"</b>. "상승-쏠림"일 때만 그 이상치
        섹터에 리스크패리티 기본비중 위로 추가 비중(+{fnum(0.5*100,0)}%p)을 얹었다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>구간</th><th>구성</th><th>CAGR</th><th>MDD</th><th>샤프비율</th></tr></thead>
            <tbody>
              <tr><td class="tk-cell"><span class="tk-name">2015~2026(강세장)</span></td>
                <td class="tk-cell">기본(리스크패리티+변동성타게팅)</td>
                <td class="num">{fnum(r_bull['vol_target']['rp_vt']['cagr'])}%</td>
                <td class="num">{fnum(r_bull['vol_target']['rp_vt']['mdd'])}%</td>
                <td class="num">{fnum(r_bull['vol_target']['rp_vt']['sharpe'])}</td></tr>
              <tr class="best-row"><td class="tk-cell"></td>
                <td class="tk-cell"><b>+ 쏠림장 모멘텀 틸트</b></td>
                <td class="num">{fnum(r_bull['vol_target']['tilt_vt']['cagr'])}%</td>
                <td class="num">{fnum(r_bull['vol_target']['tilt_vt']['mdd'])}%</td>
                <td class="num strong">{fnum(r_bull['vol_target']['tilt_vt']['sharpe'])}</td></tr>
              <tr><td class="tk-cell"></td><td class="tk-cell">S&amp;P500 매수보유</td>
                <td class="num">{fnum(r_bull['sp500_bh']['cagr'])}%</td>
                <td class="num">{fnum(r_bull['sp500_bh']['mdd'])}%</td>
                <td class="num">{fnum(r_bull['sp500_bh']['sharpe'])}</td></tr>
              <tr><td class="tk-cell"><span class="tk-name">2000~2012(약세장 포함)</span></td>
                <td class="tk-cell">기본(리스크패리티+변동성타게팅)</td>
                <td class="num">{fnum(r_bear['vol_target']['rp_vt']['cagr'])}%</td>
                <td class="num">{fnum(r_bear['vol_target']['rp_vt']['mdd'])}%</td>
                <td class="num">{fnum(r_bear['vol_target']['rp_vt']['sharpe'])}</td></tr>
              <tr><td class="tk-cell"></td>
                <td class="tk-cell">+ 쏠림장 모멘텀 틸트</td>
                <td class="num">{fnum(r_bear['vol_target']['tilt_vt']['cagr'])}%</td>
                <td class="num">{fnum(r_bear['vol_target']['tilt_vt']['mdd'])}%</td>
                <td class="num">{fnum(r_bear['vol_target']['tilt_vt']['sharpe'])}</td></tr>
              <tr><td class="tk-cell"></td><td class="tk-cell">S&amp;P500 매수보유</td>
                <td class="num">{fnum(r_bear['sp500_bh']['cagr'])}%</td>
                <td class="num">{fnum(r_bear['sp500_bh']['mdd'])}%</td>
                <td class="num">{fnum(r_bear['sp500_bh']['sharpe'])}</td></tr>
            </tbody>
          </table>
        </div>
        <div class="chart-card">
          <h3>국면틸트 vs 기본 리스크패리티 vs S&amp;P500(2015~2026, 로그축)</h3>
          <p class="chart-desc">기준 100 · {esc(START_DATE)} ~ {esc(GEN_DATE)}</p>
          <div class="legend">
            <span class="lg-item"><span class="lg-swatch" style="background:var(--blue)"></span>쏠림장 모멘텀 틸트</span>
            <span class="lg-item"><span class="lg-swatch" style="background:var(--orange)"></span>기본 리스크패리티(틸트 없음)</span>
            <span class="lg-item"><span class="lg-swatch" style="background:var(--aqua)"></span>S&amp;P500 매수보유</span>
          </div>
          <div id="chart-regime-tilt-equity"></div>
        </div>
        <p><b>가설이 실제로 맞았다.</b> 2015~2026년 기준 "상승-쏠림" 국면이 전체 거래일의
        {fnum(100*r_bull_dist.get('상승-쏠림', 0)/r_bull_total, 0)}%를 차지했다 — 최근 몇 년은
        AI/반도체 테마(XLK)가 실제로 거의 항상 통계적 이상치로 앞서 있었다는 뜻이다. 이 국면을
        인과적으로 감지해 그 섹터에 비중을 더 실었더니, 07~08장에서 검증된 "기본" 전략(샤프
        {fnum(r_bull['vol_target']['rp_vt']['sharpe'])})보다 뚜렷이 개선됐다(샤프
        <strong class="mono delta pos">{fnum(r_bull['vol_target']['tilt_vt']['sharpe'])}</strong>,
        S&amp;P500의 {fnum(r_bull['sp500_bh']['sharpe'])}보다도 높다) — CAGR도
        {fnum(r_bull['vol_target']['rp_vt']['cagr'])}% → {fnum(r_bull['vol_target']['tilt_vt']['cagr'])}%로
        S&amp;P500({fnum(r_bull['sp500_bh']['cagr'])}%)에 거의 근접했다. 약세장이 낀
        2000~2012년에서는 개선폭이 거의 없었다({fnum(r_bear['vol_target']['rp_vt']['sharpe'])} →
        {fnum(r_bear['vol_target']['tilt_vt']['sharpe'])}) — 하락 국면에는 애초에 틸트를 걸지
        않도록 설계했으니 자연스러운 결과이고, 적어도 손해는 아니었다.</p>
        <p class="caveat">⚠️ 이 결과가 07~08장의 다른 발견들보다 신뢰도가 높은 이유는 <b>임계값을
        사후에 스윕해서 고르지 않았다</b>는 점이다(z≥1은 통계학의 표준적인 "이상치" 기준을 그대로
        가져다 쓴 것). 다만 한계도 있다: (1) 틸트 대상 섹터를 후보 유니버스(GICS 11개) 안에서만
        고르므로, 후보에 없는 새로운 테마(예: 아직 별도 ETF가 없는 신생 산업)의 쏠림은 못 잡는다.
        (2) 표본이 이 저장소가 우연히 가진 두 시대(2015~2026, 2000~2012)뿐이라 "쏠림 국면에 올라타는
        것"이 다른 시대·다른 시장에서도 통할지는 별도 검증이 필요하다. (3) 거래비용은 여전히
        미반영이다. 그럼에도 <b>이 리포트에서 가장 원칙에 충실하게(사후 스윕 없이) 설계된 개선책이,
        실제로 baseline보다 나은 유일한 능동적 규칙</b>이라는 점은 특기할 만하다 — 지금까지 시도한
        "매매 타이밍" 신호 중 처음으로 baseline 대비 진짜 개선을 보인 사례다.</p>
        """

    # -------------------------------------------------------------------
    # 심층 후속 연구: "대장주(섹터 내 진짜 리더)" 재검증 + 로버스트니스 체크 + 켈리 기준 + 가설 로그
    # -------------------------------------------------------------------
    ledger_paths = {
        "true_leader": f"{OUT_DIR}/hypothesis_true_sector_leader.json",
        "ztest": f"{OUT_DIR}/hypothesis_ztest_sensitivity.json",
        "kelly": f"{OUT_DIR}/hypothesis_kelly_sizing.json",
    }
    HAS_LEDGER = all(os.path.exists(p) for p in ledger_paths.values())
    ledger_html = ""
    if HAS_LEDGER:
        with open(ledger_paths["true_leader"], encoding="utf-8") as f:
            tl = json.load(f)
        with open(ledger_paths["ztest"], encoding="utf-8") as f:
            zt = json.load(f)
        with open(ledger_paths["kelly"], encoding="utf-8") as f:
            ky = json.load(f)

        tl_bull, tl_bear = tl["2015_2026"], tl["2000_2012"]

        def tl_row(name, label, is_best=False):
            b, r = tl_bull["results"][name]["final"], tl_bear["results"][name]["final"]
            cls = "best-row" if is_best else ""
            return (
                f'<tr class="{cls}"><td class="tk-cell"><span class="tk-name">{esc(label)}</span></td>'
                f'<td class="num">{fnum(b["cagr"])}%</td><td class="num">{fnum(b["mdd"])}%</td>'
                f'<td class="num strong">{fnum(b["sharpe"])}</td>'
                f'<td class="num">{fnum(r["cagr"])}%</td><td class="num">{fnum(r["mdd"])}%</td>'
                f'<td class="num strong">{fnum(r["sharpe"])}</td></tr>'
            )

        true_leader_table = (
            tl_row("baseline", "기본(리스크패리티+변동성타게팅)")
            + tl_row("etf_tilt", "+ 섹터 ETF 쏠림 틸트", is_best=True)
            + tl_row("true_sector_leader", "+ 섹터 '내' 진짜 대장주(1종목) 틸트")
        )

        z_rows_bull = "".join(
            f'<tr><td class="num">z≥{fnum(r["z_threshold"],2)}</td><td class="num">{fnum(r["narrow_bull_pct"],1)}%</td>'
            f'<td class="num">{fnum(r["cagr"])}%</td><td class="num">{fnum(r["mdd"])}%</td>'
            f'<td class="num strong">{fnum(r["sharpe"])}</td></tr>'
            for r in zt["2015_2026"]["sweep"]
        )
        z_rows_bear = "".join(
            f'<tr><td class="num">z≥{fnum(r["z_threshold"],2)}</td><td class="num">{fnum(r["narrow_bull_pct"],1)}%</td>'
            f'<td class="num">{fnum(r["cagr"])}%</td><td class="num">{fnum(r["mdd"])}%</td>'
            f'<td class="num strong">{fnum(r["sharpe"])}</td></tr>'
            for r in zt["2000_2012"]["sweep"]
        )

        ky_bull, ky_bear = ky["2015_2026"], ky["2000_2012"]

        # ---- 이 대화 전체를 관통하는 가설 로그 ----
        hypothesis_log = [
            ("코스톨라니 달걀 이론 원전 그대로", "❌ 기각", "51개 자산 중 18%만 매수보유를 이김, 평균적으로 크게 짐", "01~05장"),
            ("하이퍼파라미터 튜닝(임계값 조정)", "🔶 부분채택", "샤프 개선되지만 평균 초과CAGR은 여전히 음수", "06장"),
            ("추세게이트+부분 비중조절(E4)", "🔶 부분채택", "평균 초과CAGR 처음 플러스 전환, 중앙값은 여전히 음수", "07장"),
            ("포트폴리오 변동성타게팅(50종목, 편향 O)", "✅ 채택(단, 편향 의심)", "CAGR 거의 동일·샤프 거의 2배·MDD 절반", "07장"),
            ("모멘텀 섹터 로테이션(No.05 아이디어)", "❌ 기각", "생존편향 제거 + dropna 버그 수정 후 오히려 S&P500에 짐", "08장"),
            ("리스크패리티+변동성타게팅(생존편향 제거, 룩어헤드 제거)", "✅ 채택", "샤프 0.88~0.92, 두 시대 모두 S&P500 상회", "08장"),
            ("실전 ETF화: SPY 하나 + 현금", "🔶 조건부채택", "강세장엔 최고, 약세장 포함 구간엔 CAGR 마이너스 유지", "08장"),
            ("실전 ETF화: 섹터ETF 9~11개 리스크패리티 + 현금", "✅ 채택", "두 시대 모두 안정적, 약세장 포함 구간에서 플러스 유지", "08장"),
            ("리스크패리티 비중의 룩어헤드 편향 자체 점검", "🔶 발견·수정", "영향은 작았음(샤프 0.92→0.88), 결론 불변", "08장"),
            ("국면 분류 + 섹터ETF 쏠림 모멘텀 틸트", "✅ 채택", "두 시대 모두 baseline·S&P500 상회, 유일한 능동적 성공", "08장"),
            ("국면별 상이한 변동성타게팅 목표(약세12%/그외18%)", "✅ 채택", "baseline 대비 MDD 추가 개선", "08장(이번 라운드)"),
            ("개별주(유니버스 전체 무작위 모멘텀) 틸트", "❌ 기각", "쏠림 섹터와 무관한 종목이라 성과 오히려 악화", "08장(이번 라운드)"),
            ("혼합(ETF 절반+무작위 개별주 절반) 틸트", "❌ 기각", "개별주 부분이 성과를 끌어내려 baseline보다도 못함", "08장(이번 라운드)"),
            ("섹터 '내' 진짜 대장주(실제 GICS 매핑) 틸트", "❌ 기각", "제대로 구현해도 2015~26년 크게 뒤짐, 2000~12년만 근소 우위 — 일관성 없음", "08장(이번 라운드)"),
            ("쏠림 임계값(z≥1) 민감도 — z=0.5~2.0", "✅ 로버스트 확인", "전 구간 샤프 0.84~0.85(강세장)·0.21~0.26(약세장) 유지, 사후 스윕 아님", "08장(이번 라운드)"),
            ("켈리 기준(Kelly criterion) 섹터 비중", "❌ 기각", "리스크패리티보다 열세, 약세장 포함 구간엔 심하게 악화(샤프 0.05)", "08장(이번 라운드)"),
            ("진짜 홀드아웃 구간(2013~2014) 검증", "✅ 채택 확인", "어떤 파라미터 결정에도 안 쓰인 구간에서 CAGR 동률·샤프/MDD/Calmar 근소 우위", "08장(세션12)"),
            ("거래비용(회전율 1단위당 2~20bp) 반영", "✅ 로버스트 확인", "현실적 비용(2~5bp)에서 결론 불변, 약세장은 고비용에 더 취약", "08장(세션12)"),
            ("재조정 빈도(매일/매주/매월) 변경", "🔶 비대칭 확인", "강세장은 매일이 최선, 약세장은 매주가 근소 우위 — 사후 스위칭은 하지 않음", "08장(세션12)"),
            ("래거드(꼴찌 섹터) 대칭 언더웨이트", "❌ 기각", "3가지 변형 모두 샤프 차이 0.01~0.02로 노이즈 수준", "08장(세션12)"),
            ("쏠림강세 한정 레버리지 완화(cap 1.0~1.5)", "❌ 기각", "CAGR은 늘지만 MDD도 같이 늘어 샤프·Calmar 개선 없음", "08장(세션12)"),
            ("절대추세필터(SPY 200일선 이탈시 방어)", "🔶 트레이드오프", "약세장엔 뚜렷이 도움, 강세장엔 뚜렷이 손해 — 기본 미탑재, 선택적 보험으로만", "08장(세션13)"),
            ("추세필터 확인형(약세장국면 AND 200일선)", "🔶 트레이드오프 심화", "오탐은 줄지만 두 시대 모두 효과가 더 극단적으로 커짐", "08장(세션13)"),
            ("방어자산(TLT/GLD) 약세장 편입", "🔶 조건부채택(세션14에서 하향)", "두 시대 평균은 순개선이나 2022년처럼 채권-주식 상관관계가 깨지는 해엔 오히려 손해", "08장(세션13→14 수정)"),
            ("방어자산 분해 — TLT vs GLD 기여도", "✅ 로버스트 확인", "금(GLD)이 효과의 대부분, 채권(TLT)은 소폭 추가기여, 시너지는 없음", "08장(세션13)"),
            ("횡보장 역발상(평균회귀) 섹터 틸트", "❌ 기각", "개별종목에서처럼 섹터로테이션 레벨에서도 뚜렷이 악화, 모멘텀만 계속 유효", "08장(세션13)"),
            ("v3 통합(리더틸트+약세장 방어자산) 홀드아웃", "✅ 부작용없음 확인", "홀드아웃 구간에 약세장이 없어 기존 시스템과 결과 동일 — 비약세장 동작 불변 확인", "08장(세션13)"),
            ("VIX 임계값(30) 기반 방어 오버레이", "❌ 기각", "두 시대 모두 손해 — VIX는 추세를 선행하지 않고 저점과 거의 동시에 튐", "08장(세션13)"),
            ("듀얼모멘텀 자산군 하드스위치(방어자산 100% 전환)", "❌ 기각", "블렌드보다 뚜렷이 열세 — 집중전환이 리스크패리티의 분산효과를 없앰", "08장(세션13)"),
            ("방어자산 비중 국면강도 비례 연속조절", "❌ 기각", "두 시대 모두 이진 스위치보다 근소하게 열세 — 단순 규칙이 정교한 조절을 이김", "08장(세션13)"),
            ("프레임워크를 국가별ETF(9개 선진국, 1998~2026)에 재현", "❌ 기각", "S&P500은커녕 같은 유니버스 동일가중 매수보유도 CAGR로는 못 이김 — MDD 개선만 일반화", "08장(세션14)"),
            ("방어자산 블렌드 2022년 개별연도 검증", "❌ 그 해엔 역효과", "TLT -32.8% 급락한 해엔 블렌드가 baseline보다 나빠짐 — 평균과 개별연도는 다르다", "08장(세션14)"),
            ("국가ETF에서 쏠림틸트 제거(순수 리스크패리티만)", "✅ 원인 규명 — 개선 확인", "틸트가 국가로테이션에선 알파가 아니라 잡음이었음, 제거시 동일가중 매수보유도 이김", "08장(세션15)"),
            ("국가ETF 유니버스에 신흥국(브라질·한국·대만·EEM) 추가", "🔶 부분개선", "격차를 절반 가까이 좁히지만 S&P500을 완전히 따라잡지는 못함", "08장(세션15)"),
            ("2022년 대응: 리스크패리티 재조정 주기 월간으로 단축", "❌ 효과 없음", "2022·전체구간 모두 사실상 변화 없음 — 원인은 재조정 지연이 아니라 그 해 채권 자체의 구조적 하락", "08장(세션15)"),
            ("미국 팩터ETF(가치·성장·퀄리티·모멘텀·저변동성)로 프레임워크 재현", "✅ 재현 성공", "S&P500·팩터동일가중 둘 다 위험조정 기준으로 상회 — GICS 섹터가 아니라 '미국 국내 분산' 일반이 핵심", "08장(세션16)"),
            ("국가 로테이션 역발상(래거드) 틸트", "✅ 채택 — 정반대 신호가 통함", "두 시대 모두 트레이드오프 없이 순개선, 섹터(모멘텀)와 정반대 신호가 국가 레벨에선 유효", "08장(세션16)"),
            ("국가 역발상 틸트 임계값(z) 민감도", "✅ 로버스트 확인", "쏠림비율이 53%→4%로 변해도 샤프 0.42~0.43 고정 — 사후 스윕 아님", "08장(세션18)"),
            ("GICS 섹터 + 스타일 팩터 결합 유니버스(16개)", "🔶 온건한 개선", "샤프는 최선의 단일유니버스와 동률, MDD는 그보다 더 개선 — 극적이진 않지만 진짜 개선", "08장(세션18)"),
        ]
        ledger_rows = "".join(
            f'<tr><td class="tk-cell" style="white-space:normal; max-width:220px;"><span class="tk-name">{esc(h)}</span></td>'
            f'<td class="ctr" style="white-space:nowrap;">{esc(status)}</td>'
            f'<td style="white-space:normal; text-align:left; max-width:320px;">{esc(reason)}</td>'
            f'<td class="ctr" style="white-space:normal; min-width:110px;">{esc(where)}</td></tr>'
            for h, status, reason, where in hypothesis_log
        )

        ledger_html = f"""
        <h3>"대장주"를 제대로 다시 검증하기 — 그리고 이 리포트가 시도한 모든 가설의 기록</h3>
        <p>지난 라운드에서 "개별종목 모멘텀 틸트가 오히려 해가 됐다"는 결과에 방법론적 허점이
        있었다 — 쏠림이 감지된 섹터와 무관하게 유니버스 전체에서 모멘텀 상위 종목을 골랐던 것이다.
        이번엔 yfinance 실제 GICS 섹터 분류로 각 종목을 해당 섹터 ETF에 정확히 매핑한 뒤, <b>그
        쏠림 섹터 "안에서" 그 시점 모멘텀이 가장 센 종목 1개(문자 그대로의 "대장주")</b>에 틸트를
        걸어 다시 검증했다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th></th><th colspan="3">2015~2026(강세장)</th><th colspan="3">2000~2012(약세장 포함)</th></tr>
            <tr><th></th><th>CAGR</th><th>MDD</th><th>샤프</th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
            <tbody>{true_leader_table}</tbody>
          </table>
        </div>
        <div class="chart-card">
          <h3>섹터ETF 쏠림틸트 vs 섹터 내 진짜 대장주 틸트 vs S&amp;P500(2015~2026, 로그축)</h3>
          <p class="chart-desc">기준 100 · {esc(START_DATE)} ~ {esc(GEN_DATE)}</p>
          <div class="legend">
            <span class="lg-item"><span class="lg-swatch" style="background:var(--blue)"></span>섹터ETF 쏠림틸트</span>
            <span class="lg-item"><span class="lg-swatch" style="background:var(--orange)"></span>섹터 내 진짜 대장주 틸트</span>
            <span class="lg-item"><span class="lg-swatch" style="background:var(--aqua)"></span>S&amp;P500 매수보유</span>
          </div>
          <div id="chart-leader-compare-equity"></div>
        </div>
        <p><b>제대로 구현해도 결론은 바뀌지 않는다 — 오히려 더 뚜렷해졌다.</b> 2015~2026년에는
        대장주 틸트(샤프 {fnum(tl_bull['results']['true_sector_leader']['final']['sharpe'])})가 섹터
        ETF 틸트(샤프 {fnum(tl_bull['results']['etf_tilt']['final']['sharpe'])})와 baseline
        (샤프 {fnum(tl_bull['results']['baseline']['final']['sharpe'])})보다도 크게 뒤처졌다 — 단일
        종목 하나에 집중하는 순간 그 종목 고유 리스크(실적 쇼크 등)를 고스란히 떠안기 때문으로
        보인다. 2000~2012년에는 반대로 대장주 틸트(샤프 {fnum(tl_bear['results']['true_sector_leader']['final']['sharpe'])})가
        오히려 근소하게 가장 높았다 — 하지만 이렇게 <b>시대마다 결과가 뒤집히는 것 자체가 신뢰할 수
        없다는 증거</b>다. 섹터 ETF 틸트는 두 시대 모두에서 일관되게 baseline을 이겼지만, 대장주
        틸트는 일관성이 없다 — <b>"안전 자산(섹터 ETF)에 이미 분산된 채로 쏠림에 올라타는 것"과
        "그 쏠림의 근원인 개별 종목에 직접 집중 베팅하는 것"은 다른 문제이고, 후자는 이 리포트가
        검증한 범위에서 기각된다.</b></p>

        <h3>이 결과가 우연이 아님을 확인 — 임계값 민감도</h3>
        <p>쏠림 판정 기준(z≥1)을 사후에 딱 맞게 스윕해서 고른 건 아닌지 확인하기 위해, 그 근방
        (z=0.5~2.0)에서 결과가 얼마나 흔들리는지 봤다. 이건 "더 좋은 값을 찾는" 스윕이 아니라
        "우연히 좋은 값을 하나 건진 게 아닌지" 검증하는 것이다.</p>
        <div class="sm-grid">
          <div class="sm-panel">
            <h4>2015~2026(강세장)</h4>
            <table class="data-table" style="min-width:0;">
              <thead><tr><th>임계값</th><th>쏠림비율</th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
              <tbody>{z_rows_bull}</tbody>
            </table>
          </div>
          <div class="sm-panel">
            <h4>2000~2012(약세장 포함)</h4>
            <table class="data-table" style="min-width:0;">
              <thead><tr><th>임계값</th><th>쏠림비율</th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
              <tbody>{z_rows_bear}</tbody>
            </table>
          </div>
        </div>
        <p class="fig-caption">샤프비율이 z=0.5~2.0 전 구간에서 강세장 0.84~0.85, 약세장 포함
        구간 0.21~0.26 사이에 안정적으로 머문다 — 특정 임계값 하나에서만 우연히 잘 나온 결과가
        아니라는 뜻이다.</p>

        <h3>추가로 기각된 것: 켈리 기준(Kelly criterion) 사이징</h3>
        <p><code>core.position_sizing.kelly_fraction</code>(이 저장소에 이미 구현된 켈리 공식,
        하프켈리 안전계수 적용)으로 트레일링 3년 일별 승률·평균손익에서 섹터 비중을 정해 리스크
        패리티(inverse-vol)와 비교했다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
            <tbody>
              <tr><td class="tk-cell"><span class="tk-name">2015~2026: 켈리+변동성타게팅</span></td>
                <td class="num">{fnum(ky_bull['kelly_final']['cagr'])}%</td><td class="num">{fnum(ky_bull['kelly_final']['mdd'])}%</td>
                <td class="num">{fnum(ky_bull['kelly_final']['sharpe'])}</td></tr>
              <tr class="best-row"><td class="tk-cell"><span class="tk-name">2015~2026: 리스크패리티+변동성타게팅</span></td>
                <td class="num">{fnum(ky_bull['rp_final']['cagr'])}%</td><td class="num">{fnum(ky_bull['rp_final']['mdd'])}%</td>
                <td class="num strong">{fnum(ky_bull['rp_final']['sharpe'])}</td></tr>
              <tr><td class="tk-cell"><span class="tk-name">2000~2012: 켈리+변동성타게팅</span></td>
                <td class="num delta neg">{fnum(ky_bear['kelly_final']['cagr'],2,True)}%</td><td class="num">{fnum(ky_bear['kelly_final']['mdd'])}%</td>
                <td class="num">{fnum(ky_bear['kelly_final']['sharpe'])}</td></tr>
              <tr class="best-row"><td class="tk-cell"><span class="tk-name">2000~2012: 리스크패리티+변동성타게팅</span></td>
                <td class="num">{fnum(ky_bear['rp_final']['cagr'])}%</td><td class="num">{fnum(ky_bear['rp_final']['mdd'])}%</td>
                <td class="num strong">{fnum(ky_bear['rp_final']['sharpe'])}</td></tr>
            </tbody>
          </table>
        </div>
        <p class="caveat">⚠️ 켈리 기준은 약세장 포함 구간에서 특히 나빴다(CAGR
        {fnum(ky_bear['kelly_final']['cagr'],2,True)}%, S&amp;P500 매수보유(0.10)보다도 낮은 샤프
        {fnum(ky_bear['kelly_final']['sharpe'])}) — 트레일링 승률·손익 기반 사이징은 직전 국면을
        따라가는 경향이 있어(최근에 잘 오른 섹터에 비중을 더 싣는 방식과 유사) 국면 전환기에 특히
        취약한 것으로 보인다. 리스크패리티(변동성 역수)처럼 "가격 방향과 무관한" 지표가 더 안정적인
        비중 기준이라는 이 리포트의 반복된 결론과 일치한다.</p>

        <h3>이 리포트 전체의 가설 기록 — 채택된 것과 기각된 것</h3>
        <p>여러 세션에 걸쳐 시도한 모든 가설을 판정과 함께 정리한다. <b>기각된 가설도 결과라는
        점을 강조하고 싶다</b> — 무엇이 안 통하는지 아는 것이 무엇이 통하는지 아는 것만큼 이 연구의
        가치다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>가설</th><th>판정</th><th>근거</th><th>위치</th></tr></thead>
            <tbody>{ledger_rows}</tbody>
          </table>
        </div>
        <p><b>최종 시스템(이 리포트가 도달한 결론):</b> 거시국면 3종(약세장/횡보장/강세장)에 강세장은
        분산도로 다시 나눈 4번째 상태(쏠림강세)까지 — 총 4개 상태 각각에 이미 검증된 하나의 규칙만
        적용한다. 약세장·횡보장·광범위강세는 리스크패리티+변동성타게팅(목표변동성만 약세장에서
        더 타이트하게) 그대로, 쏠림강세일 때만 그 섹터 ETF에 리스크패리티 기본비중+50%p를 얹는다.
        개별 종목 단위의 어떤 알파 추구(모멘텀 틸트·켈리 사이징·대장주 집중)도 이 시스템에 더할
        가치를 보여주지 못했다 — <b>ETF 레벨의 분산을 유지한 채로만 국면에 올라타는 것이, 그 밑으로
        내려가 개별 종목에 집중하는 것보다 이 리포트가 검증한 모든 사례에서 나았다.</b></p>
        """

    # -------------------------------------------------------------------
    # 실전 배치 스트레스 테스트: 홀드아웃 검증 + 거래비용 + 재조정 빈도 + 래거드 언더웨이트 + 레버리지
    # -------------------------------------------------------------------
    stress_paths = {
        "holdout": f"{OUT_DIR}/hypothesis_holdout_bridge.json",
        "txcost": f"{OUT_DIR}/hypothesis_transaction_costs.json",
        "laggard": f"{OUT_DIR}/hypothesis_laggard_underweight.json",
        "leverage": f"{OUT_DIR}/hypothesis_leverage_sensitivity.json",
    }
    HAS_STRESS = all(os.path.exists(p) for p in stress_paths.values())
    stress_html = ""
    if HAS_STRESS:
        with open(stress_paths["holdout"], encoding="utf-8") as f:
            ho = json.load(f)
        with open(stress_paths["txcost"], encoding="utf-8") as f:
            tc = json.load(f)
        with open(stress_paths["laggard"], encoding="utf-8") as f:
            lg = json.load(f)
        with open(stress_paths["leverage"], encoding="utf-8") as f:
            lv = json.load(f)

        def m_row(label, m, cls=""):
            return (
                f'<tr class="{cls}"><td class="tk-cell"><span class="tk-name">{esc(label)}</span></td>'
                f'<td class="num">{fnum(m["cagr"])}%</td><td class="num">{fnum(m["mdd"])}%</td>'
                f'<td class="num strong">{fnum(m["sharpe"])}</td><td class="num">{fnum(m["calmar"])}</td></tr>'
            )

        holdout_table = (
            m_row("baseline(리스크패리티)+변동성타게팅", ho["rp_final"])
            + m_row("+ 쏠림강세 리더틸트(최종 확정 시스템)", ho["tilt_final"], cls="best-row")
            + m_row("S&P500 매수보유", ho["sp500_bh"])
        )

        tc_rows = {p: "".join(
            f'<tr><td class="num">{fnum(float(k.replace("cost_", "").replace("bps", "")),1)}bp</td>'
            f'<td class="num">{fnum(v["cagr"])}%</td><td class="num">{fnum(v["mdd"])}%</td>'
            f'<td class="num strong">{fnum(v["sharpe"])}</td></tr>'
            for k, v in tc[p]["D"]["results"].items()
        ) for p in ["2015_2026", "2000_2012"]}

        freq_rows = {p: "".join(
            f'<tr><td class="tk-cell">{esc(tc[p][fk]["label"])}</td>'
            f'<td class="num">{fnum(tc[p][fk]["avg_daily_turnover_pct"],2)}%</td>'
            f'<td class="num strong">{fnum(tc[p][fk]["results"]["cost_0.0bps"]["sharpe"])}</td>'
            f'<td class="num">{fnum(tc[p][fk]["results"]["cost_5.0bps"]["sharpe"])}</td>'
            f'<td class="num">{fnum(tc[p][fk]["results"]["cost_20.0bps"]["sharpe"])}</td></tr>'
            for fk in ["D", "W", "MS"]
        ) for p in ["2015_2026", "2000_2012"]}

        def lg_rows(period):
            return "".join(
                f'<tr class="{"best-row" if name.startswith("leader_only") else ""}">'
                f'<td class="tk-cell">{esc(name)}</td><td class="num">{fnum(v["cagr"])}%</td>'
                f'<td class="num">{fnum(v["mdd"])}%</td><td class="num strong">{fnum(v["sharpe"])}</td></tr>'
                for name, v in lg[period].items() if name != "sp500_bh"
            )

        def lv_rows(period):
            return "".join(
                f'<tr class="{"best-row" if name == "cap_1.0" else ""}">'
                f'<td class="tk-cell">cap={esc(name.replace("cap_", ""))}</td><td class="num">{fnum(v["cagr"])}%</td>'
                f'<td class="num">{fnum(v["mdd"])}%</td><td class="num strong">{fnum(v["sharpe"])}</td>'
                f'<td class="num">{fnum(v["calmar"])}</td></tr>'
                for name, v in lv[period].items() if name != "sp500_bh"
            )

        stress_html = f"""
        <h3>실전 배치 스트레스 테스트 — 확정 시스템이 진짜로 버티는가</h3>
        <p>지금까지 확정한 시스템(리스크패리티+변동성타게팅18%/5일룩백 + 쏠림강세 리더틸트50%p)을
        실전에 그대로 배치한다고 가정하고 다섯 방향에서 추가로 흔들어봤다: ①이 시스템을 만드는 데
        전혀 쓰이지 않은 진짜 미지의 구간 ②거래비용 ③재조정 빈도 ④비중 재원 배분 방식
        ⑤레버리지 완화.</p>

        <h4>① 진짜 아웃오브샘플 — 2000~2012·2015~2026 "사이"의 2013~2014년</h4>
        <p>이 두 시대 사이, 어떤 임계값·파라미터 결정에도 전혀 관여하지 않은 {esc(ho['period']['start'])}
        ~{esc(ho['period']['end'])}(502거래일)에 이미 확정한 파라미터를 그대로 적용했다. 이 구간의
        {fnum(ho['narrow_bull_pct'],1)}%가 쏠림강세로 판정됐다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프</th><th>Calmar</th></tr></thead>
            <tbody>{holdout_table}</tbody>
          </table>
        </div>
        <p class="fig-caption">CAGR은 S&amp;P500과 거의 동률이지만 MDD·샤프·Calmar 전부 근소하게
        우위 — 진짜 미지의 구간에서도 시스템이 무너지지 않았다. 단, 이 구간 자체가 유난히 조용한
        강세장(모든 전략의 샤프가 1.6~1.7대)이라 절대수치보다 상대 순위를 봐야 한다. 흥미로운 점:
        이 구간의 쏠림 리더 섹터는 XLV(헬스케어)·XLF(금융) 위주였다 — 2015~2026년의 반도체(XLK)
        서사와는 전혀 다른 섹터라는 점에서, 분류기가 특정 섹터 스토리 하나에 과적합된 게 아니라는
        근거가 된다.</p>

        <h4>② 거래비용 — 지금까지 전부 무비용 가정이었다</h4>
        <p>변동성타게팅이 실현변동성(5일 룩백)을 매일 재계산해 노출 비중을 조절하므로 회전율이
        생각보다 크다: 강세장 일평균 {fnum(tc['2015_2026']['D']['avg_daily_turnover_pct'],2)}%,
        약세장 포함 구간 {fnum(tc['2000_2012']['D']['avg_daily_turnover_pct'],2)}%. 회전율 1단위당
        비용을 0~20bp까지 적용해봤다(매일 재조정 기준):</p>
        <div class="sm-grid">
          <div class="sm-panel">
            <h4>2015~2026(강세장)</h4>
            <table class="data-table" style="min-width:0;">
              <thead><tr><th>비용</th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
              <tbody>{tc_rows['2015_2026']}</tbody>
            </table>
          </div>
          <div class="sm-panel">
            <h4>2000~2012(약세장 포함)</h4>
            <table class="data-table" style="min-width:0;">
              <thead><tr><th>비용</th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
              <tbody>{tc_rows['2000_2012']}</tbody>
            </table>
          </div>
        </div>
        <p class="fig-caption">현실적인 섹터ETF 거래비용(2~5bp 수준, 무수수료 브로커+타이트한
        스프레드)에서는 두 시대 모두 결론이 안 바뀐다. 다만 약세장 포함 구간은 회전율 자체가 더 커서
        고비용(20bp)에서 샤프가 마이너스로 역전된다 — 저비용 채널 확보가 특히 하락장 구간에서
        중요하다.</p>

        <h4>③ 재조정 빈도 — 매일이 항상 최선은 아니다</h4>
        <p>변동성타게팅 스케일을 매일 대신 매주·매월만 갱신하면 회전율은 줄지만, 그 사이엔 스케일이
        낡은 값으로 고정된다. 두 효과가 상쇄되는지 시대별로 갈렸다:</p>
        <div class="sm-grid">
          <div class="sm-panel">
            <h4>2015~2026(강세장)</h4>
            <table class="data-table" style="min-width:0;">
              <thead><tr><th>빈도</th><th>일평균회전율</th><th>샤프(0bp)</th><th>샤프(5bp)</th><th>샤프(20bp)</th></tr></thead>
              <tbody>{freq_rows['2015_2026']}</tbody>
            </table>
          </div>
          <div class="sm-panel">
            <h4>2000~2012(약세장 포함)</h4>
            <table class="data-table" style="min-width:0;">
              <thead><tr><th>빈도</th><th>일평균회전율</th><th>샤프(0bp)</th><th>샤프(5bp)</th><th>샤프(20bp)</th></tr></thead>
              <tbody>{freq_rows['2000_2012']}</tbody>
            </table>
          </div>
        </div>
        <p class="caveat">⚠️ 강세장에서는 매일 재조정이 전 비용구간에서 압도적으로 낫다(회전율을
        줄이면 스테일 비중의 손실이 회전율 절감 이득보다 크다). 그런데 <b>약세장 포함 구간은
        정반대다</b> — 매주 재조정이 무비용 기준으로도 매일보다 낫다(위기 국면에서 매일 재조정이
        실현변동성 급등에 과민반응(whipsaw)하는 것으로 보인다). 두 시대 결과가 정반대이므로 <b>이걸
        보고 사후에 "강세장엔 매일, 약세장엔 매주"로 바꾸는 건 전형적인 과적합이라 하지 않는다</b> —
        이미 확정한 매일(5일 룩백) 설정을 그대로 유지하되, 이 비대칭성 자체를 정직하게 기록해둔다.</p>

        <h4>④·⑤ 기각된 추가 변형: 래거드 대칭 언더웨이트, 레버리지 완화</h4>
        <div class="sm-grid">
          <div class="sm-panel">
            <h4>비중 재원을 래거드(꼴찌 섹터)에서만 뺄 경우</h4>
            <table class="data-table" style="min-width:0;">
              <thead><tr><th>2015~2026</th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
              <tbody>{lg_rows('2015_2026')}</tbody>
            </table>
          </div>
          <div class="sm-panel">
            <h4>쏠림강세일 때만 레버리지 cap 완화</h4>
            <table class="data-table" style="min-width:0;">
              <thead><tr><th>2015~2026</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>Calmar</th></tr></thead>
              <tbody>{lv_rows('2015_2026')}</tbody>
            </table>
          </div>
        </div>
        <p class="caveat">⚠️ 둘 다 기각. 래거드 언더웨이트 3가지 변형(기존 비례차감/래거드 전액차감/
        절반씩)은 두 시대 모두 샤프 차이가 0.01~0.02로 노이즈 수준이라 추가 복잡성을 정당화하지
        못한다. 레버리지 완화(cap 1.0→1.5)는 CAGR을 단조 증가시키지만 MDD도 똑같이 단조 악화시켜
        Calmar·샤프가 사실상 그대로다(강세장 샤프 0.84→0.82, calmar 0.55→0.54) — <b>레버리지는
        위험조정수익을 개선하지 않는다, 수익과 위험을 비례적으로 동시에 키울 뿐</b>이라는 교과서적
        결과를 그대로 재확인했다.</p>

        <p><b>다섯 스트레스 테스트를 종합하면:</b> 확정된 시스템은 (1)진짜 미지의 구간에서도
        무너지지 않고, (2)현실적 거래비용에서도 우위가 유지되며, (3)~(5) 세 가지 구조적 변형
        (재조정 빈도·비중 재원 배분·레버리지) 중 어느 것도 유의미한 개선을 주지 못했다 — 이미 확정한
        설계가 상당히 안정적인 로컬 최적점에 가깝다는 근거로 받아들인다.</p>
        """

    # -------------------------------------------------------------------
    # 진짜 다른 전략을 국면별로 — 추세이탈 방어, 방어자산 편입, 횡보장 역발상 재검증
    # -------------------------------------------------------------------
    alpha_paths = {
        "trend": f"{OUT_DIR}/hypothesis_absolute_trend_filter.json",
        "trend_c": f"{OUT_DIR}/hypothesis_trend_filter_confirmed.json",
        "def": f"{OUT_DIR}/hypothesis_defensive_assets_bear.json",
        "def_dc": f"{OUT_DIR}/hypothesis_defensive_decompose.json",
        "sw": f"{OUT_DIR}/hypothesis_sideways_mean_reversion.json",
        "v3": f"{OUT_DIR}/hypothesis_integrated_v3_holdout.json",
        "vix": f"{OUT_DIR}/hypothesis_vix_defense.json",
        "dm": f"{OUT_DIR}/hypothesis_dual_momentum_switch.json",
        "sev": f"{OUT_DIR}/hypothesis_severity_scaled_defense.json",
    }
    HAS_ALPHA = all(os.path.exists(p) for p in alpha_paths.values())
    alpha_search_html = ""
    if HAS_ALPHA:
        with open(alpha_paths["vix"], encoding="utf-8") as f:
            vx = json.load(f)
        with open(alpha_paths["dm"], encoding="utf-8") as f:
            dm = json.load(f)
        with open(alpha_paths["sev"], encoding="utf-8") as f:
            sv = json.load(f)
        with open(alpha_paths["trend"], encoding="utf-8") as f:
            tr = json.load(f)
        with open(alpha_paths["trend_c"], encoding="utf-8") as f:
            trc = json.load(f)
        with open(alpha_paths["def"], encoding="utf-8") as f:
            de = json.load(f)
        with open(alpha_paths["def_dc"], encoding="utf-8") as f:
            dedc = json.load(f)
        with open(alpha_paths["sw"], encoding="utf-8") as f:
            sw = json.load(f)
        with open(alpha_paths["v3"], encoding="utf-8") as f:
            v3 = json.load(f)

        def trend_rows(period_data, key_prefix):
            return "".join(
                f'<tr class="{"best-row" if m == "1.0" else ""}"><td class="tk-cell">배수={m}{"(필터없음)" if m=="1.0" else ""}</td>'
                f'<td class="num">{fnum(v["cagr"])}%</td><td class="num">{fnum(v["mdd"])}%</td>'
                f'<td class="num strong">{fnum(v["sharpe"])}</td></tr>'
                for m, v in ((k.replace(f"{key_prefix}_", ""), val) for k, val in period_data.items() if k.startswith(key_prefix))
            )

        def_row = lambda label, m, cls="": (
            f'<tr class="{cls}"><td class="tk-cell">{esc(label)}</td><td class="num">{fnum(m["cagr"])}%</td>'
            f'<td class="num">{fnum(m["mdd"])}%</td><td class="num strong">{fnum(m["sharpe"])}</td>'
            f'<td class="num">{fnum(m["calmar"])}</td></tr>'
        )

        dedc_rows = {p: "".join(
            def_row(name.replace("_", " "), v) for name, v in dedc[p].items() if name != "sp500_bh"
        ) for p in ["2015_2026", "2006_2012"]}

        alpha_search_html = f"""
        <h3>"시대를 관통하는 하나의 시스템"이 아니라 진짜 다른 전략을 국면마다 — 새로운 알파 재탐색</h3>
        <p>지금까지 확정한 시스템은 약세장에서도 "같은 섹터 ETF 안에서 변동성타게팅만 타이트하게"
        했을 뿐, 실제로 주식을 떠난 적은 없었다. 국면마다 정말 다른 전략(방어자산으로 갈아타기,
        추세가 완전히 꺾이면 실제로 노출을 줄이기)을 쓰면 더 나은지, 이번 라운드에서 3가지를 새로
        검증했다.</p>

        <h4>① 절대추세필터(SPY 200일 이동평균) — 양날의 검, 공짜 알파가 아니다</h4>
        <p>지금까지의 "쏠림 국면" 신호는 섹터 간 상대적 격차(횡단면 z-점수)였다. 이번엔 완전히 다른
        신호 — SPY 가격이 200일 이동평균 아래로 떨어지면 방어배수(1.0→0.25로 낮출수록 강한 방어)를
        곱해 노출을 실제로 줄이는 "가격 레벨 기반" 필터를 시도했다.</p>
        <div class="sm-grid">
          <div class="sm-panel">
            <h4>2015~2026(강세장) — 200일선 아래 {fnum(tr['2015_2026']['below_ma_pct'],1)}%</h4>
            <table class="data-table" style="min-width:0;">
              <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
              <tbody>{trend_rows(tr['2015_2026'], 'mult')}</tbody>
            </table>
          </div>
          <div class="sm-panel">
            <h4>2000~2012(약세장 포함) — 200일선 아래 {fnum(tr['2000_2012']['below_ma_pct'],1)}%</h4>
            <table class="data-table" style="min-width:0;">
              <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
              <tbody>{trend_rows(tr['2000_2012'], 'mult')}</tbody>
            </table>
          </div>
        </div>
        <p class="caveat">⚠️ <b>정반대로 갈렸다</b> — 강세장에서는 방어배수를 낮출수록(방어를 강하게
        할수록) 샤프가 단조 악화되고({fnum(tr['2015_2026']['mult_1.0']['sharpe'])} →
        {fnum(tr['2015_2026']['mult_0.25']['sharpe'])}, 일시적 눌림목에서도 방어모드로 들어가는 오탐
        때문으로 보인다), 약세장 포함 구간은 반대로 방어를 강하게 할수록 샤프·MDD 모두 개선된다
        ({fnum(tr['2000_2012']['mult_1.0']['sharpe'])} → {fnum(tr['2000_2012']['mult_0.25']['sharpe'])},
        MDD {fnum(tr['2000_2012']['mult_1.0']['mdd'])}% → {fnum(tr['2000_2012']['mult_0.25']['mdd'])}%).
        <b>이건 버그가 아니라 추세필터의 본질이다</b> — 강한 강세장에서는 보험료를 내고 못 쓰는
        보험이고, 위기 구간에서는 보험금을 타는 보험이다. 어느 시대를 겪을지 미리 알 수 없으므로
        "공짜 알파"로 팔면 안 된다.</p>
        <p>기존 국면분류의 "약세장"(트레일링 12개월 수익률 &lt; -5%) 신호와 200일선 이탈을 <b>AND로
        묶어(둘 다 동의해야 방어)</b> 오탐을 걸러봤지만, 강세장 쪽 손실이 오히려 더 커졌다(방어배수
        0.25 기준 샤프 {fnum(tr['2015_2026']['mult_0.25']['sharpe'])} → {fnum(trc['2015_2026']['mult_0.25']['sharpe'])}) —
        약세장 국면 판정 자체가 트레일링 12개월이라는 느린 신호라, 빠른 조정(2018년 말·2020년 코로나
        등)에서 확인이 너무 늦게 온다. 반면 약세장 포함 구간에서는 AND 필터가 뚜렷이 더 나았다
        (샤프 {fnum(tr['2000_2012']['mult_0.25']['sharpe'])} → {fnum(trc['2000_2012']['mult_0.25']['sharpe'])},
        MDD {fnum(tr['2000_2012']['mult_0.25']['mdd'])}% → {fnum(trc['2000_2012']['mult_0.25']['mdd'])}%,
        CAGR도 함께 개선됨). <b>결론: 절대추세필터는 확정 시스템에 기본 탑재하지 않는다</b> — 다만
        위기 국면에 특히 민감한 투자자를 위한 "선택적 보험 옵션"으로는 유효하며, 쓴다면 트레일링
        국면과 AND로 묶는 확인형이 더 낫다는 것까지 확인했다.</p>

        <h4>② 방어자산(채권·금) 편입 — 진짜 다른 전략, 작지만 일관된 개선</h4>
        <p>확정 시스템은 약세장에도 섹터 ETF(=주식)를 벗어난 적이 없다. 이번엔 약세장 국면에서만
        리스크패리티 유니버스에 TLT(장기국채)와 GLD(금)를 추가해봤다 — 리스크패리티가 그 시점에
        변동성이 낮은 자산에 자동으로 비중을 더 싣게 된다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프</th><th>Calmar</th></tr></thead>
            <tbody>
              {def_row('2015~2026: 기존(섹터ETF만)', de['2015_2026']['baseline'])}
              {def_row('2015~2026: + 약세장 TLT/GLD 편입', de['2015_2026']['defensive_ext'], cls='best-row')}
              {def_row('2006~2012: 기존(섹터ETF만)', de['2006_2012']['baseline'])}
              {def_row('2006~2012: + 약세장 TLT/GLD 편입', de['2006_2012']['defensive_ext'], cls='best-row')}
            </tbody>
          </table>
        </div>
        <p class="fig-caption">⚠️ 2006~2012로 축소한 이유: GLD가 2004-11-18부터 존재해 모멘텀
        워밍업을 포함하면 2006년 이전 데이터는 부족하다. 이 부분구간에서도 baseline(섹터ETF만)
        {fnum(de['2006_2012']['baseline']['sharpe'])} vs S&amp;P500 {fnum(de['2006_2012']['sp500_bh']['sharpe'])}로
        기존 확정 시스템 자체가 이미 견고했다.</p>
        <p><b>두 시대 모두 방향이 일치한다</b>(트레이드오프가 아니라 순개선) — Calmar와 MDD가
        일관되게 좋아지고 CAGR·샤프도 나빠지지 않거나 소폭 개선된다. 어느 자산이 기여했는지
        분해했다:</p>
        <div class="sm-grid">
          <div class="sm-panel">
            <h4>2015~2026(강세장)</h4>
            <table class="data-table" style="min-width:0;">
              <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프</th><th>Calmar</th></tr></thead>
              <tbody>{dedc_rows['2015_2026']}</tbody>
            </table>
          </div>
          <div class="sm-panel">
            <h4>2006~2012(약세장 포함 부분구간)</h4>
            <table class="data-table" style="min-width:0;">
              <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프</th><th>Calmar</th></tr></thead>
              <tbody>{dedc_rows['2006_2012']}</tbody>
            </table>
          </div>
        </div>
        <p class="fig-caption"><b>금(GLD)이 방어효과의 대부분을 담당</b>하고 채권(TLT)은 더 작은
        추가 기여만 한다 — 둘을 합쳐도 시너지는 없고 단순 블렌드에 가깝다. 이 리포트가 검증한 범위
        에서는 <b>"약세장엔 금을 섞는다"가 "약세장엔 채권을 섞는다"보다 근소하게 낫다.</b></p>

        <h4>③ 다시 기각: 횡보장에서도 역발상(평균회귀)은 안 통한다</h4>
        <p>01~05장에서 개별종목 단위로 기각된 코스톨라니의 원래 아이디어(저평가 자산을 사서 평균
        회귀를 노림)를, 이번엔 횡보장 국면에서 섹터 로테이션 레벨로(가장 저평가된=z최소 섹터에
        틸트) 다시 검증했다. 쏠림강세 리더틸트와 정확히 대칭인 설계다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
            <tbody>
              <tr class="best-row"><td class="tk-cell">2015~2026: 기존(횡보장 틸트없음)</td>
                <td class="num">{fnum(sw['2015_2026']['baseline']['cagr'])}%</td><td class="num">{fnum(sw['2015_2026']['baseline']['mdd'])}%</td>
                <td class="num strong">{fnum(sw['2015_2026']['baseline']['sharpe'])}</td></tr>
              <tr><td class="tk-cell">2015~2026: 횡보장 역발상 틸트</td>
                <td class="num">{fnum(sw['2015_2026']['contrarian_sideways']['cagr'])}%</td><td class="num">{fnum(sw['2015_2026']['contrarian_sideways']['mdd'])}%</td>
                <td class="num">{fnum(sw['2015_2026']['contrarian_sideways']['sharpe'])}</td></tr>
              <tr class="best-row"><td class="tk-cell">2000~2012: 기존(횡보장 틸트없음)</td>
                <td class="num">{fnum(sw['2000_2012']['baseline']['cagr'])}%</td><td class="num">{fnum(sw['2000_2012']['baseline']['mdd'])}%</td>
                <td class="num strong">{fnum(sw['2000_2012']['baseline']['sharpe'])}</td></tr>
              <tr><td class="tk-cell">2000~2012: 횡보장 역발상 틸트</td>
                <td class="num">{fnum(sw['2000_2012']['contrarian_sideways']['cagr'])}%</td><td class="num">{fnum(sw['2000_2012']['contrarian_sideways']['mdd'])}%</td>
                <td class="num">{fnum(sw['2000_2012']['contrarian_sideways']['sharpe'])}</td></tr>
            </tbody>
          </table>
        </div>
        <p class="caveat">⚠️ 명확히 기각. 두 시대 모두 뚜렷이 나빠진다(2000~2012는 샤프
        {fnum(sw['2000_2012']['baseline']['sharpe'])}→{fnum(sw['2000_2012']['contrarian_sideways']['sharpe'])},
        MDD {fnum(sw['2000_2012']['baseline']['mdd'])}%→{fnum(sw['2000_2012']['contrarian_sideways']['mdd'])}%로
        크게 악화). <b>개별종목이든 섹터 로테이션이든, 이 리포트가 검증한 모든 층위에서 평균회귀
        베팅은 통하지 않는다</b> — 반대로 모멘텀(쏠림 리더에 올라타는 것)은 계속 통한다는 비대칭이
        이번에도 재확인됐다.</p>

        <h4>④ 추가로 기각: VIX 임계값 방어, 듀얼모멘텀 하드스위치</h4>
        <p>절대추세필터가 강세장에서 손해를 본 이유가 "국면판정이 느린 신호"였기 때문이라면,
        가격도 트레일링수익률도 아닌 <b>VIX(공포지수)</b>처럼 더 빠른 신호를 쓰면 나아질까? VIX가
        실무 표준 위기 임계값(30)을 넘으면 방어모드로 들어가는 오버레이를 테스트했다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
            <tbody>
              <tr class="best-row"><td class="tk-cell">2015~2026: 필터없음(VIX&gt;30 비율 {fnum(vx['2015_2026']['crisis_pct'],1)}%)</td>
                <td class="num">{fnum(vx['2015_2026']['mult_1.0']['cagr'])}%</td><td class="num">{fnum(vx['2015_2026']['mult_1.0']['mdd'])}%</td>
                <td class="num strong">{fnum(vx['2015_2026']['mult_1.0']['sharpe'])}</td></tr>
              <tr><td class="tk-cell">2015~2026: VIX방어배수 0.25</td>
                <td class="num">{fnum(vx['2015_2026']['mult_0.25']['cagr'])}%</td><td class="num">{fnum(vx['2015_2026']['mult_0.25']['mdd'])}%</td>
                <td class="num">{fnum(vx['2015_2026']['mult_0.25']['sharpe'])}</td></tr>
              <tr class="best-row"><td class="tk-cell">2000~2012: 필터없음(VIX&gt;30 비율 {fnum(vx['2000_2012']['crisis_pct'],1)}%)</td>
                <td class="num">{fnum(vx['2000_2012']['mult_1.0']['cagr'])}%</td><td class="num">{fnum(vx['2000_2012']['mult_1.0']['mdd'])}%</td>
                <td class="num strong">{fnum(vx['2000_2012']['mult_1.0']['sharpe'])}</td></tr>
              <tr><td class="tk-cell">2000~2012: VIX방어배수 0.25</td>
                <td class="num">{fnum(vx['2000_2012']['mult_0.25']['cagr'])}%</td><td class="num">{fnum(vx['2000_2012']['mult_0.25']['mdd'])}%</td>
                <td class="num">{fnum(vx['2000_2012']['mult_0.25']['sharpe'])}</td></tr>
            </tbody>
          </table>
        </div>
        <p class="caveat">⚠️ <b>기각 — 이번엔 두 시대 모두 손해</b>(강세장 샤프
        {fnum(vx['2015_2026']['mult_1.0']['sharpe'])}→{fnum(vx['2015_2026']['mult_0.25']['sharpe'])},
        약세장포함 {fnum(vx['2000_2012']['mult_1.0']['sharpe'])}→{fnum(vx['2000_2012']['mult_0.25']['sharpe'])}).
        200일선과 달리 VIX는 <b>추세를 선행하지 않고 패닉의 절정과 거의 동시에(때로는 시장 저점과
        동시에) 튄다</b> — VIX가 30을 넘는 순간 방어로 들어가면 그 직후의 반등을 놓치는 경우가 많다.
        "더 빠른 신호가 항상 더 나은 신호는 아니다"라는 교훈.</p>

        <p>또한 ②의 리스크패리티 "블렌드"(방어자산을 섞는다) 대신, Antonacci류 듀얼모멘텀처럼
        <b>자산군을 통째로 스위치</b>하는 하드버전(SPY 12개월 모멘텀이 마이너스면 TLT/GLD 중 모멘텀
        1위 자산으로 100% 전환, 위험분산 없이)도 시도했다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
            <tbody>
              <tr class="best-row"><td class="tk-cell">2015~2026: 기존(리스크패리티 블렌드)</td>
                <td class="num">{fnum(dm['2015_2026']['baseline']['cagr'])}%</td><td class="num">{fnum(dm['2015_2026']['baseline']['mdd'])}%</td>
                <td class="num strong">{fnum(dm['2015_2026']['baseline']['sharpe'])}</td></tr>
              <tr><td class="tk-cell">2015~2026: 듀얼모멘텀 하드스위치</td>
                <td class="num">{fnum(dm['2015_2026']['dual_momentum_switch']['cagr'])}%</td><td class="num">{fnum(dm['2015_2026']['dual_momentum_switch']['mdd'])}%</td>
                <td class="num">{fnum(dm['2015_2026']['dual_momentum_switch']['sharpe'])}</td></tr>
              <tr class="best-row"><td class="tk-cell">2006~2012: 기존(리스크패리티 블렌드)</td>
                <td class="num">{fnum(dm['2006_2012']['baseline']['cagr'])}%</td><td class="num">{fnum(dm['2006_2012']['baseline']['mdd'])}%</td>
                <td class="num strong">{fnum(dm['2006_2012']['baseline']['sharpe'])}</td></tr>
              <tr><td class="tk-cell">2006~2012: 듀얼모멘텀 하드스위치</td>
                <td class="num">{fnum(dm['2006_2012']['dual_momentum_switch']['cagr'])}%</td><td class="num">{fnum(dm['2006_2012']['dual_momentum_switch']['mdd'])}%</td>
                <td class="num">{fnum(dm['2006_2012']['dual_momentum_switch']['sharpe'])}</td></tr>
            </tbody>
          </table>
        </div>
        <p class="caveat">⚠️ <b>기각 — 뚜렷이 더 나쁘다</b>(강세장 샤프
        {fnum(dm['2015_2026']['baseline']['sharpe'])}→{fnum(dm['2015_2026']['dual_momentum_switch']['sharpe'])},
        MDD {fnum(dm['2015_2026']['baseline']['mdd'])}%→{fnum(dm['2015_2026']['dual_momentum_switch']['mdd'])}%로
        오히려 악화 — "안전자산으로 도망친" 결과가 더 위험해졌다). 단일 자산에 전액 집중하면
        리스크패리티가 주던 분산 효과 자체가 사라지기 때문으로 보인다 — <b>"방어자산을 섞는다"는
        ②는 통했지만 "방어자산으로 갈아탄다"는 이 버전은 안 통한다</b>. 이 리포트가 반복해서 확인한
        원칙(집중보다 분산이 이긴다)이 자산군 레벨에서도 그대로 성립한다.</p>

        <h4>⑤ 마지막 정교화 시도도 기각: 방어자산 비중을 국면 강도에 비례시키기</h4>
        <p>②의 방어자산 편입은 이진 스위치다(약세장 임계값 -5%를 넘으면 방어자산 블렌드 전체 적용,
        아니면 0%) — 국면 경계에서 급격히 전환된다. 얕은 약세장과 깊은 약세장(트레일링추세가
        -15%에 도달하면 블렌드 100%)을 구분해 연속적으로 조절하면 더 나은지 확인했다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프</th><th>Calmar</th></tr></thead>
            <tbody>
              {def_row('2015~2026: 이진 스위치(기존②, 채택안)', sv['2015_2026']['binary_switch(기존②)'], cls='best-row')}
              {def_row('2015~2026: 강도비례 연속조절', sv['2015_2026']['severity_scaled(신가설)'])}
              {def_row('2006~2012: 이진 스위치(기존②, 채택안)', sv['2006_2012']['binary_switch(기존②)'], cls='best-row')}
              {def_row('2006~2012: 강도비례 연속조절', sv['2006_2012']['severity_scaled(신가설)'])}
            </tbody>
          </table>
        </div>
        <p class="caveat">⚠️ 기각 — 두 시대 모두 이진 스위치가 근소하게 더 낫다(강세장 샤프
        {fnum(sv['2015_2026']['binary_switch(기존②)']['sharpe'])}→{fnum(sv['2015_2026']['severity_scaled(신가설)']['sharpe'])},
        약세장포함 {fnum(sv['2006_2012']['binary_switch(기존②)']['sharpe'])}→{fnum(sv['2006_2012']['severity_scaled(신가설)']['sharpe'])}).
        복잡성을 늘려도 개선이 없다 — 이 리포트가 래거드 언더웨이트·레버리지·재원배분 등에서
        반복적으로 확인한 "단순한 이진 규칙이 정교한 연속 조절보다 낫다"는 패턴이 여기서도 그대로
        나타났다. <b>②의 이진 스위치를 그대로 최종안으로 유지한다.</b></p>

        <h4>새로운 통합 시스템(v3): 쏠림강세 리더틸트 + 약세장 방어자산 편입</h4>
        <p>①은 트레이드오프라 기본 탑재하지 않고, ②는 두 시대 모두 순개선이라 채택, ③은 기각이므로
        반영하지 않는다. 이 논리를 그대로 적용해 만든 v3 시스템(쏠림강세엔 리더 ETF 틸트, 약세장엔
        TLT/GLD 편입, 그 외엔 순수 리스크패리티, 국면별 변동성타게팅)을 세션12의 진짜 홀드아웃
        구간(2013~2014)에 다시 적용했다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프</th><th>Calmar</th></tr></thead>
            <tbody>
              {def_row('기존 확정 시스템(섹터ETF만)', v3['baseline'])}
              {def_row('v3 통합(리더틸트+약세장 방어자산)', v3['v3_integrated'], cls='best-row')}
              {def_row('S&P500 매수보유', v3['sp500_bh'])}
            </tbody>
          </table>
        </div>
        <p class="fig-caption">이 홀드아웃 구간엔 약세장 국면 자체가 하루도 없었다({v3['bear_days']}/
        {502}일) — 그래서 v3와 기존 시스템 결과가 정확히 동일하다. 이건 결함이 아니라
        <b>정직성 확인</b>이다: v3가 약세장이 아닌 구간의 동작을 전혀 건드리지 않는다는 뜻으로,
        새 조각을 추가해도 부작용(사이드이펙트)이 없음을 보여준다. v3의 실질적 이득은 2000~2012·
        2006~2012처럼 약세장이 실제로 존재하는 구간에서만 나타나며, 그건 위 ②에서 이미 확인했다.</p>

        <p><b>이번 라운드가 사용자의 원래 질문에 답한다:</b> "시대를 관통하는 하나의 시스템"과 "국면
        마다 다른 전략"은 사실 배타적이지 않다 — 확정 시스템 자체가 이미 국면별로 다른 대응(약세장=
        방어형 변동성타게팅+이제는 방어자산까지, 쏠림강세=알파슬리브, 그 외=순수 베타)을 쓰고
        있었다. 이번 라운드에서 배운 것은 <b>"국면마다 다른 전략을 쓴다"는 방향 자체는 옳지만,
        어떤 전략을 쓸지는 사후 관찰이 아니라 매번 개별적으로 검증해야 한다</b>는 점이다 — 6개 중
        방어자산 "블렌드" 편입(이진 스위치) 하나만 검증을 통과했고, 나머지 다섯(절대추세필터·
        확인형·VIX방어·듀얼모멘텀 하드스위치·강도비례 연속조절)은 트레이드오프이거나 기각됐다.
        알파는 어디서나 나오지 않는다 — "분산을 유지한 채 위험자산 구성을 살짝 조정"하는 아이디어
        만 통하고, "신호에 맞춰 크게 베팅하거나 집중 전환하거나 정교하게 다듬는" 아이디어는 이
        리포트가 검증한 모든 층위에서 반복적으로 실패했다.</p>
        """

    # -------------------------------------------------------------------
    # 세션14: 프레임워크 자체의 일반화 검증(해외/타 유니버스) + 방어자산 블렌드의 개별연도 스트레스
    # -------------------------------------------------------------------
    s14_paths = {
        "intl": f"{OUT_DIR}/hypothesis_international_generalization.json",
        "s2022": f"{OUT_DIR}/hypothesis_2022_stress_case.json",
    }
    HAS_S14 = all(os.path.exists(p) for p in s14_paths.values())
    session14_html = ""
    if HAS_S14:
        with open(s14_paths["intl"], encoding="utf-8") as f:
            intl = json.load(f)
        with open(s14_paths["s2022"], encoding="utf-8") as f:
            s22 = json.load(f)

        def intl_row(label, m, cls=""):
            return (
                f'<tr class="{cls}"><td class="tk-cell">{esc(label)}</td><td class="num">{fnum(m["cagr"])}%</td>'
                f'<td class="num">{fnum(m["mdd"])}%</td><td class="num strong">{fnum(m["sharpe"])}</td>'
                f'<td class="num">{fnum(m["calmar"])}</td></tr>'
            )

        intl_rows = "".join(
            intl_row(f"{era_label}: 국가ETF 확정시스템", intl[era_key]["system"], cls="best-row")
            + intl_row(f"{era_label}: 국가ETF 동일가중 매수보유", intl[era_key]["equal_weight_bh"])
            + intl_row(f"{era_label}: S&P500 매수보유", intl[era_key]["sp500_bh"])
            for era_key, era_label in [("1998_2012", "1998~2012"), ("2013_2026", "2013~2026"), ("full_1998_2026", "전체(1998~2026)")]
        )

        session14_html = f"""
        <h3>프레임워크 자체가 일반화되는가 — 국제 시장과 실제 위기 연도로 검증 범위를 넓히다</h3>
        <p>지금까지의 모든 검증은 미국 GICS 섹터 ETF라는 단일 유니버스, 서로 겹치는 두 시대에서만
        이뤄졌다. 확정 시스템(리스크패리티+국면별 변동성타게팅+쏠림틸트+약세장 방어자산블렌드)을
        그대로 완전히 다른 유니버스와, 방어자산 블렌드가 실제로 실패할 수 있는 특정 연도에 적용해
        "이 프레임워크 자체가 일반적으로 유효한가, 아니면 미국 섹터라는 특수한 무대의 산물인가"를
        검증했다.</p>

        <h4>① 국가별 ETF로 완전히 다른 유니버스에서 재현 — EWJ·EWG·EWU 등 9개 선진국(1998~2026)</h4>
        <p>미국 섹터 대신 9개 선진국 지수 ETF(일본·독일·영국·호주·캐나다·홍콩·싱가포르·프랑스·
        스위스, 전부 1996년부터 존재)에 같은 프레임워크를 그대로 적용했다. 이 구간엔 이 리포트가
        한 번도 다룬 적 없는 위기(1997~98 아시아 외환위기)까지 포함된다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프</th><th>Calmar</th></tr></thead>
            <tbody>{intl_rows}</tbody>
          </table>
        </div>
        <p class="caveat">⚠️ <b>이번엔 명확히 기각 — 미국 섹터에서 통했던 게 여기선 안 통한다.</b>
        전체 구간(1998~2026) 기준 확정 시스템 CAGR
        {fnum(intl['full_1998_2026']['system']['cagr'])}%·샤프{fnum(intl['full_1998_2026']['system']['sharpe'])}는
        S&amp;P500(CAGR {fnum(intl['full_1998_2026']['sp500_bh']['cagr'])}%·샤프
        {fnum(intl['full_1998_2026']['sp500_bh']['sharpe'])})에 크게 못 미친다 — 심지어 <b>같은
        국가 유니버스의 단순 동일가중 매수보유(CAGR {fnum(intl['full_1998_2026']['equal_weight_bh']['cagr'])}%)
        보다도 시스템의 CAGR이 낮다</b>(샤프는 {fnum(intl['full_1998_2026']['system']['sharpe'])} vs
        {fnum(intl['full_1998_2026']['equal_weight_bh']['sharpe'])}로 거의 동률). 다만 MDD는 이번에도
        뚜렷이 개선된다({fnum(intl['full_1998_2026']['system']['mdd'])}% vs 동일가중
        {fnum(intl['full_1998_2026']['equal_weight_bh']['mdd'])}%) — <b>변동성타게팅+분산이 낙폭을
        줄이는 효과는 유니버스를 가리지 않고 일반화되지만, "벤치마크를 이긴다"는 결과는 유니버스
        자체의 질(이 경우 미국 대비 구조적으로 부진했던 선진국 지수들)에 크게 좌우된다</b>는 뜻이다.
        부수적 관찰: 이 유니버스에서는 "쏠림강세"가 전체 거래일의 절반 이상(51.6%)에서 감지됐다 —
        미국 섹터(20~30%대)보다 훨씬 잦다. 국가 간 모멘텀 격차가 원래 더 크고 불안정해서, 미국
        섹터에서 통했던 "쏠림에 올라타는" 틸트가 국가 로테이션에서는 오히려 잡음을 더 많이 태웠을
        가능성이 있다.</p>

        <h4>② 채권-주식 상관관계가 깨진 실제 사례 — 2022년 단독 검증</h4>
        <p>세션13에서 채택한 "약세장엔 TLT/GLD를 섞는다"는 결과는 여러 해를 뭉뚱그린 평균이었다.
        2022년은 실제 역사에서 연준의 급격한 금리인상으로 채권과 주식이 동시에 무너진, "60/40
        포트폴리오 최악의 해" 중 하나로 꼽히는 해다 — 평균이 좋다고 최악의 개별 사례에서도 좋다는
        보장은 없으므로 따로 확인했다.</p>
        <p class="fig-caption">2022년 TLT 누적수익률 <b>{fnum(s22['tlt_2022_return_pct'])}%</b>(역사적
        채권 급락), GLD는 {fnum(s22['gld_2022_return_pct'])}%로 상대적으로 선방. 이 해 약세장 국면
        판정 거래일은 {s22['bear_days_2022']}/{s22['total_days_2022']}일, 평균 방어자산(TLT+GLD)
        비중은 {fnum(s22['avg_defensive_weight_pct'],1)}%에 불과했다(리스크패리티가 TLT의 급등한
        실현변동성을 감지해 자동으로 비중을 줄였지만, 분기 단위 재계산이라 반응이 느렸다).</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>2022년</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>Calmar</th></tr></thead>
            <tbody>
              {intl_row('baseline(섹터ETF만)', s22['baseline'], cls='best-row')}
              {intl_row('+ 방어자산 블렌드', s22['defensive_blend'])}
              {intl_row('S&P500 매수보유', s22['sp500_bh'])}
            </tbody>
          </table>
        </div>
        <p class="caveat">⚠️ <b>우려가 현실로 확인됐다</b> — 2022년 단독으로는 방어자산 블렌드가
        baseline보다 오히려 나빴다(샤프 {fnum(s22['baseline']['sharpe'])}→{fnum(s22['defensive_blend']['sharpe'])},
        MDD {fnum(s22['baseline']['mdd'])}%→{fnum(s22['defensive_blend']['mdd'])}%). 다만 둘 다
        S&amp;P500(샤프 {fnum(s22['sp500_bh']['sharpe'])})은 압도적으로 이겼다 — 방어자산 블렌드가
        "해가 됐다"는 것과 "시스템 전체가 실패했다"는 건 다른 이야기다. <b>세션13의 "✅ 채택" 판정을
        "🔶 평균적으로 유리하지만 채권-주식 상관관계가 깨지는 해(2022 같은)엔 오히려 해가 될 수
        있다"로 하향 수정한다</b> — 켈리 사이징 기각 때와 같은 이유로, 이 결과 역시 "평균이 좋다"는
        것만으로 안심하면 안 된다는 이 리포트의 반복된 원칙을 재확인한다.</p>

        <p><b>세션14 종합:</b> 검증 범위를 넓히자 이 리포트가 지금까지 쌓아온 결론 중 두 가지에
        중요한 단서가 붙었다 — (1) 프레임워크의 "벤치마크를 이긴다"는 결과는 미국 섹터라는 특정
        유니버스의 특성에 상당 부분 의존한다(위험관리 효과 자체는 일반화되지만), (2) 방어자산
        블렌드는 평균적으론 유리해도 채권-주식 상관관계가 깨지는 특정 해엔 실패할 수 있다. 둘 다
        "그래서 전략이 틀렸다"가 아니라 <b>"이 정도까지가 이 전략이 보장하는 것이고, 이 너머는
        보장하지 않는다"는 경계를 정직하게 긋는 결과</b>다.</p>
        """

    # -------------------------------------------------------------------
    # 세션15: 국제화 실패의 원인 분해 + 신흥국 추가 + 2022년 재조정 주기 처방
    # -------------------------------------------------------------------
    s15_paths = {
        "no_tilt": f"{OUT_DIR}/hypothesis_international_no_tilt.json",
        "em": f"{OUT_DIR}/hypothesis_international_emerging.json",
        "monthly": f"{OUT_DIR}/hypothesis_monthly_rebalance_2022.json",
    }
    HAS_S15 = all(os.path.exists(p) for p in s15_paths.values())
    session15_html = ""
    if HAS_S15:
        with open(s15_paths["no_tilt"], encoding="utf-8") as f:
            nt = json.load(f)
        with open(s15_paths["em"], encoding="utf-8") as f:
            em = json.load(f)
        with open(s15_paths["monthly"], encoding="utf-8") as f:
            mr = json.load(f)

        def m_row2(label, m, cls=""):
            return (
                f'<tr class="{cls}"><td class="tk-cell">{esc(label)}</td><td class="num">{fnum(m["cagr"])}%</td>'
                f'<td class="num">{fnum(m["mdd"])}%</td><td class="num strong">{fnum(m["sharpe"])}</td></tr>'
            )

        session15_html = f"""
        <h3>국제화 실패를 파고들다 — 원인 분해, 신흥국 추가, 2022년 처방</h3>
        <p>세션14가 "국가ETF 유니버스에서는 프레임워크가 안 통한다"는 것과 "방어자산 블렌드가
        2022년엔 역효과였다"는 것을 확인한 뒤, 사용자가 새 가설로 계속 연구하라고 지시했다. 두
        결과 모두 "왜"까지는 답하지 않았으므로 원인을 분해했다.</p>

        <h4>① 쏠림틸트가 범인이었다 — 틸트를 빼면 국가ETF에서도 성적이 개선된다</h4>
        <p>세션14에서 국가ETF 유니버스는 쏠림강세가 51.6%로 미국 섹터(20~30%대)보다 훨씬 잦았다 —
        국가간 모멘텀 로테이션에는 리더 추격 틸트가 안 맞을 수 있다는 의심을 확인했다. 정확히 같은
        시스템에서 쏠림틸트만 뺀 버전을 비교했다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>전체(1998~2026)</th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
            <tbody>
              {m_row2('쏠림틸트 포함(세션14 원안)', nt['with_tilt']['full_1998_2026'])}
              {m_row2('쏠림틸트 제거(순수 리스크패리티+방어블렌드만)', nt['no_tilt']['full_1998_2026'], cls='best-row')}
              {m_row2('S&P500 매수보유', nt['sp500_full'])}
            </tbody>
          </table>
        </div>
        <p class="fig-caption">틸트를 빼자 두 시대 모두 개선됐다(전체구간 샤프
        {fnum(nt['with_tilt']['full_1998_2026']['sharpe'])}→{fnum(nt['no_tilt']['full_1998_2026']['sharpe'])},
        CAGR {fnum(nt['with_tilt']['full_1998_2026']['cagr'])}%→{fnum(nt['no_tilt']['full_1998_2026']['cagr'])}%,
        MDD도 {fnum(nt['with_tilt']['full_1998_2026']['mdd'])}%→{fnum(nt['no_tilt']['full_1998_2026']['mdd'])}%로
        함께 개선). 이 버전은 이제 세션14의 동일가중 매수보유(CAGR 4.51%·샤프0.32)도 확실히 이긴다
        — <b>여전히 S&amp;P500엔 못 미치지만, 순수 리스크패리티+변동성타게팅+방어블렌드(틸트 없이)는
        국가ETF에서도 "제 몫"을 한다</b>. 미국 섹터에서 알파였던 쏠림모멘텀 틸트가 국가 로테이션
        에서는 알파가 아니라 잡음이었다는 뜻 — "국면별 다른 전략"이라는 원칙이 "어느 유니버스에나
        같은 틸트를 복붙해도 된다"는 뜻은 아니라는 교훈.</p>

        <h4>② 선진국 편중이 원인의 일부였다 — 신흥국을 더하면 격차가 줄어든다(완전히 닫히진 않는다)</h4>
        <p>9개 선진국만 쓴 게 이 기간(미국 대비 선진국 지수가 구조적으로 부진했던 시기) 실패의
        일부였을 수 있다. 브라질·한국·대만·신흥국 전체(EEM)를 더해 재검증(2004~2026, 신흥국 ETF
        존재기간 제약).</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>2004~2026</th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
            <tbody>
              {m_row2('선진국 9개국만', em['developed_only'])}
              {m_row2('선진국9 + 신흥국4 추가', em['developed_plus_emerging'], cls='best-row')}
              {m_row2('S&P500 매수보유', em['sp500_bh'])}
            </tbody>
          </table>
        </div>
        <p class="fig-caption">신흥국을 더하자 뚜렷이 개선됐다(샤프
        {fnum(em['developed_only']['sharpe'])}→{fnum(em['developed_plus_emerging']['sharpe'])}, CAGR
        {fnum(em['developed_only']['cagr'])}%→{fnum(em['developed_plus_emerging']['cagr'])}%) — S&amp;P500
        (샤프{fnum(em['sp500_bh']['sharpe'])})과의 격차를 절반 가까이 좁히지만 완전히 닫지는
        못한다(MDD도 {fnum(em['developed_only']['mdd'])}%→{fnum(em['developed_plus_emerging']['mdd'])}%로
        더 커진다 — 신흥국의 변동성 자체가 큰 대가). <b>결론: "선진국 편중"은 실패의 진짜 원인 중
        하나였지만 전부는 아니다</b> — 이 기간 미국 시장 자체의 압도적 성과(주로 메가캡 기술주 주도)
        는 어떤 국제 분산으로도 완전히 재현되지 않았다.</p>

        <h4>③ 2022년 방어자산 역효과, 재조정을 월간으로 좁히면 고쳐지는가</h4>
        <p>세션14는 분기 단위 리스크패리티 재계산이 TLT의 2022년 급등 변동성에 너무 느리게
        반응했다고 추정했다. 재조정 주기를 월간(MS)으로 좁혀 재검증.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>2022년 단독</th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
            <tbody>
              {m_row2('분기 재조정(기존)', mr['quarterly(기존)']['y2022'])}
              {m_row2('월간 재조정(신가설)', mr['monthly(신가설)']['y2022'], cls='best-row')}
              {m_row2('S&P500 매수보유', mr['sp500_2022'])}
            </tbody>
          </table>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>2015~2026 전체(부작용 확인)</th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
            <tbody>
              {m_row2('분기 재조정(기존)', mr['quarterly(기존)']['full_2015_2026'], cls='best-row')}
              {m_row2('월간 재조정(신가설)', mr['monthly(신가설)']['full_2015_2026'])}
            </tbody>
          </table>
        </div>
        <p class="caveat">⚠️ <b>거의 고쳐지지 않는다</b> — 월간 재조정도 2022년 샤프는
        {fnum(mr['quarterly(기존)']['y2022']['sharpe'])}에서 {fnum(mr['monthly(신가설)']['y2022']['sharpe'])}로
        사실상 동일하고(CAGR만 {fnum(mr['quarterly(기존)']['y2022']['cagr'])}%→
        {fnum(mr['monthly(신가설)']['y2022']['cagr'])}%로 미세 개선), 전체 구간(2015~2026)도 거의
        변화가 없다(샤프 {fnum(mr['quarterly(기존)']['full_2015_2026']['sharpe'])}→
        {fnum(mr['monthly(신가설)']['full_2015_2026']['sharpe'])}, 부작용도 없지만 개선도 없음).
        <b>진짜 원인은 재조정 지연이 아니었다</b> — 2022년은 짧은 변동성 충격이 아니라 연준의
        지속적 금리인상으로 TLT가 한 해 내내 구조적으로 하락한 해였다. 재조정을 아무리 빨리 해도
        "그 해엔 채권이라는 자산 자체가 나쁜 베팅이었다"는 사실 자체는 바뀌지 않는다 — 처방으로
        고칠 수 있는 문제가 아니라 <b>감수해야 하는 리스크</b>라는 뜻이다. 분기 재조정을 그대로
        유지한다(바꿔도 득이 없으므로).</p>

        <p><b>세션15 종합:</b> "왜 안 통했는가"를 파고들자 부분적으로 고칠 수 있는 원인(쏠림틸트
        제거, 신흥국 추가)과 사후 과적합 없이는 고칠 수 없는 원인(2022년 특정 사례에 맞춘 재조정
        빈도 변경)이 뚜렷이 갈렸다. 전자는 시스템을 개선하고, 후자는 "이 정도의 리스크는 감수한다"는
        정직한 한계로 남긴다.</p>
        """

    # -------------------------------------------------------------------
    # 세션16: 미국 팩터ETF 재현 + 국가 로테이션 역발상 틸트(모멘텀→평균회귀로 전환)
    # -------------------------------------------------------------------
    s16_paths = {
        "factor": f"{OUT_DIR}/hypothesis_us_factor_universe.json",
        "contra": f"{OUT_DIR}/hypothesis_country_contrarian.json",
    }
    HAS_S16 = all(os.path.exists(p) for p in s16_paths.values())
    session16_html = ""
    if HAS_S16:
        with open(s16_paths["factor"], encoding="utf-8") as f:
            fc = json.load(f)
        with open(s16_paths["contra"], encoding="utf-8") as f:
            ct = json.load(f)

        def m_row3(label, m, cls=""):
            return (
                f'<tr class="{cls}"><td class="tk-cell">{esc(label)}</td><td class="num">{fnum(m["cagr"])}%</td>'
                f'<td class="num">{fnum(m["mdd"])}%</td><td class="num strong">{fnum(m["sharpe"])}</td>'
                f'<td class="num">{fnum(m["calmar"])}</td></tr>'
            )

        contra_rows = "".join(
            m_row3(f"{era_label}: no_tilt(세션15 최선안)", ct["no_tilt(세션15 최선안)"][era_key])
            + m_row3(f"{era_label}: 역발상(래거드) 틸트", ct["contrarian_laggard_tilt(신가설)"][era_key], cls="best-row")
            for era_key, era_label in [("1998_2012", "1998~2012"), ("2013_2026", "2013~2026"), ("full_1998_2026", "전체")]
        )

        session16_html = f"""
        <h3>세션16: 미국 팩터로 재현, 국가 로테이션은 역발상으로 전환</h3>
        <p>세션15가 "쏠림틸트가 국가 로테이션에서 잡음이었다"를 확인한 뒤, 두 가지 자연스러운
        후속 질문이 남았다 — (1) 프레임워크가 통했던 게 정말 "미국 섹터"라는 특정 분류 때문인가,
        아니면 "미국 주식시장 내 어떤 분산이든" 통하는가? (2) 국가 로테이션에서 모멘텀이 안 통했다면
        반대(평균회귀)는 통하는가?</p>

        <h4>① 미국 팩터ETF(가치·성장·퀄리티·모멘텀·저변동성)로 재현 — 통한다</h4>
        <p>GICS 섹터 대신 스타일 팩터 ETF(IWD·IWF·SPHQ·MTUM·USMV, 2014~2026)로 유니버스를 바꿔
        똑같은 시스템을 돌렸다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>2014~2026</th><th>CAGR</th><th>MDD</th><th>샤프</th><th>Calmar</th></tr></thead>
            <tbody>
              {m_row3('팩터ETF 확정시스템(쏠림틸트 포함)', fc['with_tilt'])}
              {m_row3('팩터ETF 확정시스템(틸트 없음)', fc['no_tilt'], cls='best-row')}
              {m_row3('팩터ETF 동일가중 매수보유', fc['equal_weight_bh'])}
              {m_row3('S&P500 매수보유', fc['sp500_bh'])}
            </tbody>
          </table>
        </div>
        <p class="fig-caption"><b>이번엔 명확히 재현됐다</b> — 틸트 없는 버전 기준 샤프
        {fnum(fc['no_tilt']['sharpe'])}로 S&amp;P500({fnum(fc['sp500_bh']['sharpe'])})과 팩터
        동일가중매수보유({fnum(fc['equal_weight_bh']['sharpe'])})를 모두 웃돌고, MDD도
        {fnum(fc['no_tilt']['mdd'])}%로 둘(각각 {fnum(fc['sp500_bh']['mdd'])}%,
        {fnum(fc['equal_weight_bh']['mdd'])}%)보다 뚜렷이 낮다(CAGR만 근소하게 낮음 — 08장 전체에서
        반복된 "위험조정으론 이기고 원수익률은 근소하게 못 미친다"는 익숙한 패턴). <b>결론: "GICS
        섹터"라는 특정 분류가 마법은 아니었다</b> — 미국 주식시장 "내부"의 어떤 합리적 분산(섹터든
        팩터든)에도 이 프레임워크가 통한다. 세션14~15가 발견한 실패는 "미국"이 아니라 "국제/국가
        단위 분산"이라는 훨씬 좁은 범위의 한계였다는 뜻. 부수 관찰: 여기서도 틸트를 빼는 게 근소하게
        더 낫다(샤프 {fnum(fc['with_tilt']['sharpe'])}→{fnum(fc['no_tilt']['sharpe'])}) — 쏠림강세
        리더가 MTUM(모멘텀 팩터 그 자체)에 가장 자주 쏠렸는데(1971일 중 825일), 모멘텀 팩터에 모멘텀
        틸트를 또 얹는 이중 베팅이 과도한 집중으로 이어진 것으로 보인다.</p>

        <h4>② 국가 로테이션은 모멘텀이 아니라 역발상(평균회귀)이 통한다</h4>
        <p>세션15의 "틸트 없음" 최선안에, 리더 대신 래거드(횡단면 z 최소 국가)로 틸트를 거는
        역발상 버전을 비교했다 — 08장에서 섹터 로테이션 레벨의 역발상은 명확히 기각됐지만, 국가
        로테이션은 애초에 모멘텀 자체가 안 통했으므로 다른 결과가 나올 수 있다고 봤다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프</th><th>Calmar</th></tr></thead>
            <tbody>{contra_rows}</tbody>
          </table>
        </div>
        <p class="fig-caption"><b>가설이 맞았다 — 트레이드오프 없는 순개선.</b> 두 시대 모두 역발상
        틸트가 no_tilt보다 낫거나 같다(전체구간 샤프 {fnum(ct['no_tilt(세션15 최선안)']['full_1998_2026']['sharpe'])}→
        {fnum(ct['contrarian_laggard_tilt(신가설)']['full_1998_2026']['sharpe'])}, CAGR
        {fnum(ct['no_tilt(세션15 최선안)']['full_1998_2026']['cagr'])}%→
        {fnum(ct['contrarian_laggard_tilt(신가설)']['full_1998_2026']['cagr'])}%, MDD도 함께 개선).
        S&amp;P500(샤프{fnum(ct['sp500_full']['sharpe'])})과의 격차가 위험조정 기준으로는 거의 다
        좁혀졌다. <b>섹터 로테이션(모멘텀이 이김)과 국가 로테이션(역발상이 이김)이 정반대라는 것
        자체가 흥미로운 결과다</b> — 섹터 쏠림(예: AI/반도체)은 몇 년씩 지속되는 구조적 테마인
        반면, 국가 간 상대성과는 통화·정책 사이클을 따라 몇 년 단위로 되돌아가는 경향이 있다는
        경제적 해석과 일치한다(단일 리포트로 인과를 증명할 순 없지만, 최소한 08장 전체에서 "평균
        회귀는 어디서나 안 통한다"고 일반화했던 이전 결론은 <b>과도한 일반화였다</b>는 것을
        인정한다 — 개별종목·섹터 레벨에서는 안 통하지만 국가 레벨에서는 통했다).</p>

        <p><b>세션16 종합:</b> 두 결과를 합치면 이 리포트의 "일반화" 지도가 더 선명해졌다 — (1)
        위험관리(분산+변동성타게팅)는 모든 유니버스에서 일반화된다. (2) 모멘텀 틸트는 미국 국내
        분산(섹터·팩터 둘 다)에서는 통하고 국가간 분산에서는 안 통한다. (3) 역발상 틸트는 정확히
        그 반대다 — 국가간 분산에서 통하고(이번에 확인) 미국 국내 분산(섹터·개별종목)에서는 계속
        기각된다. "어떤 신호가 통하는가"는 유니버스의 경제적 성격에 달려 있다는 것이, 이 리포트가
        수십 개 가설을 거쳐 도달한 가장 일반적인 결론이다.</p>
        """

    # -------------------------------------------------------------------
    # 세션18: 국가 역발상 틸트 로버스트니스 확인 + 섹터·팩터 결합 유니버스
    # -------------------------------------------------------------------
    s18_paths = {
        "robust": f"{OUT_DIR}/hypothesis_country_contrarian_robustness.json",
        "combo": f"{OUT_DIR}/hypothesis_sector_factor_combined.json",
    }
    HAS_S18 = all(os.path.exists(p) for p in s18_paths.values())
    session18_html = ""
    if HAS_S18:
        with open(s18_paths["robust"], encoding="utf-8") as f:
            rb = json.load(f)
        with open(s18_paths["combo"], encoding="utf-8") as f:
            cb = json.load(f)

        robust_rows = "".join(
            f'<tr><td class="num">z≥{z.replace("z_", "")}</td><td class="num">{fnum(rb[z]["narrow_bull_pct"],1)}%</td>'
            f'<td class="num">{fnum(rb[z]["cagr"])}%</td><td class="num">{fnum(rb[z]["mdd"])}%</td>'
            f'<td class="num strong">{fnum(rb[z]["sharpe"])}</td></tr>'
            for z in ["z_0.5", "z_0.75", "z_1.0", "z_1.5", "z_2.0"]
        )

        def combo_row(label, m, cls=""):
            return (
                f'<tr class="{cls}"><td class="tk-cell">{esc(label)}</td><td class="num">{fnum(m["cagr"])}%</td>'
                f'<td class="num">{fnum(m["mdd"])}%</td><td class="num strong">{fnum(m["sharpe"])}</td>'
                f'<td class="num">{fnum(m["calmar"])}</td></tr>'
            )

        session18_html = f"""
        <h3>세션18: 국가 역발상 틸트 로버스트니스 확인 + 섹터·팩터 결합 유니버스</h3>
        <p>세션17에서 정리한 "국면마다 다른 신호가 이긴다"는 결론에 남은 두 가지 점검 —
        (1) 국가 역발상 틸트가 z≥1.0이라는 특정 임계값에만 우연히 맞았던 건 아닌지, (2) GICS
        섹터와 스타일 팩터라는 두 "렌즈"를 하나로 합치면 어느 한쪽만 쓰는 것보다 나은지.</p>

        <h4>① 국가 역발상 틸트 — 임계값 민감도(사후 스윕 아님을 확인)</h4>
        <p>세션13이 섹터 쏠림틸트에 했던 로버스트니스 체크(z=0.5~2.0)를 국가 역발상 틸트에도
        똑같이 적용했다.</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th>임계값</th><th>쏠림비율</th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
            <tbody>{robust_rows}</tbody>
          </table>
        </div>
        <p class="fig-caption"><b>매우 안정적이다.</b> 쏠림 판정 비율이 53.4%(z≥0.5)에서
        4.1%(z≥2.0)까지 10배 넘게 달라져도 샤프비율은 0.42~0.43 사이에서 거의 움직이지 않는다 —
        세션16~17의 국가 역발상 틸트 채택이 특정 임계값 하나에서 우연히 좋게 나온 결과가 아니라는
        뜻이다.</p>

        <h4>② GICS 섹터 + 스타일 팩터 결합 유니버스(16개 자산)</h4>
        <p>세션16에서 각각 검증된 두 유니버스(미국 섹터 11개, 스타일 팩터 5개)를 하나로 합쳐
        리스크패리티를 걸면 더 나은지 확인했다(2014년 이후 팩터ETF 존재기간 제약으로 공정 비교).</p>
        <div class="table-wrap">
          <table class="data-table">
            <thead><tr><th></th><th>CAGR</th><th>MDD</th><th>샤프</th><th>Calmar</th></tr></thead>
            <tbody>
              {combo_row('섹터만(11개)', cb['sector_only'])}
              {combo_row('팩터만(5개)', cb['factor_only'])}
              {combo_row('섹터+팩터 결합(16개)', cb['combined'], cls='best-row')}
              {combo_row('S&P500 매수보유', cb['sp500_bh'])}
            </tbody>
          </table>
        </div>
        <p class="fig-caption">결합 유니버스는 샤프({fnum(cb['combined']['sharpe'])})에서 두 단일
        유니버스 중 더 나은 쪽(팩터, {fnum(cb['factor_only']['sharpe'])})과 동률이면서, MDD는
        팩터단독({fnum(cb['factor_only']['mdd'])}%)보다 뚜렷이 개선된다({fnum(cb['combined']['mdd'])}%)
        — <b>극적인 새 알파는 아니지만, "두 렌즈를 합치면 최선의 위험조정수익은 유지한 채 낙폭은
        더 줄어든다"는 온건하지만 진짜인 개선</b>이다. 세 조합 모두 S&amp;P500(샤프
        {fnum(cb['sp500_bh']['sharpe'])})을 위험조정 기준으로 상회한다.</p>

        <p><b>세션18 종합:</b> 두 확인 모두 이 리포트의 기존 결론을 강화했다 — 국가 역발상 틸트는
        더 로버스트한 것으로 확인됐고, 섹터·팩터 결합은 극적이진 않지만 진짜인 추가 개선을 보여줬다.
        11개 세션·39개 가설에 걸쳐, 이 리포트가 검증한 "진짜 통하는 것"의 목록은 여전히 짧고
        보수적이다 — 그리고 그 점 자체가 이 리포트가 가장 자신 있게 말할 수 있는 결론이다.</p>
        """

    verify_path = f"{OUT_DIR}/momentum_rotation_verification.json"
    if os.path.exists(verify_path):
        with open(verify_path, encoding="utf-8") as f:
            mom_verify = json.load(f)
    else:
        mom_verify = None

    top10_none = mom50_df[(mom50_df["top_n"] == 10) & (mom50_df["overlay"] == "none")].iloc[0]
    top10_rows = mom50_df[mom50_df["top_n"] == 10].sort_values("sharpe", ascending=False)
    top10_table_rows = []
    for _, r in top10_rows.iterrows():
        is_best = r["overlay"] == "none"
        top10_table_rows.append(
            f'<tr class="{"best-row" if is_best else ""}">'
            f'<td class="tk-cell"><span class="tk-name">{esc(r["overlay"])}</span></td>'
            f'<td class="num">{fnum(r["cagr"])}%</td>'
            f'<td class="num">{fnum(r["mdd"])}%</td>'
            f'<td class="num strong">{fnum(r["sharpe"])}</td>'
            "</tr>"
        )
    top10_table_html = "\n".join(top10_table_rows)

    momentum_section_html = f"""
    <section class="section" id="momentum">
      <h2><span class="sec-no">08</span> 크로스전략 검증 — 모멘텀 로테이션에도 적용해보나</h2>
      <p class="lede">이 리포트의 후속 리포트(No.05 "강세장엔 평균회귀가 아니라 추세추종")는 코스톨라니
      국면 매매 대신 <b>듀얼 모멘텀 섹터 로테이션</b>(GICS 11개 섹터 ETF, 매월 리밸런싱, 직전 12개월
      수익률이 양수인 섹터 중 상위 3개를 동일비중 보유)을 같은 기간에 실측해 S&amp;P500을 세 지표
      모두에서 이겼다고 보고했다. 이 장에서는 그 전략을 이 저장소에 재구현해 재현성을 확인하고,
      07장에서 검증한 <b>포트폴리오 변동성타게팅을 그 전략에도 그대로 적용</b>해봤다 — "분산+변동성
      관리"라는 도구가 특정 신호(코스톨라니)에만 통하는 우연이 아니라 신호와 무관하게 일반적으로
      통하는지 확인하기 위해서다.</p>

      <div class="callout">
        <div class="callout-title">재현성 확인 (원 리포트와 같은 2019-08~2026-08 구간)</div>
        <p>같은 방식으로, 같은 기간(2019-08-12~2026-08-12)으로 재구현한 결과 최대낙폭은 원 리포트와
        정확히 일치(&minus;31.50%)했고, CAGR·샤프는 방향은 같지만 소폭 차이가 났다(재구현 CAGR
        {fnum(mom_verify['reproduced']['cagr']) if mom_verify else 13.21}% vs 원문 15.74%, 샤프
        {fnum(mom_verify['reproduced']['sharpe']) if mom_verify else 0.74} vs 원문 0.82) — 리밸런싱
        체결 시점의 1거래일 차이 등 구현 디테일 차이로 보이며, 핵심 결론(모멘텀 로테이션이
        매수보유보다 낙폭 관리에서 낫다)에는 영향이 없다.</p>
      </div>

      <h3>11개 섹터 ETF 그대로 + 변동성타게팅 — 전체 기간(2015~2026)으로 넓히면</h3>
      <p>위 재현성 확인은 원 리포트와 같은 2019~2026 구간(SPY가 유독 강했던 7년)만 본 것이다. 이
      리포트의 분석 기간 전체({esc(START_DATE)}~{esc(GEN_DATE)}, 2018년 말 급락 등을 포함해 3년
      가까이 더 김)로 넓히면 그림이 달라진다: 모멘텀 로테이션 CAGR {fnum(mno['cagr'])}%, 샤프
      {fnum(mno['sharpe'])}로 S&amp;P500(CAGR {fnum(msp['cagr'])}%, 샤프 {fnum(msp['sharpe'])})에
      이미 못 미친다. 여기에 07장과 같은 변동성타게팅(무레버리지, 상한 1.0배)을 걸면 샤프비율이
      {fnum(mno['sharpe'])} → <strong class="mono">{fnum(mvt['sharpe'])}</strong>로 소폭 개선되지만
      여전히 S&amp;P500({fnum(msp['sharpe'])})에는 못 미치고, CAGR도 {fnum(mno['cagr'])}% →
      {fnum(mvt['cagr'])}%로 오히려 더 낮아진다. 07장의 50종목 케이스와는 달리 이번엔 변동성타게팅이
      "위험조정 기준으로도 시장을 이기게" 만들어주지 못한다 — 11개 섹터 ETF는 서로 상관관계가 높아
      (같은 시장 베타를 공유) 50종목 케이스만큼 분산 효과가 크지 않은 것으로 보인다.</p>

      <h3>후보 풀을 50종목으로 넓히면 — 그런데 해석에 주의가 필요하다</h3>
      <p>같은 로테이션 로직(절대모멘텀 필터 + 상위 N개 동일비중, 매월 리밸런싱)을 11개 섹터 ETF
      대신 이 리포트의 50종목 유니버스(10섹터×5종목)에 걸고 상위 10개를 보유하게 하면 결과가
      극적으로 달라진다:</p>
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr><th>Top10, 변동성타게팅</th><th>CAGR</th><th>MDD</th><th>샤프비율</th></tr></thead>
          <tbody>{top10_table_html}</tbody>
        </table>
      </div>
      <p class="fig-caption">강조된 행(오버레이 없음)이 이 표에서 가장 높은 CAGR·샤프 — 이례적으로
      변동성타게팅을 얹을수록 오히려 나빠진다(로테이션 자체가 이미 약한 종목을 매달 걸러내며 위험을
      관리하고 있어서로 보인다).</p>

      <div class="chart-card">
        <h3>50종목 유니버스 Top10 모멘텀 로테이션 vs S&amp;P500(로그축)</h3>
        <p class="chart-desc">기준 100 · {esc(START_DATE)} ~ {esc(GEN_DATE)} · 오버레이 없음</p>
        <div class="legend">
          <span class="lg-item"><span class="lg-swatch" style="background:var(--blue)"></span>Top10 모멘텀 로테이션</span>
          <span class="lg-item"><span class="lg-swatch" style="background:var(--aqua)"></span>S&amp;P500 매수보유</span>
        </div>
        <div id="chart-momentum-50u-equity"></div>
      </div>

      <p class="caveat">⚠️ <b>이 결과(CAGR {fnum(top10_none['cagr'])}%, 샤프 {fnum(top10_none['sharpe'])})를
      "모멘텀 로테이션이 시장을 압도한다"는 일반 법칙으로 읽으면 안 된다.</b> 이 50종목 유니버스는
      애초에 <b>2026년 현재 기준 각 업종의 최종 승자들</b>(NVDA·TSLA·AVGO 등)로 골라 놓은 것이고
      (02장), 모멘텀 랭킹은 매달 그 중에서도 "가장 잘 나가는" 종목에 자본을 더 몰아준다 — 즉
      생존편향을 완화하는 게 아니라 오히려 증폭시키는 방향이다. 07장 포트폴리오 변동성타게팅
      결과(분산 도구가 코스톨라니 신호와 무관하게 작동)와 달리, 이 결과의 대부분은 <b>"이미 결과를
      아는 상태에서 고른 승자 종목에 집중 베팅했다"는 사후편향</b>에서 나온다. 실전에서 재현하려면
      "그 시점에 이미 알려진" 종목 유니버스로, 그리고 이상적으로는 다른 기간·다른 시장에서 다시
      검증해야 한다.</p>

      {unbiased_html if HAS_UNBIASED else ''}

      <p><b>정리하면:</b> 이번엔 07장(코스톨라니 포트폴리오)만큼 깔끔하지 않다. 변동성타게팅은
      11개 섹터 ETF에서는 샤프비율을 소폭 개선했지만({fnum(mno['sharpe'])}→{fnum(mvt['sharpe'])}),
      50종목 유니버스(편향 O·편향 제거 모두)에서는 오히려 나빠졌다 — "약한 종목을 걸러내는" 절대
      모멘텀 필터 자체가 이미 위험관리 역할을 하고 있어, 그 위에 변동성타게팅을 더 얹으면 대개
      살아남은 강세 국면의 상승분까지 깎아내는 쪽으로 작용하는 것으로 보인다. 즉 "분산+변동성관리가
      신호와 무관하게 항상 위험조정수익을 높인다"는 07장의 결론은 <b>여기서는 일반화되지 않는다</b> —
      효과는 전략의 나머지 구조(이미 위험관리 메커니즘이 내장돼 있는지)에 따라 달라진다. 그리고
      모멘텀 로테이션을 더 큰 종목 풀에 거는 것의 극적인 성과는 대부분 유니버스 선정의 사후편향과
      (이 리포트 자체의 구현 버그로 인한) 계산 구간 축소가 만든 것이라 그대로 신뢰하기 어렵다는
      점은 위에서 이미 확인했다.</p>

      <p class="fig-caption">추가로 확인한 것: Top10/Top15를 동일비중 대신 위험균등(inverse-vol)
      가중으로 바꿔도 개선되지 않았다(Top10 샤프 1.15 → 1.13, Top15 1.08 → 1.07 — 오히려 근소하게
      하락). 이 유니버스에서는 "약한 종목을 아예 빼는" 절대모멘텀 필터가 이미 위험관리 역할을 하고
      있어, 남은 종목들 사이의 비중 배분 방식(동일 vs 위험균등)은 큰 차이를 만들지 않는 것으로
      보인다.</p>

      {unbiased_portfolio_html if HAS_UNBIASED_PORTFOLIO else ''}

      {bear_market_html if HAS_BEAR_MARKET else ''}

      {practical_html if HAS_PRACTICAL else ''}

      {regime_html if HAS_REGIME else ''}

      {ledger_html if HAS_LEDGER else ''}

      {stress_html if HAS_STRESS else ''}

      {alpha_search_html if HAS_ALPHA else ''}

      {session14_html if HAS_S14 else ''}

      {session15_html if HAS_S15 else ''}

      {session16_html if HAS_S16 else ''}

      {session18_html if HAS_S18 else ''}
    </section>
    """
    mom50_curve_path = f"{OUT_DIR}/momentum_rotation_50universe_equity.json"
    if os.path.exists(mom50_curve_path):
        with open(mom50_curve_path, encoding="utf-8") as f:
            R["momentum_50u_equity"] = json.load(f)
    unbiased_curve_path = f"{OUT_DIR}/momentum_rotation_unbiased_equity.json"
    if os.path.exists(unbiased_curve_path):
        with open(unbiased_curve_path, encoding="utf-8") as f:
            R["momentum_unbiased_equity"] = json.load(f)
    unbiased_port_curve_path = f"{OUT_DIR}/unbiased_portfolio_final_curve.json"
    if os.path.exists(unbiased_port_curve_path):
        with open(unbiased_port_curve_path, encoding="utf-8") as f:
            R["unbiased_portfolio_equity"] = json.load(f)
    bear_curve_path = f"{OUT_DIR}/bear_market_equity.json"
    if os.path.exists(bear_curve_path):
        with open(bear_curve_path, encoding="utf-8") as f:
            R["bear_market_equity"] = json.load(f)
    for key, fname in [("practical_bull_equity", "practical_curve_bull.json"), ("practical_bear_equity", "practical_curve_bear.json"),
                       ("regime_tilt_equity", "regime_tilt_equity.json"),
                       ("leader_compare_equity", "hypothesis_leader_compare_equity.json")]:
        p = f"{OUT_DIR}/{fname}"
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                R[key] = json.load(f)

json_blob = json.dumps(R, ensure_ascii=False).replace("</", "<\\/")
print("Prepared sections. json size:", len(json_blob))

conclusion_html = f"""
<p class="lede"><b>결론: 원전 그대로의 코스톨라니 국면 매매는, 적어도 2015~2026년 미국 대형주 51개
표본에서는 "이겼다"고 말하기 어렵다.</b> 장기 스타일 기준 매수보유를 이긴 종목은 5개 중 1개도 안 됐고
(18%), S&amp;P500 지수를 이긴 종목은 10곳 중 1곳뿐이었다(10%). 스윙 스타일로 바꾸면 S&amp;P500 대비
승률이 32%까지 오르지만, 여전히 평균적으로는 매수보유에 못 미쳤다.</p>

<p>이론이 완전히 무용하다는 뜻은 아니다. 두 가지는 분명히 확인됐다:</p>
<ul style="max-width:72ch; padding-left:20px;">
  <li><b>낙폭 방어 효과는 실재한다.</b> 평균 MDD가 전략 {fnum(overall_j['avg_strategy_mdd'])}% vs 매수보유
  {fnum(overall_j['avg_bh_mdd'])}%로, 거의 모든 업종에서 낙폭이 8~15%p가량 얕아졌다(05장 MDD 덤벨차트).
  "돈을 더 벌지는 못해도 덜 무섭게 벌 수는 있다"는 코스톨라니 이론 본연의 방어적 가치는 데이터로도
  뒷받침된다.</li>
  <li><b>실패는 특정 유형에 집중된다.</b> 문제는 반도체·빅테크처럼 수년간 구조적으로 우상향하는
  종목이다. "52주 고점권에서 거래량을 동반해 오르는" 상태(A3 국면)를 코스톨라니 이론은 "매도 검토"로
  분류하는데, 이런 종목은 인생 대부분을 바로 그 상태로 보낸다 — 이론이 겨냥한 "탐욕과 공포의 순환"이
  아니라 "계속 잘 가는 회사"이기 때문에 이론의 전제 자체가 어긋난다. 반대로 통신·필수소비재·리츠처럼
  박스권 성격이 강한 업종에서는 격차가 훨씬 작았다(-1.6~-8.2%p 수준, 05장 참고).</li>
</ul>

<p>{best_grid_note}</p>

<p>실전에서 이 결과가 시사하는 바는: 코스톨라니 달걀 이론을 <b>모든 종목에 획일적으로</b> 적용하는 것은
비효율적이고, 대신 <b>추세가 뚜렷한 구조적 성장주는 매수보유(또는 더 느슨한 매도 기준)로, 박스권·경기
민감 업종은 국면 매매로</b> 나누어 쓰는 하이브리드가 이론적으로도 데이터로도 더 합리적이다.</p>

{f'''<p><b>07장에서 이 하이브리드를 실제 규칙(장기추세 게이트 + 부분 비중조절)으로 구현해 검증한 결과,
51개 자산 평균 초과CAGR이 처음으로 플러스({fnum(sw_recommended["mean_excess_cagr_vs_bench"],2,True)}%p)로
전환됐고 S&amp;P500 대비 승률도 {fnum(sw_recommended["win_rate_vs_bench_pct"],1)}%까지 올랐다.</b> 다만
중앙값은 여전히 음수({fnum(sw_recommended["median_excess_cagr_vs_bench"],2,True)}%p)라 "평균적으로
이긴다"이지 "대부분의 종목에서 이긴다"는 아니며, 반도체 섹터의 반전은 사이클 매매 자체의 승리라기보다
추세 게이트가 구조적 성장주에서 매도를 스스로 억제해 매수보유로 수렴한 결과라는 점, 그리고 50종목
포트폴리오로 넓히면 전략과 매수보유 성과가 사실상 동률(분산이 타이밍 비용을 상쇄)이라는 점까지 종합하면,
가장 정직한 결론은 <b>"장기추세를 거스르지 않도록 이론을 보정하면 평균적으로는 시장을 근소하게 이길 수
있지만, 이는 이론 고유의 예측력이라기보다 강한 추세에 개입하지 않는 절제에서 나온다"</b>는 것이다
(자세한 실험은 07장 참고).</p>''' if HAS_COMBINED else ''}

{f'''<p><b>그런데 07장 마지막에 시도한 변동성 타게팅(포트폴리오 수익률 자체에 목표변동성을 씌워 비중을
조절하는 표준 리스크관리 기법)은 이론과 무관하게 명확히 시장을 이겼다</b> — 레버리지 없이(상한 1.0배)
CAGR은 S&amp;P500과 거의 같은데({fnum(vt_m["cagr"])}% vs {fnum(sp_m["cagr"])}%) 샤프비율은 거의
두 배({fnum(vt_m["sharpe"])} vs {fnum(sp_m["sharpe"])}), MDD는 절반 이하({fnum(vt_m["mdd"])}% vs
{fnum(sp_m["mdd"])}%)다. 다만 같은 변동성타게팅을 코스톨라니 신호 없는 단순 매수보유 포트폴리오에
걸어도 거의 동일한 결과가 나왔다 — <b>이 리포트가 찾아낸 "시장을 이기는 방법"의 진짜 공로는 코스톨라니
달걀 이론이 아니라 분산과 변동성 관리라는, 이론과 무관한 표준 포트폴리오 기법에 있다</b>는 것이
가장 정직한 최종 결론이다.</p>''' if HAS_VOL_TARGET else ''}

{f'''<p><b>그런데 08장에서 이 결론 자체도 재검증했다</b> — 50종목 유니버스가 2026년 기준 승자
위주로 골라진 편향된 표본이었기 때문이다. 생존편향을 뺀 실제 표본에 리스크패리티 가중과(변동성
룩백을 더 짧게 조정한) 변동성타게팅을 결합해 다시 걸어보니, 오히려 07장의 결론이 그대로 재현됐다
— CAGR은 S&amp;P500과 거의 같은데({fnum(up_final_m["cagr"])}% vs {fnum(up_sp["cagr"])}%) 샤프비율은
{fnum(up_final_m["sharpe"])}로 S&amp;P500({fnum(up_sp["sharpe"])})보다 뚜렷이 높고 MDD는 절반
수준이다. <b>다만 이번에도 코스톨라니 신호 자체는 무관했다</b> — 신호 없이 매수보유만 같은 방식으로
포트폴리오를 구성해도 사실상 동일한 결과가 나왔다. <b>이 리포트를 관통하는 최종 결론은: "분산과
변동성관리가 위험조정수익을 개선한다"는 명제는 이 리포트가 시도한 모든 변형(신호 있음/없음,
편향 있음/없음, 여러 유니버스)에서 일관되게 살아남은 유일한 발견이고, 코스톨라니 달걀 이론이
그 개선에 실질적으로 기여했다는 증거는 어디에서도 나오지 않았다는 것</b>이다(08장 참고).</p>''' if HAS_UNBIASED_PORTFOLIO else ''}
"""

HAS_SYNTHESIS = HAS_REGIME and HAS_LEDGER and HAS_STRESS and HAS_ALPHA and HAS_S14 and HAS_S15 and HAS_S16
if HAS_SYNTHESIS:
    def syn_row(label, m, cls=""):
        return (
            f'<tr class="{cls}"><td class="tk-cell">{esc(label)}</td><td class="num">{fnum(m["cagr"])}%</td>'
            f'<td class="num">{fnum(m["mdd"])}%</td><td class="num strong">{fnum(m["sharpe"])}</td></tr>'
        )

    final_systems_rows = (
        syn_row("미국 섹터ETF (2015~2026, 쏠림틸트+약세장방어)", r_bull["vol_target"]["tilt_vt"], cls="best-row")
        + syn_row("→ 벤치마크: S&P500 (2015~2026)", r_bull["sp500_bh"])
        + syn_row("미국 팩터ETF (2014~2026, 틸트없음)", fc["no_tilt"], cls="best-row")
        + syn_row("→ 벤치마크: S&P500 (2014~2026)", fc["sp500_bh"])
        + syn_row("국가ETF 9개국 (1998~2026, 역발상틸트)", ct["contrarian_laggard_tilt(신가설)"]["full_1998_2026"], cls="best-row")
        + syn_row("→ 벤치마크: S&P500 (1998~2026)", ct["sp500_full"])
    )

    conclusion_html += f"""
    <h3 style="margin-top:2.5rem;">이 리포트를 관통하는 최종 통합 지도 — 11개 세션·37개 가설을 하나로</h3>
    <p>2026-08-12 최초 발행 이후 여러 세션에 걸쳐 코스톨라니 원전 검증(01~05장)에서 시작해
    하이퍼파라미터 튜닝(06장), 추세필터+비중조절(07장), 그리고 국면별 다중전략·국제화 검증(08장,
    세션11~16)까지 이어졌다. 37개 가설을 관통하는 결론은 세 층으로 정리된다.</p>

    <div class="callout">
      <div class="callout-title">1층 — 어디서나 통하는 원칙: 분산 + 변동성타게팅</div>
      <p>위험관리(리스크패리티 분산 + 실현변동성 기반 노출조절)는 미국 섹터ETF, 미국 팩터ETF,
      9개국 국가ETF(신흥국 포함) 등 이 리포트가 시도한 <b>모든 유니버스에서 일관되게</b> 위험조정
      수익(샤프비율)을 개선하고 MDD를 줄였다. 코스톨라니 신호의 유무와도 무관했다(신호 없는
      매수보유 포트폴리오에도 똑같이 효과가 있었다, 07~08장). 이 리포트에서 유일하게 예외 없이
      살아남은 원칙이다.</p>
    </div>

    <div class="callout">
      <div class="callout-title">2층 — 유니버스에 따라 갈리는 신호: 모멘텀 vs 역발상</div>
      <p><b>미국 국내 분산(GICS 섹터든 스타일 팩터든)에서는 모멘텀(쏠림 리더 추격) 틸트가 이긴다</b>
      — 섹터·팩터 두 유니버스 모두에서 확인됐다. <b>국가간 분산에서는 정반대로 역발상(래거드
      추격) 틸트가 이긴다</b> — 개별종목·섹터 레벨의 평균회귀는 이 리포트 전체에서 기각됐지만
      국가 레벨에서는 유일하게 통했다. 어느 신호가 이기는지는 유니버스의 경제적 성격(구조적
      테마가 몇 년씩 지속되는가, 아니면 통화·정책 사이클로 몇 년 단위로 되돌아가는가)에 달려
      있다 — "국면마다 다른 전략이 맞다"는 사용자의 원래 통찰이 정확히 여기서 확인된다.</p>
    </div>

    <div class="table-wrap">
      <table class="data-table">
        <thead><tr><th>검증된 최종 시스템(대표 조합)</th><th>CAGR</th><th>MDD</th><th>샤프</th></tr></thead>
        <tbody>{final_systems_rows}</tbody>
      </table>
    </div>
    <p class="fig-caption">세 유니버스 모두 위험조정 기준(샤프)으로는 벤치마크와 동률이거나 상회,
    MDD는 뚜렷이 개선. CAGR은 미국 섹터·팩터에서는 벤치마크에 근접, 국가ETF에서는 여전히 격차가
    남는다(세션14~16에서 확인했듯 이 기간 미국 시장 자체의 압도적 성과 때문 — 포트폴리오 기법으로
    완전히 재현되진 않는다).</p>

    <div class="callout">
      <div class="callout-title">기각되거나 트레이드오프로 남은 것들</div>
      <p>코스톨라니 원전 그대로의 개별종목 매매, 켈리 기준 사이징, VIX 임계값 방어, 듀얼모멘텀
      자산군 하드스위치, 레버리지 완화, 래거드 대칭 언더웨이트, 국면강도 비례 연속조절, 섹터/개별
      종목 레벨 평균회귀 — 전부 기각됐다. 절대추세필터(200일선)는 트레이드오프(위기엔 도움, 강세장엔
      손해)로 남았고, 방어자산(TLT/GLD) 블렌드는 평균적으론 유리하지만 2022년처럼 채권-주식
      상관관계가 깨지는 해엔 역효과를 낼 수 있다는 조건부 채택으로 하향됐다. <b>"복잡하게 만들거나
      공격적으로 베팅하면 나아질 것"이라는 직관은 이 리포트가 검증한 거의 모든 사례에서 틀렸다</b> —
      나아진 경우는 예외 없이 "이미 검증된 원칙을 유니버스의 경제적 성격에 맞게 정확히 뒤집거나
      확장한" 경우뿐이었다(모멘텀↔역발상 전환, 섹터↔팩터↔국가 유니버스 확장).</p>
    </div>
    """

# ---------------------------------------------------------------------------
# 최종 조립: template.html의 placeholder를 전부 채워 final_report.html 작성
# ---------------------------------------------------------------------------
with open(f"{OUT_DIR}/template.html", encoding="utf-8") as f:
    tpl = f.read()

with open(f"{OUT_DIR}/chart.js", encoding="utf-8") as f:
    chart_js = f.read()

replacements = {
    "__START_DATE__": START_DATE,
    "__GEN_DATE__": GEN_DATE,
    "__EGG_SVG__": egg_svg,
    "__UNIVERSE_TABLE__": universe_table_html,
    "__KPI_ROW__": kpi_row_html,
    "__STYLE_COMPARE__": style_compare_html,
    "__TUNING_SECTION__": grid_section_html,
    "__COMBINED_SECTION__": combined_section_html,
    "__MOMENTUM_SECTION__": momentum_section_html,
    "__TICKER_TABLE_JANGI__": ticker_table_jangi,
    "__TICKER_TABLE_SWING__": ticker_table_swing,
    "__CONCLUSION__": conclusion_html,
    "__IDX_CAGR_STRAT__": fnum(overall_j["index_cagr_strategy"]),
    "__IDX_CAGR_BH__": fnum(overall_j["index_cagr_bh"]),
    "__JSON_DATA__": json_blob,
    "__CHART_JS__": chart_js,
}
for k, v in replacements.items():
    tpl = tpl.replace(k, v)

final_path = f"{OUT_DIR}/final_report.html"
with open(final_path, "w", encoding="utf-8") as f:
    f.write(tpl)

print("Wrote", final_path, "size(bytes)=", os.path.getsize(final_path))

