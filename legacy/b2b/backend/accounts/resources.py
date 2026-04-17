from import_export import resources, fields
from import_export.widgets import ForeignKeyWidget, ManyToManyWidget
from django.utils.translation import gettext_lazy as _
from .models import Company, CustomUser, CompanyType, VerificationStatus
from master_data.models import Country


class CompanyResource(resources.ModelResource):
    """
    Import/Export для компаний (клиенты, поставщики, производители).

    Пример XLSX:
    | Название | ИНН | Страна (код) | Роли (через ;) | Контактное лицо | Телефон | Email |
    """
    country = fields.Field(
        column_name=_('Страна (код)'),
        attribute='country',
        widget=ForeignKeyWidget(Country, field='code'),
    )
    verification_status = fields.Field(
        column_name=_('Статус верификации (код)'),
        attribute='verification_status',
        widget=ForeignKeyWidget(VerificationStatus, field='code'),
    )
    types = fields.Field(
        column_name=_('Роли (через ;)'),
        attribute='types',
        widget=ManyToManyWidget(CompanyType, field='code', separator=';'),
    )

    class Meta:
        model = Company
        import_id_fields = ['inn']
        fields = (
            'name', 'inn', 'country', 'types',
            'verification_status',
            'legal_address', 'contact_person',
            'phone', 'email', 'website',
            'bank_account', 'mfo',
        )
        export_order = fields
        skip_unchanged = True
        report_skipped = True


class UserResource(resources.ModelResource):
    """
    Import/Export для пользователей.

    Пример XLSX:
    | Email | Имя | Фамилия | Телефон | Роль (код) |
    """
    from .models import SystemRole

    role = fields.Field(
        column_name=_('Системная роль (код)'),
        attribute='role',
        widget=ForeignKeyWidget(SystemRole, field='code'),
    )

    class Meta:
        model = CustomUser
        import_id_fields = ['email']
        fields = (
            'email', 'first_name', 'last_name',
            'username', 'phone', 'role',
            'is_active', 'is_staff',
        )
        export_order = fields
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        """Set username from email if not provided."""
        if not row.get('username'):
            email = row.get('email', '')
            row['username'] = email.split('@')[0] if email else ''

    def after_save_instance(self, instance, row, **kwargs):
        """Set unusable password for new users — they must use setup-password flow."""
        if kwargs.get('new', False):
            instance.set_unusable_password()
            instance.is_active = False
            instance.save(update_fields=['password', 'is_active'])
