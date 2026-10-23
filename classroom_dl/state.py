"""Manifest de sincronización: qué se descargó y cuándo."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .config import manifests_dir
from .paths import sanitize_name

MANIFEST_VERSION = 1


@dataclass
class ManifestEntry:
    path: str
    modified_time: str | None = None
    size: int | None = None
    title: str | None = None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "modified_time": self.modified_time,
            "size": self.size,
            "title": self.title,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ManifestEntry:
        size = data.get("size")
        return cls(
            path=str(data.get("path", "")),
            modified_time=data.get("modified_time"),
            size=size if isinstance(size, int) else None,
            title=data.get("title"),
        )


@dataclass
class Manifest:
    """Estado de un curso, persistido en un JSON por curso."""

    course_id: str
    course_name: str = ""
    path: Path | None = None
    files: dict[str, ManifestEntry] = field(default_factory=dict)
    last_sync: str | None = None
    _dirty: int = 0
    save_every: int = 25

    @classmethod
    def for_course(cls, course_id: str, course_name: str = "") -> Manifest:
        filename = f"{sanitize_name(course_id, fallback='curso')}.json"
        manifest = cls(
            course_id=course_id,
            course_name=course_name,
            path=manifests_dir() / filename,
        )
        manifest.load()
        if course_name:
            manifest.course_name = course_name
        return manifest

    def load(self) -> None:
        if not self.path or not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        self.course_name = str(raw.get("course_name") or self.course_name)
        self.last_sync = raw.get("last_sync")
        files = raw.get("files")
        if isinstance(files, dict):
            for file_id, entry in files.items():
                if isinstance(entry, dict) and entry.get("path"):
                    self.files[str(file_id)] = ManifestEntry.from_dict(entry)

    # ----------------------------------------------------------------- consulta

    def get(self, file_id: str) -> ManifestEntry | None:
        return self.files.get(file_id)

    def is_downloaded(self, file_id: str, output_root: Path) -> bool:
        entry = self.files.get(file_id)
        if entry is None or not entry.path:
            return False
        candidate = Path(entry.path)
        if not candidate.is_absolute():
            candidate = output_root / candidate
        return candidate.exists()

    def set_last_sync(self, when: datetime | None = None) -> None:
        moment = when or datetime.now(timezone.utc)
        self.last_sync = moment.isoformat(timespec="seconds")
        self._dirty += 1

    # ---------------------------------------------------------------- escritura

    def record(self, file_id: str, entry: ManifestEntry) -> None:
        self.files[file_id] = entry
        self._dirty += 1
        if self._dirty >= self.save_every:
            self.save()

    def remove(self, file_id: str) -> None:
        if self.files.pop(file_id, None) is not None:
            self._dirty += 1

    def save(self, *, force: bool = False) -> None:
        if not self.path:
            return
        if self._dirty == 0 and not force:
            return
        payload = {
            "version": MANIFEST_VERSION,
            "course_id": self.course_id,
            "course_name": self.course_name,
            "last_sync": self.last_sync,
            "files": {file_id: entry.to_dict() for file_id, entry in sorted(self.files.items())},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
            self._dirty = 0
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)

    # ------------------------------------------------------------------ resumen

    def stats(self, output_root: Path) -> tuple[int, int, int]:
        """(archivos registrados, presentes en disco, bytes totales)."""
        present = 0
        total_size = 0
        for entry in self.files.values():
            candidate = Path(entry.path)
            if not candidate.is_absolute():
                candidate = output_root / candidate
            if candidate.exists():
                present += 1
                if entry.size:
                    total_size += entry.size
                else:
                    try:
                        total_size += candidate.stat().st_size
                    except OSError:
                        pass
        return len(self.files), present, total_size


def list_manifests() -> list[Manifest]:
    """Carga todos los manifests guardados."""
    manifests: list[Manifest] = []
    for path in sorted(manifests_dir().glob("*.json")):
        manifest = Manifest(course_id=path.stem, path=path)
        manifest.load()
        manifests.append(manifest)
    return manifests
