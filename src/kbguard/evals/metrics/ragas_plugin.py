from collections.abc import Callable
from typing import Any, Literal

from kbguard.checks.base import JudgeLike
from kbguard.models import EvalResult

# Not independently measured against real faithful/unfaithful answer
# pairs — no such labeled corpus was available this week, same honesty
# pattern as checks/chunking_damage.py's control-character ratio. 0.5 is
# a reasonable midpoint default, documented as unvalidated, not
# calibrated; revisit once judge/calibrate.py has real agreement data.
_DEFAULT_PASS_THRESHOLD = 0.5


def _build_ragas_llm(model: str) -> Any:
    """Wires kbguard's one pinned model string into ragas's own LLM
    abstraction (ragas 0.4.x — checked against the installed package,
    not an older remembered API).

    Verified by hand up to the real-provider-call boundary: the full
    chain (`ragas.llms.llm_factory` → its LiteLLM adapter →
    `instructor.from_litellm(litellm.acompletion)` → `litellm.acompletion`)
    is structurally correct — confirmed by running it for real and
    watching it fail only at "missing credentials", never at a wiring
    error, with no API key configured. It genuinely cannot be exercised
    further without a real provider call: `litellm`'s `mock_response`
    produces plain text, and `instructor`'s default mode requires an
    actual tool-call-shaped response to parse structured output from —
    confirmed by trying it and getting `InstructorRetryException: No
    tool calls or function call found in response`. That's ragas/
    instructor's own internal correctness, not this file's, so it isn't
    re-mocked here; the classes below are unit-tested against an
    *injectable* ragas metric object instead (see each class's
    `ragas_metric` constructor parameter), which is what this file
    actually owns — adapting ragas's call shape to kbguard's, not
    re-verifying ragas's own scoring.

    Also found while verifying this: ragas's `langchain-community`
    dependency (unconstrained in ragas's own metadata) resolves to a
    version that no longer has the `vertexai` module ragas's own `llms`
    package still imports eagerly, making a fresh `pip install ragas`
    literally unimportable — see pyproject.toml's `ragas` extra, pinned
    to `langchain-community<0.4` to work around it.
    """
    import instructor
    import litellm
    from ragas.llms import llm_factory

    client = instructor.from_litellm(litellm.acompletion)
    return llm_factory(model=model, provider="litellm", client=client, adapter="litellm")


def _cause(passed: bool) -> Literal["generation", "none"]:
    # "generation" whenever this metric's threshold isn't met. By the
    # time an answer-quality metric is even being scored, retrieval is
    # assumed to have already succeeded for this question — spec: cause
    # = generation specifically "if retrieval passed but the answer
    # failed". A retrieval-level cause is evaluate_retrieval's job, not
    # this one's; this file never looks at retrieval results at all.
    return "none" if passed else "generation"


def _result(name: str, value: float) -> EvalResult:
    # question_id is deliberately left blank: score()'s signature (spec
    # section 9.3) only receives raw question/answer/contexts/reference
    # strings, not the GoldenRow they came from — the caller, iterating
    # per golden row, is the one in a position to set it (e.g.
    # dataclasses.replace(result, question_id=row.id)).
    passed = value >= _DEFAULT_PASS_THRESHOLD
    return EvalResult(question_id="", metric=name, value=value, passed=passed, cause=_cause(passed))


class RagasFaithfulness:
    name = "faithfulness"

    def __init__(self, ragas_metric: Any = None) -> None:
        self._ragas_metric = ragas_metric
        self._built_for_model: str | None = None

    def _metric(self, judge: JudgeLike) -> Any:
        if self._ragas_metric is not None:
            return self._ragas_metric
        if self._built_for_model != judge.model:
            from ragas.metrics.collections import Faithfulness

            self._ragas_metric = Faithfulness(llm=_build_ragas_llm(judge.model))
            self._built_for_model = judge.model
        return self._ragas_metric

    def score(
        self, question: str, answer: str, contexts: list[str], reference: str | None, judge: JudgeLike
    ) -> EvalResult:
        result = self._metric(judge).score(user_input=question, response=answer, retrieved_contexts=contexts)
        return _result(self.name, float(result))


