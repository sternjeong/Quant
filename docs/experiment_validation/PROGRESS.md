# 14일 검증 진행 기록

## 2026-09-18 — Day 1 보류 (DAY_1_BLOCKED)

판정: 명세·입력 패널의 사전 고정을 완료하지 못했다. 감독기는 Day 1에 머물러야 한다.
후보 6개·기준선 3개·선택 게이트 및 원본 프로토콜을 변경하지 않았다.

생성 파일: `candidates.yaml`, `spec.json`, `manifest.json`, `snapshot_lock.json`,
`initial_workspace.json`, `capture_day1.py`, `capture.log`, `check_snapshot.py`,
`test_snapshot.py`, `day1_validation.json`, `validation_tests.log`, `day1_findings.md`,
`README.md`, `RESUME_NOTE.md`, `source/`의 원본 6개, `data/`의 가격 19개·메타데이터 19개·구성종목 1개.

검증 결과: ETF 19/19 조회 성공; 고정 증거 55개 SHA-256 일치; 변조/누락/완료 우회/동일일 종가 설정
차단 테스트 6개 통과(0.10초); `--require-complete` 종료 코드 2; 게시 전 검사에서 기존 미커밋 추적 파일 4개 내용·권한 일치.
테스트는 증거 보존 및 완료 방지 검사이며 백테스트 체결 정확성 통과를 의미하지 않는다.

보류 사유: B1 상세 사전 명세 미정, B2 XLRE의 2015년 시작으로 허용된 XLC→VOX 치환만으로는
첫 표본외 구간의 12개월 공통 웜업 확보 불가, B3 S6 point-in-time 입력·원본 조회 이력 미검증.
다음 실행은 `RESUME_NOTE.md`를 읽고 이 세 사항을 먼저 해소해야 한다. Day 2는 시작하지 않는다.

검토한 코드 SHA: `ba408756b47e53c170a168db63e53a45d979baf6` (기존 참고 코드; 새 프로토콜 엔진 인증 아님).
가격 조회: 2026-09-18T09:45:17.482743+00:00 ~ 2026-09-18T09:45:27.807343+00:00.
요청 범위: 2006-01-01 ≤ 거래일 < 2026-09-18. 최종 가격일: 2026-09-17.

| 고정 파일 | SHA-256 |
| --- | --- |
| `candidates.yaml` | `df8eda9ddc90aa54e64b5c5f4006fbb171a3f95a4a72a1227565152f2084f6ed` |
| `spec.json` | `c5296b50e31f35804ffae5ba3cfd738e64431ead2551b931b85becf970259d97` |
| `manifest.json` | `09466ed870c477753a6ff7d0327cb0a6786dbfd142a6ea352d87d30df4210b9d` |
| `snapshot_lock.json` | `3022ec9a3169c827ccb398c309b2cd0d46be87fce7f467e1ef0a20f366f62f9e` |


