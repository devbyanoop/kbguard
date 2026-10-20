import importlib
from collections.abc import Callable
from typing import Any

import httpx

from kbguard.config import TargetConfig


class RagTargetError(Exception):
    """Raised when calling the client's RAG system fails, for any reason —
    a client-side exception, an HTTP error, a timeout, or a response that
    doesn't match the configured JSON paths. This is the one place
    kbguard calls code it doesn't control, so every failure mode funnels
    through one exception type a caller can catch once (per question,
    turning it into a reported eval failure — not a crash of the whole
    `eval` run) rather than many ad-hoc ones."""


class RagTarget:
    """Calls a client's RAG system — either an existing Python callable
    (`module:function`) or an HTTP endpoint — and normalizes whatever it
    returns into a plain (answer, contexts) tuple."""

    def __init__(self, config: TargetConfig, client: httpx.Client | None = None) -> None:
        self._config = config
        # Test injection point: a real httpx.Client() by default, or a
        # Client wired to httpx.MockTransport in tests — no real network.
        self._client = client if client is not None else httpx.Client()
        self._callable: Callable[[str], Any] | None = None  # lazy-imported once, not per call

    def answer(self, question: str) -> tuple[str, list[str]]:
        if self._config.type == "python":
            return self._answer_python(question)
        return self._answer_http(question)

    def _answer_python(self, question: str) -> tuple[str, list[str]]:
        if self._callable is None:
            self._callable = self._load_callable()
        try:
            raw = self._callable(question)
        except Exception as exc:
            raise RagTargetError(f"callable {self._config.callable!r} raised: {exc}") from exc
        return _normalize(raw)

    def _load_callable(self) -> Callable[[str], Any]:
        target = self._config.callable
        assert target is not None  # guaranteed by TargetConfig's own validator
        module_path, sep, func_name = target.rpartition(":")
        if not sep:
            raise RagTargetError(f"target.callable must be 'module:function', got {target!r}")
        try:
            module = importlib.import_module(module_path)
            return getattr(module, func_name)  # type: ignore[no-any-return]
        except (ImportError, AttributeError) as exc:
            raise RagTargetError(f"could not import target.callable {target!r}: {exc}") from exc

    def _answer_http(self, question: str) -> tuple[str, list[str]]:
        assert self._config.url is not None  # guaranteed by TargetConfig's own validator
        try:
            response = self._client.request(
                self._config.method, self._config.url, json={"question": question}, timeout=self._config.timeout
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise RagTargetError(f"HTTP call to {self._config.url!r} failed: {exc}") from exc

        try:
            answer = _extract_json_path(data, self._config.answer_path)
            contexts = _extract_json_path(data, self._config.contexts_path)
        except (KeyError, ValueError, TypeError) as exc:
            raise RagTargetError(f"could not extract answer/contexts from response: {exc}") from exc

        return str(answer), list(contexts)


def _normalize(raw: Any) -> tuple[str, list[str]]:
    if isinstance(raw, dict):
        if "answer" not in raw:
            raise RagTargetError(f"callable's dict result is missing an 'answer' key: {raw!r}")
        return str(raw["answer"]), list(raw.get("contexts", []))
    try:
        answer, contexts = raw
    except (TypeError, ValueError) as exc:
        raise RagTargetError(
            f"callable must return a (answer, contexts) tuple or a dict with 'answer'/'contexts' keys, got {raw!r}"
        ) from exc
    return str(answer), list(contexts)


def _extract_json_path(data: Any, path: str) -> Any:
    # Deliberately limited: a dotted path from "$." only (e.g. "$.answer",
    # "$.data.answer") — no array indexing, no wildcards. Spec explicitly
    # allows this: "a small, deliberately limited subset is fine, don't
    # pull in a full JSONPath library unless you actually need wildcards."
    if not path.startswith("$."):
        raise ValueError(f"unsupported JSON path (must start with '$.'): {path!r}")
    current = data
    for part in path[2:].split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"JSON path {path!r} not found in response: {data!r}")
        current = current[part]
    return current
