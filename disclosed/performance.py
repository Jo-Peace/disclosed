"""Forward returns vs SPY, measured from the date the filing became public (House Clerk FilingDate).
Entry = adjusted close of the FIRST TRADING DAY AFTER the filing date (information could not be acted on earlier at that close).
Exit = N trading days later (N = 5, 30, 90; trading calendar = SPY's). Excess = stock return - SPY return over the same dates.
One row per (filing, ticker, direction): a filing listing the same ticker several times counts once, since entry is identical.
Rows that cannot be computed are kept with an explicit status instead of being dropped or guessed."""
from __future__ import annotations
import argparse, bisect, math, statistics
from .db import connect

HORIZONS = (5, 30, 90)
LISTED_TYPES = ("ST", "EF")

def load_series(con, ticker):
    rows = con.execute("SELECT date, adj_close FROM prices WHERE ticker=? ORDER BY date", (ticker,)).fetchall()
    return [r[0] for r in rows], [r[1] for r in rows]

def measure(public_date, tdates, tpx, sdates, spx, horizon):
    """-> dict(status, entry_date, entry_px, exit_date, ret, spy_ret, excess)"""
    if not tdates: return {"status": "no_prices"}
    i = bisect.bisect_right(sdates, public_date)           # first SPY trading day strictly after public date
    if i >= len(sdates): return {"status": "insufficient_data"}
    entry = sdates[i]
    j = bisect.bisect_left(tdates, entry)
    if j >= len(tdates) or tdates[j] != entry:             # ticker did not trade on the entry day (halt/not yet listed/data gap)
        return {"status": "no_prices"}
    if i + horizon >= len(sdates): return {"status": "insufficient_data", "entry_date": entry}
    exit_d = sdates[i + horizon]
    k = bisect.bisect_left(tdates, exit_d)
    if k >= len(tdates) or tdates[k] != exit_d: return {"status": "no_prices", "entry_date": entry}
    r = tpx[k] / tpx[j] - 1; s = spx[i + horizon] / spx[i] - 1
    return {"status": "ok", "entry_date": entry, "entry_px": tdates and tpx[j], "exit_date": exit_d, "ret": r, "spy_ret": s, "excess": r - s}

def compute(con=None):
    con = con or connect()
    sd, sp = load_series(con, "SPY")
    if not sd: raise SystemExit("no SPY prices; run: python -m disclosed.prices fetch")
    ev = con.execute(f"""SELECT t.doc_id, t.ticker, CASE WHEN t.tx_type='P' THEN 'P' ELSE 'S' END dir, f.filing_date
        FROM tx t JOIN filings f USING(doc_id) JOIN assets a ON a.ticker=t.ticker AND a.eligible=1
        WHERE (t.tx_type='P' OR t.tx_type LIKE 'S%') AND t.asset_type IN ({','.join('?'*len(LISTED_TYPES))})
        GROUP BY 1,2,3""", LISTED_TYPES).fetchall()
    cache = {}
    con.execute("DELETE FROM performance")
    for e in ev:
        if e["ticker"] not in cache: cache[e["ticker"]] = load_series(con, e["ticker"])
        td, tp = cache[e["ticker"]]
        for h in HORIZONS:
            m = measure(e["filing_date"], td, tp, sd, sp, h)
            con.execute("INSERT INTO performance VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (e["doc_id"], e["ticker"], e["dir"], e["filing_date"], m.get("entry_date"),
                        m.get("entry_px"), h, m.get("exit_date"), m.get("ret"), m.get("spy_ret"), m.get("excess"), m["status"]))
    con.commit()
    return len(ev)

def summarize(vals):
    """vals: list of excess returns. Returns stats incl. sample size; 'insufficient' if n < 10 (we refuse to headline tiny samples)."""
    n = len(vals)
    if n == 0: return {"n": 0, "insufficient": True}
    mean = statistics.fmean(vals); sd = statistics.stdev(vals) if n > 1 else None
    return {"n": n, "win_rate": sum(v > 0 for v in vals) / n, "mean_excess": mean, "median_excess": statistics.median(vals),
            "se": (sd / math.sqrt(n)) if sd is not None else None, "insufficient": n < 10}

def track_record(con, direction="P"):
    out = {}
    for h in HORIZONS:
        rows = con.execute("SELECT excess FROM performance WHERE tx_type=? AND horizon=? AND status='ok'", (direction, h)).fetchall()
        st = summarize([r[0] for r in rows])
        cnt = dict(con.execute("SELECT status, count(*) FROM performance WHERE tx_type=? AND horizon=? GROUP BY 1", (direction, h)).fetchall())
        st["status_counts"] = cnt; out[h] = st
    return out

def main():
    ap = argparse.ArgumentParser(); a = ap.parse_args(); con = connect()
    n = compute(con); print(f"events (filing x ticker x direction): {n}")
    for d, lab in (("P", "purchases"), ("S", "sales")):
        print(lab)
        for h, s in track_record(con, d).items():
            if s["n"]:
                print(f"  {h:>3}d n={s['n']:4d} win={s['win_rate']:.1%} mean_excess={s['mean_excess']:+.2%} median={s['median_excess']:+.2%} se={s['se']:.2%} {s['status_counts']}")
            else: print(f"  {h:>3}d n=0 {s['status_counts']}")

if __name__ == "__main__":
    main()
