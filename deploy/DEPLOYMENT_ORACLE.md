# Oracle Cloud 무료 VM 배포 가이드

Codespace를 꺼도 Streamlit 앱 + `scheduler/run_scheduler.py`(관심종목 스캔·주간 리포트·시장 스냅샷·
야간 미세튜닝)가 계속 돌게 하기 위한 절차. DB는 별도 서버 없이 지금과 동일한 로컬 SQLite
(`data/quant.db`)를 VM의 로컬 디스크에 그대로 둔다 — 이 규모(수백 종목 × 수년 일봉)에서는 관리형
DB로 옮길 필요가 없다.

계정 가입·VM 발급·SSH 접속은 본인만 할 수 있는 단계라 아래는 직접 따라 하는 가이드다. 리포에 있는
`deploy/setup_vm.sh` 는 그중 반복 작업(패키지 설치/systemd 등록/방화벽)만 대신 해준다.

## 0. 사전 준비

- Oracle Cloud 계정 (신용카드 등록은 필요하지만 Always Free 리소스는 과금되지 않음)
- 로컬에 SSH 키 페어 (`ssh-keygen -t ed25519` 로 없으면 생성)
- 이 리포에 대한 git 접근 권한(비공개 리포면 GitHub PAT 또는 배포용 SSH 키)

## 1. Oracle Cloud VM 발급 (Always Free)

1. https://cloud.oracle.com 가입 → 홈 리전 선택(가까운 리전, 이후 변경 어려움).
2. 콘솔 → **Compute → Instances → Create Instance**.
3. Image: **Ubuntu 24.04** (또는 최신 LTS).
4. Shape: **Change Shape → Ampere → VM.Standard.A1.Flex** 선택 후 OCPU 2 / Memory 12GB로 맞춘다
   (2026-06-15부로 Always Free 한도가 4 OCPU/24GB → 2 OCPU/12GB로 축소됨 — Always Free 표시가 붙는
   조합만 골라야 과금되지 않는다).
5. Boot volume: 기본값 사용 (Always Free 총 200GB 블록스토리지 한도 안에서 조정 가능).
6. SSH 키: 로컬 공개키(`~/.ssh/id_ed25519.pub`) 업로드.
7. **Create** → 프로비저닝 완료 후 Public IP 확인.

### 1-1. (자주 발생) "Out of host capacity" 에러 시 자동 재시도

A1.Flex는 인기 리전에서 수요가 많아 콘솔에서 바로 생성하면 `Out of host capacity` 에러가 흔하다.
`deploy/oracle_capacity_retry.sh`가 OCI CLI로 인스턴스 생성을 반복 시도한다(기본 60초 간격, capacity
에러가 아닌 다른 결과가 나오면 멈춤).

```bash
# 로컬 머신(또는 어디서든 계속 켜둘 수 있는 환경)에서
brew install oci-cli   # 또는 pip install oci-cli
oci setup config       # 콘솔 Profile > API Keys 에서 발급한 키로 인증 설정

export COMPARTMENT_ID=ocid1.compartment...        # Identity > Compartments
export IMAGE_ID=ocid1.image...                     # Compute > Images (Ubuntu 24.04 aarch64)
export SUBNET_ID=ocid1.subnet...                    # Networking > VCN > Subnets
export AVAILABILITY_DOMAINS="AD-1,AD-2,AD-3"        # 콤마로 여러 AD 순회 (Create Instance 화면에 표시됨)
# SSH_PUBLIC_KEY_FILE 기본값은 ~/.ssh/id_ed25519.pub, 필요시 덮어쓰기

bash deploy/oracle_capacity_retry.sh
```

성공하면 인스턴스 OCID/Public IP가 출력된다. 이후 단계는 아래 2번부터 그대로 진행.

## 2. 네트워크(방화벽) 설정 — 콘솔 쪽

OS 방화벽(`setup_vm.sh`가 ufw로 처리)과는 별개로, Oracle 콘솔의 **VCN Security List**(또는 VM에
붙은 NSG)에서도 인그레스 규칙을 열어야 외부에서 접속된다.

1. 콘솔 → **Networking → Virtual Cloud Networks** → 해당 VCN → **Security Lists** → Default
   Security List.
2. **Add Ingress Rules**:
   - Source CIDR `0.0.0.0/0`, IP Protocol `TCP`, Destination Port `8501` (Streamlit)
   - (SSH용 22번은 기본 이미지 생성 시 이미 열려 있음)

