"""Interfaz de línea de comandos de classroom-dl."""

from __future__ import annotations

import datetime as dt
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import NoReturn

import typer
from googleapiclient.errors import HttpError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .api import ClassroomClient, Course, parse_kinds
from .auth import SCOPES, credentials_path, describe_token, load_credentials
from .config import DOCS_FORMATS, SHEETS_FORMATS, Config, config_dir, state_dir
from .drive import DriveDownloader
from .errors import AuthError, ClassroomDLError
from .state import Manifest, list_manifests
from .sync import SyncOptions, SyncResult, sync_course
from .ui import (
    RichDownloadProgress,
    RichReporter,
    courses_table,
    items_table,
    pick_courses,
    results_table,
)

app = typer.Typer(
    name="classroom-dl",
    help="Descarga materiales, tareas y entregas de Google Classroom.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()
err_console = Console(stderr=True)


# --------------------------------------------------------------------- soporte


def _fail(message: str, code: int = 1) -> NoReturn:
    err_console.print(f"[red]Error:[/] {message}")
    raise typer.Exit(code)


def _connect(config: Config) -> tuple[object, ClassroomClient]:
    """Autentica (si hace falta) y devuelve credenciales + cliente de Classroom."""
    try:
        credentials = load_credentials(config.credentials, config.resolve_token())
    except AuthError as exc:
        _fail(str(exc))
    try:
        return credentials, ClassroomClient(credentials)  # type: ignore[arg-type]
    except Exception as exc:  # noqa: BLE001
        _fail(f"No pude inicializar el cliente de Classroom: {exc}")


def _parse_since(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise typer.BadParameter("Usa el formato AAAA-MM-DD, por ejemplo 2026-01-31") from None


def _validate_formats(docs: str | None, sheets: str | None) -> None:
    if docs is not None and docs not in DOCS_FORMATS:
        raise typer.BadParameter(f"--docs-format debe ser uno de: {', '.join(DOCS_FORMATS)}")
    if sheets is not None and sheets not in SHEETS_FORMATS:
        raise typer.BadParameter(f"--sheets-format debe ser uno de: {', '.join(SHEETS_FORMATS)}")


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"classroom-dl {__version__}")
        raise typer.Exit()


@app.callback()
def root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Muestra la versión.",
    ),
    credentials: Path | None = typer.Option(
        None, "--credentials", help="Ruta a client_secret.json."
    ),
    token: Path | None = typer.Option(None, "--token", help="Ruta al token OAuth guardado."),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Carpeta destino de las descargas."
    ),
    docs_format: str | None = typer.Option(
        None, "--docs-format", help="Formato de exportación de Google Docs."
    ),
    sheets_format: str | None = typer.Option(
        None, "--sheets-format", help="Formato de exportación de Google Sheets."
    ),
    jobs: int | None = typer.Option(
        None, "--jobs", "-j", min=1, max=8, help="Descargas en paralelo (1-8)."
    ),
) -> None:
    """Opciones globales; también se pueden guardar con `classroom-dl config`."""
    _validate_formats(docs_format, sheets_format)
    config = Config.load()
    if credentials is not None:
        config.credentials = credentials.expanduser()
    if token is not None:
        config.token = token.expanduser()
    if output is not None:
        config.output_dir = output.expanduser()
    if docs_format is not None:
        config.docs_format = docs_format
    if sheets_format is not None:
        config.sheets_format = sheets_format
    if jobs is not None:
        config.jobs = jobs
    ctx.obj = config


# ---------------------------------------------------------------------- auth


@app.command()
def auth(
    ctx: typer.Context,
    force: bool = typer.Option(
        False, "--force", "-f", help="Ignora el token guardado y vuelve a autorizar."
    ),
) -> None:
    """Autoriza la app con tu cuenta de Google (abre el navegador)."""
    config: Config = ctx.obj
    token_file = config.resolve_token()
    if token_file.exists() and not force:
        console.print(
            f"[dim]Usando el token existente:[/] {token_file}\n"
            "[dim]Si falla o quieres cambiar de cuenta usa[/] [bold]classroom-dl auth --force[/]"
        )
    try:
        credentials = load_credentials(config.credentials, token_file, force=force)
        client = ClassroomClient(credentials)
        courses = client.courses(role="student", include_archived=True)
    except AuthError as exc:
        _fail(str(exc), code=2)
    except Exception as exc:  # noqa: BLE001
        _fail(f"La autorización no quedó operativa: {exc}", code=2)

    console.print(f"[green]✔ Autorizado.[/] Token guardado en [bold]{token_file}[/]")
    console.print(f"Scopes solicitados: {len(SCOPES)} (solo lectura)")
    console.print(f"Cursos visibles como alumno: [bold]{len(courses)}[/]")


