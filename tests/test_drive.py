from pathlib import Path

import classroom_dl.drive as drive_module
from classroom_dl.api import DriveAttachment, LinkAttachment
from classroom_dl.drive import (
    EXPORT_FORMATS,
    DriveDownloader,
    DriveMetadata,
    _extension_for,
    _non_clashing_path,
    _strip_known_extension,
    _with_extension,
    write_link,
)


def test_export_formats_cover_docs_sheets_slides():
    assert "application/vnd.google-apps.document" in EXPORT_FORMATS
    assert EXPORT_FORMATS["application/vnd.google-apps.document"]["pdf"][1] == ".pdf"
    assert EXPORT_FORMATS["application/vnd.google-apps.spreadsheet"]["csv"][1] == ".csv"
    assert EXPORT_FORMATS["application/vnd.google-apps.presentation"]["pdf"][1] == ".pdf"


def test_extension_for_prefers_existing_suffix():
    meta = DriveMetadata("1", "tarea.zip", "application/zip")
    assert _extension_for(meta, DriveAttachment("1", "tarea.zip")) == ".zip"


def test_extension_for_uses_mime_when_no_suffix():
    meta = DriveMetadata("1", "sin-extension", "application/pdf")
    assert _extension_for(meta, DriveAttachment("1", "sin-extension")) == ".pdf"


def test_extension_for_unknown_mime_falls_back_to_bin():
    meta = DriveMetadata("1", "raro", "application/x-inventado")
    assert _extension_for(meta, DriveAttachment("1", "raro")) == ".bin"


def test_extension_for_ignores_numeric_suffix():
    meta = DriveMetadata("1", "Tarea 1.2", "application/pdf")
    assert _extension_for(meta, DriveAttachment("1", "Tarea 1.2")) == ".pdf"


def test_with_extension_does_not_duplicate():
    assert _with_extension("guia", ".pdf") == "guia.pdf"
    assert _with_extension("guia.PDF", ".pdf") == "guia.PDF"
    assert _with_extension("guia.pdf", ".docx") == "guia.pdf.docx"


def test_strip_known_extension_only_known_ones():
    assert _strip_known_extension("guia.pdf") == "guia"
    assert _strip_known_extension("Tarea 1.2") == "Tarea 1.2"


def test_non_clashing_path(tmp_path):
    path = tmp_path / "guia.pdf"
    path.write_text("x")
    assert _non_clashing_path(path).name == "guia (2).pdf"
    (tmp_path / "guia (2).pdf").write_text("x")
    assert _non_clashing_path(path).name == "guia (3).pdf"
    assert _non_clashing_path(tmp_path / "libre.pdf").name == "libre.pdf"


def test_write_link_creates_url_shortcut(tmp_path):
    path = write_link(
        tmp_path / "Enlaces",
        LinkAttachment(title="Formulario", url="https://forms.example/x"),
        "Formulario",
    )
    assert path == tmp_path / "Enlaces" / "Formulario.url"
    content = path.read_text()
    assert "[InternetShortcut]" in content
    assert "https://forms.example/x" in content
    assert isinstance(path, Path)


class FakeStatus:
    def __init__(self, resumable_progress, total_size):
        self.resumable_progress = resumable_progress
        self.total_size = total_size


class FakeMediaDownload:
    def __init__(self, handle, request, chunksize=None):
        self.handle = handle
        self._chunks = [(b"abc", 3, 6), (b"def", 6, 6)]
        self._index = 0

    def next_chunk(self):
        chunk, progress, total = self._chunks[self._index]
        self.handle.write(chunk)
        self._index += 1
        return FakeStatus(progress, total), self._index == len(self._chunks)


class RecordingProgress:
    def __init__(self):
        self.added = []
        self.updates = []
        self.finished = []
        self.failed = []

    def start_session(self):
        pass

    def stop_session(self):
        pass

    def add_task(self, name, total, *, dest_dir=None):
        self.added.append((name, total, dest_dir))
        return len(self.added) - 1

    def update_task(self, task_id, downloaded, total):
        self.updates.append((task_id, downloaded, total))

    def finish_task(self, task_id, path, size):
        self.finished.append((task_id, path, size))

    def fail_task(self, task_id, message):
        self.failed.append((task_id, message))


class FakeFiles:
    def get_media(self, **kwargs):
        return object()


class FakeService:
    def files(self):
        return FakeFiles()


def test_download_to_file_reports_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(drive_module, "MediaIoBaseDownload", FakeMediaDownload)
    downloader = DriveDownloader(credentials=None)  # type: ignore[arg-type]
    progress = RecordingProgress()
    task_id = progress.add_task("archivo.bin", 6)
    path = tmp_path / "archivo.bin"

    downloader._download_to_file(
        object(),
        path,
        expected_size=6,
        file_id="f1",
        progress=progress,
        task_id=task_id,
    )

    assert path.read_bytes() == b"abcdef"
    assert progress.updates[0] == (task_id, 0, 6)
    assert progress.updates[-1] == (task_id, 6, 6)


def test_download_starts_and_finishes_progress_task(tmp_path, monkeypatch):
    monkeypatch.setattr(drive_module, "build", lambda *args, **kwargs: FakeService())
    monkeypatch.setattr(drive_module, "MediaIoBaseDownload", FakeMediaDownload)
    downloader = DriveDownloader(credentials=None)  # type: ignore[arg-type]
    monkeypatch.setattr(
        downloader,
        "metadata",
        lambda file_id: DriveMetadata(
            file_id=file_id,
            name="archivo.bin",
            mime_type="application/octet-stream",
            size=6,
        ),
    )
    progress = RecordingProgress()

    result = downloader.download(
        DriveAttachment("f1", "archivo.bin"),
        tmp_path,
        "archivo",
        progress=progress,
    )

    assert result.path == tmp_path / "archivo.bin"
    assert result.size == 6
    assert result.elapsed is not None
    assert progress.added == [("archivo.bin", 6, tmp_path)]
    assert progress.finished == [(0, tmp_path / "archivo.bin", 6)]
    assert progress.failed == []
