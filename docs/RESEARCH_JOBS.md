# 검증 연구 작업 실행기 — 작업 계약과 운영

사전 등록 검증 연구(백테스트 + 코드로 고정한 판정 규칙)를 **VM 에서 사람 손 없이** 돌리는 방법이다.
연구 에이전트는 이 문서대로 스크립트와 `job.json` 을 만든다. 실행기 코드는 `core/research_jobs.py`,
스케줄러 잡은 `research_job_runner`(scheduler/run_scheduler.py), 관리 도구는 `scripts/research_jobs_admin.py` 다.
계산에는 AI 가 필요 없다. 실행기는 AI 를 부르지 않으며 주문 경로와 연결되어 있지 않다.

## 1. 작업 정의: `research/jobs/<id>/job.json`

저장소에 커밋한다(main 에 병합되어야 VM 이 본다). 폴더 이름과 `id` 가 같아야 한다.

| 필드 | 형식 | 뜻 |
|---|---|---|
| `id` | 문자열 `[a-z0-9][a-z0-9._-]{0,63}` | 작업 이름(폴더 이름과 같아야 함) |
| `title` | 문자열 | 텔레그램·관제 센터에 보이는 제목 |
| `entrypoint` | 저장소 루트 기준 `.py` 경로 | 실행할 스크립트(`..` 금지, 파일이 있어야 함) |
| `args` | 문자열 목록 | 스크립트 인자. `--out`/`--checkpoint` 는 넣지 않는다(실행기가 붙인다) |
| `timeout_seconds` | 정수 60~10800 | 한 번 실행의 상한. 실제 예산은 창의 남은 시간으로 더 줄어들 수 있다 |
| `max_attempts` | 정수 1~10 | 실패(아래 4절)를 몇 번까지 다시 시도할지. 도달하면 `failed` |
| `resumable` | true/false | 체크포인트로 이어서 계산할 수 있는가 |
| `outputs` | 상대 경로 목록(비어 있으면 안 됨) | `--out` 아래에 반드시 생겨야 하는 결과 파일. 예: `["results.json", "REPORT.md"]` |
| `summary_from` | 키 경로 문자열 또는 null | 텔레그램 요약에 쓸 결과 JSON 의 키(점으로 구분, 예: `verdicts`). 기본 파일은 `outputs` 의 첫 `.json`. 다른 파일이면 `"results.json:verdicts"` |
| `priority` | 정수 -1000~1000 | **작을수록 먼저**. 같으면 id 순 |
| `revision` (선택) | 정수/문자열, 기본 1 | 바꾸면 상태·체크포인트를 버리고 처음부터 다시 돈다(결과가 이미 있어도) |
| `max_memory_mb` (선택) | 정수 256~10240, 기본 10240 | 자식 프로세스 트리 RSS 상한. 실제 상한은 VM 총 메모리의 80%와 이 값 중 작은 쪽 |
| `max_disk_mb` (선택) | 정수, 기본 2048 | 작업 폴더(out+checkpoint) 크기 상한 |
| `max_runs` (선택) | 정수 1~500, 기본 60 | 종료 코드 3 을 이만큼 반복해도 안 끝나면 실패 |

규칙: `resumable: false` 작업의 `timeout_seconds` 는 가장 긴 실행 창(11시간 40분 − 2분; 작업 정의 상한 3시간이 먼저 걸린다)보다 짧아야 하고,
한 번에 끝낼 시간이 남은 회차에만 시작한다. 계약을 어긴 job.json 은 `invalid` 로 표시되고 텔레그램으로 한 번 알린다.

예시(`research/jobs/smoke-noop/job.json` — 실제 스모크 작업):

```json
{
  "id": "smoke-noop",
  "title": "실행기 스모크(계산 없음)",
  "entrypoint": "research/jobs/smoke-noop/run.py",
  "args": ["--steps", "4", "--steps-per-run", "2"],
  "timeout_seconds": 300,
  "max_attempts": 2,
  "resumable": true,
  "outputs": ["results.json", "REPORT.md"],
  "summary_from": "verdicts",
  "priority": 900,
  "revision": 1
}
```

