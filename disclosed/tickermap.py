"""Name -> ticker inference for SCANNED (paper) PTRs, which print no ticker symbol. NO LLM involved.

Looks the printed company name up through Yahoo's public search endpoint (cached in table ticker_infer) and accepts a symbol ONLY
when a US-listed equity/ETF has a (normalised) name that equals/closely matches the printed name and the match is unambiguous.
Accepted rows get transactions.ticker_inferred=1 + ticker_note, and the site shows them with an 'inferred' flag.
Anything uncertain stays ticker-less (and is simply not priced). Prices of companies that no longer trade are not available either."""
from __future__ import annotations
import re, time, json, argparse, datetime as dt
import requests
from .db import connect

UA = "Mozilla/5.0 (compatible; Disclosed/0.1; non-commercial research)"
US_EXCH = {"NMS", "NYQ", "NGM", "NCM", "ASE", "PCX", "BTS", "NAS", "NYS", "NYSE", "ARCA"}
STOP = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "the", "common", "stock", "cmn", "com",
        "class", "a", "b", "c", "ordinary", "shares", "share", "holdings", "holding", "group", "llc", "lp", "sa", "nv", "ag", "new", "de", "adr", "ads", "usd", "of", "and", "&", "etf", "fund", "trust"}
DDL = """CREATE TABLE IF NOT EXISTS ticker_infer (name TEXT PRIMARY KEY, ticker TEXT, matched_name TEXT, exchange TEXT, status TEXT, tried_at TEXT, candidates TEXT, qtype TEXT)"""
SKIP = re.compile(r"\b(treasury|treas|bills?|bonds?|bd|rev|revenue|mtg|due|fixed|cnty|county|city of|state of|sch|school|authority|auth|mun|fund class|cd|put|call|option)\b", re.I)


def core(name: str) -> list[str]:
    n = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", (name or "").lower())
    n = re.sub(r"[^a-z0-9& ]", " ", n)
    toks = [t for t in n.split() if t not in STOP]
    return toks


GENERIC = {"first", "american", "united", "general", "national", "global", "international", "new", "great", "pacific", "atlantic", "southern", "northern", "western", "eastern",
           "central", "capital", "financial", "energy", "bank", "health", "us", "usa", "united states", "ishares", "spdr", "vanguard", "invesco", "select", "sector", "growth", "value"}
BENIGN_TAIL = {"international", "technologies", "technology", "platforms", "systems", "communications", "industries", "enterprises", "pharmaceuticals", "therapeutics",
               "worldwide", "bancorp", "bancorporation", "financial", "energy", "resources", "brands", "laboratories", "labs", "software", "networks", "semiconductor", "motors",
               "stores", "airlines", "entertainment", "electric", "foods", "systems"}


def similar(a: list[str], b: list[str]) -> bool:
    """strict: equal token lists; or one is a token-prefix of the other where the shorter has >=2 tokens (or 1 distinctive token whose remainder is a benign
    corporate tail word); or Jaccard >= 0.75 with >=3 tokens in the union."""
    if not a or not b: return False
    if a == b: return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if long_[:len(short)] == short:
        if len(short) >= 2: return True
        return short[0] not in GENERIC and len(short[0]) >= 4 and all(t in BENIGN_TAIL for t in long_[1:])
    sa, sb = set(a), set(b)
    return len(sa | sb) >= 3 and len(sa & sb) / len(sa | sb) >= 0.75


def evaluate(name: str, cands: list[dict]) -> dict:
    want = core(name)
    ok = [c for c in cands if c["type"] in ("EQUITY", "ETF") and c["exch"] in US_EXCH and c["symbol"] and "." not in c["symbol"].replace("-", "")
          and similar(want, core(c["name"]))]
    syms = {c["symbol"] for c in ok}
    if len(syms) == 1:
        c = ok[0]; return {"ticker": c["symbol"], "matched_name": c["name"], "exchange": c["exch"], "status": "ok", "qtype": c["type"]}
    return {"ticker": None, "matched_name": None, "exchange": None, "status": "ambiguous" if syms else "no_match", "qtype": None}


def lookup(name: str) -> dict:
    q = " ".join(core(name)) or name
    for att in range(4):
        try:
            r = requests.get("https://query2.finance.yahoo.com/v1/finance/search", params={"q": q, "quotesCount": 8, "newsCount": 0},
                             headers={"User-Agent": UA}, timeout=20)
        except requests.RequestException:
            time.sleep(2 ** att); continue
        if r.status_code == 429: time.sleep(8 * (att + 1)); continue
        if r.status_code != 200: time.sleep(2 ** att); continue
        quotes = r.json().get("quotes", [])
        cands = [{"symbol": x.get("symbol"), "name": x.get("longname") or x.get("shortname"), "exch": x.get("exchange"), "type": x.get("quoteType")} for x in quotes]
        res = evaluate(name, cands); res["candidates"] = cands
        return res
    return {"ticker": None, "matched_name": None, "exchange": None, "status": "error", "candidates": [], "qtype": None}


