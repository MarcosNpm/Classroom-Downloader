"""Orquestación de la descarga de un curso."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .api import ALL_KINDS, DriveAttachment, Item, LinkAttachment
from .drive import DownloadResult, DriveMetadata, write_link
from .paths import KIND_FOLDERS, course_folder_name, item_folder_name, sanitize_name, unique_name
from .progress import DownloadProgress
from .state import Manifest, ManifestEntry


class Fetcher(Protocol):
    def items(
        self, course_id: str, kinds: Iterable[str] = ALL_KINDS, *, since: dt.date | None = None
    ) -> Iterator[Item]: ...


class Downloader(Protocol):
    def metadata(self, file_id: str) -> DriveMetadata: ...

    def download(
        self,
        attachment: DriveAttachment,
        dest_dir: Path,
        basename: str,
        *,
        docs_format: str = "pdf",
        sheets_format: str = "xlsx",
        overwrite: bool = True,
        progress: DownloadProgress | None = None,
    ) -> DownloadResult: ...


class Reporter(Protocol):
    def info(self, message: str) -> None: ...
    def ok(self, message: str) -> None: ...
    def download(
        self, message: str, *, size: int | None = None, elapsed: float | None = None
    ) -> None: ...
    def skip(self, message: str) -> None: ...
    def warn(self, message: str) -> None: ...
    def error(self, message: str) -> None: ...


class NullReporter:
    def info(self, message: str) -> None: ...
    def ok(self, message: str) -> None: ...
    def download(
        self, message: str, *, size: int | None = None, elapsed: float | None = None
    ) -> None: ...
    def skip(self, message: str) -> None: ...
    def warn(self, message: str) -> None: ...
    def error(self, message: str) -> None: ...


@dataclass
class SyncOptions:
    kinds: tuple[str, ...] = ALL_KINDS
    dry_run: bool = False
    refresh: bool = False
    since: dt.date | None = None
    docs_format: str = "pdf"
    sheets_format: str = "xlsx"
    jobs: int = 2
    links: bool = True
    prune: bool = False


@dataclass
class SyncResult:
    course_name: str
    items: int = 0
    downloaded: int = 0
    updated: int = 0
    skipped: int = 0
    links: int = 0
    bytes: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        parts = [
            f"{self.downloaded} nuevos",
            f"{self.updated} actualizados",
            f"{self.skipped} ya estaban",
            f"{self.links} enlaces",
            human_size(self.bytes),
        ]
        if self.errors:
            parts.append(f"{len(self.errors)} errores")
        return ", ".join(parts)


@dataclass(frozen=True)
class _Task:
    key: str
    attachment: DriveAttachment
    dest_dir: Path
    basename: str


def sync_course(
    *,
    fetcher: Fetcher,
    downloader: Downloader,
    course_id: str,
    course_name: str,
    output_root: Path,
    manifest: Manifest,
    options: SyncOptions,
    reporter: Reporter | None = None,
    progress: DownloadProgress | None = None,
) -> SyncResult:
    """Sincroniza un curso. No lanza por errores de archivos sueltos."""
    reporter = reporter or NullReporter()
    result = SyncResult(course_name=course_name)
    course_dir = output_root / course_folder_name(course_name)

    used_names: dict[Path, set[str]] = {}
    tasks: list[_Task] = []
    link_writes: list[tuple[str, Path, str, LinkAttachment]] = []

    items = list(fetcher.items(course_id, options.kinds, since=options.since))
    result.items = len(items)

    for item in items:
        item_dir = course_dir / KIND_FOLDERS.get(item.kind, item.kind.title()) / item_folder_name(
            item.date, item.title
        )

        for index, attachment in enumerate(item.files, start=1):
            key = f"file:{item.item_id}:{attachment.file_id}"
            basename = unique_name(
                sanitize_name(attachment.title, fallback=f"archivo-{index}"),
                used_names.setdefault(item_dir, set()),
            )
            entry = manifest.get(key)
            target = _entry_path(entry, output_root)

            if not options.refresh and entry is not None and target is not None and target.exists():
                result.skipped += 1
                reporter.skip(f"{item_dir.name}/{basename}")
                continue

            if options.refresh and entry is not None and target is not None and target.exists():
                try:
                    meta = downloader.metadata(attachment.file_id)
                except Exception as exc:  # noqa: BLE001 - se reporta y se reintenta abajo
                    reporter.warn(f"No pude verificar {attachment.title}: {exc}")
                else:
                    if entry.modified_time and entry.modified_time == meta.modified_time:
                        result.skipped += 1
                        reporter.skip(f"{item_dir.name}/{basename} (sin cambios)")
                        continue

            if options.dry_run:
                result.downloaded += 1
                reporter.info(f"[dry-run] descargaría {item_dir.name}/{basename}")
                continue

            tasks.append(
                _Task(key=key, attachment=attachment, dest_dir=item_dir, basename=basename)
            )

        if options.links:
            for index, link in enumerate(item.links, start=1):
                link_dir = course_dir / "Enlaces" / item_folder_name(item.date, item.title)
                key = f"link:{item.item_id}:{index}"
                basename = unique_name(
                    sanitize_name(link.title, fallback=f"enlace-{index}"),
                    used_names.setdefault(link_dir, set()),
                )
                entry = manifest.get(key)
                target = _entry_path(entry, output_root)
                if (
                    not options.refresh
                    and entry is not None
                    and target is not None
                    and target.exists()
                ):
                    result.skipped += 1
                    continue
                if options.dry_run:
                    result.links += 1
                    reporter.info(f"[dry-run] guardaría enlace {link_dir.name}/{basename}.url")
                    continue
                link_writes.append((key, link_dir, basename, link))

    if tasks:
        if progress is not None:
            progress.start_session()
        try:
            _run_downloads(
                tasks,
                downloader,
                manifest,
                output_root,
                options,
                reporter,
                result,
                progress,
            )
        finally:
            if progress is not None:
                progress.stop_session()

    for key, link_dir, basename, link in link_writes:
        try:
            path = write_link(link_dir, link, basename)
        except OSError as exc:
            result.errors.append((link.title, str(exc)))
            reporter.error(f"No pude guardar el enlace {link.title}: {exc}")
        else:
            manifest.record(
                key,
                ManifestEntry(
                    path=_relative(path, output_root), size=path.stat().st_size, title=link.title
                ),
            )
            result.links += 1

    manifest.course_name = course_name
    if options.dry_run:
        return result

    manifest.set_last_sync()
    manifest.save(force=True)

    if options.prune:
        _prune(manifest, output_root, reporter, result)

    return result


def _run_downloads(
    tasks: list[_Task],
    downloader: Downloader,
    manifest: Manifest,
    output_root: Path,
    options: SyncOptions,
    reporter: Reporter,
    result: SyncResult,
    progress: DownloadProgress | None = None,
) -> None:
    jobs = max(1, min(options.jobs, 8))
    with ThreadPoolExecutor(max_workers=jobs, thread_name_prefix="dl") as pool:
        futures = {
            pool.submit(
                downloader.download,
                task.attachment,
                task.dest_dir,
                task.basename,
                docs_format=options.docs_format,
                sheets_format=options.sheets_format,
                overwrite=manifest.get(task.key) is not None,
                progress=progress,
            ): task
            for task in tasks
        }
        try:
            for future in as_completed(futures):
                task = futures[future]
                try:
                    download: DownloadResult = future.result()
                except Exception as exc:  # noqa: BLE001 - un archivo no tumba el sync
                    result.errors.append((task.attachment.title, str(exc)))
                    reporter.error(f"{task.attachment.title}: {exc}")
                    continue

                existing = manifest.get(task.key)
                if existing is not None:
                    result.updated += 1
                else:
                    result.downloaded += 1
                result.bytes += download.size or 0

                manifest.record(
                    task.key,
                    ManifestEntry(
                        path=_relative(download.path, output_root),
                        modified_time=download.modified_time,
                        size=download.size,
                        title=task.attachment.title,
                    ),
                )
                suffix = " (enlace)" if download.is_shortcut else ""
                reporter.download(
                    f"{_relative(download.path, output_root)}{suffix}",
                    size=download.size,
                    elapsed=download.elapsed,
                )
        except KeyboardInterrupt:
            reporter.warn("Interrumpido: guardando lo descargado hasta ahora...")
            for future in futures:
                future.cancel()
            raise
        finally:
            manifest.save(force=True)


def _prune(manifest: Manifest, output_root: Path, reporter: Reporter, result: SyncResult) -> None:
    """Elimina registros de archivos que ya no existen en disco (no borra archivos)."""
    missing = []
    for key, entry in manifest.files.items():
        path = _entry_path(entry, output_root)
        if path is None or not path.exists():
            missing.append(key)
    for key in missing:
        manifest.remove(key)
        reporter.info(f"Olvidado en el manifest (no está en disco): {key}")
    if missing:
        manifest.save(force=True)


def _entry_path(entry: ManifestEntry | None, output_root: Path) -> Path | None:
    if entry is None or not entry.path:
        return None
    path = Path(entry.path)
    return path if path.is_absolute() else output_root / path


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def human_size(num: int) -> str:
    """Formatea una cantidad de bytes para mostrarla en la terminal."""
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"
