# 새틀라이트 선정: 후보 풀 확대(S&P500 시총 상위 70·100·150) — CRSP 1963~2007 (상장폐지 포함)

판정: **NOT_EVALUABLE_DATA** — CRSP 내보내기 파일이 준비되지 않았다. 판정은 수행하지 않았다.

문제: daily.csv 없음; names.csv 없음; delists.csv 없음; sp500.csv 없음

## 필요한 파일 (VM 의 data/research_inputs/crsp_sp500/)

```
WRDS(CRSP) 에서 아래 4개 CSV 를 내려받아 data/research_inputs/crsp_sp500/ 에 둔다 (헤더 한 줄, UTF-8, 열 이름 소문자 그대로, 날짜는 YYYY-MM-DD 또는 YYYYMMDD).
1) daily.csv   crsp.dsf (일별 주식 파일)   열: permno,date,prc,ret,vol,shrout
   필터: permno ∈ crsp.dsp500list 에 한 번이라도 나온 permno, date ≥ 1961-01-01(가능하면 2025 말까지). prc 부호(매수·매도 호가 평균은 음수)는 그대로 둔다.
2) names.csv   crsp.dsenames               열: permno,namedt,nameendt,siccd,exchcd,shrcd
   필터: 위와 같은 permno 전체(이름 구간 모두; nameendt 가 열려 있으면 비워도 된다).
3) delists.csv crsp.dsedelist              열: permno,date,dlret,dlstcd
   필터: 위와 같은 permno 전체(dlret 가 비어 있거나 −55/−66/−88/−99 인 행도 포함. date = dlstdt).
4) sp500.csv   crsp.dsp500list             열: permno,start,ending
   전체(구성종목 기간. ending 이 비어 있으면 아직 편입 중).
```

파일을 둔 뒤 `python scripts/research_jobs_admin.py retry sat-pool-crsp-v1 --fresh` 로 다시 돌린다.
