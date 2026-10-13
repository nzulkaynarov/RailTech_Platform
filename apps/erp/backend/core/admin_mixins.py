"""
Admin mixins for restricting Django Unfold ModelAdmin to inspection mode.

Per ADR-0001:
- Django Unfold is the engineering / DBA inspection tool, not a daily-use admin.
- Business operations live in React Admin and DRF endpoints.
- Bulk admin actions remain as emergency back-door for superusers only.

Usage:
    from core.admin_mixins import ReadOnlyInspectionMixin, superuser_only_action

    @admin.register(Deal)
    class DealAdmin(ReadOnlyInspectionMixin, ModelAdmin):
        actions = ["close_deal"]

        @superuser_only_action(_("[Emergency] Закрыть сделку"))
        def close_deal(self, request, queryset):
            ...
"""

from functools import wraps

from django.contrib import admin
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.template.response import TemplateResponse
from django.utils.translation import gettext_lazy as _

EMERGENCY_CONFIRM_FIELD = "_emergency_confirmed"
EMERGENCY_REASON_FIELD = "_emergency_reason"
EMERGENCY_CONFIRM_TEMPLATE = "admin/emergency_action_confirmation.html"


def superuser_only_action(description):
    """
    Decorator for admin actions that should only be available to superusers.
    Non-superusers won't see the action in the dropdown.

    Usage:
        @superuser_only_action(_("[Emergency] Подтвердить KYC"))
        def verify_kyc(self, request, queryset):
            ...
    """

    def decorator(func):
        @admin.action(description=description)
        @wraps(func)
        def wrapper(self, request, queryset):
            if not request.user.is_superuser:
                self.message_user(
                    request,
                    _("Только суперпользователь может выполнить это действие."),
                    level="error",
                )
                return

            reason = (request.POST.get(EMERGENCY_REASON_FIELD) or "").strip()
            if not request.POST.get(EMERGENCY_CONFIRM_FIELD) or not reason:
                return _confirmation_page(self, request, queryset, description, func.__name__, reason)

            # Строки снимаем ДО вызова: обработчик меняет их (а `archive_selected` и удаляет),
            # и после него набор уже не тот, о котором принималось решение.
            affected = [(obj.pk, str(obj)) for obj in queryset]
            result = func(self, request, queryset)
            _log_emergency_action(request, queryset.model, affected, func.__name__, description, reason)
            return result

        return wrapper

    return decorator


def _confirmation_page(model_admin, request, queryset, description, action_name, reason):
    """Промежуточная страница подтверждения — приём самой Django (`delete_selected`).

    Действие срабатывало С ПЕРВОГО клика: выбрал 42 компании, промахнулся в выпадающем списке,
    нажал «Выполнить» — и все 42 получили KYC L2. Отменить это нечем. Django ровно для такого
    случая показывает промежуточный экран со списком затрагиваемых строк, и здесь берётся он же,
    а не собственная выдумка.

    Обоснование обязательно по той же причине, по какой оно обязательно у break-glass и у
    приостановки подписки: аварийное вмешательство без причины неотличимо от ошибки.
    """
    opts = queryset.model._meta
    context = {
        **model_admin.admin_site.each_context(request),
        "title": description,
        "action_description": description,
        "objects": queryset,
        "objects_count": queryset.count(),
        "opts": opts,
        "action_name": action_name,
        "action_checkbox_name": ACTION_CHECKBOX_NAME,
        "selected_ids": [str(obj.pk) for obj in queryset],
        "confirm_field": EMERGENCY_CONFIRM_FIELD,
        "reason_field": EMERGENCY_REASON_FIELD,
        "reason": reason,
        "reason_missing": bool(request.POST.get(EMERGENCY_CONFIRM_FIELD)) and not reason,
        "media": model_admin.media,
    }
    return TemplateResponse(request, EMERGENCY_CONFIRM_TEMPLATE, context)


def _log_emergency_action(request, model, affected, action_name, description, reason):
    """След аварийного действия — в журнале доступа, по одной записи на строку.

    Из девяти аварийных обработчиков ЧЕТЫРЕ писали журнал (внутри своих сервисов), пять — нет,
    и ни один не попадал в «Журнал доступа»: тот отбирает по машинному коду `admin.*`
    (`core/admin_api/break_glass.py`), а свободные записи сервисов его не несут. Инженер правил
    данные арендаторов, и увидеть это можно было только в трёх разных местах или нигде.

    Пишем ЗДЕСЬ, а не в каждом сервисе (Rule 8 не нарушается: это свойство инструмента, а не
    бизнес-операции — сервис не знает, вызвали его из Unfold, из API или из Celery). Двойной
    записи не боимся: та, что пишет сервис, рассказывает о бизнес-переходе, эта — о том, кто и
    зачем полез в аварийный люк.
    """
    from core.audit import log_admin_action

    label = str(description)
    for entity_id, entity_label in affected:
        log_admin_action(
            entity_type=model._meta.label_lower,
            entity_id=entity_id,
            action=f"[FORCE_ADMIN] {label} — {entity_label}",
            actor=request.user,
            reason=reason,
            level="WARNING",
            event_code=f"admin.emergency.{action_name}",
            event_params={"model": model._meta.label_lower, "object": entity_label},
        )


