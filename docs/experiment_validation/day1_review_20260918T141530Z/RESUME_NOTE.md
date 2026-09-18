# 다음 감독: Day 1 보류 사유 해소부터

Day 1은 미완료다. B1/B2/B3가 해결되기 전 Day 2로 진행하거나 완료 표식을
쓰지 않는다. 상세 근거는 같은 디렉터리의 `review.md`, 수치와 데이터 해시는
`reference_probe.json`, 검증 명령/종료 코드는 `commands.json`에 있다.

다음 실행은 새 사전등록 근거 또는 사용자 답변이 생겼는지 먼저 확인한다.
필요한 근거는 S5/실행 관측 방식/기준선의 상세 계약, XLRE 때문에 생기는
첫 표본외 구간 충돌의 기존 승인된 해결책, S6 과거 시점 입력 출처다.
작업 55/60의 역사적 챔피언 구현은 후보 근거로 참고할 수 있으나 B1 전체나
B2/B3를 해소하지 않는다. 아무 근거가 추가되지 않았다면 같은 가격을 다시
다운로드하거나 같은 백테스트를 반복하지 말고 보류 상태를 보고한다.

새 근거가 있을 때 다음 명령으로 기존 증거를 확인한다:

```bash
cd /opt/quant
.venv/bin/python docs/experiment_validation/check_snapshot.py
.venv/bin/python -m pytest -q docs/experiment_validation/test_snapshot.py
.venv/bin/python docs/experiment_validation/day1_review_20260918T141530Z/probe_reference_contract.py
.venv/bin/python docs/experiment_validation/check_snapshot.py --require-complete
```

현재 예상 결과: 무결성 PASS, 6개 테스트 통과, 합성 입력으로 참고 코드의
세 결함 재현, 마지막 명령 종료 코드 2. 마지막 실패를 무시하거나 lock을
새로 계산해 우회하지 않는다. 원래의 독립 lock 해시는
`3022ec9a3169c827ccb398c309b2cd0d46be87fce7f467e1ef0a20f366f62f9e`다.
Day 1 명세 수정이 정당화되면 기존 증거는 보존하고 별도 revision을 만든다.

기존 연구 worktree `/tmp/quant-day1-validation-20260918`는 사라졌지만
git 등록은 남아 있다. 그 경로로 재개하지 않는다. 이번 게시 worktree는
`/tmp/quant-day1-review-20260918`, 브랜치는 `research/day1-review-20260918`이다.
둘 다 사용 전에 현재 상태를 확인한다:

```bash
git status --short
git log -5 --oneline
git worktree list --porcelain
git -C /tmp/quant-day1-review-20260918 status --short
git ls-remote --heads origin research/day1-review-20260918
```

push 실패 시 커밋 존재 여부와 파일 목록을 확인한 뒤에만 다음을 재시도한다:

```bash
git -C /tmp/quant-day1-review-20260918 log -1 --oneline
git -C /tmp/quant-day1-review-20260918 show --stat HEAD
git -C /tmp/quant-day1-review-20260918 push -u origin HEAD:refs/heads/research/day1-review-20260918
```

main 병합/push는 자동배포로 서비스를 재시작할 수 있으므로 이번 범위에
포함하지 않는다. state.json은 감독기 소유로 남겨 둔다. 운영 코드, 서비스,
인증정보, 기존 미커밋 연구와 자동 일일 HTML은 건드리지 않는다.
