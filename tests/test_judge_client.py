import sys
import types
from pathlib import Path

import pytest

from kbguard.judge.cache import JudgeCache
from kbguard.judge.client import JudgeClient, JudgeError


class _FakeMessage:
    def __init__(self, content: str | None) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str | None) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str | None) -> None:
        self.choices = [_FakeChoice(content)]


def _install_fake_litellm(monkeypatch: pytest.MonkeyPatch, responses: list[str | None]) -> list[dict]:
    """Installs a fake `litellm` module whose `completion` returns each of
    `responses` in order (one per call), and records every call's kwargs.
    """
    calls: list[dict] = []
    remaining = list(responses)

    def fake_completion(**kwargs: object) -> _FakeResponse:
        calls.append(kwargs)
        return _FakeResponse(remaining.pop(0))

    fake_module = types.ModuleType("litellm")
    fake_module.completion = fake_completion  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", fake_module)
    return calls


def _cache(tmp_path: Path) -> JudgeCache:
    return JudgeCache(tmp_path / "judge_cache.sqlite")


def test_ask_json_returns_parsed_json_on_first_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_litellm(monkeypatch, ['{"verdict": "contradiction"}'])
    client = JudgeClient(model="gpt-4o-mini", cache=_cache(tmp_path))

    result = client.ask_json("are these two facts contradictory?", schema_hint='{"verdict": str}')

    assert result == {"verdict": "contradiction"}


def test_ask_json_sends_model_and_prompt_to_litellm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_litellm(monkeypatch, ['{"verdict": "contradiction"}'])
    client = JudgeClient(model="ollama/llama3", cache=_cache(tmp_path))

    client.ask_json("prompt text", schema_hint="hint text")

    assert len(calls) == 1
    assert calls[0]["model"] == "ollama/llama3"
    assert calls[0]["response_format"] == {"type": "json_object"}
    messages = calls[0]["messages"]
    assert any("prompt text" in m["content"] for m in messages)
    assert any("hint text" in m["content"] for m in messages)


def test_ask_json_retries_once_on_malformed_json_then_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_fake_litellm(monkeypatch, ["not json at all", '{"verdict": "contradiction"}'])
    client = JudgeClient(model="gpt-4o-mini", cache=_cache(tmp_path))

    result = client.ask_json("prompt", schema_hint="hint")

    assert result == {"verdict": "contradiction"}
    assert len(calls) == 2  # exactly one retry, not zero, not more


def test_ask_json_raises_after_exhausting_retries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_litellm(monkeypatch, ["still not json", "still not json"])
    client = JudgeClient(model="gpt-4o-mini", cache=_cache(tmp_path))

    with pytest.raises(JudgeError, match="non-JSON"):
        client.ask_json("prompt", schema_hint="hint")

    assert len(calls) == 2  # bounded: didn't retry forever


def test_ask_json_raises_on_empty_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_litellm(monkeypatch, [None])
    client = JudgeClient(model="gpt-4o-mini", cache=_cache(tmp_path))

    with pytest.raises(JudgeError, match="empty"):
        client.ask_json("prompt", schema_hint="hint")


def test_ask_json_wraps_a_real_provider_failure_into_judge_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """litellm maps every provider's own failure (bad/missing key, rate
    limit, timeout, connection refused) onto the real `openai.OpenAIError`
    hierarchy -- confirmed by hand via each real exception class's
    __mro__ before relying on it in judge/client.py. Without that wrap, a
    bad API key surfaces as a full raw traceback through the CLI instead
    of a clean message (confirmed by hand against a real Anthropic call
    with no key configured)."""
    import openai

    def fake_completion(**kwargs: object) -> None:
        # The real AuthenticationError's constructor needs a real
        # httpx.Response (confirmed by hand -- it reads .request
        # internally), more than this test needs to prove. The plain
        # shared base is real and sufficient: production code catches
        # openai.OpenAIError generically, not any specific subclass.
        raise openai.OpenAIError("Missing API Key")

    fake_module = types.ModuleType("litellm")
    fake_module.completion = fake_completion  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", fake_module)

    client = JudgeClient(model="gpt-4o-mini", cache=_cache(tmp_path))

    with pytest.raises(JudgeError, match="call failed"):
        client.ask_json("prompt", schema_hint="hint")


def test_ask_json_repeat_call_hits_cache_and_does_not_call_litellm_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_fake_litellm(monkeypatch, ['{"verdict": "contradiction"}', '{"verdict": "SHOULD_NOT_BE_USED"}'])
    client = JudgeClient(model="gpt-4o-mini", cache=_cache(tmp_path))

    first = client.ask_json("same prompt", schema_hint="same hint")
    second = client.ask_json("same prompt", schema_hint="same hint")

    assert first == second == {"verdict": "contradiction"}
    assert len(calls) == 1  # the fake backend's call count didn't increase


def test_ask_json_different_prompts_do_not_share_a_cache_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_fake_litellm(monkeypatch, ['{"verdict": "a"}', '{"verdict": "b"}'])
    client = JudgeClient(model="gpt-4o-mini", cache=_cache(tmp_path))

    first = client.ask_json("prompt one", schema_hint="hint")
    second = client.ask_json("prompt two", schema_hint="hint")

    assert first == {"verdict": "a"}
    assert second == {"verdict": "b"}
    assert len(calls) == 2


def test_cache_persists_across_separate_judge_clients_sharing_a_cache_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_fake_litellm(monkeypatch, ['{"verdict": "contradiction"}', '{"verdict": "SHOULD_NOT_BE_USED"}'])
    cache_path = tmp_path / "judge_cache.sqlite"

    JudgeClient(model="gpt-4o-mini", cache=JudgeCache(cache_path)).ask_json("prompt", schema_hint="hint")
    result = JudgeClient(model="gpt-4o-mini", cache=JudgeCache(cache_path)).ask_json("prompt", schema_hint="hint")

    assert result == {"verdict": "contradiction"}
    assert len(calls) == 1


def test_missing_litellm_raises_clear_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # None in sys.modules forces `import litellm` to raise ImportError,
    # regardless of whether it's actually installed in this venv — same
    # technique as test_ingest_embeddings.py's equivalent test.
    monkeypatch.setitem(sys.modules, "litellm", None)
    client = JudgeClient(model="gpt-4o-mini", cache=_cache(tmp_path))

    with pytest.raises(JudgeError, match="litellm"):
        client.ask_json("prompt", schema_hint="hint")
