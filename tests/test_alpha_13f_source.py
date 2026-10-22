import csv
import json

from research.alpha_discovery.sec_13f_source import entries_from_submissions, fetch_filing, main, parse_equity_shares


def test_equity_parser_aggregates_shares_and_excludes_options_principal():
    def row(shares, value, kind="SH", option=""):
        return (f"<infoTable><nameOfIssuer>ACME</nameOfIssuer><cusip>123456789</cusip>"
                f"<value>{value}</value><shrsOrPrnAmt><sshPrnamt>{shares}</sshPrnamt>"
                f"<sshPrnamtType>{kind}</sshPrnamtType></shrsOrPrnAmt>"
                f"<putCall>{option}</putCall></infoTable>")
    xml = ("<informationTable xmlns='http://www.sec.gov/edgar/document/thirteenf/informationtable'>"
           + row(10, 100) + row(5, 50) + row(40, 500, "PRN") + row(20, 200, "SH", "Put")
           + "</informationTable>").encode()
    rows, counts = parse_equity_shares(xml)
    assert len(rows) == 1
    assert rows[0]["shares"] == 15
    assert rows[0]["value_reported"] == 150
    assert counts == {"information_rows": 4, "options": 1, "principal": 1, "invalid": 0}


def test_submissions_include_amendments_and_reject_after_cutoff():
    meta = {"filings": {"recent": {"form": ["13F-HR", "13F-HR/A", "13F-HR"],
            "accessionNumber": ["1", "2", "3"],
            "filingDate": ["2020-05-15", "2020-05-20", "2025-05-15"],
            "reportDate": ["2020-03-31"] * 3,
            "acceptanceDateTime": ["2020-05-15T17:00:00", "2020-05-20T12:00:00", ""]}}}
    rows = entries_from_submissions(meta, [])
    assert [r["accession"] for r in rows] == ["1", "2"]
    assert rows[1]["form"] == "13F-HR/A"
    assert rows[0]["accepted_at"] == "2020-05-15T17:00:00"


def test_archive_chooses_information_xml_and_preserves_metadata():
    class Client:
        def _get(self, url):
            if url.endswith("index.json"):
                return json.dumps({"directory": {"item": [{"name": "primary_doc.xml"},
                                      {"name": "form13fInfoTable.xml"}]}}).encode()
            assert url.endswith("form13fInfoTable.xml")
            return (b"<informationTable><infoTable><nameOfIssuer>ACME</nameOfIssuer>"
                    b"<cusip>123456789</cusip><value>100</value><shrsOrPrnAmt>"
                    b"<sshPrnamt>50</sshPrnamt><sshPrnamtType>SH</sshPrnamtType>"
                    b"</shrsOrPrnAmt></infoTable></informationTable>")
    item = {"accession": "0000000000-20-000001", "form": "13F-HR", "period": "2020-03-31",
            "filed": "2020-05-15", "accepted_at": "2020-05-15T17:00:00"}
    result = fetch_filing(Client(), "0001067983", item)
    assert result["source_status"] == "PARSED"
    assert result["rows"][0]["shares"] == 50
    assert result["item"]["accepted_at"] == item["accepted_at"]


def test_source_job_smoke_writes_machine_readable_artifacts(tmp_path):
    out = tmp_path / "out"
    assert main(["--smoke", "--out", str(out), "--checkpoint", str(tmp_path / "checkpoint")]) == 0
    result = json.loads((out / "results.json").read_text())
    assert result["verdicts"]["primary"] == "SMOKE_ONLY"
    assert result["performance_calculated"] is False
    assert result["equity_rows"] == 1
    with (out / "13f_raw_shares.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["shares"] == "50.0"
    assert rows[0]["accepted_at"] == "2020-05-15T17:00:00"
