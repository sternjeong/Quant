"""검증 연구 edge-decay-v1 (2026-10-23 사전 등록): '어디에 넣나' 규칙의 초과수익은 사라지는 중인가, 아직 살아 있나.

1927~2007 에서 통과한 규칙들이 2008 년 이후와 ETF 시대에는 약해 보인다. 그 약함이 우연인지(표본 부족), 구조적 쇠퇴인지 가른다.
방법: 매달 첫 거래일에 규칙이 고른 곳(전날 종가까지의 자료)을 산다고 보고, 그 뒤 12개월(252거래일, 다음 날 종가 매수) 수익 − 같은 기간 시장 수익을
'월별 초과수익'으로 만든다(팔지 않는 적립 한 번의 선택이 낳는 초과). 규칙: EW12, DD12(1년 고점 대비 가장 많이 빠진 산업), MA200(200일선 대비 가장 아래),
REV36(3년 수익 가장 낮은 산업), MOM12(12-1개월 수익 가장 높은 산업), BV(대형 가치주), L15F(0.15 × (필터 달린 합성 2배 다리 − 시장)).
판정(규칙마다, 2008-01-01 이후 시작하는 선택 = '최근'):
  ALIVE   ⇔ ① 최근 평균 초과 > 0, 이동 블록 부트스트랩(24개월 블록, 2,000회) 단측 p < 0.10 ② 1927~ 전체에서 초과수익을 시간(연)에 회귀한 기울기의
            Newey-West(24 지연) t 값 > −1.645 (유의한 쇠퇴 없음).
  DECAYED ⇔ 1927~2007 평균 초과가 양이고(단측 p < 0.10) 최근 평균 초과가 양이 아니거나 ①을 못 넘고, 기울기 t ≤ −1.645.
  INCONCLUSIVE ⇔ 그 밖.
보고: 15년 이동 평균 초과(연도별), 2008 전·후 평균 차이와 부트스트랩 p. 엔진은 바뀌지 않는다.
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

V1 = L._load_mod("_dca_asset_pick_v1", "research/jobs/dca-asset-pick-v1/run.py")
from core import french_factors as ff  # noqa: E402

JOB_ID = "edge-decay-v1"
RULES_VERSION = "edge-decay-v1/2026-10-23"
ARMS = ("EW12", "DD12", "MA200", "REV36", "MOM12", "BV", "L15F")
LABELS = {"EW12": "12 산업 똑같이", "DD12": "1년 고점 대비 가장 많이 빠진 산업", "MA200": "200일선 대비 가장 아래 산업",
          "REV36": "3년 수익 가장 낮은 산업", "MOM12": "12-1개월 수익 가장 높은 산업", "BV": "대형 가치주",
          "L15F": "필터 달린 합성 2배 다리 15% (시장 대비)"}
FWD = 252
RECENT_START = pd.Timestamp("2008-01-01")
BOOT = 2000
BLOCK_M = 24
NW_LAGS = 24
ALPHA = 0.10
T_DECAY = -1.645
ROLL_YEARS = 15
SEED = 20261023


def monthly_excess(data: dict) -> pd.DataFrame:
    days = data["mkt"].dropna().index
    mkt = data["mkt"].reindex(days)
    rf = data["rf"].reindex(days).fillna(0.0)
    ind_px = data["ind12"].reindex(days).apply(L.level)
    mkt_px = L.level(mkt)
    bv_px = L.level(data["bv"].reindex(days))
    leg_px = L.level(L.leg_returns(mkt, rf))
    scores = V1.score_tables(ind_px)
    mom = scores["MOM12"]
    rows = np.flatnonzero(L.lab.month_first_mask(days))
    px_m, px_i, px_b, px_l = mkt_px.to_numpy(), ind_px.to_numpy(), bv_px.to_numpy(), leg_px.to_numpy()
    out = []
    for r in rows:
        b, e = r + 1, r + 1 + FWD            # 다음 날 종가에 사서 252 거래일 뒤
        if e >= len(days):
            break
        rm = px_m[e] / px_m[b] - 1.0
        ri = px_i[e] / px_i[b] - 1.0
        rec = {"date": days[r]}
        rec["EW12"] = float(np.nanmean(ri)) - rm
        for arm in ("DD12", "MA200", "REV36"):
            j = V1.pick(scores[arm][r])
            rec[arm] = (ri[j] - rm) if j >= 0 and np.isfinite(ri[j]) else np.nan
        j = V1.pick(mom[r])
        rec["MOM12"] = (ri[j] - rm) if j >= 0 and np.isfinite(ri[j]) else np.nan
        rb = px_b[e] / px_b[b] - 1.0 if np.isfinite(px_b[b]) and np.isfinite(px_b[e]) else np.nan
        rec["BV"] = rb - rm
        rl = px_l[e] / px_l[b] - 1.0 if np.isfinite(px_l[b]) and np.isfinite(px_l[e]) else np.nan
        rec["L15F"] = 0.15 * (rl - rm)
        out.append(rec)
    return pd.DataFrame(out).set_index("date")


def mb_pvalue(x: np.ndarray, block: int, n_boot: int, rng) -> tuple[float, float]:
    """평균 > 0 단측 p: 중심화한 표본의 이동 블록 부트스트랩 평균이 관측 평균 이상인 비율."""
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2 * block:
        return float("nan"), float("nan")
    obs = float(x.mean())
    xc = x - obs
    nb = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, (n_boot, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n_boot, -1)[:, :n]
    means = xc[idx].mean(axis=1)
    return obs, float(np.mean(means >= obs))


def analyse(ex: pd.DataFrame, smoke: bool) -> dict:
    rng = np.random.default_rng(SEED)
    boot = 100 if smoke else BOOT
    res = {}
    for arm in ARMS:
        s = ex[arm].dropna()
        pre, post = s[s.index < RECENT_START], s[s.index >= RECENT_START]
        m_pre, p_pre = mb_pvalue(pre.to_numpy(), BLOCK_M, boot, rng)
        m_post, p_post = mb_pvalue(post.to_numpy(), BLOCK_M, boot, rng)
        yrs = (s.index.year + (s.index.month - 1) / 12.0).to_numpy(dtype=float)
        fit = ff.ols_nw(s.to_numpy(dtype=float), (yrs - yrs.mean())[:, None], NW_LAGS)
        slope, t_slope = float(fit["coef"][1]), float(fit["t"][1])
        alive = bool(np.isfinite(m_post) and m_post > 0 and p_post < ALPHA and t_slope > T_DECAY)
        decayed = bool(np.isfinite(m_pre) and m_pre > 0 and p_pre < ALPHA and t_slope <= T_DECAY
                       and not (np.isfinite(m_post) and m_post > 0 and p_post < ALPHA))
        roll = s.rolling(ROLL_YEARS * 12, min_periods=ROLL_YEARS * 12).mean()
        yearly = {str(y): float(roll[roll.index.year == y].iloc[-1]) for y in sorted(set(roll.dropna().index.year))[::5]}
        diff_m, diff_p = float("nan"), float("nan")
        if len(pre) > 24 and len(post) > 24:
            diff_m = float(post.mean() - pre.mean())
            both = np.concatenate([pre.to_numpy(), post.to_numpy()])
            both = both - both.mean()                      # 귀무: 전·후 평균 같음
            cnt, k = 0, 100 if smoke else 1000
            for _ in range(k):
                st = rng.integers(0, len(both) - BLOCK_M + 1, int(np.ceil(len(both) / BLOCK_M)))
                bs = np.concatenate([both[a:a + BLOCK_M] for a in st])[:len(both)]
                if bs[len(pre):].mean() - bs[:len(pre)].mean() <= diff_m:
                    cnt += 1
            diff_p = cnt / k                                # 단측: 더 낮은 쪽(쇠퇴)
        res[arm] = {"n_months": int(len(s)), "n_pre": int(len(pre)), "n_post": int(len(post)),
                    "mean_pre": m_pre, "p_pre": p_pre, "mean_post": m_post, "p_post": p_post,
                    "slope_per_year": slope, "t_slope": t_slope, "post_minus_pre": diff_m, "p_post_lower": diff_p,
                    "rolling15y_every5y": yearly,
                    "verdict": "ALIVE" if alive else ("DECAYED" if decayed else "INCONCLUSIVE")}
    return res


def body(R):
    data = R.stage("inputs", lambda: L.load_long_synthetic() if R.smoke else L.load_long_real())
    ex = R.stage("excess", lambda: monthly_excess(data))
    res = R.stage("analysis", lambda: analyse(ex, R.smoke))
    verdicts = {a: (f"SMOKE_ONLY({res[a]['verdict']})" if R.smoke else res[a]["verdict"]) for a in ARMS}
    verdicts["alive"] = f"{sum(res[a]['verdict'] == 'ALIVE' for a in ARMS)}/{len(ARMS)}"
    result = L.rnd({"judge_version": RULES_VERSION, "smoke": R.smoke, "source": data.get("source"), "verdicts": verdicts, "arms": res,
                    "rule": {"fwd_rows": FWD, "recent_start": str(RECENT_START.date()), "boot": BOOT, "block_months": BLOCK_M,
                             "nw_lags": NW_LAGS, "alpha": ALPHA, "t_decay": T_DECAY, "labels": LABELS},
                    "excess_months": int(len(ex)), "excess_first": str(ex.index[0].date()), "excess_last": str(ex.index[-1].date())})
    if R.smoke:
        assert all(res[a]["n_pre"] > 24 and res[a]["n_post"] > 24 for a in ARMS), "전·후 표본이 비었음"
        assert len({round(res[a]["mean_pre"], 8) for a in ARMS}) > 3, "규칙이 서로 같은 결과"
    return result, render(result)


def render(r: dict) -> str:
    P = L.pct
    v = r["verdicts"]
    out = [f"# 초과수익은 사라지는 중인가 — 팔지 않는 적립 규칙 v1 ({r['judge_version']}){' — 스모크(가짜 데이터)' if r['smoke'] else ''}", "",
           "규칙이 고른 곳을 사서 12개월 보유했을 때의 초과수익(대 시장)을 매달 만들어, 2008 년 이후에도 살아 있는지, 유의한 쇠퇴 추세가 있는지 본다.", "",
           f"**살아 있음(ALIVE) {v['alive']}** — " + " · ".join(f"{r['rule']['labels'][a]} **{v[a]}**" for a in ARMS), "",
           "통과는 엔진 반영이 아니다. 엔진은 바뀌지 않았다.", "",
           "## 규칙 (결과를 보기 전에 고정)", "",
           f"- 월별 초과수익 = 매달 첫 거래일에 규칙이 고른 곳(전날 종가까지의 자료)을 다음 날 종가에 사서 {FWD}거래일 보유한 단순 수익 − 같은 기간 시장 수익 (L15F 는 0.15 × (다리 − 시장)). "
           f"자료 {r['excess_first']} ~ {r['excess_last']} {r['excess_months']}개월. 인접 달은 겹치므로 블록 부트스트랩·Newey-West 를 쓴다.",
           f"- ALIVE: 2008-01-01 이후 평균 초과 > 0 이고 {r['rule']['block_months']}개월 이동 블록 부트스트랩 단측 p < {ALPHA}, 그리고 1927~ 전체 시간 기울기 Newey-West t > {T_DECAY}.",
           f"- DECAYED: 2008 전 평균 초과가 양(p < {ALPHA})인데 최근은 ALIVE 조건 미충족이고 기울기 t ≤ {T_DECAY}. 그 밖은 INCONCLUSIVE.", "",
           "## 규칙별 결과", "",
           "| 규칙 | 2008 전 평균 초과 (p) | 2008 후 평균 초과 (p) | 후 − 전 (단측 p) | 연 기울기 (t) | 판정 |", "|---|---|---|---|---|---|"]
    for a in ARMS:
        s = r["arms"][a]
        out.append(f"| {r['rule']['labels'][a]} | {P(s['mean_pre'], True, 2)} ({s['p_pre'] if s['p_pre'] is not None else '—'}) | "
                   f"{P(s['mean_post'], True, 2)} ({s['p_post'] if s['p_post'] is not None else '—'}) | {P(s['post_minus_pre'], True, 2)} "
                   f"({s['p_post_lower'] if s['p_post_lower'] is not None else '—'}) | {P(s['slope_per_year'], True, 3)} ({s['t_slope']:.2f}) | **{s['verdict']}** |")
    out += ["", f"## {ROLL_YEARS}년 이동 평균 초과 (5년 간격)", "", "| 규칙 | " + " | ".join(sorted({y for a in ARMS for y in r["arms"][a]["rolling15y_every5y"]})) + " |",
            "|---|" + "---|" * len(sorted({y for a in ARMS for y in r["arms"][a]["rolling15y_every5y"]}))]
    years = sorted({y for a in ARMS for y in r["arms"][a]["rolling15y_every5y"]})
    for a in ARMS:
        out.append(f"| {r['rule']['labels'][a]} | " + " | ".join(P(r["arms"][a]["rolling15y_every5y"].get(y), True, 1) for y in years) + " |")
    out += ["", "## 주의", "",
            "- 월별 초과수익은 12개월씩 겹쳐 독립이 아니다. 2008 후 표본은 약 16년(독립 12개월 덩어리 16개 남짓)이라 검정력이 낮다 — INCONCLUSIVE 가 많이 나올 수 있다.",
            "- 12 산업·대형 가치주는 Ken French 학술 포트폴리오다. 세금·비용은 넣지 않은 세전 초과수익이다(팔지 않는 적립이라 세금은 마지막 한 번).",
            "- 투자 조언이 아니다."]
    if r["smoke"]:
        out += ["", "스모크 실행: 가짜 데이터라 숫자에 의미가 없다."]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    return L.Runner(RULES_VERSION, argv).run(body)


if __name__ == "__main__":
    raise SystemExit(main())
