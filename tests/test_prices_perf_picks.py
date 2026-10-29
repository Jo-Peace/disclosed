import json, tempfile
from pathlib import Path
from disclosed.prices import normalize
from disclosed.performance import measure, summarize
from disclosed import picks

def test_normalize():
    assert normalize("BRK.B") == ("BRK-B", None)
    assert normalize("AAPL") == ("AAPL", None)
    assert normalize("CADE$A")[0] is None

SD = ["2026-01-02", "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12"]
SP = [100, 101, 102, 103, 104, 105, 106]

def test_measure_next_trading_day_and_horizon():
    td, tp = SD, [10, 11, 12, 13, 14, 15, 16]
    m = measure("2026-01-02", td, tp, SD, SP, 2)         # filing day 1/2 -> entry 1/5, exit 1/7
    assert m["entry_date"] == "2026-01-05" and m["exit_date"] == "2026-01-07"
    assert abs(m["ret"] - (13 / 11 - 1)) < 1e-12 and abs(m["excess"] - (13 / 11 - 103 / 101)) < 1e-12
    assert measure("2026-01-04", td, tp, SD, SP, 2)["entry_date"] == "2026-01-05"   # weekend filing
    assert measure("2026-01-08", td, tp, SD, SP, 5)["status"] == "insufficient_data"
    assert measure("2026-01-02", [], [], SD, SP, 2)["status"] == "no_prices"

def test_summarize_small_sample_flagged():
    s = summarize([0.1, -0.1, 0.2]); assert s["n"] == 3 and s["insufficient"] and abs(s["win_rate"] - 2 / 3) < 1e-9
    assert summarize([])["insufficient"]

def test_hash_chain_append_only_and_tamper():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "log.jsonl"
        picks.append(p, {"pick_date": "2026-01-02", "picks": []}); picks.append(p, {"pick_date": "2026-01-05", "picks": []})
        assert picks.verify(p)[0]
        try: picks.append(p, {"pick_date": "2026-01-05", "picks": []}); assert False
        except SystemExit: pass
        p.write_text(p.read_text().replace("2026-01-02", "2025-12-31"))
        assert not picks.verify(p)[0]
