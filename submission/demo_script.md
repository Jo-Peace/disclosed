# Disclosed · 披露了 — demo video script (≤ 2:30)

- **Format:** 1920×1080 screen recording with English voiceover and burned-in English captions.
- **UI language:** the UI stays in **繁體中文 (zh-TW)** for most of the video so judges see the real product. There is one **EN toggle moment** at 1:02–1:10.
- **Base URL while recording:** `http://localhost:8000/` (run `.venv/bin/python -m disclosed.serve --port 8000`). Replace it with the public URL if one is deployed.
- **Length:** about 310 spoken words at ~140 wpm, which is about 2:13. That leaves room for pauses and the EN toggle beat.

| # | Time | Screen / URL | Voiceover (EN) | On-screen caption |
|---|------|--------------|----------------|-------------------|
| 1 | 0:00–0:08 | Official House Clerk scanned PTR: `https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/2026/9116258.pdf` (paper form, zoom on the hand-ticked boxes and stamps) | "Every stock trade by a U.S. House member must be disclosed. It's public, but buried in PDFs, some of them scanned paper forms marked by hand." | Congress trades are public… but buried in PDFs |
| 2 | 0:08–0:15 | Quick scroll of the Clerk PDF list, then cut to `?lang=zh#/` (top of home page) | "437 filings and nine thousand trades this year. And in Chinese, we couldn't find a single tool that explains them." | 437 filings · 9,136 trades · 53 scanned PDFs · no Chinese-language tool |
| 3 | 0:15–0:22 | `?lang=zh#/` hero and stat strip | "So I built Disclosed, 披露了: a free, bilingual site where Meta's models do the reading." | Disclosed · 披露了: free, bilingual, non-commercial |
| 4 | 0:22–0:38 | `?lang=zh#/?open=1`: Consensus board (議員共識榜), 90-day tab; row 1 expanded with buyers and sellers | "The Congress Consensus board syncs buys and sells per stock: who is a net buyer, who already sold, and an estimated net amount from the disclosed ranges. Accenture: four members buying, one selling." | 議員共識榜: buys and sells synced per member · amounts estimated from ranges |
| 5 | 0:38–0:46 | Scroll to 大額單筆 (Big single-member buys) and hover the 「主要來自」 tag | "Big single-member buys get their own list, flagged when one person is most of the money." | Big single buys, flagged when one member is >60% of the amount |
| 6 | 0:46–1:02 | `?lang=zh#/` → 每日精選. Toggle 議員共識 → 規則 v1（多因子評分） (`#/?m=v1`). Point at the yellow 雙重入選 badge on NVDA and TSM | "Daily picks come in two switchable methods: Congress Consensus, and Rule v1, a multi-factor score. Stocks picked by both get an 'In both' badge, today NVIDIA and TSMC." | Two methods, one toggle · 雙重入選 = In both |
| 7 | 1:02–1:10 | Click **EN** (top right): the same page re-renders in English (`?lang=en#/?m=v1`). Click 繁中 to switch back | "Everything is bilingual, one click away." | 繁中 ⇄ EN |
| 8 | 1:10–1:18 | `?lang=zh#/member/mccaul-michael-t-tx10`: stats, filings, and trades with a link to every original PDF | "Each member page lists every filing and trade, each linked to its original PDF." | Every row links to the official PDF |
| 9 | 1:18–1:34 | `?lang=zh#/member/harshbarger-diana-tn01`: filing table with orange 「掃描 PDF（Meta 視覺解析）」 badges. Split screen with the scanned PDF 9116258 | "Scanned paper forms are read by Meta's Muse Spark vision model: all 53, zero failures. Paper forms carry no ticker, so tickers are inferred and clearly marked." | Muse Spark read 53/53 scanned filings · tickers inferred and flagged |
| 10 | 1:34–1:50 | Same page, zoom into a parse badge: 「Meta 視覺解析 · 通過·附註 77%」. Hover the tooltip | "Then MAGI review: three Meta model roles (verifier, risk reviewer, explainer) each vote, and plain code, not AI, turns the votes into a confidence score. Of 1,790 rows reviewed, 34 went to human review and 3 were rejected." | MAGI: 3 Meta roles vote → code decides → confidence % · 1,790 rows reviewed |
| 11 | 1:50–2:00 | `?lang=zh#/about` (方法與限制), parsing paragraph | "On text PDFs, Meta agrees with our rule parser on 99.44% of rows, and the disagreements exposed a parser bug." | Rule parser vs Meta: 99.44% full-row agreement (3,577 / 3,597) |
| 12 | 2:00–2:16 | `?lang=zh#/track`: scroll to 「兩種判斷方式比較」 (v4 / v1 / 雙重入選 table), then the hash-chain line | "Honesty: live picks are frozen daily into a hash-chained log that can't be back-dated, and backtests are labelled reconstructed. Some numbers are weak, like a negative 30-day median for consensus picks, and we show them." | Hash-chained frozen picks · backtest = reconstructed · weak numbers shown, not hidden |
| 13 | 2:16–2:24 | README architecture diagram (mermaid), then `providers.toml` | "Under the hood, the Meta Model API with Muse Spark does every AI job, behind a pluggable provider layer for other APIs or CLIs." | Meta Model API (muse-spark) · pluggable providers per role |
| 14 | 2:24–2:30 | Back to `?lang=zh#/` home, logo; end card | "Disclosed: public records, made readable. Not investment advice." | Disclosed · 披露了 · free · non-commercial · not investment advice · [demo URL] · [repo URL] |

