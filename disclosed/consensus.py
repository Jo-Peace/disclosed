"""Congress Consensus: tickers ranked by ESTIMATED NET BUY AMOUNT (sum of purchase range midpoints minus sale midpoints, all members);
net buyer/seller member counts shown alongside. Originally: tickers ranked by NET-BUYING distinct members within N days of the latest filing_date.
Per member per ticker, all P / S / S (partial) transactions in the window are ordered by tx_date (fallback filing_date);
the member's latest transaction decides net buyer (P) vs net seller (S/SP).
Dedupe: per filing use rule rows if any exist, else meta rows; members keyed by normalized name."""
from __future__ import annotations
import datetime as dt, re
from .names import member_id, member_name, name_key
from .performance import LISTED_TYPES   # ("ST", "EF"): options / other instruments excluded (their amounts are not stock holdings)

TYPES = {"P": "P", "S": "S", "S (partial)": "SP", "S(partial)": "SP"}

def clean_company(s):
    s = re.sub(r"\s*\[[A-Z0-9]{2}\]\s*$", "", s or "")
    s = re.sub(r"\s*\([A-Z0-9.$\-/ ]+\)\s*$", "", s)
    s = re.sub(r"(\s+(CMN|COM|COMMON STOCK))+$", "", s.strip(), flags=re.I)
    return re.sub(r"\s+", " ", s).strip(" -")

def sort_key(x):
    return (x.get("td") or x.get("fd") or "", x.get("fd") or "", x.get("doc") or "", x.get("i") or 0)

def net_side(txs):
    """'buy' if the latest transaction (by tx_date, fallback filing_date) is a purchase, else 'sell'."""
    return "buy" if max(txs, key=sort_key)["ty"] == "P" else "sell"

def tx_amount(x):
    """(low, mid, high, open_ended) for one disclosed range. Open-ended top bracket ('Over $X'): low bound used for all three, flagged."""
    lo, hi = x.get("lo"), x.get("hi")
    if lo is None: return 0, 0, 0, False
    if hi is None: return lo, lo, lo, True
    return lo, (lo + hi) / 2, hi, False

def net_amount(members):
    """Estimated net buy across members: purchases minus sales (incl. partial), using range midpoints; min/max from range bounds."""
    mid = lo_ = hi_ = 0.0; open_ = False; buy_by = {}
    for m in members:
        for x in m["tx"]:
            l, md, h, o = tx_amount(x); open_ |= o
            if x["ty"] == "P":
                mid += md; lo_ += l; hi_ += h; buy_by[m["name"]] = buy_by.get(m["name"], 0) + md
            else:
                mid -= md; lo_ -= h; hi_ -= l
    tot = sum(buy_by.values()); top = max(buy_by.items(), key=lambda kv: kv[1]) if buy_by else None
    conc = {"name": top[0], "share": round(top[1] / tot, 3)} if top and tot > 0 and top[1] / tot > CONC_SHARE else None
    return {"net": round(mid), "net_min": round(lo_), "net_max": round(hi_), "buy_amt": round(tot), "open_ended": open_, "conc": conc}

CONC_SHARE = 0.6

def rank(tickers, top=10):
    """Rank by estimated net buy amount (midpoints) desc; drop net <= 0; tie-break by net buyers, fewer sellers, alpha."""
    for t in tickers:
        t["buy"] = sum(m["side"] == "buy" for m in t["members"]); t["sell"] = sum(m["side"] == "sell" for m in t["members"])
        t["n"] = t["buy"]; t["npx"] = sum(x["ty"] == "P" for m in t["members"] for x in m["tx"])
        t.update(net_amount(t["members"]))
    out = [t for t in tickers if t["net"] > 0]
    out.sort(key=lambda t: (-t["net"], -t["buy"], t["sell"], t["tk"]))
    return out[:top]

MIN_BUYERS = 2

def is_consensus(t):
    """Main-board rule: >= 2 net buyers AND net buyers > net sellers AND est. net amount > 0."""
    return t["buy"] >= MIN_BUYERS and t["buy"] > t["sell"] and t["net"] > 0

def split_rank(tickers, top=10, top_big=8):
    """(consensus rows, big single-member rows): both ranked by est. net amount desc; big = net > 0 but fails the consensus rule."""
    allr = rank(tickers, top=10**9)
    return [t for t in allr if is_consensus(t)][:top], [t for t in allr if not is_consensus(t)][:top_big]

def rank_by_count(tickers, top=10):
    """Legacy v2 ranking (net buyers desc) kept for comparison."""
    for t in tickers:
        t["buy"] = sum(m["side"] == "buy" for m in t["members"]); t["sell"] = sum(m["side"] == "sell" for m in t["members"])
        t["npx"] = sum(x["ty"] == "P" for m in t["members"] for x in m["tx"])
    out = [t for t in tickers if t["buy"] > 0]
    out.sort(key=lambda t: (-t["buy"], t["sell"], -t["npx"], t["tk"]))
    return out[:top]

