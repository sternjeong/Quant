# 대기 중인 수동 로그인/승인 작업

무인 에이전트(Telegram → Claude/Codex)는 대화형 OAuth 로그인, `sudo`, 타 서버 SSH 로그인을
대신 할 수 없다. 이 문서는 그래서 사람이 직접 로그인해서 처리해야 남아있는 항목만 모은 목록이다.
완료했으면 해당 항목을 지우고 `PROGRESS.md`에 짧게 기록해두면 된다.

> **2026-09-16 확인**: 이 Telegram→Claude 무인 에이전트 자체가 Oracle 배포 VM
> (`138.2.11.196`)의 `quant` 계정으로 직접 돈다 (`codex-telegram.service`, `/opt/quant`).
> 즉 아래 항목들을 처리할 때 **별도 SSH 로그인은 이미 필요 없고, `quant` 계정의 sudo 비밀번호만
> 있으면 된다** (`sudo -n true` → `a password is required`로 확인, passwordless sudo 아님).
> 이번에 사람이 sudo로 로그인한 뒤 그 세션에서 비밀번호를 입력해 아래 명령만 실행하면 된다.

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

## 2. Oracle 배포 VM 코드 최신화 (`sudo`로 서비스 재시작만 남음)

- **문제**: 라이브 VM(`138.2.11.196`)의 `quant-streamlit`/`quant-scheduler`가 오래된 커밋
  (`8004880`)에 멈춰 있어 이후 머지된 기능(텔레그램 신호알림, 거장 교차참조 배지, FRED 지표
  새벽 사전예열 등)이 실제 서비스에 반영돼 있지 않았다.
- **2026-09-16에 무인 에이전트가 이미 처리함**: `/opt/quant`에서 `git pull --ff-only`로
  코드를 최신(`ef314e8`, origin/main과 동일)까지 당겨왔다. `requirements.txt`/`pyproject.toml`은
  `8004880..ef314e8` 사이에 변경 없음 — `pip install` 재실행 불필요. (사전 확인 결과
  `deploy/codex_telegram/*` 5개 파일은 diff가 있었지만 실제로는 이미 origin/main과 바이트
  단위로 동일한 내용이었음 — 에이전트가 `git status` 기준으로만 판단하지 않고 `git diff
  origin/main -- <files>`로 직접 대조해 안전을 확인한 뒤 진행했다.)
- **남은 조치 (사람이 sudo로만 가능)**:
  ```bash
  # 138.2.11.196에 quant 계정으로 이미 로그인되어 있다고 가정 (별도 SSH 불필요, sudo 비밀번호만)
  cd /opt/quant
  sudo systemctl restart quant-streamlit quant-scheduler
  ```
  (`deploy/DEPLOYMENT_ORACLE.md` 6번 절차 중 재시작 단계만 남음)

## 3. GitHub Actions 나이틀리 리서치 자동화 (GitHub 웹 로그인 + Secrets 등록, 미착수 — 우선순위 낮음)

- **배경**: Codespace 기반 리서치 에이전트 실행은 Codespace가 idle 타임아웃으로 꺼지면 멈춘다 —
  "매일 밤 자동 실행"이 필요하면 사용자가 매번 Codespace를 열어야 하는 한계가 있다.
- **대안**: 기존 `.github/workflows/nightly_tuning.yml`과 같은 GitHub Actions 스케줄 워크플로
  방식(VM/Codespace 상시 기동 불필요). 다만 Claude Pro 로그인 자격증명을 GitHub Secrets로
  안전하게 주입하는 작업이 아직 없다.
- **조치**: GitHub 웹에 로그인 → 저장소 Settings → Secrets and variables → Actions에 자격증명
  등록 → 대응 워크플로 yml 신규 작성(현재 없음). 원할 때만 진행.
