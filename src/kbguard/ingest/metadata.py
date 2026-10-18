import dataclasses
from datetime import datetime, timezone
from typing import Any

from kbguard.models import Chunk

# The only fields a metadata_map entry is allowed to target — everything
# else on Chunk (id, text, embedding, metadata itself) is set by the
# adapter, not by this mapping step.
_STANDARD_FIELDS = ("source", "position", "version", "updated_at", "title")


class MetadataMappingError(Exception):
    """Raised for a metadata_map problem that's a real configuration
    mistake — an unknown target field, or a value that can't be coerced to
    the type a field expects. NOT raised for a path that's simply absent
    from a given chunk's metadata; that's ordinary, expected real-world data
    incompleteness, left for chunking_damage's "missing metadata" rule to
    report as a finding, not a crash here."""


def validate_metadata_map(mapping: dict[str, str]) -> None:
    """Call once per scan (not per chunk) before using apply_metadata_map.
    Catches a typo'd target field, e.g. "updatd_at", which a bare dict has
    no schema to reject on its own."""
    unknown = sorted(set(mapping) - set(_STANDARD_FIELDS))
    if unknown:
        raise MetadataMappingError(
            f"metadata_map has unknown target field(s) {unknown}; "
            f"valid fields are {list(_STANDARD_FIELDS)}"
        )


def apply_metadata_map(chunk: Chunk, mapping: dict[str, str]) -> Chunk:
    """Fill Chunk's standard fields from its own `metadata` dict, per
    mapping (e.g. {"updated_at": "meta.last_modified"}). Returns a new
    Chunk — chunks are treated as immutable data flowing through the
    ingest pipeline, not mutated in place. Assumes `mapping` already passed
    validate_metadata_map(); doesn't re-check it here, since this runs
    once per chunk and the check only needs to happen once per scan.
    """
    updates: dict[str, Any] = {}
    for field_name, path in mapping.items():
        value = _get_path(chunk.metadata, path)
        if value is None:
            continue
        updates[field_name] = _coerce(field_name, path, value)

    if not updates:
        return chunk
    return dataclasses.replace(chunk, **updates)


def _get_path(data: dict[str, Any], path: str) -> Any:
    current: Any = data
    for segment in path.split("."):
        if not isinstance(current, dict) or segment not in current:
            return None
        current = current[segment]
    return current


def _coerce(field_name: str, path: str, value: Any) -> Any:
    if field_name == "position":
        return _coerce_position(path, value)
    if field_name == "updated_at":
        return _coerce_updated_at(path, value)
    return _coerce_text(field_name, path, value)


def _coerce_position(path: str, value: Any) -> int:
    if isinstance(value, bool):  # bool is a subclass of int — reject explicitly
        raise MetadataMappingError(f"metadata path {path!r} (-> position) is a bool, not an integer: {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            raise MetadataMappingError(f"metadata path {path!r} (-> position) is not a valid integer: {value!r}") from None
    raise MetadataMappingError(
        f"metadata path {path!r} (-> position) has type {type(value).__name__}, expected an integer: {value!r}"
    )


def _coerce_updated_at(path: str, value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        text = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            raise MetadataMappingError(
                f"metadata path {path!r} (-> updated_at) is not a valid ISO-8601 date/time: {value!r}"
            ) from None
    raise MetadataMappingError(
        f"metadata path {path!r} (-> updated_at) has type {type(value).__name__}, "
        f"expected a date/time, epoch number, or ISO-8601 string: {value!r}"
    )


def _coerce_text(field_name: str, path: str, value: Any) -> str:
    if isinstance(value, (dict, list)):
        raise MetadataMappingError(
            f"metadata path {path!r} (-> {field_name}) is a {type(value).__name__}, expected a scalar: {value!r}"
        )
    return str(value)
