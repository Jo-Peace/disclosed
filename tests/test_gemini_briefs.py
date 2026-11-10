"""Offline tests for Gemini brief helpers (no network, no API key)."""
import json
from disclosed.gemini_briefs import (
    parse_brief, content_hash, compare_vision, facts_blob, expand_allowed, _fresh, public_payload, fill,
    format_member_user, pick_facts,
)
from disclosed.summaries import validate


def test_parse_brief_labelled_blocks():
    zh, en = parse_brief("ZH-TW: 甲乙丙。這是公開申報資料，非投資建議，申報可在交易後 45 天內提出。\nEN: Alice bought TSM. This is public disclosure data, not investment advice.")
    assert "非投資建議" in zh and "not investment advice" in en
    assert zh.startswith("甲乙丙")


def test_parse_brief_rejects_incomplete():
    try:
        parse_brief("just some text without labels")
    except ValueError:
        return
    assert False, "expected ValueError"


def test_content_hash_is_stable():
    a = {"name": "Ada", "n": 2, "rows": [1, 2]}
    b = {"rows": [1, 2], "n": 2, "name": "Ada"}
    assert content_hash(a) == content_hash(b)
    assert content_hash(a) != content_hash({"name": "Ada", "n": 3, "rows": [1, 2]})


def test_compare_vision_overlap():
    extracted = [
        {"asset_name": "ServiceNow Inc", "tx_date": "2026-09-17", "amount_range": "$50,001 - $100,000"},
        {"asset_name": "Something illegible", "tx_date": "2020-01-01"},
    ]
    db = [
        {"asset": "SERVICENOW INC", "ticker": "NOW", "tx_type": "S (partial)", "tx_date": "2026-09-17", "amount_text": "$50,001 - $100,000"},
        {"asset": "CHIPOTLE MEXICAN GRILL I", "ticker": "CMG", "tx_type": "S (partial)", "tx_date": "2026-09-17", "amount_text": "$15,001 - $50,000"},
    ]
    c = compare_vision(extracted, db)
    assert c["name_overlaps"] == 1
    assert c["date_overlaps"] == 1
    assert c["agrees"] is True
    assert compare_vision([{"asset_name": "zzz", "tx_date": "1999-01-01"}], db)["agrees"] is False


def test_fresh_requires_matching_hash_and_ok_status():
    facts = {"hash": "abc"}
    assert _fresh({"status": "ok", "content_hash": "abc", "zh_tw": "一", "en": "a"}, facts)
    assert not _fresh({"status": "ok", "content_hash": "zzz", "zh_tw": "一", "en": "a"}, facts)
    assert not _fresh({"status": "rejected", "content_hash": "abc", "zh_tw": "一", "en": "a"}, facts)


def test_member_user_prompt_contains_counts_not_advice():
    facts = {
        "name": "Ada Lovelace", "state_dst": "CA00", "first_filing": "2026-02-01", "last_filing": "2026-10-01",
        "n_filings": 3, "n_tx": 9, "n_buy": 5, "n_sell": 4,
        "top_tickers": [{"ticker": "TSM", "n": 4}], "n_other_tickers": 2,
        "recent_tx": [{"tx_date": "2026-09-01", "type": "P", "ticker": "TSM", "asset": "TSMC", "amount": "$1,001 - $15,000"}],
        "n_scanned_filings": 1, "n_inferred_tickers": 0,
        "window_note": "Filings may be submitted up to 45 days after a trade. Amounts are ranges.",
    }
    u = format_member_user(facts)
    assert "Ada Lovelace" in u and "TSM (4 trades)" in u and "9 transaction" in u
    assert "buy" not in u.lower() or "recommend" not in u.lower()


def test_guardrail_accepts_grounded_brief():
    facts = {"name": "Ada", "ticker": "TSM", "n_tx": 2, "amount": "$1,001 - $15,000", "tx_date": "2026-10-09", "filed": "2026-10-22"}
    blob = facts_blob(facts)
    ok_en = "Ada disclosed a purchase of TSM on 2026-10-09, filed 2026-10-22, in the range $1,001 - $15,000. This is public disclosure data, not investment advice (45 days)."
    ok_zh = "Ada 申報於 2026-10-09 買入 TSM，已於 2026-10-22 送件，金額區間 $1,001 - $15,000。這是公開申報資料，非投資建議，申報可在交易後 45 天內提出。"
    assert validate(ok_en, blob, "en") == []
    assert validate(ok_zh, blob, "zh") == []
    assert validate("You should buy TSM because it will rise.", blob, "en")


def test_public_payload_drops_failures(tmp_path, monkeypatch):
    store = {
        "members": {
            "ada": {"status": "ok", "zh_tw": "甲。非投資建議。", "en": "A. Not investment advice.", "model": "gemini-2.5-flash", "checked": True},
            "bad": {"status": "rejected", "error": "nope", "zh_tw": "不要顯示", "en": "hide me"},
        },
        "picks": {},
        "vision": {"1": {"status": "ok", "doc_id": "1", "member_id": "ada", "member": "Ada", "state_dst": "CA00",
                         "filing_date": "2026-01-01", "pdf": "http://example", "zh_tw": "頁", "en": "page",
                         "rows": [{}], "compare": {"agrees": True}, "model": "gemini-2.5-flash"}},
        "meta": {"model": "gemini-2.5-flash"},
    }
    out = public_payload(store)
    assert "ada" in out["members"] and "bad" not in out["members"]
    assert out["n_members"] == 1 and out["n_vision"] == 1
    assert "error" not in json.dumps(out)


def test_fill_without_key_is_failsoft(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert fill() == 0


def test_expand_allowed_accepts_unpadded_day():
    blob = expand_allowed("filed 2026-11-05 amount $15,001 - $50,000")
    # 'November 5, 2026' yields numbers 5 and 5,
    assert "5" in blob.split()
    assert validate("Filed on November 5, 2026 for $15,001. This is not investment advice.", blob, "en") == []
