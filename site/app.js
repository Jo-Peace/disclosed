"use strict";
/* Disclosed — single-page bilingual viewer. Data: data.json (+ prices.json lazily). No tracking, no ads, no external requests. */
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
let D = null, PX = null;
let LANG = new URLSearchParams(location.search).get("lang") || localStorage.getItem("lang") || ((navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en");

const T = {
 zh: {
  nav: {home:"精選", members:"議員", tickers:"股票", track:"績效追蹤", about:"方法與限制"},
  bn_t: "重要聲明：", bn_b: "本站僅整理美國眾議院官方公開之申報資料，不是投資建議。申報金額為區間；議員最長可於交易後 45 天才申報。本站免費、無廣告、非商業用途。",
  hero_h: "看懂美國議員的股票交易申報", hero_p: "把眾議院書記官處（House Clerk）公開的 STOCK Act 定期交易申報（PTR）整理成雙語摘要。每一筆交易都附上官方原始 PDF 連結，每日精選榜單以時間戳記與雜湊鏈凍結，之後用公開價格對照 SPY 回頭檢驗。",
  s_filings: "份申報 (PTR)", s_tx: "筆交易", s_members: "位議員", s_tickers: "檔標的", s_px: "價格資料至",
  picks_h: "每日精選（規則排序，非投資建議）", picks_live: "實盤凍結", picks_back: "回測重播（事後）",
  picks_note_live: "以下榜單於凍結時間寫入僅可追加（append-only）的雜湊鏈日誌，事後無法回填或修改。",
  picks_ver: "評分版本", picks_note_back: "回測重播：只使用當日已公開的資料事後重建，僅供檢視方法，並非當時凍結的實盤榜單。",
  score: "分", why: "入榜原因", comps: {net_amount:"估計淨買進金額", net_buyers:"淨買進議員", amount:"金額", multi_member:"多位議員", delay:"申報速度", recency:"新鮮度", liquidity:"流動性"},
  ai_h: "AI 白話摘要", ai_pending: "此項尚未產生 AI 摘要（不顯示任何假造文字）。", facts_h: "自動事實句（模板產生，非 AI）",
  support: "支持交易", frozen: "凍結時間", chain: "雜湊", pick_date: "榜單日期", data_asof: "價格資料截止",
  cs_h: "議員共識榜", cs_sub: "最近 {w} 天內（依申報日，截至 {d}）議員估計淨買進金額：買進金額減去賣出（含部分賣出）金額。點一列看明細。", cs_main: "多位議員共識", cs_main_sub: "至少 2 位議員淨買進、淨買進人數多於淨賣出人數，且估計淨買進金額大於 0；依金額排序。", cs_big: "大額單筆", cs_big_sub: "估計淨買進金額大於 0、但未達共識條件（例如只有 1 位議員淨買進）的股票，依金額排序。", cs_by: "買方：{m}", cs_net: "估計淨買進 約 {x}", cs_rng: "區間 {a} ~ {b}", cs_conc: "主要來自 {m}", cs_open: "含無上限級距（以下限計）", cs_d: "{n}天", cs_bs: "買進 {b} 位 · 賣出 {s} 位", cs_tw: "台灣", cs_ty: {P:"買", S:"賣", SP:"部分賣出"}, cs_sold: "已賣出", cs_buyer: "淨買進", cs_seller: "淨賣出",
  cs_heavy: "註：{m} 為其中 {n} 檔的淨買方，單一頻繁交易者可能影響排名。", cs_disc: "依申報公開日同步買進與賣出紀錄，非投資建議。金額依申報區間中間值估算，申報不含持股數。「主要來自」＝單一議員占該檔買進金額 60% 以上。同一申報的規則與 AI 解析結果已去重，每位議員每檔只算一次。", cs_owner: {SP:"配偶", DC:"子女", JT:"共同"}, cs_none: "此期間沒有符合條件的買進。",
  latest_h: "最新申報的交易", no_picks: "目前沒有符合條件的榜單。",
  members_h: "議員", members_p: "依姓氏排序；點入可看每份申報與交易。", search: "搜尋…",
  th: {name:"姓名", dst:"選區", filings:"申報數", tx:"交易數", buy:"買進", sell:"賣出", last:"最近申報", date:"交易日", filed:"申報日", member:"議員", ticker:"代號", type:"類型", amount:"金額區間", owner:"持有人", perf:"申報後超額報酬 (vs SPY)", parse:"解析信心", pdf:"原始 PDF", asset:"資產", doc:"文件", kind:"類型", n:"筆數", name2:"名稱", members:"議員數", px:"價格"},
  ty: {P:"買進", S:"賣出", SP:"部分賣出", E:"交換"}, ow: {self:"本人", SP:"配偶", DC:"受扶養子女", JT:"共同", "":"本人"},
  text_pdf: "文字 PDF", scanned_pdf: "掃描 PDF（Meta 視覺解析）",
  parse_rule: "規則", parse_meta: "Meta 視覺解析", parse_none: "MAGI 未抽查", cons: {A:"MAGI 通過", C:"通過·附註", D:"通過·有異議", R:"MAGI 退件", N:"待人工複核"}, x_ok: "Meta 交叉一致", x_bad: "Meta 不一致", inferred: "代號為推測", illeg: "辨識不清", parse_tip: "規則解析已通過自我一致性檢查；多數文字 PDF 另由 Meta 模型獨立解析並逐筆交叉比對；掃描 PDF 只有 Meta 視覺解析。MAGI（解析員／風險審查員／說明員）為抽樣或全量複核，百分比為程式碼計算的信心分數，不是正確率。",
  perf30: "30 交易日超額報酬（買進，依申報去重）", n_label: "樣本", insuff: "樣本不足", win: "勝率", mean: "平均超額", median: "中位數",
  back: "← 返回", tx_h: "交易", filings_h: "申報文件", showmore: "顯示更多", price_h: "價格走勢（2026 起；標記＝申報日）", excluded: "未納入價格追蹤", why_ex: "原因",
  pxs: {ok:"已取得", not_found:"查無資料", error:"錯誤", no_data:"無資料", "n/a":"不適用", not_fetched:"尚未抓取"},
  reasons: {government_security_or_bond:"政府債券", corporate_bond:"公司債", option_or_derivative:"選擇權/衍生品", other_non_listed:"其他非上市資產", private_ownership_interest:"私人持股", hedge_fund_or_private_fund:"私募/對沖基金", private_stock:"私人股票", variable_annuity:"變額年金", other_locality_investment:"其他投資", asset_backed_security:"資產擔保證券", cryptocurrency:"加密貨幣", preferred_share_symbol_unsupported:"特別股（價格來源不支援）", unrecognised_symbol_format:"代號格式無法辨識", mutual_fund:"共同基金"},
  track_h: "績效追蹤", track_p: "從申報公開日（House Clerk FilingDate）之後的下一個交易日收盤價起算，持有 5 / 30 / 90 個交易日，對比同期 SPY（皆用還原收盤價）。",
  tr_buy: "全部申報之買進（基準，每份申報×標的計一次）", tr_sell: "全部申報之賣出（股價於賣出申報後是否落後 SPY）", tr_picks: "本站精選榜單的事後檢驗", tr_hist: "30 交易日超額報酬分佈（買進）",
  hz: "交易日", pending: "尚未到期", noprice: "無價格", underperf: "落後 SPY 比例", live_none: "實盤榜單才剛開始凍結，尚無已到期樣本。",
  caveats_h: "怎麼讀這些數字（限制）", caveats: ["超額報酬 = 個股報酬 − 同期 SPY 報酬；勝率 = 超額報酬 > 0 的比例。", "同一時期的樣本彼此高度相關（同一段行情、同一標的多人買進），不是獨立樣本；標準誤僅供參考。", "樣本 < 10 一律標示「樣本不足」，不下結論。", "過去的申報表現不代表未來；本站不提供買賣建議。", "價格來源為 Yahoo Finance 公開圖表資料（非官方、可能有誤差）；無資料的標的會標記為缺漏，不會補值。", "掃描 PDF 的內容由 Meta 模型讀取手寫/表格，可能有誤；已標示辨識不清的列與推測的代號，請以原始 PDF 為準。", "精選榜單的權重在看到任何績效之前就已固定、未針對結果調參；「回測重播」為事後重建，且樣本重疊、尚在累積，不能當作實盤成績。"],
  about_h: "方法與限制", about: [
   ["資料來源", "僅使用美國眾議院書記官處公開的 STOCK Act 定期交易申報（PTR）及其官方 PDF。不含參議院、不含任何非官方消息。"],
   ["解析", "文字 PDF 以 pdftotext + 規則解析，並用「申報筆數、欄位完整度、資本利得核取方塊數」做自我一致性檢查（384/384 份通過，這是自洽檢查，不等於人工逐筆驗證）。文字 PDF 另由 Meta Muse Spark 獨立解析並逐筆交叉比對；掃描 PDF（手寫/紙本表格，無股票代號）只由 Meta 視覺解析，並標記辨識不清的列；紙本表格沒有代號，代號是用公司名稱經 Yahoo 搜尋比對「推測」的（標示為推測，比對不確定者不計價）。"],
   ["MAGI 三方投票", "資料解析員、風險審查員、白話說明員三個角色各自表態，由程式碼（非 AI）決定共識與信心分數；分歧會標記待人工複核（⚑）。所有掃描申報、規則/模型不一致列、交易日晚於通知日的異常列，以及隨機抽樣文字申報列皆已跑過三方投票；其餘列顯示「MAGI 未抽查」。"],
   ["每日精選（兩種判斷方式）", "每天同時產生兩份榜單並分別凍結（雜湊鏈日誌中以 method 標記）：①「議員共識」（rules-v4-consensus-amount，預設）：近 90 天至少 2 位議員淨買進、且淨買進人數多於淨賣出人數，依估計淨買進金額（申報區間中間值估算，買進減賣出；無上限級距以下限計）排序，淨額 ≤ 0 不入榜，並要求 20 日均成交額至少 100 萬美元。②「回測最佳」（rules-v1）：依最大單筆金額 25、多位議員買進 30、申報速度 15、新鮮度 20、流動性 10 加權打分。兩者同日皆入選者標示「雙重入選」。另曾測試 v2（淨買進人數）與 v3（純淨買進金額），回測未優於上述兩版，已不採用。舊紀錄不會改寫；不是預測模型，回測為事後重建。"],
   ["價格", "Yahoo Finance 公開日線資料，本機快取；無法取得的標的會明確標記，不會填補。選擇權、債券、私募基金、特別股等不納入。"],
   ["法規提醒", "依 5 U.S.C. §13107(c)，這些申報資料不得用於商業目的、募款或徵信。本站為免費、無廣告、非商業之研究/教育專案。"],
   ["限制", "申報金額只是區間；交易可能在 45 天後才申報；配偶/子女的交易也會出現；同一標的買賣動機不明；本站不推論任何不當行為。"]],
  foot: "資料：U.S. House Clerk 公開申報。本站為免費、無廣告、非商業用途之專案，不構成投資建議；金額為區間，申報最長可延遲 45 天。價格來源：Yahoo Finance（非官方）。",
  gen: "資料產生時間",
 },
 en: {
  nav: {home:"Featured", members:"Members", tickers:"Tickers", track:"Track record", about:"Method & limits"},
  bn_t: "Important:", bn_b: "Official US House disclosures only — not investment advice. Amounts are ranges; filings can arrive up to 45 days after the trade. Free, no ads, non-commercial.",
  hero_h: "US House stock-trade disclosures, in plain language", hero_p: "A bilingual digest of STOCK Act Periodic Transaction Reports published by the House Clerk. Every transaction links to its official PDF; the daily featured list is frozen in a timestamped hash chain and scored later against SPY with public prices.",
  s_filings: "PTR filings", s_tx: "transactions", s_members: "members", s_tickers: "tickers", s_px: "prices through",
  picks_h: "Daily featured (rule-ranked, not advice)", picks_live: "Live (frozen)", picks_back: "Backtest replay (retrospective)",
  picks_note_live: "These picks were written to an append-only hash-chained log at the freeze time; they cannot be back-filled or edited afterwards.",
  picks_ver: "Scoring version", picks_note_back: "Backtest replay: rebuilt after the fact using only information public on each date, to show the method — not a list frozen at the time.",
  score: "pts", why: "Why it ranks", comps: {net_amount:"Est. net buy amount", net_buyers:"Net-buying members", amount:"Amount", multi_member:"Multiple members", delay:"Filing speed", recency:"Recency", liquidity:"Liquidity"},
  ai_h: "AI plain-language summary", ai_pending: "No AI summary generated for this item yet (no fake text is shown).", facts_h: "Auto-generated facts (template, not AI)",
  support: "Supporting transactions", frozen: "Frozen at", chain: "Hash", pick_date: "Pick date", data_asof: "Prices through",
  cs_h: "Congress Consensus", cs_sub: "Estimated net buy amount by House members in the last {w} days (by filing date, through {d}): purchases minus sales (incl. partial). Tap a row for details.", cs_main: "Multi-member consensus", cs_main_sub: "At least 2 net-buying members, more net buyers than net sellers, and a positive estimated net amount; ranked by amount.", cs_big: "Big single-member buys", cs_big_sub: "Positive estimated net amount but not a consensus (e.g. only 1 net-buying member); ranked by amount.", cs_by: "Buyer: {m}", cs_net: "Est. net buy ~{x}", cs_rng: "range {a} ~ {b}", cs_conc: "Mostly {m}", cs_open: "open-ended bracket (lower bound used)", cs_d: "{n} days", cs_bs: "{b} buying · {s} selling", cs_tw: "Taiwan", cs_ty: {P:"Buy", S:"Sell", SP:"Partial sale"}, cs_sold: "sold since", cs_buyer: "net buyer", cs_seller: "net seller",
  cs_heavy: "Note: {m} is a net buyer in {n} of these names — a single heavy trader can skew this ranking.", cs_disc: "Synced with public filing dates for both purchases and sales; not investment advice. Amounts are estimated from the midpoints of the disclosed ranges; filings do not report share counts. “Mostly X” = one member accounts for over 60% of the purchase amount. Rule-parsed and AI-parsed copies of the same filing are de-duplicated; each member counts once per ticker.", cs_owner: {SP:"spouse", DC:"child", JT:"joint"}, cs_none: "No qualifying purchases in this window.",
  latest_h: "Most recently filed transactions", no_picks: "No qualifying picks right now.",
  members_h: "Members", members_p: "Sorted by last name; open one to see every filing and transaction.", search: "Search…",
  th: {name:"Name", dst:"District", filings:"Filings", tx:"Trades", buy:"Buys", sell:"Sells", last:"Last filing", date:"Trade date", filed:"Filed", member:"Member", ticker:"Ticker", type:"Type", amount:"Amount range", owner:"Owner", perf:"Excess return after filing (vs SPY)", parse:"Parse confidence", pdf:"Original PDF", asset:"Asset", doc:"Document", kind:"Kind", n:"Rows", name2:"Name", members:"Members", px:"Prices"},
  ty: {P:"Buy", S:"Sell", SP:"Partial sell", E:"Exchange"}, ow: {self:"Self", SP:"Spouse", DC:"Dep. child", JT:"Joint", "":"Self"},
  text_pdf: "Text PDF", scanned_pdf: "Scanned PDF (Meta vision parse)",
  parse_rule: "Rule", parse_meta: "Meta vision parse", parse_none: "MAGI not sampled", cons: {A:"MAGI approved", C:"approved·caveat", D:"approved·dissent", R:"MAGI rejected", N:"needs review"}, x_ok: "Meta cross-check ✓", x_bad: "Meta differs", inferred: "ticker inferred", illeg: "low legibility", parse_tip: "The rule parse passed self-consistency checks; most text PDFs were also parsed independently by the Meta model and compared row by row; scanned PDFs have the Meta vision parse only. MAGI (parser / risk / explainer) reviewed a subset or all rows; the percentage is a code-computed confidence score, not an accuracy rate.",
  perf30: "30-trading-day excess return (purchases, de-duplicated per filing)", n_label: "sample", insuff: "insufficient sample", win: "Win rate", mean: "Mean excess", median: "Median",
  back: "← Back", tx_h: "Transactions", filings_h: "Filings", showmore: "Show more", price_h: "Price (since 2026; ticks = filing dates)", excluded: "Not price-tracked", why_ex: "Reason",
  pxs: {ok:"available", not_found:"not found", error:"error", no_data:"no data", "n/a":"n/a", not_fetched:"not fetched"},
  reasons: {government_security_or_bond:"government security / bond", corporate_bond:"corporate bond", option_or_derivative:"option / derivative", other_non_listed:"other non-listed asset", private_ownership_interest:"private ownership interest", hedge_fund_or_private_fund:"hedge / private fund", private_stock:"private stock", variable_annuity:"variable annuity", other_locality_investment:"other investment", asset_backed_security:"asset-backed security", cryptocurrency:"cryptocurrency", preferred_share_symbol_unsupported:"preferred share (not supported by price source)", unrecognised_symbol_format:"unrecognised symbol format", mutual_fund:"mutual fund"},
  track_h: "Track record", track_p: "Measured from the next trading day's close after the filing became public (House Clerk FilingDate), held 5 / 30 / 90 trading days, against SPY over the same dates (adjusted closes).",
  tr_buy: "All disclosed purchases (baseline; one per filing × ticker)", tr_sell: "All disclosed sales (did the stock lag SPY after the sale was filed?)", tr_picks: "Our featured picks, scored after the fact", tr_hist: "Distribution of 30-trading-day excess return (purchases)",
  hz: "trading days", pending: "not yet matured", noprice: "no price", underperf: "Lagged SPY", live_none: "Live picks have only just started being frozen; no matured samples yet.",
  caveats_h: "How to read these numbers (limitations)", caveats: ["Excess return = stock return − SPY return over the same dates; win rate = share with excess > 0.", "Samples overlap in time and across members buying the same name; they are not independent, so standard errors are indicative only.", "Any sample below 10 is labelled 'insufficient' and no conclusion is drawn.", "Past disclosure performance does not predict the future; this site gives no buy/sell advice.", "Prices come from Yahoo Finance public chart data (unofficial, may contain errors); tickers with no data are marked missing, never filled in.", "Scanned PDFs are read by the Meta model (handwriting / tables) and may contain errors; unclear rows and inferred tickers are flagged — the official PDF is the source of truth.", "Pick weights were fixed before any performance was looked at and have not been tuned to results; the backtest replay is a retrospective rebuild with overlapping samples and is not a live record."],
  about_h: "Method & limitations", about: [
   ["Source", "Only the STOCK Act Periodic Transaction Reports (PTRs) and official PDFs published by the US House Clerk. No Senate data, no unofficial tips."],
   ["Parsing", "Text PDFs are parsed with pdftotext + rules and self-checked (row count, field completeness, cap-gains checkbox count; 384/384 filings pass — a consistency check, not a line-by-line human audit). Text PDFs are also parsed independently by Meta Muse Spark and compared row by row. Scanned (paper/handwritten) PDFs have the Meta vision parse only, with unclear rows flagged; paper forms print no ticker, so tickers are INFERRED from the printed company name through Yahoo search (flagged as inferred; uncertain names are left unpriced)."],
   ["MAGI 3-role vote", "A data-parser, a risk-reviewer and a plain-language explainer each vote; plain code (not AI) decides consensus and confidence, and disagreements are flagged (⚑) for human review. All scanned filings, rule/model mismatches, rows whose trade date is after the notification date, and a random sample of text filings went through the vote; remaining rows show “MAGI not sampled”."],
   ["Daily featured (two methods)", "Two lists are produced and frozen separately every day (tagged by method in the hash-chained log): (1) Congress consensus (rules-v4-consensus-amount, default): at least 2 net-buying members over 90 days and more net buyers than sellers, ranked by estimated net buy amount (range midpoints, purchases minus sales; open-ended top bracket uses its lower bound), net ≤ 0 excluded, min $1M average 20-day dollar volume. (2) Backtest-best (rules-v1): weighted score — largest purchase 25, multiple buyers 30, filing speed 15, recency 20, liquidity 10. Tickers on both lists the same day are marked In both. v2 (net-buyer count) and v3 (pure net amount) were also tested and dropped because they did not beat these two in the backtest. Old records are never rewritten; not a prediction model; backtests are reconstructed after the fact."],
   ["Prices", "Yahoo Finance public daily data, cached locally; anything unavailable is marked, never imputed. Options, bonds, private funds and preferred shares are excluded."],
   ["Legal", "Under 5 U.S.C. §13107(c) these records may not be used for commercial purposes, fundraising or credit rating. This is a free, ad-free, non-commercial research/education project."],
   ["Limits", "Amounts are only ranges; trades can be filed 45 days late; spouse/child trades also appear; motives are unknown; nothing here implies wrongdoing."]],
  foot: "Data: U.S. House Clerk public filings. Free, ad-free, non-commercial project; not investment advice. Amounts are ranges and filings may be up to 45 days late. Prices: Yahoo Finance (unofficial).",
  gen: "Data generated",
 }};

const MT = {
  zh: {m_cons: "議員共識", m_v1: "回測最佳", m_lab: "判斷方式",
    m_desc_cons: "近 90 天至少 2 位議員淨買進、且淨買進人數多於淨賣出，依估計淨買進金額排序（rules-v4-consensus-amount）。",
    m_desc_v1: "依最大單筆金額、多位議員買進、申報速度、新鮮度與流動性加權打分（rules-v1），四版回測中 30/90 日表現最好的一版。",
    both: "雙重入選", both_tip: "此股票同日也在另一種判斷方式的榜單中",
    bt_lab: "回測（事後重建，非實盤）", bt_from: "自申報公開日起，相對 SPY 超額報酬：平均 / 中位數 / 勝率", ov_lab: "雙重入選子集（回測）",
    cmp_h: "兩種判斷方式比較（回測，事後重建）", cmp_note: "回測只用當日已公開的資料事後重建，同一 (股票, 公開日) 只計一次；不是實盤成績，也不保證未來。n<10 不下結論。",
    ov_row: "雙重入選（兩榜同日皆入選）", dropped: "另曾測試 v2（依淨買進人數）與 v3（純淨買進金額），回測表現未優於上述兩版，已不採用（舊紀錄保留不改寫）。",
    live_pending: "此判斷方式的實盤榜單將自下一次每日凍結開始寫入；以下先顯示回測重播。", live_h: "實盤（凍結後計分）"},
  en: {m_cons: "Congress consensus", m_v1: "Backtest-best", m_lab: "Method",
    m_desc_cons: "At least 2 members net-buying over 90 days and more net buyers than sellers, ranked by estimated net buy amount (rules-v4-consensus-amount).",
    m_desc_v1: "Weighted score on largest purchase, multiple buyers, filing speed, recency and liquidity (rules-v1) — the best of four versions at 30/90 days in the backtest.",
    both: "In both", both_tip: "This ticker is also on the other method's list for the same day",
    bt_lab: "Backtest (reconstructed, not live)", bt_from: "Excess return vs SPY from public date: mean / median / win rate", ov_lab: "In-both subset (backtest)",
    cmp_h: "Comparing the two methods (backtest, reconstructed)", cmp_note: "Backtests are rebuilt after the fact using only information public on each date; each (ticker, public date) counts once. Not live results and no guarantee of the future. n<10 is not conclusive.",
    ov_row: "In both (picked by both methods on the same day)", dropped: "We also tested v2 (rank by net-buyer count) and v3 (pure net amount); neither beat the two above in the backtest, so they were dropped (old records are kept unchanged).",
    live_pending: "Live freezing for this method starts with the next daily freeze; showing the backtest replay for now.", live_h: "Live (scored after freezing)"},
};
Object.keys(MT).forEach(l => Object.assign(T[l], MT[l]));
const hashQ = () => new URLSearchParams(location.hash.split("?")[1] || "");
const getM = () => { const m = hashQ().get("m") || new URLSearchParams(location.search).get("m"); return m === "v1" || m === "backtest_best" ? "backtest_best" : "consensus"; };
const setQ = (k, v) => { const base = location.hash.split("?")[0] || "#/"; const q = hashQ(); if (v == null) q.delete(k); else q.set(k, v); const qs = q.toString(); location.hash = base + (qs ? "?" + qs : ""); };
function mToggle() {
  const L = t(), m = getM();
  return `<div class="seg" role="tablist" aria-label="${L.m_lab}"><button data-m="cons" class="${m==="consensus"?"on":""}">${L.m_cons}</button><button data-m="v1" class="${m!=="consensus"?"on":""}">${L.m_v1}</button></div>
  <p class="mdesc">${m === "consensus" ? L.m_desc_cons : L.m_desc_v1}</p>`;
}
function statLine(s) { return s && s.n ? `${pctSpan(s.mean_excess, 2)} / ${pctSpan(s.median_excess, 2)} / <b>${(s.win_rate * 100).toFixed(1)}%</b> <span class="mu">n=${s.n}${s.n < 10 ? " ⚠" : ""}</span>` : `<span class="mu">n=0</span>`; }
function mStats(key, label) {
  const L = t(), d = D.picks_scored && D.picks_scored[key]; if (!d) return "";
  return `<div class="mstats"><div class="mu" style="font-size:12px"><b>${label}</b> · ${L.bt_from}</div><div class="msg">${["5","30","90"].map(h => `<div><span class="mu">${h}d</span> ${statLine(d.summary.from_public[h])}</div>`).join("")}</div></div>`;
}
const t = () => T[LANG];
const fmtPct = (x, d=1) => x == null ? "—" : (x >= 0 ? "+" : "") + (x * 100).toFixed(d) + "%";
const cls = x => x == null ? "mu" : x >= 0 ? "pos" : "neg";
const pctSpan = (x, d=1) => `<span class="${cls(x)}">${fmtPct(x, d)}</span>`;
const pdfLink = (u, label) => `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(label || "PDF ↗")}</a>`;

async function boot() {
  try { D = await (await fetch("data.json")).json(); } catch (e) { $("#app").innerHTML = "<p>data.json not found — run <code>python -m disclosed.export_site</code></p>"; return; }
  D.members.forEach(m => m.name = nn(m.name)); D.mById = Object.fromEntries(D.members.map(m => [m.id, m]));
  D.tById = Object.fromEntries(D.tickers.map(x => [x.tk, x]));
  document.querySelectorAll(".lang button").forEach(b => b.onclick = () => { LANG = b.dataset.l; localStorage.setItem("lang", LANG); render(); });
  window.addEventListener("hashchange", render); render();
}
async function loadPx() { if (!PX) PX = await (await fetch("prices.json")).json(); return PX; }

function chrome() {
  document.documentElement.lang = LANG === "zh" ? "zh-Hant" : "en";
  document.querySelectorAll(".lang button").forEach(b => b.classList.toggle("on", b.dataset.l === LANG));
  const h = location.hash.replace(/^#\/?/, "").split("/")[0] || "home";
  const key = h === "member" ? "members" : h === "ticker" ? "tickers" : h;
  $("#nav").innerHTML = [["home","#/"],["members","#/members"],["tickers","#/tickers"],["track","#/track"],["about","#/about"]].map(([k,u]) => `<a href="${u}" class="${key===k?"on":""}">${t().nav[k]}</a>`).join("");
  $("#bn-t").textContent = t().bn_t; $("#bn-b").textContent = t().bn_b;
  $("#foot").innerHTML = `<b>Disclosed</b> (working title) · ${esc(t().foot)}<br>${t().gen}: ${esc(D.meta.generated_at.slice(0,16).replace("T"," "))} · ${t().s_px} ${esc(D.meta.prices_as_of)}`;
}
function render() {
  if (!D) return; chrome();
  const parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  const r = parts[0] || "home"; const app = $("#app");
  const views = {home: vHome, members: vMembers, member: () => vMember(parts[1]), tickers: vTickers, ticker: () => vTicker(parts[1]), track: vTrack, about: vAbout};
  Promise.resolve((views[r] || vHome)()).then(h => { app.innerHTML = h; wire(); window.scrollTo(0, 0); });
}

/* ---------- badges / rows ---------- */
const parseBadge = (x) => {
  const L = t(); x = x || {}; const out = [];
  if (x.sc) out.push(`<em>${L.parse_meta}</em>`); else out.push(`<em>✓ ${L.parse_rule}</em>`);
  if (x.xc === 1) out.push(`<em>${L.x_ok}</em>`); else if (x.xc === 0) out.push(`<span class="badge b-warn">${L.x_bad}</span>`);
  if (x.cs) { const cls = x.cs === "A" ? "b-P" : x.cs === "R" ? "b-S" : "b-warn"; out.push(`<span class="badge ${cls}">${L.cons[x.cs]} ${Math.round((x.cf || 0) * 100)}%${x.dg ? " ⚑" : ""}</span>`); }
  else out.push(`<u>${L.parse_none}</u>`);
  if (x.inf) out.push(`<span class="badge b-gray">${L.inferred}</span>`);
  if (x.sc && x.lg === 0) out.push(`<span class="badge b-warn">${L.illeg}</span>`);
  return `<span class="badge b-parse" title="${esc(L.parse_tip)}">${out.join(" · ")}</span>`;
};
function perfCells(x) {
  if (!x.p) return `<span class="mu">—</span>`;
  return ["5","30","90"].map(h => {
    const v = x.p[h], s = x.ps && x.ps[h];
    return `<span class="nw" style="margin-right:8px"><span class="mu">${h}d</span> ${v != null ? pctSpan(v) : `<span class="mu" title="${esc(s === "insufficient_data" ? t().pending : t().noprice)}">${s === "insufficient_data" ? "…" : "n/a"}</span>`}</span>`;
  }).join("");
}
function txTable(rows, opts = {}) {
  const L = t().th, cap = opts.cap || 150, show = rows.slice(0, cap);
  return `<div class="tw"><table><thead><tr><th>${L.date}</th><th>${L.filed}</th>${opts.noMember ? "" : `<th>${L.member}</th>`}${opts.noTicker ? "" : `<th>${L.ticker}</th>`}<th>${L.type}</th><th>${L.amount}</th><th>${L.owner}</th><th>${L.perf}</th><th>${L.parse}</th><th>${L.pdf}</th></tr></thead><tbody>` +
   show.map(x => `<tr><td class="nw">${esc(x.td || "")}</td><td class="nw">${esc(x.fd)}</td>${opts.noMember ? "" : `<td><a href="#/member/${esc(x.m)}">${esc(D.mById[x.m]?.name || x.m)}</a></td>`}` +
    (opts.noTicker ? "" : `<td>${x.tk ? `<a href="#/ticker/${encodeURIComponent(x.tk)}"><b>${esc(x.tk)}</b></a><div class="mu" style="font-size:11.5px;max-width:220px">${esc(x.a).slice(0, 60)}</div>` : `<span class="mu" style="font-size:12px">${esc(x.a).slice(0, 70)}</span>`}</td>`) +
    `<td><span class="badge b-${x.ty}">${esc(t().ty[x.ty] || x.ty)}</span></td><td class="nw">${esc(x.am || "")}</td><td>${esc(t().ow[x.ow] ?? x.ow)}</td><td>${perfCells(x)}</td><td>${parseBadge(x)}</td><td class="nw">${pdfLink(x.pdf)}</td></tr>`).join("") +
   `</tbody></table></div>` + (rows.length > cap ? `<button class="more" data-more="${cap + 150}">${t().showmore} (${rows.length - cap})</button>` : "");
}

/* ---------- views ---------- */
function statStrip() {
  const m = D.meta, n = x => x.toLocaleString();
  return `<div class="stats">` + [[n(m.n_filings), t().s_filings], [n(m.n_tx), t().s_tx], [n(m.n_members), t().s_members], [n(m.n_tickers), t().s_tickers], [m.prices_as_of, t().s_px]].map(([a,b]) => `<div class="stat"><b>${esc(a)}</b><span>${esc(b)}</span></div>`).join("") + `</div>`;
}
function pickCard(p, i, entry, inBoth) {
  const L = t(), z = LANG === "zh";
  const comps = Object.entries(p.components).map(([k, c]) => `<span>${L.comps[k]}</span><div class="bar"><i style="width:${c.points / c.max * 100}%"></i></div><span class="mu">${c.points}/${c.max}</span>`).join("");
  const ai = p.ai_summary && p.ai_summary.status === "ok" ? `<div class="ai" style="border-style:solid"><b>${L.ai_h}</b> · Meta MAGI<br>${esc(z ? p.ai_summary.zh_tw : p.ai_summary.en)}</div>` : `<div class="ai"><b>${L.ai_h}</b> — <span class="badge b-warn">PLACEHOLDER</span><br>${L.ai_pending}</div>`;
  const tx = p.tx.slice(0, 6).map(x => `<tr><td class="nw">${esc(x.tx_date)}</td><td>${esc(D.mById[x.member]?.name || x.member)}</td><td class="nw">${esc(x.amount)}</td><td>${pdfLink(x.pdf_url)}</td></tr>`).join("");
  return `<div class="card pick"><div class="hd"><div class="rank">${i + 1}</div><div><a class="tk" href="#/ticker/${encodeURIComponent(p.ticker)}">${esc(p.ticker)}</a>${inBoth ? ` <span class="badge bboth" title="${L.both_tip}">${L.both}</span>` : ""}<div class="nm">${esc((p.name || "").replace(/\s*\([A-Z.$\-]+\)\s*$/, "").slice(0, 70))}</div></div><div class="score"><b>${p.score}</b><span>/100 ${L.score}</span></div></div>
   <div class="bars">${comps}</div>
   <div><div class="mu" style="font-size:12px;font-weight:700">${L.why}</div><ul class="why">${(z ? p.reasons_zh : p.reasons_en).map(r => `<li>${esc(r)}</li>`).join("")}</ul></div>
   <div class="chips">${p.members.map(m => `<a class="chip" href="#/member/${esc(m.id)}">${esc(nn(m.name))}</a>`).join("")}${p.flags.map(f => `<span class="badge b-warn">${esc(f)}</span>`).join("")}</div>
   <div class="facts"><b>${L.facts_h}:</b> ${esc(z ? p.facts_zh : p.facts_en)}</div>${ai}
   <div class="tw" style="border-radius:10px"><table><thead><tr><th>${L.th.date}</th><th>${L.th.member}</th><th>${L.th.amount}</th><th>${L.th.pdf}</th></tr></thead><tbody>${tx}</tbody></table></div></div>`;
}
function vHome() {
  const L = t(), PM = D.picks.methods, m = getM(), other = m === "consensus" ? "backtest_best" : "consensus", P = PM[m];
  const live = P.live[P.live.length - 1], back = P.backtest_latest;
  const mode = hashQ().get("mode") || (live ? "live" : "back");
  const e = mode === "live" ? live : back;
  const oe = mode === "live" ? PM[other].live.find(x => e && x.pick_date === e.pick_date) : PM[other].backtest_latest;
  const both = new Set(oe && e && oe.pick_date === e.pick_date ? oe.picks.map(p => p.ticker) : []);
  const tabs = `<div class="tabs"><button data-mode="live" class="${mode==="live"?"on":""}">${L.picks_live}${live ? "" : " (0)"}</button><button data-mode="back" class="${mode!=="live"?"on":""}">${L.picks_back}</button></div>`;
  const meta = e ? `<p class="note">${L.pick_date}: <b>${esc(e.pick_date)}</b> · ${L.data_asof}: ${esc(e.data_as_of_prices)} · ${mode==="live" ? `${L.frozen}: ${esc(e.frozen_at)} · ${L.chain}: <code>${esc((e.hash||"").slice(0,16))}…</code> (seq ${e.seq})` : ""}<br>${mode==="live" ? L.picks_note_live : L.picks_note_back} · ${L.picks_ver}: <code>${esc(e.version || "rules-v1")}</code></p>` : (mode === "live" ? `<p class="note">${L.live_pending}</p>` : "");
  const recent = D.tx.filter(x => x.tk).slice().sort((a, b) => b.fd.localeCompare(a.fd) || 0).slice(0, 15);
  return `<section class="card cons" id="cons">${consBody()}</section><div class="hero"><h1>${L.hero_h}</h1><p>${L.hero_p}</p></div>${statStrip()}
   <h2 id="picks">${L.picks_h}</h2>${mToggle()}${mStats("backtest_" + m, L.bt_lab)}${tabs}${meta}<div class="grid g2">${e && e.picks.length ? e.picks.map((p, i) => pickCard(p, i, e, both.has(p.ticker))).join("") : `<p>${L.no_picks}</p>`}</div>
   <h2>${L.latest_h}</h2>${txTable(recent, {cap: 15})}`;
}
let CW = /[?&]cw=30/.test(location.hash) ? "30" : "90";
const HON = new Set(["mr", "mrs", "ms", "miss", "hon", "dr", "md", "facs", "phd", "esq"]);
const ALIAS = {"tracey robert mann": "Tracey Mann"};
function nn(s) { const o = []; for (const w of String(s || "").split(/[\s,]+/).filter(Boolean)) { if (HON.has(w.toLowerCase().replace(/\./g, ""))) continue; if (!o.length || o[o.length-1].toLowerCase() !== w.toLowerCase()) o.push(w); } const n = o.join(" "); return ALIAS[n.toLowerCase()] || n; }
const fmt = (s, o) => s.replace(/\{(\w+)\}/g, (_, k) => o[k]);
const usd = v => { const a = Math.abs(v), x = a >= 1e6 ? `$${(a/1e6).toFixed(1)}M` : a >= 1e3 ? `$${Math.round(a/1e3)}K` : `$${Math.round(a)}`; return (v < 0 ? "−" : "") + x; };
function consRow(r, i, max, compact) {
  const L = t();
  const mlink = m => D.mById[m.id] ? `<a href="#/member/${esc(m.id)}">${esc(m.name)}</a>` : esc(m.name);
  const ty = x => `<span class="badge b-${x.ty}">${L.cs_ty[x.ty]}</span>`;
  const buyers = r.members.filter(m => m.side === "buy").map(m => m.name).join(", ");
  const tags = `${r.tk==="TSM"?` <span class="badge twtag">🇹🇼 ${L.cs_tw}</span>`:""}${!compact && r.conc ? ` <span class="badge b-warn" title="${Math.round(r.conc.share*100)}%">${esc(fmt(L.cs_conc, {m: r.conc.name}))}</span>` : ""}${r.open_ended ? ` <span class="badge b-gray">${L.cs_open}</span>` : ""}`;
  const sub = compact ? `<small><b>${esc(fmt(L.cs_by, {m: buyers}))}</b> · ${esc(r.name)}</small>` : `<small>${esc(r.tk==="TSM" && LANG==="zh" ? "台積電 · " + r.name : r.name)}</small>`;
  return `<details ${!compact && i===0 && /[?&]open=1/.test(location.hash) ? "open" : ""} class="crow${compact?" cmp":""}${r.tk==="TSM"?" tw":""}"><summary><span class="rank">${i+1}</span>
    <span class="ct"><a class="tk" href="#/ticker/${encodeURIComponent(r.tk)}">${esc(r.tk)}</a>${tags}${sub}</span>
    <span class="cbar"><i style="width:${Math.max(2, r.net/max*100)}%"></i></span>
    <span class="cn"><b>${fmt(L.cs_net, {x: usd(r.net)})}</b><small class="mu">${fmt(L.cs_rng, {a: usd(r.net_min), b: usd(r.net_max)})}</small><small><span class="pos">${fmt(L.cs_bs, {b: r.buy, s: "</span><span class=neg>" + r.sell})}</span></small></span></summary>
    <ul class="cms">${r.members.map(m => `<li class="${m.side}"><span class="who">${mlink(m)} <span class="mu">${esc(m.st||"")}</span> <span class="badge ${m.side==="buy"?"b-P":"b-S"}">${m.side==="buy" ? L.cs_buyer : L.cs_seller}</span>${m.sold_after_buy ? ` <span class="badge b-warn">${L.cs_sold}</span>` : ""}</span><span>${m.tx.map(x => `<span class="ctx">${ty(x)} <span class="nw">${esc(x.td||x.fd||"")}</span> · <span class="nw">${esc(x.am)}</span>${x.ow && L.cs_owner[x.ow] ? ` <span class="badge b-gray">${L.cs_owner[x.ow]}</span>` : ""}</span>`).join("")}</span></li>`).join("")}</ul></details>`;
}
function consBody() {
  const L = t(), C = D.consensus; if (!C) return "";
  const W = C[CW], max = Math.max(1, ...W.rows.map(r => r.net)), maxB = Math.max(1, ...(W.big || []).map(r => r.net));
  const tabs = `<div class="tabs">${["90","30"].map(w => `<button data-cw="${w}" class="${w===CW?"on":""}">${fmt(L.cs_d, {n: w})}</button>`).join("")}</div>`;
  return `<div class="chd"><div><h2>${L.cs_h}</h2><p class="note">${fmt(L.cs_sub, {w: CW, d: esc(C.latest)})}</p></div>${tabs}</div>
   <h3 class="csh">${L.cs_main}</h3><p class="note">${L.cs_main_sub}</p>
   ${W.rows.map((r, i) => consRow(r, i, max, false)).join("") || `<p>${L.cs_none}</p>`}
   ${W.heavy ? `<p class="note"><b>${fmt(L.cs_heavy, {m: esc(W.heavy.name), n: W.heavy.n})}</b></p>` : ""}
   <div id="cs-big"><h3 class="csh">${L.cs_big}</h3><p class="note">${L.cs_big_sub}</p>
   ${(W.big || []).map((r, i) => consRow(r, i, maxB, true)).join("") || `<p>${L.cs_none}</p>`}</div>
   <p class="note">${L.cs_disc}</p>`;
}
function wireCons() { document.querySelectorAll("[data-cw]").forEach(b => b.onclick = () => { CW = b.dataset.cw; $("#cons").innerHTML = consBody(); wireCons(); }); }
function vMembers() {
  const L = t().th;
  return `<h1>${t().members_h}</h1><p class="sub">${t().members_p}</p><input class="search" data-filter="mem" placeholder="${t().search}">
  <div class="tw"><table id="memtab"><thead><tr><th class="s" data-sort="0">${L.name}</th><th class="s" data-sort="1">${L.dst}</th><th class="s" data-sort="2">${L.filings}</th><th class="s" data-sort="3">${L.tx}</th><th class="s" data-sort="4">${L.buy}</th><th class="s" data-sort="5">${L.sell}</th><th class="s" data-sort="6">${L.last}</th></tr></thead><tbody>` +
  D.members.map(m => `<tr data-s="${esc((m.name + " " + m.state_dst).toLowerCase())}"><td><a href="#/member/${esc(m.id)}">${esc(m.name)}</a></td><td>${esc(m.state_dst)}</td><td>${m.filings.length}</td><td>${m.n_tx}</td><td>${m.n_buy}</td><td>${m.n_sell}</td><td class="nw">${esc(m.last)}</td></tr>`).join("") + `</tbody></table></div>`;
}
function statBox(s, label) {
  const L = t();
  if (!s || !s.n) return `<div class="card"><div class="h" style="color:var(--acc);font-weight:700;font-size:13px">${label}</div><b style="font-size:20px">—</b><div class="note">${L.insuff} (n=0)</div></div>`;
  return `<div class="card"><div class="h" style="color:var(--acc);font-weight:700;font-size:13px">${label}</div><b class="${cls(s.mean_excess)}" style="font-size:28px">${fmtPct(s.mean_excess, 2)}</b>${s.insufficient ? `<span class="ins">${L.insuff}</span>` : ""}
   <div class="note">${L.win}: <b>${(s.win_rate * 100).toFixed(1)}%</b> · ${L.median}: ${fmtPct(s.median_excess, 2)} · ${L.n_label} n=<b>${s.n}</b>${s.se != null ? ` · ±${(s.se * 100).toFixed(2)}% s.e.` : ""}</div></div>`;
}
function vMember(id) {
  const m = D.mById[id]; if (!m) return `<p>not found</p>`; const L = t();
  const rows = D.tx.filter(x => x.m === id).sort((a, b) => (b.td || "").localeCompare(a.td || ""));
  return `<div class="crumb"><a href="#/members">${L.back}</a></div><h1>${esc(m.name)} <span class="mu" style="font-size:16px">${esc(m.state_dst)}</span></h1>
  <div class="stats"><div class="stat"><b>${m.filings.length}</b><span>${L.th.filings}</span></div><div class="stat"><b>${m.n_tx}</b><span>${L.th.tx}</span></div><div class="stat"><b>${m.n_buy} / ${m.n_sell}</b><span>${L.th.buy} / ${L.th.sell}</span></div></div>
  <div class="grid g3" style="margin-top:12px">${statBox(m.perf30, L.perf30)}</div>
  <h2>${L.filings_h}</h2><div class="tw"><table><thead><tr><th>${L.th.filed}</th><th>${L.th.doc}</th><th>${L.th.kind}</th><th>${L.th.n}</th><th>${L.th.pdf}</th></tr></thead><tbody>` +
  m.filings.map(f => `<tr><td class="nw">${esc(f.date)}</td><td>${esc(f.doc)}</td><td>${f.kind === "text" ? `<span class="badge b-gray">${L.text_pdf}</span>` : `<span class="badge b-warn">${L.scanned_pdf}</span>`}</td><td>${f.n ?? "—"}</td><td>${pdfLink(f.pdf)}</td></tr>`).join("") + `</tbody></table></div>
  <h2>${L.tx_h} (${rows.length})</h2>${txTable(rows, {noMember: true})}`;
}
function vTickers() {
  const L = t().th;
  return `<h1>${t().nav.tickers}</h1><input class="search" data-filter="tk" placeholder="${t().search}">
  <div class="tw"><table id="tktab"><thead><tr><th>${L.ticker}</th><th>${L.name2}</th><th>${L.tx}</th><th>${L.members}</th><th>${L.buy}</th><th>${L.sell}</th><th>${L.last}</th><th>${L.px}</th></tr></thead><tbody>` +
  D.tickers.map(x => `<tr data-s="${esc((x.tk + " " + x.name).toLowerCase())}"><td><a href="#/ticker/${encodeURIComponent(x.tk)}"><b>${esc(x.tk)}</b></a></td><td>${esc(x.name.slice(0, 70))}</td><td>${x.n}</td><td>${x.ms}</td><td>${x.buy}</td><td>${x.sell}</td><td class="nw">${esc(x.last)}</td><td>${x.el ? `<span class="badge ${x.px === "ok" ? "b-P" : "b-gray"}">${esc(t().pxs[x.px] || x.px)}</span>` : `<span class="badge b-gray" title="${esc(x.why)}">${esc(t().reasons[x.why] || x.why)}</span>`}</td></tr>`).join("") + `</tbody></table></div>`;
}
async function vTicker(tk) {
  const x = D.tById[tk]; if (!x) return `<p>not found</p>`; const L = t();
  const rows = D.tx.filter(r => r.tk === tk).sort((a, b) => (b.td || "").localeCompare(a.td || ""));
  let chart = "";
  if (x.el && x.px === "ok") { await loadPx(); chart = priceChart(tk, rows); }
  const ex = !x.el ? `<div class="card" style="margin:12px 0"><b>${L.excluded}</b> — ${L.why_ex}: ${esc(L.reasons[x.why] || x.why)}</div>` : "";
  return `<div class="crumb"><a href="#/tickers">${L.back}</a></div><h1>${esc(tk)} <span class="mu" style="font-size:16px">${esc(x.name.slice(0, 80))}</span></h1>
  <div class="stats"><div class="stat"><b>${x.n}</b><span>${L.th.tx}</span></div><div class="stat"><b>${x.ms}</b><span>${L.th.members}</span></div><div class="stat"><b>${x.buy} / ${x.sell}</b><span>${L.th.buy} / ${L.th.sell}</span></div></div>${ex}
  ${chart ? `<h2>${L.price_h}</h2><div class="card">${chart}</div>` : ""}
  <h2>${L.tx_h} (${rows.length})</h2>${txTable(rows, {noTicker: true})}`;
}
function priceChart(tk, rows) {
  const cal = D.meta.calendar, c = PX[tk]?.c, s = PX.SPY.c; if (!c) return "";
  const W = 1000, H = 260, pad = 36, first = c.findIndex(v => v != null); if (first < 0) return "";
  const nrm = arr => arr.map(v => v == null ? null : v / arr[first] * 100);
  const a = nrm(c), b = nrm(s); const vals = a.concat(b).filter(v => v != null);
  const lo = Math.min(...vals), hi = Math.max(...vals), X = i => pad + (W - pad - 8) * i / (cal.length - 1), Y = v => 8 + (H - 30) * (1 - (v - lo) / (hi - lo || 1));
  const line = (arr, col, sw) => { let d = "", on = false; arr.forEach((v, i) => { if (v == null) { on = false; return; } d += (on ? "L" : "M") + X(i).toFixed(1) + " " + Y(v).toFixed(1); on = true; }); return `<path d="${d}" fill="none" stroke="${col}" stroke-width="${sw}"/>`; };
  const idx = d => { let i = cal.findIndex(x => x >= d); return i < 0 ? null : i; };
  const ticks = rows.map(r => { const i = idx(r.fd); if (i == null) return ""; const col = r.ty === "P" ? "#0b8f5a" : r.ty === "E" ? "#888" : "#c4372f"; return `<line x1="${X(i)}" x2="${X(i)}" y1="${H - 22}" y2="${H - 8}" stroke="${col}" stroke-width="2.5" opacity=".75"/>`; }).join("");
  const mo = []; cal.forEach((d, i) => { if (i === 0 || d.slice(5, 7) !== cal[i - 1].slice(5, 7)) mo.push(`<text x="${X(i)}" y="${H}" font-size="11" fill="#6a7088">${d.slice(0, 7)}</text>`); });
  return `<svg viewBox="0 0 ${W} ${H + 4}" style="width:100%;height:auto"><text x="4" y="${Y(hi) + 10}" font-size="11" fill="#6a7088">${hi.toFixed(0)}</text><text x="4" y="${Y(lo)}" font-size="11" fill="#6a7088">${lo.toFixed(0)}</text>${line(b, "#aab0cf", 2)}${line(a, "#3b4bd8", 2.4)}${ticks}${mo.join("")}</svg>
  <div class="legend"><span style="color:#3b4bd8">━ ${esc(tk)}</span><span style="color:#8d94b8">━ SPY</span><span style="color:#0b8f5a">▮ ${t().ty.P}</span><span style="color:#c4372f">▮ ${t().ty.S}</span><span>(indexed = 100)</span></div>`;
}
function perfRow(label, s, hz) { return `<tr><td>${label}</td>${["5","30","90"].map(h => { const v = s[h]; return v && v.n ? `<td>${(v.win_rate*100).toFixed(1)}% / ${pctSpan(v.mean_excess,2)}<div class="mu" style="font-size:11.5px">n=${v.n}${v.insufficient ? ` <span class="ins">${t().insuff}</span>` : ""}${v.pending ? ` · ${v.pending} ${t().pending}` : ""}</div></td>` : `<td class="mu">${t().insuff}<div style="font-size:11.5px">n=0${v && v.pending ? ` · ${v.pending} ${t().pending}` : ""}</div></td>`; }).join("")}</tr>`; }
function hist(h) {
  const W = 760, H = 170, n = h.counts.length, mx = Math.max(...h.counts, 1), bw = (W - 20) / n;
  const bars = h.counts.map((c, i) => `<rect x="${10 + i * bw + 1}" y="${H - 22 - (H - 40) * c / mx}" width="${bw - 2}" height="${(H - 40) * c / mx}" rx="2" fill="${h.edges[i] >= 0 ? "#18b58b" : "#e07a72"}"/>`).join("");
  const z = 10 + n / 2 * bw;
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto">${bars}<line x1="${z}" x2="${z}" y1="6" y2="${H - 20}" stroke="#14182b" stroke-dasharray="3 3"/><text x="10" y="${H - 5}" font-size="11" fill="#6a7088">−30%</text><text x="${z - 6}" y="${H - 5}" font-size="11" fill="#6a7088">0</text><text x="${W - 40}" y="${H - 5}" font-size="11" fill="#6a7088">+30%</text></svg>`;
}
function vTrack() {
  const L = t(), tr = D.track, ps = D.picks_scored;
  const kp = h => statBox(tr.purchases[h], `${h} ${L.hz}`);
  const sellRows = ["5","30","90"].map(h => { const s = tr.sales[h]; return `<td>${s.n ? `${L.underperf}: <b>${((1 - s.win_rate) * 100).toFixed(1)}%</b> · ${L.mean}: ${pctSpan(s.mean_excess, 2)}<div class="mu" style="font-size:11.5px">n=${s.n}</div>` : "—"}</td>`; }).join("");
  const m = getM(), ver = D.picks.methods[m].version;
  const picks = [["live_" + m, L.live_h], ["backtest_" + m, L.bt_lab]].map(([k, lab]) => {
    const d = ps && ps[k];
    if (!d || !d.n_events) return `<tr><td>${lab}</td><td colspan="3" class="mu">${L.live_none}</td></tr>`;
    return perfRow(`${lab}<div class="mu" style="font-size:11.5px">${d.n_events} unique picks · ${esc(ver)}</div>`, d.summary.from_public);
  }).join("");
  const cmpRow = (k, lab) => { const d = ps && ps[k]; return `<tr><td>${lab}</td>${["5","30","90"].map(h => `<td class="nw">${d ? statLine(d.summary.from_public[h]) : "—"}</td>`).join("")}</tr>`; };
  const cmp = `<h2>${L.cmp_h}</h2><div class="tw"><table class="cmp"><thead><tr><th></th>${["5","30","90"].map(h => `<th>${h} ${L.hz}<br><span style="font-weight:400">${L.mean} / ${L.median} / ${L.win}</span></th>`).join("")}</tr></thead><tbody>
    ${cmpRow("backtest_consensus", `<b>${L.m_cons}</b><div class="mu" style="font-size:11.5px">rules-v4</div>`)}${cmpRow("backtest_backtest_best", `<b>${L.m_v1}</b><div class="mu" style="font-size:11.5px">rules-v1</div>`)}${cmpRow("backtest_overlap", `<span class="badge bboth">${L.both}</span><div class="mu" style="font-size:11.5px">${L.ov_row}</div>`)}</tbody></table></div>
    <p class="note">${L.cmp_note} ${L.dropped}</p>`;
  return `<h1>${L.track_h}</h1><p class="sub">${L.track_p}</p>
  <h2>${L.tr_buy}</h2><div class="kpi">${["5","30","90"].map(kp).join("")}</div>
  <h2>${L.tr_hist}</h2><div class="card">${hist(tr.hist30)}</div>
  <h2>${L.tr_picks}</h2>${mToggle()}<div class="tw"><table><thead><tr><th></th>${["5","30","90"].map(h => `<th>${h} ${L.hz}<br><span style="font-weight:400">${L.win} / ${L.mean}</span></th>`).join("")}</tr></thead><tbody>${picks}</tbody></table></div>
  <p class="note">${D.picks.n_live} live frozen day(s), ${D.picks.n_backtest} backtest day(s) · hash chain: live ${D.picks.live_chain && D.picks.live_chain[0] ? "✓ verified" : "—"} · backtest ${D.picks.backtest_chain && D.picks.backtest_chain[0] ? "✓ verified" : "—"}</p>
  ${cmp}
  <h2>${L.tr_sell}</h2><div class="tw"><table><thead><tr>${["5","30","90"].map(h => `<th>${h} ${L.hz}</th>`).join("")}</tr></thead><tbody><tr>${sellRows}</tr></tbody></table></div>
  <h2>${L.caveats_h}</h2><div class="card"><ul class="why">${L.caveats.map(c => `<li>${esc(c)}</li>`).join("")}</ul></div>`;
}
function vAbout() {
  const L = t(); return `<h1>${L.about_h}</h1><div class="grid g2">${L.about.map(([h, b]) => `<div class="card"><h3>${esc(h)}</h3><p style="margin:0">${esc(b)}</p></div>`).join("")}</div>`;
}

/* ---------- interactions ---------- */
function wire() {
  wireCons();
  document.querySelectorAll("[data-mode]").forEach(b => b.onclick = () => setQ("mode", b.dataset.mode));
  document.querySelectorAll("[data-m]").forEach(b => b.onclick = () => { const y = scrollY; setQ("m", b.dataset.m === "v1" ? "v1" : null); requestAnimationFrame(() => scrollTo(0, y)); });
  document.querySelectorAll("input[data-filter]").forEach(i => i.oninput = () => { const q = i.value.toLowerCase(); document.querySelectorAll("tbody tr[data-s]").forEach(r => r.style.display = r.dataset.s.includes(q) ? "" : "none"); });
  document.querySelectorAll("th[data-sort]").forEach(th => th.onclick = () => { const tb = th.closest("table").tBodies[0], k = +th.dataset.sort, dir = th.dataset.d = th.dataset.d === "1" ? "-1" : "1";
    [...tb.rows].sort((a, b) => { const x = a.cells[k].textContent.trim(), y = b.cells[k].textContent.trim(), nx = parseFloat(x), ny = parseFloat(y); return (isNaN(nx) || isNaN(ny) ? x.localeCompare(y) : nx - ny) * dir; }).forEach(r => tb.appendChild(r)); });
  document.querySelectorAll("button.more").forEach(b => b.onclick = () => { /* simple: re-render full table in place */ const wrap = b.previousElementSibling; b.remove(); wrap.dataset.expanded = 1; moreRows(wrap); });
}
function moreRows(wrap) { /* rebuild with all rows for current route */
  const parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent); let rows, o = {};
  if (parts[0] === "member") { rows = D.tx.filter(x => x.m === parts[1]).sort((a, b) => (b.td || "").localeCompare(a.td || "")); o = {noMember: true}; }
  else if (parts[0] === "ticker") { rows = D.tx.filter(x => x.tk === parts[1]).sort((a, b) => (b.td || "").localeCompare(a.td || "")); o = {noTicker: true}; }
  else return; o.cap = 100000; const tmp = document.createElement("div"); tmp.innerHTML = txTable(rows, o); wrap.replaceWith(tmp.firstChild);
}
boot();
