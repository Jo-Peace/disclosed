from __future__ import annotations
import os
from pathlib import Path

ROOT = Path(os.environ.get("DISCLOSED_HOME", Path(__file__).resolve().parent.parent))
DATA = ROOT / "data"
PDF_DIR = DATA / "pdfs"
DB_PATH = Path(os.environ.get("DISCLOSED_DB", DATA / "disclosed.sqlite"))
YEAR = int(os.environ.get("DISCLOSED_YEAR", "2026"))

BASE = "https://disclosures-clerk.house.gov/public_disc"
INDEX_URL = f"{BASE}/financial-pdfs/{{year}}FD.zip"
PTR_URL = f"{BASE}/ptr-pdfs/{{year}}/{{doc_id}}.pdf"

# Be polite: identify ourselves, rate-limit.
USER_AGENT = "DisclosedHackathonBot/0.1 (non-commercial STOCK Act digest; contact: set DISCLOSED_CONTACT)"
if os.environ.get("DISCLOSED_CONTACT"):
    USER_AGENT = USER_AGENT.replace("set DISCLOSED_CONTACT", os.environ["DISCLOSED_CONTACT"])
MIN_INTERVAL_SEC = float(os.environ.get("DISCLOSED_MIN_INTERVAL", "1.0"))

# Meta Model API
META_BASE_URL = os.environ.get("META_BASE_URL", "https://api.meta.ai/v1")
META_MODEL = os.environ.get("META_MODEL", "muse-spark-1.3")
META_KEY_ENV = "MODEL_API_KEY"  # name used by Meta docs; META_API_KEY also accepted

# Meta Model API pricing (USD per 1M tokens, standard mode, muse-spark-1.3; verify on dev.meta.ai pricing page) and spend guard
META_PRICE_IN = float(os.environ.get("META_PRICE_IN", "1.25"))
META_PRICE_OUT = float(os.environ.get("META_PRICE_OUT", "4.25"))    # output_tokens include reasoning tokens
MAX_SPEND_USD = float(os.environ.get("DISCLOSED_MAX_SPEND", "40"))
LLM_CACHE = DATA / "llm_cache"          # raw model responses keyed by request hash (never contains the API key)
LLM_LEDGER = DATA / "llm_ledger.jsonl"  # one line per call: tokens + estimated cost
