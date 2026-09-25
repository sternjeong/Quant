#!/usr/bin/env bash
# Oracle VM에서 GitHub main에 새 커밋이 올라오면 사람이 SSH로 들어와 `git pull` +
# `systemctl restart`를 손으로 하지 않아도 되게 자동화하는 스크립트.
# systemd 타이머(quant-auto-deploy.timer)가 주기적으로 root 권한으로 이 스크립트를 실행한다
# (서비스를 재시작하려면 root가 필요하지만, git 자체는 항상 quant 계정 권한으로만 돌린다 —
# /opt/quant 워킹트리 소유자가 quant라서 root로 바로 git을 돌리면 최신 git의
# "dubious ownership" 안전장치에 걸린다).
#
# ★ 안전 원칙 (반드시 지킬 것): 여기서 쓰는 git 조작은 `git fetch`와 `git pull --ff-only`,
# 그리고 아래에서 설명하는 두 가지 좁은 예외뿐이다: `data/cache/fred_*.csv` 전용 `git checkout --` 한 줄과,
# VM 에이전트가 미커밋으로 덧붙이는 기록/색인 파일 몇 개(PROGRESS.md, docs/reports/README.md — deploy/progress_reconcile.sh의
# RECONCILE_FILES)에 한정한 "백업 → 그 파일만 HEAD로 되돌림 → pull → union 병합으로 다시 얹기".
# 그 외에 fast-forward가 안 되는 상황(히스토리 분기, 다른 파일의 로컬 수정이 막고 있음, 충돌
# 등)이면 그 자리에서 즉시 포기하고 텔레그램으로 알린다 — `git reset --hard`, `git clean`,
# 범용 `git checkout .`, 강제 push, stash/drop 같은 건 이 스크립트에 존재하지 않고 앞으로도
# 추가하면 안 된다. VM 워킹트리에는 지우면 안 되는 로컬 수정 파일과 미커밋 리서치 결과물이
# 실제로 쌓여 있다 (deploy/PENDING_MANUAL_LOGIN_ACTIONS.md 참고) — 자동 배포가 그걸 건드리는
# 순간 이 자동화 전체의 존재 이유가 사라진다. `fred_*.csv` 예외는 어떤 파일이든 지워도 되는
# 게 아니라, .gitignore가 이미 "VM에서 다시 만들어져도 되는 캐시"로 명시적으로 선언해둔
# 딱 그 패턴 하나만 대상으로 한다 — 새 예외를 추가하려면 같은 근거(외부에서 재요청 가능한
# 멱등 캐시인지)를 먼저 확인해야 한다. PROGRESS.md 예외의 근거는 반대로 "버려도 되는 파일"이 아니라
# "내용이 절대 버려지지 않는다"는 것이다: VM 에이전트가 미커밋으로 덧붙이는 진행 기록을 바이트 단위로 확인한
# 백업으로 먼저 보존하고, pull 뒤 새 upstream 위에 그대로 다시 얹으며(실패하면 백업에서 복원, 병합이 실패해도
# 백업이 남고 텔레그램으로 알린다), 다른 어떤 파일의 로컬 수정도 건드리지 않는다.
#
# 흔한 경우(타이머가 5분마다 실행 — 대부분 새 커밋 없음)는 `git fetch` + 해시 비교만 하고
# 조용히(로그도 안 남기고) 끝난다. 새 커밋이 있을 때만 pull/서비스 재시작/텔레그램 발송처럼
# 비용이 드는 작업을 한다.
set -euo pipefail

