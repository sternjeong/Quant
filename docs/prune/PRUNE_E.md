# PRUNE_E — 2주 실험 슈퍼바이저 삭제 (2026-09-25)

사용자 결정: 삭제 추천(재개 계획 없을 때)에 "추천대로" 승인, VM에서 서비스를 먼저 멈춘 것을 확인한 뒤 진행.

## 삭제 전 절차 (파일만 지우면 안 되는 이유)
- 유닛이 `Restart=always`, `RestartSec=30`이라 파일이 사라지면 VM에서 30초마다 시작 실패를 반복한다.
- 그래서 사용자가 VM에서 `sudo systemctl disable --now quant-experiment-supervisor`를 실행했고 `inactive`를 확인했다.

## 삭제 파일
| 경로 | 복구 |
|---|---|
| deploy/experiment_supervisor.py | `git show e2c32dd:deploy/experiment_supervisor.py` |
| deploy/test_experiment_supervisor.py | `git show e2c32dd:deploy/test_experiment_supervisor.py` |
| deploy/quant-experiment-supervisor.service | `git show e2c32dd:deploy/quant-experiment-supervisor.service` |

## 함께 고친 곳 (안 고치면 깨지는 것)
- `deploy/auto_deploy.sh`: 테스트 관문이 `test_experiment_supervisor`를 실행했다. 파일 삭제 후에도 남기면 관문이 실패해 **자동 배포가 막힌다** → 해당 실행 블록 제거.
- `hub/apps_registry.py`: 관제 센터 앱 목록의 슈퍼바이저 슬롯 제거, 스케줄러 설명에서 삭제된 "나이틀리 튜닝" 문구 정정.
- `deploy/codex_telegram/README.md`, `deploy/DEPLOYMENT_ORACLE.md`: 설명 정정.

## 남긴 것
- `.experiment-control/`, `docs/experiment_validation/`, `docs/TWO_WEEK_STRATEGY_VALIDATION_PROTOCOL.md`: 백업 대상이고 텔레그램 러너(`deploy/codex_telegram/runner.py`)와 백업(`deploy/backup_vm.py`)이 참조한다. 사람 검증 대기 표본도 여기에 있다.
- 코드 주석 속 `experiment_supervisor.py` 언급(core/champion_strategy.py, core/resource_guard.py, scheduler/run_scheduler.py, deploy/checkpoint_notify.py): 동작에 영향 없는 과거 설명이라 그대로 둠.
