"""설명서 누락 점검 — `python -m hub.guide.check` 로 무엇을 더 써야 하는지 목록으로 본다(내용 작성자용).

tests/test_hub_guide.py 의 coverage 테스트와 같은 규칙을 쓴다. 종료 코드 0 이면 빠진 것이 없다.
"""

from __future__ import annotations

import sys
from pathlib import Path

from hub.guide import build_content, live
from hub.guide.schema import PROJECT_ROOT, GuideContent, validate_entries


def _py_files(directory: str) -> set[str]:
    return {f"{directory}/{p.name}" for p in (PROJECT_ROOT / directory).glob("*.py") if p.name != "__init__.py"}


def coverage_problems(content: GuideContent) -> dict[str, list[str]]:
    """{분류: [빠진/남은 항목]} — 비어 있지 않은 분류만 담는다."""
    out: dict[str, list[str]] = {}

    nav = live.navigation_paths()
    have_pages = {p.path for p in content.pages}
    if nav - have_pages:
        out["설명이 없는 화면"] = sorted(nav - have_pages)
    if have_pages - nav:
        out["사라진 화면의 설명(지우세요)"] = sorted(have_pages - nav)

    core = _py_files("core")
    documented = {m.module for m in content.modules}
    internal = set(content.internal_modules)
    both = documented & internal
    if both:
        out["모듈이 설명과 내부 목록에 동시에 있음"] = sorted(both)
    if core - documented - internal:
        out["설명도 내부 분류도 없는 core 모듈"] = sorted(core - documented - internal)
    if (documented | internal) - core:
        out["사라진 core 모듈의 설명(지우세요)"] = sorted((documented | internal) - core)

    scripts = _py_files("scripts")
    doc_scripts = {s.path for s in content.scripts}
    int_scripts = set(content.internal_scripts)
    if scripts - doc_scripts - int_scripts:
        out["설명도 내부 분류도 없는 scripts"] = sorted(scripts - doc_scripts - int_scripts)
    gone = {s for s in (doc_scripts | int_scripts) if not (PROJECT_ROOT / s).exists()}
    if gone:
        out["사라진 스크립트의 설명(지우세요)"] = sorted(gone)

    jobs = live.job_ids()
    have_jobs = {j.job_id for j in content.jobs}
    if jobs - have_jobs:
        out["결과 보는 곳 설명이 없는 자동 잡"] = sorted(jobs - have_jobs)
    if have_jobs - jobs:
        out["사라진 잡의 설명(지우세요)"] = sorted(have_jobs - jobs)

    bad_related = sorted(
        f"{p.path} -> {j}" for p in content.pages for j in p.related_jobs if j not in jobs
    )
    if bad_related:
        out["화면이 가리키는 잡이 존재하지 않음"] = bad_related

    from core.process_registry import PROCESS_REGISTRY
    from core.job_schedule import SCHEDULED_JOBS

    no_desc = sorted(j.job_id for j in SCHEDULED_JOBS
                     if not str(PROCESS_REGISTRY.get(j.process_key, {}).get("description", "")).strip())
    if no_desc:
        out["레지스트리에 설명이 없는 잡"] = no_desc
    return out


def main() -> int:
    content = build_content()
    problems = validate_entries(content)
    cov = coverage_problems(content)
    if problems:
        print("[형식 문제]")
        print("\n".join(f"  - {p}" for p in problems))
    for title, items in cov.items():
        print(f"[{title}] {len(items)}개")
        print("\n".join(f"  - {i}" for i in items))
    if not problems and not cov:
        print("빠진 설명이 없습니다.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
