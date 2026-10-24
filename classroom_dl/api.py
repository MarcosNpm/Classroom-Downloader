"""Cliente de Google Classroom: cursos, materiales, anuncios, tareas y entregas."""

from __future__ import annotations

import datetime as dt
import random
import re
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from .errors import ApiError

ALL_KINDS = ("materials", "announcements", "coursework", "submissions")

KIND_LABELS = {
    "materials": "Materiales",
    "announcements": "Anuncios",
    "coursework": "Tareas",
    "submissions": "Mis entregas",
}

KIND_ALIASES = {
    "all": ALL_KINDS,
    "todo": ALL_KINDS,
    "todos": ALL_KINDS,
    "materials": ("materials",),
    "materiales": ("materials",),
    "material": ("materials",),
    "announcements": ("announcements",),
    "anuncios": ("announcements",),
    "anuncio": ("announcements",),
    "coursework": ("coursework",),
    "tareas": ("coursework",),
    "tarea": ("coursework",),
    "submissions": ("submissions",),
    "entregas": ("submissions",),
    "entrega": ("submissions",),
}

COURSE_ITEM_FIELDS = "id,name,section,courseState,room,ownerId,alternateLink"
COURSE_FIELDS = f"nextPageToken,courses({COURSE_ITEM_FIELDS})"
MATERIAL_FIELDS = (
    "nextPageToken,courseWorkMaterial("
    "id,title,description,state,creationTime,updateTime,materials,topicId,alternateLink)"
)
ANNOUNCEMENT_FIELDS = (
    "nextPageToken,announcements("
    "id,text,state,creationTime,updateTime,materials,alternateLink)"
)
COURSEWORK_FIELDS = (
    "nextPageToken,courseWork("
    "id,title,description,state,creationTime,updateTime,dueDate,dueTime,"
    "materials,topicId,alternateLink,maxPoints)"
)
SUBMISSION_FIELDS = (
    "nextPageToken,studentSubmissions("
    "id,courseWorkId,state,updateTime,assignedGrade,draftGrade,"
    "assignmentSubmission(attachments))"
)

_RETRY_STATUS = {429, 500, 502, 503, 504}
_RATE_LIMIT_MARKERS = (
    "ratelimitexceeded",
    "userratelimitexceeded",
    "quotaexceeded",
    "backenderror",
)

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", re.IGNORECASE)
_HTML_LINK_RE = re.compile(
    r"<a\s+[^>]*href=[\"'](https?://[^\"']+)[\"'][^>]*>(.*?)</a>",
    re.IGNORECASE | re.DOTALL,
)
_DRIVE_ID_PATTERNS = (
    re.compile(r"drive\.google\.com/file/d/([A-Za-z0-9_-]+)"),
    re.compile(r"drive\.google\.com/(?:open|uc)\?(?:[^#]*&)?id=([A-Za-z0-9_-]+)"),
    re.compile(
        r"docs\.google\.com/(?:document|spreadsheets|presentation|drawings)/d/"
        r"([A-Za-z0-9_-]+)"
    ),
)


@dataclass(frozen=True)
class Course:
    id: str
    name: str
    section: str | None = None
    state: str | None = None
    room: str | None = None
    role: str = "student"


@dataclass(frozen=True)
class DriveAttachment:
    file_id: str
    title: str
    mime_type: str = ""
    url: str | None = None


@dataclass(frozen=True)
class LinkAttachment:
    title: str
    url: str


@dataclass(frozen=True)
class Item:
    """Una unidad descargable: material, anuncio, tarea o entrega."""

    kind: str
    item_id: str
    title: str
    date: dt.date | None = None
    description: str = ""
    files: tuple[DriveAttachment, ...] = field(default_factory=tuple)
    links: tuple[LinkAttachment, ...] = field(default_factory=tuple)
    state: str | None = None


# --------------------------------------------------------------------- utilidades


def parse_kinds(value: str | None) -> tuple[str, ...]:
    """Convierte 'materiales,tareas' en ('materials', 'coursework')."""
    if not value:
        return ALL_KINDS
    result: list[str] = []
    for token in value.replace(";", ",").split(","):
        key = token.strip().lower()
        if not key:
            continue
        if key not in KIND_ALIASES:
            valid = ", ".join(sorted(KIND_ALIASES))
            raise ApiError(f"Tipo desconocido: {token!r}. Valores válidos: {valid}")
        for kind in KIND_ALIASES[key]:
            if kind not in result:
                result.append(kind)
    return tuple(result) if result else ALL_KINDS


