"""Magic Link authentication service (CONTRACTS §4, M2-ERP-01; FIX-14).

Токен в базе — только SHA-256-хеш; в логи токен не пишется (максимум префикс из 6 символов).
Письмо уходит через шаблон ``portal_magic_link`` и попадает в ``EmailLog``; выпускает и отправляет его задача
Celery (FIX-15), чтобы время ответа не выдавало известный адрес.
"""

import hashlib
import logging
from datetime import timedelta
from typing import Optional, Tuple

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from parties.models import Contact, active_company_q
from portal.exceptions import PortalGone, PortalTooManyRequests
from portal.models import MagicLinkToken, PortalSession
from portal.services.access import company_in_circulation
from portal.services.tokens import generate_token, hash_token, issue_portal_session, token_prefix
from portal.tasks import send_magic_link
from rest_framework.exceptions import PermissionDenied

from notifications.emails import send_templated_email

logger = logging.getLogger(__name__)

LOGIN_LINK_TTL = timedelta(minutes=15)
RATE_WINDOW_SECONDS = 3600


def build_login_url(raw_token: str) -> str:
    """Ссылка из письма: токен во фрагменте (`#token=`), в пути и query его нет (контракт, FIX-20/21).

    Фрагмент браузер не отправляет на сервер: Caddy, прокси и access-логи токена не видят; Cabinet читает его из
    `location.hash` и меняет на сессию через `POST /auth/magic`.
    """
    cabinet_url = getattr(settings, "CABINET_URL", "http://cabinet.localhost").rstrip("/")
    return f"{cabinet_url}/auth/magic#token={raw_token}"


def _check_address_rate_limit(clean_email: str) -> None:
    """Не больше ``PORTAL_MAGIC_LINK_MAX_PER_HOUR`` запросов в час на адрес.

    Считаются все запросы, а не только отправленные письма: иначе 429 выдавал бы, что адрес есть в базе.
    """
    limit = getattr(settings, "PORTAL_MAGIC_LINK_MAX_PER_HOUR", 5)
    key = "portal:magic-link:" + hashlib.sha256(clean_email.encode("utf-8")).hexdigest()[:32]
    cache.add(key, 0, RATE_WINDOW_SECONDS)
    try:
        count = cache.incr(key)
    except ValueError:  # ключ истёк между add и incr
        cache.set(key, 1, RATE_WINDOW_SECONDS)
        count = 1
    if count > limit:
        logger.info("Magic link rate limit exceeded (address hash %s)", key[-6:])
        raise PortalTooManyRequests("TOO_MANY_REQUESTS")


def find_login_contact(clean_email: str) -> Optional[Contact]:
    """Контакт, которому можно отправить ссылку входа; ``None`` — нельзя (нет, архив или адрес неоднозначен).

    Архивные компании не входят. Если адрес указан у активных контактов РАЗНЫХ компаний, письмо
    не отправляется: ссылка открыла бы чужую компанию.
    """
    contacts = Contact.objects.filter(active_company_q("company"), email__iexact=clean_email).select_related("company")
    company_ids = list(contacts.order_by().values_list("company_id", flat=True).distinct()[:2])
    if not company_ids:
        return None
    if len(company_ids) > 1:
        logger.warning("Magic link requested for an e-mail shared by several companies; nothing sent")
        return None
    return contacts.filter(company_id=company_ids[0]).first()


def request_magic_link(email: str) -> bool:
    """Создаёт одноразовую ссылку на 15 минут и отправляет письмо.

    Всегда возвращает True (200), чтобы не раскрывать наличие адреса в базе; единственное исключение —
    429 по лимиту на адрес, он одинаков для известных и неизвестных адресов.
    """
    clean_email = email.strip().lower()
    _check_address_rate_limit(clean_email)

    contact = find_login_contact(clean_email)
    if contact is None:
        logger.info("Magic link requested for an unknown, archived or ambiguous e-mail")
        return True

    # Ссылку выпускает и отправляет задача Celery (portal.tasks.send_magic_link): письмо уходит вне потока запроса,
    # иначе по времени ответа (SMTP только у известного адреса) видно, есть ли адрес в базе. В очередь идёт лишь
    # id контакта — токен в брокер и в журнал воркера не попадает. Сбой очереди ответ не меняет: он такой же, как
    # для неизвестного адреса, а клиент запросит ссылку ещё раз.
    try:
        send_magic_link.delay(contact.pk)
    except Exception as exc:  # noqa: BLE001 — брокер недоступен
        logger.warning("Magic link was not queued for contact %s (%s)", contact.pk, type(exc).__name__)
        return True
    logger.info("Magic link queued for contact %s", contact.pk)
    return True


def deliver_login_link(contact_id: int) -> bool:
    """Выпускает одноразовую ссылку входа на 15 минут и отправляет письмо; ``False`` — слать некому.

    Вызывается задачей `portal.tasks.send_magic_link`. Контакт и компания проверяются заново: между запросом
    и выполнением задачи компанию могли отправить в архив.
    """
    contact = Contact.objects.filter(active_company_q("company"), pk=contact_id).select_related("company").first()
    if contact is None or not contact.email:
        logger.info("Magic link not sent: contact %s is gone, archived or has no e-mail", contact_id)
        return False

    # Гасим только прежние ссылки входа: приглашение из ERP (24 часа) остаётся рабочим.
    MagicLinkToken.objects.filter(contact=contact, purpose=MagicLinkToken.PURPOSE_LOGIN, used_at__isnull=True).update(
        used_at=timezone.now()
    )

    raw_token = generate_token()
    MagicLinkToken.objects.create(
        token_hash=hash_token(raw_token),
        contact=contact,
        purpose=MagicLinkToken.PURPOSE_LOGIN,
        expires_at=timezone.now() + LOGIN_LINK_TTL,
    )

    email_log = send_templated_email(
        "portal_magic_link",
        context={
            "contact_name": contact.name,
            "company_name": contact.company.name,
            "login_url": build_login_url(raw_token),
        },
        to=[contact.email.strip().lower()],
        channel="transactional",
        language=contact.language,
    )
    logger.info("Magic link sent for contact %s (email log %s)", contact.pk, getattr(email_log, "pk", None))
    return True


def exchange_magic_link(
    token: str,
    ip_address: str = None,
    user_agent: str = "",
) -> Tuple[PortalSession, str]:
    """Обменивает одноразовый токен magic-link на сессию портала (410 при просрочке/повторе).

    Погашение атомарно: строка блокируется ``select_for_update``, ``used_at`` и сессия пишутся в одной
    транзакции, поэтому второй параллельный запрос с тем же токеном получает 410.
    """
    token_hash = hash_token(token)
    with transaction.atomic():
        token_obj = (
            MagicLinkToken.objects.select_for_update(of=("self",))
            .select_related("contact__company")
            .filter(token_hash=token_hash)
            .first()
        )
        if not token_obj or not token_obj.is_valid():
            logger.info("Magic link token invalid or expired (%s…)", token_prefix(token_hash))
            raise PortalGone("MAGIC_LINK_EXPIRED")

        if not company_in_circulation(token_obj.contact.company_id):
            logger.info("Magic link for archived company rejected (contact %s)", token_obj.contact_id)
            raise PermissionDenied("FORBIDDEN")

        token_obj.used_at = timezone.now()
        token_obj.save(update_fields=["used_at"])
        return issue_portal_session(token_obj.contact, "magic_link", ip_address=ip_address, user_agent=user_agent)
