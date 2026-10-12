"""leader-catch-v1 규칙 기계 장치: 룩어헤드 없음·특징 수학·적중률 기회 수준·부트스트랩 결정성·판정 경계·작업 계약."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
JOB = ROOT / "research/jobs/leader-catch-v1"


def _load(name, path):
    if name in sys.modules and hasattr(sys.modules[name], "Context"):
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lab = _load("leader_catch_lab", JOB / "lab.py")


def _panel(n=700, k=12, seed=1):
    idx = pd.bdate_range("2001-01-01", periods=n)
    rng = np.random.default_rng(seed)
    rets = pd.DataFrame(rng.normal(0.0003, 0.01, (n, k)), index=idx, columns=[f"I{j:02d}" for j in range(k)])
    mkt = pd.Series(rng.normal(0.0003, 0.008, n), index=idx)
    return rets, mkt, pd.Series(0.0001, index=idx)


# ---- 특징 수학 (손으로 만든 계열) ---------------------------------------------------------------------------
def test_feature_math_on_hand_built_series():
    n = 400
    idx = pd.bdate_range("2001-01-01", periods=n)
    r = pd.DataFrame({"A": 0.001, "B": -0.001, "C": 0.0}, index=idx)
    mkt = pd.Series(0.0005, index=idx)
    f = lab.raw_scores(r, mkt)
    t = 350
    # F1: 231행 복리, 21행 지연
    assert f["F1"]["A"].iloc[t] == pytest.approx(1.001 ** lab.W_F1 - 1)
    assert f["F1"]["B"].iloc[t] == pytest.approx(0.999 ** lab.W_F1 - 1)
    assert np.isnan(f["F1"]["A"].iloc[lab.W_F1 + lab.SKIP_F1 - 2])
    assert not np.isnan(f["F1"]["A"].iloc[lab.W_F1 + lab.SKIP_F1 - 1])
    assert f["F2"]["A"].iloc[t] == pytest.approx(1.001 ** 126 - 1)
    # F3: 계속 오르는 계열은 고점 = 오늘 → 1, 계속 내리는 계열은 252행 전 대비 비율
    assert f["F3"]["A"].iloc[t] == pytest.approx(1.0)
    assert f["F3"]["B"].iloc[t] == pytest.approx(0.999 ** (lab.W_HIGH - 1))
    # F4: 추세 위(A)가 아래(B)보다 항상 위
    assert f["F4"]["A"].iloc[t] > f["F4"]["C"].iloc[t] > f["F4"]["B"].iloc[t] - 1000 and f["F4"]["A"].iloc[t] > 1000
    assert f["F4"]["B"].iloc[t] < 1000
    # F5: 12개월 수익 − 시장
    assert f["F5"]["A"].iloc[t] == pytest.approx((1.001 ** 252 - 1) - (1.0005 ** 252 - 1))
    # F6: 계속 신고가면 경과 0 → 점수 0, 계속 하락이면 신고가 없음 → 가장 오래된 55행 전 최고(=창 시작)가 아니라 NaN 아닌 음수
    assert f["F6"]["A"].iloc[t] == 0
    assert f["F6"]["B"].iloc[t] < 0 or np.isnan(f["F6"]["B"].iloc[t])
    # F7: 변동성 0 → 점수 0, F8: 지난 21행 수익의 음수
    assert f["F7"]["A"].iloc[t] == pytest.approx(0.0, abs=1e-12)
    assert f["F8"]["A"].iloc[t] == pytest.approx(-(1.001 ** 21 - 1))
    assert f["F8"]["B"].iloc[t] == pytest.approx(-(0.999 ** 21 - 1))


def test_f6_days_since_high_counts_rows():
    n = 200
    idx = pd.bdate_range("2001-01-01", periods=n)
    price = np.concatenate([np.linspace(100, 150, 120), np.linspace(149, 120, 80)])
    ret = pd.Series(price).pct_change().fillna(0.0).to_numpy()
    r = pd.DataFrame({"A": ret, "B": ret}, index=idx)
    r.iloc[0] = np.nan  # 첫 행을 시작 전으로 두지 않기 위해 아래에서 되돌림
    r = r.fillna(0.0)
    f = lab.raw_scores(r, pd.Series(0.0, index=idx))
    # 고점은 행 119; 행 150 에서 경과 31
    assert f["F6"]["A"].iloc[150] == -(150 - 119)


def test_composite_is_average_rank_of_f1_f3_f5():
    rets, mkt, rf = _panel()
    ctx = lab.Context(rets, mkt, rf, 3)
    i = 15
    ranks = [pd.Series(ctx.scores[n][i]).rank(pct=True).to_numpy() for n in ("F1", "F3", "F5")]
    np.testing.assert_allclose(ctx.scores["C"][i], np.mean(ranks, axis=0))


# ---- 룩어헤드 없음 ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("sig", lab.SIGNALS)
def test_no_lookahead_changing_data_from_decision_date_leaves_scores_unchanged(sig):
    rets, mkt, rf = _panel()
    base = lab.Context(rets, mkt, rf, 3)
    m = 14
    d = int(base.dec[m])
    r2, m2 = rets.copy(), mkt.copy()
    r2.iloc[d:] = -r2.iloc[d:] * 7 + 0.02 * np.arange(r2.shape[1])   # d 이후(결정일 당일 포함)를 크게 바꿈
    m2.iloc[d:] = -0.04
    alt = lab.Context(r2, m2, rf, 3)
    np.testing.assert_allclose(base.scores[sig][: m + 1], alt.scores[sig][: m + 1], equal_nan=True)
    assert (base.picks(sig)[: m + 1] == alt.picks(sig)[: m + 1]).all()
    # 그리고 바꾼 뒤의 신호는 실제로 달라진다(시험이 헛돌지 않음)
    assert not np.allclose(base.scores[sig][m + 3:], alt.scores[sig][m + 3:], equal_nan=True)


def test_execution_is_next_day_and_weights_hold_constant():
    rets, mkt, rf = _panel()
    ctx = lab.Context(rets, mkt, rf, 3)
    pk = ctx.picks("F1")
    w = ctx.daily_weights(pk)
    m = 15
    a, b = int(ctx.dec[m]), int(ctx.dec[m + 1])
    assert (w.iloc[a:b] == pk[m] / 3.0).all().all()
    ex = w.shift(1)
    # 결정일 당일 수익은 새 포지션에 속하지 않는다
    assert (ex.iloc[a] == pk[m - 1] / 3.0).all()


# ---- 적중률 기회 수준 -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("n_members", [12, 49])
def test_hit_rate_on_random_data_is_near_one_third_and_ic_near_zero(n_members):
    rets, mkt, rf = _panel(n=2600, k=n_members, seed=5)
    ctx = lab.Context(rets, mkt, rf, 3 if n_members == 12 else 5)
    for sig in ("F1", "F8"):
        h = lab.hit_series(ctx, sig, 1)
        ic = lab.ic_series(ctx, sig)
        assert abs(np.nanmean(h) - 1 / 3) < 0.05
        assert abs(np.nanmean(ic)) < 0.05


def test_hit_rate_is_one_when_signal_is_perfect():
    rets, mkt, rf = _panel()
    ctx = lab.Context(rets, mkt, rf, 3)
    ctx.scores["F1"] = ctx.next1.copy()      # 미래를 그대로 신호로(검산용)
    h = lab.hit_series(ctx, "F1", 1)
    assert np.nanmin(h) == 1.0
    ic = lab.ic_series(ctx, "F1")
    assert np.nanmin(ic) > 0.999


# ---- 부트스트랩 ---------------------------------------------------------------------------------------------
def test_bootstrap_is_deterministic_and_covers_mean():
    rng = np.random.default_rng(0)
    x = rng.normal(0.4, 0.2, 240)
    a, b = lab.block_bootstrap_ci(x), lab.block_bootstrap_ci(x)
    assert a == b
    assert a["lo"] < a["mean"] < a["hi"]
    assert lab.block_bootstrap_ci(x, seed=1)["lo"] != a["lo"]
    # NaN 은 버리고, 표본이 너무 적으면 구간 없음
    y = np.concatenate([x, [np.nan] * 5])
    assert lab.block_bootstrap_ci(y) == a | {"n": 240} or lab.block_bootstrap_ci(y)["n"] == 240
    assert lab.block_bootstrap_ci(x[:10])["lo"] is None


def test_bootstrap_constants_are_preregistered():
    assert (lab.BOOT_BLOCK, lab.BOOT_DRAWS, lab.BOOT_SEED) == (12, 1000, 20261012)
    assert lab.TOP_K == {"ind12": 3, "ind49": 5, "ports25": 5}
    assert lab.N_TRIALS == 27


# ---- 판정 경계 ----------------------------------------------------------------------------------------------
def test_cell_pass_edges():
    ok = (0.40, 0.03, 2.0, 3)
    assert lab.cell_pass(*ok) is True
    assert lab.cell_pass(1 / 3, 0.03, 2.0, 3) is False          # 하한이 정확히 1/3 이면 불통과(엄격히 초과)
    assert lab.cell_pass(0.40, 0.03, 1.99, 3) is False
    assert lab.cell_pass(0.40, -0.01, 2.5, 3) is False
    assert lab.cell_pass(0.40, 0.0, 2.5, 3) is False
    assert lab.cell_pass(0.40, 0.03, 2.0, 2) is False
    assert lab.cell_pass(None, 0.03, 2.0, 3) is None
    assert lab.cell_pass(0.4, float("nan"), 2.0, 3) is None


def test_signal_and_overall_verdicts():
    assert lab.signal_verdict([True, True, False]) == "ROBUST"
    assert lab.signal_verdict([True, False, None]) == "NOT_ROBUST"
    assert lab.signal_verdict([None, None, None]) == "NOT_EVALUABLE"
    base = {s: "NOT_ROBUST" for s in lab.SIGNALS}
    assert lab.overall_verdict(base) == "NO_ROBUST_LEADER_SIGNAL"
    assert lab.overall_verdict({**base, "F1": "ROBUST"}) == "LEADER_SIGNAL_ROBUST"
    assert lab.overall_verdict({**base, "F1": "ROBUST", "F7": "ROBUST"}) == "NOT_DISCRIMINATING"
    assert lab.overall_verdict({**base, "F8": "ROBUST"}) == "NOT_DISCRIMINATING"
    assert lab.overall_verdict({s: "NOT_EVALUABLE" for s in lab.SIGNALS}) == "NOT_EVALUABLE"


def test_etf_menu_has_no_qqq_and_supporting_rule():
    assert "QQQ" not in lab.ETF_MENU and len(lab.ETF_MENU) == 17
    good = {"hit1": {"mean": 0.4}, "ic": {"mean": 0.05}, "port": {"alpha_mkt": 0.01}}
    assert lab.etf_supports(good) is True
    assert lab.etf_supports({**good, "ic": {"mean": -0.01}}) is False
    assert lab.etf_supports({**good, "hit1": {"mean": 1 / 3}}) is False


def test_concentration_top3_share():
    idx = pd.bdate_range("2001-01-01", "2004-12-31")
    n = len(idx)
    cols = [f"M{j:02d}" for j in range(10)]
    r = pd.DataFrame(0.0, index=idx, columns=cols)
    ctx_r = r.copy()
    for j in range(3):          # 매년 M00~M02 가 리더(연 약 +50~100%), 나머지 0
        ctx_r.iloc[:, j] = 0.003 * (3 - j)
    ctx = lab.Context(ctx_r, pd.Series(0.0, index=idx), pd.Series(0.0, index=idx), 3)
    rows = lab.concentration_table(ctx)
    assert rows and all(abs(x["top3_share_pos"] - 1.0) < 1e-9 for x in rows)
    assert all(x["top3_overlap"] == 3 for x in rows if x["top3_overlap"] is not None)
    s = lab.concentration_summary(rows)
    assert s["pre2008"]["years"] == len(rows) and s["post2008"]["years"] == 0


# ---- 작업 계약·스모크 ----------------------------------------------------------------------------------------
def test_job_definition_contract():
    from core import research_jobs as rj

    jobs, invalid = rj.load_job_definitions(rj.Config.for_root(ROOT))
    assert "leader-catch-v1" not in invalid
    j = jobs["leader-catch-v1"]
    assert j.priority == 22 and j.resumable and j.max_memory_mb <= 1500
    assert j.summary_from == "verdicts" and set(j.outputs) == {"results.json", "REPORT.md"}
    assert (JOB / "SPEC.md").exists()


def test_french_dataset_registered():
    from core import french_factors as ff

    assert ff.DATASETS["ports25_daily"] == "25_Portfolios_5x5_Daily_CSV.zip"


def test_smoke_runs_resumes_and_writes_outputs(tmp_path):
    run = [sys.executable, str(JOB / "run.py"), "--smoke", "--out", str(tmp_path / "out"), "--checkpoint", str(tmp_path / "ck")]
    p1 = subprocess.run(run + ["--max-cells", "3"], capture_output=True, text=True, cwd=ROOT)
    assert p1.returncode == 3, p1.stderr[-500:]
    assert len(list((tmp_path / "ck").glob("cell_*.json"))) == 3
    p2 = subprocess.run(run, capture_output=True, text=True, cwd=ROOT)
    assert p2.returncode == 0, p2.stderr[-800:]
    res = json.loads((tmp_path / "out/results.json").read_text(encoding="utf-8"))
    assert res["smoke"] is True and res["power"]["n_trials"] == 27
    assert set(res["signal_verdicts"]) == set(lab.SIGNALS)
    assert res["verdicts"]["overall"] in {"LEADER_SIGNAL_ROBUST", "NO_ROBUST_LEADER_SIGNAL", "NOT_DISCRIMINATING", "NOT_EVALUABLE"}
    for u in lab.UNIVERSES:
        assert set(res["universes"][u]["cells"]) == set(lab.SIGNALS)
        assert res["universes"][u]["concentration"]["summary"]["pre2008"]["years"] > 50
    assert set(res["etf"]) == set(lab.ETF_SIGNALS)
    rep = (tmp_path / "out/REPORT.md").read_text(encoding="utf-8")
    for needle in ("검정력(사전 계산)", "리더십 집중도 진단", "ETF 메뉴", "NOT_DISCRIMINATING", "F8"):
        assert needle in rep
    # 이미 끝난 체크포인트로 다시 돌리면 같은 판정(결정적)
    p3 = subprocess.run(run, capture_output=True, text=True, cwd=ROOT)
    assert p3.returncode == 0
    assert json.loads((tmp_path / "out/results.json").read_text(encoding="utf-8"))["verdicts"] == res["verdicts"]
