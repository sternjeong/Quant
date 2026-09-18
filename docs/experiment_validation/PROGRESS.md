# 14일 검증 진행 기록

## 2026-09-18 — Day 1 보류 (DAY_1_BLOCKED)

판정: 명세·입력 패널의 사전 고정을 완료하지 못했다. 감독기는 Day 1에 머물러야 한다.
후보 6개·기준선 3개·선택 게이트 및 원본 프로토콜을 변경하지 않았다.

생성 파일: `candidates.yaml`, `spec.json`, `manifest.json`, `snapshot_lock.json`,
`initial_workspace.json`, `capture_day1.py`, `capture.log`, `check_snapshot.py`,
`test_snapshot.py`, `day1_validation.json`, `validation_tests.log`, `day1_findings.md`,
`README.md`, `RESUME_NOTE.md`, `source/`의 원본 6개, `data/`의 가격 19개·메타데이터 19개·구성종목 1개.

검증 결과: ETF 19/19 조회 성공; 고정 증거 55개 SHA-256 일치; 변조/누락/완료 우회/동일일 종가 설정
차단 테스트 6개 통과(0.10초); `--require-complete` 종료 코드 2; 기존 미커밋 추적 파일 4개 내용·권한 보존.
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