def reevaluate(con):
    """re-apply the (possibly tightened) matching rule to the stored Yahoo candidates, no network"""
    con.execute(DDL); ch = 0
    for name, cj, st in con.execute("SELECT name, candidates, status FROM ticker_infer WHERE status IN ('ok','ambiguous','no_match')").fetchall():
        res = evaluate(name, json.loads(cj or "[]"))
        if res["status"] != st: ch += 1
        con.execute("UPDATE ticker_infer SET ticker=?, matched_name=?, exchange=?, status=?, qtype=? WHERE name=?", (res["ticker"], res["matched_name"], res["exchange"], res["status"], res["qtype"], name))
    con.execute("UPDATE transactions SET ticker=NULL, asset_type=NULL, ticker_inferred=0, ticker_note=NULL WHERE ticker_inferred=1")
    con.commit(); print("re-evaluated; status changes:", ch)


def run(con=None, workers=4):
    import concurrent.futures as cf
    con = con or connect(); con.execute(DDL); reevaluate(con)
    # tickers the MODEL guessed for non-option rows are NOT trusted: re-derive deterministically below (options print '(TKR)' on the form)
    con.execute("""UPDATE transactions SET ticker=NULL WHERE source='meta' AND doc_id IN (SELECT doc_id FROM filings WHERE kind='scanned')
                   AND ticker IS NOT NULL AND ticker_inferred=0 AND asset NOT LIKE '%('||ticker||')%'""")
    con.execute("""UPDATE transactions SET asset_type='OP' WHERE source='meta' AND asset_type IS NULL AND ticker IS NOT NULL
                   AND doc_id IN (SELECT doc_id FROM filings WHERE kind='scanned') AND (asset LIKE 'PUT %' OR asset LIKE 'CALL %')""")
    rows = con.execute("""SELECT DISTINCT t.asset FROM transactions t JOIN filings f USING(doc_id)
        WHERE f.kind='scanned' AND t.source='meta' AND (t.ticker IS NULL OR t.ticker='') AND t.asset IS NOT NULL AND t.asset!=''""").fetchall()
    names = [r[0] for r in rows if not SKIP.search(r[0])]
    done = {r[0] for r in con.execute("SELECT name FROM ticker_infer WHERE status!='error'")}
    todo = [n for n in names if n not in done]
    print(f"{len(rows)} distinct printed names without ticker; {len(rows) - len(names)} skipped as bonds/munis/options; {len(todo)} to look up", flush=True)
    def work(n):
        time.sleep(0.25); return n, lookup(n)
    with cf.ThreadPoolExecutor(workers) as ex:
        for k, (n, res) in enumerate(ex.map(work, todo)):
            con.execute("INSERT OR REPLACE INTO ticker_infer VALUES(?,?,?,?,?,?,?,?)", (n, res["ticker"], res["matched_name"], res["exchange"], res["status"],
                        dt.datetime.now().isoformat(timespec="seconds"), json.dumps(res["candidates"][:5]), res["qtype"]))
            if k % 50 == 0: con.commit(); print(k, "/", len(todo), flush=True)
    con.commit()
    con.execute("""UPDATE transactions SET ticker=(SELECT ticker FROM ticker_infer i WHERE i.name=transactions.asset AND i.status='ok'),
                       asset_type=(SELECT CASE i.qtype WHEN 'ETF' THEN 'EF' ELSE 'ST' END FROM ticker_infer i WHERE i.name=transactions.asset AND i.status='ok'),
                       ticker_inferred=1, ticker_note='inferred from printed name via Yahoo search (no ticker on paper form): '||(SELECT matched_name FROM ticker_infer i WHERE i.name=transactions.asset)
        WHERE source='meta' AND (ticker IS NULL OR ticker='') AND doc_id IN (SELECT doc_id FROM filings WHERE kind='scanned')
          AND asset IN (SELECT name FROM ticker_infer WHERE status='ok')""")
    con.commit()
    print(dict(con.execute("SELECT status, count(*) FROM ticker_infer GROUP BY 1").fetchall()))
    print("rows with inferred ticker:", con.execute("SELECT count(*) FROM transactions WHERE ticker_inferred=1").fetchone()[0])

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.parse_args(); run()
