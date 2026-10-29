"""Prices: classify assets (eligible listed stocks vs excluded), fetch daily history (Yahoo chart endpoint, cached, polite),
optional Tiingo fallback only if TIINGO_API_KEY is set. Missing tickers are recorded (never invented)."""
from __future__ import annotations
import argparse, datetime as dt, json, os, re, sys, time
import requests
from . import config
from .db import connect

CACHE = config.DATA / "price_cache"
UA = "Mozilla/5.0 (compatible; DisclosedHackathonBot/0.1; non-commercial research)"
FROM = "2025-10-01"            # a bit before the earliest transaction dates; returns only need data after filing dates
MIN_INTERVAL = float(os.environ.get("DISCLOSED_PRICE_INTERVAL", "0.6"))

# PTR asset-type codes (https://fd.house.gov/reference/asset-type-codes.aspx) we do NOT price, with reasons
EXCLUDE_TYPE = {
    "GS": "government_security_or_bond", "CS": "corporate_bond", "OP": "option_or_derivative", "OT": "other_non_listed",
    "OI": "private_ownership_interest", "HN": "hedge_fund_or_private_fund", "PS": "private_stock", "VA": "variable_annuity",
    "OL": "other_locality_investment", "AB": "asset_backed_security", "RS": "restricted_stock_or_unit", "CT": "cryptocurrency",
    "MF": "mutual_fund", "PE": "private_equity", "FN": "fund_non_listed", "IR": "ira_or_retirement_account", "RE": "real_estate",
    "BA": "bank_account", "DO": "debt_obligation", "FU": "futures", "WU": "warrant_or_unit", "5P": "529_plan",
}

def normalize(ticker: str) -> tuple[str | None, str | None]:
    """returns (yahoo_symbol, reason_if_unsupported)"""
    t = ticker.strip().upper()
    if "$" in t:
        return None, "preferred_share_symbol_unsupported"
    if not re.fullmatch(r"[A-Z]{1,5}([.\-/][A-Z]{1,2})?", t):
        return None, "unrecognised_symbol_format"
    return re.sub(r"[./]", "-", t), None

def classify_assets(con):
    rows = con.execute("""SELECT ticker, group_concat(DISTINCT asset_type) types, count(*) n, min(CASE WHEN asset_type='ST' THEN asset END) name_st, min(asset) name
        FROM tx WHERE ticker IS NOT NULL GROUP BY ticker""").fetchall()
    notick = con.execute("SELECT asset_type, count(*) FROM tx WHERE ticker IS NULL GROUP BY 1").fetchall()
    con.execute("DELETE FROM assets")
    for r in rows:
        types = set((r["types"] or "").split(","))
        # a ticker that appears ONLY as option/derivative/etc. is not priced; if it also appears as ST we price the stock
        if "ST" in types or "EF" in types or None in types or "" in types:
            norm, why = normalize(r["ticker"]); elig, reason = (1, "ok") if norm else (0, why)
        else:
            t = sorted(types)[0]; norm = None; elig = 0; reason = EXCLUDE_TYPE.get(t, f"asset_type_{t}")
        con.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?)", (r["ticker"], norm, elig, reason, r["n"], r["types"], r["name"]))
    con.commit()
    n_el = con.execute("SELECT count(*) FROM assets WHERE eligible=1").fetchone()[0]
    print(f"assets: {len(rows)} distinct tickers, {n_el} eligible; excluded by reason:",
          dict(con.execute("SELECT reason, count(*) FROM assets WHERE eligible=0 GROUP BY 1").fetchall()))
    print("rows without any ticker (bonds/private/etc.), by asset_type:", dict(notick))

_last = 0.0
def _throttle():
    global _last
    w = MIN_INTERVAL - (time.time() - _last)
    if w > 0: time.sleep(w)
    _last = time.time()

