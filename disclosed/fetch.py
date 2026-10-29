"""Step 1: download the House Clerk index, keep FilingType=P, download PTR PDFs politely, classify text vs scanned."""
from __future__ import annotations
import csv, datetime as dt, io, subprocess, time, zipfile, argparse, sys
import requests
from . import config
from .db import connect

_last = 0.0
def _throttle():
    global _last
    wait = config.MIN_INTERVAL_SEC - (time.time() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.time()

def _get(sess, url, retries=4):
    for a in range(retries):
        _throttle()
        try:
            r = sess.get(url, timeout=60)
        except requests.RequestException as e:
            time.sleep(2 ** a); continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(5 * (a + 1)); continue
        return r
    return None

def iso(d: str) -> str:
    try:
        return dt.datetime.strptime(d.strip(), "%m/%d/%Y").date().isoformat()
    except Exception:
        return d

def fetch_index(year=config.YEAR):
    config.DATA.mkdir(parents=True, exist_ok=True)
    sess = requests.Session(); sess.headers["User-Agent"] = config.USER_AGENT
    r = _get(sess, config.INDEX_URL.format(year=year))
    if r is None or r.status_code != 200:
        raise SystemExit(f"index download failed: {r and r.status_code}")
    (config.DATA / f"{year}FD.zip").write_bytes(r.content)
    z = zipfile.ZipFile(io.BytesIO(r.content))
    txt = z.read(f"{year}FD.txt").decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(txt), delimiter="\t"))
    con = connect(); n = 0
    for row in rows:
        if row["FilingType"].strip() != "P":
            continue
        doc = row["DocID"].strip()
        con.execute("""INSERT INTO filings(doc_id,year,prefix,last,first,suffix,filing_type,state_dst,filing_date,pdf_url)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(doc_id) DO UPDATE SET prefix=excluded.prefix,last=excluded.last,first=excluded.first,
              suffix=excluded.suffix,state_dst=excluded.state_dst,filing_date=excluded.filing_date""",
            (doc, int(row["Year"]), row["Prefix"], row["Last"], row["First"], row["Suffix"], "P",
             row["StateDst"], iso(row["FilingDate"]), config.PTR_URL.format(year=year, doc_id=doc)))
        n += 1
    con.commit()
    print(f"index: {len(rows)} rows, {n} PTR (FilingType=P) upserted")
    return n

def classify_pdf(path) -> tuple[str, int]:
    """text if pdftotext yields real text; scanned otherwise."""
    try:
        out = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, timeout=60).stdout.decode("utf-8", "replace")
    except Exception:
        return "unknown", 0
    chars = len("".join(out.split()))
    return ("text" if chars >= 150 and "Filing ID" in out else "scanned"), chars

def download_all(limit=None, year=config.YEAR):
    config.PDF_DIR.mkdir(parents=True, exist_ok=True)
    con = connect()
    sess = requests.Session(); sess.headers["User-Agent"] = config.USER_AGENT
    rows = con.execute("SELECT doc_id, pdf_url FROM filings WHERE filing_type='P' AND year=? ORDER BY doc_id", (year,)).fetchall()
    done = skipped = failed = 0
    for row in rows:
        doc = row["doc_id"]; path = config.PDF_DIR / f"{doc}.pdf"
        if path.exists() and path.stat().st_size > 0 and path.read_bytes()[:5] == b"%PDF-":
            skipped += 1
        else:
            if limit is not None and done >= limit: break
            r = _get(sess, row["pdf_url"])
            if r is None or r.status_code != 200 or r.content[:5] != b"%PDF-":
                failed += 1
                con.execute("UPDATE filings SET http_status=? WHERE doc_id=?", (r.status_code if r is not None else 0, doc)); con.commit()
                print(f"  ! {doc} failed ({r.status_code if r is not None else 'net'})", file=sys.stderr); continue
            tmp = path.with_suffix(".part"); tmp.write_bytes(r.content); tmp.rename(path)   # atomic
            done += 1
            con.execute("UPDATE filings SET http_status=200, downloaded_at=? WHERE doc_id=?", (dt.datetime.now().isoformat(timespec="seconds"), doc))
            if done % 25 == 0: print(f"  downloaded {done} ...", flush=True)
        con.execute("UPDATE filings SET pdf_path=?, pdf_bytes=? WHERE doc_id=?", (str(path), path.stat().st_size, doc))
        con.commit()
    print(f"download: new={done} already_present={skipped} failed={failed}")

def classify_all():
    con = connect(); c = {"text": 0, "scanned": 0, "unknown": 0}
    for row in con.execute("SELECT doc_id, pdf_path FROM filings WHERE pdf_path IS NOT NULL").fetchall():
        kind, chars = classify_pdf(row["pdf_path"]); c[kind] += 1
        con.execute("UPDATE filings SET kind=?, text_chars=? WHERE doc_id=?", (kind, chars, row["doc_id"]))
    con.commit(); print("classify:", c)

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("step", choices=["index", "download", "classify", "all"])
    ap.add_argument("--limit", type=int, help="max NEW pdfs to download this run")
    ap.add_argument("--year", type=int, default=config.YEAR)
    a = ap.parse_args(argv)
    if a.step in ("index", "all"): fetch_index(a.year)
    if a.step in ("download", "all"): download_all(a.limit, a.year)
    if a.step in ("classify", "all"): classify_all()

if __name__ == "__main__":
    main()
