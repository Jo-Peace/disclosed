"""Step 4: MAGI-style three-role vote. Each role is a separate prompt (and, via providers.toml, may be a different AI;
by default all three are the Meta model). Aggregation is deterministic code, not an LLM.

Roles
  parser    - verifies each transaction against the source PDF text/image (data correctness)
  risk      - flags ambiguity / data-quality / disclosure caveats (NOT investment risk advice)
  explainer - writes a neutral plain-language summary in zh-TW and English (and votes whether the row is clear enough)

Needs MODEL_API_KEY (Meta). `--dry-run` prints the exact prompts without calling any API.
"""
from __future__ import annotations
import argparse, datetime as dt, json, subprocess, sys
from pathlib import Path
from . import config
from .db import connect
from .schema import MAGI_PARSER_SCHEMA, MAGI_RISK_SCHEMA, MAGI_EXPLAINER_SCHEMA
from .providers.meta import BudgetExceeded, spent_usd
from .providers import provider_for_role, provider_name_for_role, FileInput, MissingCredentials, ProviderError

DISCLAIMER = ("Official House Clerk STOCK Act disclosures only. Not investment advice. Free, non-commercial; "
              "commercial use of this data is prohibited (5 U.S.C. 13107(c)).")

COMMON = f"""You are one of three independent reviewers (MAGI) of transactions parsed from a US House Periodic Transaction Report.
You receive the filing header, the PDF text (or the PDF itself), and candidate rows. Give ONE verdict per row idx.
vote: approve = fully correct/clear; flag = probably fine but has a caveat; reject = wrong, unreadable or unsafe to publish.
confidence: your honest 0.0-1.0 certainty in your vote. Be strict: disagree when evidence disagrees.
Never give investment advice or predictions. {DISCLAIMER}
Known limits of the inputs (do NOT flag or reject a row merely for these): (a) the pdftotext source cannot show the cap-gains checkbox, so that field cannot be verified from text; do not penalise it unless a scanned image contradicts it;
(b) a '[ST]'/'[OT]'-style asset-type suffix inside the asset string is just the printed decoration; (c) an empty owner means the filer themself; SP = spouse, DC = dependent child, JT = joint;
(d) 'days_tx_to_filing' / 'days_tx_to_notification' / 'tx_date_after_notification_date' are computed by code - trust them; (e) on SCANNED paper forms no ticker is printed, so a missing ticker there is normal.
Base every claim only on the provided source; if you cannot verify something, say so in reasons and lower your confidence rather than inventing."""

ROLE_PROMPTS = {
    "parser": COMMON + """
ROLE = DATA PARSER. Compare every candidate field (owner, asset, ticker, tx_type, tx_date, notif_date, amount range,
cap-gains checkbox) with the source. If two candidate parses (rule/meta) differ, decide which is right and say what to correct.
Reject a row if any field contradicts the source.""",
    "risk": COMMON + """
ROLE = RISK REVIEWER (data & disclosure caveats, not market risk). Check: very wide amount range, partial sale, option/derivative,
non-stock asset (bond, fund, private holding), spouse/dependent owner, missing ticker, ambiguous asset, filing later than the
45-day notification window, or a likely misparse. Fill risk_flags (use ["none"] if nothing). flag = publish with a caveat badge.""",
    "explainer": COMMON + """
ROLE = PLAIN-LANGUAGE EXPLAINER. For each row write a neutral 1-2 sentence summary in Traditional Chinese (Taiwan usage) and in English:
who (filer/owner), what asset, bought/sold, when, the amount RANGE (never a precise value), and when it was disclosed.
No opinions, no 'should buy/sell', no predictions. Vote reject if the row is too unclear to explain truthfully.""",
}
ROLE_SCHEMAS = {"parser": MAGI_PARSER_SCHEMA, "risk": MAGI_RISK_SCHEMA, "explainer": MAGI_EXPLAINER_SCHEMA}

SCORE = {"approve": 1.0, "flag": 0.5, "reject": 0.0}


