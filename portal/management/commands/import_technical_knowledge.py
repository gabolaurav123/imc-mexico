"""Import locally reviewed technical-reference JSON; never performs network I/O."""
from datetime import date
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from portal.models import Category, TechnicalReference


class Command(BaseCommand):
    help = "Importa JSON local como referencias pendientes; no descarga ni activa datos sin revisión."

    def add_arguments(self, parser):
        parser.add_argument("--path", default="knowledge/excavadoras", help="Archivo JSON o directorio local")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--deactivate-missing", action="store_true",
                            help="Desactiva sólo referencias de las categorías presentes que no estén en el archivo.")

    def _documents(self, path):
        files = [path] if path.is_file() else sorted(path.glob("*.json")) if path.is_dir() else []
        if not files:
            raise CommandError("No se encontraron archivos JSON de conocimiento local.")
        for file in files:
            try:
                content = json.loads(file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CommandError(f"{file}: JSON inválido: {exc}") from exc
            records = content.get("references", content) if isinstance(content, dict) else content
            if not isinstance(records, list):
                raise CommandError(f"{file}: se espera una lista de referencias.")
            yield from records

    @transaction.atomic
    def handle(self, *args, **options):
        path = Path(options["path"]).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        records = list(self._documents(path))
        seen, categories, created, updated = set(), set(), 0, 0
        for item in records:
            if not isinstance(item, dict):
                raise CommandError("Cada referencia debe ser un objeto JSON.")
            slug = item.get("category_slug")
            category = Category.objects.filter(slug=slug).first()
            if category is None:
                raise CommandError(f"Categoría inexistente: {slug!r}. Ejecuta seed antes de importar.")
            required = ("brand", "model", "source", "source_title", "retrieved_at")
            if any(not item.get(key) for key in required):
                raise CommandError(f"{slug}: faltan campos obligatorios: {', '.join(required)}.")
            try:
                retrieved_at = date.fromisoformat(str(item["retrieved_at"]))
            except ValueError as exc:
                raise CommandError(f"{slug}: retrieved_at debe usar AAAA-MM-DD.") from exc
            lookup = {"category": category, "brand": str(item["brand"]).strip(), "model": str(item["model"]).strip(),
                      "variant": str(item.get("variant", "")).strip(), "generation": str(item.get("generation", "")).strip(),
                      "market": str(item.get("market", "")).strip(), "source": item["source"]}
            values = {"period_from": item.get("period_from"), "period_to": item.get("period_to"),
                      "specs": item.get("specs", {}), "provenance": item.get("provenance", {}),
                      "source_title": item["source_title"], "source_version": item.get("source_version", ""),
                      "retrieved_at": retrieved_at}
            reference, is_created = TechnicalReference.objects.get_or_create(**lookup, defaults=values)
            if is_created:
                created += 1
            else:
                # Imports never bypass human review. A changed source is placed
                # back in pending state and disabled for retrieval.
                changed = any(getattr(reference, key) != value for key, value in values.items())
                if changed:
                    for key, value in values.items():
                        setattr(reference, key, value)
                    reference.review = TechnicalReference.Review.PENDING
                    reference.active = False
                    reference.reviewed_by = None
                    reference.reviewed_at = None
                    reference.full_clean()
                    reference.save()
                    updated += 1
            seen.add((category.pk, lookup["brand"], lookup["model"], lookup["variant"], lookup["generation"], lookup["market"], lookup["source"]))
            categories.add(category.pk)
        if options["deactivate_missing"]:
            for reference in TechnicalReference.objects.filter(category_id__in=categories, active=True):
                identity = (reference.category_id, reference.brand, reference.model, reference.variant,
                            reference.generation, reference.market, reference.source)
                if identity not in seen:
                    reference.active = False
                    reference.save(update_fields=["active", "updated_at"])
        if options["dry_run"]:
            transaction.set_rollback(True)
        self.stdout.write(self.style.SUCCESS(f"Conocimiento local: {created} creadas, {updated} actualizadas; todas requieren revisión antes de activarse."))
