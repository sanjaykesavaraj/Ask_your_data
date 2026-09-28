"""
OPTIONAL LLM BACK-END for Ask Your Data.

Design rules (these are the whole point of the project):
  1. The LLM is ALWAYS optional. With no key, the app runs 100% offline.
  2. The LLM only ever *proposes* SQL. Every statement - rules-generated or
     LLM-generated - goes through the identical validator in guardrails.py.
  3. A provider failure never crashes the app: we return (None, error) and the
     caller falls back to the rules engine.

Supported providers (all dependency-free, via urllib):
  * OpenAI                 https://api.openai.com/v1
  * Anthropic              https://api.anthropic.com/v1
  * Groq                   https://api.groq.com/openai/v1   (OpenAI-compatible)
  * Google Gemini          generativelanguage.googleapis.com
  * Ollama (local, free)   http://localhost:11434/v1        (OpenAI-compatible)
  * OpenAI-compatible      any server speaking /chat/completions
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

# provider -> (default base url, default model)
PRESETS = {
    "OpenAI": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "Groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "Ollama (local)": ("http://localhost:11434/v1", "qwen2.5-coder:7b"),
    "OpenAI-compatible": ("https://api.openai.com/v1", "gpt-4o-mini"),
}
ANTHROPIC_MODEL = "claude-sonnet-4-6"
GEMINI_MODEL = "gemini-2.0-flash"
TIMEOUT = 60


@dataclass
class LlmConfig:
    provider: str
    api_key: str = ""
    model: str = ""
    base_url: str = ""

    @property
    def enabled(self) -> bool:
        if not self.provider or self.provider.startswith("Off"):
            return False
        # Ollama needs no key; everyone else does
        return bool(self.api_key) or self.provider.startswith("Ollama")

    @classmethod
    def from_env(cls) -> "LlmConfig":
        """Build a config from environment variables (no UI needed)."""
        if os.environ.get("OPENAI_API_KEY"):
            # OPENAI_BASE_URL lets you point at Azure, OpenRouter, a proxy, or a
            # local mock server without touching code.
            return cls("OpenAI", os.environ["OPENAI_API_KEY"],
                       os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
                       os.environ.get("OPENAI_BASE_URL", ""))
        if os.environ.get("ANTHROPIC_API_KEY"):
            return cls("Anthropic", os.environ["ANTHROPIC_API_KEY"],
                       os.environ.get("ANTHROPIC_MODEL", ANTHROPIC_MODEL))
        if os.environ.get("GEMINI_API_KEY"):
            return cls("Google Gemini", os.environ["GEMINI_API_KEY"],
                       os.environ.get("GEMINI_MODEL", GEMINI_MODEL))
        return cls("Off (rules only)")


def strip_fences(text: str) -> str:
    """Models love ```sql fences. Return the bare statement."""
    if not text:
        return ""
    t = text.strip()
    m = re.search(r"```(?:sql)?\s*(.*?)```", t, flags=re.S)
    if m:
        t = m.group(1)
    t = t.strip()
    # drop a leading "SQL:" the model sometimes emits
    t = re.sub(r"^(?:sql|query)\s*:\s*", "", t, flags=re.I)
    return t.strip().rstrip(";").strip()


def _post(url: str, payload: dict, headers: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode())


def complete(provider: str, api_key: str, model: str, base_url: str,
             system: str, user: str) -> str:
    """Send one chat request. Raises on failure - caller handles it."""
    headers = {"Content-Type": "application/json"}

    # ---------------- Anthropic ----------------
    if provider == "Anthropic":
        headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
        out = _post("https://api.anthropic.com/v1/messages", {
            "model": model or ANTHROPIC_MODEL,
            "max_tokens": 1000,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }, headers)
        return "".join(b.get("text", "") for b in out.get("content", []))

    # ---------------- Google Gemini ----------------
    if provider == "Google Gemini":
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{model or GEMINI_MODEL}:generateContent?key={api_key}")
        out = _post(url, {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0, "maxOutputTokens": 1000},
        }, headers)
        cands = out.get("candidates") or []
        if cands:
            parts = cands[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts)
        return ""

    # ---------------- OpenAI / Groq / Ollama / compatible ----------------
    base = (base_url or PRESETS.get(provider, ("", ""))[0]).rstrip("/")
    if provider in PRESETS and not base_url:
        base = PRESETS[provider][0]
    if not base:
        raise ValueError(f"No base URL configured for provider {provider!r}")
    url = f"{base}/chat/completions"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    out = _post(url, {
        "model": model or PRESETS.get(provider, ("", "gpt-4o-mini"))[1],
        "temperature": 0,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }, headers)
    return out["choices"][0]["message"]["content"]


def generate_sql(question: str, cfg: LlmConfig, prompt_builder) -> tuple[str | None, str | None]:
    """Ask the configured provider for SQL.

    Returns (sql, error). Never raises - so a dead provider degrades to rules.
    """
    if not cfg.enabled:
        return None, "LLM back-end not configured"
    try:
        system, user = prompt_builder(question)
        raw = complete(cfg.provider, cfg.api_key, cfg.model, cfg.base_url,
                       system, user)
        sql = strip_fences(raw)
        if not sql:
            return None, "Model returned an empty response"
        return sql, None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        return None, f"{cfg.provider} HTTP {e.code}: {body}"
    except urllib.error.URLError as e:
        return None, f"Could not reach {cfg.provider} ({e.reason})"
    except Exception as e:
        return None, f"{cfg.provider} error: {type(e).__name__}: {e}"
