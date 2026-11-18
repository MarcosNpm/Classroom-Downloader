import pytest

from classroom_dl import auth
from classroom_dl.auth import (
    SCOPES,
    _has_required_scopes,
    _missing_scopes,
    _scope_change_message,
)
from classroom_dl.errors import AuthError

COURSEWORK = "https://www.googleapis.com/auth/classroom.coursework.me.readonly"
SUBMISSIONS = "https://www.googleapis.com/auth/classroom.student-submissions.me.readonly"


class FakeCreds:
    def __init__(self, scopes):
        self.scopes = scopes


def test_has_required_scopes_accepts_all():
    assert _has_required_scopes(FakeCreds(list(SCOPES)))


def test_has_required_scopes_rejects_partial():
    assert not _has_required_scopes(FakeCreds(["https://www.googleapis.com/auth/drive.readonly"]))


def test_has_required_scopes_accepts_equivalent_scope():
    # Google puede conceder student-submissions en lugar de coursework.me.
    granted = [scope for scope in SCOPES if scope != COURSEWORK]
    assert _has_required_scopes(FakeCreds(granted))


def test_has_required_scopes_accepts_either_equivalent_scope():
    # La equivalencia vale en ambos sentidos.
    granted = [scope for scope in SCOPES if scope != SUBMISSIONS]
    assert _has_required_scopes(FakeCreds(granted))


def test_has_required_scopes_rejects_missing_unrelated_scope():
    granted = [scope for scope in SCOPES if "courseworkmaterials" not in scope]
    assert not _has_required_scopes(FakeCreds(granted))


def test_missing_scopes_reports_only_real_gaps():
    granted = [scope for scope in SCOPES if scope != COURSEWORK]
    assert _missing_scopes(granted) == []
    assert _missing_scopes([COURSEWORK]) == [
        scope for scope in SCOPES if scope not in (COURSEWORK, SUBMISSIONS)
    ]


def test_has_required_scopes_allows_unknown():
    assert _has_required_scopes(FakeCreds(None))
    assert _has_required_scopes(FakeCreds([]))


def test_scope_change_message_lists_missing_scope():
    message = _scope_change_message(
        ["https://www.googleapis.com/auth/classroom.coursework.me.readonly"]
    )
    assert "classroom.coursework.me.readonly" in message
    assert "Acceso a los datos" in message
    assert "auth --force" in message


def test_scope_change_message_handles_empty():
    assert "desconocido" in _scope_change_message([])


class FakeGrantedCreds:
    def __init__(self, scopes):
        self.scopes = scopes

    def to_json(self):
        return '{"scopes": []}'


def _fake_flow(monkeypatch, granted):
    class FakeFlow:
        def run_local_server(self, **kwargs):
            return FakeGrantedCreds(granted)

    monkeypatch.setattr(
        auth.InstalledAppFlow,
        "from_client_secrets_file",
        classmethod(lambda cls, *args, **kwargs: FakeFlow()),
    )


def test_load_credentials_accepts_equivalent_scope(tmp_path, monkeypatch):
    credentials = tmp_path / "client_secret.json"
    credentials.write_text("{}")
    token = tmp_path / "token.json"
    granted = [scope for scope in SCOPES if scope != COURSEWORK]
    _fake_flow(monkeypatch, granted)

    creds = auth.load_credentials(credentials, token, force=True)

    assert creds.scopes == granted
    assert token.exists()


def test_load_credentials_rejects_real_missing_scope(tmp_path, monkeypatch):
    credentials = tmp_path / "client_secret.json"
    credentials.write_text("{}")
    token = tmp_path / "token.json"
    granted = [scope for scope in SCOPES if "courseworkmaterials" not in scope]
    _fake_flow(monkeypatch, granted)

    with pytest.raises(AuthError):
        auth.load_credentials(credentials, token, force=True)

    assert not token.exists()
