from django.core.management.base import BaseCommand

from portal.guest import purge_expired_guest_drafts


class Command(BaseCommand):
    help = "Elimina borradores temporales vencidos que ya no tienen análisis en curso."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100,
                            help="Cantidad máxima de borradores vencidos por ejecución (predeterminado: 100).")

    def handle(self, *args, **options):
        outcome = purge_expired_guest_drafts(limit=options["limit"])
        self.stdout.write(
            "Borradores temporales: {purged} eliminados, {deferred} diferidos, {skipped} preservados.".format(**outcome)
        )
