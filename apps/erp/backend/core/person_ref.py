"""Ссылка на сотрудника «кто сделал» (план СУЩ-3): id сотрудника в CRM и имя.

По `crm_user_id` Платформа находит фото и должность в справочнике сотрудников CRM; имя — как в ERP, чтобы старое имя
отключённого человека не терялось. Пользователь без связи с CRM (системный, заведённый до сопряжения) — `crm_user_id: None`,
Платформа рисует инициалы.
"""

from __future__ import annotations

from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers


def person_name(user) -> str:
    if user is None:
        return ""
    return (user.get_full_name() or user.email or "").strip() or f"Сотрудник #{user.pk}"


def person_ref(user) -> dict | None:
    """`{crm_user_id, name}`; запрашивающий код выбирает `<поле>__crm_user_mapping`, иначе это запрос на строку."""
    if user is None:
        return None
    try:
        crm_user_id = user.crm_user_mapping.crm_user_id
    except ObjectDoesNotExist:
        crm_user_id = None
    return {"crm_user_id": crm_user_id, "name": person_name(user)}


class PersonRefSerializer(serializers.Serializer):
    """Схема ссылки в выгрузке (`erp-internal.yaml`)."""

    crm_user_id = serializers.IntegerField(allow_null=True, help_text="Сотрудник в CRM; null — связи нет")
    name = serializers.CharField()
