import json
from pathlib import Path

import chromadb
from typer.testing import CliRunner

from kbguard.cli import app
from kbguard.ingest.snapshot import SnapshotReader

runner = CliRunner()


def _seed_chroma_collection(path: Path) -> None:
    client = chromadb.PersistentClient(path=str(path))
    col = client.create_collection(name="policies", embedding_function=None)
    col.add(
        ids=["a", "b"],
        embeddings=[[1.0, 0.0], [0.0, 1.0]],
        documents=["Refunds within 30 days.", "Contact support for help."],
        metadatas=[{"doc_id": "d1"}, {"doc_id": "d2"}],
    )


def test_scan_writes_a_snapshot(tmp_path: Path, monkeypatch) -> None:
    chroma_path = tmp_path / "chroma_data"
    _seed_chroma_collection(chroma_path)

    config_path = tmp_path / "kbguard.yaml"
    config_path.write_text(
        "store:\n"
        "  adapter: chroma\n"
        "  collection: policies\n"
        f"  settings: {{path: {chroma_path.as_posix()}}}\n"
        "metadata_map:\n"
        "  source: doc_id\n"
    )

    # Every seeded chunk already has a stored embedding and reuse_stored
    # defaults to true, so this never needs sentence-transformers installed
    # at all — get_embedder's lazy loading means the embedder closure it
    # returns is simply never called.
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["scan", "--collection", "policies", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    assert "2 chunks" in result.output

    snapshot_dirs = list((tmp_path / ".kbguard" / "snapshots").iterdir())
    assert len(snapshot_dirs) == 1

    reader = SnapshotReader(snapshot_dirs[0])
    read_chunks = {c.id: c for c in reader.chunks()}
    assert set(read_chunks) == {"a", "b"}
    assert read_chunks["a"].source == "d1"  # metadata_map applied
    assert reader.manifest()["adapter"] == "chroma"
    assert reader.manifest()["iteration_mode"] == "full"

    # scan now also runs the built-in checks and writes a report, not just
    # the snapshot itself.
    assert (snapshot_dirs[0] / "results.json").exists()
    assert (snapshot_dirs[0] / "report.html").exists()
    results = json.loads((snapshot_dirs[0] / "results.json").read_text())
    assert 0 <= results["health"] <= 100


def test_scan_runs_checks_and_health_reflects_a_real_duplicate_pair(tmp_path: Path, monkeypatch) -> None:
    chroma_path = tmp_path / "chroma_data"
    client = chromadb.PersistentClient(path=str(chroma_path))
    col = client.create_collection(name="policies", embedding_function=None)
    col.add(
        ids=["a", "b"],
        embeddings=[[1.0, 0.0], [1.0, 0.0]],
        documents=["Refunds within 30 days of purchase for all orders.", "Refunds within 30 days of purchase for all orders."],
        metadatas=[{"doc_id": "d1"}, {"doc_id": "d2"}],
    )

    config_path = tmp_path / "kbguard.yaml"
    config_path.write_text(
        "store:\n"
        "  adapter: chroma\n"
        "  collection: policies\n"
        f"  settings: {{path: {chroma_path.as_posix()}}}\n"
        "metadata_map:\n"
        "  source: doc_id\n"
    )

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["scan", "--collection", "policies", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    snapshot_dir = next((tmp_path / ".kbguard" / "snapshots").iterdir())
    reader = SnapshotReader(snapshot_dir)

    findings = list(reader.findings(check="duplicates"))
    assert len(findings) == 1
    assert findings[0].severity == "error"  # cross-source exact duplicate

    results = json.loads((snapshot_dir / "results.json").read_text())
    assert results["health"] < 100  # the duplicate pair must move the score


def test_report_command_regenerates_without_touching_adapter_or_judge(tmp_path: Path, monkeypatch) -> None:
    chroma_path = tmp_path / "chroma_data"
    _seed_chroma_collection(chroma_path)
    config_path = tmp_path / "kbguard.yaml"
    config_path.write_text(
        "store:\n"
        "  adapter: chroma\n"
        "  collection: policies\n"
        f"  settings: {{path: {chroma_path.as_posix()}}}\n"
        "metadata_map:\n"
        "  source: doc_id\n"
    )

    monkeypatch.chdir(tmp_path)
    scan_result = runner.invoke(app, ["scan", "--collection", "policies", "--config", str(config_path)])
    assert scan_result.exit_code == 0, scan_result.output
    snapshot_dir = next((tmp_path / ".kbguard" / "snapshots").iterdir())

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("report must not load/connect an adapter")

    monkeypatch.setattr("kbguard.cli.load_adapter", _fail_if_called)

    def _judge_client_fails_if_constructed(*args, **kwargs):
        raise AssertionError("report must not construct a JudgeClient")

    monkeypatch.setattr("kbguard.cli.JudgeClient", _judge_client_fails_if_constructed)

    report_result = runner.invoke(app, ["report", snapshot_dir.name, "--config", str(config_path)])

    assert report_result.exit_code == 0, report_result.output
    assert (snapshot_dir / "report.html").exists()


def test_report_command_missing_snapshot_fails_cleanly(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "kbguard.yaml"
    config_path.write_text("store:\n  adapter: chroma\n  collection: x\n")
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["report", "does-not-exist", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "Error" in result.output
    assert "Traceback" not in result.output


def test_scan_missing_config_file_fails_cleanly(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["scan", "--collection", "policies", "--config", "does-not-exist.yaml"])

    assert result.exit_code == 1
    assert "Error" in result.output
    assert "Traceback" not in result.output


def test_scan_unregistered_adapter_fails_cleanly(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "kbguard.yaml"
    config_path.write_text("store:\n  adapter: nonexistent\n  collection: x\n")

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["scan", "--collection", "x", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "nonexistent" in result.output
    assert "Traceback" not in result.output


def test_scan_invalid_config_fails_cleanly(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "kbguard.yaml"
    config_path.write_text("store:\n  adapter: chroma\n  collection: x\n  cosin: 0.5\n")  # typo'd unknown field

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["scan", "--collection", "x", "--config", str(config_path)])

    assert result.exit_code == 1
    assert "Traceback" not in result.output
