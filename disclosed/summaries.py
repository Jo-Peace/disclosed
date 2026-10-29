"""Plain-language summaries for featured picks.

Two clearly separate layers:
  1. `facts_line()`  - deterministic, template-generated facts (NOT AI). Always available; shown in the site as 'Auto-generated facts'.
  2. AI summary      - produced ONLY by the configured 'explainer' provider (Meta Muse Spark by default). Until a key exists the
                       placeholder {"status": "pending_meta_key", zh_tw: null, en: null} stays and the site shows 'AI summary pending'.
Summaries live in data/ai_summaries.json keyed '<pick_date>|<ticker>' so the append-only pick log is never edited.

    python -m disclosed.summaries fill      # needs MODEL_API_KEY (Meta). Without it: exits 3, writes nothing."""
from __future__ import annotations
import argparse, json, sys
from . import config
from .providers import provider_for_role, provider_name_for_role, MissingCredentials, ProviderError
from .picks import LOGDIR, _read
from .schema import MAGI_EXPLAINER_SCHEMA

STORE = config.DATA / "ai_summaries.json"

GUARD = ("HARD RULES: (1) Use ONLY the facts in the user message - do not add company background, news, prices, sectors, motives or outcomes from your own knowledge. "
         "(2) Do NOT give investment advice or recommendations, do not say a stock is a good/bad pick, and do not predict prices. "
         "(3) Do NOT make causal claims or imply wrongdoing, insider knowledge or that a member acted because of anything. "
         "(4) Every number, date, name and amount range you write must appear in the facts; amounts are RANGES, never precise values. "
         "(5) Write exactly 2 short sentences, plain and neutral; sentence 1 = who disclosed what, the trade date(s), the filing date and the amount RANGE (name the 30-day member count if >1). The 2nd sentence MUST say this is public disclosure data, not investment advice, and that filings can be filed up to 45 days after a trade.")
SYSTEM = (GUARD + " " + "You are the PLAIN-LANGUAGE EXPLAINER of a free, non-commercial disclosure digest of US House STOCK Act filings. "
          "Describe ONLY the facts given. Never recommend buying/selling, never predict prices, never imply wrongdoing. "
          "Mention that amounts are ranges and filings can be up to 45 days late. Output Traditional Chinese (Taiwan) and English.")
USER_TEMPLATE = """Pick list date: {pick_date}
Ticker: {ticker} ({name})
Members who disclosed a purchase of this ticker in the last 30 days: {members}
Transactions FILED IN THE LAST 14 DAYS (only these are listed; earlier filings in the 30-day window are not listed, so do not state a total transaction count for the 30 days). Columns: member, tx date, filing date, amount range, owner ('self' = the member):
{tx_lines}
Auto-computed facts (rule-based, not AI): {facts}
Write the 2-sentence summary in zh-TW and in English (zh-TW disclaimer wording: 非投資建議; also state the 45-day filing window)."""

def facts_line(p, lang="en"):
    n = len(p["tx"]); amts = sorted({t["amount"] for t in p["tx"] if t["amount"]})
    if lang == "en":
        return f"{p['n_members']} member(s) disclosed {n} purchase transaction(s) of {p['ticker']} (amount ranges: {'; '.join(amts)}); public since {p['public_date']}."
    return f"{p['n_members']} 位議員申報 {n} 筆 {p['ticker']} 買進交易（金額區間：{'；'.join(amts)}）；公開日 {p['public_date']}。"

BAD_PATTERNS = [r"should (buy|sell)", r"recommend", r"\bbecause\b", r"\bdue to\b", r"insider", r"will (rise|fall|go up|go down|increase|decrease)", r"undervalued", r"good (pick|buy)", r"guarantee",
                r"建議(買|賣|買進|賣出|投資)", r"因為", r"導致", r"內線", r"預期.*(上漲|下跌)", r"將(會)?(上漲|下跌)", r"值得(買|投資)", r"穩賺", r"獲利"]

