"""Дверь в инженерную админку: только суперпользователь или группа `system_engineers`.

ADR-0001 разделил две плоскости: Unfold — инструмент ИНЖЕНЕРА (справочники, аудит, расписание
Celery, аварийные правки), React Admin — рабочее место бизнес-оператора. Но сама дверь стояла
открытой: Django пускает в админку любого с `is_staff`, а этот флаг раздавался бизнес-аккаунтам
(на 20-08 — 8 аккаунтов арендаторов на дев-стенде, в сидах `seed_data.json` он стоял у 9 из 10
тестовых пользователей). Прогон глазами 20-08 показал, что продавец-арендатор видел стартовый
экран админки с оборотом платформы и ключевыми метриками — то есть сводку по ЧУЖИМ компаниям.

Гейт стоит на входе, а не на отдельных страницах: список моделей и так закрыт правами, но
дашборд, поиск по админке и служебные вью проверяют только `has_permission`.

`system_engineers` — группа из ADR-0001: её заводит миграция `accounts/0006_system_engineers_group`,
членство раздаёт `manage.py grant_engineer`. Оба куска написаны ещё в апреле — не хватало ровно
этого гейта, поэтому флаг `is_staff` работал в обход задуманной схемы. Права внутри админки
по-прежнему решают модельные пермишены; членство лишь открывает дверь.
"""

from django.contrib.admin import ModelAdmin as DjangoModelAdmin
from unfold.sites import UnfoldAdminSite

from core.admin_mixins import ReadOnlyInspectionMixin

#: Единственная группа, членство в которой открывает инженерную админку.
SYSTEM_ENGINEERS_GROUP = "system_engineers"


def with_inspection_mode(admin_class):
    """Надеть на класс режим инспекции, если он его ещё не носит.

    Замер 26-08: обещание из докстринга `ReadOnlyInspectionMixin` — «NON-superuser staff remain
    in read-only inspection mode» — выполнялось у 28 админок из 60. У остальных 32 инженер с
    модельными правами правил и удалял: ЖУРНАЛ АКТИВНОСТИ (13 полей из 18 — то есть саму
    историю, по которой потом разбирают инцидент), историю правок КП, все справочники FSM
    (DealStage, QuoteStatus, ContractStatus, InvoiceStatus, ActStatus, FulfillmentStatus), все
    справочники accounts (SystemRole, WorkspaceRole, CompanyType, VerificationStatus, KYCDocType),
    а также `auth.Group` и `auth.Permission`.

    Последнее особенно едко: волна #599 сделала модельное право «вторым ключом» к опасным
    действиям — мастер компаний требует `accounts.add_company` СВЕРХ членства в инженерной
    группе. Через открытый `GroupAdmin` этот второй ключ выдавался себе самому.

    Раздавать миксин руками по классам — та же механика, что уже разъехалась: 24 класса
    объявлены без него, и 25-й появился бы незамеченным. Поэтому решение принимает САЙТ: всё,
    что в нём регистрируют, надевает режим инспекции — включая админки сторонних приложений
    (`django_celery_beat`, `token_blacklist`), куда миксин руками не добавить.

    Явный отказ возможен — `inspection_exempt = True` на классе, — но требует причины в
    комментарии рядом.
    """
    if admin_class is None:
        admin_class = DjangoModelAdmin
    if getattr(admin_class, "inspection_exempt", False):
        return admin_class
    if issubclass(admin_class, ReadOnlyInspectionMixin):
        return admin_class
    # Новый подкласс, а не правка чужого: тот же класс может быть зарегистрирован в другом
    # сайте (тесты, сторонние приложения), и мутировать его нельзя.
    return type(admin_class.__name__, (ReadOnlyInspectionMixin, admin_class), {})


class EngineeringAdminSite(UnfoldAdminSite):
    """Unfold-админка, доступная только инженерам платформы."""

    def register(self, model_or_iterable, admin_class=None, **options):
        # Режим инспекции надевается ЗДЕСЬ, на входе в сайт, а не в каждом файле admin.py.
        return super().register(model_or_iterable, with_inspection_mode(admin_class), **options)

    def has_permission(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_active or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        # `is_staff` сам по себе больше НЕ пропускает: он остался у бизнес-аккаунтов исторически
        # и раздаётся сидами. Пропуск — членство в инженерной группе.
        return user.groups.filter(name=SYSTEM_ENGINEERS_GROUP).exists()
