import time
from pathlib import Path

from django.conf import settings


EXPORT_RETENTION_HOURS = 24


def get_care_management_export_dir():
    return Path(settings.BASE_DIR) / "exports" / "care_management"


def ensure_care_management_export_dir():
    export_dir = get_care_management_export_dir()
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir


def cleanup_old_care_management_exports(older_than_hours=EXPORT_RETENTION_HOURS, dry_run=False):
    export_dir = get_care_management_export_dir()
    if not export_dir.exists():
        return {
            "export_dir": str(export_dir),
            "deleted": 0,
            "skipped": 0,
            "errors": [],
        }

    cutoff_timestamp = time.time() - (older_than_hours * 60 * 60)
    deleted = 0
    skipped = 0
    errors = []

    for file_path in export_dir.glob("*.xlsx"):
        try:
            if file_path.stat().st_mtime > cutoff_timestamp:
                skipped += 1
                continue

            if not dry_run:
                file_path.unlink()

            deleted += 1
        except OSError as exc:
            errors.append({
                "file": str(file_path),
                "error": str(exc),
            })

    return {
        "export_dir": str(export_dir),
        "deleted": deleted,
        "skipped": skipped,
        "errors": errors,
    }
