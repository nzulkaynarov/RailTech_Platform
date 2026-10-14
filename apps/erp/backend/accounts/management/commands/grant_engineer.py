"""
Grant or revoke `system_engineers` group membership for a user.

This is the canonical way to give a user access to Django Unfold admin
(per ADR-0001). Business admins should NOT be in this group — they use
the React Admin instead.

Usage:
    python manage.py grant_engineer dev@example.com
    python manage.py grant_engineer dev@example.com --revoke
"""

from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from accounts.models import CustomUser


class Command(BaseCommand):
    help = "Grant or revoke system_engineers (Unfold admin access) for a user."

    def add_arguments(self, parser):
        parser.add_argument("email", help="User email")
        parser.add_argument(
            "--revoke",
            action="store_true",
            help="Remove from system_engineers group instead of adding",
        )

    def handle(self, *args, **options):
        email = options["email"]
        revoke = options["revoke"]

        try:
            user = CustomUser.objects.get(email=email)
        except CustomUser.DoesNotExist:
            raise CommandError(f"User '{email}' not found")

        try:
            group = Group.objects.get(name="system_engineers")
        except Group.DoesNotExist:
            raise CommandError("Group 'system_engineers' does not exist. " "Run `python manage.py migrate` first.")

        if revoke:
            user.groups.remove(group)
            user.is_staff = False
            user.save(update_fields=["is_staff"])
            self.stdout.write(self.style.SUCCESS(f"Revoked Unfold admin access from {email}"))
        else:
            user.groups.add(group)
            user.is_staff = True
            user.save(update_fields=["is_staff"])
            self.stdout.write(self.style.SUCCESS(f"Granted Unfold admin access to {email} (system_engineers group)"))
