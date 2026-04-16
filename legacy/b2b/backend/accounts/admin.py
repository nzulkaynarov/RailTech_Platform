from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, Permission
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.import_export.forms import ExportForm, ImportForm
from unfold.decorators import display
from unfold.forms import UserChangeForm, UserCreationForm
from import_export.admin import ImportExportModelAdmin
from core.admin_mixins import ReadOnlyInspectionMixin, superuser_only_action

from .models import (
    CustomUser, Company, CompanyMember, KYCDocument,
    SystemRole, WorkspaceRole, CompanyType, VerificationStatus, KYCDocType,
    CompanyRoleApplication, SupplierSubscription
)
from .resources import CompanyResource, UserResource
from . import services

admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(ModelAdmin):
    search_fields = ("name",)


@admin.register(Permission)
class PermissionAdmin(ModelAdmin):
    search_fields = ("name", "codename")
    list_per_page = 50


# ────────────────────────────────────────────
# Inlines
# ────────────────────────────────────────────

class CompanyMemberInline(TabularInline):
    model = CompanyMember
    extra = 0
    show_change_link = True
    tab = True
    fields = ["user", "role", "is_primary", "is_active", "joined_at"]
    readonly_fields = ["joined_at"]
    autocomplete_fields = ["company", "role", "user"]


class KYCDocumentInline(TabularInline):
    model = KYCDocument
    extra = 0
    show_change_link = True
    tab = True
    fields = ["doc_type", "file", "original_filename", "uploaded_at"]
    readonly_fields = ["uploaded_at", "original_filename"]
    autocomplete_fields = ["doc_type"]


# ────────────────────────────────────────────
# Lookups
# ────────────────────────────────────────────

@admin.register(SystemRole, WorkspaceRole, CompanyType, VerificationStatus, KYCDocType)
class LookupAdmin(ModelAdmin):
    list_display = ["name", "code", "sort_order", "is_active"]
    list_editable = ["sort_order", "is_active"]
    search_fields = ["name", "code"]
    list_per_page = 25


# ────────────────────────────────────────────
# Users
# ────────────────────────────────────────────

