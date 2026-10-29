"""EXAMPLE / STUB - not used in the hackathon submission and never selected by default.

Shows how to add any OpenAI-compatible Chat Completions API (OpenAI, Together, Fireworks, vLLM, Ollama, LM Studio...).
Enable it in providers.toml:

    [providers.openai_compat]
    class = "disclosed.providers.examples.openai_compat:OpenAICompatProvider"
    base_url = "http://localhost:11434/v1"
    model = "llama3.1"
    api_key_env = "OPENAI_API_KEY"          # may be unset for local servers

    [roles]
    risk = "openai_compat"                   # use it for ONE MAGI role only, for example

This stub is intentionally minimal and UNTESTED. Text-only: it does not send PDFs (supports_pdf = False),
so it can serve MAGI roles (which only need text) but not the `pdf_parser` role.
"""
from __future__ import annotations
import json, os
import requests
from ..base import LLMProvider, LLMResult, ProviderError, MissingCredentials


class OpenAICompatProvider(LLMProvider):
    name = "openai_compat"
    supports_pdf = False
    supports_json_schema = True      # via response_format=json_schema; falls back to prompt-level JSON if rejected

    def available(self) -> bool:
        return "api_key_env" not in self.options or bool(os.environ.get(self.options["api_key_env"]))

    def generate(self, *, system, user, schema=None, schema_name="result", files=None, reasoning_effort=None,
                 max_output_tokens=None, label: str = "") -> LLMResult:
        if files:
            raise ProviderError("openai_compat stub does not support file inputs; pass extracted text instead")
        key = os.environ.get(self.options.get("api_key_env", ""), "")
        headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})}
        body = {"model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if max_output_tokens:
            body["max_tokens"] = max_output_tokens
        if schema is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema}}
        r = requests.post(self.options["base_url"].rstrip("/") + "/chat/completions", headers=headers, json=body, timeout=300)
        if r.status_code >= 400:
            raise ProviderError(f"HTTP {r.status_code}: {r.text[:300]}")
        j = r.json()
        text = j["choices"][0]["message"]["content"]
        data = self.parse_json_loose(text) if schema is not None else None
        return LLMResult(text=text, data=data, provider=self.name, model=j.get("model", self.model), usage=j.get("usage", {}), raw=j)
