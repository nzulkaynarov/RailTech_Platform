from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from core.storage import get_public_storage, user_avatar_path

# ────────────────────────────────────────────
# Справочники модуля Accounts
# ────────────────────────────────────────────


class CustomUser(AbstractUser):
    """
    Пользователь системы.
    Привязка к компании — через промежуточную модель CompanyMember (Multi-tenancy).
    """

    email = models.EmailField(
        unique=True,
        verbose_name=_("Email"),
        help_text=_("Основной email для входа в систему"),
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        verbose_name=_("Телефон"),
        help_text=_("Мобильный или рабочий телефон"),
    )
    position = models.CharField(
        max_length=120,
        blank=True,
        verbose_name=_("Должность"),
        help_text=_("Должность сотрудника в компании (свободный текст)"),
    )
    avatar = models.ImageField(
        upload_to=user_avatar_path,
        storage=get_public_storage,
        null=True,
        blank=True,
        verbose_name=_("Аватар"),
        help_text=_("Фото пользователя для профиля"),
    )
    preferences = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Предпочтения"),
        help_text=_("Пользовательские настройки (тема, язык, часовой пояс)"),
    )
    totp_secret = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("TOTP Secret"),
        help_text=_("Секретный ключ для 2FA, зашифрован at rest (accounts/services/two_factor.py)"),
    )
    is_2fa_enabled = models.BooleanField(
        default=False,
        verbose_name=_("2FA Включена"),
        help_text=_("Включена ли двухфакторная аутентификация"),
    )
    role = models.ForeignKey(
        "accounts.SystemRole",
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
        verbose_name=_("Системная роль"),
        help_text=_("Глобальная роль: определяет права доступа на всей платформе"),
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    class Meta:
        verbose_name = _("Пользователь")
        verbose_name_plural = _("Пользователи")

    def __str__(self):
        return self.email

    @cached_property
    def primary_company(self):
        """Основная компания пользователя (is_primary=True). Кэшируется на инстанс."""
        try:
            for m in self.memberships.all():
                if m.is_primary and m.is_active:
                    return m.company
        except AttributeError:
            pass
        return None
