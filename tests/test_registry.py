from importlib.metadata import EntryPoint, EntryPoints

import pytest

from kbguard.registry import RegistryError, list_available, load_adapter


class _FakeAdapterForRegistry:
    name = "fake"


_FAKE_EP = EntryPoint(name="fake", value="doesnt.matter:Unused", group="kbguard.adapters")


def _fake_entry_points(*, group: str) -> EntryPoints:
    if group == "kbguard.adapters":
        return EntryPoints([_FAKE_EP])
    return EntryPoints([])


@pytest.fixture(autouse=True)
def _patch_entry_points(monkeypatch):
    # entry_points() is patched so these tests never touch real installed
    # package metadata; EntryPoint.load() is patched separately (rather than
    # relying on `value` pointing to a real importable path) so the test
    # doesn't depend on *how* pytest was invoked — entry-point `.load()`
    # resolution is a solved problem that belongs to importlib, not
    # something kbguard's own tests need to re-prove.
    monkeypatch.setattr("kbguard.registry.entry_points", _fake_entry_points)
    monkeypatch.setattr(EntryPoint, "load", lambda self: _FakeAdapterForRegistry)


def test_list_available_returns_registered_names():
    assert list_available("adapters") == ["fake"]


def test_load_adapter_returns_the_registered_class():
    adapter_cls = load_adapter("fake")

    assert adapter_cls is _FakeAdapterForRegistry


def test_load_adapter_unknown_name_raises_with_available_list():
    with pytest.raises(RegistryError, match="fake"):
        load_adapter("nonexistent")
