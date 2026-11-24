import datetime as dt
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(os.environ.get("DISCLOSED_HOME", Path(__file__).resolve().parent.parent))
TZ = ZoneInfo("Asia/Taipei")
now = dt.datetime.now(TZ)
today = now.date().isoformat()
PY = str(ROOT / ".venv/bin/python")
LOG_PATH = ROOT / "data" / "logs" / f"daily_{today}.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
LIVE_PATH = ROOT / "picklog" / "live.jsonl"
STATUS_PATH = ROOT / "data" / "logs" / "daily_last_status.json"

SECRET_KEYS = [
    "MODEL_API_KEY", "GEMINI_API_KEY", "TIINGO_API_KEY", "FB_ACCESS_TOKEN",
    "TELEGRAM_BOT_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
]
SECRETS = [os.environ[k] for k in SECRET_KEYS if os.environ.get(k)]

def redact(s):
    out = s or ""
    for val in SECRETS:
        if val:
            out = out.replace(val, "[REDACTED]")
    out = re.sub(r"(MODEL_API_KEY|GEMINI_API_KEY|TIINGO_API_KEY)\s*[=:]\s*\S+", r"\1=[REDACTED]", out)
    return out

def ts():
    return dt.datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S %z")

log_f = open(LOG_PATH, "a", encoding="utf-8")

def log(msg):
    log_f.write(redact(msg))
    if not msg.endswith("\n"):
        log_f.write("\n")
    log_f.flush()

failed_steps = []
messages = []
extra = {}

def run_cmd(args, timeout):
    try:
        p = subprocess.run(
            args, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=timeout, env=os.environ.copy(),
        )
        out = redact(p.stdout or "")
        return p.returncode, out
    except subprocess.TimeoutExpired as e:
        partial = e.stdout
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", "replace")
        return 124, redact(partial or "") + ("\n" if partial else "") + f"FAILED: timed out after {timeout}s\n"
    except Exception as e:
        return 1, f"FAILED: {type(e).__name__}: {e}\n"

def run_step(name, args, timeout, after=None):
    log(f"===== {ts()} {name} =====")
    code, out = run_cmd(args, timeout)
    if out:
        log(out if out.endswith("\n") else out + "\n")
    if code != 0:
        failed_steps.append(name)
        messages.append(f"{name} exit={code}")
        tail = "\n".join(out.strip().splitlines()[-12:])
        if tail:
            messages.append(tail)
    if after:
        after(code, out)
    return code, out

def check_fetch(code, out):
    extra["fetch"] = [ln for ln in out.splitlines() if ln.startswith(("index:", "download:", "classify:"))]
    m = re.search(r"download: new=(\d+) already_present=(\d+) failed=(\d+)", out)
    if m and int(m.group(3)) > 0:
        if "fetch all" not in failed_steps:
            failed_steps.append("fetch all")
        messages.append("PTR PDF download failed=" + m.group(3))

def already_frozen(date):
    if not LIVE_PATH.exists():
        return False
    methods = set()
    for line in LIVE_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if e.get("pick_date") == date:
            methods.add(e.get("method") or ("backtest_best" if e.get("version") == "rules-v1" else "consensus"))
    return "consensus" in methods and "backtest_best" in methods

