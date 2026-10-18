import pytest
from pydantic import ValidationError

from kbguard.config import ConfigError, KBGuardConfig, TargetConfig, resolve_env

MINIMAL_YAML = """
store:
  adapter: chroma
  collection: policies
"""

FULL_YAML = """
store:
  adapter: qdrant
  settings: {url: http://localhost:6333, api_key_env: QDRANT_API_KEY}
  collection: policies
  text_field: text

metadata_map:
  source: doc_id
  version: meta.version
  updated_at: meta.last_modified

embeddings:
  reuse_stored: true
  model: sentence-transformers/all-MiniLM-L6-v2

checks:
  duplicates: {cosine: 0.97, minhash_jaccard: 0.9}
  stale_versions: {enabled: true}
  chunking_damage: {min_tokens: 40, max_tokens: 800, required_metadata: [source]}
  contradictions: {types: [number, date, money, percent, duration]}

judge:
  model: ollama/llama3
  calibration_set: evals/calibration.jsonl
  min_agreement: 0.8

evals:
  golden: evals/golden.jsonl
  k: [1, 3, 5]
  metrics: [ragas.faithfulness, ragas.answer_relevancy]

target:
  type: python
  callable: my_app.rag:answer

fail_on:
  health_drop: 3
"""

TYPO_YAML = """
store:
  adapter: chroma
  collection: policies
checks:
  duplicates: {cosin: 0.97}
"""

WRONG_TYPE_YAML = """
store:
  adapter: chroma
  collection: policies
embeddings:
  reuse_stored: "yes please"
"""


def test_minimal_config_parses_with_defaults(tmp_path):
    path = tmp_path / "kbguard.yaml"
    path.write_text(MINIMAL_YAML)

    config = KBGuardConfig.from_yaml(path)

    assert config.store.adapter == "chroma"
    assert config.store.collection == "policies"
    assert config.judge is None
    assert config.evals is None
    assert config.target is None
    assert config.checks.duplicates.cosine == 0.97


def test_full_config_parses(tmp_path):
    path = tmp_path / "kbguard.yaml"
    path.write_text(FULL_YAML)

    config = KBGuardConfig.from_yaml(path)

    assert config.store.settings["url"] == "http://localhost:6333"
    assert config.metadata_map["source"] == "doc_id"
    assert config.checks.contradictions.types == ["number", "date", "money", "percent", "duration"]
    assert config.judge.model == "ollama/llama3"
    assert config.evals.k == [1, 3, 5]
    assert config.target.callable == "my_app.rag:answer"
    assert config.fail_on.health_drop == 3


def test_typo_d_key_raises_validation_error(tmp_path):
    path = tmp_path / "kbguard.yaml"
    path.write_text(TYPO_YAML)

    with pytest.raises(ValidationError) as exc_info:
        KBGuardConfig.from_yaml(path)

    # the error should name the actual typo, not just "invalid config"
    assert "cosin" in str(exc_info.value)


def test_wrong_type_raises_validation_error(tmp_path):
    path = tmp_path / "kbguard.yaml"
    path.write_text(WRONG_TYPE_YAML)

    with pytest.raises(ValidationError) as exc_info:
        KBGuardConfig.from_yaml(path)

    assert "reuse_stored" in str(exc_info.value)


def test_checks_defaults_are_independent_between_instances():
    a = KBGuardConfig(store={"adapter": "chroma", "collection": "a"})
    b = KBGuardConfig(store={"adapter": "chroma", "collection": "b"})

    a.checks.duplicates.cosine = 0.5

    assert b.checks.duplicates.cosine == 0.97


def test_target_python_requires_callable():
    with pytest.raises(ValidationError):
        TargetConfig(type="python")


def test_target_http_requires_url():
    with pytest.raises(ValidationError):
        TargetConfig(type="http")


def test_target_python_with_callable_is_valid():
    target = TargetConfig(type="python", callable="my_app.rag:answer")

    assert target.callable == "my_app.rag:answer"


def test_resolve_env_returns_value_when_set(monkeypatch):
    monkeypatch.setenv("KBGUARD_TEST_SECRET", "s3cr3t")

    assert resolve_env("KBGUARD_TEST_SECRET") == "s3cr3t"


def test_resolve_env_raises_config_error_when_missing(monkeypatch):
    monkeypatch.delenv("KBGUARD_TEST_SECRET_MISSING", raising=False)

    with pytest.raises(ConfigError, match="KBGUARD_TEST_SECRET_MISSING"):
        resolve_env("KBGUARD_TEST_SECRET_MISSING")
