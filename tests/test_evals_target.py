import sys
import types

import httpx
import pytest

from kbguard.config import TargetConfig
from kbguard.evals.target import RagTarget, RagTargetError


def _install_fake_module(monkeypatch: pytest.MonkeyPatch, name: str, **attrs: object) -> None:
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)


# --- python callable target ---


def test_python_callable_returning_a_tuple(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_module(monkeypatch, "fake_rag_app", answer=lambda q: ("the answer", ["ctx1", "ctx2"]))
    config = TargetConfig(type="python", callable="fake_rag_app:answer")
    target = RagTarget(config)

    answer, contexts = target.answer("What is the refund window?")

    assert answer == "the answer"
    assert contexts == ["ctx1", "ctx2"]


def test_python_callable_returning_a_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_module(
        monkeypatch, "fake_rag_app", answer=lambda q: {"answer": "the answer", "contexts": ["ctx1"]}
    )
    config = TargetConfig(type="python", callable="fake_rag_app:answer")
    target = RagTarget(config)

    answer, contexts = target.answer("question")

    assert answer == "the answer"
    assert contexts == ["ctx1"]


def test_python_callable_dict_without_contexts_defaults_to_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_module(monkeypatch, "fake_rag_app", answer=lambda q: {"answer": "the answer"})
    config = TargetConfig(type="python", callable="fake_rag_app:answer")
    target = RagTarget(config)

    _, contexts = target.answer("question")

    assert contexts == []


def test_python_callable_is_loaded_lazily_and_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_answer(q: str):
        calls.append(q)
        return ("a", [])

    _install_fake_module(monkeypatch, "fake_rag_app", answer=fake_answer)
    config = TargetConfig(type="python", callable="fake_rag_app:answer")
    target = RagTarget(config)

    target.answer("q1")
    target.answer("q2")

    assert calls == ["q1", "q2"]  # loaded once, called twice


def test_python_callable_that_raises_produces_rag_target_error_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(q: str):
        raise RuntimeError("the client's RAG system broke")

    _install_fake_module(monkeypatch, "fake_rag_app", answer=failing)
    config = TargetConfig(type="python", callable="fake_rag_app:answer")
    target = RagTarget(config)

    with pytest.raises(RagTargetError, match="broke"):
        target.answer("question")


def test_python_callable_not_found_raises_rag_target_error() -> None:
    config = TargetConfig(type="python", callable="this_module_does_not_exist:answer")
    target = RagTarget(config)

    with pytest.raises(RagTargetError, match="could not import"):
        target.answer("question")


def test_python_callable_malformed_string_without_colon_raises() -> None:
    config = TargetConfig(type="python", callable="no_colon_here")
    target = RagTarget(config)

    with pytest.raises(RagTargetError, match="module:function"):
        target.answer("question")


def test_python_callable_returning_garbage_raises_rag_target_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_module(monkeypatch, "fake_rag_app", answer=lambda q: 42)
    config = TargetConfig(type="python", callable="fake_rag_app:answer")
    target = RagTarget(config)

    with pytest.raises(RagTargetError, match="must return"):
        target.answer("question")


def test_python_callable_returning_dict_without_answer_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_module(monkeypatch, "fake_rag_app", answer=lambda q: {"contexts": ["c1"]})
    config = TargetConfig(type="python", callable="fake_rag_app:answer")
    target = RagTarget(config)

    with pytest.raises(RagTargetError, match="answer"):
        target.answer("question")


# --- http target, via httpx.MockTransport (no real network) ---


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_http_target_default_paths() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answer": "the answer", "contexts": ["ctx1", "ctx2"]})

    config = TargetConfig(type="http", url="http://fake-rag.test/answer")
    target = RagTarget(config, client=_mock_client(handler))

    answer, contexts = target.answer("question")

    assert answer == "the answer"
    assert contexts == ["ctx1", "ctx2"]


def test_http_target_custom_nested_json_paths() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"result": "nested answer", "sources": ["c1"]}})

    config = TargetConfig(
        type="http", url="http://fake-rag.test/answer", answer_path="$.data.result", contexts_path="$.data.sources"
    )
    target = RagTarget(config, client=_mock_client(handler))

    answer, contexts = target.answer("question")

    assert answer == "nested answer"
    assert contexts == ["c1"]


def test_http_target_sends_the_question_in_the_request_body() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.read()
        return httpx.Response(200, json={"answer": "a", "contexts": []})

    config = TargetConfig(type="http", url="http://fake-rag.test/answer")
    target = RagTarget(config, client=_mock_client(handler))

    target.answer("what is the refund window?")

    assert b"what is the refund window?" in captured["body"]


def test_http_target_error_status_raises_rag_target_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "internal error"})

    config = TargetConfig(type="http", url="http://fake-rag.test/answer")
    target = RagTarget(config, client=_mock_client(handler))

    with pytest.raises(RagTargetError, match="HTTP call"):
        target.answer("question")


def test_http_target_timeout_raises_rag_target_error_not_a_crash() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated timeout")

    config = TargetConfig(type="http", url="http://fake-rag.test/answer")
    target = RagTarget(config, client=_mock_client(handler))

    with pytest.raises(RagTargetError, match="HTTP call"):
        target.answer("question")


def test_http_target_missing_json_path_raises_rag_target_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"something_else": "oops"})

    config = TargetConfig(type="http", url="http://fake-rag.test/answer")
    target = RagTarget(config, client=_mock_client(handler))

    with pytest.raises(RagTargetError, match="could not extract"):
        target.answer("question")


def test_http_target_malformed_json_path_prefix_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"answer": "a", "contexts": []})

    config = TargetConfig(type="http", url="http://fake-rag.test/answer", answer_path="answer")  # missing "$."
    target = RagTarget(config, client=_mock_client(handler))

    with pytest.raises(RagTargetError, match="could not extract"):
        target.answer("question")


def test_one_broken_question_does_not_affect_the_next_call(monkeypatch: pytest.MonkeyPatch) -> None:
    # Simulates the real orchestration promise: a target that fails once
    # must still work normally on the next call -- RagTarget itself
    # carries no broken state across a failure.
    responses = iter([RuntimeError("boom"), ("a real answer", ["ctx"])])

    def flaky(q: str):
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result

    _install_fake_module(monkeypatch, "fake_rag_app", answer=flaky)
    config = TargetConfig(type="python", callable="fake_rag_app:answer")
    target = RagTarget(config)

    with pytest.raises(RagTargetError):
        target.answer("q1")

    answer, _contexts = target.answer("q2")
    assert answer == "a real answer"
