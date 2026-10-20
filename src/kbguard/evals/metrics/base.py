from typing import Protocol

from kbguard.checks.base import JudgeLike
from kbguard.models import EvalResult


class Metric(Protocol):
    """Same Protocol pattern as Check/VectorStoreAdapter — structural
    typing, no base-class coupling. ragas_plugin.py and
    deepeval_plugin.py both satisfy this without inheriting from
    anything, which is the actual proof the Protocol is plugin-shaped,
    not accidentally tied to one library's call conventions.
    """

    name: str

    def score(
        self,
        question: str,
        answer: str,
        contexts: list[str],
        reference: str | None,
        judge: JudgeLike,
    ) -> EvalResult: ...
