# PROGRESS (Turn 3 notes; updated 2026-10-29 ~11:00 Taipei)
DONE
- API verified live (Responses API, json_schema, PDF input_file base64, detail high). Model muse-spark-1.3. Cache data/llm_cache, ledger data/llm_ledger.jsonl.
- rule_parser bug fixed (row-id prefix before owner code, 17 rows/13 docs) -> rule rows re-parsed (3597 rows).
- Meta parse ALL 384 text PDFs (0 fail) + ALL 53 scanned (0 fail, 5539 rows / 48 docs with tx, 5 docs 'nothing to report'). compare: data/compare_report.txt (3577/3597 = 99.44% full-row).
- View `tx` = canonical rows (text->rule, scanned->meta). prices/performance/picks/export_site read from `tx`.
- tickermap.py: scanned name->ticker via Yahoo search (strict), 748 names ok, rows flagged ticker_inferred.
- prices re-fetched, performance recomputed (4872 events), backtest regenerated, score_picks done. live.jsonl UNCHANGED (verified cmp).
- summaries.py guardrails + validate(); 5 AI summaries filled (all verified vs facts).
- export_site.py + site/app.js updated for MAGI/Meta badges (not yet re-exported).
- magi.py: batching, sampling big scanned docs (2 blocks x25 rows), consensus rule: >=1 approve & 0 reject -> approved_with_caveat.
TODO
1. wait MAGI `--set all` (pid 247181; log data/magi_run.log, resume-safe), then rerun `python -m disclosed.magi --set all` once (new disagree docs w/ cap_gains)
2. export_site, restart serve (port 8000), screenshots (scripts_screens.sh, MEMBER=...), 
3. MAGI stats + sample review of MAGI explainer text, README update, key-leak grep, tests, final report (zh-TW)

## 2026-10-29 11:10 update
- MAGI done (2 passes): 96 docs/1790 rows; approved 446, caveat 1307, needs_review 34, rejected 3.
- Site re-exported (9136 tx, 437 filings), server restarted on :8000, screens/ regenerated (01–09).
- README results section added; key-leak scan 0 files; pytest 16 passed. Ledger $26.75.
- Remaining: demo video script, submission repo, daily live-pick freeze routine.

## 2026-10-29 14:30 update — 議員共識榜 / Congress Consensus
- New disclosed/consensus.py (`python -m disclosed.consensus` prints top10): distinct members buying (P) per ticker, filing_date within 90/30d of latest filing (2026-10-22); per doc rule rows if any else meta; assets.eligible=1; member key = normalized name.
- names.py: normalize_name() strips Mr/Mrs/Ms/Hon/Dr/MD/FACS, collapses duplicate adjacent tokens, alias Tracey Robert Mann -> Tracey Mann; used by member_name (all site names) + JS nn() for frozen pick names.
- export_site adds data.consensus; app.js section at top of home (tabs 90/30, bars, <details> expand, TSM 台灣 tag, heavy-trader note, disclaimer, zh/en); style.css responsive.
- Hash params: #/?cw=30, #/?open=1 (expand row 1). Screens 10_consensus_zh/en, 11_consensus_30d_zh, 12_consensus_mobile_zh added; 01–09 regenerated.

## 2026-10-29 ~14:40 update — net buy/sell consensus + picks rules-v2-netbuyers
- consensus.py: per member×ticker all P/S/S(partial) in window (rule rows preferred else meta, normalized-name key); latest tx (tx_date, fallback filing_date) decides net buyer/seller. Rank: net buyers desc, fewer sellers, more purchases, alpha; 0-buyer tickers dropped. net_members(con, since, until) reusable point-in-time. Heavy note counts net-buyer rows only.
- Site: split bar (green buy / red sell), 「買進 N 位 · 賣出 M 位」, expanded rows list buys+sells with 買/賣/部分賣出 tags, 淨買進/淨賣出 + 已賣出 badges; disclaimer 依申報公開日同步買進與賣出紀錄，非投資建議.
- picks.py VERSION rules-v2-netbuyers: primary = 90d net buyers (14 pts each, cap 70), amount 15, recency 15; sort net buyers, fewer sellers, score, then filing delay & liquidity tie-breakers; ADV >= $1M eligibility. live.jsonl untouched (1 rules-v1 entry, chain ok). backtest.jsonl regenerated with v2 (labelled in note/version); old v1 kept at picklog/backtest_v1_rules-v1.jsonl, scores data/picks_scored_v1.json vs _v2.json.
- Backtest from_public v1→v2: 5d +0.0%/46.9% (n226) → +0.90%/51.1% (n174); 30d +2.53%/52.5% (n200) → +1.98%/48.7% (n154); 90d +6.06%/50.4% (n123) → +2.02%/50.0% (n100).
- Site copy (about + backtest note + version label) updated zh/en. tests/test_consensus_net.py added (23 passed). Screens 01–12 regenerated.

