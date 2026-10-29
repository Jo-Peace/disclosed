from disclosed.consensus import net_side, rank, rank_by_count, heavy_trader, clean_company, net_amount, tx_amount, is_consensus, split_rank
from disclosed.names import normalize_name

def tx(ty, td, fd="2026-10-01", lo=1001, hi=15000): return {"ty": ty, "td": td, "fd": fd, "lo": lo, "hi": hi}
def mem(name, side, txs): return {"name": name, "side": side, "tx": txs}

def test_latest_purchase_is_buyer():
    assert net_side([tx("S", "2026-08-01"), tx("P", "2026-09-01")]) == "buy"

def test_bought_then_sold_is_seller_incl_partial():
    assert net_side([tx("P", "2026-08-01"), tx("S", "2026-09-01")]) == "sell"
    assert net_side([tx("P", "2026-08-01"), tx("SP", "2026-09-01")]) == "sell"

def test_missing_tx_date_falls_back_to_filing_date():
    assert net_side([tx("P", "2026-08-01"), tx("S", None, fd="2026-09-15")]) == "sell"

def test_legacy_rank_by_count():
    b = lambda n: mem(n, "buy", [tx("P", "2026-09-01")])
    s = lambda n: mem(n, "sell", [tx("S", "2026-09-01")])
    rows = [{"tk": "AAA", "members": [b("x"), b("y"), s("z")]},
            {"tk": "BBB", "members": [b("x"), b("y")]},
            {"tk": "CCC", "members": [b("x"), b("y"), b("w")]},
            {"tk": "DDD", "members": [s("x"), s("y")]},
            {"tk": "AAB", "members": [b("x"), b("y"), s("z")]}]
    out = [r["tk"] for r in rank_by_count(rows)]
    assert out == ["CCC", "BBB", "AAA", "AAB"]          # DDD (0 net buyers) dropped
    assert rank_by_count(rows)[2]["buy"] == 2 and rank_by_count(rows)[2]["sell"] == 1

def test_heavy_trader_counts_only_net_buyer_rows():
    rows = [{"tk": str(i), "members": [mem("Rohit Khanna", "buy" if i < 2 else "sell", [])]} for i in range(4)]
    assert heavy_trader(rows) is None
    rows = [{"tk": str(i), "members": [mem("Rohit Khanna", "buy", [])]} for i in range(3)]
    assert heavy_trader(rows) == {"name": "Rohit Khanna", "n": 3}

def test_name_normalizer():
    assert normalize_name("John J Mr McGuire III") == "John J McGuire III"
    assert normalize_name("Scott Scott Franklin") == "Scott Franklin"
    assert normalize_name("Neal Patrick MD, Facs Dunn") == "Neal Patrick Dunn"

def test_clean_company():
    assert clean_company("NVIDIA CORPORATION CMN") == "NVIDIA CORPORATION"

def test_tx_amount_midpoint_and_open_ended():
    assert tx_amount({"lo": 1001, "hi": 15000}) == (1001, 8000.5, 15000, False)
    assert tx_amount({"lo": 1000000, "hi": None}) == (1000000, 1000000, 1000000, True)
    assert tx_amount({"lo": None, "hi": None})[1] == 0

def test_net_amount_buys_minus_sales_with_bounds():
    ms = [mem("A", "buy", [tx("P", "2026-09-01", lo=15001, hi=50000)]),
          mem("B", "sell", [tx("P", "2026-08-01"), tx("SP", "2026-09-02", lo=1001, hi=15000)])]
    n = net_amount(ms)
    assert n["net"] == round(32500.5 + 8000.5 - 8000.5)
    assert n["net_min"] == 15001 + 1001 - 15000 and n["net_max"] == 50000 + 15000 - 1001
    assert n["conc"]["name"] == "A" and n["conc"]["share"] > 0.6

def test_rank_by_net_amount_drops_nonpositive_and_tiebreaks_by_buyers():
    big = lambda n: mem(n, "buy", [tx("P", "2026-09-01", lo=50001, hi=100000)])
    small = lambda n: mem(n, "buy", [tx("P", "2026-09-01")])
    sell = lambda n, lo, hi: mem(n, "sell", [tx("S", "2026-09-02", lo=lo, hi=hi)])
    rows = [{"tk": "ONE", "members": [big("x")]},                                   # 75,000
            {"tk": "MANY", "members": [small("a"), small("b"), small("c")]},          # 24,001
            {"tk": "TIE", "members": [small("a"), small("b"), small("c")], },        # same amount, same buyers -> alpha
            {"tk": "NEG", "members": [small("a"), sell("b", 15001, 50000)]},         # net < 0
            {"tk": "ZERO", "members": [small("a"), sell("b", 1001, 15000)]}]         # net == 0
    out = rank(rows)
    assert [r["tk"] for r in out] == ["ONE", "MANY", "TIE"]
    assert out[0]["conc"] == {"name": "x", "share": 1.0}

def test_rank_tiebreak_more_buyers_wins():
    rows = [{"tk": "A1", "members": [mem("x", "buy", [tx("P", "d", lo=2, hi=2)]), mem("y", "buy", [tx("P", "d", lo=2, hi=2)])]},
            {"tk": "B2", "members": [mem("x", "buy", [tx("P", "d", lo=4, hi=4)])]}]
    assert [r["tk"] for r in rank(rows)] == ["A1", "B2"]

def test_consensus_rule_and_split():
    b = lambda n, lo=1001, hi=15000: mem(n, "buy", [tx("P", "2026-09-01", lo=lo, hi=hi)])
    s_ = lambda n: mem(n, "sell", [tx("S", "2026-09-02", lo=1001, hi=1001)])
    rows = [{"tk": "SOLO", "members": [b("x", 1000001, 5000000)]},            # 1 buyer -> big single
            {"tk": "TWO", "members": [b("x"), b("y")]},                        # consensus
            {"tk": "TIE", "members": [b("x"), b("y", 15001, 50000), s_("z"), s_("w")]},  # 2 buyers vs 2 sellers -> not consensus
            {"tk": "NEG", "members": [b("x"), b("y"), s_("z")] + [mem("q", "sell", [tx("S", "2026-09-03", lo=50001, hi=100000)])]}]  # net < 0 -> neither
    main, big = split_rank(rows)
    assert [r["tk"] for r in main] == ["TWO"]
    assert [r["tk"] for r in big] == ["SOLO", "TIE"]
    assert all(is_consensus(r) for r in main) and not any(is_consensus(r) for r in big)
