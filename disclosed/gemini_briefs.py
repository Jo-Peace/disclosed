"""Google Gemini plain-language briefs for member pages and current daily picks.

Three genuine Gemini API usages, all free-tier, all cached by content hash:

  1. Text generation (`generateContent`, no response schema) — bilingual 繁中 + EN brief.
  2. Structured JSON output (`responseMimeType=application/json` + `responseSchema`) — fact-check of that brief.
  3. Vision (page image of a scanned PTR via `inline_data`) — second look at a small sample of paper filings.

Results are written to data/gemini_briefs.json and copied into the static site by export_site.py.
The browser never sees a key. The append-only pick log is never edited.

    python -m disclosed.gemini_briefs fill     # fail-soft: exits 0 if the key is missing or a quota is hit
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, re, sys, tempfile
from collections import Counter
from pathlib import Path

from . import config
from .db import connect
from .names import member_id, member_name
from .picks import LOGDIR, _read
from .providers import MissingCredentials, ProviderError
from .providers.base import FileInput
from .providers.gemini import GeminiProvider
from .summaries import facts_line, validate

STORE = config.GEMINI_STORE
TOP_N_MEMBERS = 30
RECENT_TX = 8
TOP_TICKERS = 8
# Small, diverse scanned stock PTRs (1–2 pages) used only as vision samples.
VISION_DOCS = ("9116361", "9116197", "9116292")

BRIEF_SYSTEM = (
    "You are writing a short, neutral plain-language brief of official US House STOCK Act disclosures "
    "for a free, non-commercial bilingual (Traditional Chinese / English) site. "
    "HARD RULES: (1) Use ONLY the facts in the user message — do not add company background, news, prices, "
    "sectors, motives or outcomes from your own knowledge. "
    "(2) Do NOT give investment advice or recommendations, do not say a stock is a good/bad pick, and do not predict prices. "
    "(3) Do NOT make causal claims or imply wrongdoing, insider knowledge, or that a member acted because of anything. "
    "(4) Every number, date, name, ticker and amount range you write must appear in the facts; amounts are RANGES, never precise values. "
    "(5) Write exactly 2 short sentences per language, plain and neutral. Sentence 1 states who disclosed what (counts, dates, notable tickers or amount ranges as given). "
    "Sentence 2 MUST say this is public disclosure data, not investment advice, and that filings can be filed up to 45 days after a trade. "
    "Traditional Chinese disclaimer wording: 非投資建議. "
    "Output format — two labelled blocks and nothing else:\nZH-TW: <two sentences>\nEN: <two sentences>"
)

CHECK_SYSTEM = (
    "You are a fact-checker. Compare a brief against a structured fact list. "
    "Mark consistent=false if the brief invents a name, ticker, date, count, or amount not in the facts, "
    "or if it gives investment advice, predicts prices, or implies wrongdoing. "
    "has_disclaimer=true only if both language versions clearly say this is not investment advice "
    "(English: 'not investment advice'; Chinese: 非投資建議 / 不是投資建議 / 不構成投資建議). "
    "ok_to_publish=true only when consistent is true, has_disclaimer is true, and invented_facts is empty. "
    "Do not rewrite the brief. Return only the JSON schema you were given."
)

CHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "consistent": {"type": "boolean"},
        "invented_facts": {"type": "array", "items": {"type": "string"}},
        "has_disclaimer": {"type": "boolean"},
        "ok_to_publish": {"type": "boolean"},
    },
    "required": ["consistent", "invented_facts", "has_disclaimer", "ok_to_publish"],
}

VISION_SYSTEM = (
    "You are reading one page of a scanned US House Periodic Transaction Report (a paper form). "
    "Transcribe only what you can see: asset / company names, any ticker-like symbols, transaction type "
    "(purchase/sale/partial), trade dates, and amount ranges. If a field is unreadable, omit it. "
    "Do not invent tickers that are not printed or clearly abbreviated on the page. "
    "Do not give investment advice. page_description_zh must be Traditional Chinese (Taiwan, 正體中文 / 繁體字), not Simplified. page_description_* should be one short neutral sentence about what the page shows. "
    "Return only the JSON schema you were given."
)

VISION_SCHEMA = {
    "type": "object",
    "properties": {
        "page_description_zh": {"type": "string"},
        "page_description_en": {"type": "string"},
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "asset_name": {"type": "string"},
                    "ticker_guess": {"type": "string"},
                    "tx_type": {"type": "string"},
                    "tx_date": {"type": "string"},
                    "amount_range": {"type": "string"},
                },
                "required": ["asset_name"],
            },
        },
    },
    "required": ["page_description_en", "page_description_zh", "rows"],
}


def content_hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load() -> dict:
    if STORE.exists():
        return json.loads(STORE.read_text())
    return {"members": {}, "picks": {}, "vision": {}, "meta": {}}


def save(store: dict):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(store, ensure_ascii=False, indent=1))


def parse_brief(text: str) -> tuple[str, str]:
    """Split a ZH-TW: / EN: labelled response into (zh, en). Raises ValueError if either is missing."""
    zh = en = ""
    m = re.search(r"ZH-TW:\s*(.+?)(?:\nEN:|\Z)", text, re.S | re.I)
    if m:
        zh = m.group(1).strip()
    m = re.search(r"\nEN:\s*(.+)\Z", text, re.S | re.I)
    if m:
        en = m.group(1).strip()
    if not zh or not en:
        # tolerate a missing newline before EN
        m = re.search(r"ZH-TW:\s*(.+?)\s+EN:\s*(.+)", text, re.S | re.I)
        if m:
            zh, en = m.group(1).strip(), m.group(2).strip()
    if not zh or not en:
        raise ValueError("brief missing ZH-TW or EN block")
    return zh, en


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def member_facts(con, mid: str) -> dict | None:
    """Compact, deterministic fact payload for one member (no model calls)."""
    filings = con.execute(
        "SELECT * FROM filings WHERE filing_type='P' ORDER BY filing_date DESC"
    ).fetchall()
    mine = [f for f in filings if member_id(f) == mid]
    if not mine:
        return None
    name = member_name(mine[0])
    state = mine[0]["state_dst"]
    docs = {f["doc_id"] for f in mine}
    txs = con.execute(
        f"SELECT * FROM tx WHERE doc_id IN ({','.join('?' * len(docs))}) ORDER BY tx_date DESC, id DESC",
        tuple(docs),
    ).fetchall()
    n_buy = sum(1 for t in txs if (t["tx_type"] or "").startswith("P"))
    n_sell = sum(1 for t in txs if (t["tx_type"] or "").startswith("S"))
    tickers = Counter(t["ticker"] for t in txs if t["ticker"])
    top = [{"ticker": k, "n": n} for k, n in tickers.most_common(TOP_TICKERS)]
    recent = []
    for t in txs[:RECENT_TX]:
        recent.append({
            "ticker": t["ticker"] or "",
            "asset": (t["asset"] or "")[:60],
            "type": t["tx_type"],
            "tx_date": t["tx_date"],
            "amount": t["amount_text"],
        })
    n_scanned = sum(1 for f in mine if f["kind"] == "scanned")
    n_inferred = sum(1 for t in txs if t["ticker_inferred"])
    facts = {
        "member_id": mid,
        "name": name,
        "state_dst": state,
        "n_filings": len(mine),
        "n_tx": len(txs),
        "n_buy": n_buy,
        "n_sell": n_sell,
        "first_filing": min(f["filing_date"] for f in mine),
        "last_filing": max(f["filing_date"] for f in mine),
        "top_tickers": top,
        "n_other_tickers": max(0, len(tickers) - len(top)),
        "recent_tx": recent,
        "n_scanned_filings": n_scanned,
        "n_inferred_tickers": n_inferred,
        "window_note": "Filings may be submitted up to 45 days after a trade. Amounts are ranges.",
    }
    facts["hash"] = content_hash({k: v for k, v in facts.items() if k != "hash"})
    return facts


def pick_facts(entry: dict, pick: dict) -> dict:
    facts = {
        "pick_date": entry["pick_date"],
        "ticker": pick["ticker"],
        "name": pick.get("name") or "",
        "members": [m.get("name") or m.get("id") for m in pick.get("members") or []],
        "n_members": pick.get("n_members", len(pick.get("members") or [])),
        "n_sellers": pick.get("n_sellers", 0),
        "tx": [
            {
                "member": t.get("member"),
                "tx_date": t.get("tx_date") or t.get("td"),
                "filing_date": t.get("filing_date") or t.get("fd"),
                "amount": t.get("amount") or t.get("am"),
                "owner": t.get("owner") or t.get("ow") or "self",
            }
            for t in (pick.get("tx") or [])[:RECENT_TX]
        ],
        "n_tx": len(pick.get("tx") or []),
        "facts_en": facts_line(pick, "en", entry["pick_date"]),
        "facts_zh": facts_line(pick, "zh", entry["pick_date"]),
        "window_note": "Filings may be submitted up to 45 days after a trade. Amounts are ranges.",
    }
    facts["hash"] = content_hash({k: v for k, v in facts.items() if k != "hash"})
    return facts


def facts_blob(facts: dict) -> str:
    """Number-bearing text used by the deterministic number guardrail."""
    return expand_allowed(json.dumps(facts, ensure_ascii=False) + " 45 2 1")


def expand_allowed(blob: str) -> str:
    """Allow equivalent number spellings (leading zeros, commas, trailing commas) so 'November 5' matches '2026-11-05'."""
    nums = re.findall(r"\d[\d,]*(?:\.\d+)?", blob)
    extra = []
    for n in nums:
        variants = {n, n.replace(",", ""), n.rstrip(","), n.replace(",", "").rstrip(",")}
        for v in list(variants):
            variants.add(v.lstrip("0") or "0")
        extra.extend(variants)
    return blob + " " + " ".join(sorted(extra))


def format_member_user(facts: dict) -> str:
    top = ", ".join(f"{x['ticker']} ({x['n']} trades)" for x in facts["top_tickers"]) or "(none with a ticker)"
    if facts["n_other_tickers"]:
        top += f", and {facts['n_other_tickers']} other ticker(s)"
    recent = "\n".join(
        f"- {r['tx_date']}, {r['type']}, {r['ticker'] or r['asset']}, {r['amount']}" for r in facts["recent_tx"]
    ) or "(none)"
    return (
        f"Member: {facts['name']} ({facts['state_dst']})\n"
        f"Periodic transaction reports filed {facts['first_filing']} to {facts['last_filing']}: "
        f"{facts['n_filings']} filing(s), {facts['n_tx']} transaction(s) "
        f"({facts['n_buy']} purchases, {facts['n_sell']} sales).\n"
        f"Most-traded tickers in this record: {top}.\n"
        f"Most recent {len(facts['recent_tx'])} transaction(s) (not a complete list when the member has more):\n{recent}\n"
        f"Scanned paper filings: {facts['n_scanned_filings']}. Inferred tickers (from printed company names): {facts['n_inferred_tickers']}.\n"
        f"{facts['window_note']}\n"
        "Write the 2-sentence brief in ZH-TW and EN as instructed."
    )


def format_pick_user(facts: dict) -> str:
    tx = "\n".join(
        f"- {t['member']}, {t['tx_date']}, filed {t['filing_date']}, {t['amount']}, {t['owner']}" for t in facts["tx"]
    ) or "(none listed)"
    return (
        f"Pick list date: {facts['pick_date']}\n"
        f"Ticker: {facts['ticker']} ({facts['name']})\n"
        f"Members in this pick: {', '.join(facts['members']) or '—'}\n"
        f"Listed supporting purchases ({len(facts['tx'])} of {facts['n_tx']}):\n{tx}\n"
        f"Auto-computed facts (template, not AI): {facts['facts_en']}\n"
        f"{facts['window_note']}\n"
        "Write the 2-sentence brief in ZH-TW and EN as instructed."
    )


def top_member_ids(con, n=TOP_N_MEMBERS) -> list[str]:
    rows = con.execute(
        """
        SELECT f.last, f.first, f.state_dst, f.suffix, count(*) n
        FROM tx t JOIN filings f ON f.doc_id = t.doc_id
        WHERE f.filing_type = 'P'
        GROUP BY 1, 2, 3, 4
        ORDER BY n DESC
        LIMIT ?
        """,
        (n,),
    ).fetchall()
    return [member_id(r) for r in rows]


def latest_live_picks() -> list[tuple[dict, dict]]:
    """(entry, pick) pairs from the latest live pick date (both methods)."""
    live = _read(LOGDIR / "live.jsonl")
    if not live:
        return []
    last_date = live[-1]["pick_date"]
    out, seen = [], set()
    for e in live:
        if e["pick_date"] != last_date:
            continue
        for p in e.get("picks") or []:
            k = p["ticker"]
            if k in seen:
                continue
            seen.add(k)
            out.append((e, p))
    return out


def render_first_page(pdf: Path) -> Path:
    """Render page 1 of a scanned PDF to a modest JPEG (free-tier vision)."""
    import pymupdf
    doc = pymupdf.open(pdf)
    page = doc[0]
    # ~1.2x default 72dpi, cap width so the request stays small
    zoom = 1.3
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
    if pix.width > 1024:
        pix = page.get_pixmap(matrix=pymupdf.Matrix(1024 / page.rect.width, 1024 / page.rect.width), alpha=False)
    tmp = Path(tempfile.mkstemp(suffix=".jpg")[1])
    pix.save(tmp.as_posix())
    return tmp


def compare_vision(extracted_rows: list[dict], db_rows: list[dict]) -> dict:
    """Deterministic overlap between Gemini vision rows and our parsed tx rows."""
    def keys(row, name_k, date_k, amt_k):
        return _norm(row.get(name_k) or ""), (row.get(date_k) or "")[:10], _norm(row.get(amt_k) or "")

    db_names = [_norm(r.get("asset") or "") for r in db_rows]
    db_dates = {(r.get("tx_date") or "")[:10] for r in db_rows}
    hits_name = 0
    for r in extracted_rows:
        n = _norm(r.get("asset_name") or "")
        if not n:
            continue
        if any(n in d or d in n for d in db_names if d):
            hits_name += 1
    hits_date = sum(1 for r in extracted_rows if (r.get("tx_date") or "")[:10] in db_dates)
    return {
        "n_vision_rows": len(extracted_rows),
        "n_db_rows": len(db_rows),
        "name_overlaps": hits_name,
        "date_overlaps": hits_date,
        "agrees": hits_name >= 1 or hits_date >= 1,
    }


def _fresh(entry: dict, facts: dict) -> bool:
    return entry.get("status") == "ok" and entry.get("content_hash") == facts.get("hash") and entry.get("zh_tw") and entry.get("en")


def _write_brief(prov: GeminiProvider, user: str, facts: dict, label: str, stats: dict) -> dict:
    blob = facts_blob(facts)
    last_err = "unknown"
    for attempt in range(2):
        try:
            gen = prov.generate(
                system=BRIEF_SYSTEM,
                user=user if attempt == 0 else user + f"\nPREVIOUS ATTEMPT REJECTED: {last_err}. Fix it. Keep the ZH-TW: / EN: labels.",
                schema=None,
                max_output_tokens=1024,
                label=f"{label}:gen:{attempt}",
            )
            stats["n_generate"] += 1
            zh, en = parse_brief(gen.text)
            probs = validate(zh, blob, "zh") + validate(en, blob, "en")
            check = prov.generate(
                system=CHECK_SYSTEM,
                user="FACTS (JSON):\n" + json.dumps(facts, ensure_ascii=False) + "\n\nBRIEF ZH-TW:\n" + zh + "\n\nBRIEF EN:\n" + en,
                schema=CHECK_SCHEMA,
                schema_name="brief_factcheck",
                max_output_tokens=512,
                label=f"{label}:check:{attempt}",
            )
            stats["n_json_check"] += 1
            cd = check.data or {}
            if probs:
                last_err = "deterministic guardrail: " + "; ".join(probs)
                continue
            if not cd.get("ok_to_publish") or not cd.get("consistent") or not cd.get("has_disclaimer"):
                last_err = f"Gemini fact-check rejected: {cd}"
                continue
            return {
                "status": "ok",
                "zh_tw": zh,
                "en": en,
                "provider": "gemini",
                "model": gen.model,
                "checked": True,
                "check_model": check.model,
                "content_hash": facts["hash"],
                "guardrail": "passed",
            }
        except MissingCredentials:
            raise
        except (ProviderError, ValueError) as e:
            last_err = str(e)[:240]
            stats["n_errors"] += 1
            continue
    return {"status": "rejected", "error": last_err[:300], "content_hash": facts["hash"]}


def fill(limit: int | None = None) -> int:
    """Generate or refresh briefs. Always returns 0 (fail-soft) except on unexpected bugs."""
    stats = {"n_generate": 0, "n_json_check": 0, "n_vision": 0, "n_cached": 0, "n_errors": 0, "n_written": 0, "n_skipped": 0}
    prov = GeminiProvider()
    if not prov.available():
        print("[gemini_briefs] GEMINI_API_KEY is not set; skipping (fail-soft). Existing store left unchanged.", file=sys.stderr)
        return 0
    store = load()
    store.setdefault("members", {}); store.setdefault("picks", {}); store.setdefault("vision", {})
    con = connect()
    targets = []

    # members
    mids = top_member_ids(con, TOP_N_MEMBERS)
    # also brief any member who has a vision sample, so the sample page has a brief
    for doc in VISION_DOCS:
        f = con.execute("SELECT * FROM filings WHERE doc_id=?", (doc,)).fetchone()
        if f:
            mid = member_id(f)
            if mid not in mids:
                mids.append(mid)
    for mid in mids:
        facts = member_facts(con, mid)
        if not facts:
            continue
        targets.append(("member", mid, facts, format_member_user(facts)))

    # current live picks
    for entry, pick in latest_live_picks():
        facts = pick_facts(entry, pick)
        key = f"{facts['pick_date']}|{facts['ticker']}"
        targets.append(("pick", key, facts, format_pick_user(facts)))

    if limit:
        targets = targets[:limit]

    try:
        for kind, key, facts, user in targets:
            bucket = "members" if kind == "member" else "picks"
            prev = store[bucket].get(key) or {}
            if _fresh(prev, facts):
                stats["n_skipped"] += 1
                continue
            rec = _write_brief(prov, user, facts, f"{kind}:{key}", stats)
            store[bucket][key] = rec
            if rec.get("status") == "ok":
                stats["n_written"] += 1
            save(store)  # incremental, so a later quota hit keeps earlier work

        # vision samples (one page each)
        for doc in VISION_DOCS:
            pdf = config.PDF_DIR / f"{doc}.pdf"
            f = con.execute("SELECT * FROM filings WHERE doc_id=?", (doc,)).fetchone()
            if not f or not pdf.exists():
                continue
            db_rows = [dict(r) for r in con.execute(
                "SELECT ticker, asset, tx_type, tx_date, amount_text FROM tx WHERE doc_id=?", (doc,)
            ).fetchall()]
            vfacts = {"doc_id": doc, "member": member_name(f), "state_dst": f["state_dst"],
                      "filing_date": f["filing_date"], "n_db_rows": len(db_rows), "script": "zh-Hant",
                      "db_preview": [{"asset": r["asset"], "ticker": r["ticker"], "type": r["tx_type"],
                                      "tx_date": r["tx_date"], "amount": r["amount_text"]} for r in db_rows[:12]]}
            vhash = content_hash(vfacts)
            prev = store["vision"].get(doc) or {}
            if prev.get("status") == "ok" and prev.get("content_hash") == vhash:
                stats["n_skipped"] += 1
                continue
            img = None
            try:
                img = render_first_page(pdf)
                user = (
                    f"This is page 1 of House PTR {doc}, filed {f['filing_date']} by {member_name(f)} ({f['state_dst']}). "
                    "Extract the visible transaction rows. Do not use any outside knowledge."
                )
                r = prov.generate(
                    system=VISION_SYSTEM, user=user, schema=VISION_SCHEMA, schema_name="ptr_vision",
                    files=[FileInput(path=img, mime="image/jpeg")], max_output_tokens=1024,
                    label=f"vision:{doc}",
                )
                stats["n_vision"] += 1
                rows = (r.data or {}).get("rows") or []
                cmp_ = compare_vision(rows, db_rows)
                store["vision"][doc] = {
                    "status": "ok",
                    "doc_id": doc,
                    "member_id": member_id(f),
                    "member": member_name(f),
                    "state_dst": f["state_dst"],
                    "filing_date": f["filing_date"],
                    "pdf": f["pdf_url"],
                    "zh_tw": r.data.get("page_description_zh") or "",
                    "en": r.data.get("page_description_en") or "",
                    "rows": rows,
                    "compare": cmp_,
                    "model": r.model,
                    "content_hash": vhash,
                }
                stats["n_written"] += 1
            except MissingCredentials:
                raise
            except Exception as e:
                stats["n_errors"] += 1
                store["vision"][doc] = {"status": "error", "doc_id": doc, "error": str(e)[:300], "content_hash": vhash}
            finally:
                if img:
                    try:
                        img.unlink(missing_ok=True)
                    except Exception:
                        pass
            save(store)

    except MissingCredentials as e:
        print(f"[gemini_briefs] credentials problem, stopping early (fail-soft): {e}", file=sys.stderr)
    except ProviderError as e:
        print(f"[gemini_briefs] provider error, keeping what was written (fail-soft): {e}", file=sys.stderr)

    store["meta"] = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "model": config.GEMINI_MODEL,
        "n_members_ok": sum(1 for v in store["members"].values() if v.get("status") == "ok"),
        "n_picks_ok": sum(1 for v in store["picks"].values() if v.get("status") == "ok"),
        "n_vision_ok": sum(1 for v in store["vision"].values() if v.get("status") == "ok"),
        "last_run": stats,
    }
    save(store)
    print("gemini_briefs", {**stats, "members_ok": store["meta"]["n_members_ok"],
                            "picks_ok": store["meta"]["n_picks_ok"], "vision_ok": store["meta"]["n_vision_ok"]})
    return 0


def public_payload(store: dict | None = None) -> dict:
    """Subset copied into site/data.json (no error strings that might be noisy; no hashes needed by the UI)."""
    store = store or load()

    def brief(v):
        if not v or v.get("status") != "ok":
            return None
        return {"zh_tw": v["zh_tw"], "en": v["en"], "model": v.get("model") or config.GEMINI_MODEL,
                "checked": bool(v.get("checked")), "provider": "gemini"}

    members = {k: brief(v) for k, v in store.get("members", {}).items()}
    members = {k: v for k, v in members.items() if v}
    picks = {k: brief(v) for k, v in store.get("picks", {}).items()}
    picks = {k: v for k, v in picks.items() if v}
    vision = {}
    for k, v in store.get("vision", {}).items():
        if v.get("status") != "ok":
            continue
        vision[k] = {
            "doc_id": v["doc_id"], "member_id": v.get("member_id"), "member": v.get("member"),
            "state_dst": v.get("state_dst"), "filing_date": v.get("filing_date"), "pdf": v.get("pdf"),
            "zh_tw": v.get("zh_tw") or "", "en": v.get("en") or "",
            "n_rows": len(v.get("rows") or []),
            "compare": v.get("compare") or {},
            "model": v.get("model"),
        }
    meta = store.get("meta") or {}
    return {"members": members, "picks": picks, "vision": vision,
            "model": meta.get("model") or config.GEMINI_MODEL,
            "n_members": len(members), "n_picks": len(picks), "n_vision": len(vision)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fill"])
    ap.add_argument("--limit", type=int, help="max member+pick briefs this run (vision still attempted)")
    a = ap.parse_args()
    sys.exit(fill(a.limit))
