"""Source gates must not mistake old caches or headers for alpha evidence."""
import json

from research.alpha_discovery.input_audit import COMMON, SIGNALS, audit_files, main


def test_missing_and_partial_headers_are_reported(tmp_path):
    (tmp_path / "daily.csv").write_text("permno,date\n1,2020-01-01\n", encoding="utf-8")
    checks = audit_files(tmp_path, COMMON)
    assert next(x for x in checks if x["file"] == "daily.csv")["status"] == "COLUMNS_MISSING"
    assert next(x for x in checks if x["file"] == "delists.csv")["status"] == "MISSING"


def test_every_signal_smoke_is_explicitly_not_a_backtest(tmp_path):
    for index, job_id in enumerate(SIGNALS):
        out = tmp_path / str(index)
        assert main(job_id, ["--smoke", "--out", str(out), "--checkpoint", str(tmp_path / "ckpt")]) == 0
        result = json.loads((out / "results.json").read_text(encoding="utf-8"))
        assert result["verdicts"]["primary"] == "SMOKE_ONLY"
        assert result["performance_calculated"] is False
        assert result["target_experiment"] == job_id
        assert (out / "REPORT.md").is_file()
