#!/usr/bin/env bash
# deploy/auto_deploy.sh가 source하는 보조 함수 (직접 실행하지 않는다).
#
# 문제: auto_deploy.sh는 `systemctl restart` 직후 곧바로 "[자동배포] 성공"을 알렸다. 새 코드가 테스트는 통과했는데 실제 기동에서
# 죽는 경우(런타임에서만 드러나는 import 오류, 설정 문제 등)에도 성공으로 보고되어, 폰으로만 운영하는 사용자는 서비스가 죽은 걸
# 모른 채 지나갈 수 있었다.
#
# 해결: 재시작 뒤 (1) 모든 서비스가 active가 될 때까지 기다리고(제한 시간 안에), (2) 헬스 엔드포인트가 있는 서비스는 실제로 응답하는지
# 확인하고, (3) 잠깐 기다렸다가 다시 확인해 "떴다가 곧바로 죽는" 서비스(재시작 루프)까지 잡는다.
#
# 사용법: unhealthy="$(verify_services_after_restart <제한 초> <서비스...>)"   # 0이면 정상, 1이면 비정상 목록을 한 줄씩 출력
# 조정용 환경변수: VERIFY_POLL_SECONDS(기본 3), VERIFY_SETTLE_SECONDS(기본 8)

declare -gA POST_DEPLOY_HEALTH_URLS=(
  [quant-streamlit]="http://127.0.0.1:8501/_stcore/health"
  [quant-hub]="http://127.0.0.1:8000/"
)

# 0: 정상, 1: 비활성, 2: 활성이지만 헬스체크 실패
_pd_service_status() {
  local svc="$1" url
  systemctl is-active --quiet "$svc" || return 1
  url="${POST_DEPLOY_HEALTH_URLS[$svc]:-}"
  if [ -n "$url" ]; then
    curl -fsS -m 5 -o /dev/null "$url" >/dev/null 2>&1 || return 2
  fi
  return 0
}

verify_services_after_restart() {
  local timeout="$1"; shift
  local poll="${VERIFY_POLL_SECONDS:-3}" settle="${VERIFY_SETTLE_SECONDS:-8}"
  local deadline=$((SECONDS + timeout)) svc rc
  local bad=()

  while :; do
    bad=()
    for svc in "$@"; do
      rc=0
      _pd_service_status "$svc" || rc=$?
      case "$rc" in
        0) ;;
        2) bad+=("$svc (활성이지만 헬스체크 실패)") ;;
        *) bad+=("$svc (비활성)") ;;
      esac
    done
    [ "${#bad[@]}" -eq 0 ] && break
    if [ "$SECONDS" -ge "$deadline" ]; then
      printf '%s\n' "${bad[@]}"
      return 1
    fi
    sleep "$poll"
  done

  # 뜨자마자 죽는 서비스(재시작 루프)를 잡기 위해 잠깐 기다렸다가 한 번 더 확인한다.
  sleep "$settle"
  bad=()
  for svc in "$@"; do
    _pd_service_status "$svc" || bad+=("$svc (기동 직후 다시 내려감)")
  done
  if [ "${#bad[@]}" -gt 0 ]; then
    printf '%s\n' "${bad[@]}"
    return 1
  fi
  return 0
}
