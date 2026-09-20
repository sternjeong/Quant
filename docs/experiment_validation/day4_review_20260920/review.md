# Day 4 재개: 새로운 PIT 원천 가용성 확인

2026-09-20 UTC. **DAY_4_BLOCKED 유지.** S6 재현과 S1 공통 성과 비교를 완료하지 못했다.
이전 Day 4 증거와 사전등록 후보·기준선·게이트는 보존했다. Day 5는 시작하지 않는다.

## 추가로 확인한 증거

이전 감사의 원천 1,548개를 SHA-256으로 대조했으며 전부 동일했다. 이전 캡처 종료 이후
`data/`, `analysis/`, `docs/`에서 PIT 관련 파일명으로 찾은 신규·변경 자료는 없었다.
검색 범위와 결과는 `local_input_delta.json`에 기록했다. 이는 외부에 자료가 없다는 주장이 아니다.

[SEC API 문서](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)는
인증 없이 회사별 XBRL facts와 제출 이력을 제공한다. 과거 자료의 실제 접근을 확인하기 위해
기존 캐시 목록의 첫 알파벳 티커 A(Agilent)를 진단 표본으로 사용했다. 성과나 순위는 보지 않았다.
CIK 1090872는 [SEC 발행사 공시](https://www.sec.gov/Archives/edgar/data/1090872/000109087226000064/0001090872-26-000064-index.htm)로 대조했다.

원문 3개(concept, recent submissions, archived submissions)를 HTTP 200으로 확보했다.
각 URL·조회 UTC·바이트 수·SHA-256은 `sec_access.json`, `sec_access_retry.json`,
`sec_history_access.json`에 있다. 원천은 진단용 별도 스냅샷이며 고정 전략 데이터에 합치지 않았다.

- 주식수 70행(관측일 2009-07-31~2026-08-26) 모두 관측일 뒤에 제출됐다. 수정 공시도 2행이다.
- recent submissions만으로는 40행이 연결됐고, 광고된 과거 파일을 추가하면 70행 모두
  accession 번호로 연결된다. 원 진단 `sec_diagnostics.json`도 보존했다.
- 첫 예시는 관측일 2009-07-31, 제출일 2009-10-05인 10-Q/A다. 관측일을 정보 가용일로
  사용하는 방식이 잘못될 수 있음을 보여준다. 수정 전 원 공시의 값은 별도 검증 대상이다.
- `acceptanceDateTime` 원문을 보존했지만 시간대·실제 공개 지연을 인증했다고 주장하지 않는다.
  CIK는 발행사 식별자이며 주식 종류·분할 단위·과거 ticker 동일성의 증거가 아니다.
  현재 SIC를 과거 GICS 섹터로 대체하지 않았다.

[Norgate 데이터 명세](https://norgatedata.com/data-content-tables.php)는 과거 구성종목·상장폐지
가격을 제공하는 경로를 설명하지만, fundamentals는 현재 값이라고 명시한다.
그 문서만으로 이 실험의 과거 섹터·공개시각·동일 단위 시총 입력을 인증할 수 없다.
구독이나 계정 변경 없이 문서만 확인했으며, 필요한 전체 자료가 제공된다고 단정하지 않는다.

## 아직 막힌 통과 조건

| Day 4 조건 | 현재 증거 | 상태 |
| --- | --- | --- |
| 미래 유니버스 없이 S6 선정 모집단 재현 | 한 회사의 공시 원천 확보; 전체 구성종목의 당시 공개·유효시각/섹터/증권 단위 미인증 | 미충족 |
| 실제 다음 거래일 시가와 5/10/25bp 비용으로 S6 재현 | 종목 선정 입력과 상장폐지·기업행사 가격 경로 미완성 | 미실행 |
| S1과 동일 날짜 비교 | 인증된 S6 반기·공통 날짜 0개 | NOT_EVALUABLE 유지 |

다음 시가를 종가수익률 shift로 대체하거나, 새 자료 한 종목으로 전체 pool을 인증하지 않는다.
이전 S1 저장 주문 4,551건의 다음 세션 시가·비용 검사는 통과했지만 S6 검증과는 구분한다.

## 검증·해시·인계

신규 진단 가드와 기존 Day 4 누수 재현 테스트를 실행했다. 수치와 로그는 `validation.json`,
`tests.log`에 있다. 기존 독립 저장 파일 검사는 PASS이고 완료 요구 종료 코드는 2(BLOCKED)다.
이전 감사 결과 268개의 해시, 동결 데이터 목록, 기존 미커밋 파일 보존도 대조한다.
기존 Day 3 백테스트와 캐시 전체 재수집은 반복하지 않았다.

| 데이터 목록 | SHA-256 |
| --- | --- |
| 기존 동결 22개 | a8132c4441f818e47309dee4cbb93bb3067b18edc40371bda00679862fb6e86d |
| 신규 SEC 원문 3개 | 772532f5e1596d41be27fd268aca88d6384ef13e829e77c77a28dc4f538a958a |

SEC 목록 해시는 파일명→SHA-256의 정렬 키 compact JSON(UTF-8, 개행 없음)이다.
생성 파일 전체 해시는 `result_hashes.json`, 실제 게시 확인은 `publication.json`에 기록한다.
CIK 문자열 처리 결함 수정은 체크포인트 `20260920T012004Z_day4-sec-cik-type` 이후
`day4_resolutions.md`에 기록하고 즉시 Telegram 전송했다. 전략 해석 변경은 없다.
다음 작업·명령은 `RESUME_NOTE.md`를 따른다.
