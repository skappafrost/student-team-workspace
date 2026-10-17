"""The compose stack must be able to boot, and must not lose the bytes it serves.

Parsed as YAML rather than by `docker compose config`, so this runs wherever the
suite runs: no Docker daemon, no network, no Compose version to assume.

Why the file exists: `docker compose up` is the documented quickstart
(`README.md`) and it could not start the backend. `app.py` aborts when
`JWT_SECRET_KEY` is still the shipped default and `ENVIRONMENT` is not `test`/
`dev`; `docker-compose.yml` defaulted the secret to exactly that literal and
nothing in Docker set `ENVIRONMENT`, so with `restart: unless-stopped` the result
was a crash loop. No CI job builds or boots an image, so nothing was watching.
"""

import re
from pathlib import Path

import yaml

import config

COMPOSE = Path(__file__).resolve().parent / "docker-compose.yml"
ENV_EXAMPLE = Path(__file__).resolve().parent / ".env.example"

# The keys that decide whether the container starts at all, and whether it is
# reachable and persistent afterwards. Not "every settings field": most are
# legitimately optional, and a test that demands all of them is a test that gets
# widened until it means nothing.
BOOT_CRITICAL = {
    "ENVIRONMENT",
    "JWT_SECRET_KEY",
    "DATABASE_URL",
    "COOKIE_SECURE",
    "CORS_ORIGINS",
}


def _doc() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def _backend() -> dict:
    return _doc()["services"]["backend"]


def _default_of(value: str) -> str:
    """`${VAR:-fallback}` -> fallback; a literal passes through."""
    match = re.fullmatch(r"\$\{[A-Z_]+:-([^}]*)}", value.strip())
    return match.group(1) if match else value.strip()


def test_boot_critical_keys_are_supplied_to_the_container():
    missing = BOOT_CRITICAL - set(_backend()["environment"])
    assert missing == set(), f"backend service sets no value for {sorted(missing)}"


def test_default_jwt_secret_is_only_shipped_alongside_a_dev_mode():
    """The two lines have to move together.

    Defaulting the secret to the guarded literal is fine for a local demo stack
    only if the mode says dev/test; defaulting the secret *and* leaving the mode
    unset is the crash loop this file was written for.
    """
    env = _backend()["environment"]
    if _default_of(env["JWT_SECRET_KEY"]) != config.JWT_SECRET_KEY_DEFAULT:
        return
    assert _default_of(env["ENVIRONMENT"]) in {"test", "dev"}, (
        "docker-compose.yml still defaults JWT_SECRET_KEY to the value app.py "
        "refuses in production, without declaring a dev/test mode"
    )


def test_env_file_cannot_break_a_fresh_clone():
    """`.env` is gitignored, so requiring it fails `cp .env.example .env` users.

    Checked for every service, not just the backend: the second service to appear
    inherits the same trap.
    """
    for name, service in _doc()["services"].items():
        for entry in service.get("env_file") or []:
            if isinstance(entry, str):
                assert entry.endswith(".example"), (
                    f"{name}: env_file {entry!r} is mandatory and gitignored; "
                    "use the long form with required: false"
                )
            else:
                assert entry.get("required", True) is False or entry.get("required") == "false", (
                    f"{name}: env_file {entry!r} must be optional"
                )


def test_uploads_survive_a_container_recreate():
    """File rows outlive the container only if the bytes do too.

    Without a mount, `upload_dir` lives on the image's writable layer: a recreate
    left every File row pointing at nothing while the workspace quota kept
    counting the bytes that had gone.
    """
    mounts = [v for v in _backend().get("volumes") or [] if v.split(":")[1].endswith("uploads")]
    assert mounts, "backend service writes uploads to the container layer"


def test_every_referenced_volume_is_declared():
    """A reference to an undeclared named volume is a compose-time error.

    Generic on purpose — the uploads mount in this branch was nearly committed
    with exactly that mistake, and only a check that spans all services catches
    the next one.
    """
    declared = set((_doc().get("volumes") or {}).keys())
    referenced = set()
    for service in _doc()["services"].values():
        for mount in service.get("volumes") or []:
            source = mount.split(":")[0]
            if not source.startswith((".", "/", "~")):
                referenced.add(source)
    assert referenced - declared == set(), (
        f"volumes used but never declared: {sorted(referenced - declared)}"
    )


def test_environment_is_a_documented_key():
    """The mode is read by three call sites, so it has to be in the example file."""
    keys = {
        line.split("=")[0].strip()
        for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#") and "=" in line
    }
    assert "ENVIRONMENT" in keys, (
        ".env.example never mentions ENVIRONMENT while app.py and dependencies.py "
        "read it — which is how 'unset' became the accidental production setting"
    )
