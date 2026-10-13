"""
Плитки экрана поддержки считают ВСЮ выборку, а не текущую страницу.

Замер 24-08: 57 тикетов, из них 55 OPEN и два срочных — на 24-й и 57-й позиции сортировки,
то есть на страницах 2 и 3. Экран печатал «Всего 57» (из `count`) рядом с «Открытых 20» и
«Срочных 0» (из `results`). Плитка, считающая страницу, врёт уверенно: оператор видел ноль
срочных при двух живых.

Счётчики считаются одним `aggregate` по `filter_queryset(get_queryset())` — той же выборке,
что и список: с фильтрами и поиском, но без постраничного среза.
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import CustomUser, SystemRole
from core.models import SupportTicket

STATS_URL = "/api/v1/support/tickets/stats/"


def _api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def operator(db):
    return CustomUser.objects.create_user(
        is_superuser=True,
        email="support.operator@test.uz",
        username="support_operator",
        password="Probe1234!",
        role=SystemRole.objects.get(code="ADMIN"),
        is_active=True,
    )


@pytest.fixture
def author(db):
    return CustomUser.objects.create_user(
        email="author@support.test", username="author_support", password="x", is_active=True
    )


@pytest.fixture
def many_tickets(author, db):
    """25 обычных открытых + один СРОЧНЫЙ, заведомо не попадающий на первую страницу."""
    for index in range(25):
        SupportTicket.objects.create(
            subject=f"Обычный #{index}",
            description="текст",
            created_by=author,
            status=SupportTicket.STATUS_OPEN,
            priority=SupportTicket.PRIORITY_NORMAL,
        )
    urgent = SupportTicket.objects.create(
        subject="Срочный",
        description="горит",
        created_by=author,
        status=SupportTicket.STATUS_OPEN,
        priority=SupportTicket.PRIORITY_URGENT,
    )
    # Сортировка по умолчанию `-created_at`: самый старый уезжает в конец списка.
    SupportTicket.objects.filter(pk=urgent.pk).update(created_at="2020-01-01T00:00:00Z")
    return urgent


def test_urgent_is_counted_even_when_it_is_off_the_first_page(operator, many_tickets):
    client = _api(operator)

    page = client.get("/api/v1/support/tickets/?page_size=20").json()
    on_page = [row for row in page["results"] if row["priority"] == "URGENT"]
    assert on_page == [], "заготовка обязана держать срочный ВНЕ первой страницы"

    stats = client.get(STATS_URL).json()

    assert stats["total"] == 26
    assert stats["open"] == 26
    assert stats["urgent"] == 1, "срочный тикет со второй страницы обязан попасть в счётчик"


def test_stats_respect_the_same_filters_as_the_list(operator, many_tickets, author):
    SupportTicket.objects.create(
        subject="Закрытый",
        description="готово",
        created_by=author,
        status=SupportTicket.STATUS_CLOSED,
        priority=SupportTicket.PRIORITY_URGENT,
    )
    client = _api(operator)

    filtered = client.get(f"{STATS_URL}?status=OPEN").json()

    assert filtered["total"] == 26, "фильтр списка обязан применяться и к счётчикам"
    assert filtered["urgent"] == 1


def test_closed_and_resolved_urgent_tickets_are_not_counted_as_urgent(operator, author, db):
    """«Срочных» — это то, что ГОРИТ: закрытый срочный тикет в плитку не идёт."""
    for status in (SupportTicket.STATUS_CLOSED, SupportTicket.STATUS_RESOLVED):
        SupportTicket.objects.create(
            subject=f"Срочный {status}",
            description="—",
            created_by=author,
            status=status,
            priority=SupportTicket.PRIORITY_URGENT,
        )

    stats = _api(operator).get(STATS_URL).json()

    assert stats["total"] == 2
    assert stats["urgent"] == 0


def test_a_member_sees_only_their_own_tickets_in_the_counters(author, db):
    """Скоуп у счётчиков тот же, что у списка: чужие тикеты в них не просачиваются."""
    stranger = CustomUser.objects.create_user(
        email="stranger@support.test", username="stranger_support", password="x", is_active=True
    )
    SupportTicket.objects.create(subject="Мой", description="—", created_by=author)
    SupportTicket.objects.create(subject="Чужой", description="—", created_by=stranger)

    stats = _api(author).get(STATS_URL).json()

    assert stats["total"] == 1


def test_counters_are_one_aggregate_not_four_counts(operator, many_tickets, django_capture_on_commit_callbacks):
    """Реестр дорастёт до тысяч строк: четыре `.count()` превратились бы в задержку на
    каждый рендер (конвенция производительности проекта).

    Считаем именно обращения к ТАБЛИЦЕ ТИКЕТОВ, а не все запросы: к ним примешивается
    резолв пользователя запроса, и жёсткая цифра «всего запросов» ломалась бы от любой
    несвязанной правки middleware.
    """
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    client = _api(operator)
    client.get(STATS_URL)  # прогрев

    with CaptureQueriesContext(connection) as captured:
        client.get(STATS_URL)

    ticket_queries = [query["sql"] for query in captured.captured_queries if "core_supportticket" in query["sql"]]
    assert len(ticket_queries) == 1, ticket_queries
    assert ticket_queries[0].count("COUNT(") >= 4, "четыре счётчика обязаны считаться одним проходом"
