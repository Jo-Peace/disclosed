"""EXAMPLE / STUB - not used in the hackathon submission and never selected by default.

Wrap any command-line AI (claude -p, gemini -p, ollama run, llm, codex exec ...) as a provider: the prompt goes to
stdin, the answer is read from stdout. The JSON schema is embedded in the prompt (no native constrained decoding).

    [providers.claude_cli]
    class = "disclosed.providers.examples.cli_tool:CliProvider"
    command = ["claude", "-p"]
    model = "cli-default"

    [roles]
    explainer = "claude_cli"
"""
from __future__ import annotations
import json, shutil, subprocess
from ..base import LLMProvider, LLMResult, ProviderError, MissingCredentials


class CliProvider(LLMProvider):
    name = "cli"
    supports_pdf = False
    supports_json_schema = False

    def available(self) -> bool:
        cmd = self.options.get("command") or []
        return bool(cmd) and shutil.which(cmd[0]) is not None

    def generate(self, *, system, user, schema=None, schema_name="result", files=None, reasoning_effort=None,
                 max_output_tokens=None, label: str = "") -> LLMResult:
        if not self.available():
            raise MissingCredentials(f"CLI not found: {self.options.get('command')}")
        if files:
            raise ProviderError("CLI stub does not support file inputs")
        prompt = f"{system}\n\n{user}"
        if schema is not None:
            prompt += "\n\nReply with ONLY a JSON object that validates against this JSON Schema:\n" + json.dumps(schema)
        p = subprocess.run(self.options["command"], input=prompt, capture_output=True, text=True, timeout=self.options.get("timeout", 600))
        if p.returncode != 0:
            raise ProviderError(f"CLI exit {p.returncode}: {p.stderr[:300]}")
        data = self.parse_json_loose(p.stdout) if schema is not None else None
        return LLMResult(text=p.stdout, data=data, provider=self.name, model=self.model, raw={"stderr": p.stderr})
