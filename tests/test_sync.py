from datetime import date

from classroom_dl.api import ALL_KINDS, DriveAttachment, Item, LinkAttachment
from classroom_dl.drive import DownloadResult, DriveMetadata
from classroom_dl.errors import DownloadError
from classroom_dl.state import Manifest, ManifestEntry
from classroom_dl.sync import SyncOptions, sync_course


class FakeFetcher:
    def __init__(self, items):
        self._items = items
        self.calls = 0

    def items(self, course_id, kinds=ALL_KINDS, *, since=None):
        self.calls += 1
        for item in self._items:
            if item.kind not in kinds:
                continue
            if since is not None and item.date is not None and item.date < since:
                continue
            yield item


class FakeDownloader:
    def __init__(self, *, fail_ids=(), modified="2026-01-01T00:00:00Z"):
        self.fail_ids = set(fail_ids)
        self.modified = modified
        self.download_calls: list[str] = []
        self.metadata_calls: list[str] = []

    def metadata(self, file_id):
        self.metadata_calls.append(file_id)
        return DriveMetadata(
            file_id=file_id,
            name=f"{file_id}.pdf",
            mime_type="application/pdf",
            modified_time=self.modified,
            size=3,
        )

    def download(
        self,
        attachment,
        dest_dir,
        basename,
        *,
        docs_format="pdf",
        sheets_format="xlsx",
        overwrite=True,
    ):
        self.download_calls.append(attachment.file_id)
        if attachment.file_id in self.fail_ids:
            raise DownloadError("falló a propósito")
        path = dest_dir / (basename if basename.endswith(".pdf") else basename + ".pdf")
        if not overwrite:
            counter = 2
            while path.exists():
                path = dest_dir / f"{basename} ({counter}).pdf"
                counter += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("abc")
        return DownloadResult(path=path, modified_time=self.modified, size=3)


def _manifest(tmp_path):
    return Manifest(course_id="c1", course_name="Curso", path=tmp_path / "manifest.json")


def _items():
    return [
        Item(
            kind="materials",
            item_id="m1",
            title="Guía",
            date=date(2026, 3, 10),
            files=(DriveAttachment("f1", "guia.pdf"),),
            links=(LinkAttachment("Web", "https://example.com/x"),),
        ),
        Item(
            kind="coursework",
            item_id="cw1",
            title="Taller 1",
            date=date(2026, 3, 12),
            files=(DriveAttachment("f2", "taller.pdf"),),
        ),
    ]


def _sync(tmp_path, downloader, options=None, manifest=None, items=None):
    output = tmp_path / "out"
    manifest = manifest or _manifest(tmp_path)
    result = sync_course(
        fetcher=FakeFetcher(items if items is not None else _items()),
        downloader=downloader,
        course_id="c1",
        course_name="Curso",
        output_root=output,
        manifest=manifest,
        options=options or SyncOptions(),
    )
    return result, manifest, output


def test_sync_downloads_files_and_links(tmp_path):
    downloader = FakeDownloader()
    result, manifest, output = _sync(tmp_path, downloader)

    assert result.items == 2
    assert result.downloaded == 2
    assert result.links == 1
    assert result.errors == []

    guide = output / "Curso" / "Materiales" / "2026-03-10 - Guía" / "guia.pdf"
    assert guide.read_text() == "abc"
    link = output / "Curso" / "Enlaces" / "2026-03-10 - Guía" / "Web.url"
    assert "https://example.com/x" in link.read_text()

    assert manifest.get("file:m1:f1") is not None
    assert manifest.get("file:cw1:f2") is not None
    assert manifest.get("link:m1:1") is not None
    assert manifest.last_sync is not None


def test_sync_is_idempotent(tmp_path):
    downloader = FakeDownloader()
    _sync(tmp_path, downloader)
    downloader.download_calls.clear()

    manifest = Manifest(course_id="c1", path=tmp_path / "manifest.json")
    manifest.load()
    result, _, _ = _sync(tmp_path, downloader, manifest=manifest)

    assert downloader.download_calls == []
    assert result.skipped == 3  # 2 archivos + 1 enlace
    assert result.downloaded == 0


def test_sync_dry_run_writes_nothing(tmp_path):
    downloader = FakeDownloader()
    result, manifest, output = _sync(
        tmp_path, downloader, options=SyncOptions(dry_run=True)
    )

    assert result.downloaded == 2
    assert result.links == 1
    assert downloader.download_calls == []
    assert not output.exists()
    assert not (tmp_path / "manifest.json").exists()


def test_sync_refresh_skips_unchanged_and_updates_changed(tmp_path):
    downloader = FakeDownloader()
    _sync(tmp_path, downloader)

    manifest = Manifest(course_id="c1", path=tmp_path / "manifest.json")
    manifest.load()
    downloader.download_calls.clear()
    downloader.metadata_calls.clear()

    result, _, _ = _sync(
        tmp_path, downloader, options=SyncOptions(refresh=True), manifest=manifest
    )
    assert result.skipped == 2
    assert downloader.download_calls == []
    assert set(downloader.metadata_calls) == {"f1", "f2"}

    downloader.modified = "2026-02-02T00:00:00Z"
    manifest = Manifest(course_id="c1", path=tmp_path / "manifest.json")
    manifest.load()
    result, _, _ = _sync(
        tmp_path, downloader, options=SyncOptions(refresh=True), manifest=manifest
    )
    assert result.updated == 2
    assert set(downloader.download_calls) == {"f1", "f2"}


def test_sync_isolates_file_errors(tmp_path):
    downloader = FakeDownloader(fail_ids={"f1"})
    result, manifest, output = _sync(tmp_path, downloader)

    assert result.downloaded == 1
    assert len(result.errors) == 1
    assert not result.ok
    assert manifest.get("file:m1:f1") is None
    assert (output / "Curso" / "Tareas" / "2026-03-12 - Taller 1" / "taller.pdf").exists()


def test_sync_filters_kinds(tmp_path):
    downloader = FakeDownloader()
    result, _, output = _sync(
        tmp_path, downloader, options=SyncOptions(kinds=("coursework",))
    )
    assert result.items == 1
    assert downloader.download_calls == ["f2"]
    assert not (output / "Curso" / "Materiales").exists()


def test_sync_since_filters_items(tmp_path):
    downloader = FakeDownloader()
    result, _, _ = _sync(
        tmp_path, downloader, options=SyncOptions(since=date(2026, 3, 11))
    )
    assert result.items == 1
    assert downloader.download_calls == ["f2"]


def test_sync_prune_forgets_missing_files(tmp_path):
    downloader = FakeDownloader()
    _, manifest, _ = _sync(tmp_path, downloader)
    manifest.record("file:gone:999", ManifestEntry(path="Curso/Materiales/gone.pdf"))
    manifest.save(force=True)

    manifest.load()
    result, manifest, _ = _sync(
        tmp_path, downloader, options=SyncOptions(prune=True), manifest=manifest
    )
    assert manifest.get("file:gone:999") is None
    assert result.errors == []


def test_sync_duplicate_names_get_suffix(tmp_path):
    items = [
        Item(
            kind="materials",
            item_id="m1",
            title="Guía",
            date=date(2026, 3, 10),
            files=(DriveAttachment("f1", "guia.pdf"), DriveAttachment("f2", "guia.pdf")),
        )
    ]
    downloader = FakeDownloader()
    result, _, output = _sync(tmp_path, downloader, items=items)

    folder = output / "Curso" / "Materiales" / "2026-03-10 - Guía"
    assert result.downloaded == 2
    assert (folder / "guia.pdf").exists()
    assert (folder / "guia (2).pdf").exists()
