"""Configuración persistente y rutas de la aplicación."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from platformdirs import user_config_dir, user_state_dir

from .errors import ClassroomDLError

APP_NAME = "classroom-dl"

DOCS_FORMATS = ("pdf", "docx", "txt", "html")
SHEETS_FORMATS = ("xlsx", "csv", "pdf")
DEFAULT_OUTPUT = Path.home() / "Classroom"

ENV_CREDENTIALS = "CLASSROOM_DL_CREDENTIALS"
ENV_TOKEN = "CLASSROOM_DL_TOKEN"
ENV_OUTPUT = "CLASSROOM_DL_OUTPUT"


def config_dir() -> Path:
    """Carpeta de configuración (credenciales, token, config.json)."""
    path = Path(user_config_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def state_dir() -> Path:
    """Carpeta de estado (manifests de sincronización)."""
    path = Path(user_state_dir(APP_NAME))
    path.mkdir(parents=True, exist_ok=True)
    return path


def manifests_dir() -> Path:
    path = state_dir() / "manifests"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_file() -> Path:
    return config_dir() / "config.json"


def default_credentials_path() -> Path:
    return config_dir() / "client_secret.json"


def default_token_path() -> Path:
    return config_dir() / "token.json"


@dataclass
class Config:
    """Preferencias del usuario, persistidas en config.json."""

    output_dir: Path = field(default_factory=lambda: DEFAULT_OUTPUT)
    docs_format: str = "pdf"
    sheets_format: str = "xlsx"
    jobs: int = 2
    credentials: Path | None = None
    token: Path | None = None

    # ------------------------------------------------------------------ carga

    @classmethod
    def load(cls) -> Config:
        data: dict = {}
        path = config_file()
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = raw
            except (OSError, ValueError):
                data = {}

        config = cls()
        if isinstance(data.get("output_dir"), str) and data["output_dir"].strip():
            config.output_dir = Path(data["output_dir"]).expanduser()
        if data.get("docs_format") in DOCS_FORMATS:
            config.docs_format = data["docs_format"]
        if data.get("sheets_format") in SHEETS_FORMATS:
            config.sheets_format = data["sheets_format"]
        if isinstance(data.get("jobs"), int) and data["jobs"] > 0:
            config.jobs = data["jobs"]
        if isinstance(data.get("credentials"), str) and data["credentials"].strip():
            config.credentials = Path(data["credentials"]).expanduser()
        if isinstance(data.get("token"), str) and data["token"].strip():
            config.token = Path(data["token"]).expanduser()

        # Variables de entorno: prioridad sobre config.json
        env_output = os.environ.get(ENV_OUTPUT)
        if env_output:
            config.output_dir = Path(env_output).expanduser()
        env_creds = os.environ.get(ENV_CREDENTIALS)
        if env_creds:
            config.credentials = Path(env_creds).expanduser()
        env_token = os.environ.get(ENV_TOKEN)
        if env_token:
            config.token = Path(env_token).expanduser()
        return config

    def save(self) -> None:
        payload = {
            "output_dir": str(self.output_dir),
            "docs_format": self.docs_format,
            "sheets_format": self.sheets_format,
            "jobs": self.jobs,
            "credentials": str(self.credentials) if self.credentials else None,
            "token": str(self.token) if self.token else None,
        }
        path = config_file()
        _atomic_write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    # --------------------------------------------------------------- resolución

    def resolve_credentials(self) -> Path:
        """Ruta al client_secret.json, buscando en los sitios habituales."""
        candidates = [
            self.credentials,
            Path.cwd() / "client_secret.json",
            default_credentials_path(),
        ]
        for candidate in candidates:
            if candidate and candidate.expanduser().is_file():
                return candidate.expanduser()
        raise ClassroomDLError(
            "No encuentro client_secret.json.\n"
            f"Guárdalo en {default_credentials_path()} o usa el flag --credentials.\n"
            "Sigue la guía del README para crear las credenciales en Google Cloud."
        )

    def resolve_token(self) -> Path:
        return (self.token or default_token_path()).expanduser()


def _atomic_write_text(path: Path, content: str, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
