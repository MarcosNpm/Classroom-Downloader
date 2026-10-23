"""Autenticación OAuth2 contra Google (flujo de app de escritorio)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .config import _atomic_write_text, default_credentials_path, default_token_path
from .errors import AuthError

# Solo lectura. Ver README para el detalle de cada scope.
SCOPES = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.me.readonly",
    "https://www.googleapis.com/auth/classroom.courseworkmaterials.readonly",
    "https://www.googleapis.com/auth/classroom.announcements.readonly",
    "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]

EXPIRED_TOKEN_HINT = (
    "El token guardado ya no es válido (en apps en modo 'Testing' Google lo caduca "
    "cada 7 días). Ejecuta: classroom-dl auth --force"
)


def credentials_path(explicit: Path | None = None) -> Path:
    """Devuelve client_secret.json o falla con instrucciones."""
    candidates = [
        explicit,
        Path(os.environ["CLASSROOM_DL_CREDENTIALS"])
        if os.environ.get("CLASSROOM_DL_CREDENTIALS")
        else None,
        Path.cwd() / "client_secret.json",
        default_credentials_path(),
    ]
    for candidate in candidates:
        if candidate and candidate.expanduser().is_file():
            return candidate.expanduser()
    raise AuthError(
        "No encuentro client_secret.json.\n"
        f"Guárdalo en {default_credentials_path()} o pasa --credentials RUTA.\n"
        "La guía completa está en el README (sección 'Configurar Google Cloud')."
    )


def load_credentials(
    client_secret: Path | None = None,
    token_path: Path | None = None,
    *,
    force: bool = False,
    interactive: bool = True,
) -> Credentials:
    """Carga el token, lo refresca o lanza el flujo OAuth del navegador."""
    if force:
        client_secret = credentials_path(client_secret)
    else:
        client_secret = None  # no exigimos el secret si el token aún sirve

    token_file = (token_path or default_token_path()).expanduser()

    creds: Credentials | None = None
    if not force and token_file.is_file():
        try:
            # Sin forzar scopes: así podemos comprobar los que realmente se concedieron.
            creds = Credentials.from_authorized_user_file(str(token_file))
        except (ValueError, OSError):
            creds = None
        if creds is not None and not _has_required_scopes(creds):
            # Token viejo con menos permisos: hay que volver a autorizar.
            creds = None

    if creds is not None and creds.valid:
        return creds

    if creds is not None and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError as exc:
            if not interactive:
                raise AuthError(EXPIRED_TOKEN_HINT) from exc
            creds = None
        else:
            _save_token(creds, token_file)
            return creds

    if not interactive:
        raise AuthError("No hay credenciales válidas. Ejecuta: classroom-dl auth")

    client_secret = credentials_path(client_secret)
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    try:
        creds = flow.run_local_server(
            port=0,
            open_browser=True,
            prompt="consent",
            authorization_prompt_message="Abre este enlace para autorizar classroom-dl:\n{url}",
            success_message="Autorización completada. Ya puedes cerrar esta pestaña.",
        )
    except Warning as exc:
        # oauthlib lanza un Warning si Google concede menos scopes de los pedidos.
        old = list(getattr(exc, "old_scope", []) or SCOPES)
        new = set(getattr(exc, "new_scope", []) or [])
        missing = [scope for scope in old if scope not in new]
        raise AuthError(_scope_change_message(missing)) from exc
    _save_token(creds, token_file)
    return creds


def _scope_change_message(missing: list[str]) -> str:
    detail = "\n".join(f"  • {scope}" for scope in missing) or "  • (desconocido)"
    return (
        "Google autorizó la cuenta, pero no concedió todos los permisos:\n"
        f"{detail}\n\n"
        "Cómo arreglarlo:\n"
        "1. Google Cloud → Google Auth Platform → Acceso a los datos (Data Access).\n"
        "2. Pulsa 'Agregar o quitar permisos' y añade los scopes que faltan.\n"
        "3. Vuelve a ejecutar: classroom-dl auth --force\n"
        "En la pantalla de consentimiento deja TODAS las casillas marcadas."
    )


def _has_required_scopes(creds: Credentials) -> bool:
    granted = set(creds.scopes or [])
    if not granted:
        # Algunos tokens no declaran scopes; no podemos verificar, confiamos.
        return True
    return set(SCOPES).issubset(granted)


def _save_token(creds: Credentials, path: Path) -> None:
    payload = creds.to_json()
    # 0o600: el refresh token es tan sensible como una contraseña.
    _atomic_write_text(path, payload, mode=0o600)


def describe_token(path: Path | None = None) -> dict:
    """Información no sensible del token guardado (para `classroom-dl status`)."""
    token_file = (path or default_token_path()).expanduser()
    if not token_file.is_file():
        return {"path": str(token_file), "exists": False}
    try:
        raw = json.loads(token_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"path": str(token_file), "exists": True, "readable": False}
    return {
        "path": str(token_file),
        "exists": True,
        "readable": True,
        "client_id": raw.get("client_id"),
        "scopes": raw.get("scopes", []),
    }
