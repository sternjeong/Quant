"""VM의 실시간 CPU 부하·여유 메모리를 확인해, 지금 무거운 작업 하나를 더 시작해도 되는지 판단한다.

배경: 이 저장소는 작은 Oracle Always-Free VM(여기서는 2 OCPU/12GB) 위에서 서로 독립적인 프로세스
여러 개가 각자 알아서 스케줄을 돌린다 — 지금은 Telegram 큐(deploy/codex_telegram/runner.py, 자체
has_capacity()로 이미 리소스를 확인함)와 스케줄러(scheduler/run_scheduler.py — 현재 이 모듈을 쓰는 곳은
07:30 daily_news_digest_job)다. (이 모듈을 만들 당시에는 2주 실험 감독기 deploy/experiment_supervisor.py
(2026-09-25 삭제)와 야간 미세튜닝 strategy_nightly_tuning_job(00:05~04:00 반복 백테스트, 2026-09-24
삭제)도 함께 돌았다.) 서로 존재를 모르기 때문에, 우연히 같은 시간대에 다 같이 무거운 작업을 돌리면 VM이
버티지 못할 수 있다. 이 모듈은 OS가 이미 알고 있는 전역 지표(부하 평균·여유 메모리)를 기준으로
판단하므로, 프로세스 간 별도의 락 파일이나 IPC 없이도 자연스럽게 서로 양보하게 된다.

deploy/codex_telegram/runner.py는 의도적으로 stdlib만 쓰는 독립 스크립트라(시스템 python3로 실행,
이 저장소의 venv/의존성 없이 동작해야 함) core/를 임포트하지 않는다 — 그래서 이 로직은 그 파일 안에
똑같이 작게 복제되어 있다(deploy/ 아래 다른 stdlib 전용 스크립트들도 env-file 파서 등 작은 헬퍼를 이런
식으로 중복해서 갖고 있다). 이 모듈은 core/*를 이미 정상적으로
임포트하는 scheduler/run_scheduler.py처럼, 프로젝트 venv 안에서 도는 코드 전용이다.
"""

import os
from typing import Optional


def available_memory_mb() -> Optional[float]:
    """`/proc/meminfo`의 MemAvailable(회수 가능한 페이지캐시까지 반영된 실사용 가능 메모리, KB)을
    MB로 반환한다. 리눅스가 아니거나 읽기 실패 시 None."""
    try:
        with open('/proc/meminfo') as meminfo:
            for line in meminfo:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) / 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def has_headroom(max_load_per_cpu: float = 1.5, min_free_memory_mb: float = 1024) -> bool:
    """1분 부하 평균이 `코어 수 * max_load_per_cpu`를 넘지 않고, 여유 메모리가
    `min_free_memory_mb` 이상이면 True. 둘 중 하나라도 확인할 수 없으면(예: 리눅스가 아님) 그
    기준은 통과한 것으로 본다 — 이 함수의 목적은 실제로 빠듯할 때 한 박자 쉬어가는 것이지, 판단이
    안 될 때 무조건 막는 게 아니다."""
    try:
        load1 = os.getloadavg()[0]
    except OSError:
        load1 = 0.0
    cpu_count = os.cpu_count() or 1
    if load1 >= cpu_count * max_load_per_cpu:
        return False
    available = available_memory_mb()
    if available is not None and available < min_free_memory_mb:
        return False
    return True
