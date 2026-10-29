import json
from disclosed import picks as P
from disclosed.score_picks import overlap_entries

def _e(m, d, tks): return {"mode": "live", "method": m, "pick_date": d, "picks": [{"ticker": t} for t in tks]}

def test_per_method_append_and_chain(tmp_path):
    p = tmp_path / "live.jsonl"
    P.append(p, {"mode": "live", "pick_date": "2026-10-28", "version": "rules-v1", "picks": []})  # legacy, untagged
    P.append(p, _e("consensus", "2026-10-29", ["NVDA"]))
    P.append(p, _e("backtest_best", "2026-10-29", ["NVDA", "DDOG"]))
    ok, _ = P.verify(p); assert ok
    for bad in (_e("consensus", "2026-10-29", []), _e("backtest_best", "2026-10-28", [])):
        try: P.append(p, bad); assert False
        except SystemExit: pass
    assert P.entry_method(P._read(p)[0]) == "backtest_best"
    lines = p.read_text().splitlines(); lines[0] = lines[0].replace("2026-10-28", "2026-10-27"); p.write_text("\n".join(lines) + "\n")
    assert not P.verify(p)[0]

def test_overlap():
    a = [_e("consensus", "d1", ["A", "B"]), _e("consensus", "d2", ["C"])]
    b = [_e("backtest_best", "d1", ["B", "X"]), _e("backtest_best", "d3", ["C"])]
    o = overlap_entries(a, b)
    assert [(e["pick_date"], [p["ticker"] for p in e["picks"]]) for e in o] == [("d1", ["B"])]
