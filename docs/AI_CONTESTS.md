# AI 대회 관리 (관제 센터 'AI 대회' 섹션)

작성 2026-09-26. 상태: **구현·단위 테스트 완료, VM 1회 설정 필요.**

## 사용자 결정 (2026-09-26)
- 대회를 누르면 **브라우저 code-server**(`code.hessejeong.duckdns.org`)가 그 대회 폴더로 열린다.
- 대회마다 GitHub 저장소는 **private 고정**(`contest-<폴더이름>`).
- 관리 항목: 기본 정보·마감일, 마감 임박 텔레그램 알림. (추가 항목 "Other" 는 내용 미기재 — 사용자 확인 대기)
- 새 대회는 **기본 뼈대**(README·data/·notebooks/·src/·submissions/·.gitignore·requirements.txt)를 넣어 만든다.

## 구조
| 구성 | 파일 | 역할 |
|---|---|---|
| 공용 로직 | `core/contests.py` | 검증·폴더/뼈대 생성·`git init --shared=group`·`gh repo create --private --push`·마감 알림 계산 |
| 화면 | `hub/contests_page.py`, `hub/server.py` | `/contests` 목록, `/contests/new`, `/contests/<slug>`(수정·VS Code 열기·저장소 재시도) |
| 카드 | `hub/apps_registry.py` | 관제 센터 'AI 대회' 카테고리 카드(진행 개수·다음 마감 D-day) |
| 알림 | 잡 `contest_deadline_alert` 09:00 KST | 마감 7일·1일 전·당일 1건씩, '제출 완료'·'종료'는 제외 |
| 1회 설정 | `deploy/setup_contests.sh` | 그룹 `contests`(ubuntu+quant), `/srv/contests` 2775, git safe.directory, gh↔git 인증, 서비스 재시작 |

대회 정보의 원본은 각 폴더의 `contest.json`(저장소에 함께 커밋). 폴더 이름은 영문 소문자·숫자·하이픈만 허용(경로 조작 차단).
GitHub 단계가 실패하면 폴더·로컬 커밋은 남고 `repo_status=failed:<사유>` 로 표시되며 대회 화면에서 다시 시도한다.
허브 POST 는 같은 사이트 요청만 받는다(`_same_origin_post`).

## VM 에서 사람이 할 일 (1회)
1. code-server 터미널에서 `sudo bash /opt/quant/deploy/setup_contests.sh`
2. code-server 에서 대회 저장소로 push 하려면 `ubuntu` 계정도 `gh auth login` 후 위 스크립트를 한 번 더 실행.

## 한계·다음 후보
- Kaggle/Dacon API 연동(데이터 다운로드·제출·리더보드 자동 수집)은 미구현.
- 대회 폴더는 GitHub 저장소가 백업 역할을 한다(VM 백업 대상에는 넣지 않음).