| 데이터 | 저장 파일 SHA-256 |
| --- | --- |
| `data/DBC.csv.gz` | `adb17ff8c659e06b017c237cbb8d881df4af872ded7e970871b685cd74ed2ff7` |
| `data/EFA.csv.gz` | `09648f56e8d1765a45603fba7bd01c6fda4ced6d73c2349ea014804d13eaeb51` |
| `data/GLD.csv.gz` | `e4778ab8d72d5b658dc86d25b52aea1bc4410468dba4e956c563bffd2b8e60ea` |
| `data/HYG.csv.gz` | `d92b75af5d242e3e4577257791c57438800b40e0f1eded317ce37cbfe6a797d5` |
| `data/IEF.csv.gz` | `e43d148e1a2cededb8db2806698252359bbdf76db0d22152ffe621bc24995ef2` |
| `data/SPY.csv.gz` | `07f2cb7fb47bd2788d4f09224a9ddc88e131c3ab1a1dd1063e3fa1a8a3271ea4` |
| `data/TLT.csv.gz` | `0e639c16142f2b67102c5364fa91e290044678e673e7d50c6d4a3195d0c89ae4` |
| `data/VOX.csv.gz` | `b2006fe6393cff69460175674997f27131b3162dd2da89f0e10f9c6feb9b417d` |
| `data/XLB.csv.gz` | `ab4faa93a123aa15b8276a89815105db2dfb90506aac81ddcbbe48dc4f3e62e4` |
| `data/XLC.csv.gz` | `b50dc748391fef615240c6ba40c134e71a6bc6318aae25530f0799bcd7da8ae0` |
| `data/XLE.csv.gz` | `f804deb711677a20d599363835af6cb10ce545d28419934e894885414f028970` |
| `data/XLF.csv.gz` | `f5b8c33f57c3b59ccb259436401da1918c2bbeb544c2c81fd52c424c2b1cea0d` |
| `data/XLI.csv.gz` | `dedd39929a1f4951ca67fa32d978972407da8ed8178baafa81b877ad34a6732e` |
| `data/XLK.csv.gz` | `dc42f7a3318eaba28f49bed0a8d8e59852b74fcfb8e0fc303450235a57c86db9` |
| `data/XLP.csv.gz` | `cde5d5d8063726edf6f03bdd3e33f342f78811c7c84cb67d5098f199f36afb78` |
| `data/XLRE.csv.gz` | `f62aa7257aaea8236bd0bc8c8ae7a2163fd33a3fed4fd5f64cb68c9278ca3d59` |
| `data/XLU.csv.gz` | `b68c3f981108c6765448a6405618828bc81e79a8794f48284a965c0153945478` |
| `data/XLV.csv.gz` | `a4efa0c6d3de98130e87f9db7aa11a2f396d7d4b3136cb3a3173cebfdc260603` |
| `data/XLY.csv.gz` | `2264b80282598ee95eaa2c74aabeb5c1553638795684d461d88d7f87d4d7f746` |
| `data/sp500_historical_constituents.csv.gz` | `a2d40878a6e8a6e6d48e11958ea0310715b3d245b9042d403298a88fc9953cb0` |

구성종목 원본(압축 전) SHA-256: `64410d91ece1c19c1cc5eb1cc597dea6600728bf93530b42bfcaf447ceee702b`.
해시 일치는 파일 동일성만 증명하며 과거 정보 가용성을 증명하지 않는다.
이 기록에는 완료 토큰을 남기지 않았다. 게시 결과는 아래에 추가한다.

### 게시 결과

증거 커밋 `38a15e61dfe95c3b02aab539732dcc20b63252fc`를
`origin/research/day1-validation-20260918`에 정상 push했다.
별도 worktree `/tmp/quant-day1-validation-20260918`에서 이 신규 디렉터리만 커밋했다.
원본 `/opt/quant`는 `main`과 기존 미커밋 상태를 유지하며, 이 산출물 디렉터리도 그대로 남아 있다.
main 병합·push 및 서비스 조작은 하지 않았다. 다음 감독은 재다운로드하지 말고 위 보류 사유부터 해결한다.

### 최종 대조에서 확인한 공유 작업 변경

09:52:43 UTC에 원본 main HEAD가 `17bad161b019eba3a62bd526f840394dea9ab340`으로
진행된 것을 확인했다. 다른 공유 작업의 `814ec7f`, `e598206`, `17bad16` 커밋이 추가되었고,
runner 내용·권한 및 원본 프로토콜 파일 권한이 최초 관측과 달라졌다. 원본 프로토콜 내용,
루트 PROGRESS.md, 보고서 README 내용은 그대로다. 이번 작업은 해당 파일들을 쓰거나 되돌리지 않았다.
`workspace_final_observation.json`에 최초/현재 SHA-256·권한·관측시각을 저장했다.
게시 전 보존 검사와 이 최종 관측을 구분해야 한다. 고정 증거 55개 및 연구 브랜치의 산출물은 여전히 일치한다.


