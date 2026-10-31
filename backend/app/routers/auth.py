from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..deps import Principal, audit, current_principal, limit, optional_principal
from ..models import User, utcnow
from ..security import CSRF_COOKIE, SESSION_COOKIE, create_session, hash_password, verify_password
from ..services.text_tools import is_safe_email

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterIn(BaseModel):
    # extra="forbid": a request cannot smuggle in role/is_active/etc.
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=10, max_length=200)
    fictional_data_ack: bool


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)
    portal: str = Field(default="candidate", pattern="^(candidate|staff)$")


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role}


def _set_cookies(response: Response, token: str, csrf: str) -> None:
    s = get_settings()
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=s.secure_cookies, samesite="lax",
                        max_age=s.session_ttl_hours * 3600, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=s.secure_cookies, samesite="strict",
                        max_age=s.session_ttl_hours * 3600, path="/")


@router.get("/csrf")
def csrf(request: Request, response: Response, p: Principal | None = Depends(optional_principal)):
    """Issue the double-submit CSRF token used for unauthenticated mutations (login/register)."""
    token = p.session.csrf_token if p else (request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(24))
    s = get_settings()
    response.set_cookie(CSRF_COOKIE, token, httponly=False, secure=s.secure_cookies, samesite="strict", path="/")
    return {"csrf_token": token}


@router.post("/register", status_code=201)
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    limit(request, "register", 5, 3600)
    if not body.fictional_data_ack:
        raise HTTPException(422, "Please confirm you are using fictional demo data only")
    email = body.email.strip().lower()
    if not is_safe_email(email):
        raise HTTPException(422, "Invalid email address")
    s = get_settings()
    if s.demo_mode and not email.rsplit("@", 1)[-1].endswith((".test", ".example", ".invalid")):
        raise HTTPException(422, "Demo mode: use a fictional address on a reserved domain such as name@example.test")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with this email already exists")
    user = User(email=email, full_name=body.full_name.strip(), role="candidate",
                password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    token, sess = create_session(db, user)
    audit(db, user, "account.registered", "user", user.id)
    db.commit()
    _set_cookies(response, token, sess.csrf_token)
    return {"user": user_out(user), "csrf_token": sess.csrf_token, "email_verified": False}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    limit(request, "login", 10, 300)
    limit(request, "login-acct", 8, 300, key_extra=body.email.lower())
    if not is_safe_email(body.email.strip().lower()):
        raise HTTPException(401, "Invalid email or password")
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    ok = verify_password(user.password_hash if user else None, body.password)
    if not ok or user is None or not user.is_active:
        audit(db, None, "auth.login_failed", "user", user.id if user else None, outcome="denied")
        db.commit()
        raise HTTPException(401, "Invalid email or password")
    if get_settings().app_env == "production" and user.is_demo_fixture:
        raise HTTPException(403, "Seeded demo credentials are disabled in production mode")
    if body.portal == "staff" and user.role == "candidate":
        raise HTTPException(403, "Use the candidate login for candidate accounts")
    if body.portal == "candidate" and user.role != "candidate":
        raise HTTPException(403, "Staff accounts sign in through the HR portal")
    token, sess = create_session(db, user)
    audit(db, user, "auth.login", "user", user.id)
    db.commit()
    _set_cookies(response, token, sess.csrf_token)
    return {"user": user_out(user), "csrf_token": sess.csrf_token}


@router.post("/logout")
def logout(response: Response, p: Principal = Depends(current_principal), db: Session = Depends(get_db)):
    p.session.revoked_at = utcnow()
    db.add(p.session)
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(p: Principal | None = Depends(optional_principal)):
    if p is None:
        return {"user": None}
    return {"user": user_out(p.user), "csrf_token": p.session.csrf_token}
