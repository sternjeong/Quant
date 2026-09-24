"""core.candidate_ledger.update_forward_outcomes 의 price_provider 시그니처(ticker, start, end)에 맞는 Alpaca 어댑터.

동작(티커별):
1. Alpaca 키가 환경에 없으면 기본 공급자(core.candidate_ledger.default_price_provider = yfinance 캐시 정책)를 그대로 쓴다.
   (키 값 자체는 읽거나 출력·저장하지 않고 존재 여부만 확인한다. Codespace 와 VM 양쪽에서 동작.)
2. 키가 있으면 Alpaca 일봉을 받아 기본 공급자의 yfinance 데이터와 core.price_crosscheck 로 대조한다.
   대조가 깨끗할 때(겹치는 날이 있고 major_diff·한쪽 결측·분할 의심·조회 실패가 없을 때)만 Alpaca 봉을 돌려주고,
   그렇지 않으면 기본 공급자 데이터로 폴백한다. 어느 소스를 왜 썼는지는 provider.report() 와 반환 DataFrame 의
   attrs["price_source"] 에 남는다.
3. **어느 소스가 옳은지 판정하지 않는다**(price_crosscheck 의 원칙). 대조 통과는 '두 소스가 일치했다'는 뜻일 뿐이고,
   IEX 피드와 SIP 의 차이·조정 정책 차이는 그대로 한계로 남는다(price_crosscheck.FEED_LIMITATIONS).
일봉만 사용한다. 네트워크 호출은 주입 가능한 함수를 통해서만 일어난다(테스트는 mock).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import pandas as pd

from core import candidate_ledger as cl
from core import price_crosscheck as pcc

ACCEPT_MAX_MAJOR_DIFF = 0
SOURCE_ALPACA = "alpaca"
SOURCE_DEFAULT = "default_provider"


def _bars_to_frame(bars: list[dict]) -> pd.DataFrame:
    rows = {}
    for b in bars or []:
        day = pcc._bar_date(b)
        if day is None or b.get("c") is None or b.get("o") is None:
            continue
        rows[pd.Timestamp(day)] = {
            "Open": float(b["o"]), "High": float(b.get("h", b["o"])), "Low": float(b.get("l", b["o"])),
            "Close": float(b["c"]), "Adj Close": float(b["c"]), "Volume": float(b.get("v") or 0.0),
        }
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame.from_dict(rows, orient="index").sort_index()
    df.index.name = "Date"
    return df


def _reject_reasons(res: dict) -> list[str]:
    """교차 대조 결과에서 Alpaca 봉을 쓰지 않을 사유. 비어 있으면 대조 통과."""
    if res.get("unavailable_reason"):
        return [f"crosscheck_unavailable: {res['unavailable_reason']}"]
    s = res.get("summary", {})
    reasons = []
    if res.get("overlap_days", 0) < 1:
        reasons.append("no_overlapping_days")
    if s.get(pcc.VERDICT_MAJOR, 0) > ACCEPT_MAX_MAJOR_DIFF:
        reasons.append(f"major_diff_days={s[pcc.VERDICT_MAJOR]}")
    if s.get(pcc.VERDICT_MISSING_ALPACA, 0):
        reasons.append(f"missing_in_alpaca_days={s[pcc.VERDICT_MISSING_ALPACA]}")
    if s.get(pcc.VERDICT_MISSING_YFINANCE, 0):
        reasons.append(f"missing_in_yfinance_days={s[pcc.VERDICT_MISSING_YFINANCE]}")
    if res.get("split_suspects"):
        reasons.append(f"split_suspects={len(res['split_suspects'])}")
    return reasons


class AlpacaCrosscheckedProvider:
    """callable(ticker, start, end) -> DataFrame. report() 로 티커별 사용 소스 메타를 얻는다."""

    def __init__(
        self, *, default_provider: Optional[Callable[[str, str, str], pd.DataFrame]] = None,
        env: Optional[dict] = None, alpaca_fetch_fn: Optional[Callable[[str, str, str], list]] = None,
        feed: str = pcc.DEFAULT_FEED,
    ) -> None:
        self._default = default_provider or cl.default_price_provider
        self._fetch = alpaca_fetch_fn
        self._env = env
        self._feed = feed
        self._report: dict[str, dict] = {}

    @property
    def alpaca_enabled(self) -> bool:
        return self._fetch is not None or pcc.credentials_available(self._env)

    def _alpaca_fetch(self, symbol: str, start: str, end: str) -> list:
        if self._fetch is not None:
            return self._fetch(symbol, start, end)
        creds = pcc.AlpacaCredentials.from_env(self._env)  # 값은 이 객체 안에만 머문다(repr 은 redacted)
        return pcc.fetch_alpaca_daily_bars(symbol, start, end, credentials=creds, feed=self._feed)

    def __call__(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        base_meta = {"feed": self._feed, "note": "불일치는 플래그이며 어느 소스가 옳은지 판정하지 않는다."}
        yf_df = self._default(ticker, start, end)
        if not self.alpaca_enabled:
            return self._done(ticker, yf_df, {**base_meta, "source": SOURCE_DEFAULT, "reason": "no_alpaca_credentials"})

        holder: dict[str, Any] = {}

        def _af(symbol: str, a: str, b: str) -> list:
            holder["bars"] = self._alpaca_fetch(symbol, a, b)
            return holder["bars"]

        res = pcc.crosscheck_symbol(ticker, start, end, yf_fetch_fn=lambda *a, **k: yf_df, alpaca_fetch_fn=_af)
        reasons = _reject_reasons(res)
        summary = {k: v for k, v in res.get("summary", {}).items() if v}
        meta = {**base_meta, "crosscheck": summary, "overlap_days": res.get("overlap_days", 0)}
        if reasons:
            return self._done(ticker, yf_df, {**meta, "source": SOURCE_DEFAULT, "reason": "fallback: " + "; ".join(reasons)})
        alpaca_df = _bars_to_frame(holder.get("bars", []))
        if alpaca_df.empty:
            return self._done(ticker, yf_df, {**meta, "source": SOURCE_DEFAULT, "reason": "fallback: alpaca_frame_empty"})
        return self._done(ticker, alpaca_df, {**meta, "source": SOURCE_ALPACA, "reason": "crosscheck_clean"})

    def _done(self, ticker: str, df: pd.DataFrame, meta: dict) -> pd.DataFrame:
        self._report[ticker] = meta
        if isinstance(df, pd.DataFrame):
            df.attrs["price_source"] = meta["source"]
        return df

    def report(self) -> dict:
        """{ticker: 메타} 와 소스별 집계. 키 값은 어디에도 없다."""
        counts: dict[str, int] = {}
        for m in self._report.values():
            counts[m["source"]] = counts.get(m["source"], 0) + 1
        return {"per_ticker": dict(self._report), "source_counts": counts, "alpaca_enabled": self.alpaca_enabled}


def make_alpaca_price_provider(**kwargs: Any) -> AlpacaCrosscheckedProvider:
    """update_forward_outcomes(price_provider=...) 에 넘길 공급자를 만든다."""
    return AlpacaCrosscheckedProvider(**kwargs)


def update_outcomes_with_sources(as_of: Any = None, session=None, provider: Optional[AlpacaCrosscheckedProvider] = None,
                                 **kwargs: Any) -> dict:
    """update_forward_outcomes 를 이 공급자로 실행하고 소스 메타를 함께 돌려준다: {"update", "price_sources"}."""
    prov = provider or make_alpaca_price_provider()
    summary = cl.update_forward_outcomes(as_of, price_provider=prov, session=session, **kwargs)
    return {"update": summary, "price_sources": prov.report()}
