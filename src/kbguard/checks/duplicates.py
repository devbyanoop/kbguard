from collections import defaultdict
from collections.abc import Iterator
from typing import TYPE_CHECKING, cast

import numpy as np

from kbguard.checks.base import CheckContext
from kbguard.config import DuplicatesCheckConfig
from kbguard.ingest.snapshot import SnapshotReader
from kbguard.models import Chunk, Finding, Severity, compute_fingerprint

if TYPE_CHECKING:
    from datasketch import MinHash

# Nearest neighbors examined per chunk before filtering by threshold. At
# this corpus size it covers every other chunk anyway; at real scale it
# bounds the ANN search cost without needing to be configurable yet — no
# current corpus has more than 50 mutual near-duplicates of one chunk.
_ANN_TOP_K = 50


class DuplicatesCheckError(Exception):
    """Raised when near-duplicate detection needs `faiss`/`datasketch`
    (the `dedup` extra) and it isn't installed. Exact-duplicate detection
    (plain text-hash matching, no extra needed) always works regardless —
    confirmed by hand with a real clean-venv install of just
    `kbguard[chroma]`: the exact path never touches either library, only
    the near-duplicate path does, so this is raised lazily, right where
    it's actually needed, not at module import time (which used to crash
    `kbguard scan` outright the instant *any* check tried to import this
    module, before the check even ran, let alone needed faiss for real)."""


class _UnionFind:
    """Standard disjoint-set structure, used to merge a transitive chain of
    near-duplicate pairs (A~B, B~C) into one cluster instead of reporting
    two separate pairwise findings that share a chunk."""

    def __init__(self, items: list[str]) -> None:
        self._parent = {item: item for item in items}

    def find(self, item: str) -> str:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


class DuplicatesCheck:
    name = "duplicates"
    default_severity: Severity = "warn"

    def run(self, snapshot: SnapshotReader, ctx: CheckContext) -> Iterator[Finding]:
        config = cast(DuplicatesCheckConfig, ctx.config)
        if not config.enabled:
            return

        chunks = {c.id: c for c in snapshot.chunks()}
        if len(chunks) < 2:
            return

        exact_clusters = _exact_duplicate_clusters(chunks)
        exact_ids = {cid for cluster in exact_clusters for cid in cluster}
        for cluster in exact_clusters:
            yield _build_finding(chunks, cluster, "exact", config.severity)

        vectors_by_id = dict(snapshot.vectors())
        near_clusters = _near_duplicate_clusters(
            chunks, vectors_by_id, config.cosine, config.minhash_jaccard, exclude_ids=exact_ids
        )
        for cluster in near_clusters:
            yield _build_finding(chunks, cluster, "near", config.severity)


