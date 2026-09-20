#!/usr/bin/env bash
# deploy/auto_deploy.sh가 source하는 보조 함수 모음 (직접 실행하지 않는다).
#
# 문제: VM의 리서치 에이전트/실험 슈퍼바이저는 루트 PROGRESS.md 맨 끝에 진행 기록을 *미커밋으로* 덧붙인다.
# 개발 쪽 커밋도 같은 파일에 항목을 추가하므로, 원격이 PROGRESS.md를 바꾸는 커밋을 올릴 때마다
# `git pull --ff-only`가 "로컬 변경이 덮어써진다"며 실패해 자동배포가 통째로 멈췄다(사람이 VM에서 손으로
# 커밋·리베이스·푸시해야 풀렸다).
#
# 해결: 그 경우에만 — (a) 로컬 PROGRESS.md가 수정돼 있고 (b) 새 커밋도 이 파일을 바꿀 때 —
#   1) 로컬 파일을 통째로 백업하고(STATE_DIR/PROGRESS.local.*),
#   2) 이 파일 하나만 HEAD로 되돌려 pull을 통과시킨 뒤,
#   3) 백업의 로컬 추가분을 새 upstream 위에 3-way *union* 병합으로 다시 얹는다
#      (양쪽이 같은 곳, 예컨대 파일 끝에 덧붙여도 충돌 마커 없이 둘 다 남는다).
# 로컬 내용은 어떤 경우에도 버려지지 않는다 — 백업 + 재적용이고, pull이 다른 이유로 실패하면 백업에서 원상 복구하며,
# 병합이 실패해도 백업 파일이 남는다. 다른 파일의 로컬 수정은 전혀 건드리지 않는다(여전히 pull을 막고 알림으로 이어짐).
#
# 호출하는 쪽이 미리 정의해둬야 하는 것: git_as_quant(quant 계정으로 git 실행), log, APP_DIR, STATE_DIR
#
# 사용 순서 (auto_deploy.sh 참고):
#   progress_prepare_for_pull <로컬 HEAD> <원격 HEAD>   # pull 직전
#   pull 성공 -> progress_reapply_after_pull <새 HEAD>  /  pull 실패 -> progress_restore_after_failed_pull

PROGRESS_FILE="PROGRESS.md"
PROGRESS_KEEP_BACKUPS=10
PROGRESS_PENDING=0
PROGRESS_LOCAL_COPY=""
PROGRESS_BASE_COPY=""
PROGRESS_TMP_PREFIX=""  # 병합 중간 파일 — 백업 이름(PROGRESS.local.*)과 겹치면 정리 대상에 섞이므로 따로 둔다

# 백업은 이름(타임스탬프) 순으로 최근 N개만 남긴다 — 파일 mtime은 원본을 따라가므로 이름으로 정렬한다.
# 정리 실패가 배포를 죽이지 않도록(호출부는 set -e) 끝에 || true.
progress_prune_backups() {
  local kind old
  for kind in local base; do
    # shellcheck disable=SC2012
    ls -1 "$STATE_DIR"/PROGRESS."$kind".* 2>/dev/null | sort | head -n "-${PROGRESS_KEEP_BACKUPS}" \
      | while IFS= read -r old; do rm -f -- "$old"; done || true
  done
  return 0
}

# 0을 돌려주면 "일반 pull을 그대로 진행해도 된다"(아무것도 안 했거나, 준비를 끝냄).
# 1을 돌려주면 준비 중 실패한 것 — 워킹트리는 건드리지 않은 상태이므로 호출자는 그냥 일반 pull로 진행하면 된다.
progress_prepare_for_pull() {
  local local_head="$1" remote_head="$2" changed stamp
  PROGRESS_PENDING=0

  [ -n "$(git_as_quant status --porcelain -- "$PROGRESS_FILE")" ] || return 0
  changed="$(git_as_quant diff --name-only "${local_head}..${remote_head}" -- "$PROGRESS_FILE")"
  [ -n "$changed" ] || return 0

  stamp="$(date +%Y%m%d-%H%M%S)-$$"
  PROGRESS_LOCAL_COPY="$STATE_DIR/PROGRESS.local.$stamp"
  PROGRESS_BASE_COPY="$STATE_DIR/PROGRESS.base.$stamp"
  PROGRESS_TMP_PREFIX="$STATE_DIR/PROGRESS.tmp.$stamp"
  cp -p "$APP_DIR/$PROGRESS_FILE" "$PROGRESS_LOCAL_COPY" || return 1
  git_as_quant show "${local_head}:${PROGRESS_FILE}" > "$PROGRESS_BASE_COPY" || return 1
  # 백업이 실제 파일과 바이트 단위로 같다는 걸 확인한 뒤에만 파일을 되돌린다.
  cmp -s "$APP_DIR/$PROGRESS_FILE" "$PROGRESS_LOCAL_COPY" || return 1

  git_as_quant checkout "$local_head" -- "$PROGRESS_FILE" || {
    cp "$PROGRESS_LOCAL_COPY" "$APP_DIR/$PROGRESS_FILE" || true
    return 1
  }
  PROGRESS_PENDING=1
  log "PROGRESS.md 로컬 미커밋 추가분과 새 커밋이 겹침 — 백업 후 pull, 끝나면 다시 얹음 (백업: $PROGRESS_LOCAL_COPY)"
  return 0
}

