"""Reproduce S6 leakage with isolated function ASTs and synthetic dependencies.

No production module import: no network, database, cache writes or orders.
"""
from __future__ import annotations
import ast
from pathlib import Path
from types import SimpleNamespace
import pandas as pd

BASE = Path(__file__).resolve().parent.parent


def function(filename, name, stubs):
    node = next(n for n in ast.parse((BASE / "source" / filename).read_text()).body
                if isinstance(n, ast.FunctionDef) and n.name == name)
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    env = {"pd": pd, **stubs}
    exec(compile(ast.fix_missing_locations(module), filename, "exec"), env)
    return env[name]


def run_probes():
    current = pd.DataFrame({"Symbol": list("ABCD"), "Sector": ["Tech", "Tech", "Energy", "Energy"]})
    sampler = function("strategy_tuning.py", "sample_universe", {
        "screener": SimpleNamespace(get_universe=lambda **kw: current),
        "point_in_time_universe": SimpleNamespace(get_constituents_as_of=lambda *a: list("ABCD")),
        "point_in_time_market_cap": SimpleNamespace(get_market_caps_asof_batch=lambda *a, **kw: dict(zip("ABCD", [100, 90, 80, 70]))),
    })
    first = sampler(n=2, as_of_date="2010-01-04", use_point_in_time_market_cap=True).ticker.tolist()
    current["Sector"] = ["Tech", "Energy", "Tech", "Energy"]
    mutated = sampler(n=2, as_of_date="2010-01-04", use_point_in_time_market_cap=True).ticker.tolist()
    assert first == ["A", "C"] and mutated == ["A", "B"]
    caps = function("point_in_time_market_cap.py", "get_market_cap_asof", {
        "get_shares_outstanding_history": lambda *a, **kw: pd.Series([1000.], index=pd.to_datetime(["2019-01-01"])),
        "_cumulative_split_factor_after": lambda *a, **kw: 1.,
        "get_price_history": lambda *a, **kw: pd.DataFrame({"Close": [10., 99.]}, index=pd.to_datetime(["2020-06-30", "2020-07-01"])),
    })
    signal_cap, fill_day_cap = caps("TEST", "2020-06-30"), caps("TEST", "2020-07-01")
    assert signal_cap == 10000 and fill_day_cap == 99000
    called_dates = []
    def pool(**kw):
        called_dates.append(kw["as_of_date"])
        return pd.DataFrame({"ticker": []})
    picker = function("champion_strategy.py", "_pick_satellite_at_date", {
        "SATELLITE_BACKTEST_TOP_K": 3, "SATELLITE_BACKTEST_POOL_N": 40,
        "SATELLITE_BACKTEST_WARMUP_DAYS": 730, "CORE_UNIVERSE": [], "MARKET_FILTER_TICKER": "SPY",
        "sample_universe": pool, "get_multiple_price_history": lambda *a, **kw: {},
    })
    picker(pd.Timestamp("2020-07-01"))
    assert called_dates == ["2020-07-01"]
    future_cap = function("point_in_time_market_cap.py", "get_market_cap_asof", {
        "get_shares_outstanding_history": lambda *a, **kw: pd.Series([1000.], index=pd.to_datetime(["2022-01-01"])),
        "_cumulative_split_factor_after": lambda *a, **kw: 1.,
        "get_price_history": lambda *a, **kw: pd.DataFrame({"Close": [10.]}, index=pd.to_datetime(["2010-01-04"])),
    })("TEST", "2010-01-04")
    assert future_cap == 10000
    members = function("point_in_time_universe.py", "get_constituents_as_of", {
        "DEFAULT_CSV_PATH": "unused",
        "load_historical_constituents_table": lambda *a: pd.DataFrame({"date": pd.to_datetime(["2020-01-02"]), "tickers_list": [["FUTURE"]]}),
    })("2019-12-31")
    assert members == ["FUTURE"]
    calculate = function("champion_strategy.py", "_compute_portfolio_returns", {"BACKTEST_COST_BPS_PER_SIDE": 5.})
    idx = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
    closes = pd.DataFrame({"TEST": [100., 110., 110.]}, index=idx)
    legacy_return = float(calculate(closes, closes * 0 + 1, cost_bps_per_side=0)["ret_net"].iloc[1])
    exact_return = 110 / 109 - 1
    assert abs(legacy_return - exact_return) > .09
    compared = {}
    repo = BASE.parent.parent
    for file, names in {"strategy_tuning.py": ["sample_universe"],
                        "point_in_time_market_cap.py": ["get_market_cap_asof"],
                        "point_in_time_universe.py": ["get_constituents_as_of"],
                        "champion_strategy.py": ["_pick_satellite_at_date", "_compute_portfolio_returns"]}.items():
        for name in names:
            def tree(path):
                return next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == name)
            compared[f"{file}:{name}"] = ast.dump(tree(BASE / "source" / file)) == ast.dump(tree(repo / "core" / file))
    return {"scope": "synthetic legacy defects; not S6 performance", "current_sector_mutation": {"before": first, "after": mutated},
            "selection_calls_market_cap_on_fill_date": called_dates,
            "fill_day_close_leak": {"signal_close_cap": signal_cap, "fill_day_close_cap": fill_day_cap},
            "earliest_future_shares_cap": future_cap, "earliest_future_members": members,
            "close_approximation_return": legacy_return, "exact_next_open_return": exact_return,
            "current_function_ast_matches_frozen_reference": compared}
