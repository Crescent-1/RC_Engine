"""Alternative LLM providers behind the LLMClient contract.

Every client implements:

    call(ledger, stage, model, max_tokens, system, user, context)
        -> (text, truncated)

with the same discipline as llm.LLMClient: ledger.guard() BEFORE the call
(hard budget invariant), ledger.record() with real token counts after, and
quota/overload errors normalized to APIExhausted so run_batch stops cleanly.

STAGE_EFFORT translation (Anthropic effort levels are the config's native
vocabulary):
  - OpenAI gpt-5.x are reasoning models — reasoning tokens count against the
    output ceiling, exactly like Sonnet's adaptive thinking. We default
    reasoning_effort to "low" (mirrors the Anthropic client disabling
    thinking) and clamp xhigh/max -> high (OpenAI accepts none|low|medium|high).
  - Gemini 2.5-family: thinking_budget=0 disables thinking. gemini-3* cannot
    fully disable thinking; we use thinking_level="low" there instead.
"""

from __future__ import annotations

import os

from . import config
from .llm import APIExhausted, CostLedger, LLMClient, resolve_effort


def make_client(provider: str):
    if provider == "claude":
        return LLMClient()
    if provider == "openai":
        return OpenAIClient()
    if provider == "gemini":
        return GeminiClient()
    raise ValueError(f"unknown provider {provider!r}; expected one of {config.PROVIDERS}")


def provider_key_present(provider: str) -> str | None:
    """Name of the env var that is set for this provider, else None."""
    for k in config.PROVIDER_ENV_KEYS[provider]:
        if os.environ.get(k):
            return k
    return None


class OpenAIClient:
    """OpenAI chat.completions wrapper honoring the ledger contract."""

    def __init__(self):
        from openai import OpenAI
        self._client = OpenAI()  # reads OPENAI_API_KEY

    def call(self, ledger: CostLedger, stage: str, model: str, max_tokens: int,
             system: str, user: str, context: dict | None = None) -> tuple[str, bool]:
        import openai

        ledger.guard(stage, len(system) + len(user), model, max_tokens)
        effort = resolve_effort(stage, context) or "low"
        if effort in ("xhigh", "max"):
            effort = "high"
        try:
            resp = self._client.chat.completions.create(
                model=model,
                # NOT max_tokens — rejected on gpt-5.x reasoning models
                max_completion_tokens=max_tokens,
                reasoning_effort=effort,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
            )
        except (openai.RateLimitError, openai.APIConnectionError) as e:
            # insufficient_quota arrives as RateLimitError on this SDK
            raise APIExhausted(str(e)) from e
        except openai.APIStatusError as e:
            status = getattr(e, "status_code", None)
            if status in (402, 429, 503, 529) or "quota" in str(e).lower():
                raise APIExhausted(str(e)) from e
            raise
        choice = resp.choices[0]
        usage = resp.usage
        ledger.record(stage, model, usage.prompt_tokens, usage.completion_tokens)
        text = choice.message.content or ""
        if not text:
            # Reasoning ate the whole output ceiling, or an empty completion:
            # tokens are already on the ledger; surface as a retryable stage
            # failure (existing per-stage retry loops absorb ValueError).
            raise ValueError(
                f"OpenAI returned no text (finish_reason={choice.finish_reason})")
        return text, choice.finish_reason == "length"


class GeminiClient:
    """google-genai wrapper honoring the ledger contract."""

    def __init__(self):
        from google import genai
        key = (os.environ.get("GOOGLE_API_KEY")
               or os.environ.get("GEMINI_API_KEY"))
        self._client = genai.Client(api_key=key)

    def call(self, ledger: CostLedger, stage: str, model: str, max_tokens: int,
             system: str, user: str, context: dict | None = None) -> tuple[str, bool]:
        from google.genai import errors, types

        ledger.guard(stage, len(system) + len(user), model, max_tokens)
        if model.startswith("gemini-3"):
            # gemini-3 models reject thinking_budget=0; "low" is the minimum
            thinking = types.ThinkingConfig(thinking_level="low")
        else:
            thinking = types.ThinkingConfig(thinking_budget=0)
        cfg = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            thinking_config=thinking,
        )
        try:
            resp = self._client.models.generate_content(
                model=model, contents=user, config=cfg)
        except errors.APIError as e:
            code = getattr(e, "code", None)
            msg = str(e)
            if code in (402, 429, 503, 529) or "RESOURCE_EXHAUSTED" in msg \
                    or "quota" in msg.lower():
                raise APIExhausted(msg) from e
            raise
        cand = (resp.candidates or [None])[0]
        finish = getattr(cand, "finish_reason", None)
        um = resp.usage_metadata
        in_tok = getattr(um, "prompt_token_count", 0) or 0
        out_tok = ((getattr(um, "candidates_token_count", 0) or 0)
                   + (getattr(um, "thoughts_token_count", 0) or 0))
        # Record BEFORE the empty-text check: paid tokens stay on the ledger
        # even when the safety filter or thinking swallowed the output.
        ledger.record(stage, model, in_tok, out_tok)
        try:
            text = resp.text or ""
        except ValueError:
            text = ""
        if not text:
            # Safety block / empty candidate: retryable stage failure, never
            # a crash — the pipeline's existing retry paths handle ValueError.
            raise ValueError(f"Gemini returned no text (finish_reason={finish})")
        return text, str(finish).endswith("MAX_TOKENS")
