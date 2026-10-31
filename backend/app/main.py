from __future__ import annotations

import hmac
import logging
import uuid

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import get_settings
from .db import get_db
from .deps import Principal, optional_principal
from .routers import auth, candidate, hr_jobs, hr_ops, supervisor
from .security import CSRF_COOKIE, CSRF_HEADER, SESSION_COOKIE, lookup_session
from .services import llm

log = logging.getLogger("talent")
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


class BodyLimitMiddleware:
    """Rejects oversized request bodies while they are being received (before multipart parsing)."""

    def __init__(self, app: ASGIApp, default_limit: int = 256 * 1024):
        self.app = app
        self.default_limit = default_limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path: str = scope["path"]
        cap = self.default_limit
        if path.endswith("/applications") or path.endswith("/resume"):
            cap = get_settings().max_upload_bytes + 64 * 1024  # multipart overhead
        headers = dict(scope.get("headers") or [])
        cl = headers.get(b"content-length")
        if cl is not None and cl.isdigit() and int(cl) > cap:
            return await _reject(send, 413, "Request body too large")
        received = 0

        async def limited_receive():
            nonlocal received
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > cap:
                    raise _TooLarge()
            return msg

        try:
            await self.app(scope, limited_receive, send)
        except _TooLarge:
            await _reject(send, 413, "Request body too large")


class _TooLarge(Exception):
    pass


async def _reject(send: Send, status: int, msg: str):
    import json

    body = json.dumps({"detail": msg}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=f"{s.product_name} API", version="0.1.0",
                  description="Human-approved AI screening and scheduling prototype. Fictional hackathon data only.")

    @app.middleware("http")
    async def csrf_and_headers(request: Request, call_next):
        cid = uuid.uuid4().hex[:16]
        request.state.correlation_id = cid
        if request.method in MUTATING and request.url.path.startswith("/api/"):
            header = request.headers.get(CSRF_HEADER, "")
            cookie = request.cookies.get(CSRF_COOKIE, "")
            if not header or not cookie or not hmac.compare_digest(header, cookie):
                return JSONResponse({"detail": "CSRF check failed - reload the page and try again"}, status_code=403)
            token = request.cookies.get(SESSION_COOKIE)
            if token:
                from .db import SessionLocal

                db = SessionLocal()
                try:
                    sess = lookup_session(db, token)
                    if sess is not None and not hmac.compare_digest(sess.csrf_token, header):
                        return JSONResponse({"detail": "CSRF token does not match the session"}, status_code=403)
                finally:
                    db.close()
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        response.headers["X-Correlation-Id"] = cid
        return response

    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=[s.public_app_url.rstrip("/")], allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
                       allow_headers=["content-type", CSRF_HEADER])

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        errs = [{"loc": [str(x) for x in e.get("loc", [])], "msg": e.get("msg")} for e in exc.errors()[:10]]
        return JSONResponse({"detail": "Invalid request", "errors": errs}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error cid=%s", getattr(request.state, "correlation_id", "-"))
        return JSONResponse({"detail": "Internal error", "correlation_id": getattr(request.state, "correlation_id", None)},
                            status_code=500)

    for r in (auth.router, candidate.router, hr_jobs.router, hr_ops.router, supervisor.router):
        app.include_router(r)

    @app.get("/api/system/status", tags=["system"])
    def status(p: Principal | None = Depends(optional_principal), db: Session = Depends(get_db)):
        mode = llm.current_mode(db)
        out = {
            "product_name": s.product_name,
            "company_name": s.company_name,
            "fictional_data": True,
            "demo_mode": s.demo_mode,
            "ai_mode": mode,
            "timezone": s.company_timezone,
            "max_upload_mb": s.max_upload_bytes // (1024 * 1024),
            "max_pdf_pages": s.max_pdf_pages,
            "email_verification": False,
        }
        if p is not None and p.role in ("recruiter", "supervisor"):
            out.update({
                "live_configured": s.live_ai_configured,
                "model_id": s.gemini_model if mode == "live" else "replay-synthetic-v1",
                "mailpit_url": s.mailpit_ui_url,
                "preflight": s.preflight(),
                "live_calls_today": llm.live_calls_today(db),
                "daily_budget": s.ai_daily_call_budget,
                "ai_rpm": s.ai_rpm,
            })
        return out

    @app.get("/api/health", tags=["system"])
    def health():
        return {"ok": True}

    return app


app = create_app()