## 3. SSH 접속 + 리포 클론 + .env 준비

```bash
ssh ubuntu@<PUBLIC_IP>
sudo git clone <이 리포 URL> /opt/quant
cd /opt/quant
sudo cp .env.example .env
sudo nano .env   # FRED_API_KEY / GEMINI_API_KEYS 등 실제 값 채우기
```

`.env`는 git에 커밋되지 않는 파일이라 로컬에서 쓰던 값을 그대로 복사해 붙여넣으면 된다
(`scp .env ubuntu@<PUBLIC_IP>:/tmp/.env` 로 옮긴 뒤 `sudo mv /tmp/.env /opt/quant/.env` 도 가능).

## 4. 자동 설정 스크립트 실행

```bash
cd /opt/quant
sudo bash deploy/setup_vm.sh
```

이 스크립트가 하는 일:
- Python 3.12 + venv 생성, `requirements.txt` 설치
- 전용 시스템 계정(`quant`)으로 서비스 실행(root로 앱을 돌리지 않기 위함)
- `deploy/quant-streamlit.service` / `deploy/quant-scheduler.service` 를 systemd에 등록해
  **부팅 시 자동 시작 + 죽으면 자동 재시작**하도록 설정
- OS 방화벽(ufw)에서 8501 허용

## 5. 확인

```bash
sudo systemctl status quant-streamlit
sudo systemctl status quant-scheduler
sudo journalctl -u quant-scheduler -f   # 스케줄러 실시간 로그(장 마감 스캔/야간 튜닝 등)
```

브라우저에서 `http://<PUBLIC_IP>:8501` 접속되면 성공. `data/quant.db` 는 최초 접속 시
`core.db.init_db()` 가 자동 생성한다.

## 6. 코드 업데이트 배포

로컬(또는 Codespace)에서 작업한 변경사항을 반영하려면:

```bash
ssh ubuntu@<PUBLIC_IP>
cd /opt/quant
sudo git pull
sudo -u quant .venv/bin/pip install -r requirements.txt   # 의존성 바뀐 경우만
sudo systemctl restart quant-streamlit quant-scheduler
```

## 7. GitHub Actions 야간 튜닝과의 관계

`.github/workflows/nightly_tuning.yml` (매일 00:05 KST)은 이 VM과 **완전히 독립적으로** 계속
동작한다 — GitHub 서버에서 실행되고 결과를 `data/nightly_tuning_leaderboard.json`으로 리포에
커밋한다. `scheduler/run_scheduler.py`의 `strategy_nightly_tuning_job()`은 이 VM의 로컬 SQLite
(`StrategyTuningRun`/`StrategyTuningResult`)에 별도로 쌓인다 — 저장소가 다른 두 결과지만,
`app/pages/13_야간_미세튜닝_리더보드.py`가 이미 **둘을 합쳐서** 보여주도록 짜여 있다(로컬 DB
결과 + 커밋된 JSON을 함께 읽어 test 구간 초과수익 기준 상위 10개를 뽑음). 이 VM에서
`git pull`만 해두면 GitHub Actions 쪽 결과도 자동으로 리더보드에 반영된다 — 아무 설정도 추가로
필요 없다.

## 8. (선택) HTTPS/도메인

지금은 `http://<PUBLIC_IP>:8501`로 평문 접속이다. 본인만 쓰는 대시보드라면 이 상태로도 충분하지만,
도메인을 붙이고 싶으면 nginx를 리버스 프록시로 두고 Let's Encrypt(`certbot`)로 인증서를 발급받는
방식이 표준적이다 — 필요해지면 별도로 셋업해줄 수 있다.

## 9. 백업

`data/quant.db` 하나가 전략/알림 이력/야간튜닝 결과의 전부다. 유실 방지를 위해 가끔
`scp ubuntu@<PUBLIC_IP>:/opt/quant/data/quant.db ./backup/quant-$(date +%F).db` 로 로컬에 받아
두는 것을 권장한다(자동화는 필요해지면 cron으로 추가 가능).

## 10. (신규, 2026-09-14) 리서치 에이전트 자동화 — 매일 밤 무인으로 Claude Code 실행