def aggregate(votes: dict[str, dict | None], rule_meta_mismatch: bool = False) -> dict:
    """votes: role -> {'vote','confidence',...} or None if that role failed. Deterministic."""
    got = {r: v for r, v in votes.items() if v}
    n_ok, missing = len(got), [r for r, v in votes.items() if not v]
    counts = {k: sum(1 for v in got.values() if v["vote"] == k) for k in SCORE}
    if missing or n_ok < 3:
        consensus = "needs_review"
    elif counts["approve"] == 3:
        consensus = "approved"
    elif counts["reject"] >= 2:
        consensus = "rejected"
    elif counts["approve"] >= 1 and counts["reject"] == 0:
        consensus = "approved_with_caveat"            # >=1 approve, rest flags (no reject): publish with a caveat badge
    elif counts["approve"] >= 2:
        consensus = "approved_with_dissent"           # 2 approve + 1 reject
    else:
        consensus = "needs_review"
    unanimous = n_ok == 3 and len({v["vote"] for v in got.values()}) == 1
    disagreement = (not unanimous) or rule_meta_mismatch or bool(missing)
    confs = [max(0.0, min(1.0, float(v["confidence"]))) for v in got.values()]
    base = sum(confs) / len(confs) if confs else 0.0
    factor = 1.0 if unanimous else (0.8 if consensus.startswith("approved") else 0.5)
    if rule_meta_mismatch: factor *= 0.7
    if missing: factor *= 0.5
    return {"consensus": consensus, "confidence": round(base * factor, 3), "disagreement": disagreement,
            "counts": counts, "missing_roles": missing, "rule_meta_mismatch": rule_meta_mismatch}


def _rows(con, doc_id):
    out = {}
    for src in ("rule", "meta"):
        rs = []
        for r in con.execute(
            "SELECT idx,owner,asset,ticker,asset_type,tx_type,tx_date,notif_date,amount_text,amount_low,amount_high,cap_gains_over_200,raw "
            "FROM transactions WHERE doc_id=? AND source=? ORDER BY idx", (doc_id, src)):
            d = dict(r); raw = json.loads(d.pop("raw") or "{}") if src == "meta" else {}
            if src == "meta":
                d["parser_legible"] = raw.get("legible"); d["parser_notes"] = raw.get("notes"); d["page"] = raw.get("page"); d["subholding"] = raw.get("subholding")
            rs.append(d)
        out[src] = rs
    return out


def _mismatch_by_idx(rows):
    r, m = rows["rule"], rows["meta"]
    if not r or not m: return {}
    keys = ["owner", "ticker", "tx_type", "tx_date", "notif_date", "amount_low", "amount_high"]
    res = {}
    for i in range(max(len(r), len(m))):
        a = r[i] if i < len(r) else None; b = m[i] if i < len(m) else None
        res[i] = (a is None or b is None) or any(a[k] != b[k] for k in keys)
    return res


def _days(a, b):
    try: return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days
    except Exception: return None


def _enrich(rows, filing_date):
    """deterministic helper fields so the model never has to do date arithmetic"""
    for r in rows:
        r["days_tx_to_filing"] = _days(r.get("tx_date"), filing_date)
        r["days_tx_to_notification"] = _days(r.get("tx_date"), r.get("notif_date"))
        r["tx_date_after_notification_date"] = bool(r["days_tx_to_notification"] is not None and r["days_tx_to_notification"] < 0)
    return rows


def build_user_prompt(filing, rows, text: str | None, lo: int, hi: int, scanned_part: str = ""):
    sel = lambda L: [r for r in L if lo <= r["idx"] < hi]
    parts = [f"Filing ID {filing['doc_id']}; filer: {filing['prefix']} {filing['first']} {filing['last']} ({filing['state_dst']}); "
             f"filing date {filing['filing_date']}; PDF: {filing['pdf_url']}{scanned_part}"]
    if text: parts.append("SOURCE TEXT (pdftotext -layout):\n" + text[:60000])
    if rows["rule"]: parts.append("CANDIDATE ROWS A (rule-based parser):\n" + json.dumps(_enrich(sel(rows["rule"]), filing["filing_date"]), ensure_ascii=False))
    if rows["meta"]: parts.append("CANDIDATE ROWS (model parser" + (" B" if rows["rule"] else "; the only parse, there is no rule parser for scanned forms") + "):\n"
                                  + json.dumps(_enrich(sel(rows["meta"]), filing["filing_date"]), ensure_ascii=False))
    parts.append(f"Return exactly one verdict for each idx in [{lo}, {hi - 1}] (idx values as given in the rows).")
    return "\n\n".join(parts)


