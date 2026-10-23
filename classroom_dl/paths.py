"""Construcción de nombres y carpetas seguras para el sistema de archivos."""

from __future__ import annotations

import re
import unicodedata
from datetime import date

# Caracteres inválidos en Linux/Windows/macOS y caracteres de control.
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")

KIND_FOLDERS = {
    "materials": "Materiales",
    "announcements": "Anuncios",
    "coursework": "Tareas",
    "submissions": "Mis entregas",
}

MAX_NAME_LENGTH = 120


def sanitize_name(
    name: str, *, fallback: str = "sin-titulo", max_length: int = MAX_NAME_LENGTH
) -> str:
    """Convierte un título de Classroom en un nombre de archivo/carpeta seguro."""
    text = unicodedata.normalize("NFC", name or "")
    text = _WHITESPACE.sub(" ", text)
    text = _INVALID_CHARS.sub("-", text).strip()
    text = text.strip(". ")
    if not text:
        return fallback

    if len(text) > max_length:
        stem, dot, ext = text.rpartition(".")
        if dot and 0 < len(ext) <= 10 and len(stem) > 0:
            keep = max_length - len(ext) - 1
            text = f"{stem[:keep].rstrip()}.{ext}"
        else:
            text = text[:max_length].rstrip()
    return text or fallback


def course_folder_name(course_name: str, section: str | None = None) -> str:
    section = (section or "").strip()
    raw = f"{course_name} - {section}" if section else course_name
    return sanitize_name(raw, fallback="Curso sin nombre")


def item_folder_name(item_date: date | None, title: str) -> str:
    prefix = item_date.strftime("%Y-%m-%d") if item_date else "sin-fecha"
    return sanitize_name(f"{prefix} - {title}", fallback="Sin titulo")


def unique_name(name: str, used: set[str]) -> str:
    """Añade ' (2)', ' (3)'... hasta que el nombre no esté en `used`.

    Compara en minúsculas porque los sistemas de archivos suelen ser
    insensibles a mayúsculas.
    """
    candidate = name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    counter = 2
    while candidate.casefold() in used:
        suffix = f" ({counter})"
        candidate = f"{stem}{suffix}.{ext}" if ext else f"{stem}{suffix}"
        counter += 1
    used.add(candidate.casefold())
    return candidate
