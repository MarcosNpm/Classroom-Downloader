"""Descarga de archivos de Google Drive, incluida la exportación de Google Docs."""

from __future__ import annotations

import json
import mimetypes
import os
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from .api import DriveAttachment, LinkAttachment
from .errors import DownloadError

CHUNK_SIZE = 8 * 1024 * 1024
MAX_ATTEMPTS = 6

# Tipos nativos de Google que se exportan a un formato "real".
# mime -> {formato: (mime de exportación, extensión)}
EXPORT_FORMATS: dict[str, dict[str, tuple[str, str]]] = {
    "application/vnd.google-apps.document": {
        "pdf": ("application/pdf", ".pdf"),
        "docx": (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".docx",
        ),
        "txt": ("text/plain", ".txt"),
        "html": ("text/html", ".html"),
    },
    "application/vnd.google-apps.spreadsheet": {
        "xlsx": (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xlsx",
        ),
        "csv": ("text/csv", ".csv"),
        "pdf": ("application/pdf", ".pdf"),
    },
    "application/vnd.google-apps.presentation": {
        "pptx": (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".pptx",
        ),
        "pdf": ("application/pdf", ".pdf"),
    },
    "application/vnd.google-apps.drawing": {
        "pdf": ("application/pdf", ".pdf"),
        "png": ("image/png", ".png"),
    },
}

# Extensiones que podemos haber añadido nosotros y que conviene reemplazar.
_REPLACEABLE_EXTS = {
    ".pdf",
    ".docx",
    ".txt",
    ".html",
    ".xlsx",
    ".csv",
    ".pptx",
    ".png",
    ".jpg",
    ".jpeg",
    ".zip",
    ".mp4",
    ".mp3",
}

_MIME_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/json": ".json",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "text/html": ".html",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}


@dataclass(frozen=True)
class DriveMetadata:
    file_id: str
    name: str
    mime_type: str
    modified_time: str | None = None
    size: int | None = None
    trashed: bool = False


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    modified_time: str | None = None
    size: int | None = None
    is_shortcut: bool = False


class DriveDownloader:
    """Descarga archivos usando un servicio de Drive por hilo."""

    def __init__(self, credentials: Credentials) -> None:
        self._credentials = credentials
        self._local = threading.local()
        self._cache: dict[str, DriveMetadata] = {}
        self._lock = threading.Lock()

    # ----------------------------------------------------------------- servicio

    @property
    def _service(self):
        service = getattr(self._local, "service", None)
        if service is None:
            service = build("drive", "v3", credentials=self._credentials, cache_discovery=False)
            self._local.service = service
        return service

    # ---------------------------------------------------------------- metadatos

    def metadata(self, file_id: str) -> DriveMetadata:
        with self._lock:
            cached = self._cache.get(file_id)
        if cached is not None:
            return cached

        try:
            raw = self._service.files().get(
                fileId=file_id,
                fields="id,name,mimeType,modifiedTime,size,trashed,shortcutDetails",
                supportsAllDrives=True,
            ).execute()
        except HttpError as exc:
            raise DownloadError(_friendly_http_error(exc, file_id)) from exc

        if raw.get("trashed"):
            raise DownloadError("El archivo está en la papelera de Drive")

        # Resolver accesos directos de Drive a su archivo real.
        if (
            raw.get("mimeType") == "application/vnd.google-apps.shortcut"
            and isinstance(raw.get("shortcutDetails"), dict)
            and raw["shortcutDetails"].get("targetId")
        ):
            target = self.metadata(str(raw["shortcutDetails"]["targetId"]))
            with self._lock:
                self._cache[file_id] = target
            return target

        size = raw.get("size")
        meta = DriveMetadata(
            file_id=str(raw.get("id", file_id)),
            name=str(raw.get("name") or file_id),
            mime_type=str(raw.get("mimeType") or ""),
            modified_time=raw.get("modifiedTime"),
            size=int(size) if size is not None else None,
            trashed=bool(raw.get("trashed")),
        )
        with self._lock:
            self._cache[file_id] = meta
        return meta

    # ----------------------------------------------------------------- descarga

    def download(
        self,
        attachment: DriveAttachment,
        dest_dir: Path,
        basename: str,
        *,
        docs_format: str = "pdf",
        sheets_format: str = "xlsx",
        overwrite: bool = True,
    ) -> DownloadResult:
        meta = self.metadata(attachment.file_id)
        dest_dir.mkdir(parents=True, exist_ok=True)

        export = EXPORT_FORMATS.get(meta.mime_type)
        if export is not None:
            preferred = sheets_format if "spreadsheet" in meta.mime_type else docs_format
            spec = export.get(preferred) or export.get("pdf")
            if spec is None:  # pragma: no cover - todas las tablas tienen pdf
                spec = next(iter(export.values()))
            export_mime, extension = spec
            filename = _with_extension(_strip_known_extension(basename), extension)
            request = self._service.files().export_media(
                fileId=attachment.file_id, mimeType=export_mime
            )
        elif meta.mime_type.startswith("application/vnd.google-apps."):
            # Formularios, Sites, Apps Script...: no se pueden exportar, se guarda un enlace.
            return self._write_shortcut(attachment, dest_dir, basename, meta)
        elif meta.mime_type == "application/vnd.google-apps.folder":
            raise DownloadError("Es una carpeta de Drive, no un archivo")
        else:
            extension = _extension_for(meta, attachment)
            filename = (
                basename
                if basename.lower().endswith(extension.lower())
                else basename + extension
            )
            request = self._service.files().get_media(
                fileId=attachment.file_id, supportsAllDrives=True
            )

        path = dest_dir / filename
        if not overwrite:
            path = _non_clashing_path(path)
        self._download_to_file(
            request,
            path,
            expected_size=meta.size if export is None else None,
            file_id=attachment.file_id,
        )
        size = path.stat().st_size
        return DownloadResult(path=path, modified_time=meta.modified_time, size=size)

    def _write_shortcut(
        self,
        attachment: DriveAttachment,
        dest_dir: Path,
        basename: str,
        meta: DriveMetadata,
    ) -> DownloadResult:
        url = attachment.url or f"https://drive.google.com/open?id={attachment.file_id}"
        path = dest_dir / _with_extension(_strip_known_extension(basename), ".url")
        path.write_text(f"[InternetShortcut]\nURL={url}\n", encoding="utf-8")
        return DownloadResult(
            path=path,
            modified_time=meta.modified_time,
            size=path.stat().st_size,
            is_shortcut=True,
        )

    def _download_to_file(
        self, request, path: Path, *, expected_size: int | None, file_id: str
    ) -> None:
        part = path.with_name(path.name + ".part")
        if part.exists():
            part.unlink()

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with part.open("wb") as handle:
                    downloader = MediaIoBaseDownload(handle, request, chunksize=CHUNK_SIZE)
                    done = False
                    while not done:
                        _, done = downloader.next_chunk()
                break
            except HttpError as exc:
                part.unlink(missing_ok=True)
                status = getattr(exc.resp, "status", None)
                if status in (429, 500, 502, 503, 504) and attempt < MAX_ATTEMPTS:
                    time.sleep(min(60.0, 2 ** (attempt - 1)) + random.uniform(0, 0.5))
                    # La petición es reutilizable: se reinicia la descarga.
                    continue
                raise DownloadError(_friendly_http_error(exc, file_id)) from exc
            except OSError as exc:
                part.unlink(missing_ok=True)
                raise DownloadError(f"Error escribiendo {path}: {exc}") from exc
        else:  # pragma: no cover - el bucle siempre rompe o lanza
            raise DownloadError("Se agotaron los reintentos")

        if expected_size is not None and part.stat().st_size != expected_size:
            size = part.stat().st_size
            part.unlink(missing_ok=True)
            raise DownloadError(
                f"Descarga incompleta ({size} de {expected_size} bytes). "
                "Vuelve a ejecutar sync para reintentar."
            )
        os.replace(part, path)