## 2. 스크립트 계약

실행 방식(작업 디렉터리 = 저장소 루트, 프로젝트 venv 의 python):

```
python <entrypoint> <args...> --out <출력 디렉터리> --checkpoint <체크포인트 디렉터리>
```

- `--out`: `outputs` 에 적은 파일을 여기에 쓴다. 재개 작업이면 실행 사이에 유지된다.
- `--checkpoint`: 중간 결과를 여기에 저장하고, 다시 실행되면 여기서 읽어 **이어서** 계산한다.
  쓰기는 원자적으로(임시 파일에 쓰고 `rename`) 해서 중간에 죽어도 깨지지 않게 한다.
- `--smoke` (연구 스크립트 관례): 작은 데이터·짧은 기간으로 몇 초~몇 분 안에 끝까지 도는 확인 모드.
  Codespace·대화 세션에서는 이것만 돌린다. 실행기는 `--smoke` 를 붙이지 않는다(필요하면 `args` 에 넣지 말 것).

종료 코드:

| 코드 | 뜻 | 실행기 처리 |
|---|---|---|
| `0` | 완료 | `outputs` 가 모두 있으면 `done`. 하나라도 없으면 실패로 센다 |
| `3` | 진행 중 — 시간이 부족해 체크포인트를 저장하고 정상 중단 | `in_progress`, 다음 회차에 이어서 실행(실패로 세지 않음) |
| 그 외 | 실패 | 실패 수 +1, `max_attempts` 전이면 다음 회차에 다시 시도 |

시간 예산: 실행기는 환경 변수로 이번 실행의 예산을 알려 준다. 스크립트는 이것을 보고 **스스로** 체크포인트를 저장하고 3 으로 끝나야 한다.

- `RESEARCH_JOB_DEADLINE_EPOCH`: 이 시각(유닉스 초)까지 끝나야 한다(여유를 30초 이상 두라).
- `RESEARCH_JOB_TIME_BUDGET_SECONDS`: 이번 실행 예산(초).
- `RESEARCH_JOB_ID`: 작업 id.

예산이 지나면 실행기가 프로세스 그룹에 SIGTERM 을 보내고 30초 뒤 SIGKILL 한다. SIGTERM 을 받아 체크포인트를 저장하고
3 으로 끝나면 정상 진행으로 본다. 재개 작업이 창 끝 때문에 강제로 끊기면 `in_progress`(실패 아님)로, 그 밖의 시간 초과는 실패로 센다.

판정: 판정 규칙(통과 기준·유의 수준·비교 대상)은 **결과를 보기 전에** 코드와 문서에 고정하고 이후 바꾸지 않는다.
`results.json` 에 `verdicts`(예: `{"H1_late_entry": "FAIL", ...}`)처럼 기계가 읽을 판정을 넣고, `REPORT.md` 에 사람이 읽을 설명을 쓴다.
결과 파일에 키·토큰·개인정보를 넣지 않는다(비밀처럼 보이는 파일은 저장소 반영에서 빠진다).

네트워크: 스크립트는 VM 의 `.env` 환경을 그대로 받는다. 가능하면 저장소·캐시에 있는 데이터만 쓰고, 외부 API 는 최소로.

## 3. 언제·어떻게 도나 (VM 부하 보호)

- 실행 창(KST, 2026-10-08 부터 하루 종일): **01:00~02:50 · 07:45~08:55 · 09:30~11:55 · 12:15~23:55**. 10분마다(:00, :10 … :50) 깨어나고, 창 밖 회차는 바로 끝난다.
  비워 둔 곳: 00:00~01:00 야간 잡 블록, 02:50~07:45(03:00~05:50 에이전트 배치, 06:10 paper 주문, 06:30 백업, 06:40 새벽 미리 계산, 07:30 뉴스),
  08:55~09:30(09:00 대회 알림·09:01 아침 재추천·09:05 워치독), 11:55~12:15(12:00 거장 동기화). VM 부하(`has_headroom`)가 높거나 자동 배포의 테스트 관문
  (`/opt/quant-deploy-staging` 존재)이 도는 동안은 쉰다. 그래서 대기 연구가 있으면 끝나는 즉시 다음 작업이 이어진다.
