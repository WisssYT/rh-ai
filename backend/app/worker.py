"""Durable worker: leased analysis tasks, outbox dispatch, hold expiry. Run: python -m app.worker"""

from __future__ import annotations

import logging
import os
import signal
import socket
import time
from concurrent.futures import ThreadPoolExecutor

from .config import get_settings
from .db import session_scope
from .services import analysis, booking, email

log = logging.getLogger("talent.worker")
_stop = False


def _handle(sig, frame):  # noqa: ARG001
    global _stop
    _stop = True


def tick(owner: str, pool: ThreadPoolExecutor | None = None) -> int:
    work = 0
    with session_scope() as db:
        analysis.recover_expired_leases(db)
    with session_scope() as db:
        email.recover_outbox(db)
    with session_scope() as db:
        work += booking.expire_holds(db)
    with session_scope() as db:
        ids = analysis.claim_tasks(db, owner, get_settings().ai_concurrency)

    def run(tid: str):
        try:
            with session_scope() as db:
                analysis.process_task(db, tid)
        except Exception:  # noqa: BLE001 - lease recovery will retry
            log.exception("task %s crashed; lease will expire and the task will be retried", tid)

    if ids:
        work += len(ids)
        if pool is not None and len(ids) > 1:
            list(pool.map(run, ids))
        else:
            for tid in ids:
                run(tid)
    for _ in range(20):
        with session_scope() as db:
            n = email.dispatch_once(db)
        if not n:
            break
        work += n
    return work


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    signal.signal(signal.SIGTERM, _handle)
    signal.signal(signal.SIGINT, _handle)
    s = get_settings()
    owner = f"{socket.gethostname()}:{os.getpid()}"
    for note in s.preflight():
        log.warning("preflight: %s", note)
    log.info("worker %s started (concurrency=%s, rpm=%s, daily budget=%s)", owner, s.ai_concurrency, s.ai_rpm,
             s.ai_daily_call_budget)
    with ThreadPoolExecutor(max_workers=s.ai_concurrency) as pool:
        while not _stop:
            try:
                did = tick(owner, pool)
            except Exception:  # noqa: BLE001
                log.exception("worker tick failed")
                did = 0
            time.sleep(0.2 if did else 1.0)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