`deploy/research_agents/`에 매일 한국시간 00:20에 Claude Code CLI를 무인으로 두 번(에이전트
B/C 각각) 실행해 새 정량 리서치 리포트를 생성하는 systemd 타이머 두 개가 정의돼 있다. API 키
과금이 아니라 **사용자의 Claude Pro/Max 구독 로그인**으로 동작한다(이 VM의 대화형 CLI 로그인은
1회만 사람이 직접 해야 함 — 아래 참고).

- `agent_b_market_portfolio.md` / `agent_c_tenbagger.md`: 각 에이전트의 페르소나·규칙·"아직
  안 풀린 문제" 목록을 담은 프롬프트. 이 저장소의 `analysis/`에 쌓인 기존 리서치 방법론(순열검정+
  블록부트스트랩 이중검증, point-in-time 유니버스, 확신도 등급, 자기회의적 태도)을 그대로
  이어가도록 지시한다. 결과물은 **git commit/push를 하지 않고** 워킹트리에만 쌓인다.
- `run_research_agent.sh`: `claude -p "<프롬프트>" --dangerously-skip-permissions`로 헤드리스
  실행 후 `pytest tests/ -q` 회귀 확인 + `notify_if_accumulated.py` 호출.
- `notify_if_accumulated.py`: `analysis/` 밑에 아직 커밋되지 않은(untracked) 새 리포트 폴더가
  마지막 알림 이후 3개 이상 쌓이면 텔레그램으로 한 번에 알린다(매번 알리면 스팸이 되므로).
- "사용량 한도에 걸리면 초기화 후 이어서 계속" 동작은 별도 재시도 로직 없이 **Claude Code 자체
  설정**(`autoContinueAtUsageLimit: true`)에 맡긴다 — 아래 3단계에서 설정한다.

**1단계 — Claude Code CLI 설치** (VM에 SSH 접속 후):
```bash
sudo apt-get install -y nodejs npm   # 이미 있으면 생략
sudo npm install -g @anthropic-ai/claude-code
```

**2단계 — `quant` 서비스 계정으로 로그인** (대화형, 1회만 — 이건 사람이 직접 해야 함):
```bash
sudo -u quant claude login
```
브라우저가 없는 서버라 화면에 인증 URL과 코드가 뜬다 — 그 URL을 본인 휴대폰/PC 브라우저로 열어
로그인하고 코드를 입력하면 된다. `quant` 계정의 `$HOME`이 `/opt/quant`로 설정돼 있어
(`deploy/setup_vm.sh`가 만듦) 자격증명이 `/opt/quant/.claude/`에 저장되고, 이후 systemd 서비스
(`User=quant`로 실행)도 같은 자격증명을 그대로 쓴다.

**3단계 — 사용량 한도 자동 대기 설정**:
```bash
sudo -u quant mkdir -p /opt/quant/.claude
# 기존 설정이 있으면 덮어쓰지 말고 "autoContinueAtUsageLimit": true 를 손으로 병합해 추가할 것
sudo -u quant tee -a /opt/quant/.claude/settings.json <<'EOF'
{"autoContinueAtUsageLimit": true}
EOF
```
(`/opt/quant/.claude/settings.json`이 이미 존재하면 `cat`으로 먼저 내용을 확인하고 JSON을
직접 병합하세요 — 위 명령은 파일이 없을 때만 안전합니다.)

**4단계 — systemd 등록**:
```bash
sudo cp /opt/quant/deploy/research_agents/quant-research-agent-b.service /etc/systemd/system/
sudo cp /opt/quant/deploy/research_agents/quant-research-agent-b.timer /etc/systemd/system/
sudo cp /opt/quant/deploy/research_agents/quant-research-agent-c.service /etc/systemd/system/
sudo cp /opt/quant/deploy/research_agents/quant-research-agent-c.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now quant-research-agent-b.timer quant-research-agent-c.timer
```

**5단계 — 확인**:
```bash
systemctl list-timers | grep quant-research   # 다음 실행 예정 시각 확인
# 당장 한 번 수동으로 테스트해보려면(타이머 안 기다리고):
sudo systemctl start quant-research-agent-b.service
journalctl -u quant-research-agent-b -f   # 실시간 로그(claude 세션 출력 포함)
```

**결과물 검토**: 매일 밤 `analysis/YYYY-MM-DD_*/` 밑에 새 폴더가 쌓인다(자동 커밋 안 됨). 3개
이상 쌓이면 텔레그램으로 알림이 온다 — `git status`로 확인하고, 검토 후 원하는 것만 직접
`git add`/`commit`/`push`하면 된다.
