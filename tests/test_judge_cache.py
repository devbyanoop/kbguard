from pathlib import Path

from kbguard.judge.cache import JudgeCache


def test_get_on_empty_cache_returns_none(tmp_path: Path) -> None:
    cache = JudgeCache(tmp_path / "judge_cache.sqlite")

    assert cache.get("missing-key") is None


def test_set_then_get_round_trips(tmp_path: Path) -> None:
    cache = JudgeCache(tmp_path / "judge_cache.sqlite")

    cache.set("key-1", {"verdict": "contradiction", "confidence": 0.9})

    assert cache.get("key-1") == {"verdict": "contradiction", "confidence": 0.9}


def test_set_overwrites_existing_key(tmp_path: Path) -> None:
    cache = JudgeCache(tmp_path / "judge_cache.sqlite")

    cache.set("key-1", {"verdict": "contradiction"})
    cache.set("key-1", {"verdict": "not_contradiction"})

    assert cache.get("key-1") == {"verdict": "not_contradiction"}


def test_cache_persists_across_separate_instances_pointed_at_the_same_file(tmp_path: Path) -> None:
    path = tmp_path / "judge_cache.sqlite"
    JudgeCache(path).set("key-1", {"verdict": "contradiction"})

    reopened = JudgeCache(path)

    assert reopened.get("key-1") == {"verdict": "contradiction"}


def test_distinct_keys_do_not_collide(tmp_path: Path) -> None:
    cache = JudgeCache(tmp_path / "judge_cache.sqlite")

    cache.set("key-1", {"verdict": "a"})
    cache.set("key-2", {"verdict": "b"})

    assert cache.get("key-1") == {"verdict": "a"}
    assert cache.get("key-2") == {"verdict": "b"}
