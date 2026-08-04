import pytest


def test_settings_reads_required_env_vars(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://likes:pw@localhost:5432/likes_archive")
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path))
    monkeypatch.setenv("X_USER_ID", "123456789")
    monkeypatch.setenv("X_BEARER_TOKEN", "Bearer TESTTOKEN")
    monkeypatch.setenv("X_COOKIES", "auth_token=abc; ct0=def")
    monkeypatch.setenv("X_CSRF_TOKEN", "deadbeef")

    from likes_archive.config import get_settings

    get_settings.cache_clear()
    s = get_settings()

    assert s.database_url == "postgresql+asyncpg://likes:pw@localhost:5432/likes_archive"
    assert s.media_root == tmp_path
    assert s.x_user_id == "123456789"
    assert s.x_bearer_token == "Bearer TESTTOKEN"
    assert s.x_cookies == "auth_token=abc; ct0=def"
    assert s.x_csrf_token == "deadbeef"


def test_settings_optional_fields_have_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://likes:pw@localhost:5432/likes_archive")
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path))
    monkeypatch.setenv("X_USER_ID", "123456789")
    monkeypatch.setenv("X_BEARER_TOKEN", "Bearer TESTTOKEN")
    monkeypatch.setenv("X_COOKIES", "auth_token=abc; ct0=def")
    monkeypatch.setenv("X_CSRF_TOKEN", "deadbeef")

    for var in [
        "MEDIA_BASE_URL",
        "MEDIA_DOWNLOAD_WORKERS",
        "SCRAPE_DELAY_MIN",
        "SCRAPE_DELAY_MAX",
        "SCRAPE_DELAY_PEAK_RATIO",
        "SCRAPE_FORCE_FULL_REFETCH",
        "TWEETS_PER_PAGE",
        "WEBHOOK_URL",
        "HOST",
        "PORT",
        "LOG_LEVEL",
    ]:
        monkeypatch.delenv(var, raising=False)

    from likes_archive.config import get_settings

    get_settings.cache_clear()
    s = get_settings()

    assert s.media_base_url == "/media"
    assert s.media_download_workers == 16
    assert s.scrape_delay_min == 1.0
    assert s.scrape_delay_max == 15.0
    assert s.scrape_delay_peak_ratio == 0.15
    assert s.scrape_force_full_refetch is False
    assert s.tweets_per_page == 50
    assert s.webhook_url is None
    assert s.host == "0.0.0.0"
    assert s.port == 8000
    assert s.log_level == "info"


def test_get_settings_is_cached(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://likes:pw@localhost:5432/likes_archive")
    monkeypatch.setenv("MEDIA_ROOT", str(tmp_path))
    monkeypatch.setenv("X_USER_ID", "123456789")
    monkeypatch.setenv("X_BEARER_TOKEN", "Bearer TESTTOKEN")
    monkeypatch.setenv("X_COOKIES", "auth_token=abc; ct0=def")
    monkeypatch.setenv("X_CSRF_TOKEN", "deadbeef")

    from likes_archive.config import get_settings

    get_settings.cache_clear()
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
    get_settings.cache_clear()


def test_settings_missing_required_field_raises(monkeypatch):
    for var in [
        "DATABASE_URL",
        "MEDIA_ROOT",
        "X_USER_ID",
        "X_BEARER_TOKEN",
        "X_COOKIES",
        "X_CSRF_TOKEN",
    ]:
        monkeypatch.delenv(var, raising=False)

    import pydantic

    from likes_archive.config import get_settings

    get_settings.cache_clear()
    with pytest.raises(pydantic.ValidationError):
        get_settings()


def test_settings_loads_deploy_env_files(monkeypatch, tmp_path):
    """Env files alone (no process env) are enough — matches LXC interactive CLI."""
    for var in [
        "DATABASE_URL",
        "MEDIA_ROOT",
        "X_USER_ID",
        "X_BEARER_TOKEN",
        "X_COOKIES",
        "X_CSRF_TOKEN",
    ]:
        monkeypatch.delenv(var, raising=False)

    secrets = tmp_path / "secrets.env"
    config = tmp_path / "config.env"
    secrets.write_text(
        "DATABASE_URL=postgresql+asyncpg://likes:pw@db:5432/likes_archive\n"
        "X_USER_ID=99\n"
        "X_BEARER_TOKEN=Bearer FROMFILE\n"
        "X_COOKIES=auth_token=x\n"
        "X_CSRF_TOKEN=csrf\n"
    )
    config.write_text(f"MEDIA_ROOT={tmp_path / 'media'}\n")

    from likes_archive.config import Settings, get_settings

    get_settings.cache_clear()
    s = Settings(_env_file=(str(secrets), str(config)))  # ty: ignore[missing-argument]
    assert s.database_url.endswith("/likes_archive")
    assert s.x_bearer_token == "Bearer FROMFILE"
    assert s.media_root == tmp_path / "media"
    get_settings.cache_clear()


def test_env_files_constant_includes_deploy_paths():
    from likes_archive.config import _ENV_FILES

    assert ".env" in _ENV_FILES
    assert "/etc/likes-archive/secrets.env" in _ENV_FILES
    assert "/etc/likes-archive/config.env" in _ENV_FILES
