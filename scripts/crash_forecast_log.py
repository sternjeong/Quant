"""급락 예측 기록기 — 실제 급락이 나면 그날의 예측을 원장에 한 줄씩 남긴다(덧붙이기 전용).

미국 시장이 1년 고점보다 15% 아래로 내려가면(crash-cycle-model-v1 의 발생일 정의) 그날과 발생 뒤 21·63·126거래일에
'최종 깊이 분포'와 '전고점 회복 확률'을 계산해 data/crash_forecast_log/forecasts.jsonl 에 적는다. 나중에 실제 결과와
맞춰 볼 수 있게 예측을 미리 못 박아 두는 것이 목적이다. 계산은 연구 공용 모듈(research/jobs/crash-cycle-lab/lab.py)의
함수를 그대로 쓴다 — 기준선(BASE)과 발생 뒤 갱신 모델(LM). 두 모델 모두 사전 등록 판정을 통과하지 못한 참고값이다.
엔진·아침 메시지·주문은 건드리지 않는다.

지수: Ken French 시장 총수익(한두 달 늦게 갱신)에 그 뒤 날짜를 SPY 수정 종가 수익으로 이어 붙인다.

    python scripts/crash_forecast_log.py              # 새로 기록할 예측이 있으면 기록하고 상태를 보여 준다
    python scripts/crash_forecast_log.py --dry-run    # 기록하지 않고 계산만
    python scripts/crash_forecast_log.py --report     # 지금까지의 기록과 그 뒤 실제 경과
    python scripts/crash_forecast_log.py --notify     # 새 기록이 생기면 텔레그램으로도 알림(스케줄러가 씀)
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOG_PATH = PROJECT_ROOT / "data" / "crash_forecast_log" / "forecasts.jsonl"
LOG_START = "2026-11-23"   # 이 날 이후 발생한 급락만 기록한다(그 전 사건은 연구에서 이미 본 것)
SAME_EPISODE_DAYS = 15     # 발생일이 이만큼(달력일) 안이면 같은 사건으로 본다 — French 자료가 뒤늦게 들어와 날짜가 며칠 밀릴 때
LATE_DAYS = 5              # 기준일보다 이만큼(달력일) 넘게 늦게 적으면 '늦은 기록'으로 표시
NOTE = "설명용 기록 — 추천 아님. BASE·LM 모두 사전 등록 판정을 통과하지 못한 참고값."


def lab():
    """연구 공용 모듈을 불러온다(폴더 이름에 '-' 가 있어 import 문을 못 쓴다)."""
    name = "crash_cycle_lab"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / "research" / "jobs" / "crash-cycle-lab" / "lab.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- 자료
def live_data(us: dict, spy: Optional[pd.Series]) -> dict:
    """French 시장 지수 뒤에 SPY 수익을 이어 붙인다. 금융 업종 지수·금리는 기록 모델이 쓰지 않아 같은 수익·0 으로 채운다."""
    L = us["L"]
    out = dict(us)
    out["french_last"], out["spy_last"] = pd.Timestamp(L.index[-1]), None
    if spy is None or len(spy) < 2:
        return out
    r = spy.astype(float).pct_change().dropna()
    r = r[r.index > L.index[-1]]
    r = r[r.index.dayofweek < 5]
    if r.empty:
        return out
    grow = (1 + r).cumprod()
    out["L"] = pd.concat([L, float(L.iloc[-1]) * grow])
    out["rf"] = pd.concat([us["rf"], pd.Series(0.0, index=r.index)])
    for k in ("F", "F49"):
        if us.get(k) is not None:
            out[k] = pd.concat([us[k], float(us[k].iloc[-1]) * grow])
    out["spy_last"] = pd.Timestamp(r.index[-1])
    return out


def load_spy() -> Optional[pd.Series]:
    from core.market_data import get_price_history

    df = get_price_history("SPY", start="1993-01-01", interval="1d")
    if df is None or df.empty:
        return None
    s = df["Adj Close"] if "Adj Close" in df.columns else df["Close"]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    return s.astype(float).dropna()


# ---------------------------------------------------------------- 원장
def read_log(path: Path = LOG_PATH) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def append_log(rows: list[dict], path: Path = LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")


def logged_t0(t0: pd.Timestamp, logged: list[dict]) -> Optional[str]:
    """이미 기록된 사건 중 발생일이 가까운 것의 발생일(없으면 None)."""
    for r in logged:
        if abs((pd.Timestamp(r["t0"]) - t0).days) <= SAME_EPISODE_DAYS:
            return r["t0"]
    return None


# ---------------------------------------------------------------- 예측
def _q(m1: Optional[dict]) -> Optional[dict]:
    return None if not m1 else {str(k): float(v) for k, v in m1.items()}


def _models(recs: list, r: dict, e: int) -> dict:
    """기준일(발생 뒤 e 거래일)까지의 정보로 낸 예측. 깊이 = 전고점 대비 최종 깊이 분위수, 회복 = 기준일부터 h 거래일 안 회복 확률."""
    m = lab()
    if e == 0:
        b = m.base0(recs, r)
        return {"BASE": {"depth": _q(b["m1"]), "recovery": _q(b["m2"]), "n_train": b["n_train"]}}
    b, lm = m.landmark_base(recs, r, e), m.landmark_lm(recs, r, e)
    return {"BASE": {"depth": _q(b["m1_trunc"]), "recovery": _q(b["m2"]), "n_train": m.n_train_of(b["m1_trunc"], b["n1"], b["m2"], b["n2"])},
            "LM": {"depth": _q(lm["m1"]), "recovery": _q(lm["m2"]), "n_train": m.n_train_of(lm["m1"], lm["n1"], lm["m2"], lm["n2"])}}


def new_rows(ctx: dict, logged: list[dict], now: Optional[datetime] = None, log_start: str = LOG_START,
             sources: Optional[dict] = None) -> list[dict]:
    """아직 적지 않은 (사건, 기준일) 예측. 예측은 기준일 종가까지의 정보만 쓴다(늦게 적어도 계산은 같다)."""
    m = lab()
    now = now or datetime.now(timezone.utc)
    today = pd.Timestamp(now.date())
    out: list[dict] = []
    for r in ctx["recs"]:
        if r["t0_date"] < pd.Timestamp(log_start):
            continue
        t0 = logged_t0(r["t0_date"], logged + out) or str(r["t0_date"].date())
        done = {x["landmark"] for x in logged + out if x["t0"] == t0}
        for e in (0,) + tuple(m.LANDMARKS):
            if e in done:
                continue
            st = m.landmark_state(r, e)
            if st is None:
                continue
            out.append({"t0": t0, "landmark": e, "asof": str(st["asof"].date()), "logged_at": now.isoformat(timespec="seconds"),
                        "late": bool((today - st["asof"]).days > LATE_DAYS), "peak_date": str(pd.Timestamp(ctx["idx"][r["tP"]]).date()),
                        "dd0": float(r["dd0"]), "depth_now": float(st["d"]), "low_so_far": float(st["m"]),
                        "models": _models(ctx["recs"], r, e), "lab": m.LAB_VERSION, "sources": sources or {}, "note": NOTE})
    return out


def outcome(ctx: dict, row: dict) -> Optional[dict]:
    """기록 뒤 실제 경과(지금까지): 사건 최저 깊이, 회복 여부와 기준일부터 걸린 거래일."""
    m = lab()
    t0 = pd.Timestamp(row["t0"])
    cand = [r for r in ctx["recs"] if abs((r["t0_date"] - t0).days) <= SAME_EPISODE_DAYS]
    if not cand:
        return None
    r = min(cand, key=lambda j: abs((j["t0_date"] - t0).days))
    a = m.pos_le(ctx["idx"], row["asof"])
    end = r["rec"] if r["rec"] is not None else ctx["last"]
    low = float(ctx["Lv"][r["t0"]:end + 1].min() / r["P"] - 1)
    return {"low": low, "recovered": r["rec"] is not None, "days": int(end - a),
            "rec_date": None if r["rec"] is None else str(pd.Timestamp(ctx["idx"][r["rec"]]).date())}


# ---------------------------------------------------------------- 출력
def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:+.0f}%"


def _depth(d: Optional[dict]) -> str:
    return "—" if not d else "/".join(_pct(d.get(k)) for k in ("0.1", "0.5", "0.9"))


def _rec(d: Optional[dict]) -> str:
    return "—" if not d else "/".join("—" if d.get(k) is None else f"{d[k] * 100:.0f}%" for k in ("252", "504", "1260"))


def row_lines(row: dict) -> list[str]:
    e = row["landmark"]
    head = f"[{row['t0']} 급락] " + ("발생일" if e == 0 else f"발생 뒤 {e}거래일") + f" 기준 {row['asof']} · 전고점 대비 {row['depth_now'] * 100:+.1f}%"
    if row.get("late"):
        head += " · 늦은 기록"
    lines = [head]
    for name, label in (("BASE", "기준선"), ("LM", "갱신 모델")):
        p = row["models"].get(name)
        if p:
            lines.append(f"  {label}: 최종 깊이 10/50/90% {_depth(p['depth'])} · 회복 1/2/5년 안 {_rec(p['recovery'])} (학습 사건 {p['n_train'] if p['n_train'] is not None else '—'})")
    return lines


def status_line(ctx: dict, data: dict) -> str:
    m = lab()
    spy = "SPY 이어 붙이기 없음" if data["spy_last"] is None else f"SPY {data['spy_last'].date()}까지 이어 붙임"
    return f"{m.now_line(m.reading_now(ctx))} (기준 {pd.Timestamp(ctx['idx'][ctx['last']]).date()} · French {data['french_last'].date()} · {spy})"


def report(ctx: dict, logged: list[dict]) -> str:
    if not logged:
        return "기록이 아직 없습니다. 시장이 1년 고점보다 15% 아래로 내려가면 그날부터 기록됩니다."
    lines = []
    for row in logged:
        lines += row_lines(row)
        o = outcome(ctx, row)
        if o:
            tail = f"회복 {o['rec_date']}(기준일 뒤 {o['days']}거래일)" if o["recovered"] else f"미회복(기준일 뒤 {o['days']}거래일째)"
            lines.append(f"  실제(지금까지): 사건 최저 {o['low'] * 100:+.1f}% · {tail}")
    return "\n".join(lines)


def build(smoke: bool = False, spy: Optional[pd.Series] = None) -> tuple[dict, dict]:
    m = lab()
    data = live_data(m.load_us(smoke), spy if (smoke or spy is not None) else load_spy())
    return m.us_context(data), data


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--report", action="store_true")
    p.add_argument("--notify", action="store_true")
    a = p.parse_args(argv)
    ctx, data = build()
    logged = read_log()
    print(status_line(ctx, data))
    if a.report:
        print(report(ctx, logged))
        return 0
    src = {"french_last": str(data["french_last"].date()), "spy_last": None if data["spy_last"] is None else str(data["spy_last"].date())}
    rows = new_rows(ctx, logged, sources=src)
    if not rows:
        print("새로 기록할 예측 없음")
        return 0
    text = "\n".join(line for r in rows for line in row_lines(r))
    print(text)
    if a.dry_run:
        print("(--dry-run: 기록하지 않음)")
        return 0
    append_log(rows)
    print(f"{len(rows)}줄 기록 → {LOG_PATH}")
    if a.notify:
        from core.telegram_notify import is_configured, send_message

        if is_configured():
            send_message("[급락 예측 기록]\n" + text + "\n\n" + NOTE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
