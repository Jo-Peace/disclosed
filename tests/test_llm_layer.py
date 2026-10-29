"""Offline tests for cost/cache/guardrail/ticker-matching logic (no network, no key needed)."""
import json
from disclosed.compare import _name
from disclosed.summaries import validate
from disclosed.tickermap import core, similar
from disclosed.providers import meta


def test_compare_name_normalisation():
    assert _name("Apple Inc. - Common Stock (AAPL) [ST]") == _name("Apple Inc. - Common Stock")
    assert _name("2000166568 SP California Cmnty Choice [GS]") == _name("California Cmnty Choice")

def test_ticker_name_matching_is_strict():
    assert similar(core("Honeywell International Inc."), core("HONEYWELL INTERNATIONAL INC CMN"))
    assert similar(core("Apple Incorporated"), core("Apple Inc."))
    assert not similar(core("Alphabet Incorporated"), core("Apple Inc."))
    assert not similar(core("First Trust"), core("First Solar Inc"))

def test_summary_guardrail():
    facts = "2026-10-09 $1,001 - $15,000 TSM 2026-10-22 45"
    ok = "Member X bought TSM on 2026-10-09 in the range $1,001 - $15,000. This is public disclosure data, not investment advice (45 days)."
    assert validate(ok, facts, "en") == []
    assert validate("You should buy TSM because it will rise.", facts, "en")
    assert any("not in provided facts" in p for p in validate("Bought 777 shares, not investment advice", facts, "en"))
    assert any("disclaimer" in p for p in validate("Member X bought TSM.", facts, "en"))

def test_cost_is_computed_from_usage(monkeypatch):
    c = meta._cost({"input_tokens": 1_000_000, "output_tokens": 1_000_000})
    assert abs(c - (meta.config.META_PRICE_IN + meta.config.META_PRICE_OUT)) < 1e-9
