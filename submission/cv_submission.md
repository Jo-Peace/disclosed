# Cerebral Valley submission draft: Meta Global AI Developer Hackathon (Indie Dev track)

> Deadline: **2026-11-05 10:00 Asia/Taipei (UTC+8)**, which is **2026-11-04 18:00 PST**. Fill the `[ … ]` placeholders before submitting.

**Project name:** Disclosed · 披露了

**Tagline (≤ 80 chars):**
Congress stock trades, read from scanned PDFs by Meta AI, explained in Chinese

**Track:** Indie Dev

**Team:** ShengHan (solo) · `[email / X handle]`

## Description (~240 words)

Members of the U.S. House must disclose their stock trades, but "public" doesn't mean usable. In 2026 alone there are 437 filings with 9,136 trades, spread across PDFs. 53 of them are scanned paper forms with stamps, hand-ticked boxes and no ticker symbols. Amounts are ranges, not share counts. And there was no tool at all for Traditional-Chinese readers.

Disclosed (披露了) is a free, non-commercial, bilingual (繁體中文 / English) site that makes these records readable. Meta's Muse Spark model reads every scanned form (53 of 53, zero failures) and independently re-parses every text PDF. It agrees with our rule-based parser on 99.44% of rows, and the disagreements exposed a real parser bug. A three-role "MAGI" review then checks the data: a verifier, a risk reviewer and an explainer, all Meta-model roles. Each votes, and plain code (not AI) turns the votes into a confidence badge shown on 1,790 reviewed rows.

On top of the data:
- A Congress Consensus board syncs each member's buys and sells and estimates net amounts from the disclosed ranges.
- Daily picks come in two switchable methods, with an "In both" badge for overlaps.
- Every row links to its original PDF.

We're strict about honesty. Live picks are frozen into an append-only, hash-chained log that can't be back-dated, and backtests are labelled reconstructed. Weak results are shown: the average disclosed purchase did not beat the S&P 500. Not investment advice.

## Tech used

- **AI:** Meta Model API (Responses endpoint) with `muse-spark-1.3`: PDF `input_file`, `json_schema` structured output, high-detail vision for scans.
- **Backend:** Python 3, SQLite, pdftotext (poppler) + PyMuPDF, requests; a pluggable LLM provider layer (`providers.toml`).
- **Frontend:** vanilla JS single-page app with no build step and no trackers, fully static (GitHub Pages or Netlify compatible), zh-TW / EN.
- **Integrity:** SHA-256 hash-chained append-only pick logs, content-hash response cache, token/cost ledger with a hard spend cap.
- **Data:** U.S. House Clerk PTR disclosures; Yahoo Finance daily prices vs SPY.

## How we use Meta models

1. **Vision parsing of scanned or paper filings.** Muse Spark receives the PDF and returns schema-constrained rows (owner, asset, buy/sell, dates, amount range, cap-gains flag), marking illegible rows itself. 53/53 filings → 5,539 rows.
2. **Independent cross-check of text PDFs.** It runs a second, independent parse of all 384 text filings, which reaches 99.44% full-row agreement (3,577/3,597) with the rule parser. Mismatches are surfaced per row.
3. **MAGI three-role review.**
   - Three separate Meta-model roles each vote approve / flag / reject with a confidence: a data verifier, a risk reviewer (data caveats only, never market advice) and a bilingual plain-language explainer.
   - Deterministic code aggregates the votes.
   - Results: 446 approved · 1,307 approved with caveat · 34 sent to human review · 3 rejected.
4. **Guard-railed bilingual summaries** for picks: no advice and no causal claims, and every number must match the data.

All four jobs run through one provider interface, so any role can be pointed at another API or CLI by configuration. For this submission everything runs on Meta.

## Links

- Demo video (≤ 2:30): `https://youtu.be/W_GIBf6EMY4`
- Live site: https://jo-peace.github.io/disclosed/
- Source code: https://github.com/Jo-Peace/disclosed (MIT)
- Screenshots: `screens/10_consensus_en.png`, `screens/14_picks_toggle_en.png`, `screens/15_trackrecord_compare_zh.png`

## Short answers (if the form asks)

- **What's next?**
  - Run the daily live freeze on a schedule and let the frozen record mature.
  - Add Senate eFD coverage.
  - Have humans review the 34 flagged rows.
  - Add push alerts in Chinese.
- **Biggest challenge?** Getting reliable rows out of scanned paper forms with no tickers, and being able to *prove* reliability: the cross-check and MAGI confidence exist for that.
- **Legal / ethics:** the site is free and non-commercial, consistent with 5 U.S.C. § 13107(c). It is not investment advice, and every row links to its source.
