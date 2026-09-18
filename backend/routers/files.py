"""File upload / management endpoints + upload-dir config."""

import logging
import mimetypes
import re
import unicodedata
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from fastapi import File as FileParam
from sqlalchemy.orm import Session

import models
import rate_limit
import schemas
from authorization import ROLE_HIERARCHY, Role, _require_member
from config import settings
from database import get_db
from dependencies import (
    _get_channel_or_404,
    _get_file_or_404,
    _get_message_or_404,
    _get_project_or_404,
    _get_task_or_404,
    _get_workspace_or_404,
    get_current_user,
)
from services import log_activity, notify

router = APIRouter()

UPLOAD_DIR = Path(settings.upload_dir)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# --- Ingress hardening (TA2-1) -------------------------------------------
#
# Extension allow-list: what the product actually stores + previews (see
# app/src/components/ui/file-preview.tsx) plus working artifacts a student
# team exchanges (archives, code, json, office documents). Deliberately
# EXCLUDES: svg/html/xml (same-origin stored XSS via the /uploads static
# mount), executables + scripts (exe/dll/bat/ps1/...), macro documents
# (docm/xlsm), and anything without a recognizable extension.
UPLOAD_ALLOWED_EXTENSIONS = frozenset({
    # images (previews inline; svg excluded — XSS vector)
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic",
    # documents (previews; rtf/csv/md under text/document)
    ".pdf", ".txt", ".md", ".csv", ".rtf",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".odp",
    # media (previews)
    ".mp4", ".mov", ".avi", ".mkv", ".webm",
    ".mp3", ".wav", ".ogg", ".m4a", ".flac",
    # archives / data / code (student-team working artifacts)
    ".zip", ".tar", ".gz", ".7z",
    ".json",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cpp", ".cs",
    ".go", ".rs", ".php", ".rb", ".sh", ".sql", ".ipynb",
    ".yml", ".yaml", ".toml", ".ini", ".cfg",
})

# Executable/architecture magic signatures refused regardless of extension
# or declared content-type (anti-spoofing). Matched against the first bytes
# of the streamed content; any hit rejects the upload.
UPLOAD_EXECUTABLE_MAGIC = (
    b"MZ",          # PE / MS-DOS (Windows .exe/.dll) — also PE-at-offset trickery
    b"\x7fELF",     # Linux ELF
    b"\xfe\xed\xfa\xce",  # Mach-O 32
    b"\xfe\xed\xfa\xcf",  # Mach-O 64
    b"\xca\xfe\xba\xbe",  # Java class / Mach-O fat
)

# Control + format characters (Unicode Cc/Cf — includes RTL overrides) never
# belong in a stored filename; stripped before the name is persisted anywhere.
# Windows-reserved filename characters on the storage side
_BAD_FS_CHARS = '<>:"|?*'
# Filename cap: uuid (36) + underscore + slug <= 160 keeps storage_key well
# under DB varchar(2048) and any filesystem component limit (255).
_MAX_NAME_CHARS = 160

# Chunk size for streaming uploads to memory before the cap check commits.
_UPLOAD_CHUNK = 1024 * 1024


def _sanitize_display_name(raw: str) -> str:
    """Return the user-facing, unicode-preserving sanitized filename.

    Traversal components (any ``/`` or ``\\``) are collapsed to ``_`` so the
    original structure is still readable; control/format characters are
    dropped; the result is truncated to a safe length (extension kept).
    Vietnamese/unicode characters survive untouched.
    """
    name = unicodedata.normalize("NFC", raw)
    name = name.replace("/", "_").replace("\\", "_")
    # Strip control characters (Cc) and format characters (Cf: RTL overrides)
    name = "".join(
        ch for ch in name
        if unicodedata.category(ch) not in ("Cc", "Cf") and ch not in _BAD_FS_CHARS
    )
    name = name.strip(" ._")
    if len(name) > _MAX_NAME_CHARS:
        stem, dot, ext = name.rpartition(".")
        if dot and 0 < len(ext) <= 10:
            name = stem[: _MAX_NAME_CHARS - len(ext) - 1] + "." + ext
        else:
            name = name[:_MAX_NAME_CHARS]
    if not name:
        raise HTTPException(status_code=422, detail="File name is required")
    return name


def _ascii_slug(name: str) -> str:
    """ASCII-safe, flat, deterministic slug for the storage key (TA2-1).

    The DB row stores the original (unicode) name for display; the on-disk
    key uses this slug so any filesystem/encoding quirk is impossible.
    Per project rule: ASCII-safe identifiers, unicode-preserving display
    names. Unicode letters are transliterated where possible (NFKD), the
    rest falls back to ``_``; separators/path parts are already gone by
    now (input is the sanitized name).
    """
    slug = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^0-9A-Za-z._-]+", "_", slug)
    slug = re.sub(r"\.{2,}", "_", slug)  # collapse dot-runs — no '..' in keys
    slug = slug.strip("._")
    return slug or "file"


