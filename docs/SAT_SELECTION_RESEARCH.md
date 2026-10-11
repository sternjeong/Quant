# 새틀라이트 종목 선정 방식 탐색 (2026-10-11 사전 등록)

사용자 가설: 새틀라이트는 '어떤 종목을 고르느냐'가 핵심이고, 선정 방식마다 최적 보유기간이 다를 것이다. 지금까지는 모두 같은 champion40 풀 안에서
순서만 바꿨다. 이 연구는 후보 풀과 선정 방식을 바꾼다. 고정 규칙·판정은 `research/jobs/sat-selection-lab/SPEC.md`(각 작업 폴더의 SPEC.md 에도 같은 내용),
구현은 `research/jobs/sat-selection-lab/{lab.py,crsp.py}`, 테스트는 `tests/test_sat_selection_research.py`.

## 작업 (모두 '전진 원장에 올릴 후보'까지만 뜻한다 — 엔진·`core/forward_tournament_v2.py` 는 바꾸지 않는다)

| 작업 | 자료 | 우선순위 | 전략 |
|---|---|---|---|
| sat-pool-v1 | Yahoo(ETF 시대 2010~) | 11 | S1 시총 상위 70·100·150 |
| sat-leader-v1 | Yahoo | 12 | S2 대장주, S3 대장주+추종주, 위약 S2p·S3p |
| sat-follower-v1 | Yahoo | 13 | S4 안전한 추종주 따라잡기 + 진단 D1 |
| sat-pool-crsp-v1 / sat-leader-crsp-v1 / sat-follower-crsp-v1 | CRSP(1963~2007 판정) | 14 / 15 / 16 | 위와 같음, 코어는 업종 코어(core-longrun-v1 복제의 FF12 보유 산업) |

자료 계층은 `Backend` 인터페이스(prices/총수익 지수, PIT 구성종목, PIT 시총, PIT 섹터)로 바뀐다: `yahoo_pit`(현재 코드), `crsp`(아래 계약).

## CRSP 입력 계약

경로 `data/research_inputs/crsp_sp500/` (VM). 파일이 없으면 CRSP 작업은 코드 0 으로 끝나고 판정은 `NOT_EVALUABLE_DATA`, REPORT.md 에 필요한 파일이 적힌다.
파일을 둔 뒤 `python scripts/research_jobs_admin.py retry sat-pool-crsp-v1 --fresh` (세 작업 모두).

```
daily.csv    permno,date,prc,ret,vol,shrout          crsp.dsf        S&P500 구성 이력이 있는 모든 permno, date ≥ 1961-01-01 (가능하면 최신까지)
names.csv    permno,namedt,nameendt,siccd,exchcd,shrcd   crsp.dsenames   같은 permno 의 모든 이름 구간
delists.csv  permno,date,dlret,dlstcd                crsp.dsedelist  같은 permno 전체 (dlret 빈 행 포함, date = dlstdt)
sp500.csv    permno,start,ending                     crsp.dsp500list 전체 (ending 빈칸 = 현재 편입)
```

처리: 시가총액 = |prc|×shrout×1000 (리밸런싱일 전 거래일), 총수익 지수 = 누적곱(1+ret) + 폐지일 dlret((1+ret)(1+dlret)−1; dlret 이 −1~+1 일 때만, −55/−66/−88/−99·빈 값은 미적용·건수 보고),
구성종목 = start ≤ 전 거래일 ≤ ending, 섹터 = 그 시점 siccd → Fama-French 12 산업(`crsp.py` 에 Ken French Siccodes12 범위 고정, 테스트됨).
메모리: 청크(200만 행)로 읽어 구성종목만 남기고 종목×날짜 배열로 변환. 25M 행 기준 피크 약 2GB(max_memory_mb 3000), 읽기·변환 수 분, 이후 선정 계획·시뮬레이션은 체크포인트로 이어서 한다.
