"""AI 국제정세 의견 shadow(core/geo_shadow.py) — 검증·불변 원장·채점·야간 배치 연결·화면 표시."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from core import geo_shadow as gs
from core.champion_strategy import CORE_UNIVERSE


def _rec(month="2026-11", **views):
    assets = {t: {"view": 0, "confidence": 0.0, "reason": ""} for t in CORE_UNIVERSE}
    for t, v in views.items():
        assets[t] = {"view": v, "confidence": 0.6, "reason": "테스트 사유"}
    return {"month": month, "summary": "요약", "assets": assets, "sources": ["https://example.com/a"]}


def test_target_month():
    assert gs.target_month(date(2026, 10, 2)) is None
    assert gs.target_month(date(2026, 10, 25)) == "2026-11"
    assert gs.target_month(date(2026, 12, 30)) == "2027-01"


def test_validate_rejects_bad_records():
    with pytest.raises(gs.GeoRecordError) as e:
        bad = _rec(XLE=-1)
        bad["assets"]["XLE"]["reason"] = ""
        del bad["assets"]["XLK"]
        bad["sources"] = []
        gs.validate(bad, "2026-11")
    msg = str(e.value)
    assert "17자산" in msg and "sources" in msg
    with pytest.raises(gs.GeoRecordError, match="최대"):
        gs.validate(_rec(**{t: 1 for t in CORE_UNIVERSE[:7]}), "2026-11")
    with pytest.raises(gs.GeoRecordError, match="month"):
        gs.validate(_rec(month="2026-12"), "2026-11")


def test_ledger_is_append_only_one_per_month(tmp_path):
    led = tmp_path / "ledger.jsonl"
    first = gs.record(_rec(XLE=-1), "2026-11", path=led, now=datetime(2026, 10, 26, tzinfo=timezone.utc))
    again = gs.record(_rec(XLE=1), "2026-11", path=led)
    assert again["assets"]["XLE"]["view"] == -1 and again["sha"] == first["sha"]
    assert len(gs.load_ledger(led)) == 1 and gs.has_month("2026-11", led)


def test_ingest_draft(tmp_path):
    (tmp_path / "2026-11.json").write_text(json.dumps(_rec(GLD=1)), encoding="utf-8")
    ok, msg = gs.ingest_draft("2026-11", draft_dir=tmp_path, path=tmp_path / "l.jsonl")
    assert ok and "GLD" in msg
    (tmp_path / "2026-12.json").write_text("{not json", encoding="utf-8")
    ok, msg = gs.ingest_draft("2026-12", draft_dir=tmp_path, path=tmp_path / "l.jsonl")
    assert not ok and "거부" in msg


def test_evaluate_waits_then_scores():
    months = [f"2027-{m:02d}" for m in range(1, 13)] + [f"2028-{m:02d}" for m in range(1, 13)]
    rets = pd.DataFrame(0.01, index=months, columns=list(CORE_UNIVERSE))
    rets["XLE"] = -0.05  # AI 가 매달 XLE 를 불리하다고 봤고 실제로 나빴다
    top4 = {m: ["XLE", "XLK", "XLV", "DBC"] for m in months}
    rows = [{"month": m, "assets": _rec(m, XLE=-1)["assets"]} for m in months]
    early = gs.evaluate(rows[:5], rets, top4)
    assert early["verdict"].startswith("판정 전")
    import numpy as np
    rets.loc[:, "XLE"] = -0.05 + np.linspace(-0.001, 0.001, len(months))
    full = gs.evaluate(rows, rets, top4)
    assert full["months_scored"] == 24 and full["hit_rate"] == 1.0
    assert full["verdict"] == "PASS"


def test_geo_plan_runs_once_per_month(tmp_path, monkeypatch):
    from core import agent_batch as ab
    from core import agent_budget as budget

    monkeypatch.setattr(gs, "LEDGER", tmp_path / "l.jsonl")
    monkeypatch.setattr(gs, "DRAFT_DIR", tmp_path / "drafts")
    monkeypatch.setattr(budget, "can_launch", lambda role, now=None, path=None: (True, "ok"))
    early = datetime(2026, 10, 9, 19, 0, tzinfo=timezone.utc)
    assert ab.geo_plan(early, set()) is None
    now = datetime(2026, 10, 25, 19, 0, tzinfo=timezone.utc)  # 10/26 04:00 KST
    assert ab.geo_plan(now, set()) == ("geo_analyst", "2026-11", {})
    (tmp_path / "drafts").mkdir()
    (tmp_path / "drafts" / "2026-11.json").write_text(json.dumps(_rec(XLE=-1)), encoding="utf-8")
    assert ab.geo_plan(now, set()) is None and gs.has_month("2026-11")
    assert ab.tools_for("geo_analyst", "2026-11")[-1] == "Edit(research/geo_shadow/2026-11.json)"
    assert "국제정세" in ab.system_prompt("geo_analyst")
