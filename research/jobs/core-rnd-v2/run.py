"""검증 연구 core-rnd-v2: 배당·분배금 포함 총수익 기준으로 챔피언 코어 선정 방식 변형 13개를 현 코어(C00)와 비교한다.
(사전 등록, 2026-10-02)

## v1 과 다른 점 (왜 새 id 인가)
v1(core-rnd-v1)을 실제 데이터로 돌린 뒤, 엔진이 가격(Close)만 쓰고 배당·분배금을 빼고 있음을 발견했다
(2022~2023 BIL: 가격 −0.04% vs 분배금 포함 +6.42%, HYG −11.1% vs −0.7%). 그래서 v1 의 현금→BIL(C01)·듀얼 모멘텀(C04)
결과는 의미가 없다. 판정 규칙은 그대로 두고 **측정 기준만 바꿔** 새로 등록한다(v1 결과는 그대로 보존):
  - 모든 변형과 현 코어의 수익은 Adj Close(배당·분배금 재투자 총수익)로 잰다 — 투자자가 실제로 받는 수익.
  - 순위·필터 신호는 각 변형 설정대로(현 코어와 C01~C12 는 현 엔진처럼 가격 기준).
  - C13 을 추가한다: 현 규칙 그대로, 순위·절대모멘텀·추세 신호만 총수익 기준(설명서상 '총수익률 랭킹'과 실제 코드의 차이를 묻는다).
  - 시도 수 N = 13. 현 코어 재현은 수익 대신 **비중**(종목 선택)이 라이브 엔진과 같은지로 확인한다.

## 사전 등록 (결과를 보기 전에 고정 — docs/RESEARCH_JOBS.md 2절, 이후 바꾸지 않는다. 바꾸려면 새 id)

변형은 아래 VARIANTS 가 전부이며(시도 수 N = 13), 각 변형은 현 코어에서 **한 가지 생각**만 바꾼다(C12 는 미리 정한 묶음).
엔진·체결 모델: core/core_lab.py (현 코어 재현은 tests/test_core_lab.py 와 이 스크립트의 replication 검사로 확인).
기간: 2008-01-01 ~ 실행일, 마지막 2년은 떼어 둔다(IS/OOS). 비용 편도 3bp(CORE_COST_BPS_PER_SIDE), 배당 반영은 가격 데이터 그대로.

판정 core-judge/v1 (core_lab.judge) — 모두 통과해야 PASS(= 사람 검토 대기, 챔피언 자동 반영 없음):
  G1 IS 일별 초과수익(변형 − 현 코어)의 Deflated Sharpe ≥ 0.95, 시도 수 13, 시도 간 샤프 분산은 고정 가정(연 0.5)
     (처음엔 12개 변형의 관측 분산을 쓰려 했으나, 합성 데이터 스모크에서 극단값 하나가 모두의 기준을 올리는 것을 보고
      실제 데이터 결과를 보기 전에 고정 가정으로 바꿨다 — 2026-10-02)
  G2 떼어 둔 2년의 샤프 ≥ 현 코어
  G3 IS 를 시간순 3등분했을 때 초과수익이 양수인 구간 ≥ 2
  G4 미리 정한 이웃 설정(NEIGHBORS)의 IS 초과 샤프가 모두 양수 (없으면 생략)
  G5 IS 최대낙폭이 현 코어보다 5%p 넘게 나쁘지 않음

규율: 결과를 보고 변형·이웃·기준을 고치지 않는다. 통과한 변형의 챔피언 반영은 사용자 확인 뒤 별도 작업이다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from core import core_lab as cl  # noqa: E402
from core.champion_strategy import CORE_UNIVERSE, MARKET_FILTER_TICKER  # noqa: E402

START = "2008-01-01"
FETCH_START = "2006-01-01"
EXTRA = [MARKET_FILTER_TICKER, cl.CASH_ETF, *cl.CREDIT_PAIR]
BASE = cl.CoreConfig()

# id: (제목, 생각, 설정, 이웃 설정들)
VARIANTS: dict[str, tuple[str, str, cl.CoreConfig, list[cl.CoreConfig]]] = {
    "C01_cash_bil": ("놀고 있는 현금 → 단기국채(BIL)", "시장필터 축소분·빈 슬롯이 수익 0 현금이라 버려진다",
                     cl.with_changes(BASE, cash="bil"), []),
    "C02_tranches4": ("4분할 시차 리밸런싱", "월 첫 거래일 하루에 모두 바꾸는 날짜 운을 줄인다",
                      cl.with_changes(BASE, tranches=4), [cl.with_changes(BASE, tranches=2)]),
    "C03_multi_horizon": ("3·6·9·12개월 모멘텀 순위 평균", "12개월 한 기간에 거는 대신 기간을 분산한다",
                          cl.with_changes(BASE, lookbacks=(63, 126, 189, 252)),
                          [cl.with_changes(BASE, lookbacks=(126, 189, 252)), cl.with_changes(BASE, lookbacks=(63, 126, 252))]),
    "C04_dual_momentum": ("현금보다 나을 때만 사기(+현금→BIL)", "12개월 수익률이 단기국채보다 나은 자산만 후보(Antonacci)",
                          cl.with_changes(BASE, abs_filter="bil", cash="bil"), []),
    "C05_corr_cap": ("상관 높은 자산 겹치지 않기(0.8)", "DBC·XLE 처럼 사실상 같은 위험에 두 번 거는 것을 막는다",
                     cl.with_changes(BASE, corr_cap=0.8),
                     [cl.with_changes(BASE, corr_cap=0.7), cl.with_changes(BASE, corr_cap=0.9)]),
    "C06_rank_buffer": ("순위 완충(6위까지 유지)", "4·5위가 엎치락뒤치락할 때의 불필요한 매매를 줄인다",
                        cl.with_changes(BASE, buffer_n=6),
                        [cl.with_changes(BASE, buffer_n=5), cl.with_changes(BASE, buffer_n=7)]),
    "C07_top3": ("3종목", "더 강한 모멘텀에 집중", cl.with_changes(BASE, top_n=3), []),
    "C08_top5": ("5종목", "더 넓게 분산", cl.with_changes(BASE, top_n=5), []),
    "C09_inverse_vol": ("변동성 반비례 비중", "같은 위험을 나눠 지도록 덜 흔들리는 자산에 더 싣는다",
                        cl.with_changes(BASE, weighting="inverse_vol"), []),
    "C10_asset_trend": ("자산별 추세 필터(10개월 이동평균)", "SPY 하나로 금·채권까지 줄이지 않고 하락 추세 자산만 뺀다(Faber)",
                        cl.with_changes(BASE, market_filter="asset_sma", filter_window=210),
                        [cl.with_changes(BASE, market_filter="asset_sma", filter_window=168),
                         cl.with_changes(BASE, market_filter="asset_sma", filter_window=252)]),
    "C11_credit_filter": ("신용 스트레스 필터(HYG/IEF)", "하이일드가 국채보다 약해지는 신용 경색 신호로 SPY 200일선을 대신한다",
                          cl.with_changes(BASE, market_filter="credit", filter_window=252),
                          [cl.with_changes(BASE, market_filter="credit", filter_window=126),
                           cl.with_changes(BASE, market_filter="credit", filter_window=378)]),
    "C12_bundle": ("묶음: 현금→BIL + 4분할 + 기간 혼합 + 상관 제한", "근거가 가장 탄탄한 넷을 미리 정해 함께 적용",
                   cl.with_changes(BASE, cash="bil", tranches=4, lookbacks=(63, 126, 189, 252), corr_cap=0.8), []),
    "C13_total_return_signal": ("순위·필터를 총수익 기준으로", "가격만 보면 분배금이 큰 채권·하이일드·유틸리티가 순위에서 손해를 본다",
                                cl.with_changes(BASE, signal_basis="total"), []),
}
N_TRIALS = len(VARIANTS)


def load_prices(smoke: bool):
    """(가격 closes, 가격 extra), (총수익 closes, 총수익 extra)."""
    tickers = list(CORE_UNIVERSE) + [t for t in EXTRA if t not in CORE_UNIVERSE]
    if smoke:
        idx = pd.bdate_range("2009-01-01", "2016-12-30")
        rng = np.random.default_rng(3)
        price = pd.DataFrame({t: 50 * np.exp(np.cumsum(rng.normal(0.0003, 0.012, len(idx)))) for t in tickers}, index=idx)
        price[cl.CASH_ETF] = 90.0
        yld = {t: rng.uniform(0.0, 0.0002) for t in tickers}
        yld[cl.CASH_ETF] = 0.0001
        total = price * pd.DataFrame({t: np.exp(np.cumsum(np.full(len(idx), yld[t]))) for t in tickers}, index=idx)
    else:
        from core.market_data import get_multiple_price_history

        hist = get_multiple_price_history(tickers, start=FETCH_START, end=None, interval="1d")
        price = pd.DataFrame({t: hist[t]["Close"] for t in tickers if t in hist and not hist[t].empty}).ffill()
        total = pd.DataFrame({t: hist[t]["Adj Close"] for t in tickers if t in hist and not hist[t].empty
                              and "Adj Close" in hist[t]}).ffill()
    core = [t for t in CORE_UNIVERSE if t in price.columns]
    ex = [t for t in EXTRA if t in price.columns]
    return (price[core], price[ex]), (total[core], total[ex])


def replication_check(closes: pd.DataFrame, extra: pd.DataFrame) -> dict:
    """C00 의 목표 비중(종목 선택)이 라이브 엔진(_build_core_weights)과 같은가. 수익은 v2 에선 총수익이라 비교하지 않는다."""
    from core.champion_strategy import _build_core_weights

    live = _build_core_weights(closes, extra[MARKET_FILTER_TICKER])
    lab = cl.build_weights(closes, extra, BASE)[live.columns]
    diff = (lab - live).abs().to_numpy().max()
    return {"days": int(len(live)), "max_abs_weight_diff": float(diff), "ok": bool(diff < 1e-12)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--smoke", action="store_true")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (closes, extra), total = load_prices(a.smoke)
    start = "2011-01-03" if a.smoke else START

    inc = cl.run(closes, extra, BASE, start, total=total)
    runs = {vid: cl.run(closes, extra, cfg, start, total=total) for vid, (_, _, cfg, _) in VARIANTS.items()}
    split = cl.holdout_split(inc.index)
    act_srs = []
    for r in runs.values():
        both = pd.concat([r.rename("v"), inc.rename("b")], axis=1).fillna(0.0)
        act_srs.append(cl.stats((both["v"] - both["b"])[both.index < split]).get("sharpe_daily", 0.0))

    results, verdicts = {}, {}
    for vid, (title, idea, cfg, nbs) in VARIANTS.items():
        nb_runs = [cl.run(closes, extra, n, start, total=total) for n in nbs]
        res = cl.judge({"returns": runs[vid]}, inc, nb_runs, n_trials=N_TRIALS, all_active_daily_srs=act_srs)
        res.update(title=title, idea=idea, config=cl.config_dict(cfg), neighbors=[cl.config_dict(n) for n in nbs])
        results[vid] = res
        verdicts[vid] = res["verdict"]
        print(f"{vid}: {res['verdict']} {'; '.join(res['reasons'])[:200]}", flush=True)

    replication = replication_check(closes, extra)
    payload = {"id": "core-rnd-v2", "return_basis": "total(Adj Close)", "judge_version": cl.JUDGE_VERSION, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "smoke": a.smoke, "period": [str(inc.index[0].date()), str(inc.index[-1].date())], "split": str(split.date()),
               "n_trials": N_TRIALS, "verdicts": verdicts, "incumbent": cl.stats(inc), "replication": replication,
               "variants": results}
    (out / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (out / "REPORT.md").write_text(report(payload), encoding="utf-8")
    return 0


def _pct(x, d=1):
    return "—" if x is None else f"{x * 100:.{d}f}%"


def report(p: dict) -> str:
    inc = p["incumbent"]
    lines = [f"# 코어 R&D v2 — 배당 포함 총수익 기준, 코어 선정 방식 변형 {p['n_trials']}개 vs 현 코어", "",
             "v1 은 가격(Close)만 써서 배당·분배금이 빠졌다(특히 BIL·HYG·채권). v2 는 모든 수익을 총수익(Adj Close)으로 잰다.", "",
             f"생성 {p['generated_at']} · 기간 {p['period'][0]} ~ {p['period'][1]} · 떼어 둔 구간 {p['split']} 이후"
             + (" · **스모크(합성 데이터) — 실제 결과 아님**" if p["smoke"] else ""), "",
             f"현 코어(C00, 총수익 기준): CAGR {_pct(inc.get('cagr'))}, 연샤프 {inc.get('sharpe_annual', 0):.2f}, 최대낙폭 {_pct(inc.get('max_drawdown'))}", ""]
    if p.get("replication"):
        rp = p["replication"]
        lines.append(f"현 코어 재현 검사(라이브 엔진과 매일의 목표 비중 비교): {'일치' if rp['ok'] else '불일치'} "
                     f"(최대 차이 {rp['max_abs_weight_diff']:.2e}, {rp['days']}일)")
        lines.append("")
    lines += ["## 판정 (사전 등록 core-judge/v1, 모든 관문 통과해야 PASS = 사람 검토 대기)", "",
              "| 변형 | 판정 | 전체 CAGR | 전체 샤프 | 최대낙폭 | IS 초과 샤프 | DSR | 2년 샤프(현 코어) | 사유 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for vid, r in p["variants"].items():
        s, g = r["stats"], r["gates"]
        lines.append(f"| {vid} {r['title']} | **{r['verdict']}** | {_pct(s['full'].get('cagr'))} | {s['full'].get('sharpe_annual', 0):.2f} | "
                     f"{_pct(s['full'].get('max_drawdown'))} | {g['G1_improves_corrected']['active_sharpe_annual']:.2f} | "
                     f"{g['G1_improves_corrected']['dsr']:.2f} | {g['G2_holdout']['oos_sharpe']:.2f} ({g['G2_holdout']['incumbent_oos_sharpe']:.2f}) | "
                     f"{'; '.join(r['reasons']) or '—'} |")
    lines += ["", "## 읽는 법", "",
              "- G1: 현 코어 대비 일별 초과수익이 13번 시도한 것을 감안해도 우연이 아닐 확률(DSR) 0.95 이상.",
              "- G2: 마지막 2년(파라미터 선택에 안 쓴 구간)에서도 샤프가 현 코어 이상.",
              "- G3: 앞 구간을 시간순으로 3등분해 2구간 이상에서 초과수익이 양수(한 시기에만 통한 게 아닌지).",
              "- G4: 숫자를 조금 바꾼 이웃 설정도 현 코어보다 나음. G5: 최대낙폭이 5%p 넘게 나빠지지 않음.",
              "- PASS 도 챔피언에 자동 반영되지 않는다. 비용은 편도 3bp 고정, 세금·슬리피지 없음. 과거 결과는 미래를 보장하지 않는다."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
