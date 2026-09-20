

## 2026-09-18 14:15 UTC — 이번 재개 결과가 이전 재개 지침보다 우선

Day 1은 B1/B2/B3로 계속 보류 중이다. 완료 표식은 없다.
새 근거가 생겼는지 먼저 확인하고, 같은 데이터 재수집/백테스트를 반복하지 않는다.
상세 다음 단계와 실행 명령:
`docs/experiment_validation/day1_review_20260918T141530Z/RESUME_NOTE.md`.
이 경로는 저장소 루트 기준이다. 이번 결과/해시는 같은 디렉터리의 `review.md`,
`reference_probe.json`, `result_hashes.json`에 있다.

기존 `/tmp/quant-day1-validation-20260918`는 실제 디렉터리가 사라졌고 git 등록만
남아 있다. 삭제하거나 강제 수정하지 않았다. 새 게시 worktree는
`/tmp/quant-day1-review-20260918`, 새 연구 브랜치는
`research/day1-review-20260918`이다. 실제 게시 SHA/상태는 이번 디렉터리의
`publication.json`을 확인한다. 그 파일이 없으면 게시가 완료됐다고 가정하지 않는다.

루트 PROGRESS.md의 기존 미커밋 연구, docs/reports/README.md, 앞선 미완료
`day1_resume_20260918T135512Z/`, 고정된 55개 증거는 덮어쓰지 않았다.
진행/재개 파일은 기존 본문 뒤에 이번 내용만 추가했다. 연구 브랜치의 루트
진행 기록에는 이번 추가분만 반영하고 별도 미커밋 연구 항목은 포함하지 않는다.
main push·서비스 조작·실계좌 주문·인증정보 변경·일일 HTML 커밋은 수행하지 않는다.


## 2026-09-19 — 최신 인계 (이전 Day 1 보류 지침을 대체)

Day 1은 기존 day1_resolutions.md와 완료 기록을 따른다. 이번 Day 2 데이터 감사는 통과했다.
다음 자동 감독은 Day 3만 수행한다. 상세 다음 단계·명령·주의할 데이터 제약은
`/opt/quant/docs/experiment_validation/day2/RESUME_NOTE.md`, 감사 결과는 같은 상위 디렉터리의
`data_audit.md`, 게시 SHA/원격 확인은 `day2/publication.json`에 있다.
원본 spec/manifest/lock은 증거로 유지하여 과거 BLOCKED 상태를 보존했다. 재다운로드나
완료된 백테스트 반복 없이 5/10/25bp 기준선/S1~S5 next-open 백테스트를 새로 수행한다.


## 2026-09-19 — 최신 인계: Day 3 검증 완료

Day 3의 다음 시가/비용 조건은 통과했으며 두 PROGRESS.md에 완료 표식을 기록했다.
다음 자동 감독은 Day 4만 수행한다. 자세한 명령/제약은
`docs/experiment_validation/day3/RESUME_NOTE.md`, 결과는 `day3_report.md`,
게시 확인 SHA는 `day3/publication.json`을 참조한다(경로는 실험 디렉터리 기준).
Day 3 백테스트와 입력 재수집을 반복하지 않는다. S6 실제 PIT 입력 검증과 S1 공통 일자
비교를 수행하고 미래/현재 데이터 fallback으로 과거를 채우지 않는다.


## 2026-09-19 — 최신 인계: Day 4 PIT 입력 인증 보류

이 항목이 이전의 Day 4 착수 지침보다 우선한다. Day 4는 BLOCKED이며 완료 표식 없음.
반기 40회/20,156행을 감사했으나 과거 공개시각·섹터·주식수 단위·상장폐지 입력을
인증한 구간이 없어 S6 성과와 S1 공통 날짜 비교를 실행할 수 없다.
다음 자동 감독은 Day 4에 머물고 `docs/experiment_validation/day4/RESUME_NOTE.md`의
입력 계약/명령을 따른다. 새 인증 증거가 없으면 동일 백테스트/캐시 수집을 반복하지 않는다.
현재 확인 명령: `.venv/bin/python docs/experiment_validation/day4/verify_saved.py --require-complete`
(기대 종료 코드 2: 감사 일치 PASS, Day 4 BLOCKED). 테스트 78개 통과.
보고서 `docs/experiment_validation/satellite_audit.md`; 해시 `day4/result_hashes.json`;
게시 확인 `day4/publication.json`(위 두 경로는 실험 디렉터리 기준).
Day 4 연구 브랜치에 기존 미게시 Day 3 의존 증거를 보존했다. 기존 Day 3 worktree/index,
main 미커밋 연구, 서비스 및 인증정보는 변경하지 않았다. Day 5 진행 금지.


## 2026-09-20 — 최신 인계: Day 4 입력 인증 보류 유지

Day 4의 실제 S6 재현·S1 공통 비교는 아직 미완료다. 다음 감독은 Day 5로 넘어가지 않는다.
새 SEC 진단 원문 3개와 주식수 70행의 공시 연결을 저장했지만 전체 모집단 PIT 인증은 아니다.
최신 다음 단계·명령: `docs/experiment_validation/day4_review_20260920/RESUME_NOTE.md`.
새 입력 확보 전 같은 API/캐시 재수집이나 백테스트를 반복하지 않는다.
검증·해시는 같은 폴더 `validation.json`, `result_hashes.json`, 게시 확인은 `publication.json`.