## 2026-09-18 14:15 UTC — Day 1 재개 검토 (DAY_1_BLOCKED)

사전등록 계약과 입력 패널의 보류 사유 B1/B2/B3가 남아 있어 Day 1 미완료를 유지한다.
초기 프로토콜 커밋 및 로컬 연구 기록을 검색했으나 이들을 해소하는 승인 기록을 찾지 못했다.
S6 역사적 방법의 근거(루트 작업55/60)는 확인했지만 S5 상세 정의·XLRE 표본 충돌·PIT 입력
출처를 대신하지 못한다. 완료 표식은 기록하지 않는다. 다음 감독은 새 명세/입력 근거부터 확인한다.

산출물 디렉터리: `day1_review_20260918T141530Z/`.
생성 파일: `review.md`, `RESUME_NOTE.md`, `initial_observation.json`, `registration_search.json`,
`integrity.json`, `tests.log`, `require_complete.json`, `commands.json`, `probe_reference_contract.py`,
`reference_probe.json`, `current_reference_comparison.json`, `publication_validation.json`,
`result_hashes.json`. 게시 및 최종 작업 보존 관측은 `publication.json`,
`workspace_final_observation.json`에 추가 기록한다. 루트와 이 디렉터리의 진행/재개 기록은
기존 내용을 보존하고 이번 결과만 덧붙였다.

검증: 고정 증거 55개 일치; 데이터 20개(ETF 19+구성종목 1)의 저장/압축 전 해시 일치;
기존 회귀 6 passed; 별도 게시 worktree에서도 6 passed; 완료 요구 검사 종료 코드 2.
합성 검사에서 다음 시가가 109인 초기 매수의 실제 0.9174%와 참고 계산 10%의 차이,
미래 주식수 fallback, 미래 구성종목 fallback을 재현했다. 세 참고 함수의 AST는 현재
main에서도 같다. 결함 재현은 전략 통과를 뜻하지 않는다. 허용 프록시 후 첫 공통 일자는
2015-10-08, 2015년 말까지 59행으로 12개월 신호를 첫 표본외 구간에 제공할 수 없다.

| 고정 증거 | SHA-256 |
| --- | --- |
| 기존 `spec.json` | `c5296b50e31f35804ffae5ba3cfd738e64431ead2551b931b85becf970259d97` |
| 기존 `manifest.json` | `09466ed870c477753a6ff7d0327cb0a6786dbfd142a6ea352d87d30df4210b9d` |
| 기존 `snapshot_lock.json` | `3022ec9a3169c827ccb398c309b2cd0d46be87fce7f467e1ef0a20f366f62f9e` |
| 데이터 20개 path→저장 해시 목록 (정렬 키 compact JSON, UTF-8, 개행 없음) | `de0ab5ab2117c537c61bfebca6bbfbc10c462a51d684ee3275ac04631c3a5bcc` |
| 이번 `result_hashes.json` | `ed2d32ecbf8b123e6978db68b61d28d7d08d988aa63a6131964c18786e8eaa6f` |

개별 데이터 해시 20개는 위의 원래 기록 및 `reference_probe.json`에 있다.
관측한 main 코드 SHA: `3f122bce490505ea3ba84872ad39fea0513aaded`.
manifest의 원래 참고 SHA `ba408756b47e53c170a168db63e53a45d979baf6`는 변경하지 않았다.
새 실행 엔진의 인증이나 데이터의 point-in-time 적합성 통과를 주장하지 않는다.

기존 게시 worktree 경로가 사라져 원래 연구 브랜치 `dced9bc`에서
`research/day1-review-20260918`을 만들었다. worktree: `/tmp/quant-day1-review-20260918`.
main과 기존 미커밋 연구를 보존하며 이 기록만 새 연구 브랜치에 게시한다.

### 이번 재개 검토 게시 결과

