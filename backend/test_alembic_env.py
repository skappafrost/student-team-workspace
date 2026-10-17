"""`alembic/env.py` must resolve the same database the application opens.

The bug these tests pin is quiet and total: `config.Settings` reads `.env`
(`env_file=".env"`), while the old resolver read only the process environment and
`alembic.ini`. A developer following the README quickstart — `cp .env.example .env`,
then `alembic upgrade head` — migrated `postgresql+psycopg2://postgres:***@localhost:5432/stw`,
the hard-coded last resort, while the app opened the `.env` database. Nothing
complained: `alembic.ini:89` still holds the `driver://user:pass@localhost/dbname`
template placeholder, and both were ignored in favor of a URL that only ever
existed in CI, where `DATABASE_URL` is exported.

`os.getenv` staying first is not incidental — `manage.py` overrides the target
database for one in-process run by setting `os.environ["DATABASE_URL"]` *after*
`config` was already imported, so an import-time cached value would stamp a
database other than the one it reports on (`test_manage.py` pins the same thing
from the other side).
"""

from __future__ import annotations

import importlib.util
import logging.config
from collections.abc import Callable
from pathlib import Path
from unittest import mock

from config import Settings

ENV_PATH = Path(__file__).resolve().parent / "alembic" / "env.py"

INI_PLACEHOLDER = "driver://user:pass@localhost/dbname"


def _load_resolver() -> Callable[[], str]:
    """`env.py`'s `get_database_url`, without running its migration entrypoint.

    `env.py` is a script, not a module: importing it executes `run_migrations_*()`
    at the bottom of the file, which connects to the database and applies the chain
    to whatever the suite is pointed at. Loading it with `alembic.context` replaced
    by a stub steers it into offline mode (no engine, no connection) and leaves the
    resolver itself completely real — it reads `os.environ` and `Settings`, neither
    of which is stubbed here.
    """
    stub_context = mock.MagicMock()
    stub_context.is_offline_mode.return_value = True
    with (
        mock.patch("alembic.context", stub_context),
        # fileConfig(alembic.ini) would hand pytest's log-capture handler back.
        mock.patch.object(logging.config, "fileConfig", lambda *a, **kw: None),
    ):
        spec = importlib.util.spec_from_file_location("stw_alembic_env", ENV_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module.get_database_url


def _write_dotenv(tmp_path: Path, url: str) -> None:
    (tmp_path / ".env").write_text(f"DATABASE_URL={url}\n", encoding="utf-8")


def test_dotenv_is_used_when_the_process_env_is_silent(tmp_path, monkeypatch):
    """The "app and alembic agree" proof, for the quickstart that started this."""
    url = "sqlite:///./from_dotenv.db"
    _write_dotenv(tmp_path, url)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    get_database_url = _load_resolver()
    assert get_database_url() == url
    assert get_database_url() == Settings().database_url


def test_process_env_wins_over_dotenv(tmp_path, monkeypatch):
    url = "sqlite:///./from_process_env.db"
    _write_dotenv(tmp_path, "sqlite:///./from_dotenv.db")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", url)

    assert _load_resolver()() == url


def test_with_no_config_anywhere_it_uses_the_app_default(tmp_path, monkeypatch):
    """No `.env`, no `DATABASE_URL`: alembic migrates the file the app would open.

    It used to try a Postgres server nobody configured, so a mis-set-up developer
    got a connection error instead of a schema.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    resolved = _load_resolver()()
    assert resolved == Settings().database_url == "sqlite:///./stw.db"


def test_never_the_placeholder_never_the_fake_credential(tmp_path, monkeypatch):
    """Whatever branch resolves, it is never one of the two retired literals."""
    monkeypatch.chdir(tmp_path)
    _write_dotenv(tmp_path, "sqlite:///./from_dotenv.db")
    get_database_url = _load_resolver()

    monkeypatch.delenv("DATABASE_URL", raising=False)
    from_dotenv = get_database_url()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./from_process_env.db")
    from_process_env = get_database_url()

    for resolved in (from_dotenv, from_process_env):
        assert resolved != INI_PLACEHOLDER
        assert "***" not in resolved, "a fake credential came back from the resolver"
