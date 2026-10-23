from pathlib import Path

from classroom_dl.api import DriveAttachment, LinkAttachment
from classroom_dl.drive import (
    EXPORT_FORMATS,
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
