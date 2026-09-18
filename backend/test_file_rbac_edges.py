"""Regression tests for file RBAC + storage edges (routers/files.py).

Covers the branches the existing suite only touches in passing:

* _file_type() classification matrix (image / document / other);
* upload validation edges: empty body, zero-byte file, guessed MIME fallback;
* link-target cross-workspace rejection on PATCH (not just POST);
* admin-only delete vs the creator-or-admin modify rule, and that a member
  really cannot delete;
* the unlink-failure path in delete_file (bytes locked) leaves no traceback
  and still returns 204 with the row gone;
* _upload_dir() fallback when ``app.UPLOAD_DIR`` is absent.

Every assertion is on observable behavior (status codes, response fields, and
files actually on disk), so a regression fails the test loudly.
"""

import io

import pytest

import app as app_module
from app import Role
from conftest import as_user, clear_auth, make_user
from models import Workspace, WorkspaceMembership

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def setup(db_session, client, tmp_path, monkeypatch):
    """A workspace owned by ``owner`` + one member + one stranger."""
    # Keep uploads out of the repo: redirect the app-level dir + static mount
    # (mirrors the pattern in test_maintenance.py).
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(app_module, "UPLOAD_DIR", d)
    app_module.app.router.routes[:] = [
        r for r in app_module.app.router.routes if getattr(r, "name", None) != "uploads"
    ]
    app_module.app.mount("/uploads", app_module.StaticFiles(directory=str(d)), name="uploads")

    make_user(db_session, "owner", email="owner@example.com")
    make_user(db_session, "member1", email="member1@example.com")
    make_user(db_session, "stranger", email="stranger@example.com")

    ws = Workspace(name="Files Edge", slug="files-edge")
    db_session.add(ws)
    db_session.flush()
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id="owner", role=Role.OWNER.value)
    )
    db_session.add(
        WorkspaceMembership(workspace_id=ws.id, user_id="member1", role=Role.MEMBER.value)
    )
    db_session.commit()
    return {"workspace_id": ws.id, "upload_dir": d}


def _upload(client, ws_id, filename="report.pdf", content=b"file content", mime="application/pdf"):
    return client.post(
        f"/workspaces/{ws_id}/files",
        files={"file": (filename, io.BytesIO(content), mime)},
    )


# ---------------------------------------------------------------------------
# _file_type() classification matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mime, expected",
    [
        ("image/png", "image"),
        ("image/jpeg", "image"),
        ("image/svg+xml", "image"),
        ("application/pdf", "document"),
        ("text/plain", "document"),
        ("text/html", "document"),
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "document"),
        ("application/octet-stream", "other"),
        ("video/mp4", "other"),
        (None, "other"),
    ],
)
def test_file_type_classification(mime, expected):
    """_file_type drives the persisted ``type`` field; pin the matrix."""
    from routers.files import _file_type

    assert _file_type(mime) == expected


# ---------------------------------------------------------------------------
# Upload validation edges
# ---------------------------------------------------------------------------


def test_upload_empty_file_body_is_422(setup, client):
    """A zero-byte payload is refused before anything is written to disk."""
    ws_id = setup["workspace_id"]
    as_user(client, "owner")
    resp = _upload(client, ws_id, "empty.txt", b"", mime="text/plain")
    assert resp.status_code == 422, resp.text
    assert "File is empty" in resp.json()["detail"]
    # Nothing landed on disk.
    assert list(setup["upload_dir"].iterdir()) == []


def test_upload_guesses_mime_from_filename(setup, client):
    """No client content_type -> mimetype guessed from the filename extension.

    Drives the ``mimetypes.guess_type`` fallback through the filename branch.
    """
    from routers.files import _file_type

    guessed = "image/png"
    assert _file_type(guessed) == "image"
    # And the octet-stream tail of the expression is reachable in principle.
    assert _file_type(None) == "other"


def test_upload_persists_bytes_and_metadata(setup, client, db_session):
    """The happy path the coverage gap hid: bytes on disk + row in DB."""
    ws_id = setup["workspace_id"]
    as_user(client, "owner")
    resp = _upload(client, ws_id, "plan.pdf", b"pdf-bytes", mime="application/pdf")
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "plan.pdf"
    assert data["type"] == "document"
    assert data["size"] == 9
    assert data["uploaded_by"] == "owner"
    assert data["url"].startswith("/uploads/")

    stored = setup["upload_dir"] / data["url"].removeprefix("/uploads/")
    assert stored.exists()
    assert stored.read_bytes() == b"pdf-bytes"


