from disclosed.summaries import facts_line, facts_scopes

P = {"ticker": "ACN", "n_members": 4, "n_sellers": 1, "public_date": "2026-10-14", "net_amount": {"net": 1},
     "tx": [{"member": "mccaul", "doc_id": "d1", "amount": "$50,001 - $100,000"}, {"member": "mccaul", "doc_id": "d1", "amount": "$50,001 - $100,000"}]}

def test_scopes_split():
    s = facts_scopes(P, "2026-10-27")
    assert (s["n_buyers"], s["n_tx"], s["n_det_members"], s["n_filings"], s["agg_days"], s["det_days"]) == (4, 2, 1, 1, 90, 14)
    zh = facts_line(P, "zh", "2026-10-27"); en = facts_line(P, "en", "2026-10-27")
    assert "近 90 天" in zh and "4 位議員淨買進" in zh and "以下列出全部 2 筆" in zh and "來自 1 位議員、1 份申報" in zh
    assert "4 位議員申報 2 筆" not in zh
    assert "4 member(s) net buying" in en and "all 2 stock purchase" in en and "1 member(s) in 1 filing(s)" in en

def test_excerpt():
    p = dict(P, tx=[{"member": f"m{i}", "doc_id": f"d{i}", "amount": "$1,001 - $15,000"} for i in range(9)])
    assert "共 9 筆，僅列部分" in facts_line(p, "zh", "2026-10-27") and "6 of 9" in facts_line(p, "en", "2026-10-27")
