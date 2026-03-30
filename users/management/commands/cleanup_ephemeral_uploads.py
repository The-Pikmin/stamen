from django.core.management.base import BaseCommand

from users.services import (
    claim_expired_uploads,
    get_uploads_ready_for_cleanup,
    mark_upload_as_deleting,
    upload_is_still_deleting,
    check_upload_in_use,
    promote_upload_to_retained,
    delete_storage_object,
    delete_upload_record,
    reset_upload_to_ephemeral,
)


class Command(BaseCommand):
    help = "Delete expired ephemeral uploads that are not referenced by saved scans."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of expired uploads to inspect in one run.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Log what would be deleted without mutating storage or database rows.",
        )

    def handle(self, *args, **options):
        limit = max(1, options["limit"])
        dry_run = options["dry_run"]

        candidates = claim_expired_uploads(limit)
        staged = 0
        inspected = 0
        deleted = 0
        retained = 0
        skipped = 0
        failed = 0

        for upload in candidates:
            if mark_upload_as_deleting(upload["id"]):
                staged += 1
            else:
                skipped += 1

        ready_uploads = get_uploads_ready_for_cleanup(limit)
        for upload in ready_uploads:
            inspected += 1
            upload_id = upload["id"]
            storage_path = upload["storage_path"]
            user_id = upload["user_id"]

            try:
                if check_upload_in_use(upload_id, user_id):
                    if dry_run:
                        self.stdout.write(
                            f"[dry-run] would retain upload {upload_id} because it is referenced"
                        )
                        reset_upload_to_ephemeral(upload_id)
                    else:
                        promote_upload_to_retained(upload_id)
                    retained += 1
                    continue

                if not upload_is_still_deleting(upload_id):
                    skipped += 1
                    continue

                if dry_run:
                    self.stdout.write(
                        f"[dry-run] would delete upload {upload_id} at {storage_path}"
                    )
                    reset_upload_to_ephemeral(upload_id)
                    deleted += 1
                    continue

                delete_storage_object(storage_path)
                delete_upload_record(upload_id)
                deleted += 1
            except Exception as exc:
                failed += 1
                reset_upload_to_ephemeral(upload_id)
                self.stderr.write(f"Failed to clean upload {upload_id}: {exc}")

        self.stdout.write(
            self.style.SUCCESS(
                "cleanup complete: "
                f"staged={staged} inspected={inspected} deleted={deleted} retained={retained} "
                f"skipped={skipped} failed={failed}"
            )
        )