APP_DIR="/opt/quant"
SERVICE_USER="quant"
SERVICES=(codex-telegram quant-streamlit quant-scheduler quant-hub)
ALERT_SCRIPT="$APP_DIR/deploy/send_telegram_alert.sh"
STATE_DIR="${AUTO_DEPLOY_STATE_DIR:-/opt/quant/.auto-deploy-state}"
FAIL_ALERT_FILE="$STATE_DIR/pull_failure_last_alert"
# A persistent (non-transient) pull failure would otherwise re-alert every timer tick (5min) --
# this caps it to one alert per cooldown window instead of spamming forever.
ALERT_COOLDOWN_SECONDS="${AUTO_DEPLOY_ALERT_COOLDOWN_SECONDS:-21600}"
# 새 커밋을 테스트했는데 실패한 그 커밋 해시를 기록해둔다. pull이 이미 그 커밋까지 끝난
# 상태라 다음 타이머 틱에서는 local_head == remote_head라 자연히 재시도/재알림을 안 하게
# 되므로(위 no-op 분기), 이 파일은 오직 "나중에 성공했을 때 복구 알림에 덧붙일 문구"용이다.
TEST_FAIL_FLAG="$STATE_DIR/last_test_failure_commit"
TEST_LOG="$STATE_DIR/last_test_output.log"
TEST_TIMEOUT_SECONDS="${AUTO_DEPLOY_TEST_TIMEOUT_SECONDS:-240}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

clear_failure_state() {
  rm -f "$FAIL_ALERT_FILE" 2>/dev/null || true
}

# 항상 quant 계정 권한으로 git을 돌린다 (워킹트리 소유자가 quant이기 때문).
# -n: 혹시라도 비밀번호가 필요한 상황이면 무인 실행 중 멈춰서 기다리지 말고 바로 실패한다.
git_as_quant() {
  sudo -n -u "$SERVICE_USER" git -C "$APP_DIR" "$@"
}

# VM 에이전트가 PROGRESS.md에 미커밋으로 덧붙인 기록 때문에 --ff-only가 막히는 문제를 푸는 보조 함수들.
# 파일이 없으면(부분 배포 등) 아무것도 안 하는 대체 함수로 두고 예전처럼 일반 pull만 한다.
if [ -r "$APP_DIR/deploy/progress_reconcile.sh" ]; then
  # shellcheck source=deploy/progress_reconcile.sh
  source "$APP_DIR/deploy/progress_reconcile.sh"
else
  progress_prepare_for_pull() { return 0; }
  progress_restore_after_failed_pull() { return 0; }
  progress_reapply_after_pull() { return 0; }
fi

# 재시작 뒤 서비스가 실제로 살아 있는지 확인하는 함수(deploy/post_deploy_check.sh). 없으면 예전처럼 확인 없이 진행한다.
POST_DEPLOY_TIMEOUT_SECONDS="${AUTO_DEPLOY_POST_CHECK_TIMEOUT_SECONDS:-90}"
if [ -r "$APP_DIR/deploy/post_deploy_check.sh" ]; then
  # shellcheck source=deploy/post_deploy_check.sh
  source "$APP_DIR/deploy/post_deploy_check.sh"
else
  verify_services_after_restart() { return 0; }
fi

cd "$APP_DIR"
mkdir -p "$STATE_DIR" 2>/dev/null || true

if ! fetch_output="$(git_as_quant fetch origin --quiet 2>&1)"; then
  # 흔치 않은 경로지만(네트워크 일시 장애 등) 조용히 넘어가면 안 되니 저널에는 남긴다.
  # 5분마다 도는 스크립트라 매번 텔레그램까지 보내면 일시적 장애에도 스팸이 되므로,
  # 알림은 실제 배포 실패(git pull --ff-only 실패) 케이스로만 한정한다.
  log "git fetch 실패 — 이번 주기는 건너뜀 (일시적 네트워크 문제일 수 있음, 텔레그램 알림 생략)"
  log "$fetch_output"
  exit 1
fi

