from datetime import datetime, timezone

import pytest

from kbguard.ingest.metadata import MetadataMappingError, apply_metadata_map, validate_metadata_map
from kbguard.models import Chunk


def _chunk(metadata: dict, **overrides) -> Chunk:
    defaults = {"id": "c1", "text": "hello", "embedding": None, "metadata": metadata}
    defaults.update(overrides)
    return Chunk(**defaults)


def test_apply_metadata_map_fills_standard_fields_from_nested_paths():
    chunk = _chunk(
        {
            "doc_id": "d1",
            "idx": 3,
            "meta": {"version": "v2", "last_modified": "2026-01-15T10:00:00Z", "title": "Refund Policy"},
        }
    )
    mapping = {
        "source": "doc_id",
        "position": "idx",
        "version": "meta.version",
        "updated_at": "meta.last_modified",
        "title": "meta.title",
    }

    result = apply_metadata_map(chunk, mapping)

    assert result.source == "d1"
    assert result.position == 3
    assert result.version == "v2"
    assert result.updated_at == datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
    assert result.title == "Refund Policy"


def test_apply_metadata_map_missing_path_leaves_field_none_without_raising():
    chunk = _chunk({"doc_id": "d1"})
    mapping = {"source": "doc_id", "version": "meta.version"}  # meta.version absent

    result = apply_metadata_map(chunk, mapping)

    assert result.source == "d1"
    assert result.version is None


def test_apply_metadata_map_empty_mapping_returns_same_instance():
    chunk = _chunk({"doc_id": "d1"})

    result = apply_metadata_map(chunk, {})

    assert result is chunk


def test_apply_metadata_map_leaves_unmapped_fields_untouched():
    chunk = _chunk({"doc_id": "d1"}, title="Set directly by the adapter")

    result = apply_metadata_map(chunk, {"source": "doc_id"})  # title not mapped

    assert result.title == "Set directly by the adapter"


def test_apply_metadata_map_coerces_position_from_string():
    chunk = _chunk({"idx": "3"})

    result = apply_metadata_map(chunk, {"position": "idx"})

    assert result.position == 3


def test_apply_metadata_map_position_bool_raises():
    chunk = _chunk({"idx": True})

    with pytest.raises(MetadataMappingError, match="bool"):
        apply_metadata_map(chunk, {"position": "idx"})


def test_apply_metadata_map_invalid_position_raises():
    chunk = _chunk({"idx": "not-a-number"})

    with pytest.raises(MetadataMappingError, match="idx"):
        apply_metadata_map(chunk, {"position": "idx"})


def test_apply_metadata_map_updated_at_from_epoch():
    chunk = _chunk({"ts": 1768471200})  # 2026-01-15T10:00:00Z

    result = apply_metadata_map(chunk, {"updated_at": "ts"})

    assert result.updated_at == datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)


def test_apply_metadata_map_invalid_updated_at_raises():
    chunk = _chunk({"ts": "not-a-date"})

    with pytest.raises(MetadataMappingError, match="ts"):
        apply_metadata_map(chunk, {"updated_at": "ts"})


def test_apply_metadata_map_text_field_rejects_nested_dict():
    chunk = _chunk({"doc": {"nested": "value"}})

    with pytest.raises(MetadataMappingError, match="source"):
        apply_metadata_map(chunk, {"source": "doc"})


def test_validate_metadata_map_accepts_known_fields():
    validate_metadata_map({"source": "doc_id", "updated_at": "meta.last_modified"})  # no raise


def test_validate_metadata_map_rejects_unknown_field():
    with pytest.raises(MetadataMappingError, match="updatd_at"):
        validate_metadata_map({"updatd_at": "meta.last_modified"})
