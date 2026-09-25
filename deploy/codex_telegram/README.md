# Telegram → Codex / Claude 무인 작업 파이프라인

## 실행 대상과 응답

`repository_selection: true`이면 일반 지시를 받은 봇은 먼저 GitHub 저장소 목록을 inline 버튼으로
표시한다. 저장소를 고른 뒤 Claude 또는 Codex를 선택한다. `＋ 새 private 저장소 만들기`를 고르면
다음 메시지로 이름을 받아 `gh repo create OWNER/NAME --private`를 실행하고 같은 선택 단계로 돌아온다.
선택한 기존 저장소는 `/opt/quant/repositories/OWNER/NAME`에 최초 한 번 clone한다. GitHub 계정은
`gh auth login`과 `gh auth setup-git`으로 `quant` 사용자에 로그인되어 있어야 한다.
기본 작업자는 `default_backend`의 Claude이며, 매 작업 버튼에서 Codex로 바꿀 수 있다. `/status`로
작업 번호와 상태를 확인하고, 인증·권한 문제로 `blocked`가 된 작업은 `/retry 작업번호`로 재개한다.

기존 `/project quant` 방식은 저장소 선택 없이 현재 Quant 작업 공간을 직접 선택하는 고급 경로로
계속 사용할 수 있다. 원격 이력 변경이 필요한 force push는 Telegram에서 별도 승인 절차를 만들기
전까지 작업자에게 허용하지 않는다.

같은 기존 봇에서 두 CLI에 지시하거나 질문할 수 있다.

```text
/codex README를 확인하고 현재 프로젝트 상태를 알려줘
/claude 최근 변경사항을 검토해줘
```

`/claude`만 보내면 이후 평문 메시지는 Claude로, `/codex`만 보내면 Codex로 전달한다.
이 선택은 서비스 재시작 후에도 유지된다. `/claude 지시`처럼 내용을 붙인 명령은 해당 작업에만
적용한다. 초기 기본값은 Codex다. `/status`는 최근 작업 상태, `/help`는 명령 목록을 반환한다.
`/claude /project quant` 다음 줄에 지시를 넣어 프로젝트도 선택할 수 있다.

접수 시 작업 ID와 실행 대상을 알려주고, 완료 시 해당 CLI의 최종 응답을 Telegram에 전달한다.
긴 응답은 나눠 보낸다. 질문만 처리한 경우 불필요한 commit을 만들지 않는다.
각 메시지는 독립 작업이며 기존 터미널 세션이나 이전 대화 내용을 자동 공유하지 않는다.
후속 지시에는 대상 파일이나 이전 작업 ID 등 필요한 맥락을 포함한다 — 단, 봇이 보낸 "접수"나
완료 메시지에 **Telegram 답장(reply)** 으로 다음 지시를 보내면 프로젝트·저장소·실행 대상은
자동으로 그 작업과 동일하게 이어진다(내용을 새로 기억하는 건 아니고 라우팅만 이어진다 — 저장소
버튼을 다시 고르거나 `/project`를 다시 안 써도 됨). `/codex`나 `/claude`를 답장 맨 앞에 붙이면
실행 대상만 그 메시지에 한해 바꿀 수 있다.

`/queue`는 대기(`queued`/`retry`)·실행(`running`)·차단(`blocked`) 중인 작업을 프로젝트·실행
대상과 함께 전부 보여준다(`/status`는 최근 8개만). `/cancel 작업ID`는 아직 시작하지 않은 작업을
큐에서 바로 제거하고, 이미 실행 중인 작업은 프로세스에 종료 신호(`SIGTERM`)를 보내 중지를
요청한다 — 실제로 멈추면 `cancelled` 상태로 확정되고 별도 Telegram 메시지가 온다. `done`,
`blocked`, `cancelled`로 이미 끝난 작업은 취소할 수 없다.

`/diff 작업ID`는 그 작업 시작 전/후의 git HEAD를 비교해 `git log --oneline`과
`git diff --stat`만 보여준다 — Claude/Codex를 다시 부르지 않는 가벼운 조회라 SSH 없이 폰으로
"진짜 뭘 고쳤는지" 바로 확인할 수 있다. 커밋이 없었다면 "커밋 변경 없음"이라고 답한다.

`/usage`는 최근 7일간 백엔드별 작업 수·완료 수·사용량 한도(429 등) 도달 횟수를 보여준다.
한도에 자주 걸리는 시간대/백엔드를 파악하는 용도다.

## 2주 전략 실험 감독 (종료됨)

2026-09-25에 `quant-experiment-supervisor.service`와 `deploy/experiment_supervisor.py`를 삭제했다.
2주 실험은 Day 4가 PIT(당시 기준) 구성종목 데이터 부재로 반복 BLOCKED 되어 일시정지 상태였고,
재개 계획이 없어 정리했다. VM에서는 `sudo systemctl disable --now quant-experiment-supervisor`로
먼저 멈췄다(파일만 지우면 `Restart=always`로 30초마다 실패를 반복하기 때문).

- 남긴 것: `docs/TWO_WEEK_STRATEGY_VALIDATION_PROTOCOL.md`, `docs/experiment_validation/`, `.experiment-control/`
  (백업 대상이며 사람 검증 대기 표본이 들어 있다). 이 텔레그램 러너의 `.experiment-control` 참조도 그대로다.
- 복구: `git show <삭제 직전 커밋>:deploy/experiment_supervisor.py` 등으로 파일을 되살리고
  유닛을 다시 설치·활성화하면 된다(`docs/prune/PRUNE_E.md` 참고).

## GitHub 저장소 선택과 생성