def write_link(dest_dir: Path, link: LinkAttachment, basename: str) -> Path:
    """Guarda un enlace (YouTube, Formulario, web) como acceso directo .url."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / _with_extension(_strip_known_extension(basename), ".url")
    path.write_text(f"[InternetShortcut]\nURL={link.url}\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------- nombres


def _extension_for(meta: DriveMetadata, attachment: DriveAttachment) -> str:
    for candidate in (meta.name, attachment.title):
        suffix = Path(candidate).suffix
        # ".2" en "Tarea 1.2" no es una extensión; ".pdf" sí.
        if suffix and 1 < len(suffix) <= 12 and any(ch.isalpha() for ch in suffix):
            return suffix
    mime = meta.mime_type.split(";")[0].strip().lower()
    if mime in _MIME_EXTENSIONS:
        return _MIME_EXTENSIONS[mime]
    guessed = mimetypes.guess_extension(mime) if mime else None
    if guessed in (".jpe", ".jpeg"):
        return ".jpg"
    return guessed or ".bin"


def _with_extension(basename: str, extension: str) -> str:
    if basename.lower().endswith(extension.lower()):
        return basename
    return basename + extension


def _non_clashing_path(path: Path) -> Path:
    """Si ya existe algo con ese nombre, prueba 'nombre (2).ext', etc."""
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    counter = 2
    while True:
        candidate = path.with_name(f"{stem} ({counter}){suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _strip_known_extension(basename: str) -> str:
    suffix = Path(basename).suffix
    if suffix.lower() in _REPLACEABLE_EXTS:
        return basename[: -len(suffix)].rstrip()
    return basename


def _friendly_http_error(exc: HttpError, file_id: str) -> str:
    status = getattr(exc.resp, "status", "?")
    reason = ""
    content = getattr(exc, "content", b"") or b""
    try:
        parsed = json.loads(content.decode("utf-8", "ignore"))
        reason = str(parsed.get("error", {}).get("message") or "")
    except (ValueError, AttributeError):
        pass
    if status == 403:
        hint = "sin permiso para descargarlo (¿el profesor restringió el acceso?)"
    elif status == 404:
        hint = "ya no existe o no tienes acceso"
    elif status == 429:
        hint = "demasiadas peticiones; reintenta más tarde"
    else:
        hint = "error de Drive"
    return f"No pude descargar {file_id}: {hint}" + (f" ({reason})" if reason else "")
