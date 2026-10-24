"""Presentación en terminal: tablas, mensajes y selección interactiva."""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence

import questionary
from rich.console import Console
from rich.table import Table

from .api import KIND_LABELS, Course, Item
from .errors import ClassroomDLError
from .sync import SyncResult


class RichReporter:
    """Implementa el protocolo Reporter de sync con rich."""

    def __init__(self, console: Console, *, verbose: bool = False) -> None:
        self.console = console
        self.verbose = verbose

    def info(self, message: str) -> None:
        self.console.print(f"[dim]{message}[/]")

    def ok(self, message: str) -> None:
        self.console.print(f"[green]↓[/] {message}")

    def skip(self, message: str) -> None:
        if self.verbose:
            self.console.print(f"[dim]· {message}[/]")

    def warn(self, message: str) -> None:
        self.console.print(f"[yellow]![/] {message}")

    def error(self, message: str) -> None:
        self.console.print(f"[red]✗[/] {message}")


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
