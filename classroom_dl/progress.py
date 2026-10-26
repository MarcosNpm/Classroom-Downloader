"""Protocolo de progreso para las descargas.

El descargador no conoce la terminal: sólo avisa cuándo empieza, avanza y
termina cada archivo. La implementación concreta vive en la capa de UI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class DownloadProgress(Protocol):
    """Recibe el progreso de cada archivo descargado."""

    def start_session(self) -> None: ...

    def stop_session(self) -> None: ...

    def add_task(self, name: str, total: int | None, *, dest_dir: Path | None = None) -> int: ...

    def update_task(self, task_id: int, downloaded: int, total: int | None) -> None: ...

    def finish_task(self, task_id: int, path: Path, size: int) -> None: ...

    def fail_task(self, task_id: int, message: str) -> None: ...


class NullDownloadProgress:
    """Implementación vacía para tests y para el modo sin verbose."""

    def start_session(self) -> None:
        pass

    def stop_session(self) -> None:
        pass

    def add_task(self, name: str, total: int | None, *, dest_dir: Path | None = None) -> int:
        return -1

    def update_task(self, task_id: int, downloaded: int, total: int | None) -> None:
        pass

    def finish_task(self, task_id: int, path: Path, size: int) -> None:
        pass

    def fail_task(self, task_id: int, message: str) -> None:
        pass
