"""core/etf_holdings.py 단위 테스트 (모듈 D: ETF/펀드 구성종목 조회).

parse_uploaded_holdings() 는 네트워크가 필요 없으므로 합성 CSV/엑셀 바이트로 직접 검증한다.
fetch_spdr_etf_holdings() 는 실제 SSGA 서버 연동이 필요해 이 환경에서 별도로
네트워크 호출로 확인했다(과제 설명 참고), 여기서는 단위 테스트 대상에서 제외한다.
"""

import io

import pandas as pd
import pytest

from core.etf_holdings import parse_uploaded_holdings


def test_parse_uploaded_holdings_csv_english_headers():
    csv_bytes = (
        "Ticker,Name,Weight,Shares Held,Sector\n"
        "AAPL,Apple Inc,10.5,1000000,Technology\n"
        "MSFT,Microsoft Corp,9.2,900000,Technology\n"
    ).encode("utf-8")

    df = parse_uploaded_holdings(csv_bytes, "holdings.csv")

    assert list(df["ticker"]) == ["AAPL", "MSFT"]
    assert df["weight_pct"].iloc[0] == pytest.approx(10.5)
    assert df["shares"].iloc[1] == pytest.approx(900000)


def test_parse_uploaded_holdings_korean_headers_with_thousands_separator():
    csv_bytes = (
        "종목코드,종목명,비중(%),보유수량\n"
        '005930,삼성전자,25.3,"1,200,000"\n'
        '000660,SK하이닉스,15.1,"500,000"\n'
    ).encode("utf-8")

    df = parse_uploaded_holdings(csv_bytes, "korean_fund.csv")

    assert list(df["name"]) == ["삼성전자", "SK하이닉스"]
    assert int(df["ticker"].iloc[0]) == 5930  # 판다스가 숫자로 인식해 앞자리 0이 빠짐 (알려진 한계)
    assert df["weight_pct"].iloc[0] == pytest.approx(25.3)
    assert df["shares"].iloc[0] == pytest.approx(1_200_000)


def test_parse_uploaded_holdings_skips_metadata_rows_before_header():
    """펀드명/기준일 등 안내 행이 실제 헤더보다 위에 있는 실제 SSGA 스타일 파일 형태."""
    rows = [
        ["Fund Name:", "SPDR S&P 500 ETF TRUST"] + [None] * 6,
        ["Ticker Symbol:", "SPY"] + [None] * 6,
        ["Holdings:", "509"] + [None] * 6,
        [None] * 8,
        ["Name", "Ticker", "Identifier", "SEDOL", "Weight", "Sector", "Shares Held", "Local Currency"],
        ["NVIDIA CORP", "NVDA", "67066G104", "2379504", 7.57, "-", 293436061.0, "USD"],
        ["APPLE INC", "AAPL", "037833100", "2046251", 7.16, "-", 177940444.0, "USD"],
    ]
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, index=False, header=False, engine="openpyxl")
    buf.seek(0)

    df = parse_uploaded_holdings(buf.read(), "holdings-daily-us-en-spy.xlsx")

    assert list(df["ticker"]) == ["NVDA", "AAPL"]
    assert df["weight_pct"].iloc[0] == pytest.approx(7.57)


def test_parse_uploaded_holdings_raises_on_unrecognizable_file():
    with pytest.raises(ValueError):
        parse_uploaded_holdings(b"not,a,real,holdings,file\n1,2,3,4,5\n", "junk.csv")
