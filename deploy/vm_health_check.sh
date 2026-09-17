#!/usr/bin/env bash
# Oracle Always Free ARM VM은 디스크/메모리 용량이 빠듯하다. 이 스크립트는 df/free로 루트
# 파티션 사용률과 메모리 사용률을 확인해서 임계값을 넘으면 텔레그램으로 알림을 보낸다.
# quant-vm-health.timer가 주기적으로 이 스크립트를 실행한다(기본 부팅 5분 후 + 15분마다).
#
# 상태(각 조건을 마지막으로 언제 알림했는지)는 텔레그램↔Claude/Codex 큐가 쓰는
# /opt/quant/.codex-telegram-state/ (SQLite DB) 와는 별개로 /opt/quant/.vm-health-state/ 에
# 저장한다 — 그 큐 디렉터리는 건드리지 않는다.
#
# 환경변수로 조정 가능:
#   DISK_THRESHOLD_PERCENT   디스크(루트 파티션) 사용률 알림 임계값 (기본 85)
#   MEM_THRESHOLD_PERCENT    메모리 사용률 알림 임계값 (기본 90)
#   ALERT_COOLDOWN_SECONDS   같은 조건으로 재알림하기까지 최소 대기 시간, 초 단위 (기본 21600 = 6시간)
#   VM_HEALTH_STATE_DIR      상태 파일 저장 위치 (기본 /opt/quant/.vm-health-state) — 로컬 테스트 시
#                            /opt/quant 가 없는 환경에서 /tmp 등으로 덮어쓰는 용도
#   VM_HEALTH_ALERT_SCRIPT   텔레그램 발송 스크립트 경로 (기본: 이 스크립트와 같은 디렉터리의
#                            send_telegram_alert.sh)
#
# 정상(=알림을 보낼 필요가 없는) 경우 stdout에 아무것도 찍지 않고 exit 0 — journald 로그를
# 조용히 유지하기 위함. 디스크/메모리 체크 중 하나가 파싱 실패 등으로 문제가 생겨도 다른 체크와
# 스크립트 전체 종료 코드에 영향을 주지 않도록 set -e는 쓰지 않는다(각 단계에서 직접 에러를 처리).
set -uo pipefail

DISK_THRESHOLD_PERCENT="${DISK_THRESHOLD_PERCENT:-85}"
MEM_THRESHOLD_PERCENT="${MEM_THRESHOLD_PERCENT:-90}"
ALERT_COOLDOWN_SECONDS="${ALERT_COOLDOWN_SECONDS:-21600}"
STATE_DIR="${VM_HEALTH_STATE_DIR:-/opt/quant/.vm-health-state}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ALERT_SCRIPT="${VM_HEALTH_ALERT_SCRIPT:-$SCRIPT_DIR/send_telegram_alert.sh}"

# 상태 디렉터리가 없으면 만든다(setup_vm.sh가 미리 quant 소유로 만들어두는 게 정상 경로지만,
# 로컬 테스트 등에서 없을 수 있으니 방어적으로 한 번 더 시도).
mkdir -p "$STATE_DIR" 2>/dev/null || true

send_alert() {
  # 텔레그램 발송이 실패해도(토큰 미설정, 네트워크 장애 등) 헬스체크 로직 자체는 계속 진행돼야
  # 하고 상태 파일도 정상적으로 기록돼야 한다 — 그래서 여기서 실패해도 스크립트를 죽이지 않는다.
  local msg="$1"
  echo "$msg"
  if [ -x "$ALERT_SCRIPT" ]; then
    if ! "$ALERT_SCRIPT" "$msg"; then
      echo "[경고] 텔레그램 알림 발송 실패 — 상태 파일 기록은 계속 진행함" >&2
    fi
  else
    echo "[경고] 알림 스크립트를 찾을 수 없거나 실행 권한 없음: $ALERT_SCRIPT" >&2
  fi
}

# 조건 하나(disk/mem)에 대한 쿨다운 + 복구 감지를 처리한다.
#   $1 = 조건 이름(상태 파일명에 씀, 예: disk/mem)
#   $2 = 현재 사용률(정수 %)
#   $3 = 임계값(정수 %)
#   $4 = 알림 메시지에 쓸 사람이 읽을 라벨
check_condition() {
  local name="$1" current="$2" threshold="$3" label="$4"
  local state_file="$STATE_DIR/${name}.alerting"
  local last_alert now diff

  if [ "$current" -ge "$threshold" ]; then
    now="$(date +%s)"
    if [ -f "$state_file" ]; then
      last_alert="$(cat "$state_file" 2>/dev/null || echo 0)"
      [[ "$last_alert" =~ ^[0-9]+$ ]] || last_alert=0
      diff=$((now - last_alert))
      if [ "$diff" -lt "$ALERT_COOLDOWN_SECONDS" ]; then
        return 0
      fi
    fi
    send_alert "⚠️ [Quant VM] ${label} 사용률 ${current}%로 임계값(${threshold}%) 초과 — 확인 필요"
    echo "$now" > "$state_file"
  else
    if [ -f "$state_file" ]; then
      send_alert "✅ [Quant VM] ${label} 사용률 ${current}%로 정상 범위 복구됨"
      rm -f "$state_file"
    fi
  fi
}

# --- 디스크 사용률(루트 파티션) ---
# df -P: POSIX 출력 형식 고정(로케일/컬럼폭 차이로 파싱 깨지는 것 방지). 2번째 줄 5번째 필드가
# "Capacity"(use%) 컬럼, 끝에 %가 붙어 있어 제거한다.
disk_line="$(df -P / 2>/dev/null | awk 'NR==2 {print $5}')"
disk_percent="${disk_line%\%}"
if [[ "$disk_percent" =~ ^[0-9]+$ ]]; then
  check_condition "disk" "$disk_percent" "$DISK_THRESHOLD_PERCENT" "디스크(/)"
else
  echo "[경고] df 출력 파싱 실패, 이번 실행에서 디스크 체크 건너뜀: '$disk_line'" >&2
fi

# --- 메모리 사용률 ---
# free -m의 available 컬럼(7번째 필드)은 캐시 중 회수 가능한 페이지캐시를 이미 "쓸 수 있는 메모리"로
# 계산해준다. 그래서 (total - free)가 아니라 (total - available)을 "실제 사용중"으로 본다 —
# 안 그러면 정상적으로 캐시가 꽉 찬 상태를 메모리 부족으로 오판하게 된다.
read -r mem_total mem_available <<< "$(free -m 2>/dev/null | awk '/^Mem:/ {print $2, $7}')"
if [[ "${mem_total:-}" =~ ^[0-9]+$ ]] && [[ "${mem_available:-}" =~ ^[0-9]+$ ]] && [ "$mem_total" -gt 0 ]; then
  mem_percent=$(( (mem_total - mem_available) * 100 / mem_total ))
  check_condition "mem" "$mem_percent" "$MEM_THRESHOLD_PERCENT" "메모리"
else
  echo "[경고] free 출력 파싱 실패, 이번 실행에서 메모리 체크 건너뜀: total='${mem_total:-}' available='${mem_available:-}'" >&2
fi

exit 0