class _CallableRagasEmbedding:
    """Wraps kbguard's own embedder (ingest/embeddings.get_embedder — a
    plain `str -> list[float]` callable, already configured for
    sentence-transformers or litellm per the user's real embeddings:
    config) into ragas's BaseRagasEmbedding interface.

    Built instead of using ragas's own `embedding_factory()` default,
    which was checked by hand and found to construct an *OpenAI*
    embeddings client unconditionally, with no way to route it through
    the user's actually-configured model — a real, silent-default-
    network-call risk this project's "runs entirely in your environment"
    principle exists specifically to rule out.
    """

    def __init__(self, embed: Callable[[str], list[float]]) -> None:
        from ragas.embeddings import BaseRagasEmbedding

        # Constructed via a dynamically-created subclass, not a module-
        # level class definition, so this file never imports
        # ragas.embeddings.BaseRagasEmbedding at module scope — same
        # "optional extra genuinely stays optional" discipline as the
        # rest of this file.
        class _Impl(BaseRagasEmbedding):
            def embed_text(self, text: str, **kwargs: Any) -> list[float]:
                return embed(text)

            async def aembed_text(self, text: str, **kwargs: Any) -> list[float]:
                return embed(text)

        self._impl = _Impl()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._impl, name)


class RagasAnswerRelevancy:
    name = "answer_relevancy"

    def __init__(self, embedder: Callable[[str], list[float]], ragas_metric: Any = None) -> None:
        self._embedder = embedder
        self._ragas_metric = ragas_metric
        self._built_for_model: str | None = None

    def _metric(self, judge: JudgeLike) -> Any:
        if self._ragas_metric is not None:
            return self._ragas_metric
        if self._built_for_model != judge.model:
            from ragas.metrics.collections import AnswerRelevancy

            llm = _build_ragas_llm(judge.model)
            embeddings = _CallableRagasEmbedding(self._embedder)
            self._ragas_metric = AnswerRelevancy(llm=llm, embeddings=embeddings)  # type: ignore[arg-type]
            self._built_for_model = judge.model
        return self._ragas_metric

    def score(
        self, question: str, answer: str, contexts: list[str], reference: str | None, judge: JudgeLike
    ) -> EvalResult:
        result = self._metric(judge).score(user_input=question, response=answer)
        return _result(self.name, float(result))


class RagasContextPrecision:
    name = "context_precision"

    def __init__(self, ragas_metric: Any = None) -> None:
        self._ragas_metric = ragas_metric
        self._built_for_model: str | None = None

    def _metric(self, judge: JudgeLike) -> Any:
        if self._ragas_metric is not None:
            return self._ragas_metric
        if self._built_for_model != judge.model:
            from ragas.metrics.collections import ContextPrecisionWithoutReference

            self._ragas_metric = ContextPrecisionWithoutReference(llm=_build_ragas_llm(judge.model))
            self._built_for_model = judge.model
        return self._ragas_metric

    def score(
        self, question: str, answer: str, contexts: list[str], reference: str | None, judge: JudgeLike
    ) -> EvalResult:
        result = self._metric(judge).score(user_input=question, response=answer, retrieved_contexts=contexts)
        return _result(self.name, float(result))


class RagasContextRecall:
    name = "context_recall"

    def __init__(self, ragas_metric: Any = None) -> None:
        self._ragas_metric = ragas_metric
        self._built_for_model: str | None = None

    def _metric(self, judge: JudgeLike) -> Any:
        if self._ragas_metric is not None:
            return self._ragas_metric
        if self._built_for_model != judge.model:
            from ragas.metrics.collections import ContextRecall

            self._ragas_metric = ContextRecall(llm=_build_ragas_llm(judge.model))
            self._built_for_model = judge.model
        return self._ragas_metric

    def score(
        self, question: str, answer: str, contexts: list[str], reference: str | None, judge: JudgeLike
    ) -> EvalResult:
        # context_recall genuinely needs a reference answer to mean
        # anything (it checks whether the retrieved contexts could have
        # supported it) — unlike the other three metrics here, there's
        # no meaningful degraded behavior without one, so this raises a
        # clear error rather than silently scoring against an empty
        # string or skipping without saying so.
        if reference is None:
            raise ValueError("context_recall needs a golden row with reference_answer set; this one has none")
        result = self._metric(judge).score(user_input=question, retrieved_contexts=contexts, reference=reference)
        return _result(self.name, float(result))
