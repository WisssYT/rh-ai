"""One free web instance: built frontend, API, worker and a private local SMTP inbox.

Postgres and the optional durable PDF bytes live outside this ephemeral container.
Any child failure stops the instance so the hosting platform can restart it.
"""
from __future__ import annotations

import json
import os
from email.message import EmailMessage
from email.utils import format_datetime
import signal
import subprocess
import sys
import time
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

children: list[subprocess.Popen] = []
stopping = False


def stop(signum=None, frame=None):
    global stopping
    stopping = True
    for child in reversed(children):
        if child.poll() is None:
            child.terminate()


def launch(args):
    child = subprocess.Popen(args)
    children.append(child)
    return child


def wait_for(url: str, timeout: int = 90):
    deadline = time.monotonic() + timeout
    while not stopping and time.monotonic() < deadline:
        if any(p.poll() is not None for p in children):
            raise RuntimeError("A service exited during startup")
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.5)
    raise RuntimeError("A service did not become ready")


def restore_demo_inbox():
    """Reconstruct the local preview inbox from already-sent, approved payloads.

    No external SMTP connection is used and no approval/outbox state is changed.
    """
    from sqlalchemy import select
    from app.db import session_scope
    from app.models import Outbox

    with urllib.request.urlopen("http://127.0.0.1:8025/mailbox/api/v1/messages", timeout=5) as response:
        if json.load(response).get("messages_count", 0):
            return
    with tempfile.TemporaryDirectory(prefix="restored-mail-") as directory:
        count = 0
        with session_scope() as db:
            for record in db.scalars(select(Outbox).where(Outbox.status == "sent")):
                msg = EmailMessage()
                payload = record.payload
                msg["From"], msg["To"], msg["Subject"] = payload["from"], payload["to"], payload["subject"]
                if record.message_id:
                    msg["Message-ID"] = record.message_id
                if record.sent_at:
                    msg["Date"] = format_datetime(record.sent_at)
                msg["X-Demo-Restored"] = "true"
                msg.set_content(payload["body"])
                Path(directory, f"{record.id}.eml").write_bytes(msg.as_bytes())
                count += 1
        if count:
            subprocess.run(["mailpit", "ingest", "--smtp-addr", "127.0.0.1:1025", directory],
                           check=True, capture_output=True)
        print(f"Restored {count} historical messages into the local preview inbox.", flush=True)


def main():
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    os.chdir("/app")
    sys.path.insert(0, "/app")
    public = os.environ.get("RENDER_EXTERNAL_URL") or os.environ.get("PUBLIC_APP_URL", "")
    if not public.startswith("https://"):
        raise RuntimeError("Set PUBLIC_APP_URL to the HTTPS deployment URL")
    if not os.environ.get("DATABASE_URL") or not os.environ.get("SESSION_SECRET"):
        raise RuntimeError("DATABASE_URL and SESSION_SECRET must be configured")
    if len(os.environ["SESSION_SECRET"]) < 32:
        raise RuntimeError("SESSION_SECRET must contain at least 32 random characters")
    db_url = os.environ["DATABASE_URL"]
    for prefix in ("postgres://", "postgresql://"):
        if db_url.startswith(prefix):
            os.environ["DATABASE_URL"] = "postgresql+psycopg://" + db_url[len(prefix):]
            break
    os.environ.update({
        "PUBLIC_APP_URL": public.rstrip("/"),
        "COOKIE_SECURE": "true",
        "DATABASE_FILE_STORAGE": "true",
        "UPLOAD_DIR": "/app/var/uploads",
        "SMTP_HOST": "127.0.0.1",
        "SMTP_PORT": "1025",
        "ALLOW_EXTERNAL_EMAIL": "false",
        "MAILPIT_UI_URL": public.rstrip("/") + "/mailbox/",
        "SITE_ADDRESS": ":" + os.environ.get("PORT", "10000"),
        "API_UPSTREAM": "127.0.0.1:8000",
        "MAILPIT_UPSTREAM": "127.0.0.1:8025",
    })
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    launch(["mailpit", "--smtp", "127.0.0.1:1025", "--listen", "127.0.0.1:8025",
            "--webroot", "/mailbox/", "--database", "/app/var/mail/mailpit.db",
            "--disable-version-check", "--block-remote-css-and-fonts", "--ignore-duplicate-ids", "--use-message-dates"])
    wait_for("http://127.0.0.1:8025/mailbox/")
    restore_demo_inbox()
    launch([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000",
            "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"])
    wait_for("http://127.0.0.1:8000/api/system/status")
    launch([sys.executable, "-m", "app.worker"])
    launch(["caddy", "run", "--config", "/app/deploy/Caddyfile", "--adapter", "caddyfile"])
    wait_for("http://127.0.0.1:" + os.environ.get("PORT", "10000") + "/api/health")
    print(json.dumps({"status": "ready", "public_url": public, "storage": "postgres"}), flush=True)
    while not stopping:
        for child in children:
            code = child.poll()
            if code is not None:
                raise RuntimeError(f"A service stopped unexpectedly (exit {code})")
        time.sleep(1)


if __name__ == "__main__":
    result = 0
    try:
        main()
    except Exception as exc:
        # Exceptions contain service names/statuses, never configuration values.
        print(f"Cloud startup failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        result = 1
    finally:
        stop()
        deadline = time.monotonic() + 65
        for child in children:
            try:
                child.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                child.kill()
    sys.exit(result)
