"""Add the composite index declared on Notification.Meta (pre-existing model drift)."""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0006_alter_notification_user"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "is_read", "audience"], name="notif_user_read_aud_idx"),
        ),
    ]