증거 커밋 `74c21a347cb6d585a44d0ae8580d3705cced1016`를 `origin/research/day1-review-20260918`에 push했고,
`git ls-remote`로 같은 SHA를 확인했다. `day1_review_20260918T141530Z/publication.json`에 기록했다.
Day 1 보류 상태는 그대로다. 다음 감독은 새 사전등록 근거가 있는지 확인한 뒤 재개한다.

## Day 1 완료 — 소유자 위임 판단으로 B1/B2/B3 해소 (2026-09-19)

사용자가 명시적으로 "진행시켜줘, 선조치 후보고로" 위임한 판단으로 세 보류 사유를 모두
해소했다 (전문: `day1_resolutions.md`). 후보/기준선/게이트는 변경 없음.

- **B1** (S5 미정 규칙): S4와 동일한 5-ETF 유니버스(SPY/EFA/IEF/GLD/DBC), 12개월 절대모멘텀
  양수분 중 상대모멘텀 상위 3, 미달분은 현금으로 확정.
- **B2** (XLRE 워밍업 부족): 프로토콜이 XLC에 이미 승인한 것과 동일한 방식으로, 2007–2015
  장기 프록시 구간은 VNQ(2004년 상장)로 XLRE를 대체하고 결과를 "프록시"로 표기. 2015-10-08
  이후는 실제 XLRE로 전환.
- **B3** (S6 provenance 불명확): 데이터셋(fja05680/sp500)의 이 저장소 도입 시각을 커밋
  `c0347056`(2026-07-17)로 기록해 upstream 발표 시각과 명시적으로 구분. S6 독립 평가는
  기존 세 표본외 구간을 그대로 사용(추가 축소 불필요). 리뷰가 찾은 두 실제 코드 결함(미래
  발행주식수 fallback 가능성, next-open 체결과 다른 shift(1) 근사)은 정책 판단이 아니므로
  새로 만들지 않고 **Day 2/Day 6 통과 조건에 명시적으로 편입**: Day 2 산출물에 "미래
  발행주식수 fallback 미사용 확인"을, Day 6 산출물에 "next-open 체결 엔진 단위테스트로
  close-to-close 근사와의 차이 확인"을 추가 조건으로 요구한다.

DAY_1_COMPLETE


## 2026-09-19 — Day 2 완료: 가격·기업행사·프록시·시간대 감사

DAY_2_COMPLETE

판정: Day 2의 결측 처리/프록시 명시 조건 및 Day 1 B3의 미래 주식수 fallback 미사용
조건을 연구 전용 입력 경로에서 충족했다. 원본 55개 해시 유지; ETF 20개 98,245행의 내부
결측/중복/비양수 OHLC 0; 거래량 0인 XLRE 5행은 보존하고 해당 시가 주문은 차단.
provider 분할 6건(실제 분할 5+XLF 현물분배 1), 조정계수 2% 초과 27건을 기록했다.
완료 월말 248개에 대해 다음 세션 시가 경계를 검사했고 관련 테스트 27개 통과.
기존 shift(1) 근사 10%와 실제 시가 109 체결 0.917431% 차이 및 미래 주식수 차단을 재현했다.
완성된 전략 엔진/S6 PIT 패널 인증은 아니며 Day 3/4/6 인계 조건은 `data_audit.md`에 명시했다.

보고서: `data_audit.md`; 판단: `day2_resolutions.md` (체크포인트 2개·즉시 Telegram 보고 성공).
생성 파일: `day2/RESUME_NOTE.md`, `day2/VNQ.csv.gz`, `day2/XNYS_sessions.csv.gz`, `day2/audit.log`, `day2/audit_results.json`, `day2/capture.log`, `day2/capture_inputs.py`, `day2/corporate_actions.csv`, `day2/data_contract.py`, `day2/external_sources.json`, `day2/initial_workspace.json`, `day2/input_manifest.json`, `day2/monthly_session_edges.csv`, `day2/notification_log.json`, `day2/price_flags.csv`, `day2/price_inventory.csv`, `day2/proxy_splice.csv`, `day2/result_hashes.json`, `day2/run_audit.py`, `day2/test_data_contract.py`, `day2/tests.log`, `day2/validation.json`.
Day 1 원본 spec/manifest/lock/19개 가격은 바꾸지 않았다. VNQ는 기존 Day 1 지정에 따라
별도 입력으로 추가했으며 이후 그 해시도 고정한다. 자동 생성 일일 HTML은 게시하지 않는다.

