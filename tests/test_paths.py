from datetime import date

import pytest

from classroom_dl.paths import (
    course_folder_name,
    item_folder_name,
    sanitize_name,
    unique_name,
)


def test_sanitize_removes_invalid_characters():
    cleaned = sanitize_name('Tarea 1/2: "repaso" <final>|*?')
    for char in '<>:"/\\|?*':
        assert char not in cleaned
    assert cleaned.startswith("Tarea 1-2")


def test_sanitize_collapses_whitespace_and_dots():
    assert sanitize_name("  hola \n\t mundo ... ") == "hola mundo"
    assert sanitize_name("...") == "sin-titulo"
    assert sanitize_name("") == "sin-titulo"


def test_sanitize_truncates_keeping_extension():
    name = sanitize_name("x" * 200 + ".pdf")
    assert name.endswith(".pdf")
    assert len(name) <= 120


def test_unique_name_adds_counter_case_insensitive():
    used: set[str] = set()
    assert unique_name("guia.pdf", used) == "guia.pdf"
    assert unique_name("guia.pdf", used) == "guia (2).pdf"
    assert unique_name("GUIA.pdf", used) == "GUIA (3).pdf"
    assert unique_name("sin-extension", used) == "sin-extension"
    assert unique_name("sin-extension", used) == "sin-extension (2)"


def test_item_folder_name_uses_date_prefix():
    assert item_folder_name(date(2026, 3, 10), "Guía: recursión") == (
        "2026-03-10 - Guía- recursión"
    )
    assert item_folder_name(None, "Sin fecha") == "sin-fecha - Sin fecha"


def test_course_folder_name_includes_section():
    assert course_folder_name("Programación I", "B") == "Programación I - B"
    assert course_folder_name("Programación I", None) == "Programación I"
    assert course_folder_name("", "") == "Curso sin nombre"


@pytest.mark.parametrize("name", ["a" * 300, "..", "con", "archivo.zip"])
def test_sanitize_never_returns_empty(name):
    assert sanitize_name(name)