## Numbers quoted in the voiceover (all from the current build; re-check if data is refreshed)

**Data volume**
- 437 PTR filings, 9,136 trades, 53 scanned PDFs.
- Source: `site/data.json` meta.

**Meta parsing and MAGI review**
- Muse Spark parsed the 53 scanned filings with 0 failures (5,539 rows). The rule-vs-Meta full-row agreement is 99.44% (3,577/3,597). Source: `data/compare_report.txt`.
- MAGI reviewed 1,790 rows across 96 filings: 446 approved, 1,307 approved with caveat, 34 needs review, 3 rejected.

**Picks shown on screen**
- Accenture (ACN): 4 net buyers, 1 seller. This is from the consensus board, 90 days to 2026-10-22.
- In both on the current backtest day: NVDA and TSM. If the live freeze for the recording day differs, update shot 6.

**Weak numbers we say out loud** (backtest, reconstructed)
- v4 30-day median excess is −2.07% (n=149).
- All disclosed purchases: 30-day mean excess −0.29%, win 44.5% (n=2,204).

## Recording checklist

1. **Fresh build.** Run `.venv/bin/python -m disclosed.export_site`, then `.venv/bin/python -m pytest -q` (expect 30 passed). Restart `.venv/bin/python -m disclosed.serve --port 8000`.
2. **Picks.** Run today's freeze before recording (`.venv/bin/python -m disclosed.picks freeze`), then `score_picks` and `export_site`, so the 實盤凍結 tab is not empty. Check that the In-both tickers match the voiceover.
3. **Browser.** Use a clean Chrome profile (no extensions, bookmarks bar hidden) at 1920×1080 and 110% zoom. Clear `localStorage` so the site opens in 繁中 and the default method is 議員共識.
4. **Second tab.** Pre-open the scanned PDF `…/ptr-pdfs/2026/9116258.pdf` for shots 1 and 9.
5. **Privacy.** Hide the terminal, notifications and any `.env` or API-key windows. Nothing with `MODEL_API_KEY` may appear on screen.
6. **Pacing.** Use a smooth scroll and keep each shot ≥ 5 s. The cursor highlight should be on. For the EN toggle moment (shot 7), click slowly so judges see the switch.
7. **Audio.** Record the voiceover separately with a quiet room and a pop filter, at −16 LUFS. Burn in the English captions from the table and check that they're legible on a phone.
8. **Final cut.** Keep it ≤ 2:30. Export 1080p MP4. Upload unlisted (YouTube or Loom) and paste the link into README.md and submission/cv_submission.md.
9. **Before uploading.** Watch it once with the sound off; the captions alone should tell the story. Check that "not investment advice" appears on the end card.
