#!/usr/bin/env python3
"""Read-only recovery inventory for private IMC backup volumes.

The script deliberately does not load ``.env``, Django, or a database connection.
It prints only aggregate filesystem data and safe backup metadata; paths, archive
member names, credentials, and file contents never enter its JSON output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from typing import Any


ARCHIVE_NAME = re.compile(r"imc-private-\d{8}T\d{6}Z-[0-9a-f]{6}\.tar\.gz\Z")
MAX_MANIFEST_BYTES = 20 * 1024 * 1024
MAX_STATUS_BYTES = 8 * 1024


def utc_timestamp(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat().replace("+00:00", "Z")


def regular_file(path: Path) -> os.stat_result | None:
    """Return lstat data only for a non-symlink regular file."""
    try:
        info = path.lstat()
    except OSError:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return None
    return info


def sha256_stream(stream: Any) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def safe_member_name(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return bool(name) and not name.startswith("/") and ".." not in parts and "\\" not in name and ":" not in name


def manifest_summary(manifest: Any) -> dict[str, Any] | None:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return None
    database = manifest.get("database")
    media = manifest.get("media")
    counts = manifest.get("table_counts")
    if not isinstance(database, dict) or not isinstance(media, list) or not isinstance(counts, dict):
        return None
    entries = [database, *media]
    if not all(isinstance(entry, dict) and isinstance(entry.get("path"), str)
               and isinstance(entry.get("sha256"), str) and isinstance(entry.get("size"), int)
               and entry["size"] >= 0 for entry in entries):
        return None
    if not all(isinstance(value, int) and value >= 0 for value in counts.values()):
        return None
    created_at = manifest.get("created_at")
    return {
        "created_at": created_at if isinstance(created_at, str) else None,
        # Do not disclose table names.  The aggregate still lets recovery staff
        # compare the archive's database scope with a restored target.
        "table_counts": {"tables": len(counts), "rows_total": sum(counts.values())},
        "media_count": len(media),
        "database_bytes": database["size"],
    }


def inspect_archive(path: Path) -> dict[str, Any]:
    """Validate an archive byte-for-byte without extracting it.

    Error messages are intentionally classified rather than returned verbatim so
    a corrupted archive cannot make sensitive paths or data appear in logs.
    """
    info = regular_file(path)
    result: dict[str, Any] = {
        "name": path.name,
        "bytes": info.st_size if info else None,
        "modified_at": utc_timestamp(info.st_mtime) if info else None,
        "integrity": "unreadable" if info is None else "invalid",
    }
    if info is None:
        return result
    try:
        with path.open("rb") as raw:
            archive_sha256, _ = sha256_stream(raw)
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if len(names) != len(set(names)) or any(not member.isfile() or not safe_member_name(member.name) for member in members):
                return result
            manifest_member = archive.getmember("manifest.json")
            if manifest_member.size > MAX_MANIFEST_BYTES:
                return result
            manifest_stream = archive.extractfile(manifest_member)
            if manifest_stream is None:
                return result
            with manifest_stream:
                manifest = json.load(manifest_stream)
            summary = manifest_summary(manifest)
            if summary is None:
                return result
            entries = [manifest["database"], *manifest["media"]]
            expected_names = {"manifest.json", *(entry["path"] for entry in entries)}
            if set(names) != expected_names:
                return result
            for entry in entries:
                stream = archive.extractfile(entry["path"])
                if stream is None:
                    return result
                with stream:
                    checksum, size = sha256_stream(stream)
                if checksum != entry["sha256"] or size != entry["size"]:
                    return result
    except (OSError, EOFError, json.JSONDecodeError, KeyError, tarfile.TarError, UnicodeDecodeError, ValueError):
        return result
    result.update(summary)
    result["archive_sha256"] = archive_sha256
    result["integrity"] = "verified"
    return result


def inspect_status(directory: Path) -> dict[str, Any]:
    path = directory / "last-success.json"
    info = regular_file(path)
    if info is None or info.st_size > MAX_STATUS_BYTES:
        return {"available": False}
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        created_at = saved["created_at"]
        state = saved["state"]
        size = saved["size"]
        media_files = saved["media_files"]
        if not isinstance(created_at, str) or state not in {"local_only", "external_verified"}:
            raise ValueError
        if not isinstance(size, int) or size <= 0 or not isinstance(media_files, int) or media_files < 0:
            raise ValueError
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return {"available": False}
    return {"available": True, "created_at": created_at, "state": state, "bytes": size, "media_count": media_files}


def inspect_backups(directory: Path) -> dict[str, Any]:
    try:
        directory_info = directory.lstat()
    except OSError:
        return {"available": False, "archive_count": 0, "archives": [], "last_success": {"available": False}}
    if stat.S_ISLNK(directory_info.st_mode) or not stat.S_ISDIR(directory_info.st_mode):
        return {"available": False, "archive_count": 0, "archives": [], "last_success": {"available": False}}
    candidates: list[tuple[Path, os.stat_result]] = []
    try:
        children = sorted(directory.iterdir(), key=lambda item: item.name)
    except OSError:
        children = []
    for candidate in children:
        if not ARCHIVE_NAME.fullmatch(candidate.name):
            continue
        info = regular_file(candidate)
        if info is not None:
            candidates.append((candidate, info))
    candidates.sort(key=lambda item: item[1].st_mtime, reverse=True)
    archives = [
        {"name": path.name, "bytes": info.st_size, "modified_at": utc_timestamp(info.st_mtime),
         "integrity": "not_checked"}
        for path, info in candidates
    ]
    # Full hash verification can read a large archive.  It is intentionally run
    # only for the newest candidate so the emergency start command stays bounded.
    if candidates:
        archives[0] = inspect_archive(candidates[0][0])
    return {"available": True, "archive_count": len(archives), "archives": archives, "last_success": inspect_status(directory)}


def inspect_media(directory: Path) -> dict[str, Any]:
    """Count private media without following symlinks or emitting filenames."""
    try:
        root_info = directory.lstat()
    except OSError:
        return {"available": False, "file_count": 0, "total_bytes": 0, "scan_complete": False}
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        return {"available": False, "file_count": 0, "total_bytes": 0, "scan_complete": False}
    file_count = total_bytes = 0
    pending = [directory]
    complete = True
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as children:
                for entry in children:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            file_count += 1
                            total_bytes += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        complete = False
        except OSError:
            complete = False
    return {"available": True, "file_count": file_count, "total_bytes": total_bytes, "scan_complete": complete}


def tool_version(binary: str) -> dict[str, Any]:
    found = shutil.which(binary)
    if not found:
        return {"available": False, "version": None}
    try:
        result = subprocess.run([found, "--version"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, timeout=10, check=False)
        match = re.search(r"PostgreSQL\)\s+(\d+(?:\.\d+){0,2})", result.stdout)
        version = match.group(1) if result.returncode == 0 and match else None
    except (OSError, subprocess.SubprocessError):
        version = None
    return {"available": version is not None, "version": version}


def build_inventory(backup_dir: Path, media_root: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "backup_dir": inspect_backups(backup_dir),
        "media_root": inspect_media(media_root),
        "postgres_tools": {"pg_dump": tool_version("pg_dump"), "pg_restore": tool_version("pg_restore")},
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only IMC recovery inventory; emits no paths or backup contents.")
    parser.add_argument("--backup-dir", type=Path, default=Path(os.environ.get("BACKUP_DIR", "/data/backups")))
    parser.add_argument("--media-root", type=Path, default=Path(os.environ.get("MEDIA_ROOT", "/data/media")))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(json.dumps(build_inventory(args.backup_dir, args.media_root), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