def execute_with_retry(
    request: Any,
    *,
    attempts: int = 6,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Ejecuta una petición de Google con backoff exponencial y jitter."""
    last_error: HttpError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return request.execute()
        except HttpError as exc:
            last_error = exc
            status = getattr(exc.resp, "status", None)
            retriable = status in _RETRY_STATUS or (status == 403 and _is_rate_limit(exc))
            if not retriable or attempt == attempts:
                raise
            delay = _retry_after(exc) or min(max_delay, base_delay * 2 ** (attempt - 1))
            sleep(delay + random.uniform(0, 0.5))
    assert last_error is not None
    raise last_error


def _is_rate_limit(exc: HttpError) -> bool:
    content = getattr(exc, "content", b"") or b""
    text = content.decode("utf-8", "ignore").lower()
    return any(marker in text for marker in _RATE_LIMIT_MARKERS)


def _retry_after(exc: HttpError) -> float | None:
    try:
        value = exc.resp.get("retry-after")
    except AttributeError:
        return None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def _paginate(
    request_factory: Callable[[str | None], Any],
    items_key: str,
    *,
    limit: int | None = None,
) -> Iterator[dict]:
    page_token: str | None = None
    seen = 0
    while True:
        response = execute_with_retry(request_factory(page_token))
        for raw in response.get(items_key, []) or []:
            if isinstance(raw, dict):
                yield raw
                seen += 1
                if limit is not None and seen >= limit:
                    return
        page_token = response.get("nextPageToken")
        if not page_token:
            return


def _parse_date(*values: str | None) -> dt.date | None:
    for value in values:
        if not value:
            continue
        text = value.replace("Z", "+00:00")
        try:
            parsed = dt.datetime.fromisoformat(text)
        except ValueError:
            continue
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(dt.timezone.utc)
        return parsed.date()
    return None


def _drive_file_payload(material: dict) -> dict | None:
    """Devuelve el objeto con id/título de un adjunto de Drive.

    La API actual anida el archivo en ``driveFile.driveFile`` (con ``shareMode``
    al lado). Las entregas siguen usando ``driveFile`` plano.
    """
    drive = material.get("driveFile")
    if not isinstance(drive, dict):
        return None
    inner = drive.get("driveFile")
    if isinstance(inner, dict):
        return inner
    return drive


def _parse_materials(
    materials: Iterable[dict] | None,
) -> tuple[tuple[DriveAttachment, ...], tuple[LinkAttachment, ...]]:
    files: list[DriveAttachment] = []
    links: list[LinkAttachment] = []
    for material in materials or []:
        if not isinstance(material, dict):
            continue
        drive = _drive_file_payload(material)
        if isinstance(drive, dict) and drive.get("id"):
            files.append(
                DriveAttachment(
                    file_id=str(drive["id"]),
                    title=str(drive.get("title") or drive["id"]),
                    mime_type=str(drive.get("mimeType") or ""),
                    url=drive.get("alternateLink"),
                )
            )
        video = material.get("youTubeVideo")
        if isinstance(video, dict):
            url = video.get("alternateLink")
            if url:
                links.append(
                    LinkAttachment(
                        title=str(video.get("title") or "Video de YouTube"), url=url
                    )
                )
        link = material.get("link")
        if isinstance(link, dict) and link.get("url"):
            links.append(
                LinkAttachment(title=str(link.get("title") or "Enlace"), url=str(link["url"]))
            )
        form = material.get("form")
        if isinstance(form, dict) and form.get("formUrl"):
            links.append(
                LinkAttachment(
                    title=str(form.get("title") or "Formulario"), url=str(form["formUrl"])
                )
            )
    return tuple(files), tuple(links)


def _clean_url(url: str) -> str:
    """Quita comillas y puntuación que suele quedar pegada al copiar una URL."""
    cleaned = url.strip().strip("<>\"'")
    while cleaned and cleaned[-1] in ".,;:!?":
        cleaned = cleaned[:-1]
    for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
        while cleaned.endswith(closing) and cleaned.count(opening) < cleaned.count(closing):
            cleaned = cleaned[:-1]
    return cleaned


def _link_title_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.netloc or "").removeprefix("www.")
    last = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    if last in {"open", "uc"}:
        file_id = parse_qs(parsed.query).get("id", [""])[0]
        if file_id:
            last = file_id[:12]
    if last:
        return f"{host} - {last}" if host else last
    return host or "Enlace"


def _extract_links(text: str) -> tuple[LinkAttachment, ...]:
    """Extrae URLs pegadas en descripciones, anuncios y textos de tareas."""
    if not text:
        return ()

    titles: dict[str, str] = {}
    for match in _MARKDOWN_LINK_RE.finditer(text):
        titles[_clean_url(match.group(2))] = match.group(1).strip()
    for match in _HTML_LINK_RE.finditer(text):
        title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
        titles[_clean_url(match.group(1))] = title

    result: list[LinkAttachment] = []
    seen: set[str] = set()
    for match in _URL_RE.finditer(text):
        url = _clean_url(match.group(0))
        if not url or url in seen or not urlparse(url).netloc:
            continue
        seen.add(url)
        result.append(
            LinkAttachment(title=titles.get(url) or _link_title_from_url(url), url=url)
        )
    return tuple(result)


def _drive_file_id(url: str) -> str | None:
    for pattern in _DRIVE_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def _parse_materials_with_text(
    materials: Iterable[dict] | None,
    text: str | None,
) -> tuple[tuple[DriveAttachment, ...], tuple[LinkAttachment, ...]]:
    """Combina adjuntos y enlaces escritos en el texto del contenido."""
    files, links = _parse_materials(materials)
    if not text:
        return files, links

    attached_ids = {file.file_id for file in files}
    seen = {link.url for link in links}
    extra: list[LinkAttachment] = []
    for link in _extract_links(text):
        if link.url in seen:
            continue
        drive_id = _drive_file_id(link.url)
        if drive_id and drive_id in attached_ids:
            continue
        seen.add(link.url)
        extra.append(link)
    return files, links + tuple(extra)


def _submission_attachments(
    raw: dict,
) -> tuple[tuple[DriveAttachment, ...], tuple[LinkAttachment, ...]]:
    """Los adjuntos de una entrega viven en assignmentSubmission.attachments."""
    submission = raw.get("assignmentSubmission")
    if not isinstance(submission, dict):
        return (), ()
    return _parse_materials(submission.get("attachments"))


def _announcement_title(text: str) -> str:
    for line in (text or "").splitlines():
        cleaned = line.strip()
        if cleaned:
            return cleaned[:100]
    return "Anuncio"


# ----------------------------------------------------------------------- cliente


class ClassroomClient:
    """Envoltorio fino sobre la API v1 de Classroom."""

    def __init__(self, credentials: Credentials) -> None:
        self._credentials = credentials
        self._service = build("classroom", "v1", credentials=credentials, cache_discovery=False)

    # ------------------------------------------------------------------ cursos

    def courses(self, *, role: str = "student", include_archived: bool = False) -> list[Course]:
        """Cursos donde el usuario es alumno, profesor o ambos."""
        if role not in ("student", "teacher", "all"):
            raise ApiError(f"Rol inválido: {role}")

        collected: dict[str, Course] = {}
        roles = ("student", "teacher") if role == "all" else (role,)
        for current in roles:
            key = "studentId" if current == "student" else "teacherId"

            def request_factory(page_token: str | None, key: str = key):
                return self._service.courses().list(
                    pageToken=page_token,
                    pageSize=100,
                    fields=COURSE_FIELDS,
                    **{key: "me"},
                )

            for raw in _paginate(request_factory, "courses"):
                state = raw.get("courseState")
                if not include_archived and state == "ARCHIVED":
                    continue
                course = Course(
                    id=str(raw.get("id", "")),
                    name=str(raw.get("name") or "Curso sin nombre"),
                    section=raw.get("section") or None,
                    state=state,
                    room=raw.get("room") or None,
                    role=current,
                )
                if not course.id:
                    continue
                existing = collected.get(course.id)
                if existing:
                    collected[course.id] = Course(
                        id=existing.id,
                        name=existing.name,
                        section=existing.section,
                        state=existing.state,
                        room=existing.room,
                        role="all",
                    )
                else:
                    collected[course.id] = course
        return sorted(collected.values(), key=lambda c: c.name.casefold())

    def get_course(self, course_id: str) -> Course:
        try:
            raw = execute_with_retry(
                self._service.courses().get(id=course_id, fields=COURSE_ITEM_FIELDS)
            )
        except HttpError as exc:
            raise ApiError(f"No pude leer el curso {course_id}: {_http_message(exc)}") from exc
        return Course(
            id=str(raw.get("id", course_id)),
            name=str(raw.get("name") or course_id),
            section=raw.get("section") or None,
            state=raw.get("courseState"),
            room=raw.get("room") or None,
        )

    # --------------------------------------------------------------- contenidos

    def items(
        self,
        course_id: str,
        kinds: Iterable[str] = ALL_KINDS,
        *,
        since: dt.date | None = None,
    ) -> Iterator[Item]:
        """Itera los contenidos del curso, filtrando opcionalmente por fecha."""
        wanted = set(kinds)

        if "materials" in wanted:
            for item in self._materials(course_id):
                if _date_ok(item.date, since):
                    yield item

        if "announcements" in wanted:
            for item in self._announcements(course_id):
                if _date_ok(item.date, since):
                    yield item

        coursework: list[Item] = []
        if "coursework" in wanted or "submissions" in wanted:
            coursework = list(self._coursework(course_id))

        if "coursework" in wanted:
            for item in coursework:
                if _date_ok(item.date, since):
                    yield item

        if "submissions" in wanted:
            for item in coursework:
                if not _date_ok(item.date, since):
                    continue
                submitted = self._submission_item(course_id, item)
                if submitted is not None:
                    yield submitted

    def _materials(self, course_id: str) -> Iterator[Item]:
        def request_factory(page_token: str | None):
            return (
                self._service.courses()
                .courseWorkMaterials()
                .list(
                    courseId=course_id,
                    pageToken=page_token,
                    pageSize=100,
                    fields=MATERIAL_FIELDS,
                )
            )

        for raw in _paginate(request_factory, "courseWorkMaterial"):
            description = str(raw.get("description") or "")
            files, links = _parse_materials_with_text(raw.get("materials"), description)
            yield Item(
                kind="materials",
                item_id=str(raw.get("id", "")),
                title=str(raw.get("title") or "Material sin título"),
                date=_parse_date(raw.get("creationTime"), raw.get("updateTime")),
                description=description,
                files=files,
                links=links,
                state=raw.get("state"),
            )

    def _announcements(self, course_id: str) -> Iterator[Item]:
        def request_factory(page_token: str | None):
            return (
                self._service.courses()
                .announcements()
                .list(
                    courseId=course_id,
                    pageToken=page_token,
                    pageSize=100,
                    fields=ANNOUNCEMENT_FIELDS,
                )
            )

        for raw in _paginate(request_factory, "announcements"):
            text = str(raw.get("text") or "")
            files, links = _parse_materials_with_text(raw.get("materials"), text)
            yield Item(
                kind="announcements",
                item_id=str(raw.get("id", "")),
                title=_announcement_title(text),
                date=_parse_date(raw.get("creationTime"), raw.get("updateTime")),
                description=text,
                files=files,
                links=links,
                state=raw.get("state"),
            )

    def _coursework(self, course_id: str) -> Iterator[Item]:
        def request_factory(page_token: str | None):
            return (
                self._service.courses()
                .courseWork()
                .list(
                    courseId=course_id,
                    pageToken=page_token,
                    pageSize=100,
                    fields=COURSEWORK_FIELDS,
                )
            )

        for raw in _paginate(request_factory, "courseWork"):
            description = str(raw.get("description") or "")
            files, links = _parse_materials_with_text(raw.get("materials"), description)
            yield Item(
                kind="coursework",
                item_id=str(raw.get("id", "")),
                title=str(raw.get("title") or "Tarea sin título"),
                date=_parse_date(raw.get("creationTime"), raw.get("updateTime")),
                description=description,
                files=files,
                links=links,
                state=raw.get("state"),
            )

    def _submission_item(self, course_id: str, coursework: Item) -> Item | None:
        def request_factory(page_token: str | None):
            return (
                self._service.courses()
                .courseWork()
                .studentSubmissions()
                .list(
                    courseId=course_id,
                    courseWorkId=coursework.item_id,
                    userId="me",
                    pageToken=page_token,
                    pageSize=100,
                    fields=SUBMISSION_FIELDS,
                )
            )
        files: list[DriveAttachment] = []
        links: list[LinkAttachment] = []
        states: list[str] = []
        grades: list[str] = []
        for raw in _paginate(request_factory, "studentSubmissions"):
            state = raw.get("state")
            if state:
                states.append(str(state))
            for key in ("assignedGrade", "draftGrade"):
                if isinstance(raw.get(key), (int, float)):
                    grades.append(f"{key}={raw[key]:g}")
            sub_files, sub_links = _submission_attachments(raw)
            files.extend(sub_files)
            links.extend(sub_links)
        if not files and not links:
            return None
        details = [f"estado={s}" for s in dict.fromkeys(states)]
        details += grades
        return Item(
            kind="submissions",
            item_id=coursework.item_id,
            title=coursework.title,
            date=coursework.date,
            description=", ".join(details),
            files=tuple(files),
            links=tuple(links),
            state=states[0] if states else None,
        )


def _date_ok(item_date: dt.date | None, since: dt.date | None) -> bool:
    if since is None or item_date is None:
        return True
    return item_date >= since


def _http_message(exc: HttpError) -> str:
    status = getattr(exc.resp, "status", "?")
    detail = ""
    content = getattr(exc, "content", b"") or b""
    try:
        import json

        parsed = json.loads(content.decode("utf-8", "ignore"))
        detail = str(parsed.get("error", {}).get("message") or "")
    except (ValueError, AttributeError):
        pass
    return f"HTTP {status}{': ' + detail if detail else ''}"