def heavy_trader(rows):
    cnt = {}
    for t in rows:
        for m in t["members"]:
            if m["side"] == "buy": cnt.setdefault(name_key(m["name"]), [m["name"], 0])[1] += 1
    h = max(cnt.values(), key=lambda x: x[1]) if cnt else None
    return {"name": h[0], "n": h[1]} if h and h[1] * 2 > len(rows) else None

_ROWS = {}
def _rows(con):
    k = id(con)
    if k not in _ROWS:
        rule_docs = {r[0] for r in con.execute("SELECT DISTINCT doc_id FROM transactions WHERE source='rule'")}
        assets = {a["ticker"]: a for a in con.execute("SELECT ticker, eligible, sample_name FROM assets")}
        rows = []
        for r in con.execute("""SELECT t.doc_id, t.idx, t.source, t.ticker, t.tx_type, t.tx_date, t.amount_low, t.amount_high, t.amount_text, t.owner, t.asset, t.asset_type,
                          f.first, f.last, f.suffix, f.state_dst, f.filing_date FROM transactions t JOIN filings f USING(doc_id)
                          WHERE f.filing_type='P' AND t.tx_type IN ('P','S','S (partial)','S(partial)') AND t.ticker IS NOT NULL AND trim(t.ticker)!=''"""):
            a = assets.get(r["ticker"])
            if r["source"] == ("rule" if r["doc_id"] in rule_docs else "meta") and a and a["eligible"] and r["asset_type"] in LISTED_TYPES: rows.append((r, a))
        _ROWS[k] = rows
    return _ROWS[k]

def net_members(con, since, until):
    """Point-in-time: {ticker: {tk, name, members:[{id,name,st,side,sold_after_buy,tx}]}} from filings with since <= filing_date <= until."""
    by = {}
    for r, a in _rows(con):
        if not (since <= r["filing_date"] <= until): continue
        t = by.setdefault(r["ticker"], {"tk": r["ticker"], "name": clean_company(a["sample_name"] or r["asset"]), "m": {}})
        m = t["m"].setdefault(name_key(member_name(r)), {"id": member_id(r), "name": member_name(r), "st": r["state_dst"], "tx": {}})
        m["tx"][(r["doc_id"], r["idx"])] = {"ty": TYPES[r["tx_type"]], "td": r["tx_date"], "fd": r["filing_date"], "doc": r["doc_id"], "i": r["idx"],
                                            "am": r["amount_text"] or "", "lo": r["amount_low"], "hi": r["amount_high"], "ow": r["owner"] or "", "at": r["asset_type"]}
    out = {}
    for t in by.values():
        ms = []
        for m in t["m"].values():
            tx = sorted(m["tx"].values(), key=sort_key, reverse=True)
            side = net_side(tx)
            ms.append({"id": m["id"], "name": m["name"], "st": m["st"], "side": side, "sold_after_buy": side == "sell" and any(x["ty"] == "P" for x in tx), "tx": tx})
        ms.sort(key=lambda m: sort_key(m["tx"][0]), reverse=True)
        ms.sort(key=lambda m: m["side"] != "buy")
        out[t["tk"]] = {"tk": t["tk"], "name": t["name"], "members": ms}
    return out

def compute(con, windows=(90, 30), top=10):
    latest = con.execute("SELECT max(filing_date) FROM filings WHERE filing_type='P'").fetchone()[0]
    out = {"latest": latest}
    for w in windows:
        since = (dt.date.fromisoformat(latest) - dt.timedelta(days=w)).isoformat()
        top_rows, big = split_rank(list(net_members(con, since, latest).values()), top)
        for t in top_rows + big:
            for m in t["members"]:
                for x in m["tx"]:
                    for k in ("doc", "i", "at"): x.pop(k, None)
        out[str(w)] = {"since": since, "rows": top_rows, "big": big, "heavy": heavy_trader(top_rows)}
    return out

if __name__ == "__main__":
    from .db import connect
    c = compute(connect())
    for w in ("90", "30"):
        print(f"== {w}d since {c[w]['since']} (latest {c['latest']}) heavy={c[w]['heavy']}")
        for i, t in enumerate(c[w]["rows"] + [None] + c[w]["big"], 1):
            if t is None: print("-- big single --"); continue
            print(i, t["tk"], t["name"][:30], [m["name"] for m in t["members"] if m["side"] == "buy"], f"net ${t['net']:,} [{t['net_min']:,}..{t['net_max']:,}]{' OPEN' if t['open_ended'] else ''} buy {t['buy']} sell {t['sell']} conc={t['conc']}")
