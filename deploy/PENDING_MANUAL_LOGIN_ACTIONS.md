# 대기 중인 수동 로그인/승인 작업

무인 에이전트(Telegram → Claude/Codex)는 대화형 OAuth 로그인, `sudo`, 타 서버 SSH 로그인을
대신 할 수 없다. 이 문서는 그래서 사람이 직접 로그인해서 처리해야 남아있는 항목만 모은 목록이다.
완료했으면 해당 항목을 지우고 `PROGRESS.md`에 짧게 기록해두면 된다.

## 1. 리서치 에이전트 B/C 야간 systemd 타이머 복구 (Oracle VM, `sudo` 필요)

- **문제**: `quant-research-agent-{b,c}.service`/`.timer` 4개 파일이 `/etc/systemd/system/`에서
  통째로 사라졌다(`timers.target.wants/`의 심볼릭 링크는 남아 `not-found`로 뜸). 원인 미상 —
  작업65가 수동으로 `cp`+`enable`했을 뿐 `deploy/setup_vm.sh`엔 원래 이 설치 단계가 없었다.
  확인: `systemctl list-timers | grep quant-research-agent` (현재 아무것도 안 뜸).
- **조치** (VM에 `ubuntu`/sudo 가능 계정으로 로그인 후):
  ```bash
  sudo bash /opt/quant/deploy/setup_vm.sh   # [5/6] 단계에 재설치 로직 추가해둠 (작업75)
  # 또는 수동으로:
  sudo cp /opt/quant/deploy/research_agents/quant-research-agent-{b,c}.{service,timer} /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable --now quant-research-agent-b.timer quant-research-agent-c.timer
  ```
- **참고**: 2026-09-15 08:48 UTC에 이 타이머 대신 수동으로 한 번 기동한 B/C는 이미 완료됨.
  `/opt/quant` 워킹트리에 결과 리포트 4개(`analysis/2026-09-14_nonai_control_basket_volatility_momentum/`,
  `analysis/2026-09-14_satellite_correlation_crisis_signal/`,
  `analysis/2026-09-15_options_collar_hedge_volatility_momentum_basket/`,
  `analysis/2026-09-15_options_collar_parameter_sensitivity/`)가 미커밋 상태로 쌓여 있으니
  검토 후 직접 커밋 필요(에이전트 페르소나 규칙상 스스로 commit/push 안 함).
- **아키텍처 참고**: 작업67에서 한 번 "리서치 에이전트는 VM이 아니라 Codespace에서 돈다"고
  정정하며 VM에서 제거했었는데, 이후(작업65 계열 운영 흐름) 다시 VM 상주 systemd 타이머로
  돌아간 상태다. 이 모순은 이 메모가 판단할 범위가 아니니, 복구 전에 "정말 VM에서 계속 돌릴지"
  먼저 확인하고 진행하는 게 안전하다.

## 2. Oracle 배포 VM 코드 최신화 (SSH 로그인 필요)

- **문제**: 라이브 VM(`138.2.11.196`)의 `quant-streamlit`/`quant-scheduler`가 오래된 커밋에
  멈춰 있어 이후 머지된 기능(텔레그램 신호알림, 거장 교차참조 배지, FRED 지표 새벽 사전예열 등)이
  실제 서비스에 반영돼 있지 않다.
- **조치**:
  ```bash
  ssh ubuntu@138.2.11.196
  cd /opt/quant
  sudo git pull
  sudo -u quant .venv/bin/pip install -r requirements.txt   # 의존성 바뀐 경우만
  sudo systemctl restart quant-streamlit quant-scheduler
  ```
  (`deploy/DEPLOYMENT_ORACLE.md` 6번 절차와 동일)

## 3. GitHub Actions 나이틀리 리서치 자동화 (GitHub 웹 로그인 + Secrets 등록, 미착수 — 우선순위 낮음)

- **배경**: Codespace 기반 리서치 에이전트 실행은 Codespace가 idle 타임아웃으로 꺼지면 멈춘다 —
  "매일 밤 자동 실행"이 필요하면 사용자가 매번 Codespace를 열어야 하는 한계가 있다.
- **대안**: 기존 `.github/workflows/nightly_tuning.yml`과 같은 GitHub Actions 스케줄 워크플로
  방식(VM/Codespace 상시 기동 불필요). 다만 Claude Pro 로그인 자격증명을 GitHub Secrets로
  안전하게 주입하는 작업이 아직 없다.
- **조치**: GitHub 웹에 로그인 → 저장소 Settings → Secrets and variables → Actions에 자격증명
  등록 → 대응 워크플로 yml 신규 작성(현재 없음). 원할 때만 진행.