- 한 번에 한 작업(파일 락 + 스케줄러 max_instances=1). 대기 작업 중 `priority` 가 가장 작은 것부터.
- 시작 전: VM 여유 확인(`core.resource_guard.has_headroom` — 부하·여유 메모리), 시스템 총 메모리의 20% 예약, 여유 디스크 2GB 이상.
- 예산: `min(timeout_seconds, 창 끝 − 지금 − 2분)`. 5분 미만이면 그 회차는 시작하지 않는다.
- 자식은 `nice 5` + `ionice -c 3`(가능하면), 자기 세션(프로세스 그룹)으로 실행. CPU 전체 사용률이 80% 이상이면 자식 그룹을 일시 중지하고 70% 이하로 내려오면 재개해 다른 VM 서비스에 CPU 여유를 둔다(5초 감시라 순간 초과는 가능).
- 자식 RSS는 VM 총 메모리의 최대 80%로 제한한다. 실행 중 시스템 가용 메모리가 총 메모리의 20%(최소 600MB) 아래면 양보하고, 30초마다 디스크(작업 폴더 상한, 여유 1GB 미만이면 양보)를 확인한다.
  양보(시스템 부족)는 실패로 세지 않는다.
- 스케줄러가 재시작되거나(자동 배포) VM 이 재부팅되면 자식도 함께 끝난다. 다음 회차가 남아 있던 `running` 을
  `in_progress`(재개 작업) 또는 `pending` 으로 되돌린다. 6번 넘게 끊기면 `failed`.
- 결과를 저장소에 push 하면 자동 배포가 스케줄러를 재시작하므로, 그 뒤 12분 동안은 새 작업을 시작하지 않는다.

상태 파일: `data/research_jobs/state.json`(원자적 쓰기) — 작업마다 status(`pending`/`running`/`in_progress`/`done`/`failed`/`cancelled`/`invalid`),
실패 수, 실행 수, 끊김 수, 마지막 시작·종료·소요, 종료 코드, 사유, 로그 꼬리(비밀 가림). 로그는 `data/research_jobs/logs/<id>/`(최근 5개),
작업 폴더는 `data/research_jobs/work/<id>/{out,checkpoint}`(완료되면 지움).

- 대기 작업이 하나도 없는 회차에는 새틀라이트 R&D 센터 계산기(`scripts/satellite_lab_worker.py`)를 같은 보호 장치로 돌린다
  (사전 등록 연구가 언제나 먼저, 설계는 [SATELLITE_LAB.md](./SATELLITE_LAB.md)). 상태는 `state.json` 의 `satellite_lab` 절.
  끄려면 스케줄러 환경에 `RESEARCH_SATELLITE_LAB=0`.
- 대기 연구가 계속 있어도 새틀라이트 R&D 는 20시간에 한 번 차례를 받는다. (2주 스프린트 별도 창은 2026-10-08 하루 종일 창으로 대체되어 없앴다.)

## 4. 결과가 사용자에게 가는 길

1. **텔레그램 1건**: `[검증 연구 결과] <제목> — 완료` + `summary_from` 판정 요약(최대 8줄) + 결과 위치와 저장소 반영 여부.
   실패는 사유 한 줄. 같은 사유의 반복 실패는 다시 알리지 않고, 마지막(재시도 중단) 실패는 항상 알린다. 진행 중(3)은 알리지 않는다.
2. **VM 보관 + 관제 센터**: `data/research_results/<id>/` 에 `outputs` 를 보관하고 `data/research_results/index.html` 을 다시 만든다.
   관제 센터(허브) '연구·검증' 묶음의 **'검증 연구 결과'** 카드가 이 페이지를 보여 준다(작업별 상태·요약·REPORT.md 본문·실패 로그 끝부분).
