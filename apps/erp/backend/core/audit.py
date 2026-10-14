"""
Admin audit helper.

Centralized writer for ActivityLog entries produced by admin/override actions.
Populates the entity scope (entity_type, entity_id), a reason, and optional
before/after JSON snapshots so the Timeline tab on admin detail pages can
render a diff.

Usage:
    from core.audit import log_admin_action
    log_admin_action(
        entity_type='company', entity_id=company.id,
        action='Компания архивирована',
        detail=f'{company.name}: в обороте → архив',
        actor=request.user, reason=reason,
        before={'is_active': True},
        after={'is_active': False},
    )
"""

from __future__ import annotations

from typing import Any, Optional


def log_admin_action(
    *,
    entity_type: str,
    entity_id: int,
    action: str,
    detail: str = "",
    actor=None,
    reason: str = "",
    before: Optional[dict[str, Any]] = None,
    after: Optional[dict[str, Any]] = None,
    level: str = "INFO",
    expires_at=None,
    company_id: Optional[int] = None,
    contact_id: Optional[int] = None,
    deal_id: Optional[int] = None,
    event_code: str = "",
    event_params: Optional[dict[str, Any]] = None,
):
    """
    Create an ActivityLog entry scoped to a single entity.

    All admin override actions must route through this helper so the timeline
    remains consistent. `expires_at` time-boxes a break-glass access grant (G2).
    company_id/contact_id/deal_id link the entry into the CRM counterparty
    timeline (Phase A, spec-remaining-2026-07-07 §2.1) — call sites pass
    whatever counterparty scope they have in context.

    event_code/event_params carry a structured (localizable) event for the
    timeline (E1): callers that emit a known event (e.g. transition_deal_stage
    → "deal.stage_changed") pass a machine code + interpolation params; the
    human-readable text is assembled client-side by viewer locale. Free-form
    admin actions leave event_code empty and render from the RU `action`
    fallback exactly as before.
    """
    from crm.models import ActivityLog

    return ActivityLog.objects.create(
        action=action[:255],
        detail=detail,
        event_code=event_code[:64],
        event_params=event_params or {},
        user=actor,
        level=level,
        entity_type=entity_type[:40],
        entity_id=int(entity_id) if entity_id else None,
        reason=(reason or "")[:5000],
        before_data=before,
        after_data=after,
        expires_at=expires_at,
        company_id=company_id,
        contact_id=contact_id,
        deal_id=deal_id,
    )


class AuditedWriteMixin:
    """Операторский вьюсет, который пишет след на создание, правку и удаление.

    До 27-08 этот блок был скопирован ЧЕТЫРЕЖДЫ — подписки, справочники, шаблоны писем и права
    компании, — и копии успели разойтись ещё до того, как их сравнили: ключ причины `reason`
    против `note`, `entity_type` то литералом, то из `_meta`, `company_id` передавали двое из
    четырёх, снимок «до» был у трёх из четырёх. Пятый операторский реестр скопировал бы ту
    копию, которую автор увидел первой.

    Настройка — три точки:

    * `audit_event_prefix` — хвост машинного кода `admin.<prefix>.<created|updated|deleted>`.
      По нему отбираются административные записи ленты (`event_code` с префиксом `admin.`), поэтому
      префикс обязателен: запись без кода в журнал не попадает.
    * `audit_action(instance, event)` — человеческая строка-фолбэк для тех, кто читает журнал
      без витрины (Unfold).
    * `audit_snapshot(instance)` — что попадает в `before`/`after`. По умолчанию снимка нет:
      «что было раньше» имеет смысл не у всякой сущности, а выдуманный снимок хуже пустого.

    Причина берётся из тела запроса ключом `reason` — тем же, что просит витрина у опасных
    действий. Удаление пишется уровнем WARNING: это единственное необратимое из трёх.
    """

    #: Обязателен. Без него запись не попадёт в «Журнал доступа».
    audit_event_prefix: str = ""

    def audit_entity_type(self, instance) -> str:
        """По умолчанию — метка модели. Переопределять ТОЛЬКО ради совместимости с уже
        записанной историей: смена значения оторвала бы новые записи от старых при разборе
        инцидента."""
        return instance._meta.label_lower

    def audit_action(self, instance, event: str) -> str:
        return f"{instance._meta.verbose_name} {event}: {instance.pk}"

    def audit_snapshot(self, instance) -> Optional[dict]:
        return None

    def audit_event_params(self, instance) -> dict:
        return {"model": instance._meta.label_lower}

    def audit_company_id(self, instance) -> Optional[int]:
        return getattr(instance, "company_id", None)

    def _write_audit(self, instance, event: str, before=None, after=None) -> None:
        assert self.audit_event_prefix, "audit_event_prefix обязателен — иначе след не виден в журнале"
        log_admin_action(
            entity_type=self.audit_entity_type(instance),
            entity_id=instance.pk,
            action=self.audit_action(instance, event),
            detail=str(instance),
            actor=self.request.user,
            reason=(self.request.data.get("reason") or "").strip(),
            before=before,
            after=after,
            company_id=self.audit_company_id(instance),
            level="WARNING" if event == "deleted" else "INFO",
            event_code=f"admin.{self.audit_event_prefix}.{event}",
            event_params=self.audit_event_params(instance),
        )

    def perform_create(self, serializer):
        super().perform_create(serializer)
        self._write_audit(serializer.instance, "created", after=self.audit_snapshot(serializer.instance))

    def perform_update(self, serializer):
        # Снимок «до» — с УЖЕ ЗАГРУЖЕННОГО инстанса: `update()` его достал, и он ещё держит
        # докоммитные значения. Второй `get_object()` был бы лишним SELECT-ом.
        before = self.audit_snapshot(serializer.instance)
        super().perform_update(serializer)
        self._write_audit(serializer.instance, "updated", before=before, after=self.audit_snapshot(serializer.instance))

    def perform_destroy(self, instance):
        # След ДО удаления: после него ни pk, ни связей уже не спросишь.
        self._write_audit(instance, "deleted", before=self.audit_snapshot(instance))
        super().perform_destroy(instance)