@admin.register(CustomUser)
class UserAdmin(ImportExportModelAdmin, BaseUserAdmin, ModelAdmin):
    resource_classes = [UserResource]
    import_form_class = ImportForm
    export_form_class = ExportForm
    list_display = ("show_user", "role_badge", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_superuser", "is_active")
    list_filter_submit = True
    search_fields = ("email", "first_name", "last_name", "phone", "username")
    list_per_page = 25
    inlines = [CompanyMemberInline]
    actions = ["make_staff"]
    warn_unsaved_form = True

    @display(header=True, description=_("Пользователь"))
    def show_user(self, obj):
        name = obj.get_full_name() or obj.username
        return [name, obj.email]

    @display(
        description=_("Роль"),
        label={
            "Администратор": "danger",
            "Менеджер по продажам": "info",
            "Аккаунт-менеджер": "info",
            "Клиент": "success",
            "Гость (не подтверждён)": "warning",
        },
    )
    def role_badge(self, obj):
        return obj.role.name if obj.role else "—"

    @superuser_only_action(_("[Emergency] Назначить SALES_MANAGER + is_staff"))
    def make_staff(self, request, queryset):
        updated, error = services.assign_sales_manager_role(queryset)
        if error:
            self.message_user(request, error, level="error")
            return
        self.message_user(request, _("%(count)d пользователей обновлено.") % {"count": updated})

    fieldsets = (
        (None, {
            "fields": (("email", "password"),),
        }),
        (_("Профиль"), {
            "classes": ["tab"],
            "fields": (
                ("first_name", "last_name"),
                ("username", "phone"),
                "avatar",
            ),
        }),
        (_("Доступ"), {
            "classes": ["tab"],
            "fields": (
                ("is_active", "is_staff", "is_superuser"),
                "role",
                "groups",
                "user_permissions",
            ),
        }),
    )
    filter_horizontal = ("groups", "user_permissions")
    autocomplete_fields = ("role",)


# ────────────────────────────────────────────
# Companies
# ────────────────────────────────────────────

@admin.register(Company)
class CompanyAdmin(ReadOnlyInspectionMixin, ImportExportModelAdmin, ModelAdmin):
    resource_classes = [CompanyResource]
    import_form_class = ImportForm
    export_form_class = ExportForm
    list_display = ("name", "inn", "status_badge", "types_display", "country", "created_at")
    list_filter = ("verification_status", "types", "country")
    list_filter_submit = True
    search_fields = ("name", "inn")
    list_per_page = 25
    inlines = [CompanyMemberInline, KYCDocumentInline]
    autocomplete_fields = ["verification_status", "country", "types"]
    actions = ["verify_kyc"]
    warn_unsaved_form = True

    @display(
        description=_("Статус KYC"),
        label={
            "Не верифицирован": "danger",
            "Профиль на проверке": "warning",
            "KYC подтверждён": "success",
            "Договор заключён": "info",
            "Отклонён": "danger",
        },
    )
    def status_badge(self, obj):
        return obj.verification_status.name if obj.verification_status else "—"

    @display(description=_("Роли"))
    def types_display(self, obj):
        types = obj.types.all()
        return ", ".join(t.name for t in types) if types else "—"

    @superuser_only_action(_("[Emergency] Подтвердить KYC (L2)"))
    def verify_kyc(self, request, queryset):
        approved, skipped = services.bulk_verify_kyc(queryset, request.user, level_code='L2_VERIFIED')
        if skipped:
            self.message_user(
                request,
                _("Без KYC документов: %(names)s") % {"names": ", ".join(skipped)},
                level="warning",
            )
        if approved:
            self.message_user(request, _("%(count)d компаний подтверждено.") % {"count": approved})

    fieldsets = (
        (None, {
            "fields": (
                ("name", "inn"),
                ("verification_status", "country"),
                "types",
            ),
        }),
        (_("Контакты"), {
            "classes": ["tab"],
            "fields": (
                ("contact_person", "phone"),
                ("email", "website"),
                "legal_address",
                "logo",
            ),
        }),
        (_("Банк"), {
            "classes": ["tab"],
            "fields": (
                ("bank_account", "mfo"),
            ),
        }),
        (_("KYC"), {
            "classes": ["tab"],
            "fields": ("kyc_notes",),
        }),
    )


@admin.register(KYCDocument)
class KYCDocumentAdmin(ModelAdmin):
    list_display = ("company", "doc_type", "original_filename", "uploaded_at")
    list_filter = ("doc_type",)
    list_filter_submit = True
    search_fields = ("company__name", "original_filename")
    autocomplete_fields = ["company", "doc_type"]
    readonly_fields = ["uploaded_at", "original_filename"]
    list_per_page = 25

    fieldsets = (
        (None, {
            "fields": (
                ("company", "doc_type"),
                ("file", "original_filename"),
                "uploaded_at",
            ),
        }),
    )


# ────────────────────────────────────────────
# Role Applications
# ────────────────────────────────────────────

@admin.register(CompanyRoleApplication)
class CompanyRoleApplicationAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    list_display = ("company", "requested_type", "app_status", "submitted_by", "reviewed_by", "created_at")
    list_filter = ("status", "requested_type", "created_at")
    list_filter_submit = True
    search_fields = ("company__name", "company__inn")
    autocomplete_fields = ["company", "requested_type", "submitted_by", "reviewed_by"]
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 25
    actions = ["approve_application", "reject_application"]
    warn_unsaved_form = True

    @display(
        description=_("Статус"),
        label={
            "На рассмотрении": "warning",
            "Требуются документы": "info",
            "Ожидание оплаты": "info",
            "Одобрено": "success",
            "Отклонено": "danger",
        },
    )
    def app_status(self, obj):
        return obj.get_status_display()

    fieldsets = (
        (None, {
            "fields": (
                ("company", "requested_type"),
                ("status", "submitted_by"),
            ),
        }),
        (_("Документы"), {
            "classes": ["tab"],
            "fields": (
                "contract_file",
                "nda_file",
                "partnership_agreement",
            ),
        }),
        (_("Рассмотрение"), {
            "classes": ["tab"],
            "fields": (
                ("reviewed_by", "reviewed_at"),
                "review_notes",
                ("created_at", "updated_at"),
            ),
        }),
    )

    @superuser_only_action(_("[Emergency] Одобрить (с проверкой документов)"))
    def approve_application(self, request, queryset):
        approved, errors = services.bulk_approve_role_applications(queryset, request.user)
        if errors:
            self.message_user(request, "\n".join(errors), level="warning")
        if approved:
            self.message_user(request, _("%(count)d заявок одобрено.") % {"count": approved})

    @superuser_only_action(_("[Emergency] Отклонить"))
    def reject_application(self, request, queryset):
        updated = services.bulk_reject_role_applications(queryset, request.user)
        self.message_user(request, _("%(count)d заявок отклонено.") % {"count": updated})


# ────────────────────────────────────────────
# Subscriptions
# ────────────────────────────────────────────

@admin.register(SupplierSubscription)
class SupplierSubscriptionAdmin(ReadOnlyInspectionMixin, ModelAdmin):
    list_display = ("company", "plan_badge", "sub_status", "monthly_rate", "currency", "valid_until")
    list_filter = ("plan", "status")
    list_filter_submit = True
    search_fields = ("company__name", "company__inn")
    autocomplete_fields = ["company", "currency"]
    readonly_fields = ("created_at", "updated_at")
    list_per_page = 25
    actions = ["activate_subscription", "suspend_subscription"]
    warn_unsaved_form = True

    @display(
        description=_("План"),
        label={"Базовый": "info", "Стандартный": "warning", "Премиум": "success"},
    )
    def plan_badge(self, obj):
        return obj.get_plan_display()

    @display(
        description=_("Статус"),
        label={
            "Пробный период": "info",
            "Активна": "success",
            "Просрочена": "danger",
            "Приостановлена": "warning",
            "Отменена": "danger",
        },
    )
    def sub_status(self, obj):
        return obj.get_status_display()

    fieldsets = (
        (None, {
            "fields": (
                "company",
                ("plan", "status"),
            ),
        }),
        (_("Биллинг"), {
            "classes": ["tab"],
            "fields": (
                ("monthly_rate", "currency"),
                ("valid_from", "valid_until"),
                ("last_payment_date", "next_payment_date"),
            ),
        }),
        (_("Заметки"), {
            "classes": ["tab"],
            "fields": (
                "notes",
                ("created_at", "updated_at"),
            ),
        }),
    )

    @superuser_only_action(_("[Emergency] Активировать"))
    def activate_subscription(self, request, queryset):
        updated = services.change_subscription_status(queryset, 'ACTIVE')
        self.message_user(request, _("%(count)d активировано.") % {"count": updated})

    @superuser_only_action(_("[Emergency] Приостановить"))
    def suspend_subscription(self, request, queryset):
        updated = services.change_subscription_status(queryset, 'SUSPENDED')
        self.message_user(request, _("%(count)d приостановлено.") % {"count": updated})