def _normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def _exact_duplicate_clusters(chunks: dict[str, Chunk]) -> list[list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for chunk_id, chunk in chunks.items():
        groups[_normalize_text(chunk.text)].append(chunk_id)
    return [sorted(ids) for ids in groups.values() if len(ids) > 1]


def _word_minhash(text: str, num_perm: int = 128) -> "MinHash":
    # Word-set Jaccard (unigrams), not literal multi-word "shingles" as the
    # spec names them: tested against the example corpus's real reworded
    # near-duplicate pair, word trigrams scored 0.0 Jaccard (a handful of
    # synonym substitutions invalidates nearly every trigram), which would
    # have made the duplicates check unable to find that exact seeded
    # problem. Word-set Jaccard scored ~0.47 for the same pair with a
    # ~12x margin over unrelated text — see config.py's minhash_jaccard
    # default and docs/guide/checks/duplicates.md for the full comparison.
    try:
        from datasketch import MinHash
    except ImportError as exc:
        raise DuplicatesCheckError(
            'near-duplicate detection needs the \'dedup\' extra: pip install "kbguard[dedup]"'
        ) from exc
    m = MinHash(num_perm=num_perm)
    for word in set(text.lower().split()):
        m.update(word.encode("utf-8"))
    return m


def _near_duplicate_clusters(
    chunks: dict[str, Chunk],
    vectors_by_id: dict[str, list[float]],
    cosine_threshold: float,
    jaccard_threshold: float,
    exclude_ids: set[str],
) -> list[list[str]]:
    # Chunks already reported as exact duplicates are excluded entirely
    # from near-duplicate detection, rather than deduplicating overlapping
    # findings after the fact — simpler, and an exact-duplicate pair would
    # trivially pass both near-duplicate thresholds anyway (cosine=1.0,
    # jaccard=1.0), so without this exclusion every exact pair would be
    # reported twice.
    candidate_ids = [cid for cid in chunks if cid not in exclude_ids and cid in vectors_by_id]
    if len(candidate_ids) < 2:
        return []

    try:
        import faiss
    except ImportError as exc:
        raise DuplicatesCheckError(
            'near-duplicate detection needs the \'dedup\' extra: pip install "kbguard[dedup]"'
        ) from exc

    dim = len(vectors_by_id[candidate_ids[0]])
    matrix = np.array([vectors_by_id[cid] for cid in candidate_ids], dtype=np.float32)
    faiss.normalize_L2(matrix)  # so inner product == cosine similarity

    index = faiss.IndexFlatIP(dim)
    index.add(matrix)

    k = min(len(candidate_ids), _ANN_TOP_K)
    similarities, neighbor_indices = index.search(matrix, k)

    minhashes = {cid: _word_minhash(chunks[cid].text) for cid in candidate_ids}

    uf = _UnionFind(candidate_ids)
    paired_ids: set[str] = set()
    seen_pairs: set[frozenset[str]] = set()
    for i, chunk_id in enumerate(candidate_ids):
        for similarity, j in zip(similarities[i], neighbor_indices[i], strict=True):
            if j < 0 or j == i or similarity < cosine_threshold:
                continue
            other_id = candidate_ids[j]
            pair_key = frozenset({chunk_id, other_id})
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            # Both signals required — cosine alone would flag same-topic,
            # differently-worded chunks as duplicates (see config.py /
            # docs/guide/checks/duplicates.md for the measured false-
            # positive case this specifically guards against: a stale-
            # version pair scored 0.852 word-Jaccard, since only one word
            # differs, but only 0.707 cosine, correctly excluding it here).
            if minhashes[chunk_id].jaccard(minhashes[other_id]) >= jaccard_threshold:
                uf.union(chunk_id, other_id)
                paired_ids.add(chunk_id)
                paired_ids.add(other_id)

    clusters: dict[str, list[str]] = defaultdict(list)
    for chunk_id in paired_ids:
        clusters[uf.find(chunk_id)].append(chunk_id)
    return [sorted(members) for members in clusters.values() if len(members) > 1]


def _build_finding(chunks: dict[str, Chunk], cluster: list[str], duplicate_type: str, base_severity: Severity) -> Finding:
    # Walrus, not a plain filtered comprehension: mypy can't narrow
    # `chunks[cid].source` from `str | None` to `str` across two separate
    # attribute accesses (the `if` clause and the set expression) even
    # though they evaluate the same dict lookup — binding it once to `s`
    # lets the narrowing carry through.
    sources = sorted({s for cid in cluster if (s := chunks[cid].source) is not None})
    # "error" regardless of the configured base severity when duplicates
    # span different sources — spec calls this out as specifically more
    # significant (real copy-pasted content) than duplicates within one
    # document, so it isn't just "whatever the user set severity to".
    severity: Severity = "error" if len(sources) >= 2 else base_severity

    message = f"{len(cluster)} chunks are {duplicate_type} duplicates"
    if len(sources) >= 2:
        message += f" across sources: {', '.join(sources)}"

    return Finding(
        check="duplicates",
        severity=severity,
        chunk_ids=cluster,
        message=message,
        evidence={"duplicate_type": duplicate_type, "sources": sources},
        fingerprint=compute_fingerprint("duplicates", cluster, identity_keys=[duplicate_type]),
    )
