from importlib.metadata import EntryPoint, entry_points
from typing import Literal

from kbguard.adapters.base import VectorStoreAdapter

# A new store/check/metric is "one file" because it only ever needs to
# register itself in one of these groups — kbguard's own built-in adapters
# (chroma, pgvector, ...) register the exact same way a third-party
# `kbguard-weaviate` package would, via its own pyproject.toml.
_GROUPS: dict[str, str] = {
    "adapters": "kbguard.adapters",
    # "checks" and "metrics" groups are added here once checks/base.py and
    # evals/metrics/base.py exist (Week 2 / Week 3) — same mechanism, just
    # not wired up until there's a Check/Metric type to return.
}


class RegistryError(Exception):
    """Raised when a requested adapter name isn't registered."""


def list_available(group: Literal["adapters"]) -> list[str]:
    eps = entry_points(group=_GROUPS[group])
    return sorted(ep.name for ep in eps)


def _find_entry_point(group: Literal["adapters"], name: str) -> EntryPoint:
    eps = entry_points(group=_GROUPS[group])
    for ep in eps:
        if ep.name == name:
            return ep
    available = ", ".join(sorted(ep.name for ep in eps)) or "(none registered)"
    singular = group[:-1]
    raise RegistryError(f"No {singular} named {name!r} is registered. Available: {available}")


def load_adapter(name: str) -> type[VectorStoreAdapter]:
    ep = _find_entry_point("adapters", name)
    return ep.load()  # type: ignore[no-any-return]
