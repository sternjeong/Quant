"""월별 point-in-time 새틀라이트 선정(2008-01 ~ 2026-06, 222개월)을 체크포인트하며 계산.
사용: python step0_picks.py <worker_id> <n_workers>  (워커별 picks_part{id}.json, 재시작 시 건너뜀)"""
import json
import sys
import time

from common import HERE, _pick_satellite_at_date, month_first_days, trading_index, load_picks

wid, nw = int(sys.argv[1]), int(sys.argv[2])
out_f = HERE / f"picks_part{wid}.json"
done = load_picks()
mine = json.loads(out_f.read_text(encoding="utf-8")) if out_f.exists() else {}
dates = [d for i, d in enumerate(month_first_days(trading_index())) if i % nw == wid]
for d in dates:
    k = str(d.date())
    if k in done:
        continue
    t0 = time.time()
    info = _pick_satellite_at_date(d)
    mine[k] = {"picks": info["picks"], "weights": info["weights"], "pool_size": info["pool_size"],
               "n_with_history": info["n_with_history"], "n_active_trend": info["n_active_trend"]}
    out_f.write_text(json.dumps(mine, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    print(f"[w{wid}] {k} {info['picks']} hist={info['n_with_history']} act={info['n_active_trend']} {time.time()-t0:.0f}s", flush=True)
print(f"[w{wid}] done", flush=True)