| 증거 | SHA-256 |
| --- | --- |
| 기존 spec.json | c5296b50e31f35804ffae5ba3cfd738e64431ead2551b931b85becf970259d97 |
| 기존 manifest.json | 09466ed870c477753a6ff7d0327cb0a6786dbfd142a6ea352d87d30df4210b9d |
| 기존 snapshot_lock.json | 3022ec9a3169c827ccb398c309b2cd0d46be87fce7f467e1ef0a20f366f62f9e |
| 새 VNQ 저장 데이터 | e74c208a307cb4f59b8ca9390d7544096ecc6b2d1824bf68ed9aa00b9bafdbff |
| 독립 XNYS 달력 | 94780f283f01ffe25ec3a05281a676fa5a0c34964f6e1e070b1c4b9ab60f85fa |
| 데이터 22개 목록(정렬 키 compact JSON, UTF-8, 개행 없음) | a8132c4441f818e47309dee4cbb93bb3067b18edc40371bda00679862fb6e86d |
| Day 2 result_hashes.json (기존+신규 증거 79개) | 4fd7ea3ced381b7e33957eccadf68cf653f7fad0f87be7d3d060d9a2cda6b2cc |

모든 개별 데이터 해시는 `day2/audit_results.json`, 저장/압축 전 해시는 원본 및
`day2/input_manifest.json`, 검증 결과는 `day2/validation.json`과 `day2/tests.log`에 있다.

다음 감독은 Day 3만 수행한다. 실제 next-open/드리프트/현금/비용 엔진으로 기준선과 S1~S5의
`baseline_metrics.csv`를 만들고, 2007년 HYG 웜업 공백·0거래량 시가 차단·VNQ→XLRE 양쪽 비용을
지킨다. 프록시/실제 표본을 분리하고 Day 4의 S6 과거 공시시각 검증을 누락하지 않는다.
별도 연구 브랜치 `research/day2-data-audit-20260919`에 게시하며 게시 SHA와 원격 확인은
`day2/publication.json`에 추가 기록한다.


### Day 2 게시 확인

감사 증거 커밋 `57bc201121ea700c622165d740f7f89e2e7da028`를 `origin/research/day2-data-audit-20260919`에 push하고 원격 SHA 일치를 확인했다.
게시 worktree에서도 테스트 27개 통과; 기존 미커밋 파일/진행 기록의 원래 내용 보존과 원본+신규 증거
79개 해시 일치를 확인했다. `day2/publication.json`, `day2/workspace_final_observation.json`에 기록했다.
main은 원래 HEAD를 유지하며 push/서비스 조작/일일 HTML 커밋은 하지 않았다.


## 2026-09-19 — Day 3 완료: 전 기간 비용 후 기준선/S1~S5

DAY_3_COMPLETE

Day 3 통과 조건인 정확한 다음 거래 세션 시가 체결과 양쪽 매매대금 비용 반영을 충족했다.
실제 17자리 2019-07-01~, 프록시 17자리 2008-05-01~, 실제 5자산 2007-03-01~의
공통 웜업 비교기간을 2026-09-17까지 평가했다. 실제/프록시 공통 표본 각각 24행,
별도 5자산 15행으로 `baseline_metrics.csv`는 63행이다. 후보 수는 여전히 6개이며
이번 평가 대상만 S1~S5다. S6·OOS·PBO/DSR·선택 게이트 판정은 해당 Day에 남긴다.

