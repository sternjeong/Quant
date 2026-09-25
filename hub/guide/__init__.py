"""Quant VM 관제 센터의 사용 설명서.

새 화면·자동 잡·core 모듈·스크립트를 추가하거나 지울 때는 이 패키지의 content_*.py 도 함께 고친다.
빠뜨리면 tests/test_hub_guide.py 가 실패하고, 자동배포의 테스트 관문이 배포를 막는다(AGENTS.md 참고).
"""

from __future__ import annotations

from hub.guide.schema import GuideContent


def build_content() -> GuideContent:
    from hub.guide import content_modules_a as ma
    from hub.guide import content_modules_b as mb
    from hub.guide import content_ops as ops
    from hub.guide import content_pages_a as pa
    from hub.guide import content_pages_b as pb

    return GuideContent(
        pages=tuple(pa.PAGES) + tuple(pb.PAGES),
        modules=tuple(ma.MODULES) + tuple(mb.MODULES),
        internal_modules={**ma.INTERNAL, **mb.INTERNAL},
        scripts=tuple(ops.SCRIPTS),
        internal_scripts=dict(ops.INTERNAL_SCRIPTS),
        jobs=tuple(ops.JOBS),
        glossary=tuple(ops.GLOSSARY),
        routines=tuple(ops.ROUTINES),
        ops=tuple(ops.OPS),
        start_here=tuple(ops.START_HERE),
    )


def render_guide_page() -> str:
    from hub.guide.render import render_guide

    return render_guide(build_content())
