"""Plumbing tests for deterministic logic only (no model calls, no fabricated model output)."""
from disclosed.magi import aggregate

def v(vote, c=0.9): return {"vote": vote, "confidence": c}

def test_unanimous():
    a = aggregate({"parser": v("approve"), "risk": v("approve"), "explainer": v("approve")})
    assert a["consensus"] == "approved" and not a["disagreement"] and a["confidence"] == 0.9

def test_dissent():
    a = aggregate({"parser": v("approve"), "risk": v("reject"), "explainer": v("approve")})
    assert a["consensus"] == "approved_with_dissent" and a["disagreement"]

def test_rejected():
    a = aggregate({"parser": v("reject"), "risk": v("reject"), "explainer": v("approve")})
    assert a["consensus"] == "rejected"

def test_missing_role():
    a = aggregate({"parser": v("approve"), "risk": None, "explainer": v("approve")})
    assert a["consensus"] == "needs_review" and a["disagreement"]

def test_rule_meta_mismatch_lowers_confidence():
    a = aggregate({"parser": v("approve"), "risk": v("approve"), "explainer": v("approve")}, rule_meta_mismatch=True)
    assert a["disagreement"] and a["confidence"] < 0.9

def test_one_approve_two_flags_is_caveat():
    a = aggregate({"parser": v("flag"), "risk": v("approve"), "explainer": v("flag")})
    assert a["consensus"] == "approved_with_caveat" and a["disagreement"]

def test_three_flags_needs_review():
    a = aggregate({"parser": v("flag"), "risk": v("flag"), "explainer": v("flag")})
    assert a["consensus"] == "needs_review"
