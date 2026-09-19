"""Upload ingress hardening (TA2-1): filename, size, type and spoofing checks.

Pins the server-side contract of POST /workspaces/{id}/files:
- storage_key must be flat + traversal-proof: user-controlled filename never
  reaches the filesystem path (posix/unix separators, '..' parts, absolute
  paths all collapse to a safe, deterministic ASCII key).
- control characters are stripped from the stored name; Vietnamese/unicode
  display names survive untouched.
- uploads are capped server-side (default 25 MB, MAX_UPLOAD_MB env); the cap
  is enforced while streaming, before anything is written to disk.
- extension allow-list rejects disallowed types regardless of the declared
  content-type; PE/ELF/Mach-O/class-file executables are refused by content
  even when renamed to an allowed extension.
- duplicate content is stored independently (documented decision, see PR +
  docs/API.md).
"""

import io

import pytest
from fastapi.testclient import TestClient
from starlette.staticfiles import StaticFiles

import app as app_module
import database
from app import app
from conftest import as_user, make_user


# ---------------------------------------------------------------------------
# Fixtures (same isolation pattern as test_maintenance.py)
# ---------------------------------------------------------------------------


@pytest.fixture()
def upload_dir(tmp_path, monkeypatch):
    """Point UPLOAD_DIR (and the /uploads static mount) at a tmp directory."""
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(app_module, "UPLOAD_DIR", d)
    # The static mount captured the default ./uploads dir at import time, so
    # swap the route to serve from the tmp dir instead.
    app_module.app.router.routes[:] = [
        r for r in app_module.app.router.routes if getattr(r, "name", None) != "uploads"
    ]
    app_module.app.mount("/uploads", StaticFiles(directory=str(d)), name="uploads")
    return d


@pytest.fixture()
def client(db_session, upload_dir):
    def _get_db_override():
        return db_session

    app.dependency_overrides[database.get_db] = _get_db_override
    yield TestClient(app)
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_workspace(client: TestClient, db_session, user_id: str = "owner") -> dict:
    make_user(db_session, user_id)
    as_user(client, user_id)
    resp = client.post("/workspaces", json={"name": "WS", "slug": "ws", "description": "x"})
    assert resp.status_code == 201, resp.text
    return resp.json()


def post_upload(
    client: TestClient,
    ws_id: str,
    filename: str,
    content: bytes,
    ctype: str = "application/pdf",
):
    return client.post(
        f"/workspaces/{ws_id}/files",
        files={"file": (filename, io.BytesIO(content), ctype)},
    )


def storage_key_of(data: dict) -> str:
    return data["url"].split("/uploads/")[1]


# ---------------------------------------------------------------------------
# Filename sanitization
# ---------------------------------------------------------------------------


