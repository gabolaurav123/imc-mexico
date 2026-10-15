import os
import math
import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections, connections

from portal.processing import process_next_job, process_notifications
from portal.access_tracking import purge_expired_accesses
from portal.guest import purge_expired_guest_drafts
from portal.worker_wake import WorkerWake


def _seconds(value, environment, default, *, minimum, maximum=None):
    """Read a bounded worker timing option without making a bad env fatal."""
    if value is None:
        value = os.getenv(environment, default)
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = float(default)
    if not math.isfinite(parsed):
        parsed = float(default)
    parsed = max(minimum, parsed)
    return min(parsed, maximum) if maximum is not None else parsed


class Command(BaseCommand):
    help = "Procesa la cola persistente de análisis y notificaciones."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Procesar un análisis y un lote de avisos, luego salir.")
        parser.add_argument("--poll", type=float, default=None,
                            help="Base del sondeo de respaldo (compatibilidad; predeterminado 3 segundos).")
        parser.add_argument("--idle-backoff-max", type=float, default=None,
                            help="Máximo del sondeo de respaldo cuando no hay trabajo (predeterminado 900 segundos).")
        parser.add_argument("--wake-check", type=float, default=None,
                            help="Frecuencia de lectura de la señal local mientras está inactivo (máximo 1 segundo).")
        parser.add_argument("--retry-poll-max", type=float, default=None,
                            help="Sondeo máximo durante una ventana local de reintentos (predeterminado 15 segundos).")

    def handle(self, *args, **options):
        self.stopping = False
        next_access_cleanup = 0
        next_guest_cleanup = 0
        base_poll = _seconds(options["poll"], "WORKER_IDLE_BACKOFF_INITIAL", 3, minimum=1)
        max_poll = _seconds(options["idle_backoff_max"], "WORKER_IDLE_BACKOFF_MAX", 900, minimum=base_poll)
        wake_check = _seconds(options["wake_check"], "WORKER_WAKE_CHECK_SECONDS", 0.5, minimum=0.05, maximum=1)
        retry_poll_max = _seconds(options["retry_poll_max"], "WORKER_RETRY_POLL_MAX", 15,
                                  minimum=base_poll)
        idle_poll = base_poll
        retry_fast_until = 0
        wake = WorkerWake()

        def stop(signum, frame):
            self.stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        self.stdout.write("Worker IMC iniciado; cola persistente en base de datos.")
        while not self.stopping:
            # Capture this before querying. A commit after it will change the
            # token, including one racing the no-work decision below.
            wake_token = wake.token()
            processed = False
            accepted = 0
            close_old_connections()
            try:
                processed = process_next_job()
                accepted = process_notifications()
                if time.monotonic() >= next_access_cleanup:
                    purge_expired_accesses()
                    next_access_cleanup = time.monotonic() + 3600
                if time.monotonic() >= next_guest_cleanup:
                    purge_expired_guest_drafts()
                    next_guest_cleanup = time.monotonic() + 3600
            except Exception as exc:
                # Never print provider response or configuration values.
                self.stderr.write(f"Worker: error operativo ({type(exc).__name__}); se reintentará.")
                if options["once"]:
                    raise SystemExit(1)
            finally:
                # conn_max_age is normally zero, but close explicitly before
                # an idle wait so Neon has no worker-held client connection.
                connections.close_all()
            if options["once"]:
                self.stdout.write(f"Análisis procesado: {int(processed)}. Avisos aceptados por backend: {accepted}.")
                break
            if processed or accepted:
                idle_poll = base_poll
                # An analysis retry may next be eligible in 30--300 seconds.
                # Keep its recovery prompt without permanently polling an idle
                # database after ordinary completed work.
                if processed:
                    retry_fast_until = time.monotonic() + 300
                continue
            # Check once more before sleeping so a commit between the query and
            # this decision is not hidden behind the fallback backoff.
            if wake.token() != wake_token:
                idle_poll = base_poll
                continue
            if wake.wait_for_change(wake_token, idle_poll, check_interval=wake_check,
                                    stopping=lambda: self.stopping):
                idle_poll = base_poll
            else:
                active_limit = retry_poll_max if time.monotonic() < retry_fast_until else max_poll
                idle_poll = min(active_limit, idle_poll * 2)
