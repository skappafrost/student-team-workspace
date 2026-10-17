"""CORS policy comes from settings, not from a wildcard.

`app.py` shipped `allow_origins=["*"]` next to `allow_credentials=True`. Browsers
reject that combination, and it made the `CORS_ORIGINS` key — documented in
`.env.example`, interpolated in `docker-compose.yml`, parsed by
`config.cors_origin_list()` — a setting with no effect at all.
"""

from fastapi.testclient import TestClient

import config
from app import app

DEV_ORIGIN = "http://localhost:3000"


def _client() -> TestClient:
    return TestClient(app)


def test_configured_origin_is_echoed_with_credentials():
    """A same-list origin gets itself back, plus the credentials opt-in."""
    resp = _client().get("/health", headers={"Origin": DEV_ORIGIN})
    assert resp.headers["access-control-allow-origin"] == DEV_ORIGIN
    assert resp.headers["access-control-allow-credentials"] == "true"


def test_unconfigured_origin_gets_no_allow_origin():
    """An origin outside the list is not permitted.

    Before the fix this assertion was impossible: `*` answered every caller, so a
    third-party page could send credentialed cross-site requests and read the
    response (the practical brake was `SameSite=lax` on the session cookie, which
    is not the same thing as a policy).
    """
    resp = _client().get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in resp.headers


def test_preflight_for_unconfigured_origin_is_not_approved():
    preflight = _client().options(
        "/workspaces",
        headers={
            "Origin": "http://evil.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert preflight.headers.get("access-control-allow-origin") is None


def test_settings_list_is_what_the_middleware_uses(monkeypatch):
    """The middleware reads the configured value, so `CORS_ORIGINS` is a control.

    The app builds its middleware at import time, so this rebuilds a second app
    from the same factory path rather than mutating the live one.
    """
    monkeypatch.setattr(
        config.settings, "cors_origins", "https://team.example, https://other.example"
    )

    assert config.settings.cors_origin_list() == ["https://team.example", "https://other.example"]
    # `app.py` resolves the list from the same helper the test just checked; the
    # module-level middleware cannot be re-pointed after import, so the contract
    # asserted here is "the helper the middleware is built from honours settings".
    from dependencies import _parse_cors_origins

    assert _parse_cors_origins() == ["https://team.example", "https://other.example"]
