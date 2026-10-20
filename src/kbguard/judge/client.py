import hashlib
import json
from typing import Any

from kbguard.judge.cache import JudgeCache

# One real call plus one retry, per spec section 10 ("one retry on parse
# failure") — written as an explicit bounded loop, not a silent swallow, so
# a persistently malformed response raises JudgeError instead of quietly
# becoming None somewhere downstream.
_MAX_ATTEMPTS = 2


class JudgeError(Exception):
    """Raised when the configured judge provider's library isn't installed,
    the judge returns an empty response, or it returns non-JSON output on
    every attempt."""


class JudgeClient:
    """A provider-neutral LLM-as-judge client: same call shape whether the
    pinned model is OpenAI, Anthropic, or a local Ollama model, via
    litellm's model-string routing (e.g. "gpt-4o-mini", "ollama/llama3").

    `litellm` is imported lazily, inside `_call`, not at module level —
    same "optional extra genuinely stays optional" pattern as
    ingest/embeddings.py's `_litellm_embedder`: a JudgeClient can be
    constructed, and even hit the cache on a repeat request, without
    `litellm` ever being imported.
    """

    def __init__(self, model: str, cache: JudgeCache) -> None:
        self.model = model
        self._cache = cache

    def ask_json(self, prompt: str, schema_hint: str) -> dict[str, Any]:
        cache_key = _request_hash(self.model, prompt, schema_hint)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached  # type: ignore[no-any-return]

        last_error: json.JSONDecodeError | None = None
        for _ in range(_MAX_ATTEMPTS):
            content = self._call(prompt, schema_hint)
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                last_error = exc
                continue
            self._cache.set(cache_key, parsed)
            return parsed  # type: ignore[no-any-return]

        raise JudgeError(
            f"judge ({self.model}) returned non-JSON output {_MAX_ATTEMPTS} times in a row: {last_error}"
        )

    def _call(self, prompt: str, schema_hint: str) -> str:
        try:
            import litellm
            import openai
        except ImportError as exc:
            raise JudgeError(
                'the judge needs the \'litellm\' extra: pip install "kbguard[litellm]"'
            ) from exc

        try:
            response = litellm.completion(
                model=self.model,
                messages=[
                    {"role": "system", "content": f"Respond with JSON only, matching this shape: {schema_hint}"},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                # LLM-as-judge calls should be as reproducible as the provider
                # allows -- a judge whose verdict flips between identical calls
                # undermines every check that relies on it. temperature=0 asks
                # for the model's most likely token at each step instead of
                # sampling; it reduces but does not guarantee determinism (see
                # judge/calibrate.py's whole reason for existing).
                temperature=0.0,
            )
        except openai.OpenAIError as exc:
            # litellm maps every provider's own exception (missing/invalid
            # key, rate limit, timeout, connection refused, ...) onto this
            # one real shared base -- confirmed by hand via each class's
            # __mro__ before relying on it here, same as elsewhere in this
            # project. Without this, a bad or missing API key surfaces as a
            # full raw traceback through the CLI instead of a clean message
            # (confirmed by hand: `Error: ...` only happens for exceptions
            # cli.py's _USER_FACING_ERRORS already knows about, and this
            # one wasn't in it before).
            raise JudgeError(f"judge ({self.model}) call failed: {exc}") from exc

        content = response.choices[0].message.content
        if not content:
            raise JudgeError(f"judge ({self.model}) returned an empty response")
        return content  # type: ignore[no-any-return]


def _request_hash(model: str, prompt: str, schema_hint: str) -> str:
    payload = json.dumps({"model": model, "prompt": prompt, "schema_hint": schema_hint}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
