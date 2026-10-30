"""One wrapper for every LLM call, with a disk cache and honest cost accounting.

- Reproducible: re-running gives identical outputs (cache keyed on the full request).
- Honest cost: each cache entry stores the ORIGINAL token usage, so a cache hit still reports
  what the call cost when it was made. Reruns never look free.
- Provider-agnostic: callers pass a `role` (patient | triage | big); configs/models.json maps
  each role to a provider + model. `provider="openai"` means any OpenAI-compatible endpoint.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = Path(os.getenv("LLM_CACHE_DIR", ".cache/llm"))
MODELS_FILE = ROOT / "configs" / "models.json"
PRICES_FILE = ROOT / "configs" / "prices.json"

STATS: dict[str, Any] = {"calls": 0, "cache_hits": 0, "input_tokens": 0, "output_tokens": 0,
                         "cost_usd": 0.0, "seconds": 0.0, "unpriced_calls": 0}
_LOCK = threading.Lock()


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cached: bool
    priced: bool


@dataclass
class ToolLLMResult:
    """One assistant turn of a tool-use conversation. `content` is the raw list of content blocks
    (text / tool_use / thinking) as plain dicts, ready to be appended back to the messages."""
    content: list[dict[str, Any]]
    stop_reason: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cost_usd: float
    cached: bool
    priced: bool

    @property
    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.content if b.get("type") == "text")

    @property
    def tool_uses(self) -> list[dict[str, Any]]:
        return [b for b in self.content if b.get("type") == "tool_use"]


def load_roles() -> dict[str, dict[str, str]]:
    """Role -> provider/model from configs/models.json; NAJDA_MODELS=<path> swaps the file for one run."""
    data = json.loads(Path(os.getenv("NAJDA_MODELS") or MODELS_FILE).read_text())
    return {k: v for k, v in data.items() if not k.startswith("_")}


def role_model(role: str) -> tuple[str, str]:
    spec = load_roles()[role]
    return spec["provider"], spec["model"]


def cost_of(model: str, usage: dict[str, int]) -> tuple[float, bool]:
    """USD for one call. usage keys: input, output, cache_write, cache_read (token counts)."""
    prices = json.loads(PRICES_FILE.read_text())
    if model not in prices:
        return 0.0, False
    p = prices[model]
    tin, tout = usage.get("input", 0), usage.get("output", 0)
    cw, cr = usage.get("cache_write", 0), usage.get("cache_read", 0)
    rate_in, rate_out = p["input"], p["output"]
    long = p.get("long_context")
    if long and tin + cw + cr > long["over_input_tokens"]:
        rate_in, rate_out = long["input"], long["output"]
    usd = tin * rate_in + tout * rate_out + cw * p.get("cache_write", rate_in) + cr * p.get("cache_read", rate_in)
    return usd / 1_000_000, True


def _key(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def call_llm_ex(
    prompt: str | list[dict],
    role: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    system: str | None = None,
    use_cache: bool = True,
    retries: int = 3,
) -> LLMResult:
    if role:
        provider, model = role_model(role)
    provider = provider or os.getenv("LLM_PROVIDER", "openai")
    model = model or os.getenv("LLM_MODEL", "gpt-4o-mini")
    messages = [{"role": "user", "content": prompt}] if isinstance(prompt, str) else prompt
    payload = {"provider": provider, "model": model, "messages": messages, "system": system,
               "temperature": temperature, "max_tokens": max_tokens}
    path = CACHE_DIR / f"{_key(payload)}.json"

    cached = use_cache and path.exists()
    if cached:
        entry = json.loads(path.read_text())
        text, usage, seconds = entry["text"], entry.get("usage", {}), 0.0
    else:
        t0 = time.time()
        for attempt in range(retries):
            try:
                text, usage = _call(provider, model, messages, system, temperature, max_tokens)
                break
            except Exception:
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)
        seconds = time.time() - t0
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"payload": payload, "text": text, "usage": usage}, ensure_ascii=False))

    tin, tout = int(usage.get("input", 0)), int(usage.get("output", 0))
    cost, priced = cost_of(model, usage)
    with _LOCK:
        STATS["calls"] += 1
        STATS["cache_hits"] += int(cached)
        STATS["input_tokens"] += tin
        STATS["output_tokens"] += tout
        STATS["cost_usd"] += cost
        STATS["seconds"] += seconds
        STATS["unpriced_calls"] += int(not priced)
    return LLMResult(text, provider, model, tin, tout, cost, cached, priced)


def call_llm(prompt: str | list[dict], **kwargs: Any) -> str:
    return call_llm_ex(prompt, **kwargs).text


def call_llm_tools_ex(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    role: str = "big",
    system: str | None = None,
    max_tokens: int = 4096,
    effort: str = "medium",
    use_cache: bool = True,
    retries: int = 3,
) -> ToolLLMResult:
    """One assistant turn with the Anthropic tools API (tool_use blocks returned, not executed).
    Cache key covers tools + messages + system. Prompt caching: the request carries a top-level
    ephemeral cache_control, so the server caches the longest stable prefix (system + tools + the
    conversation so far) and each loop turn re-reads it at the cache-read rate."""
    provider, model = role_model(role)
    if provider != "anthropic":
        raise NotImplementedError("tool use is implemented for the anthropic provider only")
    payload = {"provider": provider, "model": model, "messages": messages, "system": system,
               "tools": tools, "max_tokens": max_tokens, "effort": effort}
    path = CACHE_DIR / f"{_key(payload)}.json"

    cached = use_cache and path.exists()
    if cached:
        entry = json.loads(path.read_text())
        content, stop_reason, usage, seconds = entry["content"], entry["stop_reason"], entry.get("usage", {}), 0.0
    else:
        t0 = time.time()
        for attempt in range(retries):
            try:
                content, stop_reason, usage = _call_tools(model, messages, system, tools, max_tokens, effort)
                break
            except Exception:
                if attempt == retries - 1:
                    raise
                time.sleep(2 ** attempt)
        seconds = time.time() - t0
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"payload": payload, "content": content, "stop_reason": stop_reason,
                                    "usage": usage}, ensure_ascii=False))

    tin = int(usage.get("input", 0)) + int(usage.get("cache_write", 0)) + int(usage.get("cache_read", 0))
    tout = int(usage.get("output", 0))
    cost, priced = cost_of(model, usage)
    with _LOCK:
        STATS["calls"] += 1
        STATS["cache_hits"] += int(cached)
        STATS["input_tokens"] += tin
        STATS["output_tokens"] += tout
        STATS["cost_usd"] += cost
        STATS["seconds"] += seconds
        STATS["unpriced_calls"] += int(not priced)
    return ToolLLMResult(content, stop_reason, model, tin, tout, int(usage.get("cache_read", 0)), cost, cached, priced)


def _call_tools(model, messages, system, tools, max_tokens, effort):
    import anthropic

    client = anthropic.Anthropic()
    kwargs: dict[str, Any] = {"model": model, "messages": messages, "tools": tools, "max_tokens": max_tokens,
                              "cache_control": {"type": "ephemeral"}, "output_config": {"effort": effort}}
    if system:
        kwargs["system"] = system
    resp = client.messages.create(**kwargs)
    content = [b.model_dump(exclude_none=True) for b in resp.content]
    u = resp.usage
    usage = {"input": u.input_tokens, "output": u.output_tokens,
             "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
             "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0}
    return content, resp.stop_reason, usage


def _call(provider, model, messages, system, temperature, max_tokens):
    if provider == "anthropic":
        import anthropic

        client = anthropic.Anthropic()
        kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)  # current Claude models reject temperature; the cache keeps runs reproducible
        text = "".join(b.text for b in resp.content if b.type == "text")
        u = resp.usage
        return text, {"input": u.input_tokens, "output": u.output_tokens,
                      "cache_write": getattr(u, "cache_creation_input_tokens", 0) or 0,
                      "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0}

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
        STATS[k] = 0.0 if k in ("seconds", "cost_usd") else 0
