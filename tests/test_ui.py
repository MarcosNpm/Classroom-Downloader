import io
from pathlib import Path

from rich.console import Console

from classroom_dl import ui
from classroom_dl.api import Course


class FakeQuestion:
    def __init__(self, answers):
        self._answers = iter(answers)

    def ask(self):
        return next(self._answers)


def test_pick_courses_reprompts_when_nothing_is_selected(monkeypatch):
    calls = []
    answers = iter([[], ["curso-1"]])

    def fake_checkbox(*args, **kwargs):
        calls.append(kwargs)
        return FakeQuestion(answers)

    monkeypatch.setattr(ui.questionary, "checkbox", fake_checkbox)
    monkeypatch.setattr(ui, "_require_tty", lambda: None)

    result = ui.pick_courses([Course("curso-1", "Matemáticas para Informática")])

    assert result == ["curso-1"]
    assert len(calls) == 2


def test_reporter_download_verbose_shows_size_and_speed():
    stream = io.StringIO()
    reporter = ui.RichReporter(Console(file=stream, width=100), verbose=True)

    reporter.download("Curso/archivo.pdf", size=1024 * 1024, elapsed=2.0)

    output = stream.getvalue()
    assert "Curso/archivo.pdf" in output
    assert "MB" in output
    assert "/s" in output


def test_reporter_download_without_verbose_keeps_old_output():
    stream = io.StringIO()
    reporter = ui.RichReporter(Console(file=stream, width=100))

    reporter.download("Curso/archivo.pdf", size=1024 * 1024, elapsed=2.0)

    output = stream.getvalue()
    assert "Curso/archivo.pdf" in output
    assert "MB" not in output


def test_progress_line_mode_shows_file_and_speed():
    stream = io.StringIO()
    progress = ui.RichDownloadProgress(Console(file=stream, width=100))

    progress.start_session()
    task_id = progress.add_task("guia.pdf", 1024, dest_dir=Path("2026-03-10 - Guía"))
    progress._line_tasks[task_id].last_update = 0.0
    progress.update_task(task_id, 512, 1024)
    progress.finish_task(task_id, Path("guia.pdf"), 1024)
    progress.stop_session()

    output = stream.getvalue()
    assert "guia.pdf" in output
    assert "2026-03-10 - Guía" in output
    assert "KB" in output


def test_progress_line_mode_handles_unknown_size():
    stream = io.StringIO()
    progress = ui.RichDownloadProgress(Console(file=stream, width=100))

    task_id = progress.add_task("exportacion.pdf", None)
    progress._line_tasks[task_id].last_update = 0.0
    progress.update_task(task_id, 512, None)
    progress.finish_task(task_id, Path("exportacion.pdf"), 512)

    output = stream.getvalue()
    assert "exportacion.pdf" in output
    assert "tamaño desconocido" in output
    assert "?" in output


def test_progress_disabled_writes_nothing():
    stream = io.StringIO()
    progress = ui.RichDownloadProgress(Console(file=stream, width=100), enabled=False)

    task_id = progress.add_task("guia.pdf", 1024)
    progress.update_task(task_id, 512, 1024)
    progress.finish_task(task_id, Path("guia.pdf"), 1024)

    assert stream.getvalue() == ""
