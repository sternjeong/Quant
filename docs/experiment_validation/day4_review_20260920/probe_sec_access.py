"""One-shot, read-only SEC source probe; never supplies strategy inputs.

Agilent (A) is the first alphabetic cache ticker in the frozen Day 4 inventory.
Two public endpoints are checked once; --retry-failed captures only failed URLs
in a separate receipt. No authentication or cache writes. Existing receipts and
raw responses are never overwritten.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request


def validate_cik(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value).isdigit() or int(value) != 1090872:
        raise ValueError("unexpected CIK")


def main():
    output = Path(__file__).resolve().parent
    retry = sys.argv[1:] == ["--retry-failed"]
    if sys.argv[1:] and not retry:
        raise SystemExit("Only --retry-failed is supported")
    receipt = output / ("sec_access_retry.json" if retry else "sec_access.json")
    if receipt.exists():
        raise SystemExit("Existing source receipt preserved; do not repeat probe")
    requests = [
        ("agilent_share_concept.json", "https://data.sec.gov/api/xbrl/companyconcept/CIK0001090872/dei/EntityCommonStockSharesOutstanding.json"),
        ("agilent_submissions.json", "https://data.sec.gov/submissions/CIK0001090872.json"),
    ]
    if retry:
        previous = json.loads((output / "sec_access.json").read_text())
        failed = {row["url"] for row in previous["sources"] if row["status"] != "CAPTURED_DIAGNOSTIC_ONLY"}
        requests = [(name, url) for name, url in requests if url in failed]
    records = []
    for name, url in requests:
        if (output / name).exists():
            raise SystemExit("Existing raw source preserved")
        record = {"url": url, "attempted_at_utc": datetime.now(timezone.utc).isoformat()}
        request = urllib.request.Request(url, headers={"User-Agent": "Quant-Strategy-Validation/1.0 (read-only research)", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = response.read()
                record.update(http_status=response.status, response_sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))
            (output / name).write_bytes(payload)
            parsed = json.loads(payload)
            record["cik_json_type"] = type(parsed.get("cik")).__name__
            validate_cik(parsed.get("cik"))
            record.update(status="CAPTURED_DIAGNOSTIC_ONLY", path=name, top_level_keys=sorted(parsed))
        except urllib.error.HTTPError as error:
            payload = error.read()
            record.update(status="HTTP_ERROR", http_status=error.code, response_sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload))
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            record.update(status="ACCESS_OR_SCHEMA_ERROR", error_type=type(error).__name__)
        records.append(record)
    receipt.write_text(json.dumps({"scope": "Endpoint availability only; no PIT certification or performance calculation", "issuer_selection": "First alphabetical ticker A in previous Day 4 cache inventory; CIK from issuer SEC page", "sources": records}, indent=2) + "\n")
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