# -------------------------------------------------------------------- cursos


@app.command()
def courses(
    ctx: typer.Context,
    teacher: bool = typer.Option(
        False, "--teacher", "-t", help="Incluye también los cursos donde eres profesor."
    ),
    include_archived: bool = typer.Option(
        False, "--include-archived", help="Muestra cursos archivados."
    ),
    as_json: bool = typer.Option(False, "--json", help="Salida JSON para scripts."),
) -> None:
    """Lista los cursos del usuario."""
    config: Config = ctx.obj
    _, client = _connect(config)
    role = "all" if teacher else "student"
    try:
        found = client.courses(role=role, include_archived=include_archived)
    except HttpError as exc:
        _fail(f"Google rechazó la petición: {exc}")
    except ClassroomDLError as exc:
        _fail(str(exc))

    if as_json:
        typer.echo(json.dumps([asdict(course) for course in found], ensure_ascii=False, indent=2))
        return
    if not found:
        console.print("[yellow]No hay cursos para mostrar.[/]")
        return
    console.print(courses_table(found))


# ------------------------------------------------------------------ contenidos


@app.command("list")
def list_items(
    ctx: typer.Context,
    course: str | None = typer.Argument(None, help="ID del curso (si se omite, se elige)."),
    only: str = typer.Option(
        "all", "--only", help="materials,announcements,coursework,submissions o all."
    ),
    since: str | None = typer.Option(None, "--since", help="Desde AAAA-MM-DD."),
    teacher: bool = typer.Option(False, "--teacher", "-t", help="Incluye cursos como profesor."),
) -> None:
    """Muestra los contenidos de un curso sin descargar nada."""
    config: Config = ctx.obj
    _, client = _connect(config)
    try:
        kinds = parse_kinds(only)
        course_id = course
        if not course_id:
            found = client.courses(role="all" if teacher else "student")
            course_id = pick_courses(found, single=True)
        selected = client.get_course(course_id)
        items = list(client.items(selected.id, kinds, since=_parse_since(since)))
    except ClassroomDLError as exc:
        _fail(str(exc))
    except HttpError as exc:
        _fail(f"Google rechazó la petición: {exc}")

    if not items:
        console.print("[yellow]Ese curso no tiene contenidos de los tipos pedidos.[/]")
        return
    console.print(
        f"[bold]{selected.name}[/]"
        + (f" — {selected.section}" if selected.section else "")
    )
    console.print(items_table(items))
    total_files = sum(len(item.files) for item in items)
    total_links = sum(len(item.links) for item in items)
    console.print(f"[dim]{len(items)} contenidos, {total_files} archivos, {total_links} enlaces[/]")


# ---------------------------------------------------------------------- sync