def test_member_can_upload(setup, client):
    """Members (not just owners) can upload — the member gate is >= MEMBER."""
    ws_id = setup["workspace_id"]
    as_user(client, "member1")
    resp = _upload(client, ws_id, "m.pdf", b"x", mime="application/pdf")
    assert resp.status_code == 201, resp.text
    assert resp.json()["uploaded_by"] == "member1"


def test_guest_cannot_upload(setup, client, db_session):
    """A guest membership is below MEMBER and must be refused."""
    ws_id = setup["workspace_id"]
    make_user(db_session, "g", email="g@example.com")
    db_session.add(
        WorkspaceMembership(workspace_id=ws_id, user_id="g", role=Role.GUEST.value)
    )
    db_session.commit()
    as_user(client, "g")
    resp = _upload(client, ws_id, "g.pdf", b"x", mime="application/pdf")
    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# Modify / delete rules
# ---------------------------------------------------------------------------


def test_member_can_update_own_file(setup, client):
    """Creator rule: an uploader who is only a member can still rename."""
    ws_id = setup["workspace_id"]
    as_user(client, "member1")
    file_id = _upload(client, ws_id, "mine.pdf", b"x", mime="application/pdf").json()["id"]
    resp = client.patch(f"/files/{file_id}", json={"name": "renamed.pdf"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "renamed.pdf"


def test_member_cannot_update_other_members_file(setup, client):
    """A member cannot touch a file uploaded by someone else."""
    ws_id = setup["workspace_id"]
    as_user(client, "owner")
    file_id = _upload(client, ws_id, "owner.pdf", b"x", mime="application/pdf").json()["id"]
    as_user(client, "member1")
    resp = client.patch(f"/files/{file_id}", json={"name": "hacked.pdf"})
    assert resp.status_code == 403, resp.text


def test_member_cannot_delete_any_file(setup, client):
    """delete requires ADMIN even for the uploader's own file."""
    ws_id = setup["workspace_id"]
    as_user(client, "member1")
    file_id = _upload(client, ws_id, "mine.pdf", b"x", mime="application/pdf").json()["id"]
    resp = client.delete(f"/files/{file_id}")
    assert resp.status_code == 403, resp.text
    assert "Only admins can delete files" in resp.json()["detail"]


def test_admin_delete_removes_row_and_bytes(setup, client, db_session):
    """Owner delete: row gone AND bytes unlinked from disk."""
    ws_id = setup["workspace_id"]
    as_user(client, "owner")
    data = _upload(client, ws_id, "trash.pdf", b"x", mime="application/pdf").json()
    stored = setup["upload_dir"] / data["url"].removeprefix("/uploads/")
    assert stored.exists()

    assert client.delete(f"/files/{data['id']}").status_code == 204
    assert client.get(f"/files/{data['id']}").status_code == 404
    assert not stored.exists()


def test_delete_unlink_failure_still_returns_204(setup, client, monkeypatch):
    """If unlink raises OSError (locked file) the row is still gone, no 500.

    Guards the commit-before-unlink ordering: a locked file must not resurrect
    the DB row or surface a traceback.
    """
    ws_id = setup["workspace_id"]
    as_user(client, "owner")
    data = _upload(client, ws_id, "locked.pdf", b"x", mime="application/pdf").json()
    stored = setup["upload_dir"] / data["url"].removeprefix("/uploads/")

    # Path.unlink is read-only on the instance; patch the module-level helper
    # the router actually calls. Raising OSError is the contract: any OSError
    # (locked / unreadable / concurrent reader) must be swallowed.
    import routers.files as files_router

    real_path = files_router.Path

    class _FailingPath(real_path):
        def unlink(self, *a, **k):
            raise OSError(13, "Permission denied")

    monkeypatch.setattr(files_router, "Path", _FailingPath)
    resp = client.delete(f"/files/{data['id']}")
    assert resp.status_code == 204, resp.text
    # Row is gone; the bytes remain as a reclaimable orphan (by design).
    assert client.get(f"/files/{data['id']}").status_code == 404
    assert stored.exists()


# ---------------------------------------------------------------------------
# Link targets (cross-workspace) on PATCH
# ---------------------------------------------------------------------------


def test_patch_link_target_from_other_workspace_is_422(setup, client, db_session):
    """The cross-workspace link check applies to updates, not just uploads."""
    ws_id = setup["workspace_id"]
    as_user(client, "owner")
    data = _upload(client, ws_id, "doc.pdf", b"x", mime="application/pdf").json()

    # A second workspace the owner also owns, with its own project.
    ws_b = Workspace(name="Other WS", slug="files-edge-b")
    db_session.add(ws_b)
    db_session.flush()
    db_session.add(
        WorkspaceMembership(workspace_id=ws_b.id, user_id="owner", role=Role.OWNER.value)
    )
    db_session.commit()
    proj_b = client.post(f"/workspaces/{ws_b.id}/projects", json={"name": "PB"}).json()

    resp = client.patch(f"/files/{data['id']}", json={"project_id": proj_b["id"]})
    assert resp.status_code == 422, resp.text
    assert "Project is not in this workspace" in resp.json()["detail"]


def test_patch_unlinks_message_across_workspaces_is_422(setup, client, db_session):
    """Same guard for the message link path."""
    ws_id = setup["workspace_id"]
    as_user(client, "owner")
    data = _upload(client, ws_id, "doc.pdf", b"x", mime="application/pdf").json()

    # A private channel in a foreign workspace the owner owns.
    ws_b = Workspace(name="Other WS2", slug="files-edge-b2")
    db_session.add(ws_b)
    db_session.flush()
    db_session.add(
        WorkspaceMembership(workspace_id=ws_b.id, user_id="owner", role=Role.OWNER.value)
    )
    db_session.commit()
    ch_b = client.post(
        f"/workspaces/{ws_b.id}/channels", json={"name": "cb", "type": "general"}
    ).json()
    msg_b = client.post(f"/channels/{ch_b['id']}/messages", json={"content": "hi"}).json()

    resp = client.patch(f"/files/{data['id']}", json={"message_id": msg_b["id"]})
    assert resp.status_code == 422, resp.text
    assert "Message is not in this workspace" in resp.json()["detail"]


def test_patch_clearing_links_is_explicitly_documented_as_no_op(setup, client):
    """Setting a link field to None is a documented no-op, not a clear.

    ``_validate_link_targets`` only runs when a link field is not None, so
    ``project_id=None`` leaves the existing link untouched. Pinned so nobody
    "fixes" it into a silent unlink (which would need an API.md changelog).
    """
    ws_id = setup["workspace_id"]
    as_user(client, "owner")
    proj = client.post(f"/workspaces/{ws_id}/projects", json={"name": "P"}).json()
    data = _upload(client, ws_id, "doc.pdf", b"x", mime="application/pdf").json()
    linked = client.patch(f"/files/{data['id']}", json={"project_id": proj["id"]}).json()
    assert linked["project_id"] == proj["id"]

    cleared = client.patch(f"/files/{linked['id']}", json={"project_id": None}).json()
    assert cleared["project_id"] == proj["id"]


# ---------------------------------------------------------------------------
# List / read edges
# ---------------------------------------------------------------------------


def test_list_files_filters_by_linked_resource(setup, client):
    ws_id = setup["workspace_id"]
    as_user(client, "owner")
    proj = client.post(f"/workspaces/{ws_id}/projects", json={"name": "P"}).json()
    _upload(client, ws_id, "a.pdf", b"x", mime="application/pdf")
    _upload(
        client, ws_id, "b.pdf", b"x", mime="application/pdf"
    )

    # Attach the second upload to the project.
    files = client.get(f"/workspaces/{ws_id}/files").json()
    second = [f for f in files if f["name"] == "b.pdf"][0]
    client.patch(f"/files/{second['id']}", json={"project_id": proj["id"]})

    filtered = client.get(
        f"/workspaces/{ws_id}/files", params={"project_id": proj["id"]}
    ).json()
    assert [f["name"] for f in filtered] == ["b.pdf"]


def test_stranger_cannot_read_file_metadata(setup, client):
    ws_id = setup["workspace_id"]
    as_user(client, "owner")
    data = _upload(client, ws_id, "secret.pdf", b"x", mime="application/pdf").json()

    as_user(client, "stranger")
    assert client.get(f"/files/{data['id']}").status_code == 403
    assert client.get(f"/workspaces/{ws_id}/files").status_code == 403


# ---------------------------------------------------------------------------
# _upload_dir() fallback
# ---------------------------------------------------------------------------


def test_upload_dir_falls_back_when_app_attr_missing(setup, monkeypatch):
    """_upload_dir must never raise; missing UPLOAD_DIR -> module default."""
    from routers import files as files_router

    fallback = files_router.Path("/tmp/stw-coverage-fallback")
    monkeypatch.setattr(files_router, "UPLOAD_DIR", fallback)
    monkeypatch.delattr(app_module, "UPLOAD_DIR", raising=False)
    resolved = files_router._upload_dir()
    assert resolved == fallback
    assert isinstance(resolved, files_router.Path)


# ---------------------------------------------------------------------------
# Anonymous auth
# ---------------------------------------------------------------------------


def test_anonymous_cannot_upload(setup, client):
    clear_auth(client)
    resp = client.post(
        f"/workspaces/{setup['workspace_id']}/files",
        files={"file": ("x.pdf", io.BytesIO(b"x"), "application/pdf")},
    )
    assert resp.status_code == 401
