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


class RoutedClient:
    """Dispatches individual stages to their pinned provider/model.

    Wraps the batch's real client and preserves its contract exactly, so no
    call site changes: stages keep passing the model they resolved from
    STAGE_CONFIG, and this overrides it only where a pin applies and is usable.

    Two invariants:
      - a pin NEVER stops a batch. Missing key, missing SDK, or a construction
        error all fall back to the wrapped client, once, with a printed note.
      - the ledger records the model that actually ran, so cost telemetry and
        the pre-call budget guard stay truthful.
    """

    def __init__(self, base, pins: dict | None = None):
        self._base = base
        self._pins = pins if pins is not None else config.STAGE_MODEL_PINS
        self._clients: dict[str, object] = {}
        self._unavailable: dict[str, str] = {}
        self._announced: set[str] = set()

    def _client_for(self, provider: str):
        if provider in self._clients:
            return self._clients[provider]
        if provider in self._unavailable:
            return None
        if not provider_key_present(provider):
            self._unavailable[provider] = (
                f"no key ({'/'.join(config.PROVIDER_ENV_KEYS[provider])} unset)")
            return None
        try:
            self._clients[provider] = make_client(provider)
        except Exception as e:                     # missing SDK, bad config
            self._unavailable[provider] = f"{type(e).__name__}: {e}"
            return None
        return self._clients[provider]

    def call(self, ledger, stage, model, max_tokens, system, user, context=None):
        bp = (context or {}).get("blueprint")
        tier = getattr(bp, "tier", None)
        pin = config.resolve_stage_pin(stage, tier) if self._pins is \
            config.STAGE_MODEL_PINS else self._pins.get(stage)
        if pin:
            provider, pinned_model = pin
            client = self._client_for(provider)
            if client is not None:
                key = f"{stage}:{tier}" if tier else stage
                if key not in self._announced:
                    self._announced.add(key)
                    print(f"  [pin] {stage}"
                          + (f" ({tier})" if tier else "")
                          + f" -> {pinned_model}")
                return client.call(ledger, stage, pinned_model, max_tokens,
                                   system, user, context)
            if stage not in self._announced:
                self._announced.add(stage)
                print(f"  [pin] {stage}: {provider} unavailable "
                      f"({self._unavailable[provider]}) - using {model}")
        return self._base.call(ledger, stage, model, max_tokens, system, user,
                               context)

    def __getattr__(self, name):
        # anything else (probes, helpers) belongs to the wrapped client
        return getattr(self._base, name)


def provider_key_present(provider: str) -> str | None:
    """Name of the env var that is set for this provider, else None."""
    for k in config.PROVIDER_ENV_KEYS[provider]:
        if os.environ.get(k):
            return k
    return None


def provider_key_source(provider: str) -> str:
    """Where this provider's key came from (.env vs environment), including
    whether it is shadowing a different value in .env. Presence alone is a
    misleading health signal — a revoked key looks identical to a good one."""
    var = provider_key_present(provider)
    return config.var_source(var) if var else "unset"


def verify_key(provider: str) -> tuple[bool, str]:
    """Cheap pre-flight auth check: is the resolved key actually accepted?

    Anthropic's count_tokens endpoint is free, so this costs nothing and turns
    a mid-batch 401 (after real spend) into a clean pre-flight failure. Other
    providers have no free equivalent wired up yet, so they report 'skipped'
    rather than blocking a run."""
    var = provider_key_present(provider)
    if not var:
        return False, f"{'/'.join(config.PROVIDER_ENV_KEYS[provider])} not set"
    if provider != "claude":
        return True, f"skipped (no free probe for {provider})"
    try:
        import anthropic
        anthropic.Anthropic().messages.count_tokens(
            model=config.PROVIDER_MODELS[provider]["small"],
            messages=[{"role": "user", "content": "ping"}])
        return True, "ok"
    except Exception as e:
        name = type(e).__name__
        if name == "AuthenticationError":
            return False, f"401 rejected — the key in {var} is not valid"
        # Network hiccup / transient: do not block the run on it.
        return True, f"unverified ({name})"


class OpenAIClient:
    """OpenAI chat.completions wrapper honoring the ledger contract."""

    def __init__(self):
        from openai import OpenAI
        self._client = OpenAI()  # reads OPENAI_API_KEY

    def call(self, ledger: CostLedger, stage: str, model: str, max_tokens: int,
             system: str, user: str, context: dict | None = None) -> tuple[str, bool]:
        import openai

        ledger.guard(stage, len(system) + len(user), model, max_tokens)
        # GPT-5.6 accepts none|low|medium|high|xhigh|max natively, so the old
        # clamp of xhigh/max -> high is gone: it silently downgraded exactly the
        # stages that ask for the most reasoning. Older gpt-5.x still tops out
        # at high, so the clamp is kept for them.
        # STAGE_EFFORT wins where it is explicit (it encodes deliberate per-tier
        # choices); otherwise fall to the per-stage OpenAI map. A blanket
        # default is what broke the first live batch — see OPENAI_STAGE_EFFORT.
        bp = (context or {}).get("blueprint")
        tier = getattr(bp, "tier", None)
        effort = (resolve_effort(stage, context)
                  or config.OPENAI_TIER_STAGE_EFFORT.get(tier, {}).get(stage)
                  or config.OPENAI_STAGE_EFFORT.get(stage,
                                                    config.OPENAI_DEFAULT_EFFORT))
        if effort in ("xhigh", "max") and not model.startswith("gpt-5.6"):
            effort = "high"
        # "max" exists only on Sol; Terra and Luna return HTTP 400 for it.
        # Clamp rather than fail: an unsupported effort must never cost a run.
        if effort == "max" and not model.endswith("-sol"):
            effort = "xhigh"

        ceiling = max_tokens
        for attempt in (1, 2):
            try:
                resp = self._client.chat.completions.create(
                    model=model,
                    # NOT max_tokens — rejected on gpt-5.x reasoning models
                    max_completion_tokens=ceiling,
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
            ledger.record(stage, model, resp.usage.prompt_tokens,
                          resp.usage.completion_tokens)
            if choice.message.content or attempt == 2:
                break
            if choice.finish_reason != "length":
                break
            # Reasoning consumed the whole ceiling before emitting anything.
            # This killed the first live OpenAI batch: move_signature spent all
            # 1200 tokens reasoning, returned nothing, and the set died after
            # the render had already been paid for. One retry at double the
            # ceiling is far cheaper than losing that render.
            ceiling = max_tokens * 2
            print(f"  [openai] {stage}: reasoning consumed the {max_tokens}-token "
                  f"ceiling with no output - one retry at {ceiling}")
            ledger.guard(stage, len(system) + len(user), model, ceiling)

        usage = resp.usage
        # Guard against the reasoning-token accounting defect reported against
        # gpt-5.6 (community thread 1386467): usage.output_tokens re-sums the
        # running reasoning total once per reasoning item, inflating the billed
        # figure 3-9x. That report is against the RESPONSES API and this client
        # uses Chat Completions, so it should not apply here — but completion
        # tokens can never legitimately exceed the ceiling we asked for, so if
        # it ever does, say so loudly rather than quietly booking the number.
        if usage.completion_tokens > ceiling * 1.05:
            print(f"  [openai] !! {model} reported {usage.completion_tokens} "
                  f"completion tokens against a {ceiling} ceiling - possible "
                  f"reasoning-token accounting defect; billed cost may be inflated")
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
