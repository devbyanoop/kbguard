import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from kbguard.models import Severity


class ConfigError(Exception):
    """Raised for config problems pydantic can't catch itself — e.g. a secret
    referenced by name in kbguard.yaml that isn't set in the environment."""


class _StrictModel(BaseModel):
    # Forbids unknown fields on every config model, so a typo'd key in
    # kbguard.yaml (e.g. "cosin" instead of "cosine") is a loud validation
    # error instead of a silently-ignored field.
    model_config = ConfigDict(extra="forbid")


class StoreConfig(_StrictModel):
    adapter: str
    # Adapter-specific connection settings (url, api_key_env, dbname, ...).
    # Deliberately untyped here: config.py can't know every current and
    # future adapter's settings shape — each adapter validates its own
    # `settings` when `connect(**settings)` is called.
    settings: dict[str, Any] = Field(default_factory=dict)
    collection: str
    text_field: str | None = None  # for stores that keep chunk text in metadata


EmbeddingsProvider = Literal["sentence-transformers", "litellm"]


class EmbeddingsConfig(_StrictModel):
    reuse_stored: bool = True
    # Explicit, not inferred from `model`'s name — a prefix-based guess
    # (e.g. "starts with sentence-transformers/") would be fragile (plenty
    # of valid local HuggingFace models, like BAAI/bge-small-en-v1.5, don't
    # carry that prefix) and the cost of guessing wrong here is real:
    # misrouting to the hosted (litellm) path means document text silently
    # leaves the user's machine, against this project's local-by-default
    # principle. Default is the fully local provider.
    provider: EmbeddingsProvider = "sentence-transformers"
    model: str = "sentence-transformers/all-MiniLM-L6-v2"


class DuplicatesCheckConfig(_StrictModel):
    enabled: bool = True
    cosine: float = 0.97
    minhash_jaccard: float = 0.9
    severity: Severity = "warn"


class StaleVersionsCheckConfig(_StrictModel):
    enabled: bool = True
    severity: Severity = "warn"


class ChunkingDamageCheckConfig(_StrictModel):
    enabled: bool = True
    min_tokens: int = 40
    max_tokens: int = 800
    required_metadata: list[str] = Field(default_factory=list)
    severity: Severity = "warn"


FactType = Literal["number", "date", "money", "percent", "duration"]
_ALL_FACT_TYPES: list[FactType] = ["number", "date", "money", "percent", "duration"]


class ContradictionsCheckConfig(_StrictModel):
    enabled: bool = True
    types: list[FactType] = Field(default_factory=lambda: list(_ALL_FACT_TYPES))
    severity: Severity = "error"


class ChecksConfig(_StrictModel):
    duplicates: DuplicatesCheckConfig = DuplicatesCheckConfig()
    stale_versions: StaleVersionsCheckConfig = StaleVersionsCheckConfig()
    chunking_damage: ChunkingDamageCheckConfig = ChunkingDamageCheckConfig()
    contradictions: ContradictionsCheckConfig = ContradictionsCheckConfig()


class JudgeConfig(_StrictModel):
    model: str
    calibration_set: Path | None = None
    min_agreement: float = 0.8


class EvalsConfig(_StrictModel):
    golden: Path
    k: list[int] = Field(default_factory=lambda: [1, 3, 5])
    metrics: list[str] = Field(default_factory=list)


class TargetConfig(_StrictModel):
    type: Literal["python", "http"]
    callable: str | None = None          # required when type == "python"
    url: str | None = None               # required when type == "http"
    method: str = "POST"
    answer_path: str = "$.answer"
    contexts_path: str = "$.contexts"

    @model_validator(mode="after")
    def _check_fields_match_type(self) -> "TargetConfig":
        if self.type == "python" and not self.callable:
            raise ValueError('target.callable is required when target.type == "python"')
        if self.type == "http" and not self.url:
            raise ValueError('target.url is required when target.type == "http"')
        return self


class NewFindingsRule(_StrictModel):
    severity: Severity
    max: int = 0


class FailOnConfig(_StrictModel):
    health_drop: int | None = None
    new_findings: NewFindingsRule | None = None
    metric_drop: dict[str, float] = Field(default_factory=dict)


class KBGuardConfig(_StrictModel):
    store: StoreConfig
    metadata_map: dict[str, str] = Field(default_factory=dict)
    embeddings: EmbeddingsConfig = EmbeddingsConfig()
    checks: ChecksConfig = ChecksConfig()
    judge: JudgeConfig | None = None
    evals: EvalsConfig | None = None
    target: TargetConfig | None = None
    fail_on: FailOnConfig = FailOnConfig()

    @classmethod
    def from_yaml(cls, path: Path) -> "KBGuardConfig":
        raw = yaml.safe_load(path.read_text())
        return cls.model_validate(raw)


def resolve_env(var_name: str) -> str:
    """Resolve a secret given the *name* of an environment variable, e.g. the
    value of `store.settings.api_key_env`. Never pass the secret itself here.

    Called only at the point of use (inside an adapter's `connect()`, say) —
    never while loading config — so a missing secret only breaks the command
    that actually needed it, not every command that merely parses the file.
    """
    try:
        return os.environ[var_name]
    except KeyError:
        raise ConfigError(
            f"Environment variable {var_name!r} is not set (referenced by kbguard.yaml)"
        ) from None
