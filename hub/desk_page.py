"""관제 센터 '판단판' 화면(/desk) — 시장·내 포트폴리오·보유·관심 종목의 앞으로 1·3·6·12개월 분포와 사건 확률(읽기 전용).

원천: data/decision_desk/latest.json (scripts/decision_desk.py 가 매일 만든다). 이 화면은 계산하지 않고 그 파일만 그린다.
매수·매도를 정해 주지 않는다. 숫자마다 과거 검증 성적(근거 등급)을 함께 보여 준다.
"""

from __future__ import annotations

from typing import Any, Optional

from core import decision_desk as dd
from hub import ui

E = ui.E
GRADE_TONE = {"강함": "ok", "보통": "info", "약함": "warn", "없음": "muted"}
H_LABEL = {21: "1개월", 63: "3개월", 126: "6개월", 252: "12개월"}
BAR_SPAN = 0.5          # 막대가 그리는 범위: −50% ~ +50%
STYLE = """<style>
.desk{background:var(--surface);border:1px solid var(--border);border-radius:10px;margin:8px 0;padding:0}
.desk>summary{cursor:pointer;list-style:none;padding:10px 12px}
.desk>summary::-webkit-details-marker{display:none}
.desk .hd{display:flex;justify-content:space-between;gap:8px;align-items:baseline;flex-wrap:wrap}
.desk .tk{font-weight:700;font-size:16px}
.desk .sub{color:var(--muted);font-size:12.5px;margin-top:2px}
.desk .in{padding:0 12px 12px}
.desk table{font-size:13px;margin:6px 0}
.desk td,.desk th{padding:5px 6px;text-align:right}
.desk td:first-child,.desk th:first-child{text-align:left}
.desk .base{color:var(--muted);font-size:11.5px}
.rng{position:relative;height:10px;background:var(--bg);border-radius:5px;margin:8px 0 2px}
.rng .f{position:absolute;top:0;bottom:0;background:var(--border);border-radius:5px}
.rng .z{position:absolute;top:-2px;bottom:-2px;width:1px;background:var(--muted)}
.rng .m{position:absolute;top:-3px;bottom:-3px;width:3px;border-radius:2px;background:var(--text)}
.rngl{display:flex;justify-content:space-between;color:var(--muted);font-size:11.5px}
.flags{margin-top:4px;display:flex;gap:4px;flex-wrap:wrap}
</style>"""


def collect() -> dict[str, Any]:
    return {"snap": dd.read_snapshot()}


def card_badge(data: Optional[dict] = None) -> str:
    snap = (data or collect()).get("snap")
    if not snap:
        return ui.pill("아직 없음", "muted")
    if snap.get("status") != "ok":
        return ui.pill("모형 대기", "warn")
    return ui.pill(f"기준 {snap.get('asof', '—')}", "ok")


def _pct(x: Optional[float], digits: int = 0) -> str:
    return "—" if x is None else f"{x * 100:+.{digits}f}%"


def _p(x: Optional[float]) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def _money(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:,.0f}"


def _row(sh: dict, h: int = 63) -> Optional[dict]:
    return next((r for r in sh.get("horizons", []) if r["h"] == h), None)


def range_bar(q: list) -> str:
    """10%~90% 범위(회색 띠)와 중앙값(굵은 눈금), 0%(가는 눈금). −50%~+50% 를 그린다."""
    def pos(v: float) -> float:
        return max(0.0, min(100.0, (v + BAR_SPAN) / (2 * BAR_SPAN) * 100))

    lo, mid, hi = pos(q[0]), pos(q[2]), pos(q[4])
    return (f'<div class="rng" role="img" aria-label="10%~90% 범위 {E(_pct(q[0]))} ~ {E(_pct(q[4]))}">'
            f'<i class="f" style="left:{lo:.1f}%;width:{max(hi - lo, 1):.1f}%"></i><i class="z" style="left:50%"></i>'
            f'<i class="m" style="left:{mid:.1f}%"></i></div>'
            f'<div class="rngl"><span>나쁜 10% {E(_pct(q[0]))}</span><span>중앙 {E(_pct(q[2]))}</span><span>좋은 10% {E(_pct(q[4]))}</span></div>')


def _g(grade: Optional[str]) -> str:
    """근거 등급 표시(작은 알약)."""
    grade = grade if grade in GRADE_TONE else "없음"
    return ui.pill(grade, GRADE_TONE[grade], plain=True)


