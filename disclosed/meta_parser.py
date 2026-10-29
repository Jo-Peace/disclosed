"""Step 3: parse PTR PDFs with the Meta model (PDF as input_file + json_schema structured output)
and cross-check against the rule-based parser. Requires MODEL_API_KEY. Never substitutes another AI.

Long PDFs are split into page chunks (default 6 pages for scanned, 10 for text) so one answer never exceeds the output limit;
all responses are cached on disk and token usage/cost is logged to data/llm_ledger.jsonl (see providers/meta.py)."""
from __future__ import annotations
import argparse, json, sys, concurrent.futures as cf
from pathlib import Path
from . import config
from .db import connect
from .schema import PTR_SCHEMA
from .providers import provider_for_role, FileInput, MissingCredentials, ProviderError
from .providers.meta import BudgetExceeded, spent_usd

SYSTEM = """You extract data from US House of Representatives Periodic Transaction Reports (STOCK Act PTR PDFs). Some PDFs are electronic, others are scans of the paper form (checkbox grid, sometimes handwritten).
Output ONLY the JSON that matches the schema. Rules:
- One output item per row of the Transactions table, in page order. Do not merge or skip rows (including rows that continue across a page break). Identical rows printed twice must both be kept.
- Paper forms print a pre-filled EXAMPLE row ("Example: Mega Corp. Common Stock", dates 8/14/12 or 02/05/20 / 03/07/20, one X). It is NOT a transaction: omit it. Also omit blank rows, header rows and page footers.
- Copy asset names exactly as printed; do not correct spelling or invent tickers. ticker is only set when a ticker symbol is printed (usually in parentheses); paper forms normally have none -> null. asset_type only when a [XX] code is printed, else null.
- tx_type is exactly one of: P (purchase), S (sale), S (partial) (partial sale), E (exchange). On paper forms use the checked box (Purchase / Sale / Partial Sale / Exchange).
- Dates are mm/dd/yyyy or mm/dd/yy in the PDF; output YYYY-MM-DD (two-digit years are 20yy).
- amount_text is the printed range; amount_low/amount_high are integers in USD (amount_high = null for 'Over $X'). On paper forms the amount is the checked column: A $1,001-$15,000; B $15,001-$50,000; C $50,001-$100,000; D $100,001-$250,000; E $250,001-$500,000; F $500,001-$1,000,000; G $1,000,001-$5,000,000; H $5,000,001-$25,000,000; I $25,000,001-$50,000,000; J Over $50,000,000; K 'Over $1,000,000' (spouse/dependent-child holdings). Put the column letter in amount_column and write the range in amount_text. If no box can be told, amount_text = "" and legible=false.
- Owner column: SP = spouse, DC = dependent child, JT = joint; empty string if blank.
- cap_gains_over_200 reflects the 'Cap. Gains > $200?' checkbox (checked = true). If the form has no such box or you cannot tell, null.
- subholding: if the table shows a heading row naming an account/trust that the following rows belong to, copy it for each row; else null.
- page: the page number inside the attached file where the row is printed.
- Mark legible=false for any row you are not sure you read correctly (handwriting, blur, faint marks) and explain in notes. Do not guess illegible values.
- Do not add commentary. Do not give investment advice."""

USER = "Extract every transaction from the attached Periodic Transaction Report (Filing ID {doc_id}){part}."
CHUNK = {"scanned": 6, "text": 10}


def page_count(path: Path) -> int:
    import fitz
    with fitz.open(path) as d:
        return d.page_count


def make_chunk(path: Path, start: int, end: int, doc_id: str) -> Path:
    import fitz
    out = config.DATA / "chunks" / f"{doc_id}_p{start+1}-{end}.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not out.exists():
        with fitz.open(path) as src, fitz.open() as dst:
            dst.insert_pdf(src, from_page=start, to_page=end - 1)
            dst.save(out)
    return out


def parse_with_meta(doc_id: str, pdf_path: Path, kind: str = "text", provider=None):
    """returns (rows, meta) where rows carry absolute page numbers; chunks pdfs > CHUNK pages."""
    provider = provider or provider_for_role("pdf_parser")
    if not provider.supports_pdf:
        raise ProviderError(f"provider {provider.name} does not support PDF input; choose one with supports_pdf=True for role pdf_parser")
    n = page_count(pdf_path); step = CHUNK.get(kind, 10)
    spans = [(0, n)] if n <= step + 2 else [(s, min(s + step, n)) for s in range(0, n, step)]
    rows, usage_total, notes = [], {"input_tokens": 0, "output_tokens": 0}, []
    model = None
    for s, e in spans:
        f = pdf_path if len(spans) == 1 else make_chunk(pdf_path, s, e, doc_id)
        part = "" if len(spans) == 1 else f" - this file contains pages {s+1}-{e} of {n}; the 'page' field is relative to this file"
        res = provider.generate(system=SYSTEM, user=USER.format(doc_id=doc_id, part=part), schema=PTR_SCHEMA, schema_name="ptr_extraction",
                                files=[FileInput(f, detail="high" if kind != "text" else "low")], reasoning_effort="medium",
                                max_output_tokens=60000, label=f"parse:{doc_id}:p{s+1}-{e}")
        model = res.model
        for k in usage_total: usage_total[k] += (res.usage or {}).get(k, 0)
        for t in (res.data or {}).get("transactions", []):
            t["page"] = (t.get("page") or 1) + s if len(spans) > 1 else t.get("page")
            rows.append(t)
    return rows, {"model": model, "usage": usage_total, "chunks": len(spans), "pages": n}


