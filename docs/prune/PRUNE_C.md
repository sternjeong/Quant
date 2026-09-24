# 정리(prune) C — 야간 튜닝 '껍데기' 삭제 기록

기준 커밋 `52c4940`. 사용자 결정(확정): "야간 튜닝을 삭제한다." 사유: 사용자가 요청한 적 없는 기능이고 매일 cron 으로 돌며 결과(리더보드)를 저장소에 커밋했다.
**튜닝 엔진(`core/strategy_tuning.py`), DB 테이블/모델(`StrategyTuningRun/Result` 등), 저장된 튜닝 결과는 반기 상시 시스템이므로 삭제·수정하지 않았다.** 삭제한 것은 '야간에 자동으로 도는 껍데기'뿐이다.

## 삭제(파일 전체)

| 경로 | 줄 수 | 근거(grep) | 복구 |
|---|---|---|---|
| `.github/workflows/nightly_tuning.yml` | 58 | 매일 cron(15:05 UTC)+리더보드 커밋. 다른 워크플로/스크립트가 호출하지 않음(문서/주석 언급만) | `git show 52c4940:.github/workflows/nightly_tuning.yml` |
| `scripts/nightly_tuning_ci.py` | 258 | 유일한 호출자가 위 워크플로. 임포트하는 곳은 자기 테스트뿐(`grep nightly_tuning_ci`). 반기 튜닝 경로에서 안 씀 | `git show 52c4940:scripts/nightly_tuning_ci.py` |
| `tests/test_nightly_tuning_ci.py` | 169 (테스트 9개) | 위 스크립트 전용 | `git show 52c4940:tests/test_nightly_tuning_ci.py` |
| `scripts/five_strategy_batch_ci.py` | 253 | 진입점 워크플로는 PRUNE_B 에서 삭제됨. 호출자 없음(`grep five_strategy_batch` = 자기·자기 테스트·import 스크립트·주석뿐) | `git show 52c4940:scripts/five_strategy_batch_ci.py` |
| `scripts/import_five_strategy_batch_results.py` | 46 | `data/five_strategy_batch_top10.json` 을 읽는 1회성 가져오기. 그 JSON 은 저장소에 없음(`git ls-files data`). 다른 곳 참조 없음 | `git show 52c4940:scripts/import_five_strategy_batch_results.py` |
| `tests/test_five_strategy_batch_legacy_split.py` | 125 (테스트 6개) | `five_strategy_batch_ci` 전용 | `git show 52c4940:tests/test_five_strategy_batch_legacy_split.py` |
| `scripts/seed_five_active_strategies.json` | 774 | `five_strategy_batch_ci` 만 읽음 | `git show 52c4940:scripts/seed_five_active_strategies.json` |
| `scripts/seed_strategy_3.json` | 113 | `nightly_tuning_ci` 만 읽음 | `git show 52c4940:scripts/seed_strategy_3.json` |

## 삭제(파일 일부)

| 경로 | 삭제 내용 | 줄 수 | 복구 |
|---|---|---|---|
| `scheduler/run_scheduler.py` | `strategy_nightly_tuning_job` + `_NIGHTLY_TUNING_*` 상수/주석 블록, `add_job(nightly_strategy_tuning)`, 상단 docstring 설명, 미사용이 된 import(json/time/timedelta/date/ZoneInfo/get_session/Strategy/tuning 3종) | 약 116 | `git show 52c4940:scheduler/run_scheduler.py` |
| `core/process_registry.py` | `strategy_nightly_tuning` 항목(docstring 에 삭제 표기) | 8 | `git show 52c4940:core/process_registry.py` |
| `core/job_schedule.py` | `nightly_strategy_tuning` 항목 | 1 | `git show 52c4940:core/job_schedule.py` |
| `core/job_health.py` | `GRACE_OVERRIDES` 의 야간 튜닝 6시간 유예 → 빈 dict(메커니즘은 유지) | 1 | 위와 동일 |
| `core/theme.py` | `render_nightly_leaderboard_badge`('🌙 리더보드 N일 전' 배지)와 `_cached_ci_leaderboard_freshness`, `apply_theme` 안의 호출 | 64 | `git show 52c4940:core/theme.py` |
| `deploy/codex_telegram/runner.py` | `PROCESS_CATALOG` 의 `strategy_nightly_tuning` 항목(텔레그램 /processes 에 죽은 토글이 남지 않도록; 레지스트리와 이 목록은 함께 갱신하는 관례) | 1 | `git show 52c4940:deploy/codex_telegram/runner.py` |
| 테스트 수정 | `tests/test_run_scheduler_toggles.py`(야간 잡 테스트 2개 삭제), `tests/test_process_registry.py`·`tests/test_job_health.py`·`deploy/codex_telegram/test_runner.py`(삭제된 키 대신 `champion_signal_alert`/`champion_benchmark_gap` 로 같은 동작 검증, 등록표↔스케줄러 일치 테스트는 그대로 통과) | - | - |

## 화면(app/) 수정 — `app/pages/1_전략_스튜디오.py` 문구만(로직·탭 유지)

