"""Export the SQLite data to static JSON for the single-page site (site/data.json, site/prices.json). No server code needed."""
from __future__ import annotations
import datetime as dt, json, re
from . import config
from .db import connect
from .names import member_id, member_name
from .consensus import compute as consensus
from .performance import HORIZONS, summarize, track_record, LISTED_TYPES
from .picks import LOGDIR, _read, verify, METHODS, entry_method
from .summaries import load as load_ai, facts_line
from .score_picks import OUT as SCORED

SITE = config.ROOT / "site"
PRICE_FROM = "2026-01-01"
TYPE = {"P": "P", "S": "S", "S (partial)": "SP", "E": "E"}

def clean_name(a): return re.sub(r"\s*\[[A-Z0-9]{2}\]\s*$", "", a or "").strip()

def pstat(vals):
    s = summarize(vals)
    return {k: (round(v, 5) if isinstance(v, float) else v) for k, v in s.items()}

def main():
    con = connect(); SITE.mkdir(exist_ok=True)
    perf = {}
    for r in con.execute("SELECT doc_id, ticker, tx_type, horizon, excess, ret, status, entry_date FROM performance"):
        perf.setdefault((r["doc_id"], r["ticker"], r["tx_type"]), {})[r["horizon"]] = (None if r["excess"] is None else round(r["excess"], 4), r["status"])
    filings = con.execute("SELECT * FROM filings WHERE filing_type='P' ORDER BY filing_date DESC").fetchall()
    members = {}
    for f in filings:
        m = members.setdefault(member_id(f), {"id": member_id(f), "name": member_name(f), "state_dst": f["state_dst"], "filings": []})
        m["filings"].append({"doc": f["doc_id"], "date": f["filing_date"], "kind": f["kind"], "pdf": f["pdf_url"], "n": f["rule_n_tx"], "status": f["rule_status"]})
    fmap = {f["doc_id"]: f for f in filings}
    assets = {a["ticker"]: a for a in con.execute("SELECT * FROM assets")}
    txs = []
    CODE = {"approved": "A", "approved_with_caveat": "C", "approved_with_dissent": "D", "rejected": "R", "needs_review": "N"}
    magi = {(r["doc_id"], r["tx_idx"]): (CODE.get(r["consensus"], "N"), r["confidence"], r["disagreement"]) for r in con.execute("SELECT doc_id, tx_idx, consensus, confidence, disagreement FROM magi_results")}
    KEYS = ("owner", "ticker", "tx_type", "tx_date", "notif_date", "amount_low", "amount_high")
    meta_rows = {(r["doc_id"], r["idx"]): r for r in con.execute("SELECT * FROM transactions WHERE source='meta' AND doc_id IN (SELECT doc_id FROM filings WHERE kind!='scanned')")}
    n_by_doc = dict(con.execute("SELECT doc_id, count(*) FROM tx GROUP BY 1").fetchall())
    for f_ in filings:
        for m_ in [members[member_id(f_)]]:
            for fl in m_["filings"]:
                if fl["doc"] == f_["doc_id"]: fl["n"] = n_by_doc.get(f_["doc_id"], 0); fl["status"] = f_["rule_status"] if f_["kind"] != "scanned" else f_["meta_status"]
    for t in con.execute("SELECT * FROM tx ORDER BY id"):
        f = fmap.get(t["doc_id"])
        if not f: continue
        d = "P" if t["tx_type"] == "P" else "S" if t["tx_type"].startswith("S") else None
        pf = perf.get((t["doc_id"], t["ticker"], d)) if d and t["asset_type"] in LISTED_TYPES else None
        a = assets.get(t["ticker"])
        txs.append({"doc": t["doc_id"], "i": t["idx"], "m": member_id(f), "tk": t["ticker"], "a": clean_name(t["asset"]), "at": t["asset_type"], "ty": TYPE.get(t["tx_type"], t["tx_type"]),
                    "td": t["tx_date"], "nd": t["notif_date"], "fd": f["filing_date"], "am": t["amount_text"], "lo": t["amount_low"], "ow": t["owner"] or "", "cg": t["cap_gains_over_200"],
                    "p": {str(h): pf[h][0] for h in HORIZONS if pf and h in pf} if pf else None,
                    "ps": {str(h): pf[h][1] for h in HORIZONS if pf and h in pf} if pf else None,
                    "el": 1 if (a and a["eligible"] and t["asset_type"] in LISTED_TYPES) else 0, "pdf": f["pdf_url"]})
        _x = txs[-1]
        _mg = magi.get((t["doc_id"], t["idx"]))
        if _mg: _x["cs"], _x["cf"], _x["dg"] = _mg[0], round(_mg[1], 2), _mg[2]
        if f["kind"] == "scanned":
            _raw = json.loads(t["raw"] or "{}"); _x["sc"] = 1; _x["lg"] = 0 if _raw.get("legible") is False else 1
            if t["ticker_inferred"]: _x["inf"] = 1
        else:
            mr = meta_rows.get((t["doc_id"], t["idx"]))
            if mr is not None: _x["xc"] = int(all(mr[k] == t[k] for k in KEYS))
    # per-member / per-ticker aggregates
    for m in members.values():
        mt = [x for x in txs if x["m"] == m["id"]]
        m["n_tx"] = len(mt); m["n_buy"] = sum(x["ty"] == "P" for x in mt); m["n_sell"] = sum(x["ty"] in ("S", "SP") for x in mt)
        seen = set(); v30 = []
        for x in mt:
            k = (x["doc"], x["tk"])
            if x["ty"] == "P" and x["p"] and x["p"].get("30") is not None and k not in seen: seen.add(k); v30.append(x["p"]["30"])
        m["perf30"] = pstat(v30)
        m["last"] = m["filings"][0]["date"]
    tickers = {}
    for x in txs:
        if not x["tk"]: continue
        t = tickers.setdefault(x["tk"], {"tk": x["tk"], "name": x["a"], "n": 0, "ms": set(), "buy": 0, "sell": 0, "last": ""})
        t["n"] += 1; t["ms"].add(x["m"]); t["buy"] += x["ty"] == "P"; t["sell"] += x["ty"] in ("S", "SP"); t["last"] = max(t["last"], x["fd"])
    for k, t in tickers.items():
        t["ms"] = len(t["ms"]); a = assets.get(k)
        t["el"] = 1 if a and a["eligible"] else 0; t["why"] = None if (a and a["eligible"]) else (a["reason"] if a else "no_asset_record")
        pf = con.execute("SELECT status, n_rows, last_date FROM price_fetch WHERE ticker=?", (k,)).fetchone()
        t["px"] = pf["status"] if pf else ("n/a" if not t["el"] else "not_fetched")
    # prices
    prices = {}
    for k in tickers:
        rows = con.execute("SELECT date, close FROM prices WHERE ticker=? AND date>=? ORDER BY date", (k, PRICE_FROM)).fetchall()
        if rows: prices[k] = {"s": rows[0][0], "d": [r[0] for r in rows] if False else None, "c": [round(r[1], 2) for r in rows]}
    spy = con.execute("SELECT date, close FROM prices WHERE ticker='SPY' AND date>=? ORDER BY date", (PRICE_FROM,)).fetchall()
    cal = [r[0] for r in spy]           # shared trading calendar; ticker series aligned by date via a map below
    for k in prices:
        rows = dict(con.execute("SELECT date, close FROM prices WHERE ticker=? AND date>=?", (k, PRICE_FROM)).fetchall())
        prices[k] = {"c": [round(rows[d], 2) if d in rows else None for d in cal]}
    prices["SPY"] = {"c": [round(r[1], 2) for r in spy]}
    # track record
    def ev_vals(direction, h):
        return [r[0] for r in con.execute("SELECT excess FROM performance WHERE tx_type=? AND horizon=? AND status='ok'", (direction, h))]
    track = {"purchases": {}, "sales": {}, "hist30": None}
    for d, key in (("P", "purchases"), ("S", "sales")):
        for h in HORIZONS:
            s = pstat(ev_vals(d, h)); s["status_counts"] = dict(con.execute("SELECT status, count(*) FROM performance WHERE tx_type=? AND horizon=? GROUP BY 1", (d, h)).fetchall())
            track[key][str(h)] = s
    v = ev_vals("P", 30); bins = [-0.3 + 0.025 * i for i in range(25)]
    track["hist30"] = {"edges": [round(b, 3) for b in bins], "counts": [sum(1 for x in v if (b <= x < b + 0.025) or (b == bins[0] and x < b) or (b == bins[-2] and x >= bins[-1])) for b in bins[:-1]]}
    # picks
    live = _read(LOGDIR / "live.jsonl"); back = _read(LOGDIR / "backtest.jsonl")
    ai = load_ai()
    for e in live:
        E = e
        for p in e["picks"]:
            p["facts_en"] = facts_line(p, "en", E["pick_date"]); p["facts_zh"] = facts_line(p, "zh", E["pick_date"])
            if ai.get(f"{e['pick_date']}|{p['ticker']}", {}).get("status") == "ok": p["ai_summary"] = {"status": "ok", **{k: ai[f"{e['pick_date']}|{p['ticker']}"][k] for k in ("zh_tw", "en")}}
    scored = json.loads(SCORED.read_text()) if SCORED.exists() else None
    latest = (live[-1] if live else (back[-1] if back else None))
    if latest and latest["mode"] == "backtest":
        E = latest
        for p in latest["picks"]: p["facts_en"] = facts_line(p, "en", E["pick_date"]); p["facts_zh"] = facts_line(p, "zh", E["pick_date"])
    methods = {}
    for m, M in METHODS.items():
        bl = _read(LOGDIR / M["backtest_file"]); bp = LOGDIR / M["backtest_file"]
        bl_last = bl[-1] if bl else None
        if bl_last:
            E = bl_last
            for p in bl_last["picks"]: p["facts_en"] = facts_line(p, "en", E["pick_date"]); p["facts_zh"] = facts_line(p, "zh", E["pick_date"])
        methods[m] = {"version": M["version"], "live": [e for e in live if entry_method(e) == m], "backtest_latest": bl_last,
                      "n_backtest": len(bl), "bt_from": bl[0]["pick_date"] if bl else None, "bt_to": bl[-1]["pick_date"] if bl else None, "n_live_days": len({e["pick_date"] for e in live if entry_method(e) == m}), "n_live_entries": sum(len(e["picks"]) for e in live if entry_method(e) == m), "backtest_chain": verify(bp) if bp.exists() else None}
    def strip(sm):   # keep summary only
        return {b: {h: s for h, s in d.items()} for b, d in sm.items()}
    data = {
        "meta": {"generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "prices_as_of": cal[-1] if cal else None, "calendar_start": cal[0] if cal else None,
                 "n_filings": len(filings), "n_text": sum(f["kind"] == "text" for f in filings), "n_scanned": sum(f["kind"] == "scanned" for f in filings),
                 "n_tx": len(txs), "n_members": len(members), "n_tickers": len(tickers), "n_priced": sum(1 for t in tickers.values() if t["px"] == "ok"),
                 "first_filing": min(f["filing_date"] for f in filings), "last_filing": max(f["filing_date"] for f in filings),
                 "ptr_url_example": filings[0]["pdf_url"], "calendar": cal},
        "members": sorted(members.values(), key=lambda m: m["name"].split()[-1]), "tickers": sorted(tickers.values(), key=lambda t: -t["n"]),
        "tx": txs, "track": track, "consensus": consensus(con),
        "picks": {"live": live, "backtest_latest": back[-1] if back else None, "n_live": len(live), "n_backtest": len(back),
                  "live_chain": verify(LOGDIR / "live.jsonl") if (LOGDIR / "live.jsonl").exists() else None,
                  "backtest_chain": verify(LOGDIR / "backtest.jsonl") if (LOGDIR / "backtest.jsonl").exists() else None,
                  "latest_live_hash": live[-1]["hash"] if live else None, "methods": methods},
        "picks_scored": {m: {"n_events": d["n_events"], "summary": d["summary"], "chain_ok": d["chain_ok"]} for m, d in scored["modes"].items()} if scored else None,
    }
    (SITE / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    (SITE / "prices.json").write_text(json.dumps(prices, separators=(",", ":")))
    import os
    print({k: v for k, v in data["meta"].items() if k != "calendar"}); print("data.json", os.path.getsize(SITE / "data.json") // 1024, "KB; prices.json", os.path.getsize(SITE / "prices.json") // 1024, "KB")

if __name__ == "__main__":
    main()
