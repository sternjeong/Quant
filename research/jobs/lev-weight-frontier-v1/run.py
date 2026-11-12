"""검증 연구 lev-weight-frontier-v1 (2026-11-12 사전 등록): 끝없는 적립에서 2배 다리 비중의 프런티어 곡선 — 얼마까지 넣어도 되나.

frontier-lev-rebal-v1 은 비중 20% 하나에서 '12월 공제 한도 안 되돌림(A4_ALLOW)' 이 두 시대 모두 시장을 이긴다고 봤다. 사용자가 고를 수
있게 하려면 비중을 바꿨을 때 세후 수익과 계좌 낙폭이 어떻게 움직이는지(프런티어)가 필요하다. 같은 계좌·같은 가상 역사 설계
(frontier-lev-rebal-v1 의 simulate·부트스트랩을 그대로 불러 쓴다)에서 비중만 바꾼다.

  계좌: 처음 1,000만 원 + 매달 15만 원, 30년, 매수·매도 0.15%, 이동평균 원가, 양도세 22% × (그해 실현이익 − 250만 원) 판 즉시.
  다리: 필터 없는 고정 2배(차입 가산 연 1% + 보수 연 0.9%). 정책: A4_ALLOW(적립금은 모자란 쪽부터, 매년 12월 공제 한도 안에서만 다리를 판다).
  비중: 10·15·20·25·30·40%. 기준: 같은 돈을 시장에 그냥.
  가상 역사: 시대마다 원형 블록 부트스트랩 2,000개(블록 63거래일) — selection(1927~1966 일자)·confirmation(1967~2007 일자). 2008+ 는 보고만.

판정(비중마다) WEIGHT_OK ⇔ 두 시대 모두 ① 시장보다 많이 남은 경로 ≥ 60% ② 세후 IRR 차이 중앙값 ≥ +0.3%p ③ 10분위 ≥ −1.5%p
④ 계좌 최대낙폭 중앙값이 시장보다 10%p 넘게 나쁘지 않음 — frontier-lev-rebal-v1 과 같은 문턱.
MAX_OK_WEIGHT = 10% 부터 차례로 올라가며 끊기지 않고 WEIGHT_OK 인 가장 큰 비중(없으면 NONE).
비중이 늘수록 수익·낙폭이 어떻게 바뀌는지(추가 낙폭 1%p 당 IRR)는 서술로만 보고한다. 비중 6개는 결과를 보기 전에 고정했다(격자 탐색 아님).
엔진은 바뀌지 않는다. 전진 원장 v4 는 20% 만 기록한다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


FL = _load("frontier_lev_rebal_v1", HERE.parent / "frontier-lev-rebal-v1" / "run.py")
L = FL.L

JOB_ID = "lev-weight-frontier-v1"
RULES_VERSION = "lev-weight-frontier-v1/2026-11-12"
WEIGHTS = (0.10, 0.15, 0.20, 0.25, 0.30, 0.40)
POLICY = "A4_ALLOW"
WIN_MIN, MED_MIN, P10_MIN, MDD_GAP_MAX = 0.60, 0.003, -0.015, 0.10
N_PATHS, SEED = 2000, 20261113
JUDGED_ERAS = ("selection", "confirmation")


def sim_weight(fm, fl, cal, w: float) -> dict:
    """frontier-lev-rebal-v1.simulate 는 모듈 상수 TARGET_W 를 읽는다 — 비중마다 바꿔 부르고 되돌린다."""
    old = FL.TARGET_W
    try:
        FL.TARGET_W = w
        return FL.simulate(fm, fl, POLICY, cal)
    finally:
        FL.TARGET_W = old


def summarize(r: dict, mkt: dict) -> dict:
    rows = FL.compare(r, mkt)
    k = L.kpi_pairs_verdict(rows, WIN_MIN, MED_MIN, P10_MIN)
    gap = float(np.median(r["mdd"])) - float(np.median(mkt["mdd"]))
    k["checks"]["mdd_within"] = bool(gap >= -MDD_GAP_MAX)
    k["pass"] = bool(all(k["checks"].values()))
    k.update({"median_irr": float(np.nanmedian(r["irr"])), "median_mdd": float(np.median(r["mdd"])), "mdd_gap": gap,
              "p10_mdd": float(np.percentile(r["mdd"], 10)), "median_w_end": float(np.median(r["w_end"])),
              "median_exposure": float(np.median(r["exposure"])), "median_tax_krw": float(np.median(r["tax"])),
              "median_terminal_krw": float(np.median(r["terminal"]))})
    return k


def body(R):
    smoke = R.smoke
    months = 60 if smoke else FL.HORIZON_MONTHS
    n_paths = 60 if smoke else N_PATHS
    block = 21 if smoke else FL.BLOCK_DAYS
    data = R.stage("data", lambda: L.load_long_synthetic() if smoke else L.load_long_real())
    cal = np.arange(months) % 12
    eras: dict[str, Any] = {}
    for i, (name, (lo, hi)) in enumerate([*FL.ERAS.items(), *FL.REPORT_ERAS.items()]):
        def do(lo=lo, hi=hi, i=i):
            mkt, rf = FL.era_arrays(data, lo, hi)
            if len(mkt) < block * 4:
                return {"skipped": True, "n_days": int(len(mkt))}
            fm, fl = FL.bootstrap_monthly(mkt, rf, months, n_paths, SEED + 97 * (i + 1), block)
            base = FL.simulate(fm, fl, "MKT", cal)
            out = {"MKT": {"median_irr": float(np.nanmedian(base["irr"])), "median_mdd": float(np.median(base["mdd"])),
                           "p10_mdd": float(np.percentile(base["mdd"], 10)), "median_tax_krw": float(np.median(base["tax"]))},
                   "n_days": int(len(mkt)), "n_paths": int(n_paths), "months": int(months)}
            for w in WEIGHTS:
                R.check_time()
                out[f"w{int(round(w * 100))}"] = summarize(sim_weight(fm, fl, cal, w), base)
            return out
        eras[name] = R.stage(f"era_{name}", do)
    verdicts: dict[str, str] = {}
    max_ok = "NONE"
    chain = True
    for w in WEIGHTS:
        key = f"w{int(round(w * 100))}"
        ok = all(eras[e].get(key, {}).get("pass") is True for e in JUDGED_ERAS)
        verdicts[key] = "WEIGHT_OK" if ok else "FAIL"
        chain = chain and ok
        if chain:
            max_ok = key
    verdicts["max_ok_weight"] = max_ok
    if smoke:
        verdicts = {k: f"SMOKE_ONLY({v})" for k, v in verdicts.items()}
        e = eras["selection"]
        assert all(f"w{int(round(w * 100))}" in e for w in WEIGHTS), "비중 칸 없음"
        assert e["w40"]["median_exposure"] > e["w10"]["median_exposure"], "비중이 노출에 반영되지 않음"
    assert FL.TARGET_W == 0.20, "공유 모듈 상수가 되돌려지지 않음"
    result = L.rnd({"id": JOB_ID, "judge_version": RULES_VERSION, "smoke": smoke, "source": data.get("source"), "verdicts": verdicts,
                    "eras": eras, "rule": {"weights": WEIGHTS, "policy": POLICY, "lump_krw": FL.LUMP_KRW, "monthly_krw": FL.MONTHLY_KRW,
                                           "months": months, "n_paths": n_paths, "block_days": block,
                                           "thresholds": {"win_min": WIN_MIN, "median_irr_min": MED_MIN, "p10_irr_min": P10_MIN,
                                                          "mdd_gap_max": MDD_GAP_MAX}}})
    return result, render(result)


def render(r: dict) -> str:
    v, P = r["verdicts"], L.pct
    out = [f"# 끝없는 적립 — 2배 다리 비중 프런티어 v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
           "처음 1,000만 원 + 매달 15만 원을 30년 동안 넣고, 2배 다리 비중만 바꿔(12월 공제 한도 안 되돌림) 세후 수익과 계좌 낙폭이 어떻게 움직이는지 본다.", "",
           f"**가장 큰 통과 비중: {v['max_ok_weight']}** — " + " · ".join(f"{k} {val}" for k, val in v.items() if k != "max_ok_weight"), "",
           "통과는 엔진 반영이 아니다. 엔진은 바뀌지 않았다.", "", "## 규칙 (결과를 보기 전에 고정)", "",
           "- 정책 A4_ALLOW: 적립금은 목표보다 모자란 쪽부터, 매년 12월 그해 남은 공제(250만 원) 안에서만 다리를 팔아 시장을 산다(추가 세금 0).",
           f"- 비중마다 WEIGHT_OK ⇔ 두 시대 모두 이긴 경로 ≥ {WIN_MIN:.0%}, 세후 IRR 차이 중앙값 ≥ +{MED_MIN * 100:.1f}%p, 10분위 ≥ {P10_MIN * 100:.1f}%p, "
           f"계좌 낙폭 중앙값이 시장보다 {MDD_GAP_MAX * 100:.0f}%p 넘게 나쁘지 않음.",
           "- 가장 큰 통과 비중 = 10% 부터 끊기지 않고 통과한 가장 큰 비중.", ""]
    for name, e in r["eras"].items():
        if e.get("skipped"):
            continue
        m = e["MKT"]
        out += [f"## {name}{' (보고만)' if name not in JUDGED_ERAS else ''} — 가상 역사 {e['n_paths']}개, {e['months']}달", "",
                f"시장 그냥: 세후 IRR 중앙 {P(m['median_irr'], nd=2)} · 계좌 낙폭 중앙 {P(m['median_mdd'])} (나쁜 10% {P(m['p10_mdd'])})", "",
                "| 비중 | 이긴 비율 | IRR 차이 중앙 / 10분위 | 세후 IRR 중앙 | 계좌 낙폭 중앙 (나쁜 10%) | 낙폭 차이 | 말기 다리 비중 | 평균 노출 | 낸 세금 중앙 | 통과 |",
                "|---|---|---|---|---|---|---|---|---|---|"]
        for w in r["rule"]["weights"]:
            k = e.get(f"w{int(round(w * 100))}", {})
            if not k.get("n"):
                continue
            out.append(f"| {w:.0%} | {P(k['share_win'], nd=0)} | {P(k['median_diff_irr'], True, 2)}p / {P(k['p10_diff_irr'], True, 2)}p | "
                       f"{P(k['median_irr'], nd=2)} | {P(k['median_mdd'])} ({P(k['p10_mdd'])}) | {P(k['mdd_gap'], True)} | {P(k['median_w_end'])} | "
                       f"{k['median_exposure']:.2f} | {k['median_tax_krw'] / 1e4:,.0f}만 원 | {'예' if k.get('pass') else '아니오'} |")
        out.append("")
    out += ["## 주의", "",
            "- 합성 2배 다리는 식이다(실제 SSO 는 2006 년부터). 가상 역사는 과거 일별 수익을 63일 덩어리로 섞은 것이라 30년 동안의 큰 체제 변화는 담지 못한다.",
            "- 비중을 올리면 늘어나는 수익은 대부분 위험을 더 진 대가다(engine-candidate-v1: 추가 베타 1 당 연 7% 남짓). 낙폭 열을 반드시 함께 볼 것.",
            "- 환율 1,300 원 고정 근사, 배당 원천징수 미반영. 투자 조언이 아니다."]
    if r["smoke"]:
        out += ["", "스모크 실행: 가짜 데이터·짧은 구간이라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    R = L.Runner(RULES_VERSION, argv)
    return R.run(body)


if __name__ == "__main__":
    raise SystemExit(main())