작업자는 현재 저장소와 `/opt/projects` 아래의 저장소를 확인해 지시와 가장 관련 있는 곳을 고른다.
새 독립 프로젝트가 필요하면 `/opt/projects/<이름>`에 만들고, GitHub CLI 인증이 있을 때 private
저장소를 생성해 commit/push한다. 공개 저장소는 Telegram 지시에 명시한 경우에만 만든다.

현재 `Quant` Deploy Key는 해당 저장소에만 쓰기 권한이 있다. 다른 저장소 접근이나 새 저장소
생성에는 `quant` 계정의 GitHub CLI 로그인이 필요하다. 권한이 없거나 대상 저장소가 모호하면 작업을
`blocked`로 표시하고 응답 첫 줄에 `ACTION_REQUIRED:`와 필요한 조치를 보낸다. 해결한 뒤
`/retry 작업ID`를 보내면 `RESUME_NOTE.md`에서 계속한다. `/status`로 작업 ID를 확인할 수 있다.

기본 설정에서는 평문, `/codex 지시`, `/claude 지시`를 `workspace` 작업으로 접수한다. 작업자가
`gh repo list`와 로컬 clone을 조사해 저장소를 스스로 선택한다. `/project quant`처럼 명시하면
자동 선택을 건너뛴다. 수동 버튼 선택 흐름도 코드에 남아 있으며 `auto_repository_selection`을
`false`로 바꾸면 사용한다.

```bash
sudo -u quant env HOME=/opt/quant gh auth login --hostname github.com --git-protocol ssh --web
sudo -u quant env HOME=/opt/quant gh auth status
```

브라우저 개발환경은 서버에 이미 `/usr/bin/code-server`가 설치되어 있고
`code-server@ubuntu.service`로 실행 중이다. GitHub Codespaces는 서버에 설치하는 프로그램이
아니므로 이 파이프라인에는 기존 code-server를 사용한다.

Claude는 서버에 설치된 `/usr/local/bin/claude`와 `quant` 계정의 기존 로그인을 사용한다.
`claude_bin`, `claude_config_dir`로 변경할 수 있다. 설치된 CLI의 `--help`로 다음 플래그를 확인했다.

```text
claude -p --output-format stream-json --verbose --no-session-persistence --dangerously-skip-permissions --append-system-prompt PROMPT
```

지시는 stdin으로 전달하고 `result` 이벤트의 성공 여부와 응답을 읽는다. Claude도 한도 오류 시
같은 메모 및 재시도 규칙을 적용한다. 인증 등 일반 오류는 `blocked`로 알린다.
CLI 세션 기록은 저장하지 않으며, 기존 대화 세션에 원격으로 붙는 방식은 아니다.

두 CLI를 각각 합성 Telegram 메시지로 실행해 `done` 및 실제 Telegram 응답 전송을 확인했다.
Claude 한도 오류는 모의 이벤트로 메모 보존과 재시도를 검증했다.

두 실행 대상의 기본 추론 강도는 `xhigh`다. Codex에는
`-c model_reasoning_effort="xhigh"`, Claude에는 `--effort xhigh`를 전달한다. 로그인 횟수가
추론 품질을 높이는 것은 아니며, 이 설정이 각 CLI에 더 많은 추론 예산을 요청한다. 응답 시간이
늘고 구독 사용량 한도에 더 빨리 도달할 수 있다. `config.json`의 `codex_reasoning_effort`와
`claude_effort`로 조절할 수 있다.

이 서비스는 Telegram private chat의 새 텍스트 메시지를 SQLite 영속 큐에 기록하고, 최대
`max_concurrent_jobs`(기본 8)개까지의 작업자 스레드가 큐를 소비하되 실제 동시 실행 개수는
그 순간의 CPU 부하·여유 메모리로 정해진다(위 "실행 대상과 응답" 절 참고). 같은 프로젝트의 작업은
항상 순서대로만 실행되지만, 서로 다른 프로젝트는 여유가 되는 만큼 병렬로 실행된다. Long polling을
사용하므로 공개 webhook URL·TLS 인증서가 필요 없고, 작업자가 실행 중이어도 수신 루프는 계속
메시지를 저장한다.

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

동일 프로젝트는 앞선 작업 완료까지 대기하지만, 서로 다른 프로젝트는 VM 여유가 되는 만큼 동시에
실행한다. 재시도 대기 중에는 다른 프로젝트를 계속 실행할 수 있다. 실행 중
서비스가 죽으면 systemd가 하위 프로세스까지 정리하고 재시작 시 `running` 작업을 재개한다. SQLite
큐와 수신 offset은 함께 커밋한다.

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
  최종 호스트 재시험에서는 `done`, 테스트 파일 생성, 모델의 commit/push와 원격 HEAD 일치,
  `RESUME_NOTE.md` 삭제를 모두 확인했다. 앞서 실제 한도에 걸렸던 동일 작업도 다시 실행해
  `attempts=2`, `done`, commit/push와 메모 삭제를 확인했다. 이 시험에서는 대기 시각을
  수동으로 당겼으며, 실제 한도 초기화 시각 자체는 측정하지 않았다.
- 실제 봇 `getMe` 인증 성공, webhook 미설정 확인 후 long polling 활성화.
- 완료된 테스트 작업의 요약을 래퍼 `notify()`로 실제 Telegram에 전달하고 `notified=1` 확인.
- `quant-vm`에서 systemd `enabled`, `active (running)` 확인.
  메인 프로세스 SIGKILL 후 30초 뒤 새 PID와 `NRestarts=1` 확인.
  호스트 재부팅 자체는 기존 서비스를 중단시키므로 실시하지 않았다.
