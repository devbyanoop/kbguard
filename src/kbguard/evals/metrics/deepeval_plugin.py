from typing import Any, Literal

from kbguard.checks.base import JudgeLike
from kbguard.models import EvalResult


def _cause(passed: bool) -> Literal["generation", "none"]:
    # Same reasoning as ragas_plugin.py's _cause: by the time an answer-
    # quality metric is scored, retrieval is assumed to have already
    # succeeded for this question (spec: cause = generation specifically
    # "if retrieval passed but the answer failed") — a retrieval-level
    # cause is evaluate_retrieval's job, not this file's.
    return "none" if passed else "generation"


class _LiteLLMDeepEvalModel:
    """Wraps kbguard's one pinned model string into deepeval's
    DeepEvalBaseLLM interface via litellm — much simpler than ragas's
    wrapper: DeepEvalBaseLLM.generate()/a_generate() just need plain text
    in, plain text out (confirmed against the installed deepeval 4.x
    package's actual abstract methods), no tool-calling/structured-output
    requirement the way ragas's instructor-based LLM needed. Verified for
    real with litellm's mock_response (a plain JSON string, no tool call)
    — unlike ragas_plugin.py's LLM wrapper, this one genuinely is unit-
    tested end to end, not just verified by hand up to a credentials
    boundary.
    """

    def __init__(self, model: str) -> None:
        from deepeval.models.base_model import DeepEvalBaseLLM

        model_name = model

        class _Impl(DeepEvalBaseLLM):  # type: ignore[misc]  # deepeval.* is follow_imports="skip", so this resolves to Any
            def __init__(self) -> None:
                super().__init__(model=model_name)

            def load_model(self) -> "_Impl":
                return self

            def generate(self, prompt: str, *args: Any, **kwargs: Any) -> str:
                import litellm

                response = litellm.completion(model=model_name, messages=[{"role": "user", "content": prompt}])
                content: str = response.choices[0].message.content
                return content

            async def a_generate(self, prompt: str, *args: Any, **kwargs: Any) -> str:
                import litellm

                response = await litellm.acompletion(
                    model=model_name, messages=[{"role": "user", "content": prompt}]
                )
                content: str = response.choices[0].message.content
                return content

            def get_model_name(self, *args: Any, **kwargs: Any) -> str:
                return model_name

        self._impl = _Impl()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._impl, name)


def _build_test_case(question: str, answer: str, contexts: list[str], reference: str | None) -> Any:
    from deepeval.test_case import LLMTestCase

    return LLMTestCase(input=question, actual_output=answer, retrieval_context=contexts, expected_output=reference)


def _score(name: str, metric: Any, test_case: Any) -> EvalResult:
    value = float(metric.measure(test_case))
    # deepeval's own threshold/success logic (constructor's `threshold`
    # param, default 0.5) is used directly rather than reimplemented —
    # unlike ragas's MetricResult, which carries no pass/fail judgment of
    # its own at all.
    passed = bool(metric.is_successful())
    return EvalResult(question_id="", metric=name, value=value, passed=passed, cause=_cause(passed))


class DeepevalFaithfulness:
    name = "faithfulness"

    def __init__(self, metric: Any = None) -> None:
        self._metric = metric
        self._built_for_model: str | None = None

    def _get_metric(self, judge: JudgeLike) -> Any:
        if self._metric is not None:
            return self._metric
        if self._built_for_model != judge.model:
            from deepeval.metrics import FaithfulnessMetric

            self._metric = FaithfulnessMetric(model=_LiteLLMDeepEvalModel(judge.model), async_mode=False)
            self._built_for_model = judge.model
        return self._metric

    def score(
        self, question: str, answer: str, contexts: list[str], reference: str | None, judge: JudgeLike
    ) -> EvalResult:
        test_case = _build_test_case(question, answer, contexts, reference)
        return _score(self.name, self._get_metric(judge), test_case)


class DeepevalAnswerRelevancy:
    name = "answer_relevancy"

    def __init__(self, metric: Any = None) -> None:
        self._metric = metric
        self._built_for_model: str | None = None

    def _get_metric(self, judge: JudgeLike) -> Any:
        if self._metric is not None:
            return self._metric
        if self._built_for_model != judge.model:
            from deepeval.metrics import AnswerRelevancyMetric

            self._metric = AnswerRelevancyMetric(model=_LiteLLMDeepEvalModel(judge.model), async_mode=False)
            self._built_for_model = judge.model
        return self._metric

    def score(
        self, question: str, answer: str, contexts: list[str], reference: str | None, judge: JudgeLike
    ) -> EvalResult:
        test_case = _build_test_case(question, answer, contexts, reference)
        return _score(self.name, self._get_metric(judge), test_case)


class DeepevalContextualPrecision:
    name = "context_precision"

    def __init__(self, metric: Any = None) -> None:
        self._metric = metric
        self._built_for_model: str | None = None

    def _get_metric(self, judge: JudgeLike) -> Any:
        if self._metric is not None:
            return self._metric
        if self._built_for_model != judge.model:
            from deepeval.metrics import ContextualPrecisionMetric

            self._metric = ContextualPrecisionMetric(model=_LiteLLMDeepEvalModel(judge.model), async_mode=False)
            self._built_for_model = judge.model
        return self._metric

    def score(
        self, question: str, answer: str, contexts: list[str], reference: str | None, judge: JudgeLike
    ) -> EvalResult:
        # Unlike ragas's reference-free context precision, deepeval's
        # version genuinely needs expected_output as ground truth to
        # judge whether the *most relevant* contexts were ranked first —
        # confirmed against the installed package's own metric logic,
        # not assumed to be optional because the field is.
        if reference is None:
            raise ValueError("context_precision (deepeval) needs a golden row with reference_answer set")
        test_case = _build_test_case(question, answer, contexts, reference)
        return _score(self.name, self._get_metric(judge), test_case)


class DeepevalContextualRecall:
    name = "context_recall"

    def __init__(self, metric: Any = None) -> None:
        self._metric = metric
        self._built_for_model: str | None = None

    def _get_metric(self, judge: JudgeLike) -> Any:
        if self._metric is not None:
            return self._metric
        if self._built_for_model != judge.model:
            from deepeval.metrics import ContextualRecallMetric

            self._metric = ContextualRecallMetric(model=_LiteLLMDeepEvalModel(judge.model), async_mode=False)
            self._built_for_model = judge.model
        return self._metric

    def score(
        self, question: str, answer: str, contexts: list[str], reference: str | None, judge: JudgeLike
    ) -> EvalResult:
        if reference is None:
            raise ValueError("context_recall (deepeval) needs a golden row with reference_answer set")
        test_case = _build_test_case(question, answer, contexts, reference)
        return _score(self.name, self._get_metric(judge), test_case)