생성 파일: `baseline_metrics.csv`, `day3_report.md`, `day3_resolutions.md`;
`day3/backtest.py`, `run_day3.py`, `validate_results.py`, `verify_saved.py`,
`finalize_evidence.py`, `test_backtest.py`, `initial_workspace.json`, `notification_log.json`,
`run_manifest.json`, `run.log`, `tests.log`, `execution_validation.json`,
`saved_validation.json`, `saved_validation.log`, `validation.json`, `sample_coverage.csv`,
`sample_boundary_audit.csv`, `zero_volume_usage.csv`, `zero_volume_held_marks.csv`,
`publication_validation.json`, `RESUME_NOTE.md`, `result_hashes.json`;
63쌍의 `<sample>__<strategy>__<cost>bp.daily.csv.gz`/`.orders.csv.gz` 및
`actual_17.signals.csv.gz`, `proxy_17.signals.csv.gz`, `actual_5_full.signals.csv.gz`.
위 모든 파일의 실제 경로·SHA-256은 `day3/result_hashes.json`에 나열했다.
게시 후 `publication.json`, `workspace_final_observation.json`을 추가한다.

검증: 테스트 63 passed(기존 27+Day 3 36), 별도 게시 worktree 63 passed.
63개 계좌의 체결 54,606개와 순자산 228,360행을 실제 티커 단위로 독립 재구성했고
CSV 저장 후에도 일치했다(최대 NAV 상대오차 6.5503158452884236e-15).
동일일 종가 체결/비정상 다음 세션/거래량 0 체결 모두 0건. 양쪽 비용, 진입비용,
드리프트, 현금 슬롯, 보유 갭, 미래 가격 변경 불변, 결측 시가 차단을 확인했다.
기존 증거 55개/Day 2 증거 79개/데이터 22개 해시 유지.
거래량 0 XLRE 5개 날짜를 보존했고 실제 보유 가격 평가 39행(비용률별 계좌 합산)을
명시했다. 거래가능성/과거 가격 빈티지의 한계는 남으며 S6 PIT 인증으로 대체하지 않는다.

| 증거 | SHA-256 |
| --- | --- |
| 데이터 22개 path→sha 목록 (정렬 키 compact JSON, UTF-8, 개행 없음) | a8132c4441f818e47309dee4cbb93bb3067b18edc40371bda00679862fb6e86d |
| baseline_metrics.csv | 57644d3e8fcbb4b0dda8dac10344e4f7b590f8a2d48c25df187ef72293cabcfd |
| day3/result_hashes.json (기존+신규 232개 증거) | eead5ea262341b40897f2ee627e5d6342f308cda46843eb9f50ff5723cd812e1 |

성과 조회 전 판단 체크포인트: `20260919T200502Z_day3-execution-contract`.
`day3_resolutions.md`에 근거를 기록하고 즉시 Telegram 전송 성공했다. 후보/기준선/게이트
변경 없음. 기존 미커밋 파일 보존 검사 통과; root와 실험 진행/인계 문서는 추가만 했다.

다음 자동 감독은 **Day 4만** 수행한다: 실제 발표시각·과거 sector·주식수 단위·상장폐지
가격을 포함한 S6 PIT 입력 인증과 S1 공통 일자 비교, `satellite_audit.md`.
미래 fallback 금지. Day 3 결정론적 백테스트를 반복하지 않는다.


### 2026-09-19 — 고정 14일 프로토콜 Day 4 PIT 감사 보류

DAY_4_BLOCKED

S6 PIT 입력을 반기 40회·원본 식별자 949개·종목/시점 20,156건 감사했다.
미래에만 존재하는 주식수 8,521건, 주식수 없음/빈 캐시 531건을 확인했고
공개시각·과거 섹터·증권 식별자/단위·상장폐지 경로를 인증한 반기는 0개다.
현재 섹터 변경에 따른 과거 pool 변동, 체결일 종가를 시총 순위에 쓰는 경로,
미래 fallback 및 종가 근사의 next-open 불일치를 합성 입력으로 재현했다.
S6를 실행하지 않았고 S1 공통 비교 6개는 NOT_EVALUABLE로 남겼다. 완료 표식 없음.

