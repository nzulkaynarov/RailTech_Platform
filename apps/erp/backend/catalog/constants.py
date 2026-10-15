"""Словари двух слоёв каталога (M1-ERP-07, BUSINESS §8 паттерн 3–4, §10.1, §13).

Модуль без моделей: его читают и `catalog`, и `parties.CompanySettings` (политика компании по
умолчанию), не создавая зависимости миграций между приложениями.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class PriceVisibility(models.TextChoices):
    """Политика видимости цены карточки в опубликованном слое.

    Решение владельца 2026-10-13 (BUSINESS §13): цены и наличие — только клиенту в кабинете;
    лиду и боту вне кабинета — «по запросу». Значение по умолчанию — «по запросу» (BUSINESS §12):
    цену публикуют решением на карточке или политикой компании.
    """

    CABINET = "cabinet", _("Показывать цену в кабинете")
    ON_REQUEST = "on_request", _("Цена по запросу")


class FulfillmentPolicy(models.TextChoices):
    """Политика исполнения услуги («сервисный товар» Odoo: предоплата / по этапам / по часам).

    Только у услуг: у товара исполнение — поставка, политика пустая.
    """

    FIXED = "fixed", _("Фиксированная цена")
    MILESTONES = "milestones", _("По этапам")
    TIME = "time", _("По времени")


#: Режимы проекции опубликованного слоя (CONTRACTS §2 `mode=lead|client`, §5 `prospect|customer`).
#: `lead` — лид и бот вне кабинета: перечень без цены, наличия и срока. `client` — клиент в
#: кабинете и бот в сервисном режиме: + цена (если политика `cabinet`), наличие как статус, срок.
MODE_LEAD = "lead"
MODE_CLIENT = "client"
PROJECTION_MODES = (MODE_LEAD, MODE_CLIENT)

#: Порог публикации по умолчанию — все обязательные поля карточки (Akeneo: 100 % полноты канала).
DEFAULT_PUBLISH_THRESHOLD = 100
