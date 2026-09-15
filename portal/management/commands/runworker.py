import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from portal.processing import process_next_job, process_notifications


class Command(BaseCommand):
    help = "Procesa la cola persistente de análisis y notificaciones."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Procesar un análisis y un lote de avisos, luego salir.")
        parser.add_argument("--poll", type=float, default=3, help="Segundos entre sondeos (mínimo 1).")

    def handle(self, *args, **options):
        self.stopping = False

        def stop(signum, frame):
            self.stopping = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        self.stdout.write("Worker IMC iniciado; cola persistente en base de datos.")
        while not self.stopping:
            close_old_connections()
            try:
                processed = process_next_job()
                delivered = process_notifications()
                if options["once"]:
                    self.stdout.write(f"Análisis procesado: {int(processed)}. Avisos entregados: {delivered}.")
                    break
            except Exception as exc:
                # Never print provider response or configuration values.
                self.stderr.write(f"Worker: error operativo ({type(exc).__name__}); se reintentará.")
                if options["once"]:
                    raise SystemExit(1)
            finally:
                close_old_connections()
            time.sleep(max(1, options["poll"]))
