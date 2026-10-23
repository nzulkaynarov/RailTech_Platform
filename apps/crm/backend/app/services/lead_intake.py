"""Новые источники лидов (M3-CRM-05, ARCHITECTURE §17): форма «Запрос» с сайта и ручное создание.

Веб-лид: без аутентификации, антиспам по `domain/web_form.py` (honeypot, подписанный токен,
окно по IP — пороги из `settings.web_form`), источник `web`, попадает во «Входящие» в «Без
ответственного» (`owner_mode=paused`, бот ему написать не может — Telegram-идентичности нет).
Повторный запрос с тем же номером/почтой не плодит карточек: текст уходит заметкой в существующую.
Согласие на обработку ПДн (`consent: true`, DECISIONS Q-12) обязательно: у нового лида — это
`consent_given_at` с версией `WEB_CONSENT_VERSION` (бот всё равно спросит своё согласие — версия
другая); у существующей карточки согласие не перезаписывается, факт — в аудите `lead.web_request`.

Ручной лид: `phone` | `email` | `referral`, создавший менеджер становится ответственным
(стадия «В работе», как после «Забрать»). Совпадение телефона с лидом или контактом клиента —
409 с идентификатором найденного: фронт предлагает открыть, а не дублировать.
"""

from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bus import events as bus_events
from app.domain.contacts import contact_email
from app.domain.errors import ConflictError, RateLimitedError, Reason, ValidationFailedError
from app.domain.lead_sources import LeadSource, normalize_phone_e164
from app.domain.stages import OwnerMode, Stage, TransitionSource
from app.domain.web_form import (
    SlidingWindowLimiter,
    TokenVerdict,
    check_form_token,
    is_honeypot_filled,
    issue_form_token,
)
from app.models.leads import Lead, LeadNote
from app.repositories import events
from app.repositories import lead_intake as repo
from app.schemas.lead_intake import ManualLeadIn, WebFormToken, WebLeadIn
from app.schemas.settings import WebFormSettings
from app.security import audit
from app.security.principal import Principal
from app.services import stages
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

_HOUR_S = 3600
_SUMMARY_MAX = 2000
# Пометка заметки с повторным запросом с сайта (текст запроса — после неё).
WEB_NOTE_MARK = "[web] "
# Версия согласия из формы «Запрос» — не версия текста бота (`settings.texts.consent_version`):
# согласие формы — на обработку ПДн для связи, согласие бота — ещё и на обработку диалога ИИ.
WEB_CONSENT_VERSION = "web-form"
_TOKEN_REASONS = {
    TokenVerdict.INVALID: Reason.FORM_TOKEN_INVALID,
    TokenVerdict.TOO_FAST: Reason.FORM_TOO_FAST,
    TokenVerdict.EXPIRED: Reason.FORM_TOKEN_EXPIRED,
}


def _phone(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    value = normalize_phone_e164(raw)
    if value is None:
        raise ValidationFailedError(
            "phone must be in international format", reason=Reason.INVALID_PHONE, field="phone"
        )
    return value


def _clean(value: str | None, limit: int) -> str | None:
    text = (value or "").strip()
    return text[:limit] if text else None


def _audit_view(lead: Lead) -> dict[str, object]:
    return {
        "source": lead.source,
        "stage": lead.stage,
        "owner_mode": lead.owner_mode,
        "assigned_user_id": lead.assigned_user_id,
        "has_phone": lead.phone_e164 is not None,
        "has_email": lead.email is not None,
        "company_name": lead.company_name,
    }


class LeadIntakeService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        settings: SettingsService,
        form_key: bytes,
        limiter: SlidingWindowLimiter | None = None,
    ) -> None:
        self._sessions = sessions
        self._settings = settings
        self._key = form_key
        self._limiter = limiter or SlidingWindowLimiter(limit=1, window_s=_HOUR_S)

    async def form_token(self, now: datetime | None = None) -> WebFormToken:
        cfg = (await self._settings.get()).web_form
        moment = now or datetime.now(UTC)
        return WebFormToken(
            token=issue_form_token(self._key, moment),
            expires_at=moment + timedelta(minutes=cfg.token_ttl_minutes),
            min_fill_seconds=cfg.min_fill_seconds,
        )

    async def create_web(
        self, body: WebLeadIn, ip: str | None, now: datetime | None = None
    ) -> int | None:
        """202: id лида; None — honeypot (запрос молча отброшен). Ошибки антиспама — 422/429."""
        moment = now or datetime.now(UTC)
        cfg = (await self._settings.get()).web_form
        if is_honeypot_filled(body.website):
            logger.info("web_lead_honeypot", ip=ip)
            return None
        if not body.consent:
            # До антиспама: забытая галочка не расходует окно запросов по IP.
            raise ValidationFailedError(
                "consent to personal data processing is required",
                reason=Reason.CONSENT_REQUIRED,
                field="consent",
            )
        self._check_spam(body, cfg, ip, moment)
        phone, email = _phone(body.phone), contact_email(body.email)
        if phone is None and email is None:
            raise ValidationFailedError(
                "phone or email is required", reason=Reason.CONTACT_REQUIRED, field="phone"
            )
        text = body.text.strip()[: cfg.max_text_chars]
        async with self._sessions() as session, session.begin():
            existing = await _find_existing(session, phone, email)
            if existing is not None:
                return await _repeat_request(session, existing, text, ip, moment)
            lead = Lead(
                display_name=body.name.strip()[:255],
                language=body.language,
                stage=Stage.NEW.value,
                owner_mode=OwnerMode.PAUSED.value,
                source=LeadSource.WEB.value,
                phone_e164=phone,
                email=email,
                company_name=_clean(body.company, 255),
                need_summary=text[:_SUMMARY_MAX],
                last_lead_msg_at=moment,
                consent_given_at=moment,
                consent_version=WEB_CONSENT_VERSION,
            )
            session.add(lead)
            await session.flush()
            await audit.record(
                session,
                audit.Actor(None, "system", ip),
                "lead.create_web",
                "lead",
                lead.id,
                after={**_audit_view(lead), **_consent_view(moment)},
            )
            await bus_events.lead_created(session, lead, audit.Actor.system())
            await events.publish(session, "lead.updated", lead_id=lead.id, owner_mode="paused")
            logger.info("web_lead_created", lead_id=lead.id, language=lead.language)
            return lead.id

    def _check_spam(
        self, body: WebLeadIn, cfg: WebFormSettings, ip: str | None, now: datetime
    ) -> None:
        verdict = check_form_token(
            self._key,
            body.form_token,
            now,
            min_fill_s=cfg.min_fill_seconds,
            ttl_s=cfg.token_ttl_minutes * 60,
        )
        if verdict != TokenVerdict.OK:
            logger.info("web_lead_rejected", ip=ip, verdict=verdict.value)
            raise ValidationFailedError(
                "form token rejected", reason=_TOKEN_REASONS[verdict], field="form_token"
            )
        if not self._limiter.allow(ip or "unknown", now, limit=cfg.rate_limit_per_hour):
            logger.info("web_lead_rate_limited", ip=ip)
            raise RateLimitedError(
                "too many requests from this address", reason=Reason.RATE_LIMITED
            )

    async def create_manual(self, who: Principal, body: ManualLeadIn) -> int:
        """Лид по звонку/письму/рекомендации; создавший — ответственный, стадия «В работе»."""
        source = LeadSource(body.source)
        phone, email = _phone(body.phone), contact_email(body.email)
        _require_contact(source, phone, email)
        async with self._sessions() as session, session.begin():
            await _reject_duplicates(session, phone, email)
            lead = Lead(
                display_name=body.name.strip()[:255],
                language=body.language,
                stage=Stage.NEW.value,
                owner_mode=OwnerMode.HUMAN.value,
                assigned_user_id=who.user_id,
                source=source.value,
                phone_e164=phone,
                email=email,
                company_name=_clean(body.company, 255),
                need_summary=_clean(body.need, _SUMMARY_MAX),
            )
            session.add(lead)
            await session.flush()
            await bus_events.lead_created(session, lead, who.actor)
            await stages.transition(
                session,
                lead,
                Stage.IN_PROGRESS,
                TransitionSource.USER,
                reason="created manually",
                actor_user_id=who.user_id,
            )
            await audit.record(
                session, who.actor, "lead.create", "lead", lead.id, after=_audit_view(lead)
            )
            await events.publish(session, "lead.updated", lead_id=lead.id, owner_mode="human")
            logger.info("lead_created_manually", lead_id=lead.id, user_id=who.user_id)
            return lead.id


