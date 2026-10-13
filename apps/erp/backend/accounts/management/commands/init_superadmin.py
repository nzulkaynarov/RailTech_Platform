import os

from django.core.management.base import BaseCommand

from accounts.models import CustomUser, SystemRole


class Command(BaseCommand):
    help = (
        "Create the superadmin from SUPERADMIN_EMAIL / SUPERADMIN_PASSWORD (idempotent). "
        "An EXISTING account is left untouched unless --reset-password is passed."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="Also reset the password/role/flags of an existing superadmin account (credential rotation).",
        )

    def handle(self, *args, **options):
        email = os.environ.get("SUPERADMIN_EMAIL")
        password = os.environ.get("SUPERADMIN_PASSWORD")

        if not email or not password:
            self.stdout.write(
                self.style.WARNING(
                    "SUPERADMIN_EMAIL and/or SUPERADMIN_PASSWORD not set in environment. Skipping superadmin creation."
                )
            )
            return

        admin_role = SystemRole.objects.filter(code="ADMIN").first()

        # SEC-10: key on email (the USERNAME_FIELD) — the old get_or_create on the
        # email LOCAL PART could grab an unrelated user's account and silently
        # promote it. And never reset an existing account's password/flags on every
        # run: that undid password rotations and re-activated a disabled superadmin
        # on each deploy. Rotation is now an explicit --reset-password.
        user = CustomUser.objects.filter(email=email).first()

        if user is None:
            username = email.split("@")[0] if "@" in email else email
            if CustomUser.objects.filter(username=username).exists():
                # The local part is taken by an unrelated account — keep usernames unique.
                username = email
            user = CustomUser.objects.create(
                username=username,
                email=email,
                role=admin_role,
                is_staff=True,
                is_superuser=True,
                is_active=True,
            )
            user.set_password(password)
            user.save(update_fields=["password"])
            self.stdout.write(self.style.SUCCESS(f"Successfully created superadmin '{email}'"))
        elif options["reset_password"]:
            user.set_password(password)
            user.role = admin_role
            user.is_staff = True
            user.is_superuser = True
            user.is_active = True
            user.save(update_fields=["password", "role", "is_staff", "is_superuser", "is_active"])
            self.stdout.write(self.style.SUCCESS(f"Reset password and permissions for superadmin '{email}'"))
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Superadmin '{email}' already exists — left untouched. "
                    "Use --reset-password to rotate credentials/flags."
                )
            )
