"""Aviso de nuevas versiones publicadas en GitHub.

La comprobación es opcional, silenciosa y con caché: nunca interrumpe un
comando ni rompe la salida si no hay internet. Se puede desactivar con
``--no-update-check`` o con la variable ``CLASSROOM_DL_NO_UPDATE_CHECK=1``.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .config import _atomic_write_text, state_dir

REPO = "MarcosNpm/Classroom-Downloader"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
RAW_PYPROJECT = f"https://raw.githubusercontent.com/{REPO}/HEAD/pyproject.toml"

ENV_DISABLE = "CLASSROOM_DL_NO_UPDATE_CHECK"
CACHE_TTL = 24 * 60 * 60
FAILED_TTL = 6 * 60 * 60
REQUEST_TIMEOUT = 1.5


@dataclass(frozen=True)
class UpdateInfo:
    current: str
    latest: str
    url: str


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = re.search(r"\d+(?:\.\d+){0,2}", value)
    if not match:
        return (0, 0, 0)
    parts = [int(part) for part in match.group().split(".")]
    parts += [0] * (3 - len(parts))
    return (parts[0], parts[1], parts[2])


def is_newer(latest: str, current: str) -> bool:
    """Compara versiones simples tipo ``1.2.3`` (ignora sufijos como -beta)."""
    return _version_tuple(latest) > _version_tuple(current)


def _http_get(url: str, timeout: float) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"classroom-dl/{__version__}",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def _fetch_latest(timeout: float) -> tuple[str, str] | None:
    """Devuelve la versión más alta entre la última release y el pyproject remoto."""
    candidates: list[tuple[str, str]] = []

    try:
        payload = json.loads(_http_get(RELEASES_API, timeout))
        tag = str(payload.get("tag_name") or payload.get("name") or "").strip()
        url = str(payload.get("html_url") or RELEASES_PAGE)
        if tag:
            candidates.append((tag.lstrip("vV"), url))
    except Exception:  # noqa: BLE001 - el aviso nunca debe romper el comando
        pass

    try:
        text = _http_get(RAW_PYPROJECT, timeout)
    except Exception:  # noqa: BLE001
        text = ""
    match = re.search(r'(?m)^\s*version\s*=\s*"([^"]+)"', text)
    if match:
        candidates.append((match.group(1), RELEASES_PAGE))

    if not candidates:
        return None
    return max(candidates, key=lambda candidate: _version_tuple(candidate[0]))


def _cache_path() -> Path:
    return state_dir() / "update-check.json"


def _read_cache(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache(path: Path, latest: str | None, now: float) -> None:
    payload = {"checked_at": now, "latest": latest}
    try:
        _atomic_write_text(path, json.dumps(payload), mode=0o600)
    except OSError:
        pass


def check_for_update(
    current: str | None = None,
    *,
    cache_path: Path | None = None,
    timeout: float = REQUEST_TIMEOUT,
    now: float | None = None,
) -> UpdateInfo | None:
    """Devuelve información de una versión nueva, o ``None``.

    Usa una caché de 24 horas (6 si la última consulta falló) para no
    consultar GitHub en cada ejecución.
    """
    if os.environ.get(ENV_DISABLE):
        return None

    current = current or __version__
    now = time.time() if now is None else now
    path = cache_path or _cache_path()
    cached = _read_cache(path)
    checked_at = cached.get("checked_at")
    latest = cached.get("latest")

    ttl = CACHE_TTL if latest else FAILED_TTL
    if isinstance(checked_at, (int, float)) and now - checked_at < ttl:
        if isinstance(latest, str) and is_newer(latest, current):
            return UpdateInfo(current=current, latest=latest, url=RELEASES_PAGE)
        return None

    found = _fetch_latest(timeout)
    if found is None:
        _write_cache(path, None, now)
        return None

    latest, url = found
    _write_cache(path, latest, now)
    if is_newer(latest, current):
        return UpdateInfo(current=current, latest=latest, url=url)
    return None
