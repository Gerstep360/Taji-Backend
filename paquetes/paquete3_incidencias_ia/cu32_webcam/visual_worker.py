"""Bucle compartido por runserver local y systemd en producción."""
import logging
from threading import Thread
from time import monotonic, sleep

from django.db import DatabaseError, close_old_connections
from django.utils import timezone

from .visual_jobs import claim, expire, process, purge

logger = logging.getLogger(__name__)
_worker = None


def run_worker(*, once=False):
    last_purge = None
    last_cleanup = None
    waiting_db = False
    while True:
        close_old_connections()
        now, tick = timezone.now(), monotonic()
        try:
            if last_cleanup is None or tick - last_cleanup >= 10:
                expire(now)
                last_cleanup = tick
            if last_purge is None or tick - last_purge >= 3600:
                purge(now)
                last_purge = tick
            job = claim(now)
            if job:
                process(*job)
            waiting_db = False
        except DatabaseError:
            close_old_connections()
            if once:
                raise
            if not waiting_db:
                logger.warning('El trabajador visual espera la base y sus migraciones.')
            waiting_db = True
            job = None
        if once:
            return
        if not job:
            sleep(2)


def start_development_worker():
    global _worker
    if _worker is None or not _worker.is_alive():
        _worker = Thread(target=run_worker, name='taji-visual-vision', daemon=True)
        _worker.start()
