"""Optional language-model provider, chosen by ORPHAN_RADAR_LLM_PROVIDER.

  anthropic  - official `anthropic` SDK (pip install anthropic), model default claude-opus-5-5
  openai     - any OpenAI-compatible /chat/completions endpoint (OPENAI_BASE_URL), over plain HTTP
  none       - default; clustering falls back to rules and briefs are written from templates

The model only ever sees evidence text and is asked for JSON. Callers validate every
returned id and reject any digit that is not present in the cited evidence (grounding rule).
"""
from __future__ import annotations

import json
import re
import urllib.request

from .config import env


class LLMError(RuntimeError):
    pass


def provider_name() -> str:
    p = env("ORPHAN_RADAR_LLM_PROVIDER", "").lower()
    if p in ("", "auto"):
        if env("ANTHROPIC_API_KEY"):
            return "anthropic"
        if env("OPENAI_API_KEY"):
            return "openai"
        return "none"
    return p


def available() -> tuple[bool, str]:
    p = provider_name()
    if p == "none":
        return False, "no language-model provider configured (ORPHAN_RADAR_LLM_PROVIDER / API key unset)"
    if p == "anthropic":
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False, "ORPHAN_RADAR_LLM_PROVIDER=anthropic but the `anthropic` package is not installed (pip install anthropic)"
        return True, "anthropic"
    if p == "openai":
        if not env("OPENAI_API_KEY") and "localhost" not in env("OPENAI_BASE_URL"):
            return False, "OPENAI_API_KEY is not set"
        return True, "openai"
    return False, f"unknown provider {p!r}"


SYSTEM = (
    "You organise evidence about a software product for a research tool. You may only summarise the "
    "evidence text you are given. Never add facts, numbers, prices, dates, names or features that are not "
    "written in the evidence. If something is not in the evidence, write \"unknown\". Do not use digits "
    "unless the same digits appear in the evidence you cite. Reply with JSON only."
)


def complete_json(prompt: str, schema: dict, max_tokens: int = 16000) -> dict:
    ok, why = available()
    if not ok:
        raise LLMError(why)
    if provider_name() == "anthropic":
        return _anthropic(prompt, schema, max_tokens)
    return _openai(prompt, schema, max_tokens)


def _anthropic(prompt: str, schema: dict, max_tokens: int) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    model = env("ORPHAN_RADAR_LLM_MODEL", "claude-opus-5-5")
    kwargs = dict(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
    )
    try:
        if model.startswith(("claude-opus-5", "claude-fable-5", "claude-sonnet-5-5")):
            # Server-side fallback on a policy refusal; routes by refusal category.
            response = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs)
        else:
            response = client.messages.create(**kwargs)
    except anthropic.RateLimitError as exc:
        raise LLMError(f"rate limited: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise LLMError(f"API error {exc.status_code}: {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError(f"connection error: {exc}") from exc
    if response.stop_reason == "refusal":
        raise LLMError("the model declined the request")
    if response.stop_reason == "max_tokens":
        raise LLMError("response truncated at max_tokens")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except ValueError as exc:
        raise LLMError("model did not return JSON") from exc


def _openai(prompt: str, schema: dict, max_tokens: int) -> dict:
    base = env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    body = {
        "model": env("ORPHAN_RADAR_LLM_MODEL", "gpt-4.1-mini"),
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM + " The JSON must match this schema: " + json.dumps(schema)},
            {"role": "user", "content": prompt},
        ],
    }
    req = urllib.request.Request(base + "/chat/completions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {env('OPENAI_API_KEY')}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
        return json.loads(data["choices"][0]["message"]["content"])
    except Exception as exc:  # noqa: BLE001
        raise LLMError(f"openai-compatible call failed: {exc}") from exc


_DIGITS = re.compile(r"\d+(?:[.,]\d+)*")


def ungrounded_numbers(text: str, sources: list[str]) -> list[str]:
    """Numbers in `text` that do not appear in any of the source texts."""
    pool = " ".join(sources)
    return [n for n in _DIGITS.findall(text or "") if n not in pool]
