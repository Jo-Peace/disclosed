from __future__ import annotations
import sqlite3
from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS filings (
  doc_id TEXT PRIMARY KEY,
  year INTEGER, prefix TEXT, last TEXT, first TEXT, suffix TEXT,
  filing_type TEXT, state_dst TEXT, filing_date TEXT,       -- filing_date normalised ISO yyyy-mm-dd
  pdf_url TEXT,
  pdf_path TEXT, pdf_bytes INTEGER, downloaded_at TEXT, http_status INTEGER,
  kind TEXT,                -- 'text' | 'scanned' | 'unknown'
  text_chars INTEGER,
  rule_status TEXT,         -- 'ok' | 'partial' | 'fail' | NULL
  rule_n_tx INTEGER, rule_note TEXT,
  meta_status TEXT, meta_n_tx INTEGER
);
CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  doc_id TEXT NOT NULL REFERENCES filings(doc_id),
  source TEXT NOT NULL,     -- 'rule' | 'meta' (| other provider name)
  idx INTEGER,              -- order inside the filing
  owner TEXT,               -- SP / DC / JT / '' (self)
  asset TEXT, ticker TEXT, asset_type TEXT,   -- asset_type e.g. ST, OP, CS
  tx_type TEXT,             -- P | S | S(partial) | E
  tx_date TEXT, notif_date TEXT,              -- ISO
  amount_low INTEGER, amount_high INTEGER, amount_text TEXT,
  cap_gains_over_200 INTEGER,                 -- 1/0/NULL
  raw TEXT,
  UNIQUE(doc_id, source, idx)
);
CREATE INDEX IF NOT EXISTS tx_doc ON transactions(doc_id);
CREATE INDEX IF NOT EXISTS tx_ticker ON transactions(ticker);
CREATE TABLE IF NOT EXISTS prices (
  ticker TEXT NOT NULL, date TEXT NOT NULL, close REAL, adj_close REAL, volume REAL, source TEXT,
  PRIMARY KEY (ticker, date)
);
CREATE TABLE IF NOT EXISTS assets (
  ticker TEXT PRIMARY KEY,         -- as printed in the PTR
  norm_ticker TEXT,                -- symbol used for the price source (e.g. BRK.B -> BRK-B)
  eligible INTEGER NOT NULL,       -- 1 = listed common stock/ETF we try to price
  reason TEXT,                     -- why NOT eligible (or 'ok')
  n_tx INTEGER, asset_types TEXT, sample_name TEXT
);
CREATE TABLE IF NOT EXISTS price_fetch (
  ticker TEXT PRIMARY KEY, source TEXT, status TEXT,   -- ok | not_found | error | no_data
  fetched_at TEXT, n_rows INTEGER, first_date TEXT, last_date TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS performance (
  doc_id TEXT NOT NULL, ticker TEXT NOT NULL, tx_type TEXT NOT NULL,   -- one row per (filing, ticker, direction)
  public_date TEXT, entry_date TEXT, entry_px REAL, horizon INTEGER,
  exit_date TEXT, ret REAL, spy_ret REAL, excess REAL,
  status TEXT,                  -- ok | insufficient_data | no_prices | ineligible
  PRIMARY KEY (doc_id, ticker, tx_type, horizon)
);
-- MAGI results + daily picks log (filled by later steps)
CREATE TABLE IF NOT EXISTS magi_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT, doc_id TEXT, tx_idx INTEGER, created_at TEXT,
  result_json TEXT, consensus TEXT, confidence REAL, disagreement INTEGER
);
CREATE TABLE IF NOT EXISTS picks_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, pick_date TEXT, frozen_at TEXT, doc_id TEXT, tx_idx INTEGER,
  ticker TEXT, payload_json TEXT, sha256 TEXT
);
"""

def connect(path=None) -> sqlite3.Connection:
    config.DATA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path or config.DB_PATH), timeout=90)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    cols = {r[1] for r in con.execute("PRAGMA table_info(transactions)")}
    for c, ddl in (("ticker_inferred", "INTEGER DEFAULT 0"), ("ticker_note", "TEXT")):
        if c not in cols: con.execute(f"ALTER TABLE transactions ADD COLUMN {c} {ddl}")
    # canonical rows: text PDFs -> rule parser rows; scanned PDFs -> Meta model rows (no rule parser possible)
    con.execute("DROP VIEW IF EXISTS tx")
    con.execute("""CREATE VIEW tx AS SELECT t.* FROM transactions t JOIN filings f USING(doc_id)
                   WHERE (f.kind!='scanned' AND t.source='rule') OR (f.kind='scanned' AND t.source='meta')""")
    con.commit()
    return con
