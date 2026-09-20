"""Describe captured facts and accession joins, without certifying PIT inputs."""
import hashlib
import json
from pathlib import Path


def inspect(root):
    concept_path = root / "agilent_share_concept.json"
    submissions_path = root / "agilent_submissions.json"
    concept = json.loads(concept_path.read_text())
    submissions = json.loads(submissions_path.read_text())
    assert int(concept["cik"]) == int(submissions["cik"]) == 1090872
    assert concept["taxonomy"] == "dei"
    assert concept["tag"] == "EntityCommonStockSharesOutstanding"
    facts = concept["units"]["shares"]
    recent = submissions["filings"]["recent"]
    assert len(set(recent["accessionNumber"])) == len(recent["accessionNumber"])
    assert len(recent["accessionNumber"]) == len(recent["acceptanceDateTime"])
    accepted = dict(zip(recent["accessionNumber"], recent["acceptanceDateTime"]))
    recent_matches = sum(row["accn"] in accepted for row in facts)
    history_path = root / "agilent_submissions_history.json"
    history = json.loads(history_path.read_text())
    assert len(set(history["accessionNumber"])) == len(history["accessionNumber"])
    assert len(history["accessionNumber"]) == len(history["acceptanceDateTime"])
    for accession, timestamp in zip(history["accessionNumber"], history["acceptanceDateTime"]):
        assert accession not in accepted or accepted[accession] == timestamp, "conflicting accession timestamps"
        accepted[accession] = timestamp
    matched = [row for row in facts if row["accn"] in accepted]
    raw_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (concept_path, submissions_path, history_path)}
    return {
        "scope": "Source schema/chronology diagnostics only; no cross-issuer universe, ranking or portfolio return",
        "raw_files_sha256": raw_hashes,
        "raw_inventory_sha256": hashlib.sha256(json.dumps(raw_hashes, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "issuer": submissions["name"], "cik": 1090872,
        "concept_cik_type": type(concept["cik"]).__name__, "submissions_cik_type": type(submissions["cik"]).__name__,
        "fact_rows": len(facts), "fact_end_range": [min(r["end"] for r in facts), max(r["end"] for r in facts)],
        "filed_after_observation_end": sum(r["filed"] > r["end"] for r in facts),
        "amended_filing_rows": sum(r["form"].endswith("/A") for r in facts),
        "fact_rows_joined_to_recent_submission": recent_matches,
        "fact_rows_joined_including_history": len(matched),
        "fact_rows_without_submission": len(facts) - len(matched),
        "additional_submission_files_advertised": submissions["filings"]["files"],
        "first_fact_example": {**facts[0], "acceptance_datetime_raw": accepted.get(facts[0]["accn"])},
        "last_matched_example": {**matched[-1], "acceptance_datetime_raw": accepted[matched[-1]["accn"]]} if matched else None,
        "limitations": [
            "Observation end and filing date are different fields; neither proves intraday public availability.",
            "Raw acceptance timestamps are reported without certifying their timezone or public dissemination.",
            "CIK is a filer identity; it is not a historical security/share-class mapping or split-unit certificate.",
            "Current SIC is not a historical GICS sector series and is not substituted into S6.",
            "One issuer cannot certify all members used for sector allocation and market-cap ranking.",
            "No missing delisted prices, corporate actions or historical membership timestamps were filled.",
        ],
        "certified_s6_rebalances_added": 0,
        "day4_complete": False,
    }


if __name__ == "__main__":
    print(json.dumps(inspect(Path(__file__).resolve().parent), indent=2))
