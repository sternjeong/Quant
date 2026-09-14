# Telegram → Codex 무인 작업 파이프라인

이 서비스는 Telegram private chat의 새 텍스트 메시지를 SQLite 영속 큐에 기록하고, 프로젝트별로
하나씩 Codex CLI 작업자로 실행한다. Long polling을 사용하므로 공개 webhook URL·TLS 인증서가
필요 없고, 작업자가 실행 중이어도 수신 루프는 계속 메시지를 저장한다.

## 설치

1. `/opt/quant/.codex-telegram-runtime/telegram.env`에 다음 값을 둔다 (권한 `0600`).
   기존 `.env`를 쓰려면 설정의 `env_file`을 해당 경로로 바꾼다. 값은 절대 커밋하지 않는다.

   ```dotenv
   TELEGRAM_BOT_TOKEN=123456:replace-with-bot-token
   TELEGRAM_CHAT_ID=your-numeric-private-chat-id
   ```

2. Codex CLI를 프로젝트 전용 위치에 설치한다.

   ```bash
   sudo -u quant npm install --prefix /opt/quant/.codex-telegram-runtime @openai/codex@0.154.0
   ```

3. `config.example.json`을 `config.json`으로 복사해 프로젝트 별칭과 경로를 검토한다. 이 파일은
   gitignore 대상이며 권한은 `0600`이어야 한다. `projects`에 등록된 별칭만 `/project 별칭`으로
   선택할 수 있다. 기본값은 `quant`다.

4. 실제 Ubuntu 호스트에서 `./install.sh`를 실행한다. 이것은 unit을 `/etc/systemd/system`에 설치하고
   `enable --now` 한다. 이후 상태와 로그는 다음으로 확인한다.

   ```bash
   sudo systemctl status codex-telegram
   sudo journalctl -u codex-telegram -f
   ```

Codex 인증은 전용 `codex_home`에 둔다. 새 설치에서는 다음으로 인증한다.

```bash
sudo install -d -m 700 -o quant -g quant /opt/quant/.codex-telegram-runtime/auth
sudo -u quant env CODEX_HOME=/opt/quant/.codex-telegram-runtime/auth /opt/quant/.codex-telegram-runtime/node_modules/.bin/codex login --device-auth
```

설정이 없더라도 unit은 설치되고 자동 시작이 등록된다. Telegram 설정이 없으면 30초 간격으로
재시작하며 기다린다. Codex 인증 오류 작업은 `blocked`로 남으므로 인증 후 아래 방법으로 재개한다.
2026-09-14 구축에서는 기존 작업 환경의 Telegram 설정과 Codex 인증을 SSH로 전용 경로에 전달했다.

## 메시지와 작업 순서

평문 메시지는 기본 프로젝트에 큐잉된다. 다른 등록 프로젝트는 첫 행을 아래처럼 사용한다.

```text
/project quant
README의 오류를 고치고 테스트 후 커밋과 push까지 해줘.
```

동일 프로젝트는 앞선 작업이 `queued`, `running`, `retry`, `blocked`이면 뒤 작업을 실행하지 않는다.
`blocked` 작업은 오류를 해결한 뒤 큐 SQLite에서 상태를 조정하는 운영자 개입이 필요하다. 이는
서로 다른 지시가 같은 작업 트리를 동시에 바꾸는 일을 막는다.

인증/권한 오류 해결 뒤 특정 작업을 재개하는 예시 (`123`은 실제 작업 ID로 교체):

```bash
sudo -u quant sqlite3 /opt/quant/.codex-telegram-state/queue.sqlite "UPDATE jobs SET status='retry',due=0,notified=0 WHERE id=123 AND status='blocked';"
```

등록 프로젝트는 작업자 한 개가 순서대로 실행한다. 재시도 대기 중에는 다른 프로젝트를 실행할 수
있으며, 동일 프로젝트는 앞선 작업 완료까지 대기한다. 실행 중 서비스가 죽으면 systemd가 하위
프로세스까지 정리하고 재시작 시 `running` 작업을 재개한다. SQLite 큐와 수신 offset은 함께 커밋한다.

## 사용량 한도 재개

Codex CLI 0.154.0의 설치 바이너리 문자열에서 다음 식별자를 확인했다:
`usage_limit_exceeded`, `rate_limit_exceeded`, `workspace_owner_usage_limit_reached`, 그리고
`You've hit your usage limit.`. 래퍼는 JSON event의 오류와 일반 출력에서 이 패턴 및 HTTP 429를
검사한다. 한도 전용 종료 코드는 확인되지 않았으므로 종료 코드만으로 판정하지 않는다.
일반 작업 출력의 JSON `item`은 한도 판정에서 제외해, 코드나 문서에 들어 있는 오류 문구를 오인하지 않는다.

