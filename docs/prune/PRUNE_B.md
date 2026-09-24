# 정리(prune) B — 화면 밖 자산 삭제/보류 기록

기준 커밋 `2decea2`. 범위: app 화면·deploy·워크플로·docs·루트·analysis·연구 스캐폴딩(Python 코드 core/scripts/tests 제외).
삭제는 고신뢰(참조 없음/대체됨/죽은 워크플로)만 했고, 나머지는 사용자 확인용 보류로 남겼다.

**요약: 삭제 6개 항목(파일 6개 + 깨진 서브모듈 링크 1개), 약 3,208줄 / 약 335KB. 보류 9건. 삭제한 화면 페이지 없음(내비게이션 변경 없음).**

## 삭제

| 경로 | 크기 | 판단 | 근거 | 왜 불필요한가 | 복구 |
|---|---|---|---|---|---|
| `docs/study-notes/quant-concepts.html` | 51,875B / 909줄 | 삭제 | 저장소 전체 grep(`study-notes`, 파일명)에서 PROGRESS 외 참조 0. docs/README 색인에도 없음 | `docs/reports/study_notes_fin_engineering.html`와 제목 동일, 래퍼만 다른 옛 사본(7/27 커밋, 이후 reports/로 대체) | `git show 2decea2:docs/study-notes/quant-concepts.html` |
| `docs/study-notes/quant-engines.html` | 46,426B / 693줄 | 삭제 | 위와 동일 | `docs/reports/engine_architecture_notes.html`로 대체 | `git show 2decea2:docs/study-notes/quant-engines.html` |
| `docs/study-notes/quant-lecture-notes.html` | 78,710B / 1,132줄 | 삭제 | 위와 동일 | `docs/reports/quant_lecture_notes.html`로 대체 | `git show 2decea2:docs/study-notes/quant-lecture-notes.html` |
| `.github/workflows/five_strategy_batch_tuning.yml` | 1,474B / 40줄 | 삭제 | 수동 실행 전용(workflow_dispatch만), 스스로 "2026-07-17 1회성 실험"이라 명시. 저장소 grep 결과 다른 워크플로·deploy·문서가 호출하지 않음. 결과 JSON은 이미 커밋·가져오기 완료 | 1회성 긴급 배치 워크플로, 재실행 계획 없음 | `git show 2decea2:.github/workflows/five_strategy_batch_tuning.yml` |
| `kr.tradingview.com_chart_Uiykkvez__symbol=NASDAQ%3AIREN.png` | 157,144B | 삭제 | 루트에 놓인 초기 커밋(7/12)의 차트 스크린샷. grep 참조 0 | 코드·문서 어디서도 쓰지 않는 일회성 캡처 | `git show 2decea2:"kr.tradingview.com_chart_Uiykkvez__symbol=NASDAQ%3AIREN.png" > 파일` |
| `awesome-design-md` (gitlink 160000) | 0 | 삭제 | `.gitmodules` 없음 = 깨진 서브모듈 항목, 작업트리에 내용 없음, grep 참조 0 | 체크아웃해도 비어 있는 죽은 항목 | `git show 2decea2:awesome-design-md`는 불가; 인덱스 항목 복구는 `git checkout 2decea2 -- awesome-design-md` |

## 보류(사용자 확인 필요)

| 경로 | 크기 | 사유 | 확인 사항 |
|---|---|---|---|
| `.github/workflows/nightly_tuning.yml` | 약 3KB | 매일 cron이 살아 있고 저장소에 리더보드를 커밋함. 사용자가 요청한 적 없고 기본 꺼짐이라는 결정과 어긋나지만, 전략 스튜디오 리더보드 화면이 그 산출물을 읽음 | 야간 튜닝 자체를 폐기할지(워크플로+scripts/nightly_tuning_ci.py+리더보드 표시 함께 정리) |
| `docs/reports/*.html` 중 analysis 원본과 바이트 동일한 사본 약 38개(약 2MB) | 약 2MB | 중복이지만 (1) 연구 에이전트/`deploy/progress_reconcile.sh`가 `docs/reports/README.md`를 실사용, (2) `app/pages/11_챔피언_전략.py` 안내 문구가 `docs/reports/research_program_synthesis.html`을 가리킴 | 리포트 위치를 analysis/ 로 일원화할지. 결정되면 화면 문구·색인 함께 수정 필요 |
| `analysis/kostolany_market_report_2026-08-12/` (약 92MB: shot_*.png 각 5MB, equity_curves.pkl 19MB 등) | 92MB | 사용자가 요청한 산출물 폴더라 삭제 안 함. 스크린샷·pkl은 재생성 가능한 중간물로 보임 | 중간 산출물만 지울지 |
| `analysis/macro_event_study_2026-08-21/` | 15MB | 사용자가 별도 스레드로 진행 중인 프로젝트 | 유지 권장 |
| `deploy/experiment_supervisor.py`, `deploy/quant-experiment-supervisor.service`, `deploy/test_experiment_supervisor.py`, `docs/experiment_validation/day1_resolutions.md`, `docs/TWO_WEEK_STRATEGY_VALIDATION_PROTOCOL.md` | 소규모 | 2주 실험은 일시정지 상태이고 재개 조건이 문서에 살아 있음. setup 스크립트는 이 서비스를 설치하지 않음 | 실험을 종결·폐기할지 |
| `deploy/PENDING_MANUAL_LOGIN_ACTIONS.md` | 약 8KB | DEPLOYMENT_ORACLE.md·setup_vm.sh·nginx-quant.conf·auto_deploy.sh가 참조. 1~3번 항목(리서치 에이전트 타이머 복구, VM 최신화, GitHub Actions 야간 리서치)은 낡은 내용 | 낡은 절만 삭제하고 문서는 유지할지 |
| `research_agents/*.md` (7개) | 60KB | VM 리서치 에이전트 페르소나로 PROGRESS에서 계속 사용된 기록 있음 | 리서치 에이전트 운용을 계속할지 |
| `analysis/2026-*/`(40여 개 폴더) | 수십 MB | 연구 원본 및 재생성 스크립트, docs/reports 색인과 연결 | 오래된 라운드를 아카이브할지 |
| `deploy/nginx-quant.conf` | 소규모 | setup_vm.sh가 설치(`cp`), 게이트웨이(setup_gateway.sh)와 관계 재확인 필요 | 게이트웨이로 완전 대체됐는지 |

## 범위 A(core/scripts/tests)로 넘길 후속

- `.github/workflows/five_strategy_batch_tuning.yml` 삭제로 `scripts/five_strategy_batch_ci.py`는 워크플로 진입점을 잃었다. 단, `scripts/import_five_strategy_batch_results.py`와 `tests/test_five_strategy_batch_legacy_split.py`가 아직 쓰므로 삭제 여부는 범위 A가 판단.
- 삭제한 화면 페이지가 없어 화면 전용 core 모듈 고아화는 없다.

## 검증

- 삭제 전 기준선: `python -m pytest tests -q` 1659 passed. 삭제 후 1659 passed. `python -m compileall app -q` 통과.
- 삭제 파일에 대한 참조 grep: `study-notes`, `five_strategy_batch_tuning`, `awesome-design`, `kr.tradingview` 모두 잔존 참조 없음(PROGRESS.md의 과거 기록 제외).
