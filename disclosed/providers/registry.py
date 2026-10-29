"""Resolve which provider serves which role.

Order of precedence for a role:  env DISCLOSED_PROVIDER_<ROLE>  >  providers.toml [roles]  >  "meta".
A provider name is looked up in BUILTIN, then in providers.toml [providers.<name>] (with `class = "pkg.mod:Class"`),
or can itself be a "pkg.mod:Class" spec."""
from __future__ import annotations
import importlib, os, tomllib
from pathlib import Path
from .base import LLMProvider, ProviderError
from .. import config

CONFIG_PATH = Path(os.environ.get("DISCLOSED_PROVIDERS_TOML", config.ROOT / "providers.toml"))
ROLES = ("pdf_parser", "parser", "risk", "explainer")

def _builtin():
    from .meta import MetaProvider
    return {"meta": MetaProvider}

def load_config() -> dict:
    if CONFIG_PATH.exists():
        return tomllib.loads(CONFIG_PATH.read_text())
    return {}

def _import(spec: str):
    mod, _, cls = spec.partition(":")
    return getattr(importlib.import_module(mod), cls)

def get_provider(name: str) -> LLMProvider:
    cfg = load_config().get("providers", {}).get(name, {})
    opts = {k: v for k, v in cfg.items() if k != "class"}
    builtin = _builtin()
    if cfg.get("class"):
        cls = _import(cfg["class"])
    elif name in builtin:
        cls = builtin[name]
    elif ":" in name:
        cls = _import(name)
    else:
        raise ProviderError(f"unknown provider {name!r}; known built-ins: {sorted(builtin)}; or define [providers.{name}] class=... in {CONFIG_PATH.name}")
    return cls(**opts)

def provider_name_for_role(role: str) -> str:
    env = os.environ.get(f"DISCLOSED_PROVIDER_{role.upper()}")
    if env:
        return env
    return load_config().get("roles", {}).get(role, "meta")

def provider_for_role(role: str) -> LLMProvider:
    return get_provider(provider_name_for_role(role))
