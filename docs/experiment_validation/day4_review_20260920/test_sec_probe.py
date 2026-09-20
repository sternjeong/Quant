"""CIK representation regression; no external requests or strategy execution."""
import importlib.util
import json
from pathlib import Path
import shutil
import pytest

spec = importlib.util.spec_from_file_location("sec_probe", Path(__file__).with_name("probe_sec_access.py"))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


@pytest.mark.parametrize("value", [1090872, "1090872", "0001090872"])
def test_same_issuer_cik_representations(value):
    probe.validate_cik(value)


@pytest.mark.parametrize("value", [None, 1090873, "0001090873", 1090872.0, True, "1.090872e6", "", "Agilent"])
def test_other_issuers_and_malformed_ciks_are_rejected(value):
    with pytest.raises(ValueError, match="unexpected CIK"):
        probe.validate_cik(value)


@pytest.mark.parametrize("args", [[], ["--retry-failed"]])
def test_existing_receipt_prevents_network_access(monkeypatch, args):
    monkeypatch.setattr(probe.sys, "argv", [str(Path(probe.__file__)), *args])
    def forbidden(*args, **kwargs):
        pytest.fail("Existing evidence must not trigger a request")
    monkeypatch.setattr(probe.urllib.request, "urlopen", forbidden)
    with pytest.raises(SystemExit, match="Existing source receipt preserved"):
        probe.main()


@pytest.mark.parametrize("corruption", ["wrong_issuer", "conflicting_accession"])
def test_diagnostic_join_rejects_inconsistent_inputs(tmp_path, corruption):
    root = Path(__file__).parent
    inspector_spec = importlib.util.spec_from_file_location("sec_inspector", root / "inspect_sec_evidence.py")
    inspector = importlib.util.module_from_spec(inspector_spec)
    inspector_spec.loader.exec_module(inspector)
    for name in ("agilent_share_concept.json", "agilent_submissions.json", "agilent_submissions_history.json"):
        shutil.copyfile(root / name, tmp_path / name)
    if corruption == "wrong_issuer":
        path = tmp_path / "agilent_share_concept.json"
        data = json.loads(path.read_text())
        data["cik"] = 320193
    else:
        path = tmp_path / "agilent_submissions_history.json"
        data = json.loads(path.read_text())
        recent = json.loads((tmp_path / "agilent_submissions.json").read_text())["filings"]["recent"]
        data["accessionNumber"][0] = recent["accessionNumber"][0]
        data["acceptanceDateTime"][0] = "1900-01-01T00:00:00.000Z"
    path.write_text(json.dumps(data))
    with pytest.raises(AssertionError):
        inspector.inspect(tmp_path)