def tables(sh: dict) -> str:
    """수익 범위 표와 확률 표. 괄호 안은 과거 평균(상태를 보지 않은 값), 알약은 그 칸의 근거 등급."""
    rows = sh.get("horizons", [])
    if not rows:
        return ""
    a = "".join(f'<tr><td>{E(H_LABEL[r["h"]])}</td><td>{E(_pct(r["q"][0]))}</td><td>{E(_pct(r["q"][2]))} '
                f'<span class="base">({E(_pct(r["q_base"][2]))})</span></td><td>{E(_pct(r["q"][4]))}</td><td>{_g(r["grade"].get("q"))}</td></tr>'
                for r in rows)
    evs = [k for k in ("up", "dd15", "beat") if any(k in r["p"] for r in rows)]
    names = {"up": "오를 확률", "dd15": "15% 이상 빠질 확률", "beat": "시장을 이길 확률"}
    out = ('<table class="tbl"><tr><th>수익 범위</th><th>나쁜 10%</th><th>중앙 (평균)</th><th>좋은 10%</th><th>등급</th></tr>' + a + "</table>")
    for k in evs:
        cells = "".join(f'<tr><td>{E(H_LABEL[r["h"]])}</td><td>{E(_p(r["p"].get(k)))}</td><td class="base">{E(_p(r["p_base"].get(k)))}</td>'
                        f'<td>{_g(r["grade"].get(k))}</td></tr>' for r in rows if k in r["p"])
        out += f'<table class="tbl"><tr><th>{E(names[k])}</th><th>엔진</th><th>과거 평균</th><th>등급</th></tr>{cells}</table>'
    return out


def _stats_line(sh: dict) -> str:
    st = sh.get("stats") or {}
    ret = st.get("ret") or {}
    bits = [f"1년 고점 대비 {_pct(st.get('dd_252'))}", f"200일 평균 대비 {_pct(st.get('vs_200ma'))}",
            f"최근 3개월 {_pct(ret.get('63'))} · 12개월 {_pct(ret.get('252'))}", f"연 변동성 {_p(st.get('vol_ann'))}"]
    return '<div class="sub">' + E(" · ".join(bits)) + "</div>"


def asset_block(sh: dict, *, open_: bool = False) -> str:
    """자산 하나: 접힌 줄(3개월 범위·낙폭 위험)과 펼친 표."""
    pos = sh.get("position") or {}
    head_right = []
    if pos.get("weight") is not None:
        head_right.append(f"비중 {_p(pos['weight'])}")
    if pos.get("pnl_pct") is not None:
        head_right.append(f"손익 {_pct(pos['pnl_pct'])}")
    if sh.get("value") is not None:
        head_right.append(f"평가액 {_money(sh['value'])}")
    flags = "".join(ui.pill(f, "warn", plain=True) for f in sh.get("flags", []))
    flags = f'<div class="flags">{flags}</div>' if flags else ""
    head = (f'<div class="hd"><span class="tk">{E(sh["ticker"])}</span><span class="sub">{E(" · ".join(head_right))}</span></div>')
    if sh.get("error"):
        return f'<details class="desk"><summary>{head}<div class="sub">{E(sh["error"])}</div>{flags}</summary></details>'
    r = _row(sh)
    risk = ""
    if r:
        extra = "" if "beat" not in r["p"] else f" · 시장 이길 확률 {_p(r['p']['beat'])}"
        risk = (f'<div class="sub">3개월 안 15% 이상 빠질 확률 <b>{E(_p(r["p"].get("dd15")))}</b> (과거 평균 {E(_p(r["p_base"].get("dd15")))})'
                f'{E(extra)}</div>')
    bar = range_bar(r["q"]) if r else ""
    inner = _stats_line(sh) + tables(sh)
    if pos.get("bad_case_63") is not None:
        inner += f'<div class="base">3개월 나쁜 10% 경우 이 종목 평가 손익 약 {E(_money(pos["bad_case_63"]))}</div>'
    if sh.get("bad_case_63") is not None:
        inner += f'<div class="base">3개월 나쁜 10% 경우 포트폴리오 평가 손익 약 {E(_money(sh["bad_case_63"]))}</div>'
    if sh.get("dropped"):
        inner += f'<div class="base">이력이 짧아 뺀 종목: {E(", ".join(sh["dropped"]))}</div>'
    inner += f'<div class="base">{E(dd.LAYER_LABELS.get(sh.get("layer"), ""))} · 기준일 {E(sh.get("asof", "—"))}</div>'
    return (f'<details class="desk"{" open" if open_ else ""}><summary>{head}{bar}{risk}{flags}</summary>'
            f'<div class="in">{inner}</div></details>')


