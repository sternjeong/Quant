

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
