"""역할별 에이전트 모델 변경(허브 /research 폼, 텔레그램 /models) — 저장 파일은 tmp 로 격리."""

import importlib.util
import io
import json
from pathlib import Path

import pytest

from core import agent_budget as bud

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def iso(tmp_path, monkeypatch):
    monkeypatch.setattr(bud, "MODEL_OVERRIDES", tmp_path / "agent_models.json")
    monkeypatch.setattr(bud, "USAGE_LOG", tmp_path / "usage.jsonl")
    return tmp_path


def test_default_then_override_changes_model_and_estimate():
    assert bud.effective("writer").model == "opus"
    bud.set_model("writer", "sonnet", "test")
    cfg = bud.effective("writer")
    assert cfg.model == "sonnet" and cfg.est_cost_usd == pytest.approx(4.0 * 1.0 / 2.5)
    assert cfg.max_turns == bud.ROLES["writer"].max_turns        # 모델 외 상한은 그대로
    with pytest.raises(ValueError):
        bud.set_model("writer", "gpt-5")


def test_corrupt_or_unknown_override_falls_back(iso):
    (iso / "agent_models.json").write_text('{"writer": {"model": "gpt"}, "nobody": "opus", "critic": "haiku"}')
    assert bud.effective("writer").model == "opus" and bud.effective("critic").model == "haiku"
    (iso / "agent_models.json").write_text("not json")
    assert bud.model_overrides() == {}


def test_usage_estimate_uses_model_recorded_at_run_time():
    bud.record({"at": "2026-10-05T03:10:00+09:00", "role": "writer", "model": "haiku", "cost_usd": None})
    from datetime import datetime, timezone
    s = bud.summary(datetime(2026, 10, 4, 18, 30, tzinfo=timezone.utc))
    assert s["night_cost"] == pytest.approx(4.0 * 0.25 / 2.5)


def test_hub_form_saves_only_changes_and_renders_selected():
    from hub import research_status as rsx

    changed = rsx.apply_model_form({"writer": ["sonnet"], "critic": ["opus"], "scout": ["evil"], "zzz": ["opus"]})
    assert changed == ["writer=sonnet"]                           # critic 은 이미 opus, 잘못된 값은 무시
    html = rsx.render_model_form({"roles": bud.ROLES, "models": {r: bud.effective(r).model for r in bud.ROLES},
                                  "model_choices": bud.MODEL_CHOICES})
    assert 'name="writer"' in html and '<option value="sonnet" selected>sonnet</option>' in html
    assert '<option value="opus">opus (기본)</option>' in html


def test_hub_post_saves_and_redirects_and_blocks_foreign_origin():
    from hub.server import HubRequestHandler

    def call(origin):
        body = b"writer=haiku"
        h = HubRequestHandler.__new__(HubRequestHandler)
        h.path = "/research/models"
        h.headers = {"Host": "hub.example", "Content-Length": str(len(body)), **({"Origin": origin} if origin else {})}
        h.rfile, h.wfile = io.BytesIO(body), io.BytesIO()
        sent = []
        h.send_response = lambda code: sent.append(code)
        h.send_header = lambda *a: None
        h.end_headers = lambda: None
        h.do_POST()
        return sent[0]

    assert call("https://evil.example") == 403 and bud.effective("writer").model == "opus"
    assert call("https://hub.example") == 303 and bud.effective("writer").model == "haiku"


def test_telegram_runner_roles_match_core():
    spec = importlib.util.spec_from_file_location("runner_models", ROOT / "deploy" / "codex_telegram" / "runner.py")
    runner = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runner)
    assert [(r, d) for r, _, d in runner.AGENT_ROLES] == [(r, c.model) for r, c in bud.ROLES.items()]
    assert tuple(runner.AGENT_MODEL_CHOICES) == bud.MODEL_CHOICES
