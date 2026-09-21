#!/usr/bin/env bash
# deploy/auto_deploy.sh가 source하는 보조 함수 모음 (직접 실행하지 않는다).
#
# 문제: VM의 리서치 에이전트/실험 슈퍼바이저는 루트 PROGRESS.md 맨 끝(그리고 docs/reports/README.md 여러 곳)에 진행 기록/색인을
# *미커밋으로* 덧붙인다. 개발 쪽 커밋도 같은 파일에 항목을 추가하므로, 원격이 그 파일을 바꾸는 커밋을 올릴 때마다
# `git pull --ff-only`가 "로컬 변경이 덮어써진다"며 실패해 자동배포가 통째로 멈췄다(사람이 VM에서 손으로
# 커밋·리베이스·푸시해야 풀렸다).
#
# 해결: RECONCILE_FILES에 든 파일마다, (a) 로컬에서 수정돼 있고 (b) 새 커밋도 그 파일을 바꿀 때만 —
#   1) 로컬 파일을 통째로 백업하고(STATE_DIR/<이름>.local.*),
#   2) 그 파일 하나만 HEAD로 되돌려 pull을 통과시킨 뒤,
#   3) 백업의 로컬 추가분을 새 upstream 위에 3-way *union* 병합으로 다시 얹는다
#      (양쪽이 같은 곳, 예컨대 파일 끝에 덧붙여도 충돌 마커 없이 둘 다 남는다. 서로 다른 곳이면 그냥 합쳐진다).
# 로컬 내용은 어떤 경우에도 버려지지 않는다 — 백업 + 재적용이고, pull이 다른 이유로 실패하면 백업에서 원상 복구하며,
# 병합이 실패해도 백업 파일이 남는다. 목록에 없는 다른 파일의 로컬 수정은 전혀 건드리지 않는다(여전히 pull을 막고 알림으로 이어짐).
# 새 파일을 이 목록에 넣으려면 "에이전트가 덧붙이는 기록/색인이라 union 병합이 안전한가"를 먼저 확인해야 한다.
#
# 호출하는 쪽이 미리 정의해둬야 하는 것: git_as_quant(quant 계정으로 git 실행), log, APP_DIR, STATE_DIR
#
# 사용 순서 (auto_deploy.sh 참고):
#   progress_prepare_for_pull <로컬 HEAD> <원격 HEAD>   # pull 직전
#   pull 성공 -> progress_reapply_after_pull <새 HEAD>  /  pull 실패 -> progress_restore_after_failed_pull

# 백업 파일 이름 접두사는 PROGRESS.md만 예전 그대로("PROGRESS"), 나머지는 경로의 /를 _로 바꾼 이름이다.
RECONCILE_FILES=("PROGRESS.md" "docs/reports/README.md")
PROGRESS_KEEP_BACKUPS=10

RC_PENDING=()      # 인덱스별: 1이면 이 파일을 되돌려 놓은 상태(pull 뒤 다시 얹어야 함)
RC_LOCAL_COPY=()
RC_BASE_COPY=()
RC_TMP_PREFIX=()

_rc_prefix() {
  local file="$1"
  if [ "$file" = "PROGRESS.md" ]; then echo "PROGRESS"; else echo "${file//\//_}"; fi
}

# 백업은 이름(타임스탬프) 순으로 파일마다 최근 N개만 남긴다 — 파일 mtime은 원본을 따라가므로 이름으로 정렬한다.
# 정리 실패가 배포를 죽이지 않도록(호출부는 set -e) 끝에 || true.
progress_prune_backups() {
  local file prefix kind old
  for file in "${RECONCILE_FILES[@]}"; do
    prefix="$(_rc_prefix "$file")"
    for kind in local base; do
      # shellcheck disable=SC2012
      ls -1 "$STATE_DIR"/"$prefix"."$kind".* 2>/dev/null | sort | head -n "-${PROGRESS_KEEP_BACKUPS}" \
        | while IFS= read -r old; do rm -f -- "$old"; done || true
    done
  done
  return 0
}

# 한 파일 준비. 0: 일반 pull을 진행해도 됨(아무것도 안 했거나 준비를 끝냄), 1: 준비 중 실패(그 파일은 건드리지 않은 상태).
_rc_prepare() {
  local i="$1" local_head="$2" remote_head="$3"
  local file="${RECONCILE_FILES[$i]}" prefix changed stamp
  RC_PENDING[$i]=0

  [ -n "$(git_as_quant status --porcelain -- "$file")" ] || return 0
  changed="$(git_as_quant diff --name-only "${local_head}..${remote_head}" -- "$file")"
  [ -n "$changed" ] || return 0

  prefix="$(_rc_prefix "$file")"
  stamp="$(date +%Y%m%d-%H%M%S)-$$"
  RC_LOCAL_COPY[$i]="$STATE_DIR/$prefix.local.$stamp"
  RC_BASE_COPY[$i]="$STATE_DIR/$prefix.base.$stamp"
  RC_TMP_PREFIX[$i]="$STATE_DIR/$prefix.tmp.$stamp"
  cp -p "$APP_DIR/$file" "${RC_LOCAL_COPY[$i]}" || return 1
  git_as_quant show "${local_head}:${file}" > "${RC_BASE_COPY[$i]}" || return 1
  # 백업이 실제 파일과 바이트 단위로 같다는 걸 확인한 뒤에만 파일을 되돌린다.
  cmp -s "$APP_DIR/$file" "${RC_LOCAL_COPY[$i]}" || return 1

  git_as_quant checkout "$local_head" -- "$file" || {
    cp "${RC_LOCAL_COPY[$i]}" "$APP_DIR/$file" || true
    return 1
  }
  RC_PENDING[$i]=1
  log "$file: 로컬 미커밋 추가분과 새 커밋이 겹침 — 백업 후 pull, 끝나면 다시 얹음 (백업: ${RC_LOCAL_COPY[$i]})"
  return 0
}