class ReadOnlyInspectionMixin:
    """
    Inspection-mode guard for Django Unfold ModelAdmin.

    RULE CHANGE (2026-06-29, owner directive): the **superuser** (Platform Engineer) now
    has FULL privileges in Unfold — add / change / delete — for direct data administration.
    Unfold is no longer a read-only inspection tool for the superuser.

    AUDIT SCOPE (be precise — do NOT overclaim): django-pghistory triggers capture changes
    ONLY for the tracked business models — Deal, Quote, QuoteItem, Contract, Invoice, Payment,
    Act (and SystemSetting). Mutations to OTHER models (Company, SupplierSubscription,
    CompanyRoleApplication, Fulfillment, Product, SupplierOffer, …) are NOT history-tracked.
    Direct edits here also BYPASS service-layer side effects (FSM transitions, KYC/subscription
    emails, document-number minting, invoice.amount_paid recompute) — for those, prefer the
    React Operator pages / DRF services / @superuser_only_action handlers, which are audited.
    A handful of admins therefore keep `has_add_permission=False` (Contract/Invoice/Act/Payment)
    because raw creation produces structurally-broken rows (empty unique number / stale balance).
    NOTE: Company IS history-tracked (`@pghistory.track()` on the model) — the list above named
    it as untracked, which was wrong. Its M2M `types`, however, pghistory does NOT cover: M2M
    changes live in `django_admin_log`, and `LogEntry` is not registered in Unfold, so such a
    change is invisible in the interface (замер 25-08).

    NON-superuser staff (should any be granted Django admin access) remain in read-only
    inspection mode:
    - Add / Delete via UI: forbidden
    - Field editing in change form: forbidden (all fields become readonly)
    - View change form: ALLOWED (so they can inspect a record)
    Override `inspection_editable_fields` (tuple) to allow specific fields for such staff.
    Custom @admin.action handlers remain superuser-only (@superuser_only_action).
    """

    inspection_editable_fields: tuple = ()

    def has_add_permission(self, request):
        return bool(getattr(request.user, "is_superuser", False))

    def has_delete_permission(self, request, obj=None):
        return bool(getattr(request.user, "is_superuser", False))

    def get_readonly_fields(self, request, obj=None):
        existing = list(super().get_readonly_fields(request, obj))

        # Superuser edits freely (full privileges); only non-superuser staff are locked
        # down to read-only inspection.
        if getattr(request.user, "is_superuser", False):
            return existing

        if obj is None:
            return existing

        # M2M ВКЛЮЧЁН намеренно. Раньше он вычёркивался вместе с обратными связями, и
        # «режим только чтения» оставлял на форме компании ровно одно редактируемое поле —
        # `types`: инженер снимал компании роль продавца, и она пропадала из подбора у ВСЕХ
        # покупателей (замер 25-08: 30 полей readonly, одно живое). Тот же зазор открывал
        # `Deal.target_sellers` — адресацию конкретной заявки, то есть keystone-инвариант
        # «скрытой конкуренции» (ADR-0003 §5). Докстринг обещал «all fields become readonly»,
        # и это было неправдой ровно там, где цена ошибки выше всего.
        #
        # `one_to_many` (обратные связи) исключаются по-прежнему: это не поля формы, и Django
        # падает, если объявить их readonly.
        all_fields = [f.name for f in self.model._meta.get_fields() if not f.one_to_many]
        editable = set(self.inspection_editable_fields)
        for name in all_fields:
            if name not in editable and name not in existing:
                existing.append(name)
        return existing

    def get_changelist_instance(self, request):
        """Правка прямо в списке — обход режима «только чтение».

        `readonly_fields` управляет ФОРМОЙ записи, а `list_editable` рисует поля прямо в
        реестре и сохраняет их своим POST'ом мимо неё. У справочников это `sort_order` и
        `is_active`: не-суперпользователь гасил строку справочника из списка, ни разу не
        открыв карточку. Django строит `ChangeList` из `self.list_editable` (общего на все
        запросы), поэтому гасим на ЭКЗЕМПЛЯРЕ — мутировать атрибут класса небезопасно, он
        общий для всех одновременных запросов.
        """
        changelist = super().get_changelist_instance(request)
        if not request.user.is_superuser:
            changelist.list_editable = ()
        return changelist

    def get_actions(self, request):
        """Массовые действия — инструмент суперпользователя, а не всякого, кто вошёл.

        Прежний отбор оставлял не-суперпользователю всё, у чего нет `__wrapped__`, — то есть
        всё, что НЕ обёрнуто `superuser_only_action`. Признак хрупкий: он говорит о наличии
        `functools.wraps`, а не о намерении автора. Достаточно завести обычный
        `@admin.action` — и он проходит насквозь (так и случилось с «Пометить прочитанными»,
        правившим чужие уведомления, замер 26-08).

        Считаем наоборот: не-суперпользователю остаётся только то, что зарегистрировано САМОЙ
        Django (`delete_selected` и подобные из `admin.site._actions`), а всё, что объявил
        разработчик на модели, — нет. Отсутствие обёртки больше не пропуск.
        """
        actions = super().get_actions(request)
        if request.user.is_superuser:
            return actions
        site_actions = set(getattr(self.admin_site, "_actions", {}))
        return {name: value for name, value in actions.items() if name in site_actions}