생성 파일: `docs/experiment_validation/satellite_audit.md`, `day4_resolutions.md`,
`day4/`의 입력 manifest·캐시 목록·고정 관측치·종목/반기 누락표·원본 식별자 매핑,
코드/테스트/누수 재현 결과·비교 상태 CSV·검증 JSON·재개 문서.
전체 생성 파일 경로·개별 SHA-256은 `day4/result_hashes.json`에 기록했다.
검증: 78 tests passed(기존 63+신규 15), 게시 worktree에서도 78 passed;
저장 파일 독립 감사 PASS(20,156행), S1 저장 주문 4,551건의 다음 시가·비용 일치.
완료 요구 검사 종료 코드 2(BLOCKED); 기존 232개 증거 및 동결 데이터 22개 해시 유지.
동결 데이터 목록 SHA-256: `a8132c4441f818e47309dee4cbb93bb3067b18edc40371bda00679862fb6e86d`.
진단 입력 6개 목록 SHA-256: `691125e34c07b7a80ecafa717cf04bd30ffbd8b7cb28154206214d9c7b6b0cb8`.
결과 증거 268개 목록 SHA-256: `e2feee3b02da9fe7685224b6c32bbfedce83937289a87469f1f6a1e424de5e4c`.

판단은 체크포인트 `20260919T205729Z_day4-pit-certification` 후 문서화/즉시 Telegram 보고했다.
후보·기준선·게이트·원본 해시·기존 미커밋 연구는 보존했다. Day 3 미게시 증거는 별도
Day 4 브랜치의 의존 커밋 `6ea72a8`에 복사했고 기존 Day 3 worktree/index는 보존했다.
게시 브랜치: `research/day4-satellite-audit-20260919`; 원격 확인은 `day4/publication.json`.
다음 자동 감독은 Day 5로 넘어가지 않고 **Day 4 재개**: 공개시각을 검증할 수 있는
PIT 입력을 확보한 뒤 S6 다음 시가 재현/S1 공통 날짜 비교를 수행한다. 새 증거가 없으면
캐시 재수집·완료된 Day 3 백테스트 반복 금지. `day4/RESUME_NOTE.md`에 상세 명령을 남겼다.

Day 4 게시 확인: 증거 커밋 `81723b7db1e88e6f45a096619a7fc7b0ffdeae97`을
`origin/research/day4-satellite-audit-20260919`에 push하고 원격 SHA 일치를 확인했다.
보류 결과 Telegram 전송 성공. `day4/publication.json`에 기록했고 Day 4 미완료를 유지한다.


### 2026-09-20 — Day 4 재개: SEC 원천 확인, PIT 전체 인증 보류

DAY_4_BLOCKED

이전 Day 4 원천 1,548개와 증거 268개 해시를 확인했고 추가 로컬 PIT 자료는 찾지 못했다.
새 SEC 원문 3개를 확보해 A(Agilent) 주식수 70행 전체를 공시 accession에 연결했다.
관측일과 제출일은 70행 모두 다르고 수정 공시도 2행이다. 전체 모집단의 과거 섹터·공개시각·
증권 단위·상장폐지 입력은 여전히 미인증이므로 S6 재현과 S1 공통 비교는 미완료다.
완료 표식은 추가하지 않았고 Day 5를 시작하지 않았다.