## 2026-09-20 05:38 UTC — 최신 인계: Day 4 전체 PIT 입력 보류

공식 과거 GICS 공지 원문 2개와 MSCI 미국 변경 코드 62행을 추가 확보했지만,
S&P500 전체 PIT 인증 자료가 아니므로 Day 4는 BLOCKED다. 완료 표식 없음.
다음 감독은 Day 4 전체 구성/섹터/증권/공개시각/상장폐지 입력부터 확보한다.
최신 결과와 다음 명령: `docs/experiment_validation/day4_sector_sources_20260920/RESUME_NOTE.md`.
새 증거 없이 같은 공지·SEC·캐시·Day 3 백테스트를 반복하지 않고 Day 5로 넘어가지 않는다.
신규/기존 Day 4 테스트 26개 통과, 원문/CSV 독립 감사 PASS, 완료 요구 종료 코드 2.
게시 결과는 해당 폴더 `publication.json`에서 확인한다.


## 2026-09-20 Day 4 전체 모집단 입력 인계

Day 4는 BLOCKED다. 최신 재개 문서는
`docs/experiment_validation/day4_input_handoff_20260920/RESUME_NOTE.md`, 필요한 전체
입력/조회 키는 같은 폴더 `input_request.md`와 요청 CSV 3개다. 입력 인증 반기/공통 날짜
0개이므로 완료 표식 금지, Day 5 미착수. 신규 PIT export/기존 데이터 경로가 있을 때
계속하며 단일 회사/공지 조사와 완료된 백테스트를 반복하지 않는다. 24개 테스트와
저장 요청/달력/기존 해시 검사는 통과했으나 실제 S6 재현 통과가 아니다.


## 2026-09-20 10:47 UTC — 최신 인계: Day 4 신규 PIT 자료 없음

Day 4는 BLOCKED다. 로컬 데이터 3,470개 중 새 변경은 SPY/VIX 가격 캐시 2개뿐이며
인증 누락을 해결하지 못했다. 원천 1,548개/동결 22개/이전 증거 해시 유지, 기존 테스트
15개 통과. 실제 S6 재현·S1 공통 비교 미완료이므로 Day 5로 넘어가지 않는다.
다음 단계/명령: `docs/experiment_validation/day4_reentry_20260920T1047Z/RESUME_NOTE.md`.
실제 PIT export 또는 기존 데이터 경로를 확보했을 때 재개하고 같은 백테스트/원천 조사/
요청 패키지는 반복하지 않는다. 게시 확인은 같은 디렉터리 `publication.json`.


## 2026-09-20 14:56 UTC — 최신 인계: Day 4 신규 PIT 자료 없음

Day 4는 BLOCKED다. 로컬 3,470개 중 새 파일은 없고 가격 캐시 20개의 메타데이터
차이만 확인했다. 원천 1,548개·동결 22개·기존 증거 해시는 유지됐다. 저장 상태와
신규 delta 검사는 PASS지만 실제 S6 재현·S1 비교는 미완료다. 이전 테스트/백테스트는
반복하지 않았다. 다음 단계·명령은
`docs/experiment_validation/day4_reentry_20260920T1456Z/RESUME_NOTE.md`를 따른다.
실제 PIT export 또는 기존 데이터 경로를 확보해 인증한 뒤에 계속하며 Day 5로
넘어가지 않는다. 원격 게시·알림 확인은 같은 디렉터리 `publication.json`에 있다.


## 2026-09-20 19:05 UTC — 최신 인계: Day 4 실제 PIT 입력 보류

Day 4는 BLOCKED다. 로컬 3,482개에서 새 파일 12개/메타데이터 변경 579개를 찾았지만
별도 연구 결과·가격/매크로 캐시·현재 목록/스냅샷으로 PIT 누락을 해결하지 못했다.
신규 delta/스키마/해시 및 기존 원천/동결 입력/증거 검증 PASS, 실제 S6 재현과
S1 공통 비교는 미완료다. 완료된 테스트·백테스트는 반복하지 않았다.
다음 단계/명령: `docs/experiment_validation/day4_reentry_20260920T1905Z/RESUME_NOTE.md`.
실제 PIT export/기존 자료 경로를 확보해 인증한 뒤 계속하며, Day 5로 넘어가지 않는다.
게시/알림 결과는 같은 폴더 `publication.json`.


## 2026-09-20 23:12 UTC — 최신 인계: Day 4 실제 PIT 입력 변화 없음

Day 4는 BLOCKED다. 3,482개 데이터 파일의 추가·삭제·메타데이터 변경 0개이며
새 PIT 입력을 확보하지 못했다. 원천 1,548개·동결 22개·기존 증거 해시/저장 상태
검증 PASS지만 S6 재현·S1 공통 비교는 미완료다. 완료 표식 없음, Day 5 미착수.
다음 단계·명령: `docs/experiment_validation/day4_reentry_20260920T2312Z/RESUME_NOTE.md`.
실제 PIT export/기존 자료 경로를 확보해 인증한 뒤 계속하며 새 증거 없이 같은
조사·요청 생성·백테스트를 반복하지 않는다. 게시/알림 결과는 같은 폴더 `publication.json`.