def validate(text, allowed_blob, lang):
    """deterministic guardrail check. returns list of problems (empty = ok)"""
    import re
    probs = [f"banned pattern /{b}/" for b in BAD_PATTERNS if re.search(b, text, re.I)]
    allowed = set(re.findall(r"\d[\d,]*(?:\.\d+)?", allowed_blob))
    for num in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        if num.strip(",") and num not in allowed and num.strip(",") not in {a.strip(",") for a in allowed}:
            probs.append(f"number '{num}' not in provided facts")
    low = text.lower()
    if lang == "en" and not ("not investment advice" in low or "not advice" in low): probs.append("missing 'not investment advice' disclaimer")
    if lang == "zh" and "非投資建議" not in text and "不構成投資建議" not in text and "不是投資建議" not in text: probs.append("missing 非投資建議 disclaimer")
    return probs

def load(): return json.loads(STORE.read_text()) if STORE.exists() else {}

def fill(limit=None):
    try:
        prov = provider_for_role("explainer")
    except MissingCredentials as e:
        print(f"[blocked] explainer provider '{provider_name_for_role('explainer')}' has no credentials: {e}\nNo summaries written (no fake text).", file=sys.stderr); return 3
    if not prov.available():
        print(f"[blocked] explainer provider '{provider_name_for_role('explainer')}' is not available (no credentials). No summaries written (no fake text).", file=sys.stderr); return 3
    store = load(); n = 0
    for path in (LOGDIR / "live.jsonl",):                    # backtest picks are not summarised
        for e in _read(path):
            for p in e["picks"]:
                k = f"{e['pick_date']}|{p['ticker']}"
                if k in store and store[k].get("status") == "ok": continue
                tx = "\n".join(f"- {t['member']}, {t['tx_date']}, {t['filing_date']}, {t['amount']}, {t['owner']}" for t in p["tx"])
                user = USER_TEMPLATE.format(pick_date=e["pick_date"], ticker=p["ticker"], name=p["name"], tx_lines=tx,
                                            members=", ".join(m["name"] for m in p["members"]), facts=facts_line(p))
                blob = user + " 45 2 1"                       # the 45-day window is allowed by the prompt rule
                ok = None
                for attempt in range(2):
                    try:
                        r = prov.generate(system=SYSTEM, user=user + (f"\nPREVIOUS ATTEMPT REJECTED BY GUARDRAIL: {probs}. Fix it." if attempt else ""),
                                          schema={"type": "object", "properties": {"summary_zh_tw": {"type": "string"}, "summary_en": {"type": "string"}}, "required": ["summary_zh_tw", "summary_en"], "additionalProperties": False},
                                          schema_name="pick_summary", reasoning_effort="low", label=f"summary:{e['pick_date']}:{p['ticker']}:{attempt}")
                    except MissingCredentials as ex:
                        print("[blocked]", ex, file=sys.stderr); return 3
                    except ProviderError as ex:
                        store[k] = {"status": "error", "error": str(ex)[:200]}; break
                    probs = validate(r.data["summary_zh_tw"], blob, "zh") + validate(r.data["summary_en"], blob, "en")
                    if not probs: ok = r; break
                else:
                    store[k] = {"status": "rejected_by_guardrail", "problems": probs, "zh_tw": r.data["summary_zh_tw"], "en": r.data["summary_en"]}
                if ok is None: continue
                r = ok
                store[k] = {"status": "ok", "zh_tw": r.data["summary_zh_tw"], "en": r.data["summary_en"], "provider": r.provider, "model": r.model, "guardrail": "passed"}
                n += 1
                if limit and n >= limit: break
    STORE.write_text(json.dumps(store, ensure_ascii=False, indent=1)); print("filled", n); return 0

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["fill"]); ap.add_argument("--limit", type=int)
    a = ap.parse_args(); sys.exit(fill(a.limit))