@app.command()
def sync(
    ctx: typer.Context,
    course: list[str] = typer.Option(
        None, "--course", "-c", help="ID de curso a sincronizar (repetible)."
    ),
    all_courses: bool = typer.Option(
        False, "--all", "-a", help="Sincroniza todos los cursos (sin menú interactivo)."
    ),
    teacher: bool = typer.Option(False, "--teacher", "-t", help="Incluye cursos como profesor."),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Muestra qué haría sin descargar ni escribir."
    ),
    refresh: bool = typer.Option(
        False, "--refresh", help="Revisa si los archivos ya descargados cambiaron en Drive."
    ),
    only: str = typer.Option(
        "all", "--only", help="materials,announcements,coursework,submissions o all."
    ),
    since: str | None = typer.Option(None, "--since", help="Solo contenidos desde AAAA-MM-DD."),
    no_links: bool = typer.Option(False, "--no-links", help="No guarda enlaces como .url."),
    prune: bool = typer.Option(
        False, "--prune", help="Olvida del manifest los archivos que ya no están en disco."
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Muestra el progreso de cada descarga (tamaño, velocidad y tiempo) y los omitidos.",
    ),
) -> None:
    """Descarga los contenidos de uno o varios cursos."""
    config: Config = ctx.obj
    try:
        kinds = parse_kinds(only)
        since_date = _parse_since(since)
    except ClassroomDLError as exc:
        _fail(str(exc))

    credentials, client = _connect(config)
    downloader = DriveDownloader(credentials)  # type: ignore[arg-type]
    reporter = RichReporter(console, verbose=verbose)
    progress = RichDownloadProgress(console) if verbose else None

    try:
        available = client.courses(role="all" if teacher else "student")
    except HttpError as exc:
        _fail(f"Google rechazó la petición: {exc}")
    except ClassroomDLError as exc:
        _fail(str(exc))

    try:
        selected: list[Course]
        if course:
            selected = [client.get_course(course_id) for course_id in course]
        elif all_courses:
            selected = available
        else:
            ids = set(pick_courses(available))
            selected = [c for c in available if c.id in ids]
    except ClassroomDLError as exc:
        _fail(str(exc))

    if not selected:
        console.print("[yellow]No hay cursos seleccionados.[/]")
        raise typer.Exit(0)

    output_root: Path = config.output_dir.expanduser()
    if not dry_run:
        output_root.mkdir(parents=True, exist_ok=True)

    options = SyncOptions(
        kinds=kinds,
        dry_run=dry_run,
        refresh=refresh,
        since=since_date,
        docs_format=config.docs_format,
        sheets_format=config.sheets_format,
        jobs=config.jobs,
        links=not no_links,
        prune=prune,
    )

    results: list[SyncResult] = []
    failures = 0
    console.print(
        f"[bold]Destino:[/] {output_root}"
        + ("  [yellow](dry-run, no se escribe nada)[/]" if dry_run else "")
    )
    console.print(f"[bold]Cursos:[/] {len(selected)} · [bold]Tipos:[/] {', '.join(kinds)}")

    try:
        for selected_course in selected:
            console.print(
                f"\n[bold cyan]{selected_course.name}[/]"
                + (f" — {selected_course.section}" if selected_course.section else "")
                + f" [dim]({selected_course.id})[/]"
            )
            manifest = Manifest.for_course(selected_course.id, selected_course.name)
            try:
                result = sync_course(
                    fetcher=client,
                    downloader=downloader,
                    course_id=selected_course.id,
                    course_name=selected_course.name,
                    output_root=output_root,
                    manifest=manifest,
                    options=options,
                    reporter=reporter,
                    progress=progress,
                )
            except KeyboardInterrupt:
                raise
            except (ClassroomDLError, HttpError, OSError) as exc:
                failures += 1
                reporter.error(f"Curso {selected_course.name}: {exc}")
                continue
            results.append(result)
            console.print(f"[green]✔[/] {result.summary()}")
            if result.errors:
                failures += 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrumpido por el usuario.[/] Lo descargado quedó guardado.")
        raise typer.Exit(130) from None

    if results:
        console.print()
        console.print(results_table(results))
    if failures or any(not result.ok for result in results):
        _fail("Terminó con errores. Revisa los mensajes de arriba.", code=1)


# -------------------------------------------------------------------- estado


@app.command()
def status(ctx: typer.Context) -> None:
    """Muestra configuración, token y cursos ya sincronizados."""
    config: Config = ctx.obj
    token_info = describe_token(config.resolve_token())

    table = Table(title="classroom-dl", header_style="bold cyan", show_header=False)
    table.add_column("Clave", style="dim")
    table.add_column("Valor")
    table.add_row("Versión", __version__)
    table.add_row("Configuración", str(config_dir() / "config.json"))
    table.add_row("Estado", str(state_dir()))
    table.add_row("Destino", str(config.output_dir))
    table.add_row("Google Docs", config.docs_format)
    table.add_row("Google Sheets", config.sheets_format)
    table.add_row("Descargas en paralelo", str(config.jobs))
    if token_info.get("exists"):
        table.add_row("Token", f"{token_info['path']} [green](presente)[/]")
    else:
        table.add_row("Token", "[yellow]no autorizado (ejecuta: classroom-dl auth)[/]")
    console.print(table)

    manifests = list_manifests()
    if not manifests:
        console.print("\n[dim]Todavía no has sincronizado ningún curso.[/]")
        return

    manifests_table = Table(
        title="Cursos sincronizados", header_style="bold cyan", show_lines=False
    )
    manifests_table.add_column("Curso")
    manifests_table.add_column("Archivos", justify="right")
    manifests_table.add_column("En disco", justify="right")
    manifests_table.add_column("Tamaño", justify="right")
    manifests_table.add_column("Última sync")
    for manifest in manifests:
        total, present, size = manifest.stats(config.output_dir)
        manifests_table.add_row(
            manifest.course_name or manifest.course_id,
            str(total),
            str(present),
            _fmt_size(size),
            manifest.last_sync or "-",
        )
    console.print()
    console.print(manifests_table)