def _call_role(role, f, user, files, doc_id, lo):
    prov = provider_for_role(role)
    if not prov.available(): raise MissingCredentials(f"provider '{prov.name}' for role '{role}' has no credentials")
    res = prov.generate(system=ROLE_PROMPTS[role], user=user, schema=ROLE_SCHEMAS[role], schema_name=f"magi_{role}",
                        files=files if prov.supports_pdf else None, reasoning_effort="medium", max_output_tokens=30000,
                        label=f"magi:{role}:{doc_id}:{lo}")
    return role, {it["idx"]: it for it in res.data.get("items", [])}, f"{res.provider}:{res.model}"


def evaluate_filing(doc_id: str, batch: int = 25, dry_run: bool = False, max_blocks: int = 2):
    """model calls only (thread-safe: own DB connection, read only). Returns list of result dicts."""
    import concurrent.futures as cf
    from .meta_parser import make_chunk
    con = connect()
    f = con.execute("SELECT * FROM filings WHERE doc_id=?", (doc_id,)).fetchone()
    rows = _rows(con, doc_id)
    scanned = f["kind"] == "scanned"
    if scanned: rows["rule"] = []                    # scanned forms have no rule parse
    cand = rows["rule"] or rows["meta"]
    if not cand: return []
    mism = _mismatch_by_idx(rows)
    text = None
    if f["kind"] == "text":
        text = subprocess.run(["pdftotext", "-layout", f["pdf_path"], "-"], capture_output=True).stdout.decode("utf-8", "replace")
    out = []
    starts = list(range(0, len(cand), batch))
    if scanned and len(starts) > max_blocks + 1:      # big paper filings: random consecutive blocks only (cost cap); recorded in the results
        import random
        starts = sorted(random.Random(int(doc_id)).sample(starts, max_blocks))
    for lo in starts:
        hi = min(lo + batch, len(cand))
        files, part = None, ""
        if scanned:
            pgs = [r.get("page") for r in cand[lo:hi] if r.get("page")]
            if pgs:
                p0, p1 = max(1, min(pgs)), max(pgs)
                src = Path(f["pdf_path"])
                files = [FileInput(make_chunk(src, p0 - 1, p1, doc_id) if (p0, p1) != (1, None) else src, detail="high")]
                part = f" (attached file = pages {p0}-{p1} of the original; the 'page' value in rows is relative to the ORIGINAL document)"
        user = build_user_prompt(f, rows, text, lo, hi, part)
        if dry_run:
            print(f"--- batch {lo}-{hi} files={bool(files)} ---\n{user[:1200]}\n"); continue
        per_role, models = {}, {}
        with cf.ThreadPoolExecutor(3) as ex:
            futs = {ex.submit(_call_role, r, f, user, files, doc_id, lo): r for r in ("parser", "risk", "explainer")}
            for fu in cf.as_completed(futs):
                r = futs[fu]
                try:
                    role, items, model = fu.result(); per_role[role] = items; models[role] = model
                except ProviderError as e:
                    print(f"{doc_id} role {r} batch {lo} failed: {e}", file=sys.stderr); per_role[r] = {}
        for i in range(lo, hi):
            votes = {r: per_role.get(r, {}).get(i) for r in ("parser", "risk", "explainer")}
            agg = aggregate(votes, mism.get(i, False))
            ex_ = votes["explainer"] or {}
            out.append({"doc_id": doc_id, "tx_idx": i, "row": cand[i], "votes": votes, "aggregate": agg, "models": models,
                        "summary_zh_tw": ex_.get("summary_zh_tw"), "summary_en": ex_.get("summary_en"),
                        "risk_flags": (votes["risk"] or {}).get("risk_flags", []), "disclaimer": DISCLAIMER})
    return out


def save_results(con, doc_id, results):
    now = dt.datetime.now().isoformat(timespec="seconds")
    con.execute("DELETE FROM magi_results WHERE doc_id=?", (doc_id,))
    for r in results:
        agg = r["aggregate"]
        con.execute("INSERT INTO magi_results(doc_id,tx_idx,created_at,result_json,consensus,confidence,disagreement) VALUES(?,?,?,?,?,?,?)",
                    (doc_id, r["tx_idx"], now, json.dumps(r, ensure_ascii=False), agg["consensus"], agg["confidence"], int(agg["disagreement"])))
    con.commit()


