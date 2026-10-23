"""Excepciones propias de la aplicación."""

from __future__ import annotations


class ClassroomDLError(Exception):
    """Error controlado: se muestra al usuario sin traceback."""


class AuthError(ClassroomDLError):
    """Problema de credenciales, consentimiento o token caducado."""


class ApiError(ClassroomDLError):
    """Error al hablar con las APIs de Google."""


class DownloadError(ClassroomDLError):
    """No se pudo descargar un archivo concreto."""
