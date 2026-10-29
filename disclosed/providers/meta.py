"""Meta Model API provider (Muse Spark) - the DEFAULT and the only provider used in the hackathon submission.

Docs (verified 2026-10-28):
  base URL  https://api.meta.ai/v1      auth: Bearer $MODEL_API_KEY (keys look like LLM_<id>_<secret>)
  POST /responses   structured output: text.format = {"type":"json_schema","name":..,"schema":..,"strict":false}
  PDF input:        {"type":"input_file","filename":..,"file_data":"data:application/pdf;base64,..","detail":"low|high"}
  reasoning:        reasoning.effort in minimal|low|medium|high|xhigh|max  ("none" is rejected by Muse Spark)
  limits:           inline file <= 50MB; PDF text from first 100 pages, first 50 page images
"""
from __future__ import annotations
import base64, hashlib, json, os, random, threading, time
import requests
from .base import LLMProvider, LLMResult, FileInput, ProviderError, MissingCredentials
from .. import config


def _key() -> str | None:
    return os.environ.get(config.META_KEY_ENV) or os.environ.get("META_API_KEY")


class BudgetExceeded(RuntimeError):
    """Deliberately NOT a ProviderError: callers must not swallow it. Estimated spend passed DISCLOSED_MAX_SPEND."""

_lock = threading.Lock()

def spent_usd() -> float:
    if not config.LLM_LEDGER.exists():
        return 0.0
    tot = 0.0
    for line in config.LLM_LEDGER.read_text().splitlines():
        try:
            tot += json.loads(line).get("cost_usd", 0.0)
        except Exception:
            pass
    return tot

def _cost(usage: dict) -> float:
    return (usage.get("input_tokens", 0) * config.META_PRICE_IN + usage.get("output_tokens", 0) * config.META_PRICE_OUT) / 1e6

def _ledger(rec: dict):
    with _lock:
        config.LLM_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with config.LLM_LEDGER.open("a") as f:
            f.write(json.dumps(rec) + "\n")


class MetaProvider(LLMProvider):
    name = "meta"
    supports_pdf = True
    supports_json_schema = True

    def __init__(self, **options):
        super().__init__(**options)
        self.base_url = options.get("base_url", config.META_BASE_URL).rstrip("/")
        self.options.setdefault("model", config.META_MODEL)
        self.timeout = options.get("timeout", 300)
        self.max_retries = options.get("max_retries", 5)

    def available(self) -> bool:
        return bool(_key())

    # ------------------------------------------------------------------
    def build_request(self, *, system, user, schema, schema_name, files, reasoning_effort, max_output_tokens) -> dict:
        content = [{"type": "input_text", "text": user}]
        for f in files or []:
            b64 = base64.b64encode(Path_read(f.path)).decode()
            content.append({"type": "input_file", "filename": f.filename,
                            "file_data": f"data:{f.mime};base64,{b64}", "detail": f.detail})
        body = {
            "model": self.model,
            "input": [
                {"type": "message", "role": "system", "content": [{"type": "input_text", "text": system}]},
                {"type": "message", "role": "user", "content": content},
            ],
            "max_output_tokens": max_output_tokens or self.options.get("max_output_tokens", 16000),
        }
        effort = reasoning_effort or self.options.get("reasoning_effort")
        if effort:
            body["reasoning"] = {"effort": effort}
        if schema is not None:
            body["text"] = {"format": {"type": "json_schema", "name": schema_name, "schema": schema, "strict": False}}
        return body

    def generate(self, *, system, user, schema=None, schema_name="result", files=None, reasoning_effort=None,
                 max_output_tokens=None, label: str = "") -> LLMResult:
        body = self.build_request(system=system, user=user, schema=schema, schema_name=schema_name, files=files,
                                  reasoning_effort=reasoning_effort, max_output_tokens=max_output_tokens)
        ck = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        cf = config.LLM_CACHE / f"{ck}.json"
        if cf.exists():                                   # disk cache: identical request is never paid for twice
            resp = json.loads(cf.read_text())
            _ledger({"ts": time.time(), "key": ck[:16], "label": label, "cached": True, "model": resp.get("model"), "cost_usd": 0.0})
            return self._result(resp, schema)
        key = _key()
        if not key:
            raise MissingCredentials(f"{config.META_KEY_ENV} is not set (create a key in the Meta Model API dashboard).")
        if spent_usd() >= config.MAX_SPEND_USD:
            raise BudgetExceeded(f"estimated spend ${spent_usd():.2f} reached the cap ${config.MAX_SPEND_USD:.2f} (DISCLOSED_MAX_SPEND); stopping")
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        delay = 0.5
        for attempt in range(self.max_retries):
            try:
                r = requests.post(f"{self.base_url}/responses", headers=headers, json=body, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt == self.max_retries - 1:
                    raise ProviderError(f"network error: {e}") from e
                time.sleep(delay + random.random()); delay *= 2; continue
            if r.status_code in (429, 500, 502, 503, 504):
                wait = float(r.headers.get("Retry-After", delay)) + random.random()   # docs: exp. backoff + jitter
                if attempt == self.max_retries - 1:
                    raise ProviderError(f"HTTP {r.status_code}: {r.text[:300]}")
                time.sleep(wait); delay *= 2; continue
            if r.status_code == 401:
                raise MissingCredentials("HTTP 401 invalid_api_key")
            if r.status_code >= 400:
                raise ProviderError(f"HTTP {r.status_code}: {r.text[:500]}")
            break
        resp = r.json()
        usage = resp.get("usage", {})
        _ledger({"ts": time.time(), "key": ck[:16], "label": label, "cached": False, "model": resp.get("model"), "status": resp.get("status"),
                 "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
                 "reasoning_tokens": (usage.get("output_tokens_details") or {}).get("reasoning_tokens"), "cost_usd": _cost(usage)})
        config.LLM_CACHE.mkdir(parents=True, exist_ok=True)
        if resp.get("status") == "completed":
            cf.write_text(json.dumps(resp))
        return self._result(resp, schema)

    def _result(self, resp, schema) -> LLMResult:
        text = self.extract_text(resp)
        data = None
        if schema is not None:
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                try:
                    data = self.parse_json_loose(text)
                except Exception as e:
                    raise ProviderError(f"model did not return valid JSON: {text[:300]!r}") from e
        return LLMResult(text=text, data=data, provider=self.name, model=resp.get("model", self.model),
                         usage=resp.get("usage", {}), raw=resp)

    @staticmethod
    def extract_text(resp: dict) -> str:
        if resp.get("status") not in (None, "completed"):
            raise ProviderError(f"response status={resp.get('status')} incomplete={resp.get('incomplete_details')} error={resp.get('error')}")
        parts = []
        for item in resp.get("output", []):
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") == "output_text":
                        parts.append(c.get("text", ""))
        if not parts and isinstance(resp.get("output_text"), str):
            parts.append(resp["output_text"])
        if not parts:
            raise ProviderError("no output_text in response")
        return "".join(parts)


def Path_read(p) -> bytes:
    with open(p, "rb") as fh:
        return fh.read()
