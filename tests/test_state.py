import json

from classroom_dl.state import Manifest, ManifestEntry


def _manifest(tmp_path):
    return Manifest(course_id="123", course_name="Curso", path=tmp_path / "123.json")


def test_manifest_roundtrip(tmp_path):
    manifest = _manifest(tmp_path)
    manifest.record(
        "file:1",
        ManifestEntry(path="Curso/Materiales/a.pdf", modified_time="2026-01-01T00:00:00Z", size=10),
    )
    manifest.set_last_sync()
    manifest.save(force=True)

    loaded = Manifest(course_id="123", path=tmp_path / "123.json")
    loaded.load()

    entry = loaded.get("file:1")
    assert entry is not None
    assert entry.path == "Curso/Materiales/a.pdf"
    assert entry.size == 10
    assert loaded.course_name == "Curso"
    assert loaded.last_sync is not None


def test_manifest_is_downloaded_checks_disk(tmp_path):
    output = tmp_path / "out"
    output.mkdir()
    file_path = output / "curso" / "a.pdf"
    file_path.parent.mkdir()
    file_path.write_text("x")

    manifest = _manifest(tmp_path)
    manifest.record("f1", ManifestEntry(path="curso/a.pdf"))
    assert manifest.is_downloaded("f1", output)
    assert not manifest.is_downloaded("f2", output)

    file_path.unlink()
    assert not manifest.is_downloaded("f1", output)


def test_manifest_stats(tmp_path):
    output = tmp_path / "out"
    (output / "curso").mkdir(parents=True)
    (output / "curso" / "a.pdf").write_text("12345")

    manifest = _manifest(tmp_path)
    manifest.record("f1", ManifestEntry(path="curso/a.pdf", size=5))
    manifest.record("f2", ManifestEntry(path="curso/no-existe.pdf", size=7))

    total, present, size = manifest.stats(output)
    assert (total, present, size) == (2, 1, 5)


def test_manifest_autosave(tmp_path):
    manifest = _manifest(tmp_path)
    manifest.save_every = 1
    manifest.record("f1", ManifestEntry(path="a.pdf"))
    assert (tmp_path / "123.json").exists()
    data = json.loads((tmp_path / "123.json").read_text())
    assert data["version"] == 1
    assert "f1" in data["files"]


def test_manifest_tolerates_corrupt_file(tmp_path):
    path = tmp_path / "123.json"
    path.write_text("{no es json")
    manifest = Manifest(course_id="123", path=path)
    manifest.load()
    assert manifest.files == {}


def test_manifest_remove_and_save(tmp_path):
    manifest = _manifest(tmp_path)
    manifest.record("f1", ManifestEntry(path="a.pdf"))
    manifest.save(force=True)
    manifest.remove("f1")
    manifest.remove("no-existe")
    manifest.save(force=True)

    loaded = Manifest(course_id="123", path=tmp_path / "123.json")
    loaded.load()
    assert loaded.get("f1") is None