def _require_contact(source: LeadSource, phone: str | None, email: str | None) -> None:
    if source == LeadSource.PHONE and phone is None:
        raise ValidationFailedError(
            "phone is required for a call", reason=Reason.CONTACT_REQUIRED, field="phone"
        )
    if source == LeadSource.EMAIL and email is None:
        raise ValidationFailedError(
            "email is required for an email lead", reason=Reason.CONTACT_REQUIRED, field="email"
        )
    if phone is None and email is None:
        raise ValidationFailedError(
            "phone or email is required", reason=Reason.CONTACT_REQUIRED, field="phone"
        )


async def _find_existing(
    session: AsyncSession, phone: str | None, email: str | None
) -> Lead | None:
    lead = await repo.lead_by_phone(session, phone) if phone else None
    if lead is None and email:
        lead = await repo.lead_by_email(session, email)
    return lead


async def _reject_duplicates(session: AsyncSession, phone: str | None, email: str | None) -> None:
    """409 с идентификатором найденного: лид (по телефону или почте) или клиент (по телефону)."""
    lead = await _find_existing(session, phone, email)
    if lead is not None:
        raise ConflictError(
            "lead with this contact already exists",
            reason=Reason.LEAD_EXISTS,
            lead_id=lead.id,
            display_name=lead.display_name,
            field="phone" if phone and lead.phone_e164 == phone else "email",
        )
    client = await repo.client_by_phone(session, phone) if phone else None
    if client is not None:
        raise ConflictError(
            "client with this phone already exists",
            reason=Reason.CLIENT_EXISTS,
            client_id=client[0],
            client_name=client[1],
            field="phone",
        )


def _consent_view(moment: datetime) -> dict[str, object]:
    return {"consent_given_at": moment.isoformat(), "consent_version": WEB_CONSENT_VERSION}


async def _repeat_request(
    session: AsyncSession, lead: Lead, text: str, ip: str | None, moment: datetime
) -> int:
    """Повторный запрос с сайта от известного контакта — заметкой в существующую карточку.

    Согласие карточки не трогаем: у Telegram-лида, ещё не давшего согласие боту, оно открыло бы
    обработку диалога ИИ (квалификатор). Согласие формы фиксируется в аудите.
    """
    session.add(
        LeadNote(
            lead_id=lead.id, user_id=None, text=(WEB_NOTE_MARK + text)[:4000], visible_to_bot=True
        )
    )
    lead.notes_count += 1
    if not lead.need_summary:
        lead.need_summary = text[:_SUMMARY_MAX]
    await audit.record(
        session,
        audit.Actor(None, "system", ip),
        "lead.web_request",
        "lead",
        lead.id,
        after={"repeat": True, "source": lead.source, **_consent_view(moment)},
    )
    await events.publish(session, "lead.updated", lead_id=lead.id)
    logger.info("web_lead_repeat", lead_id=lead.id)
    return lead.id