class TestFilenameSanitization:
    def test_traversal_names_with_allowed_ext_rejected_422(self, client, db_session, upload_dir):
        """A filename carrying a path separator is rejected outright (422).

        Reconciles TA2-1 (#128, which flattened traversal names into a safe
        key) with TA7-1 (#175, which hard-rejects them). The reject wins: it
        answers the client with the truthful reason ('path separators')
        instead of silently renaming the upload, and it never reaches the
        filesystem, so nothing can escape UPLOAD_DIR.
        """
        ws = create_workspace(client, db_session)
        for name in (
            "../../etc/passwd.txt",
            "ok/../../outside.txt",
            "..\\..\\evil.txt",
            "/etc/shadow.txt",
            "a/../../escaped.txt",
        ):
            resp = post_upload(client, ws["id"], name, b"x", "text/plain")
            assert resp.status_code == 422, (name, resp.text)
            assert "path separators" in resp.json()["detail"], (name, resp.text)
        # rejected before any write: the upload dir stays empty and nothing
        # escapes it into a parent directory.
        assert list(upload_dir.iterdir()) == []
        assert not (upload_dir.parent / "escaped.txt").exists()
        assert not (upload_dir.parent / "passwd").exists()

    def test_traversal_with_disallowed_or_missing_ext_rejected(self, client, db_session, upload_dir):
        """Traversal names are rejected for the separator itself (422) ahead of
        the extension allow-list — TA7-1 reject-wins. Disallowed extensions are
        still covered for clean names by ``test_disallowed_extension_rejected_415``;
        an absolute Windows path is left out here because multipart transports
        normalize drive-qualified paths inconsistently across platforms.
        Dot-only names carry no separator, so they still fall through and fail
        as 'name required'."""
        ws = create_workspace(client, db_session)
        for name in (
            "../../etc/passwd",  # relative path, '/' survives -> separator
            "/etc/shadow",  # '/' survives -> separator
        ):
            resp = post_upload(client, ws["id"], name, b"x", "application/octet-stream")
            assert resp.status_code == 422, (name, resp.text)
            assert "path separators" in resp.json()["detail"], (name, resp.text)
        # dot-only names sanitize to empty -> 422 (correct: name required)
        for name in ("..", "."):
            resp = post_upload(client, ws["id"], name, b"x", "application/octet-stream")
            assert resp.status_code == 422, (name, resp.text)
        assert list(upload_dir.iterdir()) == []

    def test_control_and_format_chars_stripped_from_stored_name(self, client, db_session, upload_dir):
        ws = create_workspace(client, db_session)
        # ESC (Cc) and RTL-override U+202E (Cf) both transport raw over
        # multipart and must be stripped; httpx percent-encodes NUL/CRLF
        # client-side, so they never arrive raw through this transport.
        cases = [
            ("a\x1bb.txt", "ab.txt"),            # escape — ANSI bomb residue
            ("ev\u202eil.pdf", "evil.pdf"),        # RTL override — name spoofing
            ("no\x1b[31mcolor.txt", "no[31mcolor.txt"),  # bracket survives, ESC dies
        ]
        for name, expected in cases:
            resp = post_upload(client, ws["id"], name, b"x", "text/plain")
            assert resp.status_code == 201, (name, resp.text)
            data = resp.json()
            assert data["name"] == expected, (name, data["name"])
            key = storage_key_of(data)
            for bad in ("\x1b", "\u202e", "\x00", "\r", "\n"):
                assert bad not in key
            assert (upload_dir / key).is_file()

    def test_vietnamese_name_survives_display_and_key_is_ascii(self, client, db_session, upload_dir):
        ws = create_workspace(client, db_session)
        name = "Báo cáo cuối kỳ - Hùng.pdf"
        resp = post_upload(client, ws["id"], name, b"pdf content")
        assert resp.status_code == 201, resp.text
        data = resp.json()
        # display name keeps unicode
        assert data["name"] == "Báo cáo cuối kỳ - Hùng.pdf"
        # storage key is ASCII-safe, flat, deterministic
        key = storage_key_of(data)
        assert key.isascii(), key
        assert "/" not in key and "\\" not in key and ".." not in key
        assert (upload_dir / key).is_file()

    def test_same_name_twice_produces_distinct_deterministic_keys(self, client, db_session, upload_dir):
        ws = create_workspace(client, db_session)
        r1 = post_upload(client, ws["id"], "doc.pdf", b"one")
        r2 = post_upload(client, ws["id"], "doc.pdf", b"two")
        assert r1.status_code == r2.status_code == 201
        k1, k2 = storage_key_of(r1.json()), storage_key_of(r2.json())
        assert k1 != k2
        # slug part is a pure function of the input name (deterministic)
        r3 = post_upload(client, ws["id"], "doc.pdf", b"one")
        assert r3.status_code == 201
        assert storage_key_of(r3.json()).split("_", 1)[1] == k1.split("_", 1)[1]

    def test_long_filename_truncated_to_safe_length(self, client, db_session, upload_dir):
        ws = create_workspace(client, db_session)
        resp = post_upload(client, ws["id"], "a" * 400 + ".pdf", b"pdf")
        assert resp.status_code == 201, resp.text
        key = storage_key_of(resp.json())
        assert len(key) <= 200
        assert key.endswith(".pdf")


# ---------------------------------------------------------------------------
# Size cap
# ---------------------------------------------------------------------------


