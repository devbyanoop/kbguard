import json
import sqlite3
from pathlib import Path
from typing import Any


class JudgeCache:
    """Persists judge responses keyed by request hash, as a sqlite file
    living inside one snapshot's own directory (spec section 10: "all calls
    cached by request hash in the snapshot").

    This is scoped to one snapshot, not shared across separate `kbguard
    scan` runs — each scan writes a brand-new, differently-named snapshot
    directory (see cli.py), so a second scan always starts with a cold
    cache. What this cache actually buys: running checks, `report`, or
    `diff` more than once against the *same* already-written snapshot never
    re-pays for a judge call it already made — useful on its own (iterating
    on a report template or a health-score weight shouldn't cost LLM calls),
    just narrower than "caching" alone might suggest.
    """

    def __init__(self, path: Path) -> None:
        self._path = path

    def get(self, key: str) -> Any | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT response FROM judge_cache WHERE key = ?", (key,)).fetchone()
        finally:
            conn.close()
        return json.loads(row[0]) if row is not None else None

    def set(self, key: str, value: Any) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO judge_cache (key, response) VALUES (?, ?)",
                (key, json.dumps(value)),
            )
            conn.commit()
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.execute("CREATE TABLE IF NOT EXISTS judge_cache (key TEXT PRIMARY KEY, response TEXT NOT NULL)")
        return conn