한도에 걸리거나 중단되면 작업은 `retry`가 된다. 첫 대기는 15분이고, 이후 배수로 늘어나며 최대
1시간마다 재시도한다. 정확한 사용량 초기화 주기는 계정·요금제별 공개 보장이 없으므로 이 보수적
재시도 방식으로 구성했다. 재시도 전 `RESUME_NOTE.md`가 있으면 Codex에게 그것을 먼저 읽도록
지시한다. 정상 완료 시 작업자가 파일을 삭제해야 하고, 다음 시도 시작 전 파일이 없다면 그 작업은
완료로 확정되어 더 이상 재시도하지 않는다.

작업 시작 전 래퍼도 초기 메모를 만들어, 모델이 첫 응답 전 차단되어도 재개 지점이 남도록 한다.
정확한 진행 내용은 작업자가 중요 단계마다 갱신한다. 메모 삭제는 완료 신호이므로 운영자가 임의로
지우면 재시도가 종료된다. 인증 실패, 잘못된 CLI 등 일반 오류는 무한 재시도하지 않고 `blocked`로 알린다.

원본 이벤트와 Codex의 원시 출력은 저장하지 않고 `--ephemeral`로 CLI 세션 파일 저장도 끈다.
완료 요약은 설정 파일의 알려진 비밀 값과 키 패턴을 가린 후 Telegram으로 보낸다. 이는 모든 임의의
비밀을 탐지하는 보장은 아니므로 작업자 지침 역시 인증 정보 출력과 커밋을 금지한다.

## 실행 명령 근거

설치된 `codex-cli 0.154.0`의 `--help`, `exec --help`를 직접 확인했다. 실행 형태는 다음과 같다.
프롬프트는 stdin, 사용자 지정 작업자 프롬프트 원문은 `developer_instructions` 설정으로 전달한다.

```text
codex -a never exec --ephemeral --json --color never -s danger-full-access -C PROJECT -c sandbox_workspace_write.network_access=true -c developer_instructions=TOML_STRING -
```

공식 문서: [비대화형 실행](https://developers.openai.com/codex/noninteractive),
[CLI 명령](https://developers.openai.com/codex/cli/reference).
초기화 시각을 추정한 고정 시간표는 사용하지 않으며, 실제 한도 해제 여부는 다음 실행으로 확인한다.
서버 관리와 무인 Git 쓰기를 위해 작업자는 `quant` OS 계정 권한으로 실행하며 CLI sandbox는
사용하지 않는다. 승인 입력은 `never`다. 작업자 프롬프트의 파괴적 명령 금지는 행동 지침이며
OS 차원의 차단은 아니다. `sandbox`를 `workspace-write`로 바꿀 수 있지만 경계 밖 작업은 실패할 수 있다.

## 확인

```bash
python3 -m unittest discover -s deploy/codex_telegram -p 'test_*.py' -v
python3 deploy/codex_telegram/smoke.py
```

`smoke.py`는 임시 bare Git origin과 임시 프로젝트를 만들고, 실제 Codex CLI에 합성 Telegram
update를 전달한다. 파일 생성, commit, push, `RESUME_NOTE.md` 삭제까지 확인하면 exit 0이다.
실제 한도에 걸려 `retry`로 남으면 exit 2이며, 이는 중단 처리 확인이지 작업 완료 성공이 아니다.
exit 1은 실행 실패다. 임시 프로젝트와 큐는 조사할 수 있도록 출력된 경로에 남긴다.

호스트 테스트에는 `CODEX_HOME=/opt/quant/.codex-telegram-runtime/auth`를 지정한다.

2026-09-14 검증 결과:

- 단위 테스트 5개 통과: 허용 채팅/중복 수신, 오류 분류, 한도 후 실제 두 번째 worker 호출,
  메모 삭제 시 중지, 일반 실행 오류 보류.
- 합성 Telegram update가 실제 Codex CLI로 전달됨. 실제 사용량 한도로 `retry`와 메모 보존 확인.
  정상 작업 완료 및 모델에 의한 commit/push는 한도 해제 전이므로 미검증.
- 실제 봇 `getMe` 인증 성공, webhook 미설정 확인 후 long polling 활성화.
- `quant-vm`에서 systemd `enabled`, `active (running)` 확인.
  메인 프로세스 SIGKILL 후 30초 뒤 새 PID와 `NRestarts=1` 확인.
  호스트 재부팅 자체는 기존 서비스를 중단시키므로 실시하지 않았다.
