"""
Manually trigger Message archive to S3 cold storage.

Usage:
    python manage.py archive_messages                # default: 90 days
    python manage.py archive_messages --older-than 30
    python manage.py archive_messages --async        # queue via Celery
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Archive Message rows older than N days to S3 (JSONL files)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than",
            type=int,
            default=90,
            dest="days",
            help="Archive messages older than N days (default: 90)",
        )
        parser.add_argument(
            "--async",
            action="store_true",
            dest="run_async",
            help="Queue as Celery task instead of running synchronously",
        )

    def handle(self, *args, **options):
        days = options["days"]
        run_async = options["run_async"]

        from crm.tasks import archive_old_messages

        if run_async:
            task = archive_old_messages.delay(days)
            self.stdout.write(self.style.SUCCESS(
                f"Queued archive_old_messages(days={days}) — task id: {task.id}"
            ))
        else:
            self.stdout.write(f"Running archive_old_messages(days={days}) synchronously...")
            result = archive_old_messages(days)
            self.stdout.write(self.style.SUCCESS(
                f"Result: {result}"
            ))
