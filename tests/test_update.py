from pathlib import Path

from classroom_dl import update


def test_version_comparison():
    assert update.is_newer("0.4.0", "0.3.1")
    assert update.is_newer("1.0", "0.9.9")
    assert not update.is_newer("0.3.1", "0.3.1")
    assert not update.is_newer("v0.3.0", "0.3.1")


def test_fetch_latest_prefers_highest_version(monkeypatch):
    def fake_get(url, timeout):
        if "api.github.com" in url:
            return '{"tag_name": "v0.3.0", "html_url": "https://example.com/rel"}'
        return '[project]\nversion = "0.4.0"'

    monkeypatch.setattr(update, "_http_get", fake_get)

    assert update._fetch_latest(1.0) == ("0.4.0", update.RELEASES_PAGE)


def test_check_for_update_returns_info(tmp_path, monkeypatch):
    monkeypatch.delenv(update.ENV_DISABLE, raising=False)
    monkeypatch.setattr(
        update, "_fetch_latest", lambda timeout: ("0.4.0", "https://example.com/release")
    )
    cache = tmp_path / "update-check.json"

    info = update.check_for_update("0.3.1", cache_path=cache, now=1000.0)

    assert info is not None
    assert info.latest == "0.4.0"
    assert info.url == "https://example.com/release"
    assert cache.exists()


def test_check_for_update_is_quiet_when_current(tmp_path, monkeypatch):
    monkeypatch.delenv(update.ENV_DISABLE, raising=False)
    monkeypatch.setattr(update, "_fetch_latest", lambda timeout: ("0.3.1", "url"))

    assert update.check_for_update("0.3.1", cache_path=tmp_path / "c.json", now=1000.0) is None


def test_fresh_cache_avoids_network(tmp_path, monkeypatch):
    monkeypatch.delenv(update.ENV_DISABLE, raising=False)
    cache = tmp_path / "update-check.json"
    cache.write_text('{"checked_at": 1000.0, "latest": "0.5.0"}')

    def fail(timeout):
        raise AssertionError("no debería consultar la red")

    monkeypatch.setattr(update, "_fetch_latest", fail)

    info = update.check_for_update("0.3.1", cache_path=cache, now=1000.0 + 60)

    assert info is not None
    assert info.latest == "0.5.0"


def test_failed_check_is_cached_briefly(tmp_path, monkeypatch):
    monkeypatch.delenv(update.ENV_DISABLE, raising=False)
    cache = tmp_path / "update-check.json"
    calls = []

    def fail(timeout):
        calls.append(timeout)
        return None

    monkeypatch.setattr(update, "_fetch_latest", fail)
    assert update.check_for_update("0.3.1", cache_path=cache, now=1000.0) is None
    assert update.check_for_update("0.3.1", cache_path=cache, now=1000.0 + 60) is None
    assert len(calls) == 1


def test_env_var_disables_check(monkeypatch):
    monkeypatch.setenv(update.ENV_DISABLE, "1")

    def fail(timeout):
        raise AssertionError("no debería consultar la red")

    monkeypatch.setattr(update, "_fetch_latest", fail)
    assert update.check_for_update("0.3.1") is None


def test_cache_path_uses_state_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(update, "state_dir", lambda: tmp_path)
    assert update._cache_path() == Path(tmp_path) / "update-check.json"
