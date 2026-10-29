"""Step 2: rule-based parser for ELECTRONIC (text) PTR PDFs using `pdftotext -layout`.

Output rows -> transactions(source='rule'). Cap-gains checkbox is a vector drawing (not text), so it is read
with PyMuPDF (optional dependency; if unavailable cap_gains stays NULL).
"""
from __future__ import annotations
import re, subprocess, json, argparse, datetime as dt
from dataclasses import dataclass, asdict, field
from . import config
from .db import connect

DATE = r"\d{2}/\d{2}/\d{4}"
MAIN = re.compile(
    r"^(?P<lead>\s*)(?:(?P<rid>\d{9,})\s+)?(?:(?P<owner>SP|DC|JT)\s{2,})?(?P<asset>\S.*?)\s+(?P<type>S \(partial\)|S\s*\(partial\)|P|S|E)\s+"
    rf"(?P<tx>{DATE})\s+(?P<nd>{DATE})\s*(?P<amt>.*?)\s*$")
STATUS = re.compile(r"^\s*F\s+S\s*:\s*(?P<s>.*?)\s*$")
AMT_TAIL = re.compile(r"\s{2,}(\$[\d,.]+(?:\s*-)?|Over|Over \$[\d,]+|Spouse/DC Over)\s*$")
TICKER = re.compile(r"\(([A-Z][A-Z0-9.\-/$]{0,9})\)")
ATYPE = re.compile(r"\[([A-Za-z]{2,3})\]")
AMT_FULL = re.compile(r"^(?:Spouse/DC\s+)?(?:\$(?P<lo>[\d,]+)\s*-\s*\$(?P<hi>[\d,]+)|Over\s+\$(?P<over>[\d,]+)|\$(?P<exact>[\d,]+(?:\.\d+)?))$")
HEADER = re.compile(r"^\s*(ID\s+Owner\s+Asset|Type\s+Date\s+Gains|Gains >|\$200\?|Filing ID #|Clerk of the House|Type\s+Date\s+$)")

@dataclass
class Tx:
    idx: int
    owner: str = ""
    asset: str = ""
    ticker: str | None = None
    asset_type: str | None = None
    tx_type: str | None = None
    tx_date: str | None = None
    notif_date: str | None = None
    amount_low: int | None = None
    amount_high: int | None = None
    amount_text: str | None = None
    cap_gains_over_200: int | None = None
    filing_status: str | None = None
    raw: str = ""
    page: int = 0
    end_page: int = 0

def _iso(d):  # mm/dd/yyyy -> iso
    return dt.datetime.strptime(d, "%m/%d/%Y").date().isoformat()

def pdf_text(path) -> str:
    return subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, timeout=120).stdout.decode("utf-8", "replace")

def _parse_amount(txt: str):
    t = re.sub(r"\s+", " ", txt).strip().replace("$ ", "$")
    m = AMT_FULL.match(t)
    if not m:
        return None, None, t or None
    if m.group("over"):
        return int(m.group("over").replace(",", "")), None, t
    if m.group("exact"):
        v = int(float(m.group("exact").replace(",", "")))
        return v, v, t
    return int(m.group("lo").replace(",", "")), int(m.group("hi").replace(",", "")), t

def parse_text(text: str) -> tuple[list[Tx], int]:
    """returns (transactions, expected_rows) where expected_rows is an independent count of 'Filing Status' lines."""
    out: list[Tx] = []
    expected = 0
    cur: Tx | None = None
    amt_parts: list[str] = []
    state = None  # 'asset' until the Filing Status line is seen, then 'after'

    def close():
        nonlocal cur, amt_parts
        if cur is not None:
            cur.asset = re.sub(r"\s+", " ", cur.asset).strip()
            lo, hi, at = _parse_amount(" ".join(amt_parts))
            cur.amount_low, cur.amount_high, cur.amount_text = lo, hi, at
            tk = TICKER.findall(cur.asset); cur.ticker = tk[-1] if tk else None
            ty = ATYPE.findall(cur.asset); cur.asset_type = ty[-1] if ty else None
            out.append(cur)
        cur = None; amt_parts = []

    for pno, page in enumerate(text.split("\f"), 1):       # rows may continue across a page break
        for line in page.splitlines():
            if HEADER.match(line):
                continue
            st = STATUS.match(line)
            if st:
                expected += 1
                if cur is not None:
                    cur.filing_status = st.group("s"); state = "after"; cur.end_page = pno
                continue
            m = MAIN.match(line)
            if m and not line.lstrip().startswith("*"):
                close()
                try:
                    txd, nd = _iso(m.group("tx")), _iso(m.group("nd"))
                except ValueError:
                    txd = nd = None
                cur = Tx(idx=len(out), owner=m.group("owner") or "", asset=m.group("asset"),
                         tx_type=re.sub(r"\s+", " ", m.group("type")),
                         tx_date=txd, notif_date=nd, raw=line.strip(), page=pno)
                if m.group("amt"): amt_parts.append(m.group("amt"))
                state = "asset"; continue
            if cur is None:
                continue
            if not line.strip():
                if state == "after": close(); state = None
                continue
            if state == "asset":
                s = line.rstrip()
                tail = AMT_TAIL.search(s)
                if tail or re.match(r"^\s{20,}(\$[\d,]+|Over)\b", s):
                    t = tail.group(1) if tail else s.strip()
                    amt_parts.append(t.strip())
                    s = s[:tail.start()] if tail else ""
                if s.strip(): cur.asset += " " + s.strip()
            cur.raw += " | " + line.strip()
    close()
    return out, expected

