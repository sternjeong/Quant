"""R&D 센터 연구 주제 켜기/끄기 (2026-10-05, 사용자 요청).

사용자가 관제 센터 'R&D 센터'에서 주제별로 연구를 켜고 끈다. 끄면 그 주제의 새 아이디어·재작업·판정이 멈추고, 이미 만든 아이디어·
기록·누적 시도 수·대기열은 그대로 남아 다시 켜면 그 자리에서 이어진다(아무것도 지우지 않는다).

상태 파일: data/rnd_topics.json — {"topics": {key: {"on": bool, "changed_at", "actor"}}, "log": [...최근 50건]}.
파일이 없거나 깨졌으면 모든 주제가 기본값(켜짐)이다. 주문 경로와 연결되어 있지 않다.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = PROJECT_ROOT / "data" / "rnd_topics.json"

# key: (이름, 무엇을 연구하나, 끄면 멈추는 것, 기본값)
TOPICS: dict[str, tuple[str, str, str, bool]] = {
    "sat_selection": ("새틀라이트 종목 선정", "어떤 종목을 고를지(신호·후보 풀·종목 수) — 야간 AI 아이디어",
                      "이 주제의 새 아이디어·재작업·판정", True),
    "sat_entry": ("새틀라이트 진입 타이밍", "뽑힌 종목을 언제 살지(바로·며칠 뒤·눌림목 기다리기)",
                  "이 주제의 새 아이디어·재작업·판정", True),
    "sat_exit": ("새틀라이트 매도 규칙", "언제 팔지(손절·익절·기간 청산·추세 이탈 청산·보유 기간)",
                 "이 주제의 새 아이디어·재작업·판정", True),
    "core_quarterly": ("코어 분기 연구", "분기마다 AI 가 근거 있는 코어 아이디어(선정·보유 중 매도 시점)를 제안하고 같은 판정으로 시험",
                       "분기 아이디어 제안과 판정", True),
    "geo_shadow": ("AI 국제정세 의견", "매달 리밸런싱 전 17자산 정세 의견 기록(배분 미반영, 24개월 뒤 판정)",
                   "그달 의견 기록(꺼진 달은 비고, 판정 표본이 줄어듦)", True),
    "crypto_shadow": ("코인 추세 기록", "BTC·ETH 100일 평균 위 보유 5% 슬리브를 매일 기록(12개월 뒤 판정)",
                      "매일 기록(꺼진 날은 직전 상태로 이어 본 것으로 평가되므로 오래 끄지 않기를 권함)", True),
    "sat_guru": ("거장 포트폴리오 참고", "버핏·애크먼 등 거장 13F(공시된 것만)로 새틀라이트·챔피언 종목을 고를 수 있는지(보유·확신·신규 매수·합의 복제)",
                 "이 주제의 새 아이디어·재작업·판정", True),
    "forward_tournament": ("앞으로 토너먼트", "v1: 현 코어와 아깝게 떨어진 후보 5개·SPY·60/40, v2: SPY+ERC 코어 블렌드·거장 우선 새틀라이트의 비중을 매일 기록(252거래일 뒤 판정)",
                           "매일 기록(꺼진 날은 직전 비중이 이어진 것으로 평가되므로 오래 끄지 않기를 권함)", True),
}
# 새틀라이트 아이디어 spec.topic → 주제 키
SAT_TOPIC_KEYS = {"selection": "sat_selection", "entry": "sat_entry", "exit": "sat_exit", "guru": "sat_guru"}


def _load(path: Optional[Path] = None) -> dict:
    p = Path(path or STATE_PATH)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("topics", {})
            data.setdefault("log", [])
            return data
    except (OSError, ValueError):
        pass
    return {"topics": {}, "log": []}


def is_on(key: str, path: Optional[Path] = None) -> bool:
    if key not in TOPICS:
        raise KeyError(key)
    entry = _load(path)["topics"].get(key)
    return bool(entry["on"]) if isinstance(entry, dict) and "on" in entry else TOPICS[key][3]


def all_states(path: Optional[Path] = None) -> dict[str, dict]:
    data = _load(path)
    out = {}
    for key, (label, what, pauses, default) in TOPICS.items():
        e = data["topics"].get(key) or {}
        out[key] = {"label": label, "what": what, "pauses": pauses, "on": bool(e.get("on", default)),
                    "changed_at": e.get("changed_at"), "actor": e.get("actor")}
    return out


def set_on(key: str, on: bool, actor: str = "hub", path: Optional[Path] = None) -> dict:
    if key not in TOPICS:
        raise KeyError(key)
    p = Path(path or STATE_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p.with_suffix(".lock"), "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = _load(p)
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        data["topics"][key] = {"on": bool(on), "changed_at": now, "actor": actor}
        data["log"] = (data["log"] + [{"at": now, "key": key, "on": bool(on), "actor": actor}])[-50:]
        fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
    return all_states(p)[key]


def sat_topic_on(spec_topic: Optional[str], path: Optional[Path] = None) -> bool:
    """새틀라이트 아이디어(spec.topic)의 주제가 켜져 있나. 모르는 값은 종목 선정으로 본다."""
    return is_on(SAT_TOPIC_KEYS.get(spec_topic or "selection", "sat_selection"), path)


def enabled_sat_topics(path: Optional[Path] = None) -> list[str]:
    """켜진 새틀라이트 주제(spec.topic 값) 목록 — 야간 배치가 새 아이디어 주제를 돌아가며 고른다."""
    return [t for t, k in SAT_TOPIC_KEYS.items() if is_on(k, path)]
