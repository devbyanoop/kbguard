from typing import Any

import pytest

from kbguard.evals.metrics.ragas_plugin import (
    RagasAnswerRelevancy,
    RagasContextPrecision,
    RagasContextRecall,
    RagasFaithfulness,
    _build_ragas_llm,
)


class _FakeJudge:
    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model

    def ask_json(self, prompt: str, schema_hint: str) -> dict[str, Any]:
        raise AssertionError("ragas plugins never call ask_json -- they build their own LLM wrapper")


class _FakeRagasMetric:
    def __init__(self, value: float) -> None:
        self._value = value
        self.calls: list[dict[str, Any]] = []

    def score(self, **kwargs: Any) -> float:
        self.calls.append(kwargs)
        return self._value


def test_build_ragas_llm_constructs_without_a_real_network_call() -> None:
    # Construction alone (not .score()/.generate()) never makes a network
    # call -- confirmed by hand before trusting it. This exercises this
    # project's own import paths and argument names, not ragas's internal
    # scoring correctness.
    llm = _build_ragas_llm("gpt-4o-mini")
    assert llm is not None


def test_faithfulness_passes_the_right_kwargs_and_reports_pass() -> None:
    fake = _FakeRagasMetric(0.9)
    metric = RagasFaithfulness(ragas_metric=fake)

    result = metric.score("question", "answer", ["ctx1", "ctx2"], None, _FakeJudge())

    assert fake.calls == [{"user_input": "question", "response": "answer", "retrieved_contexts": ["ctx1", "ctx2"]}]
    assert result.value == 0.9
    assert result.passed is True
    assert result.cause == "none"
    assert result.metric == "faithfulness"


def test_faithfulness_below_threshold_reports_fail_and_generation_cause() -> None:
    fake = _FakeRagasMetric(0.3)
    metric = RagasFaithfulness(ragas_metric=fake)

    result = metric.score("q", "a", ["c"], None, _FakeJudge())

    assert result.passed is False
    assert result.cause == "generation"


def test_pass_threshold_boundary_is_inclusive() -> None:
    fake = _FakeRagasMetric(0.5)
    metric = RagasFaithfulness(ragas_metric=fake)

    result = metric.score("q", "a", ["c"], None, _FakeJudge())

    assert result.passed is True  # >= 0.5, not > 0.5


def test_question_id_is_left_blank_for_the_caller_to_fill_in() -> None:
    fake = _FakeRagasMetric(1.0)
    metric = RagasFaithfulness(ragas_metric=fake)

    result = metric.score("q", "a", ["c"], None, _FakeJudge())

    assert result.question_id == ""


def test_answer_relevancy_does_not_pass_retrieved_contexts() -> None:
    fake = _FakeRagasMetric(0.8)
    metric = RagasAnswerRelevancy(embedder=lambda text: [0.0], ragas_metric=fake)

    metric.score("question", "answer", ["ctx1"], None, _FakeJudge())

    assert fake.calls == [{"user_input": "question", "response": "answer"}]


def test_context_precision_passes_contexts() -> None:
    fake = _FakeRagasMetric(0.7)
    metric = RagasContextPrecision(ragas_metric=fake)

    metric.score("question", "answer", ["ctx1", "ctx2"], None, _FakeJudge())

    assert fake.calls == [{"user_input": "question", "response": "answer", "retrieved_contexts": ["ctx1", "ctx2"]}]


def test_context_recall_passes_reference_not_response() -> None:
    fake = _FakeRagasMetric(0.6)
    metric = RagasContextRecall(ragas_metric=fake)

    metric.score("question", "answer", ["ctx1"], "the reference answer", _FakeJudge())

    assert fake.calls == [{"user_input": "question", "retrieved_contexts": ["ctx1"], "reference": "the reference answer"}]


def test_context_recall_without_reference_raises_clear_error_not_calling_ragas() -> None:
    fake = _FakeRagasMetric(0.6)
    metric = RagasContextRecall(ragas_metric=fake)

    with pytest.raises(ValueError, match="reference_answer"):
        metric.score("question", "answer", ["ctx1"], None, _FakeJudge())

    assert fake.calls == []  # never reached ragas at all -- failed fast on the missing reference


def test_each_metric_has_a_distinct_name() -> None:
    names = {
        RagasFaithfulness(ragas_metric=_FakeRagasMetric(1.0)).name,
        RagasAnswerRelevancy(embedder=lambda t: [0.0], ragas_metric=_FakeRagasMetric(1.0)).name,
        RagasContextPrecision(ragas_metric=_FakeRagasMetric(1.0)).name,
        RagasContextRecall(ragas_metric=_FakeRagasMetric(1.0)).name,
    }
    assert names == {"faithfulness", "answer_relevancy", "context_precision", "context_recall"}
