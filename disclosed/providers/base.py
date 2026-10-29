"""Provider interface. Every LLM backend (API or CLI) implements `LLMProvider.generate`.

MAGI roles and the PDF parser only talk to this interface, never to a vendor SDK, so a different AI can be
assigned to any role via config (see providers/registry.py and providers.toml)."""
from __future__ import annotations
import abc, json, os
from dataclasses import dataclass, field
from pathlib import Path


class ProviderError(RuntimeError):
    """Any provider failure (HTTP error, bad output, missing credential...)."""

class MissingCredentials(ProviderError):
    """Raised when the provider's API key / CLI is not available. Callers must STOP, never fall back to another AI silently."""


@dataclass
class FileInput:
    path: Path
    mime: str = "application/pdf"
    detail: str = "high"          # render quality hint for scanned docs ("low" | "high"); providers may ignore
    @property
    def filename(self) -> str:
        return Path(self.path).name


@dataclass
class LLMResult:
    text: str                      # raw text of the model answer
    data: dict | list | None       # parsed JSON when a schema was requested
    provider: str
    model: str
    usage: dict = field(default_factory=dict)
    raw: dict | None = None        # full raw response for audit logs


class LLMProvider(abc.ABC):
    """Subclass this. Set `name`; implement `generate` (and `available`)."""
    name: str = "base"
    supports_pdf: bool = False          # can accept FileInput(PDF) natively
    supports_json_schema: bool = False  # can force schema-constrained JSON natively

    def __init__(self, **options):
        self.options = options

    @property
    def model(self) -> str:
        return self.options.get("model", "unknown")

    def available(self) -> bool:
        """True if credentials/binaries are present. Must not make network calls."""
        return True

    @abc.abstractmethod
    def generate(self, *, system: str, user: str, schema: dict | None = None, schema_name: str = "result",
                 files: list[FileInput] | None = None, reasoning_effort: str | None = None,
                 max_output_tokens: int | None = None, label: str = "") -> LLMResult:
        """Run one request. If `schema` is given the result MUST be JSON matching it, returned in `LLMResult.data`.
        Providers without native schema support should put the schema in the prompt, parse, and raise ProviderError on failure."""

    # helper for providers without native JSON mode
    @staticmethod
    def parse_json_loose(text: str):
        t = text.strip()
        if t.startswith("```"):
            t = t.strip("`")
            t = t[t.find("\n") + 1:] if "\n" in t else t
            t = t.rsplit("```", 1)[0]
        try:
            return json.loads(t)
        except json.JSONDecodeError:
            a, b = t.find("{"), t.rfind("}")
            if a >= 0 and b > a:
                return json.loads(t[a:b + 1])
            raise
