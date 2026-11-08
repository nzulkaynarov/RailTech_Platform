"""Magic Link authentication service (CONTRACTS §4, M2-ERP-01; FIX-14; B-MAIL-1).

Токен в базе — только SHA-256-хеш; в логи токен не пишется (максимум префикс из 6 символов).
Письмо уходит через шаблон ``portal_magic_link`` и попадает в ``EmailLog``; контакт ищет и письмо отправляет задача
Celery (FIX-15, FX-3), чтобы ни ответ, ни его время не выдавали известный адрес. В письме — ссылка и 6-значный код входа на 60 минут
(B-MAIL-1, `portal.services.login_code`); Reply-To — ответственный менеджер клиента, если он известен.
"""

import hashlib
import logging
from typing import Optional, Tuple

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from kombu.exceptions import KombuError
from parties.models import Contact, active_contact_q
from portal.exceptions import PortalGone, PortalTooManyRequests
from portal.models import MagicLinkToken, PortalSession
from portal.services.access import cabinet_company_q, company_has_cabinet_access
from portal.services.login_code import LOGIN_LINK_TTL, issue_login, reset_address_failures
from portal.services.mail_context import responsible_manager_email
from portal.services.tokens import hash_token, issue_portal_session, token_prefix
from portal.tasks import send_magic_link, send_magic_link_to_address
from redis.exceptions import RedisError
from rest_framework.exceptions import PermissionDenied

from notifications.emails import send_templated_email

logger = logging.getLogger(__name__)

RATE_WINDOW_SECONDS = 3600
# Анонимный запрос не ждёт Redis дольше секунды-двух. max_retries: 0 — иначе kombu повторяет подключение сам, ещё до публикации.
PUBLISH_TRANSPORT_OPTIONS = {"socket_connect_timeout": 1, "socket_timeout": 1, "max_retries": 0}


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
    """Контакт, которому можно отправить ссылку входа; ``None`` — нельзя (нет, архив, не клиент или адрес неоднозначен).

    Архивные компании и компании без типа CLIENT не входят (K0): поставщик с адресом в базе получает тот же
    ответ, что и неизвестный адрес. Если адрес указан у активных контактов РАЗНЫХ допущенных компаний, письмо
    не отправляется: ссылка открыла бы чужую компанию.
    """
    contacts = Contact.objects.filter(
        cabinet_company_q("company"), active_contact_q(), email__iexact=clean_email
    ).select_related("company")
    company_ids = list(contacts.order_by().values_list("company_id", flat=True).distinct()[:2])
    if not company_ids:
        return None
    if len(company_ids) > 1:
        logger.warning("Magic link requested for an e-mail shared by several companies; nothing sent")
        return None
    return contacts.filter(company_id=company_ids[0]).first()


def request_magic_link(email: str) -> None:
    """Принимает запрос ссылки входа: один и тот же путь для любого адреса, зарегистрирован он или нет (FX-3).

    Лимит 429 считает все адреса, поиск контакта и письмо — в задаче Celery. Внутри запроса нет ни чтения контактов, ни
    ветвления по их наличию, поэтому ни ответ, ни его время не выдают адрес. Отказ брокера или бэкенда результатов ответ не
    меняет, и его ожидание ограничено таймаутами сокета: клиент запросит ссылку ещё раз.
    """
    clean_email = email.strip().lower()
    _check_address_rate_limit(clean_email)
    # Новый код — счёт неверных попыток заново; для любого адреса, иначе сброс выдал бы, что адрес известен.
    reset_address_failures(clean_email)

    app = send_magic_link_to_address.app
    try:
        # Своё соединение с таймаутами, без повторов и без бэкенда результатов: иначе недоступный Redis держал бы анонимный
        # запрос (при отказе бэкенда — около 19 с и голый RuntimeError). argsrepr прячет адрес только при первой доставке:
        # при повторе задачи Celery показывает настоящие аргументы.
        with app.connection_for_write(transport_options=PUBLISH_TRANSPORT_OPTIONS) as connection:
            send_magic_link_to_address.apply_async(
                args=[clean_email],
                argsrepr="('<address>',)",
                ignore_result=True,
                retry=False,
                connection=connection,
            )
    except (KombuError, OSError, RedisError) as exc:  # отказ брокера или бэкенда, ошибки кода не прячем
        logger.warning("Login link request was not queued (%s)", type(exc).__name__)


def queue_login_link_for_address(clean_email: str) -> bool:
    """Шаг воркера: находит контакт по адресу и ставит письмо; ``False`` — слать некому (ответ клиенту от этого не зависит).

    В очередь письма идёт лишь id контакта — токен рождается внутри `send_magic_link` и в брокер не попадает.
    """
    contact = find_login_contact(clean_email)
    if contact is None:
        logger.info("Magic link requested for an unknown, archived, non-client or ambiguous e-mail")
        return False
    send_magic_link.delay(contact.pk)
    logger.info("Magic link queued for contact %s", contact.pk)
    return True


def deliver_login_link(contact_id: int) -> bool:
    """Выпускает одноразовые ссылку и код входа на 60 минут и отправляет письмо; ``False`` — слать некому.

    Вызывается задачей `portal.tasks.send_magic_link`. Контакт и компания проверяются заново: между запросом
    и выполнением задачи компанию могли отправить в архив или снять с неё тип CLIENT.
    """
    contact = (
        Contact.objects.filter(cabinet_company_q("company"), active_contact_q(), pk=contact_id)
        .select_related("company")
        .first()
    )
    if contact is None or not contact.email:
        logger.info("Magic link not sent: contact %s is gone, archived or has no e-mail", contact_id)
        return False

    # Гасим только прежние ссылки и коды входа: приглашение из ERP (24 часа) остаётся рабочим.
    issued = issue_login(contact, MagicLinkToken.PURPOSE_LOGIN, LOGIN_LINK_TTL)
    reply_to = responsible_manager_email(contact.company_id)

    email_log = send_templated_email(
        "portal_magic_link",
        context={
            "contact_name": contact.name,
            "company_name": contact.company.name,
            "login_url": build_login_url(issued.raw_token),
            "login_code": issued.code,
            "expires_minutes": int(LOGIN_LINK_TTL.total_seconds() // 60),
        },
        to=[contact.email.strip().lower()],
        channel="transactional",
        language=contact.language,
        reply_to=[reply_to] if reply_to else None,
        redact=(issued.code,),
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

        if not company_has_cabinet_access(token_obj.contact.company_id):
            logger.info("Magic link for a company without cabinet access rejected (contact %s)", token_obj.contact_id)
            raise PermissionDenied("FORBIDDEN")

        if token_obj.contact.is_archived:
            logger.info("Magic link of an archived contact rejected (contact %s)", token_obj.contact_id)
            raise PermissionDenied("FORBIDDEN")

        token_obj.used_at = timezone.now()
        token_obj.save(update_fields=["used_at"])
        return issue_portal_session(token_obj.contact, "magic_link", ip_address=ip_address, user_agent=user_agent)
