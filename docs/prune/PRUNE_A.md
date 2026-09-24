# PRUNE_A: Python 코드 정리 (기준 커밋 2decea2)

## 요약
- 삭제: 2개 파일 (core/page_order.py 74줄 + tests/test_page_order.py 64줄 = 138줄)
- 보류(사용자 확인 필요): 9개
- 테스트: 삭제 전 1659 passed -> 삭제 후 1651 passed (page_order 테스트 8개 감소)
- 방법: core/*.py 60여 개와 scripts/*.py 전부에 대해 `grep -rlw <모듈명> core scripts app deploy scheduler .github research_agents hub`
  로 비테스트 참조 그래프를 만들고, tests 참조 수를 별도 집계. 참조 0이거나 테스트만 참조하는 것을 1차 후보로 삼음.
  나머지 모듈은 화면(app/), 스케줄러, 다른 core 모듈, CI 워크플로가 실제로 참조하고 있어 후보가 아님.

## 삭제

| 경로 | 줄 수 | 삭제 여부 | 근거 | 왜 불필요한가 | 복구 |
|---|---|---|---|---|---|
| core/page_order.py | 74 | 삭제 | `grep -rn "page_order\|list_pages\|reorder_pages\|move_page" app deploy scheduler .github core scripts` -> 자기 자신만 나옴. 테스트 외 import 0, 동적 import/문자열 등록 없음 | 파일명 숫자 접두어를 rename 해 사이드바 순서를 바꾸던 유틸. 현재 사이드바는 core/app_navigation.py 의 NAVIGATION 이 명시적으로 정하므로 대체됨(superseded). 환경설정 화면도 사용 안 함 | `git show 2decea2:core/page_order.py` |
| tests/test_page_order.py | 64 | 삭제 | page_order 만 테스트 | 위 모듈 삭제에 따른 동반 삭제 | `git show 2decea2:tests/test_page_order.py` |

문서 색인 참조: docs/ 에는 page_order 언급 없음. PROGRESS.md(루트 문서, 범위 B)에만 과거 이력 언급이 있어 손대지 않음(역사 기록이라 무해).

## 보류 (사용자 확인 필요 / 보존 목록)

| 경로 | 줄 수 | 상태 | 근거 | 보류 사유 |
|---|---|---|---|---|
| core/info_dedup.py | 354 | 보류 | 비테스트 참조 0, 테스트 1 | 보존 목록(공시/가이던스 신규 모듈) |
| scripts/candidate_ledger_update.py | 114 | 보류 | 참조 0(수동 CLI) | 후보 shadow 원장 도구, 보존 목록 |
| scripts/paper_run_admin.py | 142 | 보류 | 참조 0(수동 CLI) | paper 실행 운영 도구, 보존 목록 성격 |
| scripts/verify_alpaca_paper_idempotency.py | 502 | 보류 | 참조 0(수동 CLI) | Alpaca 측정 도구, 보존 목록 |
| scripts/earnings_guidance_extraction_sample.py | 203 | 보류 | 참조 0, 테스트 0 | 가이던스 신규 검증 스크립트, 보존 목록 |
| scripts/filing_change_extraction_check.py | 232 | 보류 | 참조 0, 테스트 0 | 공시 신규 검증 스크립트, 보존 목록 |
| analysis/ 아래 코드 전체 | - | 보류 | 연구 기록 산출물, 실행 참조는 없으나 리서치 재현용 | 사용 여부 판단 근거 없음. 삭제 원칙상 '오래돼 보임'은 근거가 아님 |
| core/expression_engine.py, nl_strategy.py, strategy_explainer.py, strategy_library.py, chart_rendering.py, era_validation.py | 341/847/248/239/279/156 | 보류(삭제 안 함) | 전략 스튜디오(app/pages/1_전략_스튜디오.py)와 strategy_engine/strategy_tuning 이 실제 import | 살아 있는 기능. 스튜디오 페이지 자체를 지울지는 범위 B(화면) 결정에 달림. 페이지가 삭제되면 chart_rendering, era_validation, strategy_explainer, strategy_library 는 고아가 되므로 그때 재검토 |
| core/etf_holdings.py | 195 | 보류 | 거장 포트폴리오 페이지(4_)만 사용 | 보존 목록(guru) 화면에서 사용 중 |

## 참고
- 잔여 삭제 후보는 범위 B가 화면/페이지를 지우는 경우에만 연쇄적으로 생김(위 스튜디오 관련 모듈). 그 경우 이 표의 해당 행 기준으로 후속 정리 가능.
