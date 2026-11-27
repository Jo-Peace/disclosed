#!/bin/bash
set +x
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
cd "$ROOT"
export PATH="/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin"
mkdir -p data/logs
today="$(date +%F)"
exec >>"data/logs/daily_${today}.log" 2>&1

fail() {
    printf '%s ERROR: %s\n' "$(date '+%F %T')" "$1" >&2
    exit 1
}

# Hold the lock on the shell's open descriptor until the wrapper exits.
exec 9>>data/logs/daily.lock
python="$ROOT/.venv/bin/python"
"$python" -c 'import fcntl; fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)' ||
    fail "Could not acquire the daily updater lock."
[[ "$(git symbolic-ref --quiet --short HEAD)" == main ]] ||
    fail "The updater requires the main branch."

printf '%s Starting daily refresh\n' "$(date '+%F %T')"
(
    set -a
    source "$ROOT/.env" >/dev/null 2>&1 || fail "Could not load .env."
    set +a
    export DISCLOSED_HOME="$ROOT" DISCLOSED_SKIP_SERVE=1
    "$python" "$ROOT/data/_daily_run.py" || fail "Daily pipeline failed."

    # The verifier can print False and still exit zero. Require a valid live
    # chain and a successful result for every other chain it reports.
    verification="$("$python" -m disclosed.picks verify)" || fail "Verifier command failed."
    printf '%s\n' "$verification"
    awk '/^live / {live = 1} !/ entries: True ok$/ {bad = 1} END {exit (!live || bad)}' \
        <<<"$verification" || fail "Pick log verification failed."
)

files=(
    picklog/live.jsonl
    data/picks_scored.json
    site/data.json
    site/prices.json
    data/llm_ledger.jsonl
)
git add -- "${files[@]}"
if git diff --cached --quiet -- "${files[@]}"; then
    printf '%s No daily data changes to publish.\n' "$(date '+%F %T')"
    exit 0
fi

git diff --cached --numstat -- picklog/live.jsonl |
    awk '$2 != "0" {exit 1}' || fail "The live pick log contains a non-append change."

# An explicit path list keeps unrelated staged work out of the daily commit.
git commit --only -m "$today daily picks and data refresh" -- "${files[@]}"
git push origin main || fail "Push to origin/main failed. The daily commit remains on local main."
printf '%s Daily refresh pushed.\n' "$(date '+%F %T')"
