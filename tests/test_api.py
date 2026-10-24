from datetime import date

import pytest
from googleapiclient.errors import HttpError

from classroom_dl.api import (
    DriveAttachment,
    Item,
    _announcement_title,
    _extract_links,
    _paginate,
    _parse_date,
    _parse_materials,
    _parse_materials_with_text,
    execute_with_retry,
    parse_kinds,
)
from classroom_dl.errors import ApiError


class FakeResp:
    def __init__(self, status: int, retry_after: str | None = None):
        self.status = status
        self.reason = "error"
        self._retry_after = retry_after

    def get(self, key, default=None):
        if key.lower() == "retry-after" and self._retry_after is not None:
            return self._retry_after
        return default


class FakeRequest:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def execute(self):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def http_error(status: int, message: str = "error", retry_after: str | None = None) -> HttpError:
    content = f'{{"error": {{"message": "{message}"}}}}'.encode()
    return HttpError(FakeResp(status, retry_after), content)


def test_course_fields_use_course_state():
    from classroom_dl.api import COURSE_FIELDS

    assert "courseState" in COURSE_FIELDS
    assert "courses.state" not in COURSE_FIELDS


def test_material_fields_use_singular_resource_name():
    from classroom_dl.api import MATERIAL_FIELDS

    assert "courseWorkMaterial(" in MATERIAL_FIELDS
    assert "courseWorkMaterials(" not in MATERIAL_FIELDS


def test_submission_attachments_reads_nested_object():
    from classroom_dl.api import _submission_attachments

    files, links = _submission_attachments(
        {
            "assignmentSubmission": {
                "attachments": [
                    {"driveFile": {"id": "f1", "title": "entrega.zip"}},
                    {"link": {"title": "Repo", "url": "https://github.com/x"}},
                ]
            }
        }
    )
    assert [f.file_id for f in files] == ["f1"]
    assert [link.url for link in links] == ["https://github.com/x"]
    assert _submission_attachments({}) == ((), ())


def test_parse_kinds_aliases():
    assert parse_kinds("materiales,tareas") == ("materials", "coursework")
    assert parse_kinds("ALL") == ("materials", "announcements", "coursework", "submissions")
    assert parse_kinds(None) == ("materials", "announcements", "coursework", "submissions")
    assert parse_kinds("entregas;anuncios") == ("submissions", "announcements")
    with pytest.raises(ApiError):
        parse_kinds("inventado")


def test_parse_materials_extracts_files_and_links():
    files, links = _parse_materials(
        [
            {"driveFile": {"id": "f1", "title": "guia.pdf", "alternateLink": "http://x"}},
            {
                "driveFile": {
                    "driveFile": {
                        "id": "f2",
                        "title": "apunte.pdf",
                        "alternateLink": "http://y",
                    },
                    "shareMode": "VIEW",
                }
            },
            {"youTubeVideo": {"title": "Video", "alternateLink": "http://yt"}},
            {"link": {"title": "Web", "url": "http://web"}},
            {"form": {"title": "Form", "formUrl": "http://form"}},
            {},
        ]
    )
    assert files == (
        DriveAttachment("f1", "guia.pdf", url="http://x"),
        DriveAttachment("f2", "apunte.pdf", url="http://y"),
    )
    assert [link.url for link in links] == ["http://yt", "http://web", "http://form"]


def test_extract_links_from_text_and_markdown():
    links = _extract_links(
        "Mira https://example.com/a, y [GitHub](https://github.com/x/y). "
        "Repetido: https://example.com/a"
    )
    assert [link.url for link in links] == [
        "https://example.com/a",
        "https://github.com/x/y",
    ]
    assert links[1].title == "GitHub"


def test_clean_url_keeps_balanced_parentheses_and_trims_punctuation():
    from classroom_dl.api import _clean_url

    assert (
        _clean_url("https://en.wikipedia.org/wiki/Foo_(bar).")
        == "https://en.wikipedia.org/wiki/Foo_(bar)"
    )
    assert _clean_url("https://example.com/a).") == "https://example.com/a"


def test_parse_materials_with_text_adds_description_links():
    files, links = _parse_materials_with_text(
        [
            {"driveFile": {"id": "f1", "title": "guia.pdf"}},
            {"link": {"title": "Web", "url": "https://example.com/a"}},
        ],
        "https://example.com/a https://drive.google.com/file/d/f1/view "
        "https://extra.test/x",
    )
    assert [file.file_id for file in files] == ["f1"]
    assert [link.url for link in links] == [
        "https://example.com/a",
        "https://extra.test/x",
    ]


def test_parse_date_handles_z_and_invalid():
    assert _parse_date("2026-03-10T12:00:00Z") == date(2026, 3, 10)
    assert _parse_date("2026-03-10T23:30:00-05:00") == date(2026, 3, 11)
    assert _parse_date("no-es-fecha", None) is None


def test_announcement_title_uses_first_non_empty_line():
    assert _announcement_title("\n  Hola clase\nmás texto") == "Hola clase"
    assert _announcement_title("") == "Anuncio"


def test_execute_with_retry_recovers_from_500():
    request = FakeRequest([http_error(500), {"ok": True}])
    sleeps: list[float] = []
    result = execute_with_retry(request, sleep=sleeps.append)
    assert result == {"ok": True}
    assert request.calls == 2
    assert len(sleeps) == 1


def test_execute_with_retry_honors_retry_after():
    request = FakeRequest([http_error(429, retry_after="7"), {"ok": True}])
    sleeps: list[float] = []
    execute_with_retry(request, sleep=sleeps.append)
    assert sleeps and 7 <= sleeps[0] < 8


def test_execute_with_retry_does_not_retry_404():
    request = FakeRequest([http_error(404)])
    with pytest.raises(HttpError):
        execute_with_retry(request, sleep=lambda _: None)
    assert request.calls == 1


def test_execute_with_retry_retries_rate_limit_403():
    request = FakeRequest([http_error(403, "userRateLimitExceeded"), {"ok": True}])
    assert execute_with_retry(request, sleep=lambda _: None) == {"ok": True}
    assert request.calls == 2


def test_paginate_follows_next_page_token():
    pages = [
        {"items": [{"id": "1"}], "nextPageToken": "p2"},
        {"items": [{"id": "2"}]},
    ]
    tokens: list[str | None] = []

    def factory(token):
        tokens.append(token)
        return FakeRequest([pages.pop(0)])

    assert [item["id"] for item in _paginate(factory, "items")] == ["1", "2"]
    assert tokens == [None, "p2"]


def test_item_is_hashable_and_immutable():
    item = Item(kind="materials", item_id="1", title="T")
    assert item.files == ()
    assert item.links == ()