# data/cache/fred_*.csv는 .gitignore에서 일부러 추적 대상으로 남겨둔 예외다(야간 매크로 캐시
# 자동화가 커밋해서 라이브 앱이 재사용하도록). 그런데 이 VM의 quant-scheduler도 같은 FRED
# 시계열을 독립적으로 새로고침해서 로컬에 쓰기 때문에, 원격에서 같은 파일을 건드리는 커밋이
# 오면 매번 "로컬 변경이 있어 --ff-only 불가"로 막힌다. 이 데이터는 외부 API에서 그대로
# 재요청 가능한 멱등 캐시라 VM의 로컬 버전을 버려도 다음 스케줄러 주기에 다시 채워지므로
# 안전하다 -- 아래는 그 파일 패턴 하나만 골라 되돌리는 것이지, 금지된 범용 checkout/reset이
# 아니다(.gitignore가 이미 선언한 것과 동일한 범위).
stale_cache="$(git_as_quant status --porcelain -- 'data/cache/fred_*.csv' | awk '{print $2}')"
if [ -n "$stale_cache" ]; then
  log "로컬에서 갱신된 FRED 캐시 파일을 pull 전에 되돌림: $(printf '%s' "$stale_cache" | tr '\n' ' ')"
  git_as_quant checkout -- 'data/cache/fred_*.csv'
fi

local_head="$(git_as_quant rev-parse HEAD)"
remote_head="$(git_as_quant rev-parse origin/main)"

if [ "$local_head" = "$remote_head" ]; then
  # 흔한 경우: 새 커밋 없음 — 출력도 남기지 않고 바로 종료 (요구사항: no-op은 조용하고 가볍게)
  clear_failure_state
  exit 0
fi

log "새 커밋 감지: ${local_head:0:7} -> ${remote_head:0:7}. git pull --ff-only 시도"

# 기록 파일(PROGRESS.md 등)의 로컬 미커밋 추가분이 새 커밋과 겹치면 여기서 백업하고 그 파일만 HEAD로 되돌린다(아니면 아무것도 안 함).
# 준비에 실패해도 워킹트리는 그대로이므로 일반 pull로 진행하고, 막히면 아래 기존 실패 알림으로 이어진다.
if ! progress_prepare_for_pull "$local_head" "$remote_head"; then
  log "기록 파일(PROGRESS.md 등) 사전 처리에 실패 — 해당 파일은 그대로, 일반 pull로 진행"
fi

if pull_output="$(git_as_quant pull --ff-only 2>&1)"; then
  new_head="$(git_as_quant rev-parse HEAD)"
  commit_count="$(git_as_quant rev-list --count "${local_head}..${new_head}")"
  commit_summary="$(git_as_quant log --oneline "${local_head}..${new_head}")"
  commit_summary_short="$(printf '%s' "$commit_summary" | head -c 1500)"
  if [ "${#commit_summary}" -gt 1500 ]; then
    commit_summary_short="${commit_summary_short}
... (생략)"
  fi

  log "pull 성공: ${local_head:0:7} -> ${new_head:0:7} ($commit_count 커밋)"
  log "$commit_summary"

  if ! progress_reapply_after_pull "$new_head"; then
    # 배포 자체는 계속한다 — 코드는 이미 최신이고, 잃은 것도 없다(로컬 기록은 백업 파일에 남아 있음).
    "$ALERT_SCRIPT" "[자동배포] 기록 파일(PROGRESS.md 등) 병합 실패 — 배포는 계속함
