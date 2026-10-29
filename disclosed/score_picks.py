"""Score logged picks against SPY. Safe to run any day: horizons not yet reached stay 'pending' (insufficient_data), never guessed.
Primary: from the pick's public date (next trading day close, as requested). Secondary: from the freeze/pick date (what a follower of the
list could actually have done). Results go to data/picks_scored.json; the log itself is never modified."""
from __future__ import annotations
import json
from . import config
from .db import connect
from .performance import HORIZONS, load_series, measure, summarize, track_record
from .picks import LOGDIR, _read, verify, METHODS, entry_method

OUT = config.DATA / "picks_scored.json"

def _score_entries(con, entries, sd, sp, cache):
    events = {}   # unique (ticker, public_date): identical entry => count once
    for e in entries:
        for p in e["picks"]:
            k = (p["ticker"], p["public_date"])
            if k in events: continue
            if p["ticker"] not in cache: cache[p["ticker"]] = load_series(con, p["ticker"])
            td, tp = cache[p["ticker"]]
            ev = {"ticker": p["ticker"], "first_pick_date": e["pick_date"], "public_date": p["public_date"], "score": p["score"], "n_members": p["n_members"], "from_public": {}, "from_pick_date": {}}
            for h in HORIZONS:
                ev["from_public"][h] = measure(p["public_date"], td, tp, sd, sp, h)
                ev["from_pick_date"][h] = measure(e["pick_date"], td, tp, sd, sp, h)
            events[k] = ev
    summ = {}
    for basis in ("from_public", "from_pick_date"):
        summ[basis] = {}
        for h in HORIZONS:
            vals = [v[basis][h]["excess"] for v in events.values() if v[basis][h]["status"] == "ok"]
            s = summarize(vals); s["pending"] = sum(v[basis][h]["status"] == "insufficient_data" for v in events.values())
            s["no_prices"] = sum(v[basis][h]["status"] == "no_prices" for v in events.values())
            summ[basis][h] = s
    return {"n_events": len(events), "n_days": len(entries), "summary": summ, "events": list(events.values())}

def overlap_entries(a, b):
    """Per pick_date, picks whose ticker appears in BOTH methods' lists (taken from the consensus-method entry)."""
    bm = {e["pick_date"]: {p["ticker"] for p in e["picks"]} for e in b}
    out = []
    for e in a:
        both = [p for p in e["picks"] if p["ticker"] in bm.get(e["pick_date"], set())]
        if both: out.append({**e, "picks": both})
    return out

def score(con=None):
    con = con or connect()
    sd, sp = load_series(con, "SPY"); cache = {}
    res = {"generated_at_prices": sd[-1], "modes": {}}
    live_path = LOGDIR / "live.jsonl"; live = _read(live_path); lok = verify(live_path) if live_path.exists() else (True, "empty")
    sets = {}
    for m, M in METHODS.items():
        bp = LOGDIR / M["backtest_file"]
        sets[f"backtest_{m}"] = (_read(bp), verify(bp) if bp.exists() else (False, "missing"), M["version"])
        sets[f"live_{m}"] = ([e for e in live if entry_method(e) == m], lok, M["version"])
    sets["backtest_overlap"] = (overlap_entries(sets["backtest_consensus"][0], sets["backtest_backtest_best"][0]), (True, "derived"), "overlap")
    sets["live_overlap"] = (overlap_entries(sets["live_consensus"][0], sets["live_backtest_best"][0]), (True, "derived"), "overlap")
    for k, (ents, (ok, msg), ver) in sets.items():
        res["modes"][k] = {"chain_ok": ok, "chain_msg": msg, "version": ver, **_score_entries(con, ents, sd, sp, cache)}
    res["baseline_all_purchases"] = {h: s for h, s in track_record(con, "P").items()}
    OUT.write_text(json.dumps(res, indent=1, default=str))
    return res

def main():
    r = score()
    for mode, m in r["modes"].items():
        print(f"[{mode}] chain={m['chain_msg']} unique events={m['n_events']}")
        for basis, d in m["summary"].items():
            for h, s in d.items():
                if s["n"]: print(f"  {basis:14} {h:>3}d n={s['n']:4d} win={s['win_rate']:.1%} mean_excess={s['mean_excess']:+.2%} median={s['median_excess']:+.2%} pending={s['pending']}{'  (n<10: insufficient)' if s['insufficient'] else ''}")
                else: print(f"  {basis:14} {h:>3}d n=0 pending={s['pending']} (insufficient data)")
    print("baseline (all purchases):", {h: (s['n'], round(s['win_rate'], 3) if s['n'] else None) for h, s in r["baseline_all_purchases"].items()})

if __name__ == "__main__":
    main()