def live_tail():
    if not LIVE_PATH.exists():
        return {"n": 0, "seq": None, "last_date": None, "today": []}
    rows = [json.loads(l) for l in LIVE_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
    last = rows[-1] if rows else {}
    today_rows = []
    for e in rows:
        if e.get("pick_date") == today:
            today_rows.append({
                "seq": e.get("seq"),
                "method": e.get("method") or ("backtest_best" if e.get("version") == "rules-v1" else "consensus"),
                "hash": (e.get("hash") or "")[:16],
                "tickers": [p.get("ticker") for p in e.get("picks") or []],
            })
    return {"n": len(rows), "seq": last.get("seq"), "last_date": last.get("pick_date"), "today": today_rows}

def sqlite_meta():
    import sqlite3
    con = sqlite3.connect(str(ROOT / "data" / "disclosed.sqlite"))
    def n(q):
        return con.execute(q).fetchone()[0]
    scanned_ok = n("select count(*) from filings where kind='scanned' and meta_status='ok'")
    text_ok = n("select count(*) from filings where kind='text' and rule_status='ok'")
    need_scanned = [r[0] for r in con.execute(
        "select doc_id from filings where pdf_path is not null and kind='scanned' "
        "and (meta_status is null or meta_status like 'error%') order by doc_id"
    )]
    need_failed = [r[0] for r in con.execute(
        "select doc_id from filings where pdf_path is not null and kind!='scanned' "
        "and (rule_status is null or rule_status in ('fail','failed','error') "
        "or rule_status like 'fail%' or rule_status like 'error%') "
        "and (meta_status is null or meta_status like 'error%') order by doc_id"
    )]
    n_filings = n("select count(*) from filings")
    last_filing = con.execute("select max(filing_date) from filings").fetchone()[0]
    last_price = con.execute("select max(date) from prices where ticker='SPY'").fetchone()[0]
    con.close()
    return scanned_ok, text_ok, need_scanned, need_failed, n_filings, last_filing, last_price

def http_code():
    try:
        r = urllib.request.urlopen("http://127.0.0.1:8000/", timeout=5)
        return int(r.status)
    except Exception:
        return 0

run_step("fetch all", [PY, "-m", "disclosed.fetch", "all"], 600, check_fetch)
run_step("rule_parser", [PY, "-m", "disclosed.rule_parser"], 300)

scanned_ok, text_ok, need_scanned, need_failed, n_filings, last_filing, last_price = sqlite_meta()
need = list(dict.fromkeys(need_scanned + need_failed))
log(f"===== {ts()} meta_parser =====")
if not need:
    msg = f"skipped: no new scanned or failed filings (scanned meta ok={scanned_ok}; text rule ok={text_ok})"
    log(msg)
    extra["meta"] = msg
else:
    extra["meta"] = {"scanned": need_scanned, "failed": need_failed}
    args = [PY, "-m", "disclosed.meta_parser"]
    for d in need:
        args += ["--doc", str(d)]
    timeout = min(900, 180 + 120 * max(1, len(need)))
    run_step("meta_parser --doc " + " ".join(map(str, need)) + " (new scanned/failed only)", args, timeout)
    scanned_ok, text_ok, need_scanned, need_failed, n_filings, last_filing, last_price = sqlite_meta()
    leftover = need_scanned + need_failed
    if leftover:
        failed_steps.append("meta_parser")
        messages.append("unparsed filings remain: " + ", ".join(map(str, leftover)))

log(f"===== {ts()} prices classify + fetch =====")
code_c, out_c = run_cmd([PY, "-m", "disclosed.prices", "classify"], 180)
code_f, out_f = run_cmd([PY, "-m", "disclosed.prices", "fetch"], 900)
prices_out = (out_c + ("" if out_c.endswith("\n") or not out_c else "\n") + out_f)
if prices_out:
    log(prices_out if prices_out.endswith("\n") else prices_out + "\n")
extra["prices"] = [ln for ln in prices_out.splitlines() if "price_fetch status" in ln or ln.startswith("assets:")][-6:]
if code_c != 0 or code_f != 0:
    failed_steps.append("prices classify + fetch")
    messages.append(f"prices classify exit={code_c} fetch exit={code_f}")
    tail = "\n".join(prices_out.strip().splitlines()[-12:])
    if tail:
        messages.append(tail)
elif "price_fetch status:" not in prices_out:
    failed_steps.append("prices classify + fetch")
    messages.append("prices did not print status")

if already_frozen(today):
    log(f"===== {ts()} picks freeze =====")
    log(f"already frozen for {today}; skip freeze (append-only)")
    extra["freeze"] = {"already": True, **live_tail()}
else:
    def check_freeze(code, out):
        extra["freeze"] = {"already": False, "out": [ln for ln in out.splitlines() if ln.strip()][:20]}
        if code != 0:
            return
        info = live_tail()
        extra["freeze"].update(info)
        if not already_frozen(today):
            failed_steps.append("picks freeze")
            messages.append("freeze exited 0 but today's both methods are not in live.jsonl")
    run_step("picks freeze", [PY, "-m", "disclosed.picks", "freeze"], 180, check_freeze)

def check_verify(code, out):
    extra["verify"] = out.strip().splitlines()
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if code != 0 or not lines or any("False" in ln for ln in lines) or not any(ln.endswith("ok") or " True ok" in ln for ln in lines):
        if "picks verify" not in failed_steps:
            failed_steps.append("picks verify")
        if not any(m.startswith("verify") or "False" in m or "hash" in m.lower() for m in messages[-4:]):
            messages.append("hash chain verification failed")

run_step("picks verify", [PY, "-m", "disclosed.picks", "verify"], 180, check_verify)
run_step("score_picks", [PY, "-m", "disclosed.score_picks"], 180)

def check_export(code, out):
    extra["export"] = [ln for ln in out.splitlines() if ln.strip()][-6:]
    if code == 0 and "data.json" not in out:
        failed_steps.append("export_site")
        messages.append("export_site did not write data.json")

run_step("export_site", [PY, "-m", "disclosed.export_site"], 180, check_export)

log(f"===== {ts()} serve check =====")
if os.environ.get("DISCLOSED_SKIP_SERVE"):
    serve_msg = "serve skipped (DISCLOSED_SKIP_SERVE)"
    log(serve_msg)
else:
    code = http_code()
    if code == 200:
        serve_msg = "serve already running http=200"
        log(serve_msg)
    else:
        serve_log = open(ROOT / "data" / "serve.log", "a", encoding="utf-8")
        subprocess.Popen(
            [PY, "-m", "disclosed.serve", "--port", "8000"],
            cwd=str(ROOT), stdout=serve_log, stderr=subprocess.STDOUT, start_new_session=True, env=os.environ.copy(),
        )
        time_ok = False
        import time
        for _ in range(10):
            time.sleep(1)
            if http_code() == 200:
                time_ok = True
                break
        if time_ok:
            serve_msg = "serve started http=200"
            log(serve_msg)
        else:
            serve_msg = f"serve not responding (before={code}, after={http_code()})"
            log(serve_msg)
            failed_steps.append("serve check")
            messages.append(serve_msg)
extra["serve"] = serve_msg

scanned_ok, text_ok, need_scanned, need_failed, n_filings, last_filing, last_price = sqlite_meta()
info = live_tail()
ok = not failed_steps
if ok:
    log(f"===== {ts()} done =====")
else:
    log(f"===== {ts()} FAILED steps={failed_steps} =====")

status = {
    "ok": ok,
    "date": today,
    "runAt": now.isoformat(timespec="seconds"),
    "failedSteps": failed_steps,
    "messages": [redact(m) for m in messages],
    "liveSeq": info.get("seq"),
    "liveN": info.get("n"),
    "todayPicks": info.get("today"),
    "nFilings": n_filings,
    "lastFiling": last_filing,
    "lastPrice": last_price,
    "serve": extra.get("serve"),
    "fetch": extra.get("fetch"),
    "meta": extra.get("meta"),
    "prices": extra.get("prices"),
    "verify": extra.get("verify"),
    "export": extra.get("export"),
    "freeze": extra.get("freeze"),
    "log": str(LOG_PATH),
}
STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
log_f.close()
print("DISCLOSED_DAILY_STATUS:" + json.dumps(status, ensure_ascii=False), flush=True)
raise SystemExit(0 if ok else 1)
