"""One wrapper for every LLM call, with a disk cache.

Why the cache matters for judging:
- Reproducible: re-running an eval gives identical outputs (Engineering Quality).
- Cheap and fast: re-scoring after a metric change costs nothing.

Works with any OpenAI-compatible endpoint (OpenAI, HUMAIN/ALLaM if exposed that way,
Groq, Together, local vLLM/Ollama...) via LLM_BASE_URL, plus native Anthropic.
Set LLM_PROVIDER=openai|anthropic in .env.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

CACHE_DIR = Path(os.getenv("LLM_CACHE_DIR", ".cache/llm"))
STATS = {"calls": 0, "cache_hits": 0, "input_tokens": 0, "output_tokens": 0, "seconds": 0.0}


def _key(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def call_llm(
    prompt: str | list[dict],
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    system: str | None = None,
    use_cache: bool = True,
    retries: int = 3,
) -> str:
    provider = os.getenv("LLM_PROVIDER", "openai")
    model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")
    messages = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else prompt
    payload = {"provider": provider, "model": model, "messages": messages, "system": system,
               "temperature": temperature, "max_tokens": max_tokens}
    path = CACHE_DIR / f"{_key(payload)}.json"

    STATS["calls"] += 1
    if use_cache and path.exists():
        STATS["cache_hits"] += 1
        return json.loads(path.read_text())["text"]

    t0 = time.time()
    for attempt in range(retries):
        try:
            text, usage = _call(provider, model, messages, system, temperature, max_tokens)
            break
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    STATS["seconds"] += time.time() - t0
    STATS["input_tokens"] += usage.get("input", 0)
    STATS["output_tokens"] += usage.get("output", 0)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"payload": payload, "text": text}, ensure_ascii=False))
    return text


def _call(provider, model, messages, system, temperature, max_tokens):
    if provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic()
        kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)  # newer Claude models don't take temperature; the cache keeps runs reproducible
        text = "".join(b.text for b in resp.content if b.type == "text")
        return text, {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}

    from openai import OpenAI

    client = OpenAI(base_url=os.getenv("LLM_BASE_URL") or None, api_key=os.getenv("LLM_API_KEY"))
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    resp = client.chat.completions.create(model=model, messages=msgs, temperature=temperature,
                                          max_tokens=max_tokens)
    u = resp.usage
    return resp.choices[0].message.content or "", {
        "input": getattr(u, "prompt_tokens", 0), "output": getattr(u, "completion_tokens", 0)}


def reset_stats() -> None:
    for k in STATS:
        STATS[k] = 0 if k != "seconds" else 0.0
