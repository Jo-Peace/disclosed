"""JSON schemas sent to the model (plain JSON Schema, non-recursive, depth < 10 as required by Meta's structured output)."""

TX_TYPES = ["P", "S", "S (partial)", "E"]
OWNERS = ["", "SP", "DC", "JT"]          # '' = filer; SP spouse; DC dependent child; JT joint

PTR_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "filing_id": {"type": ["string", "null"], "description": "Number after 'Filing ID #' at top of page 1"},
        "filer_name": {"type": ["string", "null"]},
        "state_district": {"type": ["string", "null"]},
        "transactions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "owner": {"type": "string", "enum": OWNERS,
                              "description": "Owner column: SP, DC, JT, or empty string when blank (filer)"},
                    "asset": {"type": "string", "description": "Asset name exactly as printed, without the [XX] code"},
                    "ticker": {"type": ["string", "null"], "description": "Ticker in parentheses if printed, else null. Never guess."},
                    "asset_type": {"type": ["string", "null"], "description": "Two-letter code inside [ ] e.g. ST, OP, GS, CS, HN"},
                    "tx_type": {"type": "string", "enum": TX_TYPES},
                    "tx_date": {"type": ["string", "null"], "description": "Transaction date YYYY-MM-DD"},
                    "notif_date": {"type": ["string", "null"], "description": "Notification date YYYY-MM-DD"},
                    "amount_text": {"type": "string", "description": "Amount range exactly as printed, e.g. '$1,001 - $15,000'"},
                    "amount_low": {"type": ["integer", "null"]},
                    "amount_high": {"type": ["integer", "null"], "description": "null for 'Over $X' ranges"},
                    "cap_gains_over_200": {"type": ["boolean", "null"], "description": "State of the 'Cap. Gains > $200?' checkbox; null if unreadable"},
                    "page": {"type": ["integer", "null"], "description": "Page number (1-based, within the attached file) where the row is printed"},
                    "subholding": {"type": ["string", "null"], "description": "Name of the account/trust/sub-holding heading the row sits under, if the form shows one; else null"},
                    "amount_column": {"type": ["string", "null"], "description": "For paper forms: the checked amount column letter A-K; null for electronic PDFs"},
                    "legible": {"type": "boolean", "description": "false if the row was hard to read (handwriting/scan quality)"},
                    "notes": {"type": ["string", "null"]},
                },
                "required": ["owner", "asset", "ticker", "asset_type", "tx_type", "tx_date", "notif_date",
                             "amount_text", "amount_low", "amount_high", "cap_gains_over_200", "page", "subholding", "amount_column", "legible", "notes"],
            },
        },
    },
    "required": ["filing_id", "filer_name", "state_district", "transactions"],
}

# ---- MAGI -------------------------------------------------------------------
VOTES = ["approve", "flag", "reject"]

def _items_schema(extra_props: dict, extra_required: list[str]) -> dict:
    props = {
        "idx": {"type": "integer", "description": "Transaction index as given in the input"},
        "vote": {"type": "string", "enum": VOTES},
        "confidence": {"type": "number", "description": "0.0 - 1.0"},
        "reasons": {"type": "array", "items": {"type": "string"}, "description": "short reasons, max 3"},
        **extra_props,
    }
    return {"type": "object", "additionalProperties": False, "properties": {
        "items": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                             "properties": props, "required": ["idx", "vote", "confidence", "reasons", *extra_required]}}},
        "required": ["items"]}

MAGI_PARSER_SCHEMA = _items_schema({
    "corrections": {"type": ["string", "null"], "description": "If you reject/flag: what field is wrong and what it should be"},
}, ["corrections"])

MAGI_RISK_SCHEMA = _items_schema({
    "risk_flags": {"type": "array", "items": {"type": "string",
        "enum": ["wide_amount_range", "partial_sale", "option_or_derivative", "non_stock_asset", "late_filing",
                 "spouse_or_dependent", "ticker_missing", "ambiguous_asset", "possible_misparse", "exchange_or_other", "none"]}},
}, ["risk_flags"])

MAGI_EXPLAINER_SCHEMA = _items_schema({
    "summary_zh_tw": {"type": "string", "description": "1-2 sentence plain-language description in Traditional Chinese (Taiwan). Neutral, factual, NO investment advice."},
    "summary_en": {"type": "string", "description": "Same in plain English. Neutral, factual, NO investment advice."},
}, ["summary_zh_tw", "summary_en"])