# --------------------------------------------------------------- configuración


@app.command("config")
def config_cmd(
    ctx: typer.Context,
    output: Path | None = typer.Option(None, "--output", "-o", help="Carpeta destino."),
    docs_format: str | None = typer.Option(None, "--docs-format"),
    sheets_format: str | None = typer.Option(None, "--sheets-format"),
    jobs: int | None = typer.Option(None, "--jobs", "-j", min=1, max=8),
) -> None:
    """Muestra o cambia la configuración guardada."""
    _validate_formats(docs_format, sheets_format)
    config: Config = ctx.obj
    changed = False
    if output is not None:
        config.output_dir = output.expanduser()
        changed = True
    if docs_format is not None:
        config.docs_format = docs_format
        changed = True
    if sheets_format is not None:
        config.sheets_format = sheets_format
        changed = True
    if jobs is not None:
        config.jobs = jobs
        changed = True

    if changed:
        config.save()
        console.print("[green]✔ Configuración guardada.[/]")

    table = Table(header_style="bold cyan", show_header=False)
    table.add_column("Clave", style="dim")
    table.add_column("Valor")
    table.add_row("output_dir", str(config.output_dir))
    table.add_row("docs_format", config.docs_format)
    table.add_row("sheets_format", config.sheets_format)
    table.add_row("jobs", str(config.jobs))
    table.add_row("client_secret.json", str(credentials_path_safe(config)))
    table.add_row("token.json", str(config.resolve_token()))
    console.print(table)


def credentials_path_safe(config: Config) -> str:
    try:
        return str(credentials_path(config.credentials))
    except ClassroomDLError:
        return "no encontrado (ver README)"


# --------------------------------------------------------------------- ayuda


@app.command()
def guide() -> None:
    """Pasos para configurar Google Cloud (credenciales OAuth)."""
    text = Text()
    text.append("1. ", style="bold cyan")
    text.append("Entra a https://console.cloud.google.com y crea un proyecto.\n\n")
    text.append("2. ", style="bold cyan")
    text.append("APIs y servicios → Biblioteca → habilita:\n")
    text.append("   • Google Classroom API\n   • Google Drive API\n\n")
    text.append("3. ", style="bold cyan")
    text.append("Pantalla de consentimiento OAuth:\n")
    text.append("   • Tipo de usuario: External\n")
    text.append("   • Modo de publicación: Testing\n")
    text.append("   • Usuarios de prueba: agrega tu correo de Google\n\n")
    text.append("4. ", style="bold cyan")
    text.append("Credenciales → Crear credenciales → ID de cliente OAuth:\n")
    text.append("   • Tipo: Aplicación de escritorio\n")
    text.append("   • Descarga el JSON y guárdalo como:\n")
    text.append(f"     {config_dir() / 'client_secret.json'}\n\n")
    text.append("5. ", style="bold cyan")
    text.append("Ejecuta: classroom-dl auth\n\n")
    text.append("Nota: ", style="bold yellow")
    text.append(
        "en modo Testing el token caduca a los 7 días; vuelve a ejecutar "
        "`classroom-dl auth --force` cuando pase."
    )
    console.print(Panel(text, title="Configurar Google Cloud", border_style="cyan"))


@app.command()
def version() -> None:
    """Muestra la versión instalada."""
    console.print(f"classroom-dl {__version__}")


# ---------------------------------------------------------------------- main


def _fmt_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelado.[/]")
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
