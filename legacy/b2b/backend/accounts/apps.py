from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self):
        # Connect signals so that post-M2M-edit consistency rules fire.
        from . import signals  # noqa: F401
