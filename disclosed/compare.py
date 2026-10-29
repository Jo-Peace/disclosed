"""Cross-check rule-based vs Meta-model transactions for the same filings (field-level agreement).
Works on whatever is in the DB; reports honest counts. Needs rows with source='rule' AND source='meta'."""
from __future__ import annotations
import argparse, re
from .db import connect

FIELDS = ["owner", "ticker", "tx_type", "tx_date", "notif_date", "amount_low", "amount_high", "cap_gains_over_200"]

def _norm(v):
    return re.sub(r"\W+", "", v.lower()) if isinstance(v, str) else v

def _name(v):
    """asset name without '(TICKER)' and '[XX]' decorations, and without a leading row id, normalised"""
    v = re.sub(r"\[[A-Z0-9]{2}\]", "", v or "")
    v = re.sub(r"\([A-Z0-9.$\-]{1,8}\)", "", v)
    v = re.sub(r"^\d{9,}\s*(SP|DC|JT)?\s*", "", v.strip())
    return re.sub(r"\W+", "", v.lower())

def compare(con=None, doc_ids=None):
    con = con or connect()
    docs = doc_ids or [r[0] for r in con.execute(
        "SELECT DISTINCT doc_id FROM transactions WHERE source='meta' INTERSECT SELECT DISTINCT doc_id FROM transactions WHERE source='rule'")]
    rep = {"docs": len(docs), "docs_same_count": 0, "rows_compared": 0, "row_full_match": 0,
           "field_match": {f: 0 for f in FIELDS}, "asset_name_match": 0, "disagreements": []}
    for d in docs:
        rule = con.execute("SELECT * FROM transactions WHERE doc_id=? AND source='rule' ORDER BY idx", (d,)).fetchall()
        meta = con.execute("SELECT * FROM transactions WHERE doc_id=? AND source='meta' ORDER BY idx", (d,)).fetchall()
        if len(rule) == len(meta): rep["docs_same_count"] += 1
        else: rep["disagreements"].append((d, "row_count", len(rule), len(meta)))
        for a, b in zip(rule, meta):
            rep["rows_compared"] += 1; ok_all = True
            for f in FIELDS:
                same = _norm(a[f]) == _norm(b[f])
                rep["field_match"][f] += same
                if not same:
                    ok_all = False; rep["disagreements"].append((d, a["idx"], f, a[f], b[f]))
            rep["asset_name_match"] += _name(a["asset"]) == _name(b["asset"])
            if _name(a["asset"]) != _name(b["asset"]): rep["disagreements"].append((d, a["idx"], "asset", a["asset"][:50], b["asset"][:50]))
            rep["row_full_match"] += ok_all
    return rep

def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    r = compare()
    if not r["docs"]:
        print("No filing has both rule and meta results yet (run meta_parser first; needs MODEL_API_KEY)."); return
    n = r["rows_compared"]
    print(f"docs compared: {r['docs']}  (same row count: {r['docs_same_count']})  rows: {n}")
    print(f"rows with ALL fields equal: {r['row_full_match']}/{n} = {r['row_full_match']/max(n,1):.1%}")
    for f, c in r["field_match"].items(): print(f"  {f:20s} {c}/{n} = {c/max(n,1):.1%}")
    print(f"  asset name (normalised)  {r['asset_name_match']}/{n}")
    print("first disagreements:")
    for x in r["disagreements"][:25]: print("  ", x)

if __name__ == "__main__":
    main()