class TestSizeCap:
    def test_default_cap_is_25mb(self):
        from config import settings

        assert settings.max_upload_mb == 25.0
        assert settings.max_upload_bytes == 25 * 1024 * 1024

    def test_oversize_rejected_413_without_writing_disk(self, client, db_session, upload_dir, monkeypatch):
        from config import settings

        ws = create_workspace(client, db_session)
        monkeypatch.setattr(settings, "max_upload_mb", 0.001)  # ~1 KB cap
        resp = post_upload(client, ws["id"], "big.pdf", b"x" * 4096)
        assert resp.status_code == 413, resp.text
        assert list(upload_dir.iterdir()) == []

    def test_boundary_at_cap_passes_one_byte_over_fails(self, client, db_session, upload_dir, monkeypatch):
        from config import settings

        ws = create_workspace(client, db_session)
        monkeypatch.setattr(settings, "max_upload_mb", 1)
        cap = settings.max_upload_bytes
        at_cap = b"x" * cap
        one_over = b"x" * (cap + 1)
        r_ok = post_upload(client, ws["id"], "at.pdf", at_cap)
        assert r_ok.status_code == 201, r_ok.text
        r_big = post_upload(client, ws["id"], "over.pdf", one_over)
        assert r_big.status_code == 413, r_big.text

    def test_empty_file_still_422(self, client, db_session, upload_dir):
        ws = create_workspace(client, db_session)
        resp = post_upload(client, ws["id"], "empty.pdf", b"")
        assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# Type allow-list & spoofing
# ---------------------------------------------------------------------------


class TestTypeAllowList:
    def test_allowed_types_pass(self, client, db_session, upload_dir):
        ws = create_workspace(client, db_session)
        cases = [
            ("photo.png", b"\x89PNG\r\n\x1a\n", "image/png", "image"),
            ("report.pdf", b"%PDF-1.4 fake", "application/pdf", "document"),
            ("filler.pdf", b"arbitrary non-magic bytes", "application/pdf", "document"),
            ("notes.txt", b"hello world", "text/plain", "document"),
            ("notes.TXT", b"hi", "text/plain", "document"),  # case-insensitive ext
            ("clip.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4", "other"),
            ("song.mp3", b"ID3\x04", "audio/mpeg", "other"),
            ("archive.zip", b"PK\x03\x04", "application/zip", "other"),
            ("schema.json", b"{}", "application/json", "other"),
            ("src.py", b"print('hi')\n", "text/x-python", "document"),
        ]
        for name, content, ctype, expected_type in cases:
            resp = post_upload(client, ws["id"], name, content, ctype)
            assert resp.status_code == 201, (name, resp.text)
            assert resp.json()["type"] == expected_type, name

    def test_disallowed_extension_rejected_415(self, client, db_session, upload_dir):
        ws = create_workspace(client, db_session)
        for name, ctype in [
            ("evil.exe", "application/x-msdownload"),
            ("macro.docm", "application/vnd.ms-word.document.macroenabled.12"),
            ("shell.bat", "application/bat"),
            ("payload.svg", "image/svg+xml"),  # stored XSS via /uploads static
            ("page.html", "text/html"),  # stored XSS via /uploads static
            ("noext", "application/octet-stream"),
        ]:
            resp = post_upload(client, ws["id"], name, b"whatever", ctype)
            assert resp.status_code == 415, (name, resp.text)
        assert list(upload_dir.iterdir()) == []

    def test_spoofed_extension_with_executable_content_rejected(self, client, db_session, upload_dir):
        ws = create_workspace(client, db_session)
        cases = [
            ("notes.pdf", b"MZ\x90\x00\x03\x00\x00\x00", "application/pdf"),  # PE
            ("notes.txt", b"\x7fELF\x02\x01\x01\x00", "text/plain"),  # ELF
            ("photo.png", b"\xfe\xed\xfa\xceMZ", "image/png"),  # Mach-O
            ("app.pdf", b"\xca\xfe\xba\xbe\x00\x00\x00", "application/pdf"),  # Java class
        ]
        for name, content, ctype in cases:
            resp = post_upload(client, ws["id"], name, content, ctype)
            assert resp.status_code == 415, (name, resp.text)
        assert list(upload_dir.iterdir()) == []

    def test_duplicate_content_stored_independently(self, client, db_session, upload_dir):
        ws = create_workspace(client, db_session)
        r1 = post_upload(client, ws["id"], "one.pdf", b"same-bytes")
        r2 = post_upload(client, ws["id"], "two.pdf", b"same-bytes")
        assert r1.status_code == r2.status_code == 201
        assert r1.json()["id"] != r2.json()["id"]
        assert len(list(upload_dir.iterdir())) == 2