산출물: `docs/experiment_validation/day4_review_20260920/`의 `review.md`,
SEC 원문 3개·조회 receipt·`input_manifest.json`·관측/공시 진단 JSON·소스/회귀 테스트,
`local_input_delta.json`, `validation.json`, `result_hashes.json`, `RESUME_NOTE.md`.
개별 경로·해시는 result_hashes.json(20개)에 기록했다. 신규/Day 4 회귀 30개 통과;
기존 독립 감사 PASS(20,156행, S1 저장 주문 4,551건), 완료 요구 종료 코드 2(BLOCKED).
데이터 22개 동결 목록 SHA-256: `a8132c4441f818e47309dee4cbb93bb3067b18edc40371bda00679862fb6e86d`.
신규 SEC 원문 3개 목록 SHA-256: `772532f5e1596d41be27fd268aca88d6384ef13e829e77c77a28dc4f538a958a`.
이번 결과 목록 파일 SHA-256: `030a176b498e30a1d870a44dbb38682663f49c22a435e7008258f0b1824ba694`.

CIK 정수/문자열 처리 결함은 체크포인트 `20260920T012004Z_day4-sec-cik-type` 후
문서화·즉시 Telegram 보고했다. 기존 결과/미커밋 연구·후보·기준선·게이트는 보존했다.
다음 자동 감독은 Day 4에 머물러 전체 선정 모집단의 과거 구성·섹터·증권/단위·공개시각 및
상장폐지 가격 자료를 확보한다. 이미 받은 SEC 파일이나 완료된 백테스트는 반복하지 않는다.
연구 브랜치 `research/day4-source-review-20260920`; 실제 게시 결과는 같은 폴더 `publication.json`.


### 2026-09-20 — Day 4 재개: 공식 과거 섹터 공지 원천 감사

DAY_4_BLOCKED

MSCI/S&P 공동 공지 PDF와 MSCI 기업별 변경 공지 HTML을 새로 확보했다. 미국 구간 62행을
독립 대조했고 섹터 코드 변경은 20행이다. MSCI 적용일과 S&P 적용일이 달라 이 목록을
S&P500 전체 과거 섹터로 편입하지 않았다. 전체 모집단 PIT/주식수 단위/상장폐지 입력은
여전히 미인증이다. S6 재현·S1 공통 비교 미완료, 완료 표식 없음, Day 5 미착수.

산출물: `docs/experiment_validation/day4_sector_sources_20260920/`의 `review.md`,
원문 2개(로컬만 보존), 조회 receipt 2개, `input_manifest.json`, `source_diagnostics.json`,
`usa_announced_code_changes.csv`, 파서/검증 코드·테스트·로그, `local_input_delta.json`,
`validation.json`, `result_hashes.json`, `RESUME_NOTE.md`. 전체 18개 경로/개별 해시는
`result_hashes.json`에 기록했다. 신규 11+기존 Day 4 15개 테스트 통과(26 passed).
신규 원문/CSV 독립 감사 PASS, 완료 요구 종료 코드 2(BLOCKED). 기존 증거 268+20개,
동결 데이터 22개, 기존 로컬 원천 1,548개 해시 유지. 기존 백테스트 재실행 없음.
동결 데이터 목록 SHA-256: `a8132c4441f818e47309dee4cbb93bb3067b18edc40371bda00679862fb6e86d`.
신규 원문 2개 목록 SHA-256: `0572bac5ba5f54e7f741c587ad5811f808ff0321454adf524ace6e488059c02b`.
결과 목록 파일 SHA-256: `b1b66242954f473d5858a8717686bde6a064f9c577387ca212d9cd6d7f75f6fa`.

새 전략 해석/기존 버그 수정 없이 기존 PIT 계약에 따라 원천만 감사했다. 후보·기준선·게이트,
기존 미커밋 작업은 보존했다. 다음 감독은 전체 S&P 구성/과거 섹터의 공개·유효시각과
증권/단위/상장폐지 가격 입력부터 확보한다. 새 자료가 없으면 이번 공지나 이전 SEC/캐시/
백테스트를 반복하지 않는다. 상세 명령은 해당 폴더 `RESUME_NOTE.md`, 게시 결과는
`publication.json`. 연구 브랜치 `research/day4-sector-sources-20260920`.
