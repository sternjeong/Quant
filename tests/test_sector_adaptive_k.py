import importlib.util
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location("sector_adaptive_k",ROOT/"research/jobs/sector-adaptive-k-v1/run.py")
MOD=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MOD)

def test_adaptive_gap_uses_only_previous_60_months():
    history=[1/12]*60
    assert MOD.choose_k(1/12,history)==2  # ties stay diversified
    assert MOD.choose_k(2/12,history)==1

def test_insufficient_history_defaults_to_top_two():
    assert MOD.choose_k(1.0,[0.0]*59)==2
    assert MOD.choose_k(None,[0.0]*100)==2