progress_restore_after_failed_pull() {
  [ "$PROGRESS_PENDING" -eq 1 ] || return 0
  PROGRESS_PENDING=0
  if cp "$PROGRESS_LOCAL_COPY" "$APP_DIR/$PROGRESS_FILE"; then
    log "pull 실패 — PROGRESS.md를 백업에서 원래 로컬 내용으로 복원함"
  else
    log "pull 실패 후 PROGRESS.md 복원도 실패 — 로컬 내용은 $PROGRESS_LOCAL_COPY 에 그대로 있음"
    return 1
  fi
}

# 0: 로컬 추가분을 새 upstream 위에 다시 얹음(또는 할 일 없음). 1: 실패 — 워킹트리엔 upstream 버전이 있고
# 로컬 내용은 $PROGRESS_LOCAL_COPY 에 보관돼 있다(호출자가 알림을 보낸다).
progress_reapply_after_pull() {
  local new_head="$1" result=0
  [ "$PROGRESS_PENDING" -eq 1 ] || return 0
  PROGRESS_PENDING=0
  _progress_reapply "$new_head" || result=1
  rm -f "$PROGRESS_TMP_PREFIX.upstream" "$PROGRESS_TMP_PREFIX.merged"
  return "$result"
}

_progress_reapply() {
  local new_head="$1" upstream merged rc=0
  upstream="$PROGRESS_TMP_PREFIX.upstream"
  merged="$PROGRESS_TMP_PREFIX.merged"

  if ! git_as_quant show "${new_head}:${PROGRESS_FILE}" > "$upstream"; then
    log "새 커밋의 PROGRESS.md를 읽지 못함 — 로컬 내용은 $PROGRESS_LOCAL_COPY 에 보관됨"
    return 1
  fi
  cp "$PROGRESS_LOCAL_COPY" "$merged" || { log "병합용 임시 파일을 만들지 못함 — 로컬 내용은 $PROGRESS_LOCAL_COPY 에 보관됨"; return 1; }
  # git merge-file <현재> <공통 조상> <상대>: 결과는 첫 인자 파일에 덮어써진다. --union은 충돌 구간을 양쪽 다 남긴다.
  git merge-file --union "$merged" "$PROGRESS_BASE_COPY" "$upstream" || rc=$?
  if [ "$rc" -ge 128 ] || grep -q '^<<<<<<< ' "$merged"; then
    log "PROGRESS.md 병합 실패(rc=$rc) — 워킹트리엔 새 upstream 버전이 있고 로컬 내용은 $PROGRESS_LOCAL_COPY 에 보관됨"
    return 1
  fi
  # 소유자/권한을 유지하려고 rm/mv가 아니라 기존 파일에 덮어쓴다.
  if ! cat "$merged" > "$APP_DIR/$PROGRESS_FILE"; then
    log "병합 결과를 PROGRESS.md에 쓰지 못함 — 로컬 내용은 $PROGRESS_LOCAL_COPY 에 보관됨"
    return 1
  fi
  rm -f "$PROGRESS_BASE_COPY"
  progress_prune_backups
  log "PROGRESS.md: 새 upstream 위에 로컬 미커밋 추가분을 다시 얹음 (union 병합, 백업: $PROGRESS_LOCAL_COPY)"
  return 0
}
