from classroom_dl.auth import SCOPES, _has_required_scopes, _scope_change_message


class FakeCreds:
    def __init__(self, scopes):
        self.scopes = scopes


def test_has_required_scopes_accepts_all():
    assert _has_required_scopes(FakeCreds(list(SCOPES)))


def test_has_required_scopes_rejects_partial():
    assert not _has_required_scopes(FakeCreds(["https://www.googleapis.com/auth/drive.readonly"]))


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