def store(con, doc_id: str, rows, meta):
    con.execute("DELETE FROM transactions WHERE doc_id=? AND source='meta'", (doc_id,))
    for i, t in enumerate(rows):
        con.execute("""INSERT INTO transactions(doc_id,source,idx,owner,asset,ticker,asset_type,tx_type,tx_date,notif_date,
            amount_low,amount_high,amount_text,cap_gains_over_200,raw) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (doc_id, "meta", i, t.get("owner", ""), t.get("asset"), t.get("ticker"), t.get("asset_type"), t.get("tx_type"),
             t.get("tx_date"), t.get("notif_date"), t.get("amount_low"), t.get("amount_high"), t.get("amount_text"),
             None if t.get("cap_gains_over_200") is None else int(t["cap_gains_over_200"]),
             json.dumps({"legible": t.get("legible"), "notes": t.get("notes"), "page": t.get("page"), "subholding": t.get("subholding"),
                         "amount_column": t.get("amount_column"), "model": meta["model"]}, ensure_ascii=False)))
    con.execute("UPDATE filings SET meta_status='ok', meta_n_tx=? WHERE doc_id=?", (len(rows), doc_id))
    con.commit()


def run_docs(rows, workers=6, provider=None):
    """parse many filings concurrently (model calls only); DB writes happen in the calling thread."""
    provider = provider or provider_for_role("pdf_parser")
    con = connect(); done = fail = 0
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(parse_with_meta, r["doc_id"], Path(r["pdf_path"]), r["kind"] or "text", provider): r for r in rows}
        for f in cf.as_completed(futs):
            r = futs[f]
            try:
                txs, meta = f.result()
            except BudgetExceeded as e:
                print("STOP:", e, file=sys.stderr); ex.shutdown(wait=False, cancel_futures=True); sys.exit(4)
            except MissingCredentials as e:
                print("ERROR:", e, file=sys.stderr); sys.exit(3)
            except (ProviderError, Exception) as e:      # any per-document failure is recorded, never aborts the batch
                con.execute("UPDATE filings SET meta_status=? WHERE doc_id=?", ("error: " + f"{type(e).__name__}: {e}"[:200], r["doc_id"])); con.commit()
                print(f"{r['doc_id']}: ERROR {type(e).__name__}: {e}", file=sys.stderr, flush=True); fail += 1; continue
            store(con, r["doc_id"], txs, meta); done += 1
            print(f"{r['doc_id']} [{r['kind']}]: {len(txs)} tx, {meta['pages']}p/{meta['chunks']} chunk(s), tokens in/out {meta['usage']['input_tokens']}/{meta['usage']['output_tokens']}  (spent so far ${spent_usd():.2f})", flush=True)
    print(f"done={done} failed={fail} total spend ${spent_usd():.2f}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--doc", action="append", help="DocID (repeatable)")
    ap.add_argument("--kind", choices=["text", "scanned"], help="process only this kind (when no --doc)")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--redo", action="store_true", help="re-run even if meta_status is set (responses are cached on disk anyway)")
    a = ap.parse_args(argv)
    provider = provider_for_role("pdf_parser")
    if not provider.available():
        print("ERROR: Meta API key missing. Export MODEL_API_KEY (see README: 'Getting a Meta API key'). Nothing was run; no fallback model is used.", file=sys.stderr)
        sys.exit(3)
    con = connect()
    if a.doc:
        rows = [con.execute("SELECT doc_id,pdf_path,kind FROM filings WHERE doc_id=?", (d,)).fetchone() for d in a.doc]
    else:
        q = "SELECT doc_id,pdf_path,kind FROM filings WHERE pdf_path IS NOT NULL" + ("" if a.redo else " AND (meta_status IS NULL OR meta_status LIKE 'error%')")
        q += " AND kind=?" if a.kind else ""
        rows = con.execute(q + " ORDER BY doc_id LIMIT ?", ((a.kind, a.limit) if a.kind else (a.limit,))).fetchall()
    run_docs(rows, a.workers, provider)

if __name__ == "__main__":
    main()