- **2026-09-16**: 사용자가 "결제가 필요한 것은 제외"라는 조건으로 나머지 항목 실행을 허용해서
  검토했음. 이 항목은 GitHub Actions에서 Claude/Codex를 매일 밤 자동 실행하는 구조라 API/Actions
  사용량 과금이 계속 발생한다 — 조건에 걸려 이번에 진행하지 않았다. 정말 원하면 다음에 명시적으로
  "결제 발생해도 진행"이라고 지시해야 한다.

## 4. ~~관제 허브(hub/) 신규 배포~~ — 2026-09-20 완료

`quant-hub.service` 설치, nginx 사이트를 허브(127.0.0.1:8000)로 교체, `deploy/auto_deploy.sh`의
`SERVICES`에 `quant-hub` 추가까지 전부 끝났다. `http://138.2.11.196/`에서 관제 센터가 뜨고
`:8501` Streamlit도 그대로 동작함을 확인했다. 이후 `hub/*.py` 변경도 자동배포로 재시작까지 반영된다.

## 5. 브라우저 코드 스페이스(code-server) 외부 접속 허용 — `sudo` + Oracle 콘솔 필요

- **배경**: 텔레그램 지시("내 vm에 브라우저 코드 스페이스도 만들어주라, Github Codespaces를
  모방해서")로 조사해보니 `code-server`(VS Code 브라우저 버전)가 이미 `ubuntu` 계정으로
  `code-server@ubuntu.service`가 1주일 넘게 떠 있었다(`127.0.0.1:8080`만 바인딩, 외부 접속 불가
  상태). 이 자동화 계정(`quant`)은 `/home/ubuntu/`를 읽을 권한이 없고 sudo도 안 돼서 비밀번호
  확인·bind-addr 변경·서비스 재시작을 대신 할 수 없다.
- **지금 당장 쓰는 법 (조치 불필요, 가장 안전)**: `ssh -L 8080:localhost:8080 ubuntu@138.2.11.196`
  터널을 연 뒤 로컬에서 `http://localhost:8080` 접속. 자세한 내용은
  `deploy/DEPLOYMENT_ORACLE.md` 14번.
- **브라우저 주소(터널 없이)로도 열고 싶다면, 조치** (`138.2.11.196`에 `sudo` 가능한 계정으로
  로그인 후):
  ```bash
  # 1) 비밀번호 확인/교체 (약하면 openssl rand -base64 24 등으로 새로 생성해 password: 에 넣기)
  sudo cat /home/ubuntu/.config/code-server/config.yaml

  # 2) 외부에서 접속되도록 바인드 주소 변경
  sudo sed -i 's/^bind-addr: 127.0.0.1:8080/bind-addr: 0.0.0.0:8080/' \
    /home/ubuntu/.config/code-server/config.yaml
  sudo systemctl restart code-server@ubuntu
  sudo systemctl status code-server@ubuntu --no-pager   # active (running) 확인

  # 3) OS 방화벽
  sudo ufw allow 8080/tcp
  ```
  그리고 Oracle Cloud 콘솔 → Networking → Virtual Cloud Networks → 해당 VCN → Security Lists →
  Default Security List → Add Ingress Rules에서 `0.0.0.0/0` / TCP / `8080` 규칙을 추가한다
  (`deploy/DEPLOYMENT_ORACLE.md` 2번과 동일한 절차, 포트만 8080).
- **확인**: 브라우저에서 `http://138.2.11.196:8080/` 접속 → code-server 로그인 화면이 뜨고
  비밀번호 입력 후 VS Code 화면이 열리면 성공. 허브(`http://138.2.11.196/`, 아직 4번 미완료면
  안 뜸)를 먼저 배포했다면 "브라우저 코드 스페이스" 카드로도 바로 연결된다
  (`hub/apps_registry.py`에 이미 슬롯 등록해둠, 별도 코드 변경 불필요).
- **보안 참고**: 이 VM엔 도메인/TLS가 없어 평문 HTTP로 노출된다 — 비밀번호가 충분히 강한지
  1번 단계에서 반드시 확인/교체할 것. 신뢰 안 되는 네트워크에서 접속할 땐 SSH 터널 방식을 쓰는
  게 낫다.
