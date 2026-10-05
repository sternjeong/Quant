"""검증 연구 tax-rnd-v1: 매매 규칙을 세금에 맞게 바꾸면 '세후·청산 후 원화' 수익이 늘어나나. (사전 등록, 2026-10-05)

사용자 요청(2026-10-05): "이러한 세금들도 고려하도록 엔진을 구축해주라." 계좌 모델은 core/tax_fx.py(카카오페이증권:
수수료 0.1%, 달러 보유·환전 스프레드 0.05%, 양도세 250만 원 공제 후 22% 다음 해 5월 납부, 이동평균, 배당 원천징수 15%·즉시 재투자).

## 사전 등록 (결과를 보기 전에 고정 — 바꾸려면 새 id)
비중: 코어 엔진(core_lab, 가격 12개월 모멘텀 상위 4, SPY 200일선 절반, 남는 몫 BIL)의 목표 비중, 코어 100%.
변형(V0 = 현 코어):
  V1 연말 공제 채우기   — 12월 마지막 거래일 3일 전, 그해 실현 이익 < 250만 원이면 이익 난 종목을 팔았다 바로 다시 산다
  V2 연말 손실 확정     — 같은 날, 그해 실현 이익 > 250만 원이면 손실 난 종목을 팔았다 바로 다시 산다
  V3 V1 + V2
  V4 순위 완충 6        — 보유 자산은 순위가 6위 안이면 계속 보유(매매·실현 횟수 감소). 주의: sprint-2w F2 에서 이미 본 설정
  V5 V3 + V4
지표: 세후·청산 후 원화 연수익 = 기간 끝에 전부 팔고 남은 세금까지 낸 금액의 연복리(초기 3,000만 원).
판정 tax-judge/v1 (변형마다 V0 대비, 모두 만족해야 PASS = 사람 검토 대기, 엔진 자동 반영 없음):
  1. 전체 기간(2010-01-01 ~ 실행일) 개선 ≥ +0.15%p/년
  2. 앞 절반(2010-01-01 ~ 2017-12-31)과 뒤 절반(2018-01-01 ~ 실행일)을 각각 새 계좌로 굴렸을 때 둘 다 개선 > 0
  3. 초기 1억 원 계좌(전체 기간)에서도 개선 > 0
  4. 세후 원화 최대낙폭이 V0 보다 3%p 넘게 나쁘지 않음
참고(판정 아님): 선입선출, 매번 원화 환전(우대 0%), 3억 원 계좌.
V4·V5 는 과거에 본 설정이라 PASS 여도 앞으로 토너먼트 같은 앞으로 검증 없이 도입하지 않는다.
한계: 새틀라이트 15% 미포함, 일봉 종가 체결, 연말 '팔았다 다시 사기'는 같은 종가로 근사, 금융소득 종합과세 미반영.
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

from core import champion_strategy as cs  # noqa: E402
from core import core_lab as cl  # noqa: E402
from core import tax_fx as tx  # noqa: E402

JUDGE_VERSION = "tax-judge/v1"
START = "2010-01-01"
SPLIT = "2018-01-01"
MIN_GAIN_PP = 0.15
MDD_TOL = 0.03
VARIANTS = {
    "V0": {"label": "현 코어", "buffer_n": None, "gains": False, "losses": False},
    "V1": {"label": "연말 공제 채우기", "buffer_n": None, "gains": True, "losses": False},
    "V2": {"label": "연말 손실 확정", "buffer_n": None, "gains": False, "losses": True},
    "V3": {"label": "공제 채우기 + 손실 확정", "buffer_n": None, "gains": True, "losses": True},
    "V4": {"label": "순위 완충 6", "buffer_n": 6, "gains": False, "losses": False},
    "V5": {"label": "공제 채우기 + 손실 확정 + 순위 완충 6", "buffer_n": 6, "gains": True, "losses": True},
}


def _data(smoke: bool):
    tickers = list(cs.CORE_UNIVERSE) + [cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF]
    if smoke:
        idx = pd.bdate_range("2008-06-02", "2013-12-31")
        rng = np.random.default_rng(11)
        hist = {}
        for t in tickers:
            c = 50 * np.exp(np.cumsum(rng.normal(0.0004, 0.012, len(idx))))
            hist[t] = pd.DataFrame({"Close": c, "Adj Close": c * np.linspace(0.9, 1.0, len(idx))}, index=idx)
        fx = pd.Series(1100 + 50 * np.sin(np.arange(len(idx)) / 200), index=idx)
        return hist, fx
    from core.market_data import get_multiple_price_history

    return get_multiple_price_history(tickers, start="2008-06-01", end=None, interval="1d"), tx.usdkrw_series()


def _weights(hist, buffer_n):
    tick = [t for t in list(cs.CORE_UNIVERSE) + [cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF] if t in hist]
    price = cs._closes_from_histories(hist, tick)
    core_cols = [t for t in cs.CORE_UNIVERSE if t in price.columns]
    extra = price[[c for c in (cs.MARKET_FILTER_TICKER, cs.CORE_CASH_ETF) if c in price.columns]]
    cfg = cl.with_changes(cl.CoreConfig(cash="bil"), buffer_n=buffer_n) if buffer_n else cl.CoreConfig(cash="bil")
    w = cl.build_weights(price[core_cols], extra, cfg)
    return w.loc[:, (w != 0).any()]


def _cagr_liq(res, start, end, initial):
    yrs = (pd.Timestamp(end) - pd.Timestamp(start)).days / 365.25
    v = res["final_after_liquidation_krw"]
    return (v / initial) ** (1 / yrs) - 1 if yrs > 0 and v > 0 else float("nan")


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    start, split = ("2009-07-01", "2011-07-01") if a.smoke else (START, SPLIT)

    hist, fx = _data(a.smoke)
    close = pd.DataFrame({t: h["Close"] for t, h in hist.items()}).sort_index().ffill()
    adj = pd.DataFrame({t: h["Adj Close"] for t, h in hist.items()}).sort_index().ffill()
    weights = {}
    for buf in {v["buffer_n"] for v in VARIANTS.values()}:
        weights[buf] = _weights(hist, buf)

    def run(vid, lo, hi, **over):
        v = VARIANTS[vid]
        w = weights[v["buffer_n"]]
        w = w[(w.index >= pd.Timestamp(lo)) & (w.index < pd.Timestamp(hi))] if hi else w[w.index >= pd.Timestamp(lo)]
        cfg = tx.AccountConfig(**{"harvest_gains": v["gains"], "harvest_losses": v["losses"], **over})
        res = tx.simulate(w, close, adj, fx, cfg)
        end = w.index[-1]
        return {"cagr_liq": _cagr_liq(res, w.index[0], end, cfg.initial_krw), "cagr_after": res["cagr_after"],
                "cagr_pre": res["cagr_pre"], "mdd_after": res["mdd_after"],
                "final_after_liquidation_krw": res["final_after_liquidation_krw"],
                "totals": res["totals"], "harvests": len(res["harvests"]), "start": str(w.index[0].date()), "end": str(end.date())}

    setups = {
        "full": (start, None, {}),
        "first_half": (start, split, {}),
        "second_half": (split, None, {}),
        "full_100m": (start, None, {"initial_krw": 100_000_000}),
        "ref_fifo": (start, None, {"cost_basis": "fifo"}),
        "ref_krw_each_trade": (start, None, {"fx_mode": "krw_each_trade", "fx_spread": 0.01}),
        "ref_300m": (start, None, {"initial_krw": 300_000_000}),
    }
    metrics = {vid: {name: run(vid, lo, hi, **over) for name, (lo, hi, over) in setups.items()} for vid in VARIANTS}

    verdicts, details = {}, {}
    base = metrics["V0"]
    for vid in VARIANTS:
        if vid == "V0":
            continue
        m = metrics[vid]
        d = {k: (m[k]["cagr_liq"] - base[k]["cagr_liq"]) * 100 for k in setups}
        checks = {
            "full_gain_ge_0.15pp": d["full"] >= MIN_GAIN_PP,
            "both_halves_positive": d["first_half"] > 0 and d["second_half"] > 0,
            "positive_at_100m": d["full_100m"] > 0,
            "mdd_ok": m["full"]["mdd_after"] >= base["full"]["mdd_after"] - MDD_TOL,
        }
        verdicts[vid] = "PASS" if all(checks.values()) else "FAIL"
        details[vid] = {"label": VARIANTS[vid]["label"], "delta_pp": {k: round(v, 3) for k, v in d.items()}, "checks": checks}

    result = {"judge_version": JUDGE_VERSION, "smoke": a.smoke, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "verdicts": verdicts, "details": details,
              "metrics": json.loads(json.dumps(metrics, default=lambda x: None if isinstance(x, float) and math.isnan(x) else str(x)))}
    (out / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")

    lines = [f"# 세금 R&D v1 ({JUDGE_VERSION}){' — 스모크(가짜 데이터)' if a.smoke else ''}", "",
             "세후·청산 후 원화 연수익(초기 3,000만 원, 카카오페이증권 가정). V0 대비 차이는 %p/년.", "",
             "| 변형 | 판정 | 전체 | 앞 절반 | 뒤 절반 | 1억 | 선입선출(참고) | 매번 환전(참고) | 3억(참고) |", "|---|---|---|---|---|---|---|---|---|"]
    lines.append("| V0 현 코어 | 기준 | " + " | ".join(f"{base[k]['cagr_liq'] * 100:.2f}%" for k in setups) + " |")
    for vid, dd in details.items():
        lines.append(f"| {vid} {dd['label']} | {verdicts[vid]} | " + " | ".join(f"{dd['delta_pp'][k]:+.2f}" for k in setups) + " |")
    lines += ["", "세후 원화 최대낙폭(전체): " + ", ".join(f"{vid} {metrics[vid]['full']['mdd_after'] * 100:.1f}%" for vid in VARIANTS),
              "", "양도세 합계(전체, 백만 원): " + ", ".join(f"{vid} {metrics[vid]['full']['totals']['capital_gains_tax_krw'] / 1e6:.1f}" for vid in VARIANTS),
              "", "판정 기준: 전체 개선 ≥ +0.15%p, 두 절반 모두 > 0, 1억 계좌 > 0, 최대낙폭 3%p 넘게 나빠지지 않음. "
              "PASS 도 사람 검토 대기이며 엔진에 자동 반영되지 않는다. V4·V5 는 과거에 본 설정(sprint-2w F2)이라 앞으로 검증이 먼저다.",
              "", "한계: 새틀라이트 15% 미포함, 일봉 종가 체결, 연말 팔았다 다시 사기는 같은 종가 근사, 금융소득 종합과세 미반영."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(verdicts, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