${local_head:0:7}..${new_head:0:7} ($commit_count 커밋)
VM의 미커밋 기록 파일(PROGRESS.md, docs/reports/README.md)을 새 커밋 위에 다시 얹지 못했음. 기록은 $STATE_DIR/*.local.* 백업에 그대로 있으니
수동으로 합쳐주세요." || log "텔레그램 알림 전송도 실패"
  fi

  deps_note=""
  if git_as_quant diff --name-only "${local_head}..${new_head}" | grep -qx 'requirements.txt'; then
    log "requirements.txt 변경 감지 — 서비스 재시작 전에 pip install 먼저 실행"
    if pip_output="$(sudo -n -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" 2>&1)"; then
      log "pip install 완료"
      deps_note="의존성(requirements.txt) 변경 감지 — pip install 완료 후 재시작함
"
    else
      log "pip install 실패 — 서비스는 재시작하지 않음(기존 버전 계속 실행 중), 수동 확인 필요"
      log "$pip_output"
      truncated_pip_output="$(printf '%s' "$pip_output" | tail -c 1500)"
      message="[자동배포] 코드는 pull됐지만 pip install 실패 — 수동 확인 필요
${local_head:0:7}..${new_head:0:7} ($commit_count 커밋)
requirements.txt가 바뀌었는데 의존성 설치가 실패해서 서비스는 재시작하지 않았음(기존 버전 계속 실행 중).

pip install 에러:
$truncated_pip_output"
      "$ALERT_SCRIPT" "$message" || log "텔레그램 알림 전송도 실패"
      exit 1
    fi
  fi

  log "서비스 재시작 전 테스트 게이트 실행 (tests/ + deploy 유닛테스트, 최대 ${TEST_TIMEOUT_SECONDS}초)"
  : > "$TEST_LOG"
  tests_ok=1
  if ! sudo -n -u "$SERVICE_USER" timeout "$TEST_TIMEOUT_SECONDS" \
        "$APP_DIR/.venv/bin/python" -m pytest "$APP_DIR/tests" -q >>"$TEST_LOG" 2>&1; then
    tests_ok=0
  fi
  # runner.py는 프로젝트 venv 없이 시스템 python3로 도는
  # stdlib-only 프로세스라(core/resource_guard.py 주석 참고), 시스템 python3로 검증한다.
  # pytest는 프로젝트 venv에만 설치돼 있고 시스템 python3에는 없다(stdlib-only라는 전제와
  # 모순되므로 여기 설치하지 않는다) — 테스트 파일이 unittest.TestCase라 표준 라이브러리
  # unittest만으로 그대로 돌아간다. 상대 임포트(`from runner import ...`)가 풀리려면 각 테스트
  # 파일이 있는 디렉터리에서 실행해야 한다(`python -m` 이 실행 당시 작업 디렉터리를 sys.path에
  # 넣어주는 동작에 의존).
  if ! sudo -n -u "$SERVICE_USER" timeout 60 bash -c \
        "cd '$APP_DIR/deploy/codex_telegram' && python3 -m unittest test_runner" >>"$TEST_LOG" 2>&1; then
    tests_ok=0
  fi

  if [ "$tests_ok" -eq 0 ]; then
    log "테스트 실패 — 서비스는 재시작하지 않음(기존 버전 계속 실행 중). 워킹트리는 이미 새 커밋으로 이동했으므로, 다음 새 커밋이 올 때만 다시 테스트함(같은 커밋 재시도/재알림 없음)"
    cat "$TEST_LOG"
    echo "$new_head" > "$TEST_FAIL_FLAG"

    truncated_test_output="$(tail -c 2000 "$TEST_LOG")"
    message="[자동배포] pull은 됐지만 테스트 실패 — 서비스는 재시작하지 않음(기존 버전 계속 실행 중)
${local_head:0:7}..${new_head:0:7} ($commit_count 커밋)
워킹트리는 이미 새 커밋으로 옮겨갔지만 서비스는 이전 버전을 그대로 실행 중. 같은 커밋으로는
재시도/재알림하지 않고, 다음에 새 커밋이 오면 그걸로 다시 테스트함.

pytest 실패 출력(뒷부분):
$truncated_test_output"
    "$ALERT_SCRIPT" "$message" || log "텔레그램 알림 전송도 실패"
    exit 1
  fi

  log "테스트 통과 (tests/ + deploy 유닛테스트)"
  log "서비스 재시작: ${SERVICES[*]}"

  systemctl restart "${SERVICES[@]}"

  log "재시작 완료"

  # 재시작 직후 "성공"을 알리기 전에, 서비스가 실제로 떠서 응답하고 곧바로 죽지 않는지 확인한다.
  if unhealthy_services="$(verify_services_after_restart "$POST_DEPLOY_TIMEOUT_SECONDS" "${SERVICES[@]}")"; then
    log "재시작 후 서비스 상태 확인: 모두 정상"
  else
    log "재시작 후 비정상 서비스: $(printf '%s' "$unhealthy_services" | tr '\n' ' ')"
    message="[자동배포] 배포는 됐지만 재시작 후 서비스가 정상이 아님 — 확인 필요
${local_head:0:7}..${new_head:0:7} ($commit_count 커밋)
테스트는 통과했지만 아래 서비스가 제한 시간(${POST_DEPLOY_TIMEOUT_SECONDS}초) 안에 정상 상태가 되지 못했음:
$unhealthy_services

원인은 VM에서 journalctl -u <서비스> -n 50 으로 확인하고, 코드가 원인이면 되돌리는 커밋을 올리면 자동으로 다시 배포됨."
    "$ALERT_SCRIPT" "$message" || log "텔레그램 알림 전송도 실패"
    exit 1
  fi

  # 직전까지 실패 알림/테스트 실패 상태였다면, 이번에 복구됐다는 걸 메시지에 덧붙이고 상태를 지운다.
  recovery_note=""
  if [ -f "$FAIL_ALERT_FILE" ]; then
    recovery_note="(이전 배포 실패 상태에서 복구됨)
"
    clear_failure_state
  fi
  if [ -f "$TEST_FAIL_FLAG" ]; then
    recovery_note="${recovery_note}(이전 테스트 실패 상태에서 복구됨)
"
    rm -f "$TEST_FAIL_FLAG" 2>/dev/null || true
  fi

  message="[자동배포] 성공
${recovery_note}${local_head:0:7}..${new_head:0:7} ($commit_count 커밋)
${deps_note}재시작: ${SERVICES[*]} (재시작 후 상태 확인 완료)

$commit_summary_short"
  if ! "$ALERT_SCRIPT" "$message"; then
    log "텔레그램 알림 전송 실패 (배포 자체는 이미 성공했음)"
  fi

  log "완료"
  exit 0
else
  pull_status=$?
  progress_restore_after_failed_pull || true
  log "git pull --ff-only 실패 (exit $pull_status) — 워킹트리는 그대로 두고 서비스도 건드리지 않음. 수동 확인 필요"
  log "$pull_output"

  truncated_output="$(printf '%s' "$pull_output" | tail -c 1500)"

  now="$(date +%s)"
  should_alert=1
  if [ -f "$FAIL_ALERT_FILE" ]; then
    last_alert="$(cat "$FAIL_ALERT_FILE" 2>/dev/null || echo 0)"
    [[ "$last_alert" =~ ^[0-9]+$ ]] || last_alert=0
    if [ $((now - last_alert)) -lt "$ALERT_COOLDOWN_SECONDS" ]; then
      should_alert=0
    fi
  fi
  if [ "$should_alert" -eq 0 ]; then
    log "직전 실패 알림 쿨다운 중이라 이번엔 텔레그램 재알림을 생략함 (계속 실패 중 -- journalctl -u quant-auto-deploy 로 계속 확인 가능)"
    exit 1
  fi
  echo "$now" > "$FAIL_ALERT_FILE"

  message="[자동배포] 실패 — 수동 확인 필요
로컬 ${local_head:0:7}, 원격 ${remote_head:0:7} (fast-forward 불가 또는 오류로 추정)
워킹트리는 건드리지 않았음. git reset/clean 등 자동 복구는 하지 않음.
같은 문제가 계속되면 해결 전까지 ${ALERT_COOLDOWN_SECONDS}초(기본 6시간)마다 한 번만 다시 알림.

git pull --ff-only 에러:
$truncated_output"
  if ! "$ALERT_SCRIPT" "$message"; then
    log "텔레그램 알림 전송도 실패"
  fi

  exit 1
fi