def select_docs(con, what: str, n_sample: int = 30, seed: int = 7):
    import random
    scanned = [r[0] for r in con.execute("SELECT doc_id FROM filings WHERE kind='scanned' AND meta_n_tx>0 ORDER BY doc_id")]
    odd = [r[0] for r in con.execute("""SELECT DISTINCT t.doc_id FROM tx t WHERE t.tx_date>t.notif_date""")]
    dis = [r[0] for r in con.execute("""SELECT DISTINCT a.doc_id FROM transactions a JOIN transactions b ON a.doc_id=b.doc_id AND a.idx=b.idx
        AND a.source='rule' AND b.source='meta' WHERE a.owner IS NOT b.owner OR a.ticker IS NOT b.ticker OR a.tx_type IS NOT b.tx_type OR a.tx_date IS NOT b.tx_date
        OR a.notif_date IS NOT b.notif_date OR a.amount_low IS NOT b.amount_low OR a.amount_high IS NOT b.amount_high OR a.cap_gains_over_200 IS NOT b.cap_gains_over_200""")]
    text = [r[0] for r in con.execute("""SELECT doc_id FROM filings WHERE kind!='scanned' AND rule_n_tx>0 AND meta_n_tx>0 AND rule_n_tx<=40 ORDER BY doc_id""")]
    rnd = random.Random(seed); rnd.shuffle(text)
    sample = [d for d in text if d not in set(odd) | set(dis)][:n_sample]
    return {"scanned": scanned, "odd": odd, "disagree": dis, "sample": sample}


def run_many(doc_ids, workers=3, batch=25, max_blocks=2):
    import concurrent.futures as cf
    con = connect(); n_ok = 0
    todo = [d for d in doc_ids if not con.execute("SELECT 1 FROM magi_results WHERE doc_id=? LIMIT 1", (d,)).fetchone()]
    print(f"MAGI: {len(todo)} filings to evaluate ({len(doc_ids) - len(todo)} already done)", flush=True)
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(evaluate_filing, d, batch, False, max_blocks): d for d in todo}
        for fu in cf.as_completed(futs):
            d = futs[fu]
            try: res = fu.result()
            except BudgetExceeded as e:
                print("STOP:", e, file=sys.stderr); ex.shutdown(wait=False, cancel_futures=True); sys.exit(4)
            except MissingCredentials as e:
                print("ERROR:", e, file=sys.stderr); ex.shutdown(wait=False, cancel_futures=True); sys.exit(3)
            except Exception as e:
                print(f"{d}: FAILED {type(e).__name__}: {e}", file=sys.stderr); continue
            if any(x["aggregate"]["missing_roles"] for x in res):
                print(f"{d}: some roles missing -> stored as needs_review", file=sys.stderr)
            save_results(con, d, res); n_ok += 1
            c = {}
            for x in res: c[x["aggregate"]["consensus"]] = c.get(x["aggregate"]["consensus"], 0) + 1
            print(f"{d}: {len(res)} rows {c}  (spent ${spent_usd():.2f})", flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--set", choices=["scanned", "odd", "disagree", "sample", "all"], help="run MAGI on a predefined subset")
    ap.add_argument("--max-blocks", type=int, default=2, help="scanned filings with more than this many 25-row blocks (+1) are sampled")
    ap.add_argument("--sample", type=int, default=30); ap.add_argument("--workers", type=int, default=3); ap.add_argument("--batch", type=int, default=25)
    a = ap.parse_args(argv)
    con = connect()
    if a.set:
        sel = select_docs(con, a.set, a.sample)
        ids = sorted(set(sum(sel.values(), []))) if a.set == "all" else sel[a.set]
        print({k: len(v) for k, v in sel.items()}); 
        if a.dry_run: print('dry run: would evaluate', len(ids), 'filings'); return
        run_many(ids, a.workers, a.batch, a.max_blocks); return
    if not a.doc: ap.error("--doc or --set required")
    res = evaluate_filing(a.doc, a.batch, a.dry_run)
    if a.dry_run: return
    save_results(con, a.doc, res)
    for r in res:
        ag = r["aggregate"]
        print(f"[{r['tx_idx']}] {str(r['row']['asset'])[:40]:40s} {r['row']['tx_type']:>11s} -> {ag['consensus']} conf={ag['confidence']} disagreement={ag['disagreement']}")
        print("     zh:", r["summary_zh_tw"]); print("     en:", r["summary_en"])

if __name__ == "__main__":
    main()
