#!/usr/bin/env bash
# 리서치 에이전트(B/C/D/E/F/G/H) 하나를 무인으로 실행하는 래퍼 스크립트.
#
# 사용법: run_research_agent.sh <agent-name> <prompt-file> [effort-level]
#   예: run_research_agent.sh b agent_b_market_portfolio.md
#   예: run_research_agent.sh g agent_g_methodology_auditor.md high
#
# - claude CLI를 헤드리스(-p, 비대화형)로 실행하고, 권한 확인 프롬프트를 건너뛴다
#   (--dangerously-skip-permissions — 무인 서버 실행이라 매번 사람이 승인할 수 없음).
# - "최대한 사용량을 소진하고, 한도에 걸리면 초기화 후 이어서 계속" 동작은 claude 자체 설정
#   (autoContinueAtUsageLimit=true, 이 VM의 ~/.claude/settings.json에 설정해둠)이 담당한다 —
#   이 스크립트가 재시도 로직을 따로 구현하지 않는다.
# - effort-level(선택, 2026-09-14 추가): "더 고도의 추론"이 필요한 에이전트(G/H — 메타 감사/
#   학술 문헌 대조)에 --effort 플래그로 추론 강도를 높인다(예: high). 안 주면 계정 기본값 사용.
# - 실행이 끝나면(성공/실패 무관) notify_if_accumulated.py를 호출해, analysis/ 밑에 아직
#   커밋 안 된 새 리포트가 일정 개수 이상 쌓였으면 텔레그램으로 한 번에 알린다.
set -uo pipefail

AGENT_NAME="${1:?agent name required (b|c|d|e|f|g|h)}"
PROMPT_FILE="${2:?prompt file required}"
EFFORT_LEVEL="${3:-}"

PROJECT_ROOT="/opt/quant"
PROMPT_PATH="${PROJECT_ROOT}/deploy/research_agents/${PROMPT_FILE}"
LOG_DIR="${PROJECT_ROOT}/data/cache/research_agent_logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/agent_${AGENT_NAME}_$(date +%Y%m%d_%H%M%S).log"

cd "${PROJECT_ROOT}" || exit 1

EFFORT_ARGS=()
if [ -n "${EFFORT_LEVEL}" ]; then
    EFFORT_ARGS=(--effort "${EFFORT_LEVEL}")
fi

echo "[$(date)] 리서치 에이전트 ${AGENT_NAME} 시작 (프롬프트: ${PROMPT_FILE}, effort: ${EFFORT_LEVEL:-기본값})" | tee -a "${LOG_FILE}"

claude -p "$(cat "${PROMPT_PATH}")" \
    --dangerously-skip-permissions \
    "${EFFORT_ARGS[@]}" \
    >> "${LOG_FILE}" 2>&1
CLAUDE_EXIT_CODE=$?

echo "[$(date)] 리서치 에이전트 ${AGENT_NAME} 종료 (exit code: ${CLAUDE_EXIT_CODE})" | tee -a "${LOG_FILE}"

# 회귀 확인(에이전트가 core/*.py를 건드렸을 수 있으므로) — 실패해도 알림은 계속 보낸다.
"${PROJECT_ROOT}/.venv/bin/python" -m pytest tests/ -q >> "${LOG_FILE}" 2>&1
echo "[$(date)] pytest 결과는 ${LOG_FILE} 참고" | tee -a "${LOG_FILE}"

"${PROJECT_ROOT}/.venv/bin/python" "${PROJECT_ROOT}/deploy/research_agents/notify_if_accumulated.py" \
    --agent "${AGENT_NAME}" >> "${LOG_FILE}" 2>&1

exit 0
