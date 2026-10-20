import sys
import types
from typing import Any

import pytest

from kbguard.evals.metrics.deepeval_plugin import (
    DeepevalAnswerRelevancy,
    DeepevalContextualPrecision,
    DeepevalContextualRecall,
    DeepevalFaithfulness,
    _LiteLLMDeepEvalModel,
)


class _FakeJudge:
    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model

    def ask_json(self, prompt: str, schema_hint: str) -> dict[str, Any]:
        raise AssertionError("deepeval plugins never call ask_json -- they build their own LLM wrapper")


class _FakeDeepevalMetric:
    def __init__(self, value: float, passed: bool) -> None:
        self._value = value
        self._passed = passed
        self.measured_with: list[Any] = []

    def measure(self, test_case: Any) -> float:
        self.measured_with.append(test_case)
        return self._value

    def is_successful(self) -> bool:
        return self._passed


# --- _LiteLLMDeepEvalModel: genuinely unit-tested, unlike ragas's LLM wrapper ---


def _install_fake_litellm(monkeypatch: pytest.MonkeyPatch, response_content: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    class _FakeMessage:
        content = response_content

    class _FakeChoice:
        message = _FakeMessage()

    class _FakeResponse:
        def __init__(self) -> None:
            self.choices = [_FakeChoice()]

    def fake_completion(**kwargs: Any) -> _FakeResponse:
        calls.append(kwargs)
        return _FakeResponse()

    async def fake_acompletion(**kwargs: Any) -> _FakeResponse:
        calls.append(kwargs)
        return _FakeResponse()

    fake_module = types.ModuleType("litellm")
    fake_module.completion = fake_completion  # type: ignore[attr-defined]
    fake_module.acompletion = fake_acompletion  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", fake_module)
    return calls


def test_litellm_model_generate_calls_litellm_with_the_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_litellm(monkeypatch, "the generated text")
    model = _LiteLLMDeepEvalModel("ollama/llama3")

    result = model.generate("a prompt")

    assert result == "the generated text"
    assert calls[0]["model"] == "ollama/llama3"
    assert calls[0]["messages"] == [{"role": "user", "content": "a prompt"}]


@pytest.mark.asyncio
async def test_litellm_model_a_generate_calls_litellm_async(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_fake_litellm(monkeypatch, "async generated text")
    model = _LiteLLMDeepEvalModel("gpt-4o-mini")

    result = await model.a_generate("a prompt")

    assert result == "async generated text"
    assert calls[0]["model"] == "gpt-4o-mini"


def test_litellm_model_get_model_name_returns_the_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_litellm(monkeypatch, "x")
    model = _LiteLLMDeepEvalModel("claude-3-5-sonnet")

    assert model.get_model_name() == "claude-3-5-sonnet"


# --- the four Metric adapters, via an injected fake deepeval metric ---


def test_faithfulness_builds_a_test_case_and_reports_pass() -> None:
    fake = _FakeDeepevalMetric(value=0.9, passed=True)
    metric = DeepevalFaithfulness(metric=fake)

    result = metric.score("question", "answer", ["ctx1", "ctx2"], None, _FakeJudge())

    assert result.value == 0.9
    assert result.passed is True
    assert result.cause == "none"
    assert result.metric == "faithfulness"
    test_case = fake.measured_with[0]
    assert test_case.input == "question"
    assert test_case.actual_output == "answer"
    assert test_case.retrieval_context == ["ctx1", "ctx2"]


def test_faithfulness_failing_reports_generation_cause() -> None:
    fake = _FakeDeepevalMetric(value=0.2, passed=False)
    metric = DeepevalFaithfulness(metric=fake)

    result = metric.score("q", "a", ["c"], None, _FakeJudge())

    assert result.passed is False
    assert result.cause == "generation"


def test_passed_uses_deepevals_own_is_successful_not_a_reimplemented_threshold() -> None:
    # value below what kbguard's own 0.5 default would consider passing,
    # but the fake reports is_successful()=True anyway -- deepeval's own
    # judgment must win, confirming this isn't silently reimplementing a
    # threshold comparison on the raw value.
    fake = _FakeDeepevalMetric(value=0.1, passed=True)
    metric = DeepevalFaithfulness(metric=fake)

    result = metric.score("q", "a", ["c"], None, _FakeJudge())

    assert result.passed is True


def test_question_id_is_left_blank_for_the_caller_to_fill_in() -> None:
    fake = _FakeDeepevalMetric(value=1.0, passed=True)
    metric = DeepevalFaithfulness(metric=fake)

    result = metric.score("q", "a", ["c"], None, _FakeJudge())

    assert result.question_id == ""


def test_answer_relevancy_builds_a_test_case() -> None:
    fake = _FakeDeepevalMetric(value=0.8, passed=True)
    metric = DeepevalAnswerRelevancy(metric=fake)

    result = metric.score("question", "answer", ["ctx"], None, _FakeJudge())

    assert result.metric == "answer_relevancy"
    assert fake.measured_with[0].input == "question"


def test_contextual_precision_passes_expected_output_as_reference() -> None:
    fake = _FakeDeepevalMetric(value=0.7, passed=True)
    metric = DeepevalContextualPrecision(metric=fake)

    metric.score("question", "answer", ["ctx1"], "the reference", _FakeJudge())

    assert fake.measured_with[0].expected_output == "the reference"


def test_contextual_precision_without_reference_raises_clear_error_not_calling_deepeval() -> None:
    fake = _FakeDeepevalMetric(value=0.7, passed=True)
    metric = DeepevalContextualPrecision(metric=fake)

    with pytest.raises(ValueError, match="reference_answer"):
        metric.score("question", "answer", ["ctx1"], None, _FakeJudge())

    assert fake.measured_with == []  # never reached deepeval -- failed fast on the missing reference


def test_contextual_recall_without_reference_raises_clear_error() -> None:
    fake = _FakeDeepevalMetric(value=0.7, passed=True)
    metric = DeepevalContextualRecall(metric=fake)

    with pytest.raises(ValueError, match="reference_answer"):
        metric.score("question", "answer", ["ctx1"], None, _FakeJudge())

    assert fake.measured_with == []


def test_contextual_recall_with_reference_works() -> None:
    fake = _FakeDeepevalMetric(value=0.85, passed=True)
    metric = DeepevalContextualRecall(metric=fake)

    result = metric.score("question", "answer", ["ctx1"], "the reference", _FakeJudge())

    assert result.value == 0.85
    assert fake.measured_with[0].expected_output == "the reference"


def test_each_metric_has_a_distinct_name() -> None:
    names = {
        DeepevalFaithfulness(metric=_FakeDeepevalMetric(1.0, True)).name,
        DeepevalAnswerRelevancy(metric=_FakeDeepevalMetric(1.0, True)).name,
        DeepevalContextualPrecision(metric=_FakeDeepevalMetric(1.0, True)).name,
        DeepevalContextualRecall(metric=_FakeDeepevalMetric(1.0, True)).name,
    }
    assert names == {"faithfulness", "answer_relevancy", "context_precision", "context_recall"}
