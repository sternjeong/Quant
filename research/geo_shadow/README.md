# AI 국제정세 의견 초안 (야간 배치 geo_analyst 가 씀)

매달 25일 이후 한 번, 다음 달 코어 리밸런싱 전에 `<YYYY-MM>.json` 을 쓴다. 배치가 검증해 `data/geo_shadow/ledger.jsonl`
(에이전트가 쓸 수 없는 원장)에 시각과 함께 기록한다. 배분에는 반영하지 않는다. 판정 규칙: `core/geo_shadow.py` (geo-judge/v1).