# ---- cap gains checkbox (vector) -------------------------------------------------
def _checkboxes_per_page(path):
    """list (per page) of lists [checked_bool] sorted top->bottom, or None if PyMuPDF missing."""
    try:
        import pymupdf
    except Exception:
        try:
            import fitz as pymupdf
        except Exception:
            return None
    pages = []
    d = pymupdf.open(str(path))
    for p in d:
        w = p.rect.width; boxes = {}
        for x in p.get_drawings():
            r = x["rect"]
            if r.x0 > w * 0.85 and r.width < 30 and r.height < 30 and len(x["items"]) == 20 and x.get("fill"):
                f = round(x["fill"][0], 3)
                key = round((r.y0 + r.y1) / 2, 0)
                if f == 0.663: boxes.setdefault(key, False)
                elif f == 0.463: boxes[key] = True
        pages.append([boxes[k] for k in sorted(boxes)])
    return pages

def attach_capgains(path, txs: list[Tx]) -> bool:
    """Map checkboxes -> rows per page. A row split across a page break is drawn on both pages; its box on the
    continuation page is skipped and the box from its start page is used."""
    cb = _checkboxes_per_page(path)
    if cb is None: return False
    ok = True
    for pno in sorted({t.page for t in txs}):
        rows = [t for t in txs if t.page == pno]
        boxes = list(cb[pno - 1]) if pno - 1 < len(cb) else []
        n_cont = sum(1 for t in txs if t.page == pno - 1 and t.end_page == pno)   # rows continued INTO this page
        carry = [t for t in txs if t.page == pno and t.end_page > pno]             # rows continuing OUT of this page
        boxes = boxes[n_cont:] if n_cont and len(boxes) - n_cont == len(rows) else boxes
        if len(boxes) == len(rows):
            for t, b in zip(rows, boxes):
                t.cap_gains_over_200 = int(b)
        else:
            ok = False
    return ok

def parse_pdf(path) -> dict:
    text = pdf_text(path)
    txs, expected = parse_text(text)
    cap_ok = attach_capgains(path, txs) if txs else False
    complete = all(t.tx_type and t.tx_date and t.notif_date and t.amount_low is not None and t.asset for t in txs)
    count_ok = len(txs) == expected and expected > 0
    status = "ok" if (count_ok and complete and (cap_ok or _checkboxes_per_page(path) is None)) else ("partial" if txs else "fail")
    note = f"parsed={len(txs)} expected={expected} complete={complete} capgains_attached={cap_ok}"
    return {"txs": txs, "status": status, "note": note, "expected": expected}

def run_all():
    con = connect()
    rows = con.execute("SELECT doc_id, pdf_path FROM filings WHERE kind='text' AND pdf_path IS NOT NULL ORDER BY doc_id").fetchall()
    stats = {"ok": 0, "partial": 0, "fail": 0}; ntx = 0; bad = []
    con.execute("DELETE FROM transactions WHERE source='rule'")
    for r in rows:
        res = parse_pdf(r["pdf_path"]); txs = res["txs"]; stats[res["status"]] += 1; ntx += len(txs)
        if res["status"] != "ok": bad.append((r["doc_id"], res["note"]))
        for t in txs:
            con.execute("""INSERT INTO transactions(doc_id,source,idx,owner,asset,ticker,asset_type,tx_type,tx_date,notif_date,
                amount_low,amount_high,amount_text,cap_gains_over_200,raw) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["doc_id"], "rule", t.idx, t.owner, t.asset, t.ticker, t.asset_type, t.tx_type, t.tx_date, t.notif_date,
                 t.amount_low, t.amount_high, t.amount_text, t.cap_gains_over_200, t.raw))
        con.execute("UPDATE filings SET rule_status=?, rule_n_tx=?, rule_note=? WHERE doc_id=?",
                    (res["status"], len(txs), res["note"], r["doc_id"]))
    con.commit()
    n = len(rows)
    print(f"rule parser over {n} text PDFs: ok={stats['ok']} partial={stats['partial']} fail={stats['fail']} "
          f"-> success rate {stats['ok']/n:.1%} ; {ntx} transactions")
    for d, note in bad[:40]: print("  !", d, note)
    return stats, bad

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--doc"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.doc:
        res = parse_pdf(config.PDF_DIR / f"{a.doc}.pdf")
        print(res["note"]); 
        for t in res["txs"]: print(json.dumps(asdict(t), ensure_ascii=False) if a.json else t)
    else:
        run_all()

if __name__ == "__main__":
    main()
