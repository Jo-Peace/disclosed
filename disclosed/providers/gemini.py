"""Google Gemini API provider (AI Studio / Gemini API).

Used by `disclosed.gemini_briefs` for free-tier text, JSON-schema and vision calls.
Auth: env GEMINI_API_KEY, sent only as the `x-goog-api-key` header — never logged, never written to cache keys as the raw secret.
Endpoint: POST {base}/models/{model}:generateContent
"""
from __future__ import annotations
import hashlib, json, os, random, threading, time
import requests
from .base import LLMProvider, LLMResult, FileInput, ProviderError, MissingCredentials
from .. import config

_lock = threading.Lock()
_last_call = 0.0


def _key() -> str | None:
    return os.environ.get(config.GEMINI_KEY_ENV) or None


def _ledger(rec: dict):
    with _lock:
        config.GEMINI_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with config.GEMINI_LEDGER.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _wait_interval():
    """Process-wide min interval between live (non-cache) Gemini calls."""
    global _last_call
    gap = float(os.environ.get("GEMINI_MIN_INTERVAL", config.GEMINI_MIN_INTERVAL))
    with _lock:
        now = time.time()
        wait = _last_call + gap - now
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()


class GeminiProvider(LLMProvider):
    name = "gemini"
    supports_pdf = False          # briefs pass a rendered page image, not a raw PDF
    supports_json_schema = True

    def __init__(self, **options):
        super().__init__(**options)
        self.base_url = options.get("base_url", config.GEMINI_BASE).rstrip("/")
        self.options.setdefault("model", config.GEMINI_MODEL)
        self.timeout = options.get("timeout", 60)
        self.max_retries = options.get("max_retries", 5)

    def available(self) -> bool:
        return bool(_key())

    def _parts(self, user: str, files: list[FileInput] | None):
        parts = [{"text": user}]
        for f in files or []:
            raw = open(f.path, "rb").read()
            import base64
            parts.append({"inline_data": {"mime_type": f.mime, "data": base64.b64encode(raw).decode()}})
        return parts

    def build_payload(self, *, system, user, schema, files, max_output_tokens) -> dict:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": self._parts(user, files)}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": max_output_tokens or self.options.get("max_output_tokens", 2048),
            },
        }
        if schema is not None:
            body["generationConfig"]["responseMimeType"] = "application/json"
            body["generationConfig"]["responseSchema"] = schema
        return body

    def generate(self, *, system: str, user: str, schema: dict | None = None, schema_name: str = "result",
                 files: list[FileInput] | None = None, reasoning_effort: str | None = None,
                 max_output_tokens: int | None = None, label: str = "") -> LLMResult:
        body = self.build_payload(system=system, user=user, schema=schema, files=files,
                                  max_output_tokens=max_output_tokens)
        # Cache key hashes the payload but strips inline image bytes down to a content hash so the cache file itself
        # is smaller and never needed as a secret store. The API key is not part of the hash.
        cache_body = json.loads(json.dumps(body))
        for part in cache_body["contents"][0]["parts"]:
            if "inline_data" in part:
                blob = part["inline_data"].get("data", "")
                part["inline_data"] = {"mime_type": part["inline_data"].get("mime_type"),
                                       "sha256": hashlib.sha256(blob.encode()).hexdigest(), "n": len(blob)}
        ck = hashlib.sha256(json.dumps({"model": self.model, "body": cache_body}, sort_keys=True).encode()).hexdigest()
        cf = config.GEMINI_CACHE / f"{ck}.json"
        if cf.exists():
            resp = json.loads(cf.read_text())
            _ledger({"ts": time.time(), "key": ck[:16], "label": label, "cached": True, "model": self.model, "cost_usd": 0.0})
            return self._result(resp, schema)

        key = _key()
        if not key:
            raise MissingCredentials(f"{config.GEMINI_KEY_ENV} is not set (create a free key in Google AI Studio).")

        url = f"{self.base_url}/models/{self.model}:generateContent"
        headers = {"Content-Type": "application/json", "x-goog-api-key": key}
        delay = 2.0
        r = None
        for attempt in range(self.max_retries):
            _wait_interval()
            try:
                r = requests.post(url, headers=headers, json=body, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt == self.max_retries - 1:
                    raise ProviderError(f"network error: {e}") from e
                time.sleep(delay + random.random()); delay *= 2; continue
            if r.status_code == 404:
                raise ProviderError(f"HTTP 404: {r.text[:300]}")
            if r.status_code in (429, 500, 502, 503, 504):
                wait = float(r.headers.get("Retry-After", delay)) + random.random()
                if attempt == self.max_retries - 1:
                    # Never include the request URL (it might have been logged with a key if someone used ?key=).
                    raise ProviderError(f"HTTP {r.status_code}: {r.text[:300]}")
                time.sleep(wait); delay = min(delay * 2, 60); continue
            if r.status_code == 400 and "API key" in r.text:
                raise MissingCredentials("HTTP 400: Gemini rejected the API key")
            if r.status_code in (401, 403):
                raise MissingCredentials(f"HTTP {r.status_code}: Gemini auth failed")
            if r.status_code >= 400:
                raise ProviderError(f"HTTP {r.status_code}: {r.text[:500]}")
            break
        resp = r.json()
        usage = (resp.get("usageMetadata") or {})
        _ledger({"ts": time.time(), "key": ck[:16], "label": label, "cached": False, "model": self.model,
                 "prompt_tokens": usage.get("promptTokenCount"), "output_tokens": usage.get("candidatesTokenCount"),
                 "total_tokens": usage.get("totalTokenCount"), "cost_usd": 0.0})
        config.GEMINI_CACHE.mkdir(parents=True, exist_ok=True)
        if resp.get("candidates"):
            cf.write_text(json.dumps(resp, ensure_ascii=False))
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
        return LLMResult(text=text, data=data, provider=self.name, model=resp.get("modelVersion", self.model),
                         usage=resp.get("usageMetadata") or {}, raw=resp)

    @staticmethod
    def extract_text(resp: dict) -> str:
        err = resp.get("error")
        if err:
            raise ProviderError(f"Gemini error: {err.get('message') or err}")
        cands = resp.get("candidates") or []
        if not cands:
            raise ProviderError(f"no candidates in response (promptFeedback={resp.get('promptFeedback')})")
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        if not text.strip():
            raise ProviderError("empty text in Gemini response")
        return text
