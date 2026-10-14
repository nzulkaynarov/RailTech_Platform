from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group, Permission
from django.utils.translation import gettext_lazy as _
from import_export.admin import ImportExportModelAdmin
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.import_export.forms import ExportForm, ImportForm
from unfold.decorators import display
from unfold.forms import UserChangeForm, UserCreationForm  # noqa: F401

from core.admin_mixins import ReadOnlyInspectionMixin

from .models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from .resources import CompanyResource, UserResource

admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(ModelAdmin):
    """Django auth Group — оставлен для инженерной инспекции.

    В ERP бизнес-RBAC живёт в SystemRole + CompanyMember.role (ADR-0002),
    Django Groups НЕ используются для проверки прав в services.py. Этот экран —
    для DBA, который хочет понять, какие Django-разрешения выданы группе.
    """

    list_display = ("name", "permissions_count")
    search_fields = ("name",)
    filter_horizontal = ("permissions",)
    list_per_page = 25

    @display(description=_("Разрешений"))
    def permissions_count(self, obj):
        return obj.permissions.count()

    def get_queryset(self, request):
        # Аннотация через raw SQL была бы оптимальнее, но Group.permissions.count()
        # вызывается только при рендере ~25 строк — дешевле, чем subquery.
        return super().get_queryset(request).prefetch_related("permissions")


@admin.register(Permission)
class PermissionAdmin(ModelAdmin):
    """Django Permission — 4 авто-разрешения на каждый ContentType (add/change/delete/view).

    В ERP НЕ используется для проверки бизнес-прав (услуги проверяют
    is_member_of / role.code). Этот экран нужен только чтобы понять, что Django
    знает о каждой модели — отладка, не повседневное использование.
    """

    list_display = ("permission_name", "app_label_col", "model_col", "codename")
    list_filter = ("content_type__app_label", "content_type__model")
    list_filter_submit = True
    search_fields = ("name", "codename", "content_type__app_label", "content_type__model")
    list_select_related = ("content_type",)
    list_per_page = 50
    show_full_result_count = False

    @display(description=_("Разрешение"), ordering="name")
    def permission_name(self, obj):
        # Bypass Permission.__str__ which dereferences content_type and would
        # crash on any orphaned FK; just return the name field directly.
        return obj.name

    @display(description=_("Приложение"), ordering="content_type__app_label")
    def app_label_col(self, obj):
        ct = getattr(obj, "content_type", None)
        return ct.app_label if ct else "—"

    # Name is `model_col`, NOT `model` — ModelAdmin.model already shadows any
    # list_display entry called "model" (it's the admin's bound model class),
    # and Django's lookup_field resolves to the class, not to this callable.
    @display(description=_("Модель"), ordering="content_type__model")
    def model_col(self, obj):
        ct = getattr(obj, "content_type", None)
        return ct.model if ct else "—"


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


# ────────────────────────────────────────────
# Lookups
# ────────────────────────────────────────────


@admin.register(SystemRole, WorkspaceRole, CompanyType)
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
    list_select_related = ("role",)
    inlines = [CompanyMemberInline]
    warn_unsaved_form = True

    @display(header=True, description=_("Пользователь"))
    def show_user(self, obj):
        name = obj.get_full_name() or obj.username
        return [name, obj.email]

    @display(
        description=_("Роль"),
        label={
            "Администратор платформы": "danger",
            "Пользователь": "info",
        },
    )
    def role_badge(self, obj):
        return obj.role.name if obj.role else "—"

    fieldsets = (
        (
            None,
            {
                "fields": (("email", "password"),),
            },
        ),
        (
            _("Профиль"),
            {
                "classes": ["tab"],
                "fields": (
                    ("first_name", "last_name"),
                    ("username", "phone"),
                    "avatar",
                ),
            },
        ),
        (
            _("Доступ"),
            {
                "classes": ["tab"],
                "fields": (
                    ("is_active", "is_staff", "is_superuser"),
                    "role",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
    )
    filter_horizontal = ("groups", "user_permissions")
    autocomplete_fields = ("role",)

    #: Поля, которыми человек поднимает СЕБЕ или другому уровень доступа на всю платформу.
    PRIVILEGE_FIELDS = ("is_superuser", "is_staff", "groups", "user_permissions")

    def get_readonly_fields(self, request, obj=None):
        """Привилегированный блок редактирует ТОЛЬКО суперпользователь.

        Прогон 20-08: инженер с правом `accounts.change_customuser` открывал форму пользователя и
        сохранял себе `is_superuser=True` — тремя кликами, без следа и без второго человека.
        Django-админка сама такой защиты не даёт: право на модель означает право на ВСЕ её поля.

        Ровно так же поступает сам Django в `contrib.auth.admin.UserAdmin` (`get_form`: поле
        `user_permissions` прячется от того, кто не суперпользователь) — здесь мы распространяем
        тот же принцип на весь блок эскалации, включая членство в группах: `system_engineers`
        открывает инженерную админку, и раздавать её должен тот же, кто раздаёт суперправа.
        """
        readonly = list(super().get_readonly_fields(request, obj))
        if not request.user.is_superuser:
            readonly.extend(field for field in self.PRIVILEGE_FIELDS if field not in readonly)
        return tuple(readonly)


# ────────────────────────────────────────────
# Companies
# ────────────────────────────────────────────


@admin.register(Company)
class CompanyAdmin(ReadOnlyInspectionMixin, ImportExportModelAdmin, ModelAdmin):
    resource_classes = [CompanyResource]
    import_form_class = ImportForm
    export_form_class = ExportForm
    list_display = ("name", "inn", "types_display", "country", "created_at")
    list_filter = ("types", "country")
    list_filter_submit = True
    search_fields = ("name", "inn")
    list_per_page = 25
    list_select_related = ("country",)
    inlines = [CompanyMemberInline]
    autocomplete_fields = ["country", "types"]
    warn_unsaved_form = True

    def get_queryset(self, request):
        # Prefetch M2M `types` so types_display() doesn't issue 1 query per row.
        return super().get_queryset(request).prefetch_related("types")

    @display(description=_("Роли"))
    def types_display(self, obj):
        types = obj.types.all()
        return ", ".join(t.name for t in types) if types else "—"

    fieldsets = (
        (
            None,
            {
                "fields": (
                    ("name", "inn"),
                    "country",
                    "types",
                ),
            },
        ),
        (
            _("Контакты"),
            {
                "classes": ["tab"],
                "fields": (
                    ("contact_person", "phone"),
                    ("email", "website"),
                    "legal_address",
                    "logo",
                ),
            },
        ),
        (
            _("Банк"),
            {
                "classes": ["tab"],
                "fields": (("bank_account", "mfo"),),
            },
        ),
    )
