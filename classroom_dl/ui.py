"""Presentación en terminal: tablas, mensajes y selección interactiva."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

import questionary
from rich.console import Console
from rich.markup import escape
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Column, Table

from .api import KIND_LABELS, Course, Item
from .errors import ClassroomDLError
from .sync import SyncResult, human_size

# Serializa la salida cuando hay descargas en paralelo. Rich usa un buffer
# interno y dos hilos imprimiendo a la vez pueden mezclar líneas.
_OUTPUT_LOCK = threading.RLock()


class RichReporter:
    """Implementa el protocolo Reporter de sync con rich."""

    def __init__(self, console: Console, *, verbose: bool = False) -> None:
        self.console = console
        self.verbose = verbose

    def info(self, message: str) -> None:
        with _OUTPUT_LOCK:
            self.console.print(f"[dim]{message}[/]")

    def ok(self, message: str) -> None:
        with _OUTPUT_LOCK:
            self.console.print(f"[green]↓[/] {message}")

    def download(
        self, message: str, *, size: int | None = None, elapsed: float | None = None
    ) -> None:
        message = escape(message)
        with _OUTPUT_LOCK:
            if self.verbose and size is not None and elapsed is not None and elapsed > 0:
                speed = size / elapsed
                self.console.print(
                    f"[green]↓[/] {message} "
                    f"[dim]({human_size(size)} en {elapsed:.1f}s · {human_size(int(speed))}/s)[/]"
                )
            else:
                self.console.print(f"[green]↓[/] {message}")

    def skip(self, message: str) -> None:
        if self.verbose:
            with _OUTPUT_LOCK:
                self.console.print(f"[dim]· {message}[/]")

    def warn(self, message: str) -> None:
        with _OUTPUT_LOCK:
            self.console.print(f"[yellow]![/] {message}")

    def error(self, message: str) -> None:
        with _OUTPUT_LOCK:
            self.console.print(f"[red]✗[/] {message}")


@dataclass
class _LineTask:
    label: str
    total: int | None
    started: float
    last_update: float = 0.0
    downloaded: int = 0


def _download_label(name: str, dest_dir: Path | None) -> str:
    if dest_dir is not None and dest_dir.name:
        return f"{dest_dir.name}/{name}"
    return name


class RichDownloadProgress:
    """Progreso de descargas para `sync --verbose`.

    En una terminal muestra barras en vivo con tamaño, porcentaje, velocidad y
    tiempo restante. Si la salida está redirigida (cron, archivo de log), usa
    líneas de texto simples para no meter códigos ANSI en el log.
    """

    def __init__(self, console: Console, *, enabled: bool = True) -> None:
        self.console = console
        self.enabled = enabled
        self._live = enabled and console.is_terminal and not console.is_dumb_terminal
        self._lock = threading.RLock()
        self._next_id = 0
        self._line_tasks: dict[int, _LineTask] = {}
        self._progress: Progress | None = None
        if self._live:
            self._progress = Progress(
                SpinnerColumn(),
                TextColumn(
                    "{task.description}",
                    style="bold",
                    markup=False,
                    table_column=Column(ratio=3, no_wrap=True),
                ),
                BarColumn(bar_width=None, table_column=Column(ratio=2)),
                DownloadColumn(binary_units=True),
                TransferSpeedColumn(),
                TimeRemainingColumn(compact=True),
                console=console,
            )

    # ------------------------------------------------------------- sesión
    def start_session(self) -> None:
        if self._progress is None:
            return
        with self._lock:
            self._progress.start()

    def stop_session(self) -> None:
        if self._progress is None:
            with self._lock:
                self._line_tasks.clear()
            return
        with self._lock:
            self._progress.stop()
            for task_id in self._progress.task_ids:
                self._progress.remove_task(task_id)

    # ------------------------------------------------------------ tareas
    def add_task(self, name: str, total: int | None, *, dest_dir: Path | None = None) -> int:
        if not self.enabled:
            return -1
        label = _download_label(name, dest_dir)
        if self._progress is not None:
            with self._lock:
                return self._progress.add_task(label, total=total)
        with self._lock:
            task_id = self._next_id
            self._next_id += 1
            now = time.monotonic()
            self._line_tasks[task_id] = _LineTask(
                label=label,
                total=total,
                started=now,
                last_update=now,
            )
            size = human_size(total) if total is not None else "tamaño desconocido"
            with _OUTPUT_LOCK:
                self.console.print(f"[dim]Descargando {escape(label)} ({size})...[/]")
            return task_id

    def update_task(self, task_id: int, downloaded: int, total: int | None) -> None:
        if not self.enabled or task_id < 0:
            return
        if self._progress is not None:
            with self._lock:
                self._progress.update(task_id, completed=downloaded, total=total)
            return
        with self._lock:
            state = self._line_tasks.get(task_id)
            if state is None:
                return
            state.downloaded = downloaded
            if total is not None:
                state.total = total
            now = time.monotonic()
            if now - state.last_update < 1.0:
                return
            state.last_update = now
            elapsed = max(now - state.started, 0.001)
            speed = downloaded / elapsed
            with _OUTPUT_LOCK:
                self.console.print(self._line_update(state, speed))

    def finish_task(self, task_id: int, path: Path, size: int) -> None:
        if not self.enabled or task_id < 0:
            return
        if self._progress is not None:
            with self._lock:
                if task_id in self._progress.task_ids:
                    self._progress.remove_task(task_id)
            return
        with self._lock:
            self._line_tasks.pop(task_id, None)

    def fail_task(self, task_id: int, message: str) -> None:
        if not self.enabled or task_id < 0:
            return
        if self._progress is not None:
            with self._lock:
                if task_id in self._progress.task_ids:
                    self._progress.remove_task(task_id)
            return
        with self._lock:
            self._line_tasks.pop(task_id, None)

    # ------------------------------------------------------------ formato
    def _line_update(self, state: _LineTask, speed: float) -> str:
        downloaded = human_size(state.downloaded)
        if state.total:
            total = human_size(state.total)
            percent = min(100, int(state.downloaded * 100 / state.total))
            progress = f"{downloaded}/{total} ({percent}%)"
        else:
            progress = f"{downloaded}/?"
        return (
            f"[dim]  {escape(state.label)}: {progress} · "
            f"{human_size(int(speed))}/s[/]"
        )


def courses_table(courses: Sequence[Course]) -> Table:
    table = Table(title="Cursos", header_style="bold cyan", show_lines=False)
    table.add_column("ID", style="dim")
    table.add_column("Nombre")
    table.add_column("Sección")
    table.add_column("Estado")
    table.add_column("Rol")
    for course in courses:
        role = {"student": "alumno", "teacher": "profesor", "all": "alumno/profesor"}.get(
            course.role, course.role
        )
        table.add_row(
            course.id,
            course.name,
            course.section or "-",
            course.state or "-",
            role,
        )
    return table


def items_table(items: Sequence[Item]) -> Table:
    table = Table(title="Contenidos", header_style="bold cyan")
    table.add_column("Tipo", style="cyan")
    table.add_column("Fecha", style="dim")
    table.add_column("Título")
    table.add_column("Archivos", justify="right")
    table.add_column("Enlaces", justify="right")
    for item in items:
        table.add_row(
            KIND_LABELS.get(item.kind, item.kind),
            item.date.strftime("%Y-%m-%d") if item.date else "-",
            item.title,
            str(len(item.files)),
            str(len(item.links)),
        )
    return table


def results_table(results: Iterable[SyncResult]) -> Table:
    table = Table(title="Resumen", header_style="bold cyan")
    table.add_column("Curso")
    table.add_column("Contenidos", justify="right")
    table.add_column("Nuevos", justify="right", style="green")
    table.add_column("Actualizados", justify="right")
    table.add_column("Omitidos", justify="right", style="dim")
    table.add_column("Enlaces", justify="right")
    table.add_column("Errores", justify="right", style="red")
    for result in results:
        table.add_row(
            result.course_name,
            str(result.items),
            str(result.downloaded),
            str(result.updated),
            str(result.skipped),
            str(result.links),
            str(len(result.errors)),
        )
    return table


def _require_tty() -> None:
    if not sys.stdin.isatty():
        raise ClassroomDLError(
            "El modo interactivo necesita una terminal.\n"
            "Usa --all o --course ID para ejecutarlo desde un script o cron."
        )


def pick_courses(courses: Sequence[Course], *, single: bool = False):
    """Selección de cursos con flechas/espacio. Devuelve lista de IDs (o uno)."""
    _require_tty()
    if not courses:
        raise ClassroomDLError("No hay cursos disponibles para este usuario.")

    choices = [
        questionary.Choice(
            title=f"{c.name}" + (f" — {c.section}" if c.section else "") + f"  [id {c.id}]",
            value=c.id,
        )
        for c in courses
    ]

    try:
        if single:
            answer = questionary.select(
                "Elige un curso:", choices=choices, instruction="(↑/↓ y Enter)"
            ).ask()
            return answer

        console = Console()
        console.print(
            "[dim]Para marcar un curso pulsa [bold]ESPACIO[/]; "
            "[bold]Enter[/] solo confirma la selección.[/]"
        )
        while True:
            answer = questionary.checkbox(
                "Elige los cursos:",
                choices=choices,
                instruction="(↑/↓ mover · ESPACIO marcar · Enter confirmar)",
            ).ask()
            if answer is None:
                raise ClassroomDLError("Selección cancelada.")
            if answer:
                return answer
            console.print(
                "[yellow]No marcaste ningún curso.[/] Pulsa [bold]ESPACIO[/] "
                "sobre el curso que quieras y luego [bold]Enter[/]."
            )
    except KeyboardInterrupt:
        raise ClassroomDLError("Selección cancelada.") from None