3. **저장소 반영**: `outputs` 중 작은 텍스트(.json/.md/.csv/.txt, 파일당 256KB·합계 1MB 이하, 비밀처럼 보이지 않는 것)만
   `research/results/<id>/` 경로로 **origin/main 에 커밋 하나를 얹어** push 한다. VM 작업트리·HEAD·인덱스는 건드리지 않는다
   (임시 인덱스 + `hash-object`/`commit-tree`, deploy/codex_telegram/runner.py 의 `/progress` 와 같은 원리). 그 사이 누가 push 해서
   fast-forward 가 안 되면 다시 fetch 해서 3번까지 시도하고, 그래도 안 되면 포기하고 알림에 적는다. VM 에 push 권한이 없으면
   그 사실을 알림에 적고 1·2 만 한다. 이 경로는 어떤 코드도 import 하지 않으므로 자동 배포 테스트 관문에 영향이 없다.
   끄려면 스케줄러 환경에 `RESEARCH_JOBS_PUBLISH=0`.

엔진(챔피언 전략 등) 반영은 결과를 본 **사용자 확인 뒤** 별도 작업으로 한다. 실행기는 결과를 전달할 뿐이다.

## 5. 사람 조작

- 켜기/끄기: 텔레그램 `/processes` 의 연구 묶음 '검증 연구 작업 실행기', 또는 관제 센터 '백그라운드 스케줄러' 카드(키 `research_job_runner`, 기본 켜짐).
- 상태·재시도·취소(VM 에서, 또는 텔레그램 `/claude` 에이전트에게 실행을 맡겨서):

```
python scripts/research_jobs_admin.py list
python scripts/research_jobs_admin.py retry <id>            # 실패·취소·완료 작업을 대기로(실패 수 0). 재개 작업은 체크포인트에서
python scripts/research_jobs_admin.py retry <id> --fresh    # 체크포인트까지 지우고 처음부터
python scripts/research_jobs_admin.py cancel <id>           # 대기면 즉시 취소, 실행 중이면 몇 초 안에 중단
```

VM 에서는 `/opt/quant` 에서 `sudo -u quant /opt/quant/.venv/bin/python scripts/research_jobs_admin.py list` 처럼 quant 계정으로 실행한다
(상태 파일 소유자가 quant 다).

## 6. 새 연구를 올리는 순서 (연구 에이전트용)

1. `research/jobs/<id>/run.py`(또는 다른 위치의 스크립트) + `job.json` 을 이 계약대로 만든다. 판정 규칙을 먼저 코드·문서에 고정한다.
2. Codespace·대화 세션에서는 `python <entrypoint> <args> --smoke --out /tmp/x/out --checkpoint /tmp/x/ckpt` 로 스모크만 돌린다
   (전체 계산 금지). 가능하면 재개 동작도 확인한다(두 번 실행해 3 → 0).
3. `python -m pytest tests -q` 통과 후 브랜치를 push 하고 main 병합을 요청한다. main 에 들어가면 다음 실행 창에서 VM 이 돈다.
4. 결과는 텔레그램·관제 센터·`research/results/<id>/` 로 받는다. 판정을 바꾸고 싶어지면 새 `revision` 이 아니라 새 사전 등록(새 id)으로 한다.

## 7. 이어받기(Codespace 없이)

Codespace 가 꺼져 연구 브랜치가 main 에 병합되지 못한 채 남아 있으면, 사용자가 폰의 텔레그램에서 VM 의 `/claude` 에이전트에게 병합을 맡긴다.

### 텔레그램에 그대로 붙여 넣을 지시문

```
/claude docs/RESEARCH_JOBS.md 이어받기 절차대로 origin 의 미병합 연구 브랜치를 확인하고 스모크·테스트 통과한 것만 main 에 병합해
```

