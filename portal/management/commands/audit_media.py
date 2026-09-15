"""Conservative local media inventory and explicit cleanup of old unreferenced files."""
import json
import os
from pathlib import Path
import stat
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from portal.models import Asset
from portal.storage import PrivateStorage, option


def checked_root():
    root = Path(settings.MEDIA_ROOT)
    if not root.is_absolute() or ".." in root.parts or root == Path(root.anchor):
        raise CommandError("MEDIA_ROOT debe ser un directorio absoluto específico, sin traversal.")
    if root.resolve() != root or root.is_symlink() or not root.is_dir():
        raise CommandError("MEDIA_ROOT debe existir y no puede atravesar enlaces simbólicos.")
    return root


def regular_files(root, report):
    """scandir never descends into symlinks, junctions or any Windows reparse point."""
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError:
            report["unreadable_entries"] += 1
            continue
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
                if entry.is_symlink() or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
                    report["skipped_links"] += 1
                    continue
                path = Path(entry.path)
                if not path.resolve().is_relative_to(root):
                    report["skipped_links"] += 1
                    continue
                if stat.S_ISDIR(info.st_mode):
                    pending.append(path)
                elif stat.S_ISREG(info.st_mode):
                    # DirEntry.stat on Windows reports zero inode/device; lstat
                    # supplies the identity used for the later replacement check.
                    current = safe_current_file(path, root)
                    if current:
                        yield path, current
            except OSError:
                report["unreadable_entries"] += 1


def safe_current_file(path, root):
    """Recheck every ancestor immediately before an explicitly requested unlink."""
    relative = path.relative_to(root)
    current = root
    for part in relative.parts:
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024):
            return None
    if not path.resolve().is_relative_to(root) or not stat.S_ISREG(info.st_mode):
        return None
    return info


class Command(BaseCommand):
    help = "Audita medios sin modificar nada. --apply elimina sólo archivos locales sin referencia y con antigüedad mínima de 7 días."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--older-than", type=int, default=7, metavar="DAYS")

    def handle(self, *args, **options):
        if options["older_than"] < 7:
            raise CommandError("La antigüedad mínima es de 7 días.")
        report = {"mode": "apply" if options["apply"] else "report_only", "older_than_days": options["older_than"],
                  "storage": "s3" if option("PRIVATE_S3_BUCKET", "") else "local",
                  "referenced_files": 0, "missing_referenced_files": 0, "unreferenced_files": 0,
                  "eligible_old_files": 0, "eligible_bytes": 0, "deleted_files": 0,
                  "skipped_links": 0, "unreadable_entries": 0, "changed_or_referenced_again": 0}
        # Every Asset is retained, including those belonging to historical versions.
        references = {str(name).replace("\\", "/") for row in Asset.objects.values_list("original", "preview") for name in row if name}
        report["referenced_files"] = len(references)
        found = set()
        cutoff = time.time() - options["older_than"] * 86400
        if report["storage"] == "s3":
            if options["apply"]:
                raise CommandError("La eliminación no está implementada para S3; ejecuta el inventario sin --apply.")
            storage = PrivateStorage()
            try:
                for page in storage.client().get_paginator("list_objects_v2").paginate(Bucket=storage.bucket):
                    for item in page.get("Contents", []):
                        name = item["Key"]
                        if name.endswith("/"):
                            continue
                        if name in references:
                            found.add(name)
                        else:
                            report["unreferenced_files"] += 1
                            if item["LastModified"].timestamp() <= cutoff:
                                report["eligible_old_files"] += 1
                                report["eligible_bytes"] += item["Size"]
            except Exception:
                raise CommandError("No se pudo completar el inventario privado S3.") from None
            report["missing_referenced_files"] = len(references - found)
            report["result"] = "Inventario S3 de solo lectura terminado; no se eliminaron objetos."
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
            return
        root = checked_root()
        for path, observed in regular_files(root, report):
            name = path.relative_to(root).as_posix()
            if name in references:
                found.add(name)
                continue
            report["unreferenced_files"] += 1
            if observed.st_mtime > cutoff:
                continue
            report["eligible_old_files"] += 1
            report["eligible_bytes"] += observed.st_size
            if not options["apply"]:
                continue
            try:
                current = safe_current_file(path, root)
                if (not current or (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) !=
                        (observed.st_dev, observed.st_ino, observed.st_size, observed.st_mtime_ns) or
                        Asset.objects.filter(Q(original=name) | Q(preview=name)).exists()):
                    report["changed_or_referenced_again"] += 1
                    continue
                path.unlink()
                report["deleted_files"] += 1
            except OSError:
                report["unreadable_entries"] += 1
        report["missing_referenced_files"] = len(references - found)
        report["result"] = "Inventario terminado. No se modificaron registros, versiones ni directorios."
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
