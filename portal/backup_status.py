"""A small, allowlisted operational summary; never expose backup paths or contents."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import stat

from .storage import option


def get_backup_status():
    unknown = {"available": False, "stale": False}
    path = Path(option("BACKUP_DIR", "/data/backups")) / "last-success.json"
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 8192:
            return unknown
        with path.open("rb") as stream:
            raw = stream.read(8193)
        if len(raw) > 8192:
            return unknown
        saved = json.loads(raw)
        created_at = datetime.fromisoformat(saved["created_at"])
        now = datetime.now(timezone.utc)
        if created_at.tzinfo is None or created_at > now + timedelta(minutes=5):
            return unknown
        state, media_files, size = saved["state"], saved["media_files"], saved["size"]
        if state not in {"local_only", "external_verified"}:
            return unknown
        if type(media_files) is not int or media_files < 0 or type(size) is not int or size <= 0:
            return unknown
        return {"available": True, "created_at": created_at, "state": state,
                "media_files": media_files, "size": size,
                "stale": now - created_at > timedelta(hours=48)}
    except (OSError, ValueError, KeyError, TypeError):
        return unknown