def yahoo_fetch(sym: str, refresh=False):
    """returns (status, rows[(date, close, adj, vol)], error). Cached raw JSON under data/price_cache/."""
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{sym}.json"
    if f.exists() and not refresh and time.time() - f.stat().st_mtime < 12 * 3600:
        j = json.loads(f.read_text())
    else:
        p1 = int(dt.datetime.fromisoformat(FROM).replace(tzinfo=dt.timezone.utc).timestamp())
        p2 = int(time.time()) + 86400
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
        j = None
        for a in range(4):
            _throttle()
            try:
                r = requests.get(url, params={"period1": p1, "period2": p2, "interval": "1d", "events": "div,splits"}, headers={"User-Agent": UA}, timeout=30)
            except requests.RequestException as e:
                time.sleep(2 ** a); continue
            if r.status_code == 429: time.sleep(10 * (a + 1)); continue
            if r.status_code == 404: return "not_found", [], "HTTP 404"
            if r.status_code != 200: time.sleep(2 ** a); continue
            j = r.json(); break
        if j is None: return "error", [], "request failed after retries"
        f.write_text(json.dumps(j))
    res = (j.get("chart") or {}).get("result")
    if not res:
        err = (j.get("chart") or {}).get("error")
        return "not_found", [], json.dumps(err)[:200]
    r0 = res[0]; ts = r0.get("timestamp") or []
    q = r0["indicators"]["quote"][0]; adj = (r0["indicators"].get("adjclose") or [{}])[0].get("adjclose") or [None] * len(ts)
    tz = r0["meta"].get("exchangeTimezoneName", "America/New_York")
    from zoneinfo import ZoneInfo
    rows = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None: continue
        d = dt.datetime.fromtimestamp(t, ZoneInfo(tz)).date().isoformat()
        rows.append((d, round(c, 4), round(adj[i], 4) if adj[i] is not None else round(c, 4), q["volume"][i]))
    return ("ok" if rows else "no_data"), rows, None

def tiingo_fetch(sym: str):
    key = os.environ.get("TIINGO_API_KEY")
    if not key: return "error", [], "no TIINGO_API_KEY"
    _throttle()
    r = requests.get(f"https://api.tiingo.com/tiingo/daily/{sym}/prices", params={"startDate": FROM, "token": key}, timeout=30)
    if r.status_code == 404: return "not_found", [], "HTTP 404"
    if r.status_code != 200: return "error", [], f"HTTP {r.status_code}"
    rows = [(x["date"][:10], x["close"], x["adjClose"], x["volume"]) for x in r.json()]
    return ("ok" if rows else "no_data"), rows, None

def fetch_all(limit=None, refresh=False):
    con = connect()
    syms = [("SPY", "SPY")] + [(r["ticker"], r["norm_ticker"]) for r in con.execute("SELECT ticker, norm_ticker FROM assets WHERE eligible=1 ORDER BY n_tx DESC")]
    done = 0
    for tk, sym in syms:
        prev = con.execute("SELECT status, fetched_at FROM price_fetch WHERE ticker=?", (tk,)).fetchone()
        if prev and prev["status"] in ("ok", "not_found") and not refresh:
            continue
        if limit is not None and done >= limit: break
        status, rows, err = yahoo_fetch(sym, refresh); src = "yahoo"
        if status != "ok" and os.environ.get("TIINGO_API_KEY"):
            s2, r2, e2 = tiingo_fetch(sym)
            if s2 == "ok": status, rows, err, src = s2, r2, None, "tiingo"
        con.execute("DELETE FROM prices WHERE ticker=?", (tk,))
        con.executemany("INSERT INTO prices(ticker,date,close,adj_close,volume,source) VALUES(?,?,?,?,?,?)", [(tk, d, c, a, v, src) for d, c, a, v in rows])
        con.execute("INSERT OR REPLACE INTO price_fetch VALUES(?,?,?,?,?,?,?,?)", (tk, src, status, dt.datetime.now().isoformat(timespec="seconds"),
                    len(rows), rows[0][0] if rows else None, rows[-1][0] if rows else None, err))
        con.commit(); done += 1
        if done % 50 == 0: print(f"  fetched {done}/{len(syms)}", flush=True)
    st = dict(con.execute("SELECT status, count(*) FROM price_fetch GROUP BY 1").fetchall())
    print("price_fetch status:", st, "| last price date:", con.execute("SELECT max(date) FROM prices WHERE ticker='SPY'").fetchone()[0])

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("step", choices=["classify", "fetch", "all"]); ap.add_argument("--limit", type=int); ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args(argv); con = connect()
    if a.step in ("classify", "all"): classify_assets(con)
    if a.step in ("fetch", "all"): fetch_all(a.limit, a.refresh)

if __name__ == "__main__":
    main()
