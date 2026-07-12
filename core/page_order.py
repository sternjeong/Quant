"""app/pages/ 안의 Streamlit 페이지 파일을 사이드바 노출 순서대로 재정렬하는 유틸.

Streamlit 멀티페이지 앱은 `app/pages/*.py` 파일명 맨 앞의 숫자로 사이드바 노출 순서를 정한다
(README.md "개발 컨벤션" 참고: `{순번}_{한글이름}.py`). 즉 사이드바 순서를 바꾸려면 실제로
파일명을 바꿔야 하므로, 이 모듈이 그 파일명 변경을 중간 충돌 없이(2단계 rename) 수행한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_PAGE_RE = re.compile(r"^(\d+)_(.+)\.py$")


@dataclass
class PageEntry:
    filename: str  # 전체 파일명, 예: "1_백테스팅.py"
    order: int  # 파일명 맨 앞 숫자
    label: str  # 숫자/확장자를 뗀 표시용 이름 (밑줄은 공백으로), 예: "백테스팅"


def list_pages(pages_dir: Path) -> list[PageEntry]:
    """`{숫자}_{이름}.py` 형식에 맞는 파일만 순서대로 정리해 반환한다."""
    entries = []
    for f in pages_dir.glob("*.py"):
        m = _PAGE_RE.match(f.name)
        if not m:
            continue
        entries.append(PageEntry(filename=f.name, order=int(m.group(1)), label=m.group(2).replace("_", " ")))
    entries.sort(key=lambda e: (e.order, e.filename))
    return entries


def reorder_pages(pages_dir: Path, ordered_filenames: list[str]) -> None:
    """ordered_filenames 순서대로 1,2,3... 접두어를 다시 붙인다.

    한 번에 여러 파일명이 바뀌므로, 중간 과정에서 두 파일이 같은 이름을 갖는 충돌을 피하기 위해
    먼저 전부 임시 이름으로 옮긴 뒤(1단계) 최종 이름으로 옮긴다(2단계).
    """
    temp_entries: list[tuple[Path, str]] = []
    for filename in ordered_filenames:
        src = pages_dir / filename
        tmp = pages_dir / f"__reorder_tmp__{filename}"
        src.rename(tmp)
        temp_entries.append((tmp, filename))

    for i, (tmp, original_name) in enumerate(temp_entries, start=1):
        m = _PAGE_RE.match(original_name)
        suffix = m.group(2)
        tmp.rename(pages_dir / f"{i}_{suffix}.py")


def move_page(pages_dir: Path, filename: str, direction: str) -> None:
    """filename 페이지를 direction("top"/"up"/"down"/"bottom")으로 옮기고 즉시 재정렬한다."""
    entries = list_pages(pages_dir)
    names = [e.filename for e in entries]
    idx = names.index(filename)

    if direction == "up" and idx > 0:
        names[idx - 1], names[idx] = names[idx], names[idx - 1]
    elif direction == "down" and idx < len(names) - 1:
        names[idx + 1], names[idx] = names[idx], names[idx + 1]
    elif direction == "top" and idx > 0:
        names.pop(idx)
        names.insert(0, filename)
    elif direction == "bottom" and idx < len(names) - 1:
        names.pop(idx)
        names.append(filename)
    else:
        return

    reorder_pages(pages_dir, names)