HOW_TO = (
    ("무엇을 보여 주나", "자산마다 앞으로 1·3·6·12개월 수익이 어디에 떨어질지(나쁜 10%·중앙·좋은 10%)와, 오를 확률·기간 중 15% 이상 빠질 확률·시장(SPY)을 이길 확률입니다."),
    ("괄호 안 숫자", "상태를 보지 않은 과거 평균입니다. 엔진 숫자가 괄호와 많이 다르면 지금 상태(변동성·낙폭·추세)가 평소와 다르다는 뜻입니다."),
    ("근거 등급", "그 칸의 예측이 과거에 과거 평균보다 얼마나 잘 맞았는지입니다. 강함 = 엄격한 검정을 통과, 보통 = 5% 수준에서 유의하고 모든 시대에서 나았음, 약함 = 평균적으로만 나았음, 없음 = 과거 평균보다 낫지 않았음. 약함·없음인 칸은 괄호 안 과거 평균과 같은 무게로 보세요."),
    ("이 엔진이 아는 것과 모르는 것", "검증(desk-engine-v1, 2026-11-23): 종목·업종의 '수익 범위'와 '15% 이상 빠질 확률'은 과거 평균보다 뚜렷하게 잘 맞았습니다(강함) — 대부분 지금 변동성에서 나옵니다. '오를 확률'과 '시장을 이길 확률'은 과거 평균보다 낫지 않았습니다(없음) — 방향은 이 엔진이 모릅니다. 시장(SPY) 자체는 모든 칸이 약함입니다. 그래서 이 화면은 '얼마나 흔들리고 얼마나 위험한가'를 보는 데 쓰고, '오를까'의 근거로 쓰지 마세요."),
    ("무엇이 아닌가", "매수·매도 신호가 아닙니다. 분포를 맞히는 것과 돈을 버는 것은 다릅니다. 개별 종목 모형은 상장폐지 종목이 빠진 자료로 만들어 하락 위험이 실제보다 낮게 잡힙니다."),
    ("검증에서 확인된 것", "급락 뒤 반등 신호를 기다린 쪽은 바로 산 쪽보다 나빴습니다(신호 7개 모두). 분할 매수는 1967년 이후 일괄 매수보다 뒤졌습니다. 시장이 1년 고점 −15%에 닿은 뒤 최종 낙폭 중앙값은 −21%, 나쁜 10%는 −50%였습니다."),
)


def live_score_block(ls: Optional[dict]) -> str:
    """실전 기록 채점: 기간이 지난 예측의 범위 적중률과 사건 확률 대 실제 빈도."""
    if not ls:
        return ""
    rows = ls.get("horizons") or []
    if not rows:
        return ui.note(f"기간이 다 지난 예측이 아직 없습니다(대기 {ls.get('pending', 0)}건). 첫 채점은 기록 시작 약 1개월 뒤입니다.")
    names = {"up": "오름", "dd15": "15%↓", "beat": "시장↑"}
    body = ""
    for r in rows:
        ev = " · ".join(f"{names.get(k, k)} 예측 {_p(e['mean_p'])} / 실제 {_p(e['freq'])}" for k, e in r["events"].items())
        body += (f'<tr><td>{E(H_LABEL.get(r["h"], str(r["h"])))}</td><td>{r["n"]}</td><td>{E(_p(r["coverage80"]))}</td>'
                 f'<td style="text-align:left">{E(ev)}</td></tr>')
    return ('<table class="tbl"><tr><th>기간</th><th>건수</th><th>범위 적중(목표 80%)</th><th>확률: 예측 평균 / 실제 빈도</th></tr>' + body + "</table>"
            + ui.note("겹치는 날짜의 예측은 서로 독립이 아니어서, 건수가 많아 보여도 근거는 그보다 적습니다."))


def render_body(data: dict) -> str:
    snap = data.get("snap")
    if not snap:
        return (ui.verdict("muted", "판단판이 아직 없습니다", "자동 잡 decision_desk 가 화~토 아침에 만듭니다.")
                + ui.callout("지금 만들려면 VM 에서 <code>python scripts/decision_desk.py</code> 를 실행합니다."))
    parts = [STYLE]
    if snap.get("status") != "ok":
        parts.append(ui.verdict("warn", "판단판을 만들지 못했습니다", snap.get("message", "")))
        if snap.get("crash"):
            parts.append(ui.section("급락 상황", "".join(ui.note(line) for line in snap["crash"])))
        return "".join(parts)
    model = snap.get("model") or {}
    sub = f"모형 {model.get('study', '—')} · 학습 자료 {model.get('data_end', '—')}까지 · 만든 시각 {str(snap.get('generated_at', ''))[:16].replace('T', ' ')} UTC"
    parts.append(ui.verdict("info", f"기준일 {snap.get('asof', '—')}", sub))
    if model.get("smoke"):
        parts.append(ui.callout("가짜 자료로 만든 시험용 모형입니다. 숫자에 뜻이 없습니다.", icon="⚠", tone="warn"))
    parts.append(ui.callout(E(snap.get("note", dd.NOTE)) + " 괄호 안은 과거 평균입니다.", icon="ℹ"))
    parts.append(ui.section("시장 (SPY)", asset_block(snap["market"], open_=True)))
    if snap.get("crash"):
        parts.append(ui.section("급락 상황", "".join(ui.note(line) for line in snap["crash"])))
    if snap.get("portfolio"):
        parts.append(ui.section("내 포트폴리오 전체", asset_block(snap["portfolio"], open_=True)
                                + ui.note("지금 비중을 계속 유지했다고 놓고 만든 가격 이력으로 읽은 값입니다. 현금은 넣지 않았습니다.")))
    if snap.get("positions"):
        parts.append(ui.section(f"보유 종목 {len(snap['positions'])}", "".join(asset_block(sh) for sh in snap["positions"])))
    if snap.get("watch"):
        parts.append(ui.section(f"관심 종목 {len(snap['watch'])}", "".join(asset_block(sh) for sh in snap["watch"])))
    if snap.get("live_score"):
        parts.append(ui.section("실전 기록 (이 화면이 낸 예측의 채점)", live_score_block(snap["live_score"])))
    parts.append(ui.section("읽는 법", ui.kv_table((k, E(v)) for k, v in HOW_TO)))
    return "".join(parts)
