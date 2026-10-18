# Answer metrics

!!! warning "Planned — Week 3"
    Not implemented yet.

## Planned behavior

kbguard calls your actual RAG system through a **target** — either a Python callable or an HTTP endpoint:

```yaml
target:
  type: python            # or http
  callable: my_app.rag:answer      # (question) -> {answer, contexts}
```

The answer and retrieved contexts are then scored by metric plugins, reusing established libraries rather than reinventing scoring:

| Plugin | Metrics |
| --- | --- |
| `ragas_plugin` | faithfulness, answer_relevancy, context_precision, context_recall |
| `deepeval_plugin` | faithfulness, answer relevancy, contextual precision/recall |

**Cause tagging:** if retrieval passed (the right context was found) but the metric still fails, `cause = "generation"` — the model had what it needed and didn't use it correctly.

This page will include a real worked example once `evals/target.py` and the metric plugins are built and tested.