## 2026-10-29 ~15:00 update — rank by estimated net buy AMOUNT (rules-v3-netamount)
- consensus.py: net_amount(): sum purchase range midpoints − sale (incl. partial) midpoints across all members; net_min/net_max from range bounds; open-ended bracket ('Over $X') uses lower bound + open_ended flag; conc = one member > 60% of purchase amount. rank(): net amount desc, drop net <= 0, tie: net buyers, fewer sellers, alpha. rank_by_count() keeps v2 logic. Only ST/EF rows now (options OP excluded — Pelosi BE/INTC had OP rows duplicating stock amounts).
- Site: 「估計淨買進 約 $X」 + range + 「買進 N 位 · 賣出 M 位」, bar = net amount, 「主要來自 XX」 tag, open-ended tag, disclaimer 金額依申報區間中間值估算，申報不含持股數 (zh/en); about + backtest note updated for v3.
- picks.py VERSION rules-v3-netamount (build_picks_v2 kept). Live log untouched (sha256 0cc282c9…). Backtests: picklog/backtest_v1_rules-v1.jsonl, backtest_v2_rules-v2-netbuyers.jsonl, backtest_v3_rules-v3-netamount.jsonl (= current backtest.jsonl); scores data/picks_scored_v1/v2/v3.json.
- Backtest from_public mean/median/win: 30d v1 +2.53/+1.12/52.5% (n200), v2 +1.98/−0.63/48.7% (n154), v3 +2.23/−0.06/49.7% (n159); 90d v1 +6.06/+0.94/50.4% (n123), v2 +2.02/−0.13/50.0% (n100), v3 +3.79/−0.99/47.4% (n95).
- Tests 27 passed (net amount, open bracket, ranking, legacy count rank). Screens 01–12 regenerated.

## 2026-10-29 ~15:20 update — hybrid board + rules-v4-consensus-amount
- consensus.py: is_consensus (>=2 net buyers, buyers > sellers, net > 0), split_rank -> data.consensus[w].rows (「多位議員共識」, top 10 by est. net amount, tie: buyers) + .big (「大額單筆 / Big single-member buys」: net > 0 but not consensus, top 8). Options still excluded (ST/EF only).
- Site: two sub-sections under 議員共識榜 with shared 90/30 tabs; big section compact rows with buyer name. Copy (about + backtest note) updated zh/en for v4.
- picks.py VERSION rules-v4-consensus-amount (= build_picks_v3 with consensus rule; liquidity filter kept). live.jsonl untouched (sha256 0cc282c9…). Backtests v1–v4 kept in picklog/backtest_v*_*.jsonl (current backtest.jsonl = v4); scores data/picks_scored_v1..v4.json.
- Backtest from_public mean/median/win (n): 30d v1 +2.53/+1.12/52.5 (200), v2 +1.98/−0.63/48.7 (154), v3 +2.23/−0.06/49.7 (159), v4 +1.27/−2.07/43.6 (149); 90d v1 +6.06/+0.94/50.4 (123), v2 +2.02/−0.13/50.0 (100), v3 +3.79/−0.99/47.4 (95), v4 +4.11/−2.13/45.1 (91).
- Screens 01–12 regenerated + 13_big_single_zh/en (cropped). Tests 28 passed.

## 2026-10-29 — Two switchable methods (議員共識 v4 / 回測最佳 v1)
- picks.py: restored `build_picks_v1` (rules-v1). It reproduces backtest_v1_rules-v1.jsonl exactly: 186/186 days, same tickers. Added `METHODS` = consensus (rules-v4-consensus-amount, default) and backtest_best (rules-v1).
- Entries are tagged `method`. Legacy untagged entries count as backtest_best (v1).
- `append` now enforces one entry per method per day and never allows backdating. Hash chain unchanged.
- `freeze` writes both methods by default (`--method` to pick one). `backtest` writes `picklog/backtest_<v>.jsonl` per method.
- live.jsonl not modified. It is still 1 entry; sha256 0cc282c9… is unchanged. Today's entries were NOT frozen manually; the next daily freeze writes both.
- score_picks.py scores these modes: backtest_/live_ × consensus/backtest_best, plus an overlap subset (same pick_date, ticker in both lists).
- Site:
  - Segmented toggle on the picks section and on Track record. `?m=v1` selects backtest-best; the default is consensus.
  - One-line description plus backtest stats for each method.
  - 雙重入選 / "In both" badge.
  - v1 vs v4 vs overlap comparison table.
  - Methodology now explains both methods and notes v2/v3 as dropped. Consensus board unchanged.
- Tests: tests/test_methods.py (per-method chain and overlap). 30 pass.
- Screens: 14_picks_toggle_zh/en, 15_trackrecord_compare_zh.
- Backtest, from_public, mean/median/win (n):
  - v4 5d +0.78/+0.03/50.3 (165); 30d +1.27/−2.07/43.6 (149); 90d +4.11/−2.13/45.1 (91)
  - v1 5d −0.01/−0.29/46.9 (226); 30d +2.53/+1.12/52.5 (200); 90d +6.06/+0.94/50.4 (123)
  - overlap 5d +0.25/−0.31/44.4 (63); 30d +4.06/+1.29/50.9 (55); 90d +10.02/−3.81/47.1 (34)

## 2026-10-29 ~15:30 — hackathon submission package
- New `submission/demo_script.md`: 14-shot, ≤2:30 script (English VO ~310 words, zh-TW UI with an EN-toggle beat at 1:02), numbers source list, recording checklist.
- New `submission/cv_submission.md`: name, tagline, ~240-word description, tech, Meta-model usage, link placeholders. Deadline 2026-11-05 10:00 Taipei = 2026-11-04 18:00 PST.
- README.md rewritten for judges (old version replaced): problem, features, Meta usage table, mermaid architecture, provider guide, results table (baseline/v4/v1/overlap), legal (§13107(c)), run, limitations.
- LICENSE (MIT, plus a data-use note) added. .gitignore now covers .venv, .env*, keeps .env.example, data/pdfs, llm_cache, chunks, price_cache, sqlite, logs.
- Repo size excluding ignored paths: about 22 MB, 79 files. The largest file is site/data.json at 3.9 MB.
- site/ is static with only relative paths (no root-relative URLs, no external hosts); added site/.nojekyll for GitHub Pages.
- Deploy check:
  - gh 2.103.0 is installed but not logged in. git 2.47.3 has no global user.name or email. This folder is not a git repo.
  - The outbound HTTPS probe and the local subpath server test could not run: Auto-review classification errored.
- No push, no repos created, no paid API calls. pytest 30 passed.
