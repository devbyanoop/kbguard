from importlib.metadata import EntryPoint, entry_points
from typing import Literal

from kbguard.adapters.base import VectorStoreAdapter
from kbguard.checks.base import Check

# A new store/check/metric is "one file" because it only ever needs to
# register itself in one of these groups — kbguard's own built-in adapters
# (chroma, pgvector, ...) and checks (duplicates, ...) register the exact
# same way a third-party package would, via its own pyproject.toml.
#
# This is also what keeps an optional, heavy dependency honestly optional:
# checks/duplicates.py imports faiss/datasketch at module level (it
# genuinely needs them, same as adapters/chroma.py needing chromadb) — but
# that module is only ever imported when load_check("duplicates") actually
# runs, so a user who never enables the duplicates check never pays for
# importing those libraries. "metrics" group is added once
# evals/metrics/base.py exists (Week 3) — same mechanism, not wired up
# until there's a Metric type to return.
_GROUPS: dict[str, str] = {
    "adapters": "kbguard.adapters",
    "checks": "kbguard.checks",
}


class RegistryError(Exception):
    """Raised when a requested adapter/check name isn't registered."""


def list_available(group: Literal["adapters", "checks"]) -> list[str]:
    eps = entry_points(group=_GROUPS[group])
    return sorted(ep.name for ep in eps)


def _find_entry_point(group: Literal["adapters", "checks"], name: str) -> EntryPoint:
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


def load_check(name: str) -> type[Check]:
    ep = _find_entry_point("checks", name)
    return ep.load()  # type: ignore[no-any-return]
