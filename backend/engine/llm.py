"""Optional LLM providers (plain HTTP, no SDKs). Attesta works fully without any of them."""
from __future__ import annotations

import httpx

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o-mini",
    "ollama": "llama3.1",
}


class LLMError(RuntimeError):
    pass


def complete(settings: dict, system: str, user: str, max_tokens: int = 1200,
             transport: httpx.BaseTransport | None = None) -> str:
    provider = settings.get("provider", "offline")
    model = settings.get("model") or DEFAULT_MODELS.get(provider, "")
    key = settings.get("api_key", "")
    try:
        with httpx.Client(timeout=90, transport=transport) as http:
            if provider == "anthropic":
                if not key:
                    raise LLMError("Add your Anthropic API key in Settings.")
                r = http.post("https://api.anthropic.com/v1/messages",
                              headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                              json={"model": model, "max_tokens": max_tokens, "system": system,
                                    "messages": [{"role": "user", "content": user}]})
                _raise(r)
                return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
            if provider == "openai":
                if not key:
                    raise LLMError("Add your OpenAI API key in Settings.")
                r = http.post("https://api.openai.com/v1/chat/completions",
                              headers={"Authorization": f"Bearer {key}"},
                              json={"model": model, "max_tokens": max_tokens, "temperature": 0.4,
                                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
                _raise(r)
                return r.json()["choices"][0]["message"]["content"]
            if provider == "ollama":
                base = (settings.get("ollama_url") or "http://localhost:11434").rstrip("/")
                r = http.post(f"{base}/api/chat", json={"model": model, "stream": False,
                                                        "messages": [{"role": "system", "content": system},
                                                                     {"role": "user", "content": user}]})
                _raise(r)
                return r.json()["message"]["content"]
    except httpx.HTTPError as e:
        raise LLMError(f"Could not reach {provider}: {e.__class__.__name__}") from e
    raise LLMError("No LLM provider configured.")


def _raise(r: httpx.Response):
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {})
            msg = msg.get("message") if isinstance(msg, dict) else str(msg)
        except Exception:  # noqa: BLE001
            msg = r.text[:200]
        raise LLMError(f"LLM API error {r.status_code}: {msg}")
