"""무디스 AAA·BAA 월별 수익률 스냅숏 만들기 (crash-cycle-lab, 설계 3.4 절). 작업이 아니다 — 실행기·테스트는 부르지 않는다.

python research/jobs/crash-cycle-lab/build_moodys_snapshot.py

- 출처: FRED 공개 CSV(키 불필요) https://fred.stlouisfed.org/graph/fredgraph.csv?id=AAA , ...?id=BAA
- 출력: research/jobs/crash-cycle-lab/data/moodys_monthly.csv (머리줄 month,AAA,BAA · 값은 % 그대로 · 달 오름차순)
- 받은 날짜·행 수·sha256 을 출력한다 → SPEC.md '자료 출처' 절에 적는다.
- 연구 작업은 이 커밋된 파일만 읽고 네트워크를 쓰지 않는다.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import urllib.request
from pathlib import Path

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
UA = "Mozilla/5.0 (quant research)"
OUT = Path(__file__).resolve().parent / "data" / "moodys_monthly.csv"


def fetch(sid: str) -> dict[str, str]:
    req = urllib.request.Request(URL.format(sid=sid), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        text = resp.read().decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    out: dict[str, str] = {}
    for r in rows:
        date = r.get("observation_date") or r.get("DATE")
        val = (r.get(sid) or "").strip()
        if not date or val in ("", "."):
            continue
        out[date[:7]] = val
    return out


def _next_month(m: str) -> str:
    y, mo = int(m[:4]), int(m[5:7])
    y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    return f"{y:04d}-{mo:02d}"


def main() -> int:
    aaa, baa = fetch("AAA"), fetch("BAA")
    months = sorted(set(aaa) & set(baa))
    assert months and months[0] == "1919-01", f"첫 달이 1919-01 이 아님: {months[:1]}"
    m = months[0]
    for k in months[1:]:
        m = _next_month(m)
        assert k == m, f"빠진 달: {m}"
    assert all(float(aaa[k]) > 0 and float(baa[k]) > 0 for k in months), "양수가 아닌 값"
    assert months[-1] >= "2026-08", f"마지막 달이 2026-08 보다 이름: {months[-1]}"
    lines = ["month,AAA,BAA"] + [f"{k},{aaa[k]},{baa[k]}" for k in months]
    data = ("\n".join(lines) + "\n").encode("utf-8")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".csv.tmp")
    tmp.write_bytes(data)
    tmp.replace(OUT)
    print(f"downloaded {dt.date.today().isoformat()} · rows {len(months)} · first {months[0]} · last {months[-1]} · "
          f"sha256 {hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
