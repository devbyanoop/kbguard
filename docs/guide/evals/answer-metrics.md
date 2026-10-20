# Answer metrics

`evals/target.py` (`RagTarget`) and both metric plugins (`evals/metrics/ragas_plugin.py`, `evals/metrics/deepeval_plugin.py`) are built and tested.

## The target: calling code kbguard doesn't control

```yaml
target:
  type: python            # or http
  callable: my_app.rag:answer      # (question) -> (answer, contexts) or {"answer": ..., "contexts": [...]}
  timeout: 30.0            # http only -- a plain Python call has no cross-platform-safe timeout
```

Every failure — a client exception, an HTTP error, a timeout, a response that doesn't match the configured `answer_path`/`contexts_path` — raises one `RagTargetError`, never a crash. `kbguard eval` catches it per question, reports a failed `EvalResult` for that one question, and keeps going; one broken question never aborts the other 99.

`answer_path`/`contexts_path` support a small, deliberately limited JSON-path subset (`$.field.nested`, dotted only — no array indexing, no wildcards), matching the spec's own "don't pull in a full JSONPath library unless you need wildcards."

## The metrics: two libraries, one Protocol

```python
class Metric(Protocol):
    name: str
    def score(self, question, answer, contexts, reference, judge) -> EvalResult: ...
```

| Plugin | Metrics |
| --- | --- |
| `ragas_plugin` | `faithfulness`, `answer_relevancy`, `context_precision`, `context_recall` |
| `deepeval_plugin` | `faithfulness`, `answer_relevancy`, `context_precision`, `context_recall` |

Both wrap their library's real scoring classes directly — this file stays thin on purpose (spec: "if this file is doing anything beyond adapting the library's call shape ... something's been reinvented"). `answer_relevancy`/`context_recall`/`context_precision` each need slightly different inputs per library (deepeval's `context_precision` needs a `reference_answer` as ground truth; ragas's doesn't) — each plugin raises a clear `ValueError` up front when a golden row is missing something a specific metric genuinely needs, rather than calling the library with a value that would produce a meaningless score.

**Cause tagging:** by the time an answer-quality metric is scored, retrieval is assumed to have already succeeded for that question (evaluated separately — see [Retrieval metrics](retrieval-metrics.md)) — so `cause = "generation"` whenever the metric's own pass/fail threshold isn't met, `"none"` otherwise. A retrieval-level cause is `evaluate_retrieval`'s job, not this file's.

## Two real integration surprises, found by hand before trusting either library

**ragas** (0.4.x) needs its own LLM wrapper built from `instructor.from_litellm()` — structured-output, tool-calling-based, not a plain prompt/response. This was verified by hand up to the real-provider-call boundary (constructing it never hits the network; scoring does) — `litellm`'s `mock_response` can't be used to test it further, since it returns plain text and `instructor`'s default mode needs an actual tool-call-shaped response. Also found while installing it: `ragas`'s own `langchain-community` dependency is unconstrained, and pip resolving the latest breaks `ragas` outright (`ragas.llms.base` imports a `langchain_community.chat_models.vertexai` module that no longer exists there) — `pyproject.toml`'s `ragas` extra pins `langchain-community<0.4` to work around it.

**deepeval**'s LLM wrapper (`DeepEvalBaseLLM`) turned out to be much simpler — plain text in, plain text out, no tool-calling requirement. Confirmed by actually scoring a real `FaithfulnessMetric` with a mocked `litellm` response: it reached deepeval's own internal JSON-schema validation and failed only because the mock content didn't match deepeval's specific multi-step schema, never on a wiring error. This means deepeval's LLM wrapper is genuinely unit-tested end to end (`tests/test_evals_metrics_deepeval_plugin.py`), unlike ragas's (verified by hand, not by a mocked unit test).

## Testing strategy

Both plugins' adapter logic (kwarg mapping, cause tagging, pass/fail threshold, the reference-required guards) is tested against an *injectable* fake metric object matching each library's real call shape — the same boundary-faking principle used everywhere else in this project (fake the library's entry point, never its internals). Each plugin class takes an optional `ragas_metric=`/`metric=` constructor parameter for exactly this.
