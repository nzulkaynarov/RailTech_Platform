from django.core.management.base import BaseCommand
from accounts.models import CustomUser, SystemRole
import os


class Command(BaseCommand):
    help = 'Creates or updates the superadmin user from environment variables'

    def handle(self, *args, **options):
        email = os.environ.get('SUPERADMIN_EMAIL')
        password = os.environ.get('SUPERADMIN_PASSWORD')

        if not email or not password:
            self.stdout.write(self.style.WARNING(
                "SUPERADMIN_EMAIL and/or SUPERADMIN_PASSWORD not set in environment. Skipping superadmin creation."))
            return

        username = email.split('@')[0] if '@' in email else email
        admin_role = SystemRole.objects.filter(code='ADMIN').first()

        user, created = CustomUser.objects.get_or_create(
            username=username,
            defaults={
                'email': email,
                'role': admin_role,
                'is_staff': True,
                'is_superuser': True,
                'is_active': True,
            }
        )

        user.set_password(password)
        # Ensure role/flags are correct even if user already existed
        user.email = email
        user.role = admin_role
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(
                f"Successfully created superadmin '{username}'"))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Successfully updated password and permissions for superadmin '{username}'"))