- 12~13행: 탭 안내에서 "로컬 스케줄러/GitHub Actions가 반복 튜닝한 결과" → "과거 야간 튜닝이 저장해 둔 결과(더 이상 자동 갱신되지 않음)".
- 2998~3002행(주석): 두 경로로 쌓인다는 설명 → 야간 삭제, 저장된 결과만 표시한다는 설명.
- `_load_ci_leaderboard_json` docstring 1줄: 워크플로 삭제 표기.
- 리더보드 탭 상단 `st.caption`: 야간 자동 갱신을 전제한 서술 → "이미 저장된 결과, 더 이상 매일 갱신되지 않음, 새 결과는 직접 실행 시에만".
- 결과 없음 `st.info`: `run_scheduler.py` 상시 실행/워크플로 안내 → 삭제됐고 '다종목 미세튜닝' 탭에서 직접 실행 안내.
- 메트릭 라벨 2개: "로컬 스케줄러 누적 실행 횟수" → "로컬 DB 누적 실행 횟수", "GitHub Actions 결과 파일 건수" → "저장소 결과 파일 건수".
- v2/유의성 필터 안내 `st.info` 2곳: "다음 야간 튜닝이 새로 돌면" → "새 튜닝을 직접 실행하면".
- 그 외: 탭 이름·리더보드/이력/저장 로직·`source="nightly_tuning_leaderboard"` 값은 그대로(저장된 전략 식별 키라 바꾸면 안 됨). '배치 생성' 탭의 "야간 미세튜닝은…" 문장(2868행 근처)은 일반 설명이라 그대로 둠.

기타 문서/주석 정정: `deploy/DEPLOYMENT_ORACLE.md` 7절(야간 튜닝과의 관계) → 삭제 안내로 교체, `deploy/PENDING_MANUAL_LOGIN_ACTIONS.md`·DEPLOYMENT_ORACLE 197행의 워크플로 참조에 "(삭제됨)" 표기, `core/resource_guard.py`·`core/market_regime.py`·`scripts/nightly_market_snapshot_ci.py` 주석의 삭제된 스크립트 참조 정리.

## 보류(삭제하지 않음)와 사유

| 항목 | 사유 |
|---|---|
| `data/nightly_tuning_leaderboard.json` (커밋된 리더보드 산출물) | 전략 스튜디오 리더보드 탭이 읽는다(`_load_ci_leaderboard_json`). "저장된 결과"이므로 유지. 화면이 더 이상 필요 없다고 결정되면 파일+로더를 함께 정리 |
| `core/strategy_tuning.py` 전체(`get_top_tuning_results`, `list_tuning_runs`, `partition_by_score_version`, `run_and_save_tuning`, `sample_universe` 등) | 반기 상시 시스템. 화면·챔피언·시장진단이 사용 |
| `core/models.py`/`core/db.py` 의 튜닝 테이블·모델 | 데이터가 있을 수 있음. 금지 사항 |
| `source="nightly_tuning_leaderboard"` 전략(라이브러리에 저장된 것) | 사용자 자산. 식별 문자열 유지 |
| `docs/STRATEGY_TUNING_ENGINE_SPEC.md` 의 야간 관련 서술, `PROGRESS.md`, `docs/SESSION_HANDOFF.md` | 과거 기록/금지 파일. 스펙의 야간 절은 역사 기록으로 남김(필요하면 후속으로 "삭제됨" 각주) |
| `deploy/codex_telegram/runner.py` 수정 | 지시 목록엔 없지만 레지스트리와 함께 갱신하는 저장소 관례라 포함. 이견이 있으면 이 1줄만 되돌릴 것 |

## 고아 함수(이 삭제로 호출자가 사라진 것)

- `core/strategy_tuning.py::get_ci_leaderboard_freshness` 와 `_CI_LEADERBOARD_PATH` — 배지 전용이었음. **튜닝 엔진 안이라 삭제하지 않음**(호출자 0, 테스트도 없음). 후속 정리 후보.
- `core/theme.py` 의 배지 함수 2개 — 이미 이번에 함께 삭제.
- `core/resource_guard.has_headroom` — 아직 `daily_news_digest` 잡이 사용하므로 고아 아님.
- 엔진 함수(`run_and_save_tuning`, `sample_universe`, `get_top_tuning_results` 등)는 모두 다른 호출자가 있어 고아 아님.
- `core/fred_data` 의 `CACHE_DIR/DEFAULT_INDICATORS/_cache_file/get_series` — 야간 CI 가 매크로 캐시를 갱신하려 임포트했을 뿐, 모듈 자체는 다른 곳에서 사용 중이라 고아 아님.
- 부수 효과: 워크플로가 하던 `data/cache/fred_*.csv` 커밋도 멈춘다(FRED 캐시 예열은 스케줄러의 `fred_indicator_prewarm` 잡이 별도로 수행).

## 검증

- 삭제 전 기준선 `python -m pytest tests -q`: 1739 passed. 삭제 후: 1722 passed(-17 = 삭제 테스트 9+6+스케줄러 2, 추가 1(grace override)). `deploy/codex_telegram/test_runner.py` 62 passed(tests/ 밖이라 별도 실행).
- `python -m compileall core scripts scheduler app -q` 통과.
- 잔존 참조 grep(`nightly_tuning`, `five_strategy`, `seed_strategy_3`, `seed_five`, `strategy_nightly_tuning`): 남은 것은 PROGRESS/SESSION_HANDOFF/SPEC/docs/prune 과거 기록, 삭제 표기 주석, 리더보드 JSON 경로·`source` 값(보류 항목) 뿐.
- 확인 못한 것: 실제 Streamlit 화면 렌더(배지 제거 후 상단바, 스튜디오 탭)는 띄워 보지 못함(컴파일·테스트만). VM 의 `data/process_toggles.json` 에 남은 `strategy_nightly_tuning` 키는 무해(무시됨).
