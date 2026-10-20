import hashlib
import json
import random
from pathlib import Path
from typing import Any

import pandas as pd

from kbguard.checks.base import JudgeLike
from kbguard.ingest.snapshot import SnapshotReader

# Reproducible sampling across two generate() calls against the *same*
# snapshot — not a security-sensitive random choice, same reasoning as
# adapters/bridge_langchain.py's probe-vector seed.
_SAMPLE_SEED = 0

_SCHEMA_HINT = '{"question": str}'

_CSV_COLUMNS = ["question", "expected_chunk_ids", "reference_answer", "approved"]


def generate(snapshot: SnapshotReader, n: int, judge: JudgeLike) -> pd.DataFrame:
    """Samples up to n chunks from the snapshot and asks the judge to write
    one plausible, specific question whose answer is found in each — the
    first place the judge is used for *generation*, not yes/no
    classification (checks/contradictions.py's use case).

    Returns a review DataFrame, not a written file — the caller decides
    where/whether to save it (`df.to_csv(path, index=False)`), keeping
    this function pure and easy to test. `approved` is always False here:
    this step must never auto-approve anything, even for convenience —
    the human review step is a stated v0.1 requirement, not a formality.
    """
    chunks = list(snapshot.chunks())
    sample = random.Random(_SAMPLE_SEED).sample(chunks, k=min(n, len(chunks)))

    rows: list[dict[str, Any]] = []
    for chunk in sample:
        prompt = (
            "Write one specific, answerable question whose answer is directly stated in this text. "
            "Don't ask something answerable without it.\n\n"
            f"Text: {chunk.text!r}"
        )
        response = judge.ask_json(prompt, _SCHEMA_HINT)
        question = response.get("question")
        if not question:
            continue  # a judge that returns no usable question for this chunk is simply skipped
        rows.append(
            {
                "question": question,
                "expected_chunk_ids": chunk.id,
                "reference_answer": "",
                "approved": False,
            }
        )

    return pd.DataFrame(rows, columns=_CSV_COLUMNS)  # type: ignore[no-any-return]


def _is_approved(value: Any) -> bool:
    # This CSV is meant for a human to edit by hand (spec: "human edits /
    # approves rows in the CSV") — a reviewer leaving even one row's
    # `approved` cell blank while they work through the rest is completely
    # normal. That blank cell makes pandas infer the whole column as mixed
    # `object` dtype (real bool values alongside float('nan')), and
    # `df[df["approved"]]` then raises ValueError: Cannot mask with
    # non-boolean array containing NA/NaN values — confirmed by hand, not
    # assumed. Parsing each cell explicitly (NaN/blank -> not approved,
    # case-insensitive "true" string or real bool True -> approved) avoids
    # relying on pandas' automatic dtype inference staying clean.
    if pd.isna(value):
        return False
    return str(value).strip().lower() == "true"


def freeze(csv_path: Path, out_path: Path) -> None:
    """Filters a reviewed CSV down to approved rows, assigns each a stable
    id, and writes evals/golden.jsonl.

    id = sha256(question)[:16] — stable across repeated freezes of the
    same CSV (the same question text always hashes the same), and across
    a fresh generate()+review+freeze cycle that happens to reproduce an
    identical question, without needing to track ids anywhere in between.
    """
    df = pd.read_csv(csv_path)
    approved = df[df["approved"].apply(_is_approved)]

    with out_path.open("w", encoding="utf-8") as f:
        for _, row in approved.iterrows():
            question = str(row["question"])
            reference_answer = None if pd.isna(row["reference_answer"]) else str(row["reference_answer"])
            expected_chunk_ids = [s.strip() for s in str(row["expected_chunk_ids"]).split(",") if s.strip()]

            record = {
                "id": hashlib.sha256(question.encode("utf-8")).hexdigest()[:16],
                "question": question,
                "expected_chunk_ids": expected_chunk_ids,
                "reference_answer": reference_answer,
            }
            f.write(json.dumps(record) + "\n")
