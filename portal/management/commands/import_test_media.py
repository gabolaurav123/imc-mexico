"""Import an operator-transferred bundle solely into existing is_test assets."""
import hashlib
import io
import json
from pathlib import PurePosixPath
import tarfile

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from portal.models import Asset
from portal.storage import PrivateStorage
from .backup_private import hash_stream


class Command(BaseCommand):
    help = "Importa medios de ensayo existentes y verificados, sin crear registros ni reemplazar archivos."

    def add_arguments(self, parser):
        parser.add_argument("archive")

    def handle(self, *args, **options):
        storage = PrivateStorage()
        allowed = {str(name) for row in Asset.objects.filter(machine__owner__is_test=True).values_list("original", "preview")
                   for name in row if name}
        prepared = []
        try:
            with tarfile.open(options["archive"], "r:gz") as archive:
                members = archive.getmembers()
                names = [m.name for m in members]
                if len(names) != len(set(names)) or len(members) > 201:
                    raise CommandError("El paquete de ensayo no es válido.")
                for member in members:
                    if not member.isfile() or member.name.startswith("/") or ".." in PurePosixPath(member.name).parts or "\\" in member.name:
                        raise CommandError("El paquete contiene una ruta no permitida.")
                manifest_info = archive.getmember("manifest.json")
                if manifest_info.size > 1024 * 1024:
                    raise CommandError("El manifiesto de ensayo es demasiado grande.")
                manifest = json.load(archive.extractfile(manifest_info))
                if manifest.get("purpose") != "imc-synthetic-test-media-v1":
                    raise CommandError("El archivo no es un paquete de medios de ensayo.")
                entries = manifest["files"]
                if set(names) != {"manifest.json", *(entry["path"] for entry in entries)}:
                    raise CommandError("Los archivos no coinciden con el manifiesto.")
                if sum(archive.getmember(e["path"]).size for e in entries) > 100 * 1024 * 1024:
                    raise CommandError("El paquete excede 100 MB de medios de ensayo.")
                for entry in entries:
                    key = storage.safe_name(entry["path"])
                    if key not in allowed:
                        raise CommandError("Un archivo no pertenece a un registro de ensayo existente.")
                    with archive.extractfile(key) as source:
                        raw = source.read()
                    if len(raw) != entry["size"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                        raise CommandError("El paquete de ensayo no superó la verificación de integridad.")
                    if storage.exists(key):
                        with storage.open(key, "rb") as existing:
                            digest, size = hash_stream(existing)
                        if digest != entry["sha256"] or size != entry["size"]:
                            raise CommandError("Ya existe un archivo diferente. No se reemplazó ningún medio.")
                    else:
                        prepared.append((key, raw))
            for key, raw in prepared:
                # Recheck immediately before save. Storage.save must not rename a
                # referenced path; fail if a concurrent writer created it.
                if storage.exists(key):
                    raise CommandError("Los medios cambiaron durante la importación. Repite la verificación.")
                saved = storage.save(key, ContentFile(raw))
                if saved != key:
                    storage.delete(saved)
                    raise CommandError("El almacenamiento cambió la ruta. No se reemplazó el archivo existente.")
            self.stdout.write(self.style.SUCCESS(f"Medios de ensayo verificados: {len(entries)}. Archivos nuevos: {len(prepared)}."))
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"No se pudo importar el paquete de ensayo ({type(exc).__name__}).") from None
