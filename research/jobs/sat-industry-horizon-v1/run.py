"""검증 연구 sat-industry-horizon-v1 (2026-11-15 사전 등록): 주도 세부 산업 1~3개에 집중한 새틀라이트가 기간별로 시장을 7%p 넘게 이기나.

사용자 목표(2026-11-15): 새틀라이트를 시장을 이기는 alpha 로. 수익 극대화, 도박은 아님. S&P 500 대비 +7%p 이상을 정해진 기간 안에.
기간 n 개를 정해 기간마다 맞는 선정 방법을 연구.

왜 산업인가(앞선 증거):
  - 시점 기준 S&P 500 종목 고르기(sat-horizon-v1·v2)는 어떤 기간에서도 +7%p 를 시대와 무관하게 넘기지 못했다.
    무료 가격의 생존편향 때문에 깨끗한 확인도 어렵다.
  - Ken French 산업 포트폴리오는 CRSP 전 종목(상장폐지 포함)이라 생존편향이 없고 1926 년부터 있다.
    sector-concentrate-v1 의 '보고만' 표에서 49 산업 12개월 상대강도 상위 1·2 는 1927~2007 연 20%(시장 9.9%)였다.
    그 연구는 월 1회 교체·연수익만 봤다. 49 산업의 2008 년 이후와 보유 기간별 초과수익은 아직 아무도 보지 않았다.
  - 새틀라이트의 뜻: 코어(시장)는 그대로 두고, 작은 몫을 지금 가장 강한 영역에 집중해 초과수익을 노린다.
    한 산업도 그 안은 시가총액 가중 수십~수백 종목이라 개별 종목 한 개에 거는 도박과 다르다.

설계(결과를 보기 전에 고정):
  - 자료: Ken French 49 산업(일별, 시가총액 가중), 시장 = Mkt-RF + RF. 평일 달력. 결측 산업은 그날 후보에서 뺀다.
  - 기간: 1·3·6·12개월(21·63·126·252거래일).
  - 후보 칸 9개 = 신호 3 × 상위 k 3. 매달 첫 거래일 d 에 d 전 거래일까지의 수익으로 고른다.
    - 신호: RS12(12개월 수익 − 시장 12개월 수익), M6(6개월 수익), C(두 신호 순위 평균)
    - k: 1·2·3
    - 직전 252거래일 중 230일 이상 수익이 있는 산업만 쓴다.
    - d 종가에 같은 비중으로 사서 H 거래일 뒤 판다.
    - E = 고른 산업 평균 수익 − 시장 수익 − 왕복 비용 20bp.
  - 무작위 기준선: 같은 날 같은 후보에서 무작위 k 산업(500회).
  - 고르기: 선택 구간(형성 1927-07 ~ 1966-12)에서 E 중앙값 > 0 인 칸 중 평균 E 최대.
  - 확인 A: 형성 1967-01 ~, 끝 ≤ 2007-12-31. 확인 B(49 산업으로는 아무도 보지 않은 구간): 형성 2008-01 ~, 끝 ≤ 2024-09-30.
  - TARGET_MET ⇔ A·B 각각 아래를 모두 만족한다.
    - (a) 평균 E ≥ +7%p
    - (b) P(E ≥ 7%p) − 무작위 P 평균 > 0, 이동 블록 부트스트랩(블록 max(12, H개월)달, 2,000회) 단측 p < 0.0125(0.05/4 기간)
    - (c) E 중앙값 > 0, E > 0 인 달 비율 ≥ 50%
  - 그 밖:
    - SKILL_BELOW_TARGET: A·B 모두 (b)(c)는 만족, (a)는 미달
    - FAIL / FAIL_UNDERPOWERED
    - NOT_EVALUABLE: 형성 달이 확인 구간마다 24 미만
  2024-10 이후, 세금(한국 22%) 근사, 산업 이름은 보고만. 통과해도 엔진은 바뀌지 않는다(사용자 확인 뒤 별도 작업).
한계: 산업 포트폴리오를 그대로 사는 상품은 없다(가까운 산업 ETF·대표 종목으로 근사해야 함). 세금·환전 미반영(보고만 근사).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

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


LAB = _load("core_longrun_lab", HERE.parent / "core-longrun-v1" / "lab.py")      # Ken French 일별 자료 읽기·평일 달력
L = _load("lab", HERE.parent / "dca-dip-deploy-v1" / "lab.py")                     # Runner·rnd·pct
from core import research_power as rp  # noqa: E402

JOB_ID = "sat-industry-horizon-v1"
RULES_VERSION = "sat-industry-horizon-v1/2026-11-15"
SEED = 20261117
HORIZONS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252}
SIGNALS = ("RS12", "M6", "C")
KS = (1, 2, 3)
CELLS = tuple(f"{s}_k{k}" for s in SIGNALS for k in KS)
W_RS, W_M6, MIN_OBS = 252, 126, 230
COST_RT = 0.002
TARGET = 0.07
SELECT = ("1927-07-01", "1966-12-31")
CONFIRM_A = ("1967-01-01", "2007-12-31")
CONFIRM_B = ("2008-01-01", "2024-09-30")
N_RANDOM = 500
BOOT = 2000
ALPHA = 0.05 / len(HORIZONS)
HIT0_MIN = 0.5
MIN_MONTHS = 24


# =================================================================================================
# 1. 표 만들기
# =================================================================================================

def build_tables(ind: pd.DataFrame, mkt: pd.Series, check=lambda: None) -> dict[str, pd.DataFrame]:
    """{H: DataFrame(index=형성일, 열: end, <칸>(E), rand_hit7_k{k}, rand_mean_k{k}, n_valid, picks_<칸>)}."""
    idx = ind.index
    obs = ind.notna().to_numpy()
    lr = np.log1p(ind.fillna(0.0)).to_numpy()
    cum = np.vstack([np.zeros(lr.shape[1]), np.cumsum(lr, axis=0)])         # cum[i] = 행 0..i−1 합
    mlr = np.log1p(mkt.reindex(idx).fillna(0.0)).to_numpy()
    mcum = np.concatenate([[0.0], np.cumsum(mlr)])
    ocum = np.vstack([np.zeros(obs.shape[1]), np.cumsum(obs, axis=0)])
    names = list(ind.columns)
    rng = np.random.default_rng(SEED)
    d_rows = np.flatnonzero(LAB.month_first_mask(idx))
    d_rows = d_rows[d_rows > W_RS]
    out = {h: [] for h in HORIZONS}
    for d in d_rows:
        check()
        e = d                                               # 행 d−1 까지 포함 = cum[d]
        valid = (ocum[e] - ocum[e - W_RS] >= MIN_OBS) & obs[d]
        if valid.sum() < 2 * max(KS):
            continue
        r12 = np.expm1(cum[e] - cum[e - W_RS])
        m12 = np.expm1(mcum[e] - mcum[e - W_RS])
        rs12 = np.where(valid, r12 - m12, np.nan)
        m6 = np.where(valid, np.expm1(cum[e] - cum[e - W_M6]), np.nan)
        rk = lambda a: pd.Series(a).rank(pct=True).to_numpy()  # noqa: E731
        sc = {"RS12": rs12, "M6": m6, "C": np.where(valid, (rk(rs12) + rk(m6)) / 2, np.nan)}
        cand = np.flatnonzero(valid)
        for name, h in HORIZONS.items():
            if d + 1 + h > len(idx):
                continue
            fwd = np.expm1(cum[d + 1 + h] - cum[d + 1])          # 행 d+1..d+h 수익(d 종가 매수, d+h 종가 매도)
            mk = float(np.expm1(mcum[d + 1 + h] - mcum[d + 1]))
            ex = fwd - mk - COST_RT
            row: dict[str, Any] = {"date": idx[d], "end": idx[d + h], "n_valid": int(valid.sum()), "mkt": mk}
            for s in SIGNALS:
                order = cand[np.argsort(-sc[s][cand], kind="stable")]
                for k in KS:
                    pick = order[:k]
                    row[f"{s}_k{k}"] = float(ex[pick].mean())
                    row[f"picks_{s}_k{k}"] = ",".join(names[j] for j in pick)
            exc = ex[cand]
            for k in KS:
                sel = np.argpartition(rng.random((N_RANDOM, len(cand))), k, axis=1)[:, :k]
                draws = exc[sel].mean(axis=1)
                row[f"rand_hit7_k{k}"], row[f"rand_mean_k{k}"] = float(np.mean(draws >= TARGET)), float(np.mean(draws))
            out[name].append(row)
    return {h: pd.DataFrame(v).set_index("date") if v else pd.DataFrame() for h, v in out.items()}


# =================================================================================================
# 2. 판정
# =================================================================================================

def block_boot_p(d: np.ndarray, block: int, seed: int, n: int = BOOT) -> float:
    d = d[np.isfinite(d)]
    if len(d) < max(2 * block, 12):
        return float("nan")
    rng = np.random.default_rng(seed)
    obs = d.mean()
    c = d - obs
    nb = int(np.ceil(len(d) / block))
    sims = np.empty(n)
    for i in range(n):
        st = rng.integers(0, len(d) - block + 1, nb)
        sims[i] = np.concatenate([c[s:s + block] for s in st])[:len(d)].mean()
    return float((np.sum(sims >= obs) + 1) / (n + 1))


def window(t: pd.DataFrame, a: str, b: str) -> pd.DataFrame:
    return t[(t.index >= a) & (t["end"] <= b)]


def summarize(t: pd.DataFrame, cell: str) -> dict[str, Any]:
    e = t[cell].dropna()
    if e.empty:
        return {"n": 0}
    k = cell[-1]
    return {"n": int(len(e)), "mean": float(e.mean()), "median": float(e.median()), "hit7": float((e >= TARGET).mean()),
            "hit0": float((e > 0).mean()), "p10": float(e.quantile(0.1)), "p90": float(e.quantile(0.9)),
            "rand_hit7": float(t.loc[e.index, f"rand_hit7_k{k}"].mean()), "rand_mean": float(t.loc[e.index, f"rand_mean_k{k}"].mean())}


def confirm_checks(w: pd.DataFrame, cell: str, h: int, seed: int) -> dict[str, Any]:
    s = summarize(w, cell)
    if s.get("n", 0) < MIN_MONTHS:
        return {"evaluable": False, "stats": s}
    k = cell[-1]
    d = ((w[cell] >= TARGET).astype(float) - w[f"rand_hit7_k{k}"]).to_numpy()
    p = block_boot_p(d, max(12, h // 21), seed)
    active = (w[cell] - w[f"rand_mean_k{k}"]).to_numpy()
    ir = float(np.mean(active) / np.std(active) * np.sqrt(252 / h)) if np.std(active) > 0 else None
    return {"evaluable": True, "stats": s, "p_one_sided": p, "hit7_minus_random": float(np.mean(d)), "observed_ir_vs_random": ir,
            "a": s["mean"] >= TARGET, "b": bool(np.isfinite(p) and np.mean(d) > 0 and p < ALPHA),
            "c": s["median"] > 0 and s["hit0"] >= HIT0_MIN, "noop": rp.noop_guard(active.tolist())}


def judge_horizon(name: str, t: pd.DataFrame, power: dict) -> dict[str, Any]:
    h = HORIZONS[name]
    parts = {"select": window(t, *SELECT), "confirm_A": window(t, *CONFIRM_A), "confirm_B": window(t, *CONFIRM_B),
             "post": t[t["end"] > CONFIRM_B[1]]}
    table = {p: {c: summarize(df, c) for c in CELLS} for p, df in parts.items() if not df.empty}
    sel = table.get("select", {})
    eligible = [c for c in CELLS if sel.get(c, {}).get("n") and sel[c]["median"] > 0]
    out: dict[str, Any] = {"horizon_days": h, "table": table, "eligible_in_selection": eligible}
    if not eligible:
        out["verdict"] = "NO_ELIGIBLE_CELL"
        return out
    chosen = max(eligible, key=lambda c: (sel[c]["mean"], -CELLS.index(c)))
    out["chosen"] = chosen
    ca = confirm_checks(parts["confirm_A"], chosen, h, SEED + h)
    cb = confirm_checks(parts["confirm_B"], chosen, h, SEED + 7 * h)
    out["confirm_A"], out["confirm_B"] = ca, cb
    if not (ca["evaluable"] and cb["evaluable"]):
        out["verdict"] = "NOT_EVALUABLE"
        return out
    if ca["noop"] or cb["noop"]:
        out["verdict"], out["reason"] = "NOT_EVALUABLE", ca["noop"] or cb["noop"]
        return out
    if all(x[g] for x in (ca, cb) for g in ("a", "b", "c")):
        verdict = "TARGET_MET"
    elif all(x[g] for x in (ca, cb) for g in ("b", "c")):
        verdict = "SKILL_BELOW_TARGET"
    else:
        irs = [x["observed_ir_vs_random"] for x in (ca, cb) if x["observed_ir_vs_random"] is not None]
        verdict = rp.classify_fail(min(irs) if irs else None, power)
    out["verdict"] = verdict
    out["latest_picks"] = {"date": str(t.index[-1].date()), "industries": t[f"picks_{chosen}"].iloc[-1]}
    return out


# =================================================================================================
# 3. 본문
# =================================================================================================

def body(R):
    data = R.stage("french", lambda: LAB.synthetic_data() if R.smoke else LAB.load_real())
    ind = data["ind49"]
    if ind is None or ind.empty:
        raise RuntimeError("49 산업 자료가 없음")
    tables = R.stage("tables", lambda: build_tables(ind, data["mkt"], R.check_time))
    years = sum((pd.Timestamp(b) - pd.Timestamp(a)).days for a, b in (CONFIRM_A, CONFIRM_B)) / 365.25
    power = rp.power_report(years, len(HORIZONS))
    res = {h: judge_horizon(h, tables[h], power) if not tables[h].empty else {"verdict": "NOT_EVALUABLE", "table": {}} for h in HORIZONS}
    verdicts = {h: res[h]["verdict"] + (f"({res[h]['chosen']})" if res[h].get("chosen") else "") for h in HORIZONS}
    if R.smoke:
        verdicts = {k: f"SMOKE_ONLY({v})" for k, v in verdicts.items()}
    result = L.rnd({"id": JOB_ID, "judge_version": RULES_VERSION, "smoke": R.smoke, "source": data.get("source", ""), "verdicts": verdicts,
                    "power": power, "power_line": rp.power_line(power), "horizons": res,
                    "coverage": {"industries": int(ind.shape[1]), "first": str(ind.index[0].date()), "last": str(ind.index[-1].date()),
                                 "months": {h: int(len(t)) for h, t in tables.items()}},
                    "rule": {"cells": list(CELLS), "target": TARGET, "cost_round_trip": COST_RT, "select": SELECT, "confirm_A": CONFIRM_A,
                             "confirm_B": CONFIRM_B, "alpha": ALPHA, "n_random": N_RANDOM, "boot": BOOT, "seed": SEED}})
    return result, render(result)


NOTE = {"RS12": "12개월 상대강도(산업 − 시장)", "M6": "6개월 수익", "C": "두 신호 순위 평균"}


def render(r: dict) -> str:
    P = L.pct
    v = r["verdicts"]
    out = [f"# 주도 세부 산업 1~3개 집중 새틀라이트 — 기간별로 시장을 7%p 넘게 이기나 ({r['judge_version']})" + (" — 스모크(가짜 데이터)" if r["smoke"] else ""), "",
           "**판정:** " + " · ".join(f"{h} **{v[h]}**" for h in HORIZONS), "",
           "통과는 '전진 원장 후보'일 뿐 엔진 채택이 아니다. 엔진은 바뀌지 않았다.", "", "## 규칙 (결과를 보기 전에 고정)", "",
           f"- 자료: {r['source']} · 49 산업 {r['coverage']['industries']}개 · {r['coverage']['first']} ~ {r['coverage']['last']}",
           "- 칸 = 신호(" + ", ".join(f"{k} {n}" for k, n in NOTE.items()) + ") × 상위 1·2·3. 매달 첫 거래일, 같은 비중, 기간 끝 매도, 왕복 20bp.",
           f"- 고르기: 선택 구간 {r['rule']['select'][0]}~{r['rule']['select'][1]} 에서 E 중앙값 > 0 인 칸 중 평균 E 최대.",
           f"- TARGET_MET = 확인 A({r['rule']['confirm_A'][0]}~{r['rule']['confirm_A'][1]})·B({r['rule']['confirm_B'][0]}~{r['rule']['confirm_B'][1]}, 49 산업으로는 처음 보는 구간) 모두 "
           f"(a) 평균 E ≥ +7%p (b) P(E≥7%p) 가 무작위 산업보다 높음, 블록 부트스트랩 p < {r['rule']['alpha']:.4f} (c) E 중앙값 > 0·E>0 비율 ≥ 50%. (b)(c)만이면 SKILL_BELOW_TARGET.",
           f"- {r['power_line']}", ""]
    for h, x in r["horizons"].items():
        out += [f"## {h} — {x['verdict']}" + (f" · 고른 칸 {x['chosen']}" if x.get("chosen") else ""), ""]
        for key, label in (("confirm_A", "확인 A"), ("confirm_B", "확인 B")):
            c = x.get(key)
            if c and c.get("evaluable"):
                out.append(f"- {label}: 평균 E {P(c['stats']['mean'], True, 1)} · 중앙 {P(c['stats']['median'], True, 1)} · P(≥7%p) {P(c['stats']['hit7'], nd=0)} "
                           f"(무작위 {P(c['stats']['rand_hit7'], nd=0)}, p={c['p_one_sided']}) · E>0 {P(c['stats']['hit0'], nd=0)} · 관문 a/b/c "
                           f"{'✓' if c['a'] else '✗'}/{'✓' if c['b'] else '✗'}/{'✓' if c['c'] else '✗'}")
        if x.get("latest_picks"):
            out.append(f"- 최근 고른 산업({x['latest_picks']['date']}): {x['latest_picks']['industries']}")
        for part, label in (("select", "선택 구간"), ("confirm_A", "확인 A"), ("confirm_B", "확인 B"), ("post", "2024-10 이후(보고)")):
            tb = x.get("table", {}).get(part)
            if not tb:
                continue
            out += ["", f"**{label}**", "", "| 칸 | 달 | 평균 E | 중앙 E | P(E≥7%p) | 무작위 P | E>0 | 하위 10% | 상위 10% |", "|---|---|---|---|---|---|---|---|---|"]
            for c in CELLS:
                s = tb.get(c) or {}
                if s.get("n"):
                    out.append(f"| {c}{' ★' if c == x.get('chosen') else ''} | {s['n']} | {P(s['mean'], True, 1)} | {P(s['median'], True, 1)} | {P(s['hit7'], nd=0)} | "
                               f"{P(s['rand_hit7'], nd=0)} | {P(s['hit0'], nd=0)} | {P(s['p10'], True, 1)} | {P(s['p90'], True, 1)} |")
        out.append("")
    out += ["## 주의", "",
            "- Ken French 산업 포트폴리오는 CRSP 전 종목(상장폐지 포함) 시가총액 가중이라 생존편향이 없다. 하지만 그대로 사는 상품은 없어 산업 ETF·대표 종목으로 근사해야 한다.",
            "- 세금(한국 양도세 22%)·환전 미반영. 기간이 짧을수록 교체가 잦아 세후 차이가 커진다.",
            "- 기간이 겹치는 달들은 독립이 아니다(블록 부트스트랩으로 반영). 투자 조언이 아니다."]
    if r["smoke"]:
        out += ["", "스모크 실행: 가짜 데이터라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    return L.Runner(RULES_VERSION, argv).run(body)


if __name__ == "__main__":
    raise SystemExit(main())
