from django.utils.translation import gettext_lazy as _
from import_export import fields, resources
from import_export.widgets import ForeignKeyWidget, ManyToManyWidget

from master_data.models import Country

from .models import Company, CompanyType, CustomUser


class CompanyResource(resources.ModelResource):
    """
    Import/Export для компаний (клиенты, поставщики, производители).

    Пример XLSX:
    | Название | ИНН | Страна (код) | Роли (через ;) | Контактное лицо | Телефон | Email |
    """

    country = fields.Field(
        column_name=_("Страна (код)"),
        attribute="country",
        widget=ForeignKeyWidget(Country, field="code"),
    )
    # Статус верификации в импорте/экспорте НЕ участвует: KYC-уровень ставит сервис
    # (`accounts.services.kyc.verify_company_kyc`) — с проверкой, аудитом и письмом компании.
    # Строкой в файле его штамповать нельзя (20-08).
    types = fields.Field(
        column_name=_("Роли (через ;)"),
        attribute="types",
        widget=ManyToManyWidget(CompanyType, field="code", separator=";"),
    )

    class Meta:
        model = Company
        import_id_fields = ["inn"]
        fields = (
            "name",
            "inn",
            "country",
            "types",
            "legal_address",
            "contact_person",
            "phone",
            "email",
            "website",
            "bank_account",
            "mfo",
        )
        export_order = fields
        skip_unchanged = True
        report_skipped = True


class UserResource(resources.ModelResource):
    """
    Import/Export для пользователей.

    Пример XLSX:
    | Email | Имя | Фамилия | Телефон | Активен |
    """

    class Meta:
        model = CustomUser
        import_id_fields = ["email"]
        fields = (
            "email",
            "first_name",
            "last_name",
            "username",
            "phone",
            "is_active",
        )
        # `role` и `is_staff` СОЗНАТЕЛЬНО не импортируются и не экспортируются. Системную роль
        # меняет сервис (`accounts.services.members.change_user_role`) — с проверкой инвариантов
        # и записью в аудит, а `is_staff` — это доступ в инженерную админку, который выдаётся
        # членством в группе `system_engineers`, а не строкой в таблице. Пока они были в списке,
        # загруженный XLSX выдавал права платформы мимо всех проверок (20-08).
        export_order = fields
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        """Set username from email if not provided."""
        if not row.get("username"):
            email = row.get("email", "")
            row["username"] = email.split("@")[0] if email else ""

    def after_save_instance(self, instance, row, **kwargs):
        """Set unusable password for new users — they must use setup-password flow."""
        if kwargs.get("new", False):
            instance.set_unusable_password()
            instance.is_active = False
            instance.save(update_fields=["password", "is_active"])