def _stream_upload(file: UploadFile) -> bytes:
    """Read the body in chunks, enforcing the MAX_UPLOAD_MB cap as we go.

    Returns the buffered bytes (≤ cap). Raising 413 mid-stream aborts the
    request before anything is written to disk — with the default 25 MB cap
    the peak memory per upload is bounded by the cap itself.
    """
    cap = settings.max_upload_bytes
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = file.file.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > cap:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds the maximum upload size of {int(settings.max_upload_mb)} MB",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _check_extension(name: str) -> str:
    """Validate the sanitized filename's extension against the allow-list."""
    ext = Path(name).suffix.lower()
    if ext not in UPLOAD_ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"File type '{ext or '(none)'}' is not allowed. Allowed: images, PDF, "
            "text/markdown/code, office docs, archives, media",
        )
    return ext


def _check_not_executable(content: bytes) -> None:
    """Reject known executable signatures even behind allowed extensions."""
    head = content[:8]
    for magic in UPLOAD_EXECUTABLE_MAGIC:
        if head.startswith(magic):
            raise HTTPException(
                status_code=415,
                detail="File content looks like an executable and was rejected",
            )


def _upload_dir() -> Path:
    """Resolve the upload dir at request time.

    Tests monkeypatch ``app.UPLOAD_DIR`` (and remount /uploads) to redirect
    storage into a tmp dir; reading through the app module keeps that hook
    working now that the routes live in this router instead of app.py.
    """
    try:
        import app as _app

        return Path(getattr(_app, "UPLOAD_DIR", UPLOAD_DIR))
    except Exception:
        return UPLOAD_DIR


def _file_type(mime_type: str | None) -> str:
    if not mime_type:
        return "other"
    if mime_type.startswith("image/"):
        return "image"
    if (
        mime_type in ("application/pdf",)
        or mime_type.startswith("text/")
        or "document" in mime_type
    ):
        return "document"
    return "other"


def _file_out(file: models.File) -> dict:
    return {
        "id": file.id,
        "workspace_id": file.workspace_id,
        "project_id": file.project_id,
        "task_id": file.task_id,
        "message_id": file.message_id,
        "name": file.original_name,
        "type": _file_type(file.mime_type),
        "size": file.size_bytes,
        "url": f"/uploads/{file.storage_key}",
        "uploaded_by": file.uploader_id,
        "created_at": file.created_at,
    }


def _can_modify_file(
    file: models.File, membership: models.WorkspaceMembership, current_user: dict
) -> bool:
    user_role_value = membership.role
    user_role = Role(user_role_value) if user_role_value in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] >= ROLE_HIERARCHY[Role.ADMIN]:
        return True
    return file.uploader_id == current_user["id"]


def _validate_link_targets(
    db: Session,
    workspace_id: str,
    project_id: str | None,
    task_id: str | None,
    message_id: str | None,
) -> None:
    """Ensure linked resources exist and belong to the same workspace."""
    if project_id is not None:
        project = _get_project_or_404(db, project_id)
        if project.workspace_id != workspace_id:
            raise HTTPException(status_code=422, detail="Project is not in this workspace")
    if task_id is not None:
        task = _get_task_or_404(db, task_id)
        task_project = _get_project_or_404(db, task.project_id)
        if task_project.workspace_id != workspace_id:
            raise HTTPException(status_code=422, detail="Task is not in this workspace")
    if message_id is not None:
        message = _get_message_or_404(db, message_id)
        channel = _get_channel_or_404(db, message.channel_id)
        if channel.workspace_id != workspace_id:
            raise HTTPException(status_code=422, detail="Message is not in this workspace")