상태만 보고 싶을 때:

```
/claude docs/RESEARCH_JOBS.md 5절대로 python scripts/research_jobs_admin.py list 결과를 알려줘(아무것도 바꾸지 마)
```

재시도시킬 때:

```
/claude docs/RESEARCH_JOBS.md 5절대로 연구 작업 <id> 를 retry 해줘(코드 변경·커밋 없이)
```

(텔레그램에서 저장소를 묻는 버튼이 나오면 Quant 를 고른다. `/project quant` 다음 줄에 지시를 적어도 된다.)

### 에이전트가 따를 절차

1. `git fetch origin` 후 `git branch -r --no-merged origin/main` 으로 미병합 브랜치를 찾는다. 이 중 `research/jobs/` 에 `job.json` 을 추가·수정한 브랜치만 대상이다.
2. **`/opt/quant` 작업트리에서 브랜치를 checkout·stash·reset 하지 않는다**(라이브 서비스가 도는 폴더이고 자동 배포가 쓴다).
   별도 작업 폴더를 쓴다: `git -C /opt/quant worktree add /opt/projects/quant-merge-<브랜치> origin/<브랜치>` 또는 `/opt/projects` 아래 새 clone.
3. 그 폴더에서: job.json 이 1절 계약을 지키는지(`python -c "from core.research_jobs import load_job_definitions, Config; ..."` 또는 `scripts/research_jobs_admin.py list` 로 invalid 여부),
   각 새 작업의 `--smoke` 실행이 0 으로 끝나는지, `python -m pytest tests -q` 와 `cd deploy/codex_telegram && python3 -m unittest test_runner` 가 통과하는지 확인한다.
4. 모두 통과한 브랜치만 main 에 병합한다: 그 폴더에서 `git checkout -B merge-tmp origin/main && git merge --no-ff origin/<브랜치>` → 테스트 한 번 더 → `git push origin merge-tmp:main`.
   충돌이 나거나 테스트가 실패하면 병합하지 않고 이유를 보고한다(강제 push 금지). 판정 규칙·결과 파일을 고치지 않는다.
5. 끝나면 `git worktree remove` 로 작업 폴더를 정리하고, 병합한 브랜치·건너뛴 브랜치와 이유를 텔레그램 최종 응답으로 요약한다.
   main 에 들어간 작업은 다음 실행 창(01:00 또는 13:00 KST)에 실행기가 집어 간다.

### 실제로 되는 것과 안 되는 것 (deploy/codex_telegram/runner.py 기준, 2026-09-27 코드 확인)

- 된다: `/claude` 지시는 VM 에서 Claude CLI 를 `--dangerously-skip-permissions` 로, 설정의 프로젝트 폴더(예시 설정: quant → `/opt/quant`)에서 실행한다.
  작업 프롬프트(deploy/codex_telegram/worker_prompt.md)가 끝에 commit + push 를 요구하므로 git 조작과 push 를 할 수 있다.
  러너의 `/progress` 가 같은 VM 에서 origin main 으로 push 하므로 VM 에 push 자격이 있는 구성이 전제다.
- 확인 필요: VM 의 Claude CLI 로그인 상태와 사용량 한도(한도에 걸리면 작업이 멈추고 다음에 이어진다), VM 의 실제 push 권한(이 문서 작성 시 VM 에서 직접 확인하지 않음).
- 안 된다/하지 않는다: 러너 자체에는 '미병합 브랜치 자동 병합' 기능이 없다 — 사람이 위 지시문을 보내야 시작한다.
  저장소·브랜치 삭제, 강제 push 는 worker_prompt 규칙상 하지 않는다. 에이전트가 기본적으로 `/opt/quant` 에서 시작하므로 2번(별도 작업 폴더)을 지키는지가 중요하다.
- 병합 뒤 VM 반영은 자동 배포(5분 주기, 테스트 관문)가 한다. 테스트가 실패하면 서비스는 이전 버전으로 계속 돈다.
