"""Auth endpoints: register, login, me, logout."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

import models
import rate_limit
from authorization import Role
from database import get_db
from dependencies import (
    AuthUser,
    _clear_session_cookie,
    _decode_token,
    _set_session_cookie,
    _token_from_request,
    create_session_pair,
    get_current_user,
    get_password_hash,
    revoke_all_sessions,
    revoke_session,
    rotate_session,
    verify_password,
)

router = APIRouter()


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def _password_within_bcrypt_limit(cls, v: str) -> str:
        # Byte limit (72) is stricter than the 128-char cap; checked here so
        # register returns a clean 422 before any bcrypt call.
        from dependencies import _password_bytes

        try:
            _password_bytes(v)
        except HTTPException as exc:
            raise ValueError(exc.detail) from exc
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class RefreshIn(BaseModel):
    refresh_token: str = Field(..., min_length=1)


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: AuthUser


@router.post(
    "/auth/register",
    response_model=TokenOut,
    status_code=201,
    dependencies=[Depends(rate_limit.register_limit)],
)
async def register(payload: RegisterIn, response: Response, db: Session = Depends(get_db)):
    """Register a new user and return an JWT session."""
    existing = db.query(models.User).filter(models.User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = models.User(
        email=payload.email,
        display_name=payload.email.split("@")[0],
        hashed_password=get_password_hash(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    access_token, refresh_token = create_session_pair(user.id, db)
    db.commit()
    _set_session_cookie(response, access_token)

    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        user=AuthUser(id=user.id, name=user.display_name, email=user.email, role=Role.MEMBER.value),
    )


@router.post("/auth/login", response_model=TokenOut, dependencies=[Depends(rate_limit.login_limit)])
async def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    """Authenticate a user and return a JWT session."""
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user or not user.hashed_password:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token, refresh_token = create_session_pair(user.id, db)
    db.commit()
    _set_session_cookie(response, access_token)

    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        user=AuthUser(id=user.id, name=user.display_name, email=user.email, role=Role.MEMBER.value),
    )


@router.get("/auth/me", response_model=AuthUser)
async def me(request: Request, db: Session = Depends(get_db)):
    """Return the current authenticated user."""
    token = _token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = _decode_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user_id = payload.get("sub")
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return AuthUser(id=user.id, name=user.display_name, email=user.email, role=Role.MEMBER.value)


@router.post("/auth/refresh", response_model=TokenOut)
async def refresh(payload: RefreshIn, response: Response, db: Session = Depends(get_db)):
    """Rotate a refresh token into a fresh access+refresh pair (TA1-1).

    Rotation policy (single-use refresh tokens, reuse detection):

    - A refresh token is bound to the same ``auth_sessions`` row (jti) as
      its access token, so ``/auth/logout``, ``/auth/logout-all`` and
      account deletion revoke it too — a logged-out refresh token is dead.
    - Each successful refresh ROTATES the row: the old refresh token becomes
      single-use (revoked-with-rotated) and a successor row is minted with a
      fresh jti, chained to the same rotation ``family_id``.
    - REPLAY (reuse of an already-rotated refresh token) is treated as token
      theft: the ENTIRE family is revoked — every successor row, hence every
      access and refresh token minted from that login — and the request is
      answered 401.
    - Expired / malformed / revoked-but-not-rotated tokens get a plain 401
      with no family action.

    Response shape: the same ``TokenOut`` as ``/auth/login`` (a NEW endpoint
    defining its own shape, deliberately mirroring login's).
    """
    from jose import JWTError, jwt

    from dependencies import ALGORITHM, _get_secret

    try:
        claims = jwt.decode(payload.refresh_token, _get_secret(), algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid refresh token") from None
    if claims.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    jti = claims.get("jti")
    user_id = claims.get("sub")
    if not jti or not user_id:
        # Pre-TA1-1 stateless refresh tokens (and forgeries) carry no jti.
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    rotated = rotate_session(db, jti, user_id)
    if rotated is None:
        # Unknown/expired/revoked row, or a subject mismatch (cross-user
        # token): fail closed with the same 401, no state change.
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    access_token, refresh_token, replayed = rotated
    if replayed:
        # Reuse of an already-rotated token: family already revoked above.
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    _set_session_cookie(response, access_token)
    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        user=AuthUser(id=user.id, name=user.display_name, email=user.email, role=Role.MEMBER.value),
    )


@router.post("/auth/logout")
async def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """Revoke the current session (jti blocklist) and clear the cookie."""
    token = _token_from_request(request)
    if token:
        payload = _decode_token(token)
        # _decode_token returns None once revoked; decode raw to still allow
        # idempotent logout on an already-dead token.
        if payload is None:
            from jose import JWTError, jwt

            from dependencies import ALGORITHM, _get_secret

            try:
                payload = jwt.decode(token, _get_secret(), algorithms=[ALGORITHM])
            except JWTError:
                payload = None
        if payload and payload.get("jti"):
            revoke_session(db, payload["jti"])
            db.commit()
    _clear_session_cookie(response)
    return {"ok": True}


@router.post("/auth/logout-all")
async def logout_all(
    response: Response,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Sign out everywhere: revoke every active session for the current user."""
    revoked = revoke_all_sessions(db, current_user["id"])
    db.commit()
    _clear_session_cookie(response)
    return {"ok": True, "revoked": revoked}