@router.post(
    "/workspaces/{workspace_id}/files",
    status_code=201,
    dependencies=[Depends(rate_limit.upload_limit)],
)
async def upload_file(
    workspace_id: str,
    file: UploadFile = FileParam(...),
    project_id: str | None = Form(None),
    task_id: str | None = Form(None),
    message_id: str | None = Form(None),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a file to a workspace, optionally linked to a project/task/message."""
    _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot upload files")

    if not file.filename:
        raise HTTPException(status_code=422, detail="File name is required")

    _validate_link_targets(db, workspace_id, project_id, task_id, message_id)

    # --- Ingress hardening pipeline (TA2-1) ---
    # 1) sanitize the user-controlled filename (traversal/control chars out,
    #    unicode display name preserved, NFC-normalized for deterministic
    #    duplicate handling)
    original_name = _sanitize_display_name(file.filename)
    # 2) extension allow-list (rejects spoofed/no-extension uploads)
    _check_extension(original_name)
    # 3) stream-read the body with a server-side size cap (413 mid-stream,
    #    before anything touches disk)
    content = _stream_upload(file)
    size = len(content)
    if size == 0:
        raise HTTPException(status_code=422, detail="File is empty")
    # 4) reject executable magic signatures behind allowed extensions
    _check_not_executable(content)

    mime_type = (
        file.content_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    )
    # ASCII-safe, flat, deterministic storage key: uuid prefix keeps
    # re-uploads of the same name distinct; the slug is derived from the
    # sanitized name so identical inputs produce identical slug parts.
    storage_key = f"{uuid.uuid4()}_{_ascii_slug(original_name)}"
    file_path = _upload_dir() / storage_key
    file_path.write_bytes(content)

    db_file = models.File(
        workspace_id=workspace_id,
        project_id=project_id,
        task_id=task_id,
        message_id=message_id,
        uploader_id=current_user["id"],
        original_name=original_name,
        storage_key=storage_key,
        mime_type=mime_type,
        size_bytes=size,
    )
    db.add(db_file)
    db.commit()
    db.refresh(db_file)

    # Notify the uploader + record activity via the shared service layer (R03).
    notify(
        db,
        user_id=current_user["id"],
        type="file-upload",
        title="File uploaded",
        content=f"Your file {original_name} was uploaded successfully.",
        link="/dashboard/files",
    )
    log_activity(
        db,
        workspace_id=workspace_id,
        actor_id=current_user["id"],
        verb="uploaded",
        target_type="file",
        target_id=db_file.id,
        target_label=original_name,
    )
    db.commit()

    return _file_out(db_file)


@router.get("/workspaces/{workspace_id}/files")
async def list_workspace_files(
    workspace_id: str,
    project_id: str | None = None,
    task_id: str | None = None,
    message_id: str | None = None,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List files in a workspace, optionally filtered by linked resource."""
    _get_workspace_or_404(db, workspace_id)
    membership = _require_member(workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot view files")

    query = db.query(models.File).filter(models.File.workspace_id == workspace_id)
    if project_id is not None:
        query = query.filter(models.File.project_id == project_id)
    if task_id is not None:
        query = query.filter(models.File.task_id == task_id)
    if message_id is not None:
        query = query.filter(models.File.message_id == message_id)
    files = query.order_by(models.File.created_at.desc()).all()
    return [_file_out(f) for f in files]


@router.get("/files/{file_id}")
async def get_file(
    file_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get a single file. Must be a workspace member."""
    file = _get_file_or_404(db, file_id)
    membership = _require_member(file.workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.MEMBER]:
        raise HTTPException(status_code=403, detail="Guests cannot view files")

    return _file_out(file)


@router.patch("/files/{file_id}")
async def update_file(
    file_id: str,
    payload: schemas.FileUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update a file's metadata. Requires creator or admin/owner."""
    file = _get_file_or_404(db, file_id)
    membership = _require_member(file.workspace_id, current_user["id"], db)

    if not _can_modify_file(file, membership, current_user):
        raise HTTPException(status_code=403, detail="Not allowed to update this file")

    if payload.name is not None:
        file.original_name = payload.name
    if (
        payload.project_id is not None
        or payload.task_id is not None
        or payload.message_id is not None
    ):
        _validate_link_targets(
            db, file.workspace_id, payload.project_id, payload.task_id, payload.message_id
        )
        if payload.project_id is not None:
            file.project_id = payload.project_id
        if payload.task_id is not None:
            file.task_id = payload.task_id
        if payload.message_id is not None:
            file.message_id = payload.message_id

    db.commit()
    db.refresh(file)
    return _file_out(file)


@router.delete("/files/{file_id}", status_code=204)
async def delete_file(
    file_id: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete a file. Requires admin/owner."""
    file = _get_file_or_404(db, file_id)
    membership = _require_member(file.workspace_id, current_user["id"], db)

    user_role = Role(membership.role) if membership.role in [r.value for r in Role] else Role.GUEST
    if ROLE_HIERARCHY[user_role] < ROLE_HIERARCHY[Role.ADMIN]:
        raise HTTPException(status_code=403, detail="Only admins can delete files")

    # Commit the row deletion BEFORE unlinking the bytes: if the commit fails
    # the bytes must stay on disk (a row pointing at a missing file breaks
    # downloads with a 500). Worst case we leave an orphaned upload, which
    # `python -m maintenance purge-orphans` reclaims.
    db.delete(file)
    db.commit()

    storage_path = _upload_dir() / file.storage_key
    try:
        if storage_path.exists():
            storage_path.unlink()
    except OSError:
        # Bytes may be locked/unreadable (antivirus, concurrent reader) — the
        # row is already gone; the maintenance purge reaps orphan bytes later.
        logging.getLogger(__name__).warning("Failed to unlink %s", storage_path, exc_info=True)
    return None
