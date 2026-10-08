"""검증 연구 theme-rotation-v1: 지금 '불장'인 테마 ETF 를 빨리 잡아 들고 있으면, 자주 갈아타지 않고도 SPY 를 압도하나. (사전 등록, 2026-10-08)

사용자 의견(2026-10-08): "특정 기간에는 특정 섹터가 반짝인다 — 로봇이 뜰 때 로봇, 반도체가 뜰 때 반도체. 1~3달마다 감시.
중요한 건 1) 지금 어느 시장이 불장인지 2) 그걸 재빨리 잡는지 3) 여러 번 순환하지 않아도 SPY 를 압도하는지."

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
테마 목록(고정, 28개 — 상장 후 252거래일이 지나야 후보가 된다. 없던 ETF 를 과거에 쓰지 않음):
  반도체 SMH · 소프트웨어 IGV · 클라우드 SKYY · 사이버보안 HACK · 로봇·자동화 ROBO · 혁신 ARKK · 바이오 IBB · 소형 바이오 XBI ·
  의료기기 IHI · 방산 ITA · 태양광 TAN · 클린에너지 ICLN · 리튬·배터리 LIT · 우라늄 URA · 금광 GDX · 석유탐사 XOP · 유전서비스 OIH ·
  지역은행 KRE · 주택건설 XHB · 운송 IYT · 소매 XRT · 인터넷 FDN · 소셜미디어 SOCL · 물 PHO · 금속·광업 XME · 구리 COPX ·
  농업 MOO · 인프라 PAVE
'불장'(기준 1): 전날 종가가 200일 이동평균 위 AND 최근 L 거래일 수익률이 같은 기간 SPY 보다 높음. 불장 테마가 슬롯보다 적으면 남는 몫은 SPY.
규칙(18개 = L {21, 63, 126} × 상위 N {1, 2, 3} × 보유 {1, 3}개월): 매 1 또는 3개월 첫 거래일, 불장 테마 중 최근 L일 수익률 상위 N 개를
  같은 비중으로 사서 다음 점검일까지 보유(다음 날 체결, 편도 5bp). 비교 대상(기준선): SPY 그냥 보유. 참고: 현 코어.
판정 theme-judge/v1 — 모두 만족해야 PASS(사람 검토 대기, 엔진 자동 반영 없음):
  A. (과적합 방지, sprint-judge 와 같은 장치) 2007-01 ~ 마지막 2년 전(앞 구간)에서 샤프 최선 1개를 고르고, 그 승자가
     SPY 대비 초과의 Deflated Sharpe ≥ 0.95(시도 18), CSCV 과적합 확률 PBO ≤ 25%, 떼어 둔 2년 샤프 > SPY.
  B. (기준 3 — 돈) 승자를 카카오페이증권 계좌(core/tax_fx 기본, 3,000만 원, 원화)로 굴린 세후·청산 후 연수익이
     SPY 그냥 보유보다 전체 기간 +2.0%p 이상, 떼어 둔 2년에서도 SPY 보다 높음.
진단(판정 아님, 기준 1·2): 고른 테마가 보유 기간에 SPY 를 이긴 비율(적중률), '뜨거운 달'(테마가 그달 상위 3 이고 SPY 를 5%p 이상
  이김)에 실제로 들고 있던 비율(포착률)과 연속된 뜨거운 구간의 시작부터 처음 보유까지 걸린 달 수(지연).
한계: 사라진 테마 ETF 는 데이터에 없어 생존편향(실제보다 좋게 나올 수 있음), 테마 ETF 의 다수가 2010년 전후 상장(초기 후보 적음), 일봉 종가.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import sprint_lab as sp  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JUDGE_VERSION = "theme-judge/v1"
THEMES = ["SMH", "IGV", "SKYY", "HACK", "ROBO", "ARKK", "IBB", "XBI", "IHI", "ITA", "TAN", "ICLN", "LIT", "URA", "GDX",
          "XOP", "OIH", "KRE", "XHB", "IYT", "XRT", "FDN", "SOCL", "PHO", "XME", "COPX", "MOO", "PAVE"]
START = "2007-01-01"
LOOKBACKS = (21, 63, 126)
TOP_NS = (1, 2, 3)
HOLDS = (1, 3)
BPS = 5.0
MIN_AFTER_TAX_EDGE = 0.02


def _data(smoke: bool):
    tick = THEMES + ["SPY"]
    if smoke:
        idx = pd.bdate_range("2005-01-03", "2014-12-31")
        rng = np.random.default_rng(8)
        close = pd.DataFrame({t: 50 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, len(idx)))) for t in tick}, index=idx)
        for t in THEMES[20:]:
            close.loc[close.index < "2010-06-01", t] = np.nan  # 늦게 상장한 테마 흉내
        return close, close.copy(), pd.Series(1100.0, index=idx)
    from core.market_data import get_multiple_price_history

    h = get_multiple_price_history(tick, start="2005-06-01", end=None, interval="1d")
    close = pd.DataFrame({t: h[t]["Close"] for t in tick if t in h and not h[t].empty}).sort_index()
    adj = pd.DataFrame({t: h[t]["Adj Close"] for t in tick if t in h and not h[t].empty}).sort_index()
    days = close["SPY"].dropna().index
    return close.reindex(days), adj.reindex(days), tx.usdkrw_series()


def build_weights(close: pd.DataFrame, L: int, n: int, hold: int, start: str) -> tuple[pd.DataFrame, list]:
    days = close.index[close.index >= pd.Timestamp(start)]
    months = pd.Series(days, index=days).groupby(days.to_period("M")).first()
    rebal = [d for i, d in enumerate(months.values) if i % hold == 0]
    sma = close.rolling(200, min_periods=200).mean()
    ret = close / close.shift(L) - 1
    age = close.notna().cumsum()
    cols = [t for t in THEMES if t in close.columns] + ["SPY"]
    w = pd.DataFrame(np.nan, index=days, columns=cols)
    picks_log = []
    for d in rebal:
        d = pd.Timestamp(d)
        i = close.index.get_loc(d)
        prev = close.index[i - 1]  # 전날 종가까지만 본다
        spy_r = ret.at[prev, "SPY"]
        bulls = []
        for t in cols[:-1]:
            c, s, r = close.at[prev, t], sma.at[prev, t], ret.at[prev, t]
            if age.at[prev, t] >= 252 and pd.notna(c) and pd.notna(s) and pd.notna(r) and c > s and pd.notna(spy_r) and r > spy_r:
                bulls.append((t, float(r)))
        bulls.sort(key=lambda kv: (-kv[1], kv[0]))
        chosen = [t for t, _ in bulls[:n]]
        row = pd.Series(0.0, index=cols)
        for t in chosen:
            row[t] = 1.0 / n
        row["SPY"] += (n - len(chosen)) / n
        w.loc[d] = row
        picks_log.append((d, chosen))
    return w.ffill().fillna(0.0), picks_log


def daily_returns(w: pd.DataFrame, adj: pd.DataFrame) -> pd.Series:
    r = adj[w.columns].pct_change(fill_method=None).reindex(w.index).fillna(0.0)
    ex = w.shift(1).fillna(0.0)
    turnover = (ex - ex.shift(1).fillna(0.0)).abs().sum(axis=1)
    return (r * ex).sum(axis=1) - turnover * BPS / 1e4


def diagnostics(picks, close: pd.DataFrame, hold: int) -> dict:
    hits, n = 0, 0
    for i, (d, chosen) in enumerate(picks):
        end = picks[i + 1][0] if i + 1 < len(picks) else close.index[-1]
        for t in chosen:
            a, b = close.at[d, t], close.at[end, t]
            sa, sb = close.at[d, "SPY"], close.at[end, "SPY"]
            if pd.notna(a) and pd.notna(b):
                n += 1
                hits += int(b / a > sb / sa)
    m = close.resample("ME").last()
    mr = m.pct_change(fill_method=None)
    held = {}
    for i, (d, chosen) in enumerate(picks):
        end = picks[i + 1][0] if i + 1 < len(picks) else close.index[-1]
        for p in pd.period_range(d.to_period("M"), end.to_period("M")):
            if p != end.to_period("M") or i + 1 == len(picks):
                held.setdefault(p, set()).update(chosen)
    hot, caught, lags = 0, 0, []
    start_p = picks[0][0].to_period("M") if picks else None
    for t in THEMES:
        if t not in mr.columns:
            continue
        run = None
        for ts, v in mr[t].items():
            p = ts.to_period("M")
            if start_p is None or p < start_p or pd.isna(v):
                continue
            rank = mr.loc[ts, THEMES if all(x in mr.columns for x in THEMES) else [c for c in THEMES if c in mr.columns]].rank(ascending=False)[t]
            is_hot = rank <= 3 and v - mr.at[ts, "SPY"] >= 0.05
            if is_hot:
                hot += 1
                got = t in held.get(p, set())
                caught += int(got)
                if run is None:
                    run = {"start": p, "first_hold": p if got else None}
                elif run["first_hold"] is None and got:
                    run["first_hold"] = p
            elif run is not None:
                if run["first_hold"] is not None:
                    lags.append((run["first_hold"] - run["start"]).n)
                run = None
    return {"hit_rate_vs_spy": hits / n if n else None, "n_picks": n, "hot_months": hot,
            "hot_month_capture": caught / hot if hot else None, "median_lag_months": float(np.median(lags)) if lags else None,
            "rebalances": len(picks), "avg_themes_held": float(np.mean([len(c) for _, c in picks])) if picks else None}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    close, adj, fx = _data(a.smoke)
    start = "2006-01-02" if a.smoke else START

    configs, rets, weights, picks = [], {}, {}, {}
    for L in LOOKBACKS:
        for n in TOP_NS:
            for hold in HOLDS:
                name = f"L{L}_top{n}_hold{hold}m"
                w, pk = build_weights(close, L, n, hold, start)
                configs.append(name)
                rets[name], weights[name], picks[name] = daily_returns(w, adj), w, pk
    idx = rets[configs[0]].index
    spy_w = pd.DataFrame({"SPY": 1.0}, index=idx)
    rets["SPY_hold"] = daily_returns(spy_w, adj)
    names = configs + ["SPY_hold"]
    mat = np.column_stack([rets[k].reindex(idx).to_numpy() for k in names])
    split = idx[-1] - pd.DateOffset(years=2)
    fam = sp.finalize_returns_family(names, mat, idx, split, "SPY_hold")
    win = fam["winner"]
    checks_a = {"winner_is_not_spy": win != "SPY_hold", "dsr_ge_0.95": fam["dsr"] >= sp.DSR_MIN,
                "pbo_le_25pct": fam["pbo"] is not None and fam["pbo"]["pbo"] <= sp.PBO_MAX,
                "holdout_sharpe_gt_spy": bool(fam["winner_oos"] and fam["incumbent_oos"] and fam["winner_oos"]["sharpe"] > fam["incumbent_oos"]["sharpe"])}

    def after_tax(w: pd.DataFrame, lo=None) -> dict:
        ww = w if lo is None else w[w.index >= lo]
        r = tx.simulate(ww, close, adj, fx, tx.AccountConfig())
        yrs = (ww.index[-1] - ww.index[0]).days / 365.25
        return {"cagr_after_liquidation": (r["final_after_liquidation_krw"] / 30_000_000) ** (1 / yrs) - 1,
                "cagr_after": r["cagr_after"], "cagr_pre": r["cagr_pre"], "mdd_after": r["mdd_after"],
                "capital_gains_tax_krw": r["totals"]["capital_gains_tax_krw"], "fees_krw": r["totals"]["fees_krw"]}

    win_w = weights.get(win, spy_w)
    tax = {"winner_full": after_tax(win_w), "spy_full": after_tax(spy_w),
           "winner_holdout": after_tax(win_w, split), "spy_holdout": after_tax(spy_w, split)}
    edge = tax["winner_full"]["cagr_after_liquidation"] - tax["spy_full"]["cagr_after_liquidation"]
    checks_b = {"after_tax_edge_ge_2pp": win != "SPY_hold" and edge >= MIN_AFTER_TAX_EDGE,
                "holdout_after_tax_gt_spy": win != "SPY_hold" and tax["winner_holdout"]["cagr_after_liquidation"] > tax["spy_holdout"]["cagr_after_liquidation"]}
    verdict = "PASS" if all(checks_a.values()) and all(checks_b.values()) else "FAIL"
    diag = {k: diagnostics(picks[k], close, int(k.split("hold")[1][0])) for k in configs}
    result = {"judge_version": JUDGE_VERSION, "smoke": a.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "verdicts": {"theme_rotation": verdict}, "winner": win, "checks_overfit": checks_a, "checks_money": checks_b,
              "after_tax_edge_pp": edge * 100, "family": fam, "after_tax": tax, "diagnostics": diag, "holdout_start": str(split.date()),
              "winner_recent_picks": [(str(d.date()), c) for d, c in picks.get(win, [])[-6:]]}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    def pct(v):
        return "—" if v is None else f"{v * 100:.1f}%"
    lines = [f"# 테마 순환 v1 ({JUDGE_VERSION}){' — 스모크(가짜 데이터)' if a.smoke else ''}", "",
             f"판정 **{verdict}** · 앞 구간 승자 `{win}` · 떼어 둔 구간 {split.date()}~", "",
             "## 기준 3 — 세후로 SPY 를 압도하나 (3,000만 원, 원화, 청산 후)", "",
             "| | 전체 | 떼어 둔 2년 | 원화 MDD(전체) | 양도세(백만) |", "|---|---|---|---|---|",
             f"| 승자 {win} | {pct(tax['winner_full']['cagr_after_liquidation'])} | {pct(tax['winner_holdout']['cagr_after_liquidation'])} | {pct(tax['winner_full']['mdd_after'])} | {tax['winner_full']['capital_gains_tax_krw'] / 1e6:.1f} |",
             f"| SPY 그냥 보유 | {pct(tax['spy_full']['cagr_after_liquidation'])} | {pct(tax['spy_holdout']['cagr_after_liquidation'])} | {pct(tax['spy_full']['mdd_after'])} | {tax['spy_full']['capital_gains_tax_krw'] / 1e6:.1f} |",
             "", f"세후 차이 {edge * 100:+.2f}%p/년 (기준 +2.0%p) · 과적합 검사: DSR {fam['dsr']:.2f}(≥0.95), PBO {pct((fam['pbo'] or {}).get('pbo'))}(≤25%), "
             f"떼어 둔 2년 샤프 {fam['winner_oos'].get('sharpe', float('nan')):.2f} vs SPY {fam['incumbent_oos'].get('sharpe', float('nan')):.2f}", "",
             "## 기준 1·2 — 불장을 맞히고 빨리 잡나 (진단, 판정 아님)", "",
             "| 규칙 | 적중률(보유 기간 SPY 이김) | 뜨거운 달 포착률 | 지연(중앙값, 달) | 점검 횟수 |", "|---|---|---|---|---|"]
    order = [c["config"] for c in fam["top10"] if c["config"] in diag][:8]
    for k in order:
        dg = diag[k]
        lines.append(f"| {k} | {pct(dg['hit_rate_vs_spy'])} | {pct(dg['hot_month_capture'])} | {dg['median_lag_months'] if dg['median_lag_months'] is not None else '—'} | {dg['rebalances']} |")
    lines += ["", "승자의 최근 선택: " + "; ".join(f"{d} {', '.join(c) or 'SPY'}" for d, c in result["winner_recent_picks"]), "",
              "한계: 사라진 테마 ETF 는 데이터에 없음(생존편향), 테마 ETF 다수가 2010년 전후 상장, 일봉 종가 체결. PASS 도 사람 검토 대기."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(result["verdicts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
