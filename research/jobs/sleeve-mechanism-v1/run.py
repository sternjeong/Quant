"""검증 연구 sleeve-mechanism-v1 (2026-11-11 사전 등록): 레버리지 다리의 이득은 어디서 오나 — 변동성 조절·200일선·하락장 몰아넣기.

engine-candidate-v1 에서 실제 SSO 로 'SPY 80 + SSO 20(200일선 필터)' 이 SPY 를 이겼지만, 필터 없는 SSO 20 도 이겨서 이득의 대부분이
'베타를 더 진 대가'인지 '필터의 시점 선택'인지 갈리지 않았다. 여기서는 1927~2024 미국 시장(Ken French 일별)으로 팔지 않는 월 10만 원 적립에서
새 돈의 20% 를 넣는 다리를 네 가지로 바꿔 비교한다.

  L20N  = 합성 2배 늘 켜짐(필터 없음)                     — 기준 1(순수 베타)
  L20F  = 합성 2배 + band200 필터(꺼지면 RF)              — 기준 2(현재 후보)
  VM20  = 변동성 조절 레버리지(Moreira–Muir 2017 계열): 매달 첫 거래일에 L = min(2, 2 × σ_ref / σ_21)
          σ_21 = 전날까지 21거래일 실현 변동성(연율), σ_ref = 그때까지의 월초 σ_21 들의 중앙값(12개 이상, 미리 보기 없음, 그 전엔 L=1)
  VMF20 = VM20 의 L 에 band200 필터를 곱한 것(필터 꺼지면 L=0 → RF)
  U20F  = 1배(레버리지 없음) + band200 필터 — 필터 혼자의 시점 가치(보고)
  DDL   = 평소엔 새 돈 100% 시장, 적립일 전날 시장이 252거래일 고점보다 20% 이상 아래면 그달 돈 100% 를 필터 없는 2배에 넣고 영원히 보유(보고)

L 배 다리의 일 수익 = L×r + (1−L)×rf − max(L−1, 0)×차입 가산(연 1%)/252 − 보수(연 0.9%)/252 × [L>0], L 이 바뀐 날 |ΔL| × 10bp.
판정(선택: 끝 ≤ 1966, 확인: 1967~2007, 각 10·20년 = 네 칸 모두):
  VM_BEATS_MARKET(VM20·VMF20 각각) ⇔ 대 시장 ① 이긴 구간 ≥ 65% ② 세후 IRR 차이 중앙값 ≥ +0.3%p ③ 10분위 ≥ −1.5%p ④ 계좌 최대낙폭 중앙값이 시장보다 10%p 넘게 나쁘지 않음.
  VM_BEATS_FILTER(VM20·VMF20 각각) ⇔ 대 L20F ① 이긴 구간 ≥ 60% ② IRR 차이 중앙값 ≥ +0.2%p ③ 계좌 최대낙폭 중앙값이 L20F 보다 3%p 넘게 나쁘지 않음.
  FILTER_ADDS_VALUE ⇔ L20F 가 대 L20N 으로 ① 이긴 구간 ≥ 50% ② IRR 차이 중앙값 ≥ 0 ③ 계좌 최대낙폭 중앙값이 5%p 이상 덜 깊음 (같은 비중에서 필터가 위험을 줄이며 수익을 잃지 않나).
U20F·DDL·2008 이후 구간은 보고만. 엔진은 바뀌지 않는다.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "dca-dip-deploy-v1"))
sys.path.insert(0, str(HERE.parents[2]))
import lab as L  # noqa: E402

JOB_ID = "sleeve-mechanism-v1"
RULES_VERSION = "sleeve-mechanism-v1/2026-11-11"
MONTHLY_KRW = 100_000
W = 0.20
FIN, FEE_Y, COST_BPS = 0.010, 0.009, 10.0
VOL_WIN, VOL_MIN_HIST, L_CAP = 21, 12, 2.0
DD_TRIGGER, DD_LOOKBACK = 0.20, 252
HORIZONS = (10, 20)
JUDGED_SETS = ("selection", "confirmation")
MKT_RULE = (0.65, 0.003, -0.015, 0.10)        # 이긴 비율, IRR 중앙값, 10분위, MDD 허용
VS_FILTER = (0.60, 0.002, 0.03)               # 이긴 비율, IRR 중앙값, MDD 허용
FILTER_VALUE = (0.50, 0.0, 0.05)              # 이긴 비율, IRR 중앙값, MDD 개선 최소
ARMS = ("L20N", "L20F", "VM20", "VMF20", "U20F", "DDL")
LABELS = {"L20N": "시장 80 + 2배 20 (필터 없음)", "L20F": "시장 80 + 2배 20 (200일선)", "VM20": "시장 80 + 변동성 조절 레버리지 20",
          "VMF20": "시장 80 + 변동성 조절 × 200일선 20", "U20F": "시장 80 + 1배 20 (200일선, 보고)", "DDL": "하락장(−20%)에만 2배 몰아넣기 (보고)"}


def vm_leverage(mkt: pd.Series) -> np.ndarray:
    """매달 첫 거래일에 정하는 레버리지(전날까지의 자료만). 다음 달 첫 거래일까지 유지."""
    r = mkt.fillna(0.0).to_numpy()
    sig = pd.Series(r).rolling(VOL_WIN, min_periods=VOL_WIN).std().to_numpy() * np.sqrt(252)
    flags = L.lab.month_first_mask(mkt.index)
    out, cur, hist = np.zeros(len(r)), 1.0, []
    for i in range(len(r)):
        if flags[i] and i > 0 and np.isfinite(sig[i - 1]) and sig[i - 1] > 0:
            if len(hist) >= VOL_MIN_HIST:
                cur = min(L_CAP, L_CAP * float(np.median(hist)) / sig[i - 1])
            hist.append(sig[i - 1])
        out[i] = cur
    return out


def lev_leg(mkt: pd.Series, rf: pd.Series, lev: np.ndarray) -> pd.Series:
    """lev[i] = i 일 장 마감 뒤 정한 다음 날 레버리지. i 일 수익은 lev[i-1] 로."""
    r = mkt.fillna(0.0).to_numpy()
    f = rf.reindex(mkt.index).fillna(0.0).to_numpy()
    out = np.zeros(len(r))
    for i in range(1, len(r)):
        lv = lev[i - 1]
        x = lv * r[i] + (1 - lv) * f[i] - max(lv - 1.0, 0.0) * FIN / 252 - (FEE_Y / 252 if lv > 0 else 0.0)
        prev = lev[i - 2] if i >= 2 else lv
        if lv != prev:
            x = (1 + x) * (1 - abs(lv - prev) * COST_BPS / 1e4) - 1
        out[i] = x
    return pd.Series(out, index=mkt.index)


def build(data: dict):
    days = data["mkt"].dropna().index
    mkt = data["mkt"].reindex(days)
    rf = data["rf"].reindex(days).fillna(0.0)
    lvl = (1 + mkt.fillna(0.0)).cumprod()
    band = L.leg_state(lvl, "band200").to_numpy(dtype=float)
    vm = vm_leverage(mkt)
    legs = {
        "N": L.leg_returns(mkt, rf, fin_spread=FIN, fee=FEE_Y, mode="none", cost_bps=COST_BPS),
        "F": L.leg_returns(mkt, rf, fin_spread=FIN, fee=FEE_Y, mode="band200", cost_bps=COST_BPS),
        "VM": lev_leg(mkt, rf, vm),
        "VMF": lev_leg(mkt, rf, vm * band),
        "U": lev_leg(mkt, rf, band),
    }
    cols = ["M", "N", "F", "VM", "VMF", "U"]
    px = np.column_stack([L.level(mkt).to_numpy()] + [L.level(legs[c]).to_numpy() for c in cols[1:]])
    dd = (lvl / lvl.rolling(DD_LOOKBACK, min_periods=1).max() - 1).shift(1).fillna(0.0).to_numpy()
    stats = {"vm_mean_lev": float(np.mean(vm)), "vm_share_at_cap": float(np.mean(vm >= L_CAP - 1e-9)),
             "vmf_mean_lev": float(np.mean(vm * band)), "band_on_share": float(np.mean(band)),
             "dd_trigger_month_share": float(np.mean(dd[L.lab.month_first_mask(days)] <= -DD_TRIGGER))}
    return days, px, cols, dd, stats


def weights_for(arm: str, cols: list, dd: np.ndarray):
    c = cols.index
    if arm == "DDL":
        return lambda r: [(c("N"), 1.0)] if dd[r] <= -DD_TRIGGER else [(0, 1.0)]
    leg = {"L20N": "N", "L20F": "F", "VM20": "VM", "VMF20": "VMF", "U20F": "U"}[arm]
    return lambda r: [(0, 1 - W), (c(leg), W)]


def compare(rows: list, rule: tuple, kind: str) -> dict:
    if kind == "market":
        v = L.kpi_pairs_verdict(rows, rule[0], rule[1], rule[2])
    else:
        v = L.kpi_pairs_verdict(rows, rule[0], rule[1], -1.0)
        v["checks"].pop("p10_irr", None)
    if not rows:
        return v
    v["median_mdd_gap"] = float(np.nanmedian([r["mdd_gap"] for r in rows]))
    v["median_ratio"] = float(np.nanmedian([r["ratio"] for r in rows]))
    if kind == "market":
        v["checks"]["mdd"] = v["median_mdd_gap"] >= -rule[3]
    elif kind == "filter":
        v["checks"]["mdd"] = v["median_mdd_gap"] >= -rule[2]
    else:  # filter_value: L20F 낙폭이 L20N 보다 rule[2] 이상 얕아야
        v["checks"]["mdd"] = v["median_mdd_gap"] >= rule[2]
    v["pass"] = all(v["checks"].values())
    return v


def eval_set(days, px, cg, cols, dd, wins) -> dict:
    res = {a: [] for a in ARMS}
    mk = []
    for s, e in wins:
        mk.append(L.weighted_window(px, cg, days, s, e, MONTHLY_KRW, lambda r: [(0, 1.0)]))
        for a in ARMS:
            res[a].append(L.weighted_window(px, cg, days, s, e, MONTHLY_KRW, weights_for(a, cols, dd)))
    out = {}
    for a in ARMS:
        out[f"{a}|market"] = compare([L.pair_summary(x, b) for x, b in zip(res[a], mk)], MKT_RULE, "market")
    for a in ("VM20", "VMF20"):
        out[f"{a}|L20F"] = compare([L.pair_summary(x, b) for x, b in zip(res[a], res["L20F"])], VS_FILTER, "filter")
    out["L20F|L20N"] = compare([L.pair_summary(x, b) for x, b in zip(res["L20F"], res["L20N"])], FILTER_VALUE, "filter_value")
    out["irr_median"] = {a: float(np.nanmedian([x["irr"] for x in res[a]])) if wins else None for a in ARMS}
    out["irr_median"]["MKT"] = float(np.nanmedian([x["irr"] for x in mk])) if wins else None
    out["mdd_median"] = {a: float(np.nanmedian([x["mdd"] for x in res[a]])) if wins else None for a in ARMS}
    out["mdd_median"]["MKT"] = float(np.nanmedian([x["mdd"] for x in mk])) if wins else None
    return out


def body(R: "L.Runner"):
    data = R.stage("inputs", lambda: L.load_long_synthetic() if R.smoke else L.load_long_real())
    days, px, cols, dd, stats = R.stage("panel", lambda: build(data))
    cg = np.cumprod(1 + data["rf"].reindex(days).fillna(0.0).to_numpy() * (1 - L.INTEREST_TAX))
    cells = {}
    for h in HORIZONS:
        sets = L.window_sets(days, h, R.smoke)
        for sn, wins in sets.items():
            cells[f"{h}y|{sn}"] = R.stage(f"set_{h}y_{sn}", lambda wins=wins: eval_set(days, px, cg, cols, dd, wins))
    judged = [f"{h}y|{sn}" for h in HORIZONS for sn in JUDGED_SETS]

    def all_pass(key):
        return all(cells[k].get(key, {}).get("pass") is True for k in judged)

    verdicts = {}
    for a in ("VM20", "VMF20"):
        verdicts[f"{a}_vs_market"] = "VM_BEATS_MARKET" if all_pass(f"{a}|market") else "FAIL"
        verdicts[f"{a}_vs_L20F"] = "VM_BEATS_FILTER" if all_pass(f"{a}|L20F") else "FAIL"
    verdicts["L20F_vs_L20N"] = "FILTER_ADDS_VALUE" if all_pass("L20F|L20N") else "FAIL"
    if R.smoke:
        verdicts = {k: f"SMOKE_ONLY({v})" for k, v in verdicts.items()}
    report_only = {a: {k: cells[k].get(f"{a}|market", {}).get("pass") for k in judged} for a in ("L20N", "L20F", "U20F", "DDL")}
    result = L.rnd({"judge_version": RULES_VERSION, "smoke": R.smoke, "source": data.get("source"), "verdicts": verdicts, "cells": cells,
                    "report_only_vs_market": report_only, "leg_stats": stats,
                    "rule": {"monthly_krw": MONTHLY_KRW, "weight": W, "fin_spread": FIN, "fee": FEE_Y, "cost_bps": COST_BPS,
                             "vol_win": VOL_WIN, "vol_min_hist": VOL_MIN_HIST, "lev_cap": L_CAP, "dd_trigger": DD_TRIGGER,
                             "market_rule": MKT_RULE, "vs_filter_rule": VS_FILTER, "filter_value_rule": FILTER_VALUE}})
    if R.smoke:
        c = cells["10y|selection"]
        assert c["L20F|market"].get("n", 0) > 0, "빈 구간"
        assert 0 < stats["vm_mean_lev"] <= L_CAP, "레버리지 범위 이상"
        assert len({round(c["irr_median"][a], 8) for a in ARMS}) >= 4, "팔이 서로 구별되지 않음"
    return result, render(result)


def render(r: dict) -> str:
    v, P, st = r["verdicts"], L.pct, r["leg_stats"]
    out = [f"# 레버리지 다리의 이득은 어디서 오나 v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
           "팔지 않는 월 10만 원 적립에서 새 돈의 20% 를 넣는 다리를 바꿔, 시장을 이긴 몫이 '베타를 더 진 대가'인지, 200일선이나 변동성 조절 같은 "
           "'시점 선택'이 더한 가치인지 1927~2024 미국 자료로 가른다.", "",
           "**판정**", ""]
    for k, val in v.items():
        out.append(f"- {k}: **{val}**")
    out += ["", "통과는 엔진 반영이 아니다. 엔진은 바뀌지 않았다.", "", "## 규칙 (결과를 보기 전에 고정)", "",
            "- 다리 일 수익 = L×시장 + (1−L)×RF − max(L−1,0)×차입 가산 연 1% − 보수 연 0.9%(L>0), L 이 바뀐 날 |ΔL|×10bp.",
            "- VM: 매달 첫 거래일 L = min(2, 2 × σ_ref / σ_21). σ_21 은 전날까지 21거래일 실현 변동성, σ_ref 는 그때까지 월초 σ_21 의 중앙값(12개 이상, 그 전엔 L=1).",
            "- VMF: VM 의 L × band200 켜짐(0/1). U20F: L = band200 켜짐(1배). DDL: 적립일 전날 시장이 252거래일 고점 대비 −20% 이하면 그달 돈 전부를 필터 없는 2배에.",
            f"- 대 시장: 이긴 구간 ≥ {MKT_RULE[0]:.0%}, IRR 차이 중앙값 ≥ +{MKT_RULE[1] * 100:.1f}%p, 10분위 ≥ {MKT_RULE[2] * 100:.1f}%p, 계좌 낙폭 중앙값 차이 ≥ −{MKT_RULE[3] * 100:.0f}%p.",
            f"- 대 L20F: 이긴 구간 ≥ {VS_FILTER[0]:.0%}, IRR 차이 중앙값 ≥ +{VS_FILTER[1] * 100:.1f}%p, 낙폭 차이 ≥ −{VS_FILTER[2] * 100:.0f}%p.",
            f"- 필터 가치(L20F 대 L20N): 이긴 구간 ≥ {FILTER_VALUE[0]:.0%}, IRR 차이 중앙값 ≥ 0, 낙폭이 {FILTER_VALUE[2] * 100:.0f}%p 이상 얕음.",
            "- 선택(끝 ≤ 1966)·확인(1967~2007) × 10·20년 네 칸 모두 통과해야 한다. 2008 이후는 보고만.", "",
            f"다리 통계: VM 평균 L {st['vm_mean_lev']:.2f} (상한에 붙은 날 {P(st['vm_share_at_cap'], nd=0)}), VMF 평균 L {st['vmf_mean_lev']:.2f}, "
            f"200일선 켜짐 {P(st['band_on_share'], nd=0)}, 하락장 몰아넣기 발동 달 {P(st['dd_trigger_month_share'], nd=0)}.", ""]
    for key, title in [(k, k) for k in r["cells"]]:
        c = r["cells"][key]
        out += [f"## {title}{' (보고만)' if 'post2008' in key else ''}", "",
                "| 비교 | 구간 | 이긴 비율 | IRR 차이 중앙값 / 10분위 | 계좌 낙폭 차이 | 통과 |", "|---|---|---|---|---|---|"]
        for ck, s in c.items():
            if "|" not in ck or not s.get("n"):
                continue
            a, b = ck.split("|")
            out.append(f"| {LABELS.get(a, a)} 대 {'시장' if b == 'market' else LABELS.get(b, b)} | {s['n']} | {P(s['share_win'], nd=0)} | "
                       f"{P(s['median_diff_irr'], True, 2)}p / {P(s['p10_diff_irr'], True, 2)}p | {P(s.get('median_mdd_gap'), True)} | {'예' if s.get('pass') else '아니오'} |")
        im, mm = c.get("irr_median", {}), c.get("mdd_median", {})
        out += ["", "| 팔 | 세후 IRR 중앙값 | 계좌 최대낙폭 중앙값 |", "|---|---|---|"]
        for a in ("MKT",) + ARMS:
            out.append(f"| {LABELS.get(a, '시장 100%')} | {P(im.get(a), nd=2)} | {P(mm.get(a))} |")
        out.append("")
    out += ["## 주의", "",
            "- 합성 레버리지는 식이다. 1930년대에는 이런 상품이 없었고, 실제로는 다리 안에서 바꿀 때마다 팔아야 하므로 양도세가 생긴다(여기 다리는 '한 상품'으로 근사).",
            "- 변동성 조절의 σ_ref 는 그때까지의 자료만 쓰지만, 이 규칙 형태 자체는 2017 년 논문을 보고 고른 것이다(사후 선택 위험).",
            "- 구간이 크게 겹친다. 환율 1,300 원 고정, 배당 원천징수 미반영. 투자 조언이 아니다."]
    if r["smoke"]:
        out += ["", "스모크 실행: 가짜 데이터·짧은 구간이라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    R = L.Runner(RULES_VERSION, argv)
    return R.run(body)


if __name__ == "__main__":
    raise SystemExit(main())
