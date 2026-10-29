"""Explainable daily 'featured picks' + append-only, hash-chained, timestamped log.

This is NOT a recommendation engine.
CURRENT (rules-v4-consensus-amount, from 2026-10-29): v3 below restricted to the consensus rule (>= 2 net buyers, buyers > sellers, net > 0).
PREVIOUS rules-v3-netamount (build_picks_v3): RANK = estimated NET BUY AMOUNT over 90 days = sum of purchase range midpoints minus
sale (incl. partial) midpoints across all members (open-ended top bracket -> lower bound, flagged); net <= 0 excluded.
Tie-breakers: net buyers, fewer net sellers, filing speed, liquidity. Liquidity (>= $1M avg 20d $vol) is an eligibility filter.
Displayed points (net_amount 70 log-scaled $1K..$10M, net_buyers 15, recency 15) are explanatory only.
PREVIOUS rules-v2-netbuyers (build_picks_v2): PRIMARY = distinct members who are NET BUYERS of the ticker over 90 days
(latest P/S in the window is a purchase; same logic as disclosed.consensus). Points: net_buyers 70 (14 each, cap 5), amount 15, recency 15.
Sort: net buyers desc, net sellers asc, score, then filing speed and liquidity as TIE-BREAKERS only; liquidity (>= $1M avg 20d $vol) is an eligibility filter.
LEGACY rules-v1 (kept in old log entries) ranked by additive rules (max 100 points):
  amount       25  size tier of the largest disclosed purchase (amounts are RANGES; we use the lower bound)
  multi_member 30  distinct members who disclosed buying the same ticker in the last 30 days (10 per extra member, cap 3 extra)
  delay        15  how quickly the trade was disclosed (days from transaction to filing): <=10d 15, <=30d 10, <=45d 5, later 0
  recency      20  how recently the filing became public: <=3d 20, <=7d 15, <=14d 10
  liquidity    10  20-day average dollar volume: >=$50M 10, >=$10M 7, >=$1M 4, else 0 (flagged illiquid)
Only information public on `pick_date` is used (filing_date <= pick_date, prices <= pick_date): no look-ahead.
Public date of a pick = the LATEST supporting filing date (when the whole signal was public); scoring starts the next trading day.
Modes: 'live' (frozen on the day it runs, cannot be backdated) and 'backtest' (retrospective replay, labelled as such, separate file)."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, math, re, statistics
from pathlib import Path
from . import config
from .db import connect
from .names import member_id, member_name
from .consensus import net_members, net_amount, MIN_BUYERS

LOGDIR = config.ROOT / "picklog"
VERSION = "rules-v4-consensus-amount"   # older v1/v2 entries stay untouched in the logs
TOP_N = 5
RECENT_DAYS = 14
MULTI_DAYS = 30
NET_DAYS = 90
MIN_ADV = 1e6
WEIGHTS = {"net_amount": 70, "net_buyers": 15, "recency": 15}   # explanatory points; RANK = net amount; delay & liquidity: tie-break / eligibility only
AMOUNT_TIERS_V2 = [(500001, 15), (250001, 13), (100001, 10), (50001, 7), (15001, 4), (1001, 2)]
AMOUNT_TIERS = [(500001, 25), (250001, 21), (100001, 17), (50001, 12), (15001, 7), (1001, 3)]
GENESIS = "0" * 64

def _days(a, b): return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days

def avg_dollar_volume(con, ticker, asof, n=20):
    rows = con.execute("SELECT close, volume FROM prices WHERE ticker=? AND date<=? ORDER BY date DESC LIMIT ?", (ticker, asof, n)).fetchall()
    rows = [r for r in rows if r[0] and r[1]]
    return statistics.fmean(r[0] * r[1] for r in rows) if len(rows) >= 10 else None

def build_picks_v2(con, pick_date, top_n=TOP_N):
    """LEGACY rules-v2-netbuyers (kept for reproducing picklog/backtest_v2_*.jsonl): rank by distinct NET-BUYING members (latest P/S in the 90d window is a purchase; same logic as the consensus board)."""
    pd_ = dt.date.fromisoformat(pick_date)
    lo_recent = (pd_ - dt.timedelta(days=RECENT_DAYS)).isoformat(); lo_net = (pd_ - dt.timedelta(days=NET_DAYS)).isoformat()
    pdf = dict(con.execute("SELECT doc_id, pdf_url FROM filings").fetchall())
    out = []
    for tk, t in net_members(con, lo_net, pick_date).items():
        buyers = [m for m in t["members"] if m["side"] == "buy"]; sellers = [m for m in t["members"] if m["side"] == "sell"]
        # eligibility: a stock (ST) purchase by a net buyer filed in the last RECENT_DAYS
        recent = [(m, x) for m in buyers for x in m["tx"] if x["ty"] == "P" and x["at"] == "ST" and x["fd"] >= lo_recent]
        if not recent: continue
        adv = avg_dollar_volume(con, tk, pick_date)
        if adv is None or adv < MIN_ADV: continue            # eligibility filter only, no points
        nb, ns = len(buyers), len(sellers)
        net_pts = min(nb, 5) * 14
        low = max((x["lo"] or 0) for _, x in recent)
        amt = next((p for lim, p in AMOUNT_TIERS_V2 if low >= lim), 0)
        pub = max(x["fd"] for _, x in recent); age = _days(pub, pick_date)
        rec = 15 if age <= 3 else 10 if age <= 7 else 5
        delays = [_days(x["td"], x["fd"]) for _, x in recent if x["td"]]
        dl = statistics.median(delays) if delays else None
        out.append({
            "ticker": tk, "name": t["name"], "score": net_pts + amt + rec,
            "components": {"net_buyers": {"points": net_pts, "max": 70, "value": f"{nb} net buyer(s), {ns} net seller(s) in {NET_DAYS}d"},
                           "amount": {"points": amt, "max": 15, "value": f"largest purchase lower bound ${low:,}"},
                           "recency": {"points": rec, "max": 15, "value": f"public {age} day(s) before pick date"}},
            "tiebreak": {"delay_median_days": dl, "avg_dollar_volume_20d": round(adv)},
            "public_date": pub, "members": [{"id": m["id"], "name": f"{m['name']} ({m['st']})"} for m in buyers], "n_members": nb, "n_sellers": ns,
            "sellers": [{"id": m["id"], "name": f"{m['name']} ({m['st']})"} for m in sellers],
            "tx": [{"doc_id": x["doc"], "idx": x["i"], "member": m["id"], "tx_date": x["td"], "filing_date": x["fd"], "amount": x["am"], "owner": x["ow"] or "self", "pdf_url": pdf.get(x["doc"])}
                   for m, x in sorted(recent, key=lambda mx: mx[1]["fd"], reverse=True)],
            "flags": (["late_filing_over_45d"] if dl is not None and dl > 45 else []) + (["has_net_sellers"] if ns else []),
            "reasons_en": reasons(nb, ns, low, dl, age, adv, "en"), "reasons_zh": reasons(nb, ns, low, dl, age, adv, "zh"),
            # PLACEHOLDER: filled later by the Meta/MAGI explainer (python -m disclosed.summaries fill). Never fake text here.
            "ai_summary": {"status": "pending_meta_key", "zh_tw": None, "en": None},
        })
    # primary: net buyers; then fewer net sellers; then score (amount+recency); tie-breakers: faster filing, higher liquidity
    out.sort(key=lambda p: (-p["n_members"], p["n_sellers"], -p["score"], p["tiebreak"]["delay_median_days"] if p["tiebreak"]["delay_median_days"] is not None else 999, -p["tiebreak"]["avg_dollar_volume_20d"], p["ticker"]))
    return out[:top_n]

def fmt_usd(v):
    a = abs(v); s = f"${a/1e6:.1f}M" if a >= 1e6 else f"${a/1e3:.0f}K" if a >= 1e3 else f"${a:,.0f}"
    return ("-" if v < 0 else "") + s

def build_picks_v3(con, pick_date, top_n=TOP_N, consensus_rule=False):
    """rules-v3-netamount (consensus_rule=True -> rules-v4-consensus-amount): rank by ESTIMATED NET BUY AMOUNT over NET_DAYS (purchase range midpoints minus sale midpoints, all members;
    same dedupe as disclosed.consensus). Eligible: net > 0, a stock purchase filed in the last RECENT_DAYS, avg 20d $ volume >= MIN_ADV."""
    pd_ = dt.date.fromisoformat(pick_date)
    lo_recent = (pd_ - dt.timedelta(days=RECENT_DAYS)).isoformat(); lo_net = (pd_ - dt.timedelta(days=NET_DAYS)).isoformat()
    pdf = dict(con.execute("SELECT doc_id, pdf_url FROM filings").fetchall())
    out = []
    for tk, t in net_members(con, lo_net, pick_date).items():
        na = net_amount(t["members"])
        if na["net"] <= 0: continue
        recent = [(m, x) for m in t["members"] for x in m["tx"] if x["ty"] == "P" and x["at"] == "ST" and x["fd"] >= lo_recent]
        if not recent: continue
        adv = avg_dollar_volume(con, tk, pick_date)
        if adv is None or adv < MIN_ADV: continue            # eligibility filter only, no points
        buyers = [m for m in t["members"] if m["side"] == "buy"]; sellers = [m for m in t["members"] if m["side"] == "sell"]
        nb, ns = len(buyers), len(sellers)
        if consensus_rule and not (nb >= MIN_BUYERS and nb > ns): continue    # v4: >= 2 net buyers and buyers > sellers (net > 0 checked above)
        amt_pts = round(max(0, min(1, (math.log10(na["net"]) - 3) / 4)) * 70)     # $1K -> 0, $10M+ -> 70 (log scale)
        nb_pts = min(nb, 3) * 5
        pub = max(x["fd"] for _, x in recent); age = _days(pub, pick_date)
        rec = 15 if age <= 3 else 10 if age <= 7 else 5
        delays = [_days(x["td"], x["fd"]) for _, x in recent if x["td"]]
        dl = statistics.median(delays) if delays else None
        flags = (["open_ended_bracket_lower_bound_used"] if na["open_ended"] else []) + (["late_filing_over_45d"] if dl is not None and dl > 45 else []) + (["has_net_sellers"] if ns else [])
        if na["conc"]: flags.append("concentrated_one_member")
        out.append({
            "ticker": tk, "name": t["name"], "score": amt_pts + nb_pts + rec,
            "net_amount": {k: na[k] for k in ("net", "net_min", "net_max", "buy_amt", "open_ended", "conc")},
            "components": {"net_amount": {"points": amt_pts, "max": 70, "value": f"est. net buy {fmt_usd(na['net'])} (range {fmt_usd(na['net_min'])}..{fmt_usd(na['net_max'])}) in {NET_DAYS}d"},
                           "net_buyers": {"points": nb_pts, "max": 15, "value": f"{nb} net buyer(s), {ns} net seller(s)"},
                           "recency": {"points": rec, "max": 15, "value": f"public {age} day(s) before pick date"}},
            "tiebreak": {"delay_median_days": dl, "avg_dollar_volume_20d": round(adv)},
            "public_date": pub, "members": [{"id": m["id"], "name": f"{m['name']} ({m['st']})"} for m in buyers], "n_members": nb, "n_sellers": ns,
            "sellers": [{"id": m["id"], "name": f"{m['name']} ({m['st']})"} for m in sellers],
            "tx": [{"doc_id": x["doc"], "idx": x["i"], "member": m["id"], "tx_date": x["td"], "filing_date": x["fd"], "amount": x["am"], "owner": x["ow"] or "self", "pdf_url": pdf.get(x["doc"])}
                   for m, x in sorted(recent, key=lambda mx: mx[1]["fd"], reverse=True)],
            "flags": flags,
            "reasons_en": reasons_v3(na, nb, ns, dl, age, "en"), "reasons_zh": reasons_v3(na, nb, ns, dl, age, "zh"),
            # PLACEHOLDER: filled later by the Meta/MAGI explainer (python -m disclosed.summaries fill). Never fake text here.
            "ai_summary": {"status": "pending_meta_key", "zh_tw": None, "en": None},
        })
    # primary: estimated net buy amount; tie-breakers: net buyers, fewer sellers, faster filing, liquidity
    out.sort(key=lambda p: (-p["net_amount"]["net"], -p["n_members"], p["n_sellers"], p["tiebreak"]["delay_median_days"] if p["tiebreak"]["delay_median_days"] is not None else 999, -p["tiebreak"]["avg_dollar_volume_20d"], p["ticker"]))
    return out[:top_n]

def build_picks(con, pick_date, top_n=TOP_N):
    """rules-v4-consensus-amount: same as v3 (rank by est. net buy amount, liquidity filter) but only tickers meeting the
    consensus rule of the home-page board: >= 2 net buyers AND net buyers > net sellers AND est. net amount > 0."""
    return build_picks_v3(con, pick_date, top_n, consensus_rule=True)

def reasons_v3(na, nb, ns, dl, age, lang):
    rng = f"{fmt_usd(na['net_min'])} ~ {fmt_usd(na['net_max'])}"
    if lang == "en":
        r = [f"estimated net buy ~{fmt_usd(na['net'])} over the last {NET_DAYS} days (range {rng}; midpoints of disclosed ranges, purchases minus sales)",
             f"{nb} member(s) net buying, {ns} net selling", f"filing public {age} day(s) before this list"]
        if na["conc"]: r.append(f"{na['conc']['share']:.0%} of the purchase amount comes from {na['conc']['name']}")
        if na["open_ended"]: r.append("includes an open-ended top bracket; its lower bound was used")
        if dl is not None: r.append(f"disclosed a median of {dl:g} days after the trade (legal limit: 45)")
    else:
        r = [f"近 {NET_DAYS} 天估計淨買進約 {fmt_usd(na['net'])}（區間 {rng}；以申報金額區間中間值估算，買進減賣出）",
             f"買進 {nb} 位議員、賣出 {ns} 位", f"申報於本榜單前 {age} 天公開"]
        if na["conc"]: r.append(f"買進金額的 {na['conc']['share']:.0%} 來自 {na['conc']['name']}")
        if na["open_ended"]: r.append("含無上限的最高級距，以下限計算")
        if dl is not None: r.append(f"交易後中位數 {dl:g} 天才申報（法定上限 45 天）")
    return r

def reasons(nb, ns, low, dl, age, adv, lang):
    if lang == "en":
        r = [f"{nb} member(s) are net buyers over the last {NET_DAYS} days" + (f"; {ns} net seller(s)" if ns else "; no net sellers"),
             f"largest recent purchase in the ${low:,}+ range (amounts are ranges)", f"filing public {age} day(s) before this list"]
        if dl is not None: r.append(f"disclosed a median of {dl:g} days after the trade (legal limit: 45)")
    else:
        r = [f"近 {NET_DAYS} 天內有 {nb} 位議員淨買進" + (f"、{ns} 位淨賣出" if ns else "，無人淨賣出"),
             f"近期最大單筆買進區間下限為 ${low:,}（申報金額為區間）", f"申報於本榜單前 {age} 天公開"]
        if dl is not None: r.append(f"交易後中位數 {dl:g} 天才申報（法定上限 45 天）")
    return r

# ---------- rules-v1 (restored verbatim logic; method "backtest_best") ----------
V1_WEIGHTS = {"amount": 25, "multi_member": 30, "delay": 15, "recency": 20, "liquidity": 10}
AMOUNT_TIERS = [(500001, 25), (250001, 21), (100001, 17), (50001, 12), (15001, 7), (1001, 3)]

def build_picks_v1(con, pick_date, top_n=TOP_N):
    lo_recent = (dt.date.fromisoformat(pick_date) - dt.timedelta(days=RECENT_DAYS)).isoformat()
    lo_multi = (dt.date.fromisoformat(pick_date) - dt.timedelta(days=MULTI_DAYS)).isoformat()
    rows = con.execute("""SELECT t.*, f.filing_date, f.last, f.first, f.suffix, f.state_dst, f.pdf_url, a.sample_name
        FROM tx t JOIN filings f USING(doc_id) JOIN assets a ON a.ticker=t.ticker AND a.eligible=1
        WHERE t.tx_type='P' AND t.asset_type='ST' AND f.filing_date<=? AND f.filing_date>=?""", (pick_date, lo_multi)).fetchall()
    by = {}
    for r in rows: by.setdefault(r["ticker"], []).append(r)
    out = []
    for tk, rs in by.items():
        recent = [r for r in rs if r["filing_date"] >= lo_recent]
        if not recent: continue
        members = sorted({member_id(r) for r in rs})
        mnames = {member_id(r): member_name(r) + f" ({r['state_dst']})" for r in rs}
        low = max((r["amount_low"] or 0) for r in recent)
        amt = next((p for lim, p in AMOUNT_TIERS if low >= lim), 0)
        nm = len(members); multi = min(nm - 1, 3) * 10
        delays = [_days(r["tx_date"], r["filing_date"]) for r in recent if r["tx_date"]]
        dl = statistics.median(delays) if delays else None
        dpt = 0 if dl is None else 15 if dl <= 10 else 10 if dl <= 30 else 5 if dl <= 45 else 0
        pub = max(r["filing_date"] for r in recent); age = _days(pub, pick_date)
        rec = 20 if age <= 3 else 15 if age <= 7 else 10
        adv = avg_dollar_volume(con, tk, pick_date)
        liq = 0 if adv is None else 10 if adv >= 50e6 else 7 if adv >= 10e6 else 4 if adv >= 1e6 else 0
        total = amt + multi + dpt + rec + liq
        out.append({
            "ticker": tk, "name": re.sub(r"\s*\[[A-Z0-9]{2}\]\s*$", "", rs[0]["sample_name"] or ""), "score": total,
            "components": {"amount": {"points": amt, "max": 25, "value": f"largest purchase lower bound ${low:,}"},
                           "multi_member": {"points": multi, "max": 30, "value": f"{nm} member(s) in {MULTI_DAYS}d"},
                           "delay": {"points": dpt, "max": 15, "value": None if dl is None else f"median {dl:g} days tx->filing"},
                           "recency": {"points": rec, "max": 20, "value": f"public {age} day(s) before pick date"},
                           "liquidity": {"points": liq, "max": 10, "value": None if adv is None else f"avg 20d $ volume {adv/1e6:,.1f}M"}},
            "public_date": pub, "members": [{"id": m, "name": mnames[m]} for m in members], "n_members": nm,
            "tx": [{"doc_id": r["doc_id"], "idx": r["idx"], "member": member_id(r), "tx_date": r["tx_date"], "filing_date": r["filing_date"],
                    "amount": r["amount_text"], "owner": r["owner"] or "self", "pdf_url": r["pdf_url"]} for r in recent],
            "flags": (["illiquid_or_no_volume_data"] if liq == 0 else []) + (["late_filing_over_45d"] if dl is not None and dl > 45 else []),
            "reasons_en": reasons_v1(nm, low, dl, age, adv, "en"), "reasons_zh": reasons_v1(nm, low, dl, age, adv, "zh"),
            "ai_summary": {"status": "pending_meta_key", "zh_tw": None, "en": None},
        })
    out.sort(key=lambda p: (-p["score"], -p["n_members"], p["ticker"]))
    return out[:top_n]

def reasons_v1(nm, low, dl, age, adv, lang):
    if lang == "en":
        r = [f"{nm} member(s) disclosed buying it in the last {MULTI_DAYS} days", f"largest purchase in the ${low:,}+ range (amounts are ranges)",
             f"filing public {age} day(s) before this list"]
        if dl is not None: r.append(f"disclosed a median of {dl:g} days after the trade (legal limit: 45)")
        if adv: r.append(f"average daily dollar volume about ${adv/1e6:,.1f}M")
    else:
        r = [f"近 {MULTI_DAYS} 天內有 {nm} 位議員申報買進", f"最大單筆買進區間下限為 ${low:,}（申報金額為區間）", f"申報於本榜單前 {age} 天公開"]
        if dl is not None: r.append(f"交易後中位數 {dl:g} 天才申報（法定上限 45 天）")
        if adv: r.append(f"近 20 日平均成交金額約 ${adv/1e6:,.1f}M")
    return r

# Two published methods, frozen side by side each day (entries tagged "method"). Legacy live entries without "method" are rules-v1.
METHODS = {
    "consensus": {"version": "rules-v4-consensus-amount", "build": lambda con, d: build_picks(con, d),
                  "params": lambda: {"weights": WEIGHTS, "top_n": TOP_N, "recent_days": RECENT_DAYS, "net_days": NET_DAYS, "min_adv": MIN_ADV,
                                     "eligibility": ">=2 net buyers, net buyers > net sellers, est. net > 0, avg 20d $vol >= MIN_ADV",
                                     "sort": "est. net buy amount desc, net_buyers desc, net_sellers asc, filing delay asc, liquidity desc",
                                     "amount_method": "range midpoints; open-ended top bracket uses lower bound"},
                  "backtest_file": "backtest_v4_rules-v4-consensus-amount.jsonl"},
    "backtest_best": {"version": "rules-v1", "build": lambda con, d: build_picks_v1(con, d),
                      "params": lambda: {"weights": V1_WEIGHTS, "top_n": TOP_N, "recent_days": RECENT_DAYS, "multi_days": MULTI_DAYS},
                      "backtest_file": "backtest_v1_rules-v1.jsonl"},
}
DEFAULT_METHOD = "consensus"
def entry_method(e): return e.get("method") or ("backtest_best" if e.get("version", "rules-v1") == "rules-v1" else "consensus")

# ---------- append-only hash-chained log ----------
def _canon(o): return json.dumps(o, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
def _read(path: Path):
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()] if path.exists() else []

def verify(path: Path):
    prev = GENESIS
    for i, e in enumerate(_read(path)):
        h = e.pop("hash")
        if e["prev_hash"] != prev: return False, f"line {i+1}: prev_hash mismatch"
        if hashlib.sha256(_canon(e).encode()).hexdigest() != h: return False, f"line {i+1}: content hash mismatch"
        prev = h
    return True, "ok"

def append(path: Path, entry: dict):
    ok, msg = verify(path)
    if not ok: raise SystemExit(f"refusing to append: chain broken ({msg})")
    ents = _read(path)
    same = [e for e in ents if entry_method(e) == entry_method(entry)]
    if same and entry["pick_date"] <= same[-1]["pick_date"]:
        raise SystemExit(f"refusing to append: pick_date {entry['pick_date']} <= last logged {same[-1]['pick_date']} for method {entry_method(entry)} (append-only, one entry per method per day)")
    if ents and entry["pick_date"] < ents[-1]["pick_date"]:
        raise SystemExit(f"refusing to append: pick_date {entry['pick_date']} is before the last logged entry {ents[-1]['pick_date']} (no backdating)")
    entry["seq"] = len(ents) + 1; entry["prev_hash"] = ents[-1]["hash"] if ents else GENESIS
    entry["hash"] = hashlib.sha256(_canon(entry).encode()).hexdigest()
    path.parent.mkdir(exist_ok=True)
    with path.open("a") as f: f.write(_canon(entry) + "\n")
    return entry

def make_entry(con, pick_date, mode, method=DEFAULT_METHOD):
    M = METHODS[method]
    last_px = con.execute("SELECT max(date) FROM prices WHERE ticker='SPY'").fetchone()[0]
    return {"mode": mode, "method": method, "pick_date": pick_date, "frozen_at": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).isoformat(timespec="seconds"),
            "frozen_tz_note": "Asia/Taipei (UTC+8)", "data_as_of_prices": last_px, "version": M["version"],
            "params": M["params"](), "picks": M["build"](con, pick_date)}

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze", help="freeze today's picks for BOTH methods into picklog/live.jsonl"); f.add_argument("--date", help="default: today (Asia/Taipei)")
    f.add_argument("--method", choices=[*METHODS, "all"], default="all")
    b = sub.add_parser("backtest", help="rebuild picklog/backtest_<version>.jsonl by point-in-time replay (labelled retrospective)")
    b.add_argument("--start", default="2026-02-02"); b.add_argument("--method", choices=[*METHODS, "all"], default="all")
    sub.add_parser("verify")
    a = ap.parse_args(argv); con = connect()
    if a.cmd == "freeze":
        d = a.date or dt.date.today().isoformat()
        for m in (METHODS if a.method == "all" else [a.method]):
            e = append(LOGDIR / "live.jsonl", make_entry(con, d, "live", m))
            print(f"[{m} / {e['version']}] frozen seq={e['seq']} date={d} hash={e['hash'][:16]}…"); [print(f"  {p['ticker']:6} score={p['score']} members={p['n_members']}") for p in e["picks"]]
    elif a.cmd == "backtest":
        days = [r[0] for r in con.execute("SELECT date FROM prices WHERE ticker='SPY' AND date>=? ORDER BY date", (a.start,))]
        for m in (METHODS if a.method == "all" else [a.method]):
            p = LOGDIR / METHODS[m]["backtest_file"]; p.unlink(missing_ok=True); n = 0
            for d in days:
                e = make_entry(con, d, "backtest", m); e["frozen_at"] = None
                e["note"] = f"[{e['version']}] retrospective replay using only information public on pick_date; NOT a live frozen pick"
                if e["picks"]: append(p, e); n += 1
            print(f"[{m}] backtest entries: {n} over {len(days)} trading days -> {p}")
    elif a.cmd == "verify":
        for n in ["live", "backtest"] + [M["backtest_file"][:-6] for M in METHODS.values()]:
            p = LOGDIR / f"{n}.jsonl"
            if p.exists(): print(n, len(_read(p)), "entries:", *verify(p))

if __name__ == "__main__":
    main()
