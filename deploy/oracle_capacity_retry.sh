#!/usr/bin/env bash
# Oracle Cloud Always Free ARM VM (A1.Flex)은 인기 리전에서 "Out of host capacity"
# 에러로 즉시 생성이 안 되는 경우가 흔하다. 이 스크립트는 OCI CLI로 인스턴스 생성을
# 계속 재시도하다 capacity 에러가 아닌 다른 결과(성공 또는 다른 에러)가 나오면 멈춘다.
#
# 사전 준비:
#   1. OCI CLI 설치 + 인증 설정: `oci setup config` (API 키는 콘솔 Profile > API Keys에서 발급)
#   2. 아래 환경변수를 채운 뒤 실행: `bash deploy/oracle_capacity_retry.sh`
#      (또는 별도 .env 파일을 만들어 `source`한 뒤 실행)
#
# 필요한 값은 모두 OCI 콘솔에서 확인 가능:
#   COMPARTMENT_ID     : Identity > Compartments (테넌시 루트 OCID로도 가능)
#   AVAILABILITY_DOMAIN : Compute > Instances > Create Instance 화면에 표시되는 AD 이름
#                         (예: "AbCd:AP-CHUNCHEON-1-AD-1") — 여러 AD를 콤마로 넣으면 순서대로 돌아가며 시도
#   IMAGE_ID           : Compute > Images 에서 Ubuntu 24.04 (aarch64) OCID
#   SUBNET_ID          : Networking > VCN > Subnets 의 OCID
#   SSH_PUBLIC_KEY_FILE : 로컬 공개키 경로 (기본 ~/.ssh/id_ed25519.pub)

set -uo pipefail

COMPARTMENT_ID="${COMPARTMENT_ID:?export COMPARTMENT_ID=ocid1.compartment...}"
IMAGE_ID="${IMAGE_ID:?export IMAGE_ID=ocid1.image...}"
SUBNET_ID="${SUBNET_ID:?export SUBNET_ID=ocid1.subnet...}"
AVAILABILITY_DOMAINS="${AVAILABILITY_DOMAINS:?export AVAILABILITY_DOMAINS=\"AD-1,AD-2,AD-3\" (콤마 구분, AD 이름만)}"
SSH_PUBLIC_KEY_FILE="${SSH_PUBLIC_KEY_FILE:-$HOME/.ssh/id_ed25519.pub}"
INSTANCE_NAME="${INSTANCE_NAME:-quant-vm}"
SHAPE="${SHAPE:-VM.Standard.A1.Flex}"
OCPUS="${OCPUS:-2}"
MEMORY_GB="${MEMORY_GB:-12}"
RETRY_INTERVAL_SECONDS="${RETRY_INTERVAL_SECONDS:-60}"

IFS=',' read -ra AD_LIST <<< "$AVAILABILITY_DOMAINS"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

attempt=0
while true; do
  attempt=$((attempt + 1))
  for ad in "${AD_LIST[@]}"; do
    ad_trimmed="$(echo "$ad" | xargs)"
    log "시도 #$attempt — AD=$ad_trimmed"

    output=$(oci compute instance launch \
      --compartment-id "$COMPARTMENT_ID" \
      --availability-domain "$ad_trimmed" \
      --shape "$SHAPE" \
      --shape-config "{\"ocpus\": $OCPUS, \"memoryInGBs\": $MEMORY_GB}" \
      --display-name "$INSTANCE_NAME" \
      --image-id "$IMAGE_ID" \
      --subnet-id "$SUBNET_ID" \
      --ssh-authorized-keys-file "$SSH_PUBLIC_KEY_FILE" \
      --assign-public-ip true \
      2>&1)
    status=$?

    if [ $status -eq 0 ]; then
      log "성공! 인스턴스가 생성됐다."
      echo "$output"
      exit 0
    fi

    if echo "$output" | grep -qi "Out of host capacity"; then
      log "Out of host capacity ($ad_trimmed) — 다음 AD/재시도로 넘어감"
      continue
    fi

    if echo "$output" | grep -qi "TooManyRequests\|status.*429"; then
      log "API rate limit(429) — 다음 재시도로 넘어감"
      continue
    fi

    log "예상치 못한 에러 — 재시도를 멈추고 원인을 확인해야 함:"
    echo "$output"
    exit 1
  done

  log "모든 AD에서 capacity 없음. ${RETRY_INTERVAL_SECONDS}초 후 재시도."
  sleep "$RETRY_INTERVAL_SECONDS"
done