# 0을 돌려주면 "일반 pull을 그대로 진행해도 된다". 1이면 어느 파일 준비가 실패한 것 — 그 파일은 건드리지 않은 상태이므로
# 호출자는 그냥 일반 pull로 진행하면 된다(막히면 기존 실패 알림으로 이어짐).
progress_prepare_for_pull() {
  local local_head="$1" remote_head="$2" i overall=0
  RC_PENDING=()
  for i in "${!RECONCILE_FILES[@]}"; do
    _rc_prepare "$i" "$local_head" "$remote_head" || overall=1
  done
  return "$overall"
}

progress_restore_after_failed_pull() {
  local i overall=0 file
  for i in "${!RECONCILE_FILES[@]}"; do
    [ "${RC_PENDING[$i]:-0}" -eq 1 ] || continue
    RC_PENDING[$i]=0
    file="${RECONCILE_FILES[$i]}"
    if cp "${RC_LOCAL_COPY[$i]}" "$APP_DIR/$file"; then
      log "pull 실패 — $file 를 백업에서 원래 로컬 내용으로 복원함"
    else
      log "pull 실패 후 $file 복원도 실패 — 로컬 내용은 ${RC_LOCAL_COPY[$i]} 에 그대로 있음"
      overall=1
    fi
  done
  return "$overall"
}

# 0: 로컬 추가분을 새 upstream 위에 다시 얹음(또는 할 일 없음). 1: 한 파일이라도 실패 — 그 파일의 워킹트리엔 upstream 버전이 있고
# 로컬 내용은 백업에 보관돼 있다(호출자가 알림을 보낸다).
progress_reapply_after_pull() {
  local new_head="$1" i overall=0
  for i in "${!RECONCILE_FILES[@]}"; do
    [ "${RC_PENDING[$i]:-0}" -eq 1 ] || continue
    RC_PENDING[$i]=0
    _rc_reapply "$i" "$new_head" || overall=1
    rm -f "${RC_TMP_PREFIX[$i]}.upstream" "${RC_TMP_PREFIX[$i]}.merged"
  done
  return "$overall"
}

_rc_reapply() {
  local i="$1" new_head="$2"
  local file="${RECONCILE_FILES[$i]}" upstream merged rc=0
  upstream="${RC_TMP_PREFIX[$i]}.upstream"
  merged="${RC_TMP_PREFIX[$i]}.merged"

  if ! git_as_quant show "${new_head}:${file}" > "$upstream"; then
    log "$file: 새 커밋의 내용을 읽지 못함 — 로컬 내용은 ${RC_LOCAL_COPY[$i]} 에 보관됨"
    return 1
  fi
  cp "${RC_LOCAL_COPY[$i]}" "$merged" || { log "$file: 병합용 임시 파일을 만들지 못함 — 로컬 내용은 ${RC_LOCAL_COPY[$i]} 에 보관됨"; return 1; }
  # git merge-file <현재> <공통 조상> <상대>: 결과는 첫 인자 파일에 덮어써진다. --union은 충돌 구간을 양쪽 다 남긴다.
  git merge-file --union "$merged" "${RC_BASE_COPY[$i]}" "$upstream" || rc=$?
  if [ "$rc" -ge 128 ] || grep -q '^<<<<<<< ' "$merged"; then
    log "$file: 병합 실패(rc=$rc) — 워킹트리엔 새 upstream 버전이 있고 로컬 내용은 ${RC_LOCAL_COPY[$i]} 에 보관됨"
    return 1
  fi
  # 소유자/권한을 유지하려고 rm/mv가 아니라 기존 파일에 덮어쓴다.
  if ! cat "$merged" > "$APP_DIR/$file"; then
    log "$file: 병합 결과를 쓰지 못함 — 로컬 내용은 ${RC_LOCAL_COPY[$i]} 에 보관됨"
    return 1
  fi
  rm -f "${RC_BASE_COPY[$i]}"
  progress_prune_backups
  log "$file: 새 upstream 위에 로컬 미커밋 추가분을 다시 얹음 (union 병합, 백업: ${RC_LOCAL_COPY[$i]})"
  return 0
}
