"""Role model and RBAC checks shared by all routers."""

from enum import StrEnum

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

import models
from database import get_db
from dependencies import get_current_user


class Role(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    GUEST = "guest"


ROLE_HIERARCHY = {
    Role.OWNER: 4,
    Role.ADMIN: 3,
    Role.MEMBER: 2,
    Role.GUEST: 1,
}

# Roles that may be handed out by another user. `owner` is excluded on purpose:
# it is reachable only through POST /workspaces/{id}/transfer-ownership (SEC-01).
ASSIGNABLE_ROLES = (Role.ADMIN, Role.MEMBER, Role.GUEST)


def role_in_workspace(workspace_id: str, user_id: str, db: Session) -> Role:
    """The caller's role *inside* the workspace.

    ``current_user["role"]`` is the global token role, which
    ``get_current_user`` always reports as ``member`` — comparing a grant
    against it would let any workspace admin mint owners.
    """
    membership = _require_member(workspace_id, user_id, db)
    try:
        return Role(membership.role)
    except ValueError:
        return Role.GUEST


def require_assignable_role(caller_role: Role, requested: Role) -> None:
    """Refuse a role grant the caller has no standing to make."""
    if requested not in ASSIGNABLE_ROLES:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Cannot grant '{requested.value}': ownership moves only through "
                "transfer-ownership"
            ),
        )
    if ROLE_HIERARCHY[requested] > ROLE_HIERARCHY[caller_role]:
        raise HTTPException(
            status_code=403,
            detail=f"Cannot grant '{requested.value}': it outranks your own role",
        )


def _require_member(workspace_id: str, user_id: str, db: Session) -> models.WorkspaceMembership:
    membership = (
        db.query(models.WorkspaceMembership)
        .filter(
            models.WorkspaceMembership.workspace_id == workspace_id,
            models.WorkspaceMembership.user_id == user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Not a workspace member")
    return membership


def _require_min_role(current_user: dict, required_role: Role) -> None:
    user_role_value = current_user.get("role", Role.GUEST.value)
    try:
        user_role = Role(user_role_value)
    except ValueError:
        user_role = Role.GUEST
    user_level = ROLE_HIERARCHY[user_role]
    required_level = ROLE_HIERARCHY[required_role]
    if user_level < required_level:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{user_role.value}' is insufficient. Requires '{required_role.value}'.",
        )


def require_role(required_role: Role):
    """Dependency factory that requires a minimum workspace role."""

    def _check_role(
        current_user: dict = Depends(get_current_user),
        workspace_id: str = None,
        db: Session = Depends(get_db),
    ) -> dict:
        # If workspace_id is not provided, check global role (from token)
        if workspace_id is None:
            _require_min_role(current_user, required_role)
            return current_user

        # First check if workspace exists
        workspace = db.query(models.Workspace).filter(models.Workspace.id == workspace_id).first()
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")

        # Check role within the specific workspace
        membership = _require_member(workspace_id, current_user["id"], db)
        user_role_value = membership.role
        try:
            user_role = Role(user_role_value)
        except ValueError:
            user_role = Role.GUEST
        user_level = ROLE_HIERARCHY[user_role]
        required_level = ROLE_HIERARCHY[required_role]
        if user_level < required_level:
            raise HTTPException(
                status_code=403,
                detail=f"Role '{user_role.value}' is insufficient in this workspace. Requires '{required_role.value}'.",
            )
        return current_user

    return _check_role


def require_permission(permission: str):
    """Dependency factory that requires a specific permission."""
    # Map permissions to required roles
    PERMISSION_ROLES = {
        # Workspace permissions
        "workspace.create": Role.MEMBER,
        "workspace.delete": Role.OWNER,
        "workspace.transfer_ownership": Role.OWNER,
        "workspace.update": Role.ADMIN,
        "workspace.invite": Role.ADMIN,
        "workspace.manage_members": Role.ADMIN,
        "workspace.view_audit_log": Role.ADMIN,
        # Member permissions
        "member.remove": Role.ADMIN,
        "member.update_role": Role.ADMIN,
        # Project permissions
        "project.create": Role.MEMBER,
        "project.update": Role.ADMIN,
        "project.delete": Role.ADMIN,
        "project.manage_members": Role.ADMIN,
    }

    required_role = PERMISSION_ROLES.get(permission, Role.OWNER)
    return require_role(required_role)
