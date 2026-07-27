from django.core.management.base import BaseCommand

from care_management.exports import (
    EXPORT_RETENTION_HOURS,
    cleanup_old_care_management_exports,
)


class Command(BaseCommand):
    help = "Permanently delete care management export files older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-hours",
            type=int,
            default=EXPORT_RETENTION_HOURS,
            help="Delete export files older than this number of hours. Defaults to 24.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without deleting files.",
        )

    def handle(self, *args, **options):
        older_than_hours = options["older_than_hours"]
        if older_than_hours < 1:
            self.stderr.write("older-than-hours must be greater than 0.")
            return

        result = cleanup_old_care_management_exports(
            older_than_hours=older_than_hours,
            dry_run=options["dry_run"],
        )

        self.stdout.write(f"Export directory: {result['export_dir']}")
        self.stdout.write(f"Deleted files: {result['deleted']}")
        self.stdout.write(f"Skipped files: {result['skipped']}")

        if result["errors"]:
            self.stderr.write(f"Errors: {len(result['errors'])}")
            for error in result["errors"]:
                self.stderr.write(f"{error['file']}: {error['error']}")
