"""Auth endpoints: register, login, me, logout."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

import models
from authorization import Role
from database import get_db
from dependencies import (
    AuthUser,
    _clear_session_cookie,
    _decode_token,
    _set_session_cookie,
    _token_from_request,
    create_access_token,
    create_refresh_token,
    get_password_hash,
    verify_password,
)

router = APIRouter()


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: AuthUser


@router.post("/auth/register", response_model=TokenOut, status_code=201)
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

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
    _set_session_cookie(response, access_token)

    return TokenOut(
        access_token=access_token,
        refresh_token=refresh_token,
        user=AuthUser(id=user.id, name=user.display_name, email=user.email, role=Role.MEMBER.value),
    )


@router.post("/auth/login", response_model=TokenOut)
async def login(payload: LoginIn, response: Response, db: Session = Depends(get_db)):
    """Authenticate a user and return a JWT session."""
    user = db.query(models.User).filter(models.User.email == payload.email).first()
    if not user or not user.hashed_password:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)
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


@router.post("/auth/logout")
async def logout(response: Response):
    """Clear the session cookie."""
    _clear_session_cookie(response)
    return {"ok": True}
