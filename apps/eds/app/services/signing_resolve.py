"""«Кто вправе подписать вид X на сумму Y на дату D» (ADR-0024 п. 2–3): подбор по реестру полномочий с учётом замещения.

Шаг подписи маршрута вызывает `resolve` (подписанта подбирают правила реестра, модель не участвует) и `check_signer`
(может ли подписать именно этот сотрудник). `evaluate` — то же без базы: чистая функция над строками реестра и проекцией
сотрудников, поэтому каждая ветка проверяется быстрым тестом.

Правила:

1. Полномочие подходит, если оно не отозвано, началось и не кончилось на дату D, вид документа в его списке, сумма не
   больше лимита в той же валюте (сумма в другой валюте не пересчитывается — курс решает не реестр, а человек: такое
   полномочие отклоняется как `currency_mismatch`). Документ без суммы лимит не проверяет. Владелец должен быть активен.
2. Замещение (период в проекции CRM) **переводит задачу**, но не права. Если держатель на дату D отсутствует, задача
   идёт его заместителю (цепочка заместителей, петля — отказ); подписать заместитель может, только если у него
   самого есть подходящее полномочие. Нет — отклонение `deputy_without_authority` с объяснением; держатель сам
   подписать не может.
3. Ответ — кандидаты по порядку (сначала сами держатели, устав выше приказа, приказ выше доверенности, затем по имени),
   отклонённые с причиной и пошаговое объяснение (по-русски) для экрана и помощника.
"""

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import any_, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Employee, SigningAuthority
from app.models.signing import BASIS_CHARTER, BASIS_ORDER, BASIS_POWER_OF_ATTORNEY
from app.schemas.common import PersonRef
from app.schemas.signing import (
    RejectedSigner,
    RejectReason,
    ResolvedAuthority,
    ResolveStep,
    SignerCandidate,
    SignerCheck,
    SigningResolution,
)

MAX_DEPUTY_CHAIN = 5
_RANK = {BASIS_CHARTER: 0, BASIS_ORDER: 1, BASIS_POWER_OF_ATTORNEY: 2}


@dataclass(frozen=True, slots=True)
class Grant:
    """Строка реестра в том виде, в каком её читает подбор."""

    id: uuid.UUID
    crm_user_id: int
    kinds: tuple[str, ...]
    limit_amount: Decimal | None
    limit_currency: str | None
    basis: str
    basis_number: str | None
    basis_date: date | None
    valid_from: date
    valid_to: date | None
    revoked: bool = False


@dataclass(frozen=True, slots=True)
class Holder:
    """Сотрудник из проекции: активность, должность и замещение на период."""

    crm_user_id: int
    full_name: str
    position: str | None
    is_active: bool
    deputy_id: int | None = None
    deputy_from: date | None = None
    deputy_to: date | None = None

    def absent_on(self, day: date) -> bool:
        """Отсутствует на дату: назначен заместитель и день в периоде замещения (включительно)."""
        return (
            self.deputy_id is not None
            and self.deputy_from is not None
            and self.deputy_to is not None
            and self.deputy_from <= day <= self.deputy_to
        )


def money(amount: Decimal, currency: str) -> str:
    return f"{amount:,.2f}".replace(",", " ") + f" {currency}"


def basis_text(basis: str, number: str | None, issued: date | None, valid_to: date | None) -> str | None:
    """Основание для отметки на документе (ADR-0024 п. 5): устав — без отметки; формулу уточняет юрист (Q-SIGN-1)."""
    if basis == BASIS_CHARTER or number is None or issued is None:
        return None
    if basis == BASIS_ORDER:
        return f"Действует на основании приказа № {number} от {issued:%d.%m.%Y}"
    until = f" (до {valid_to:%d.%m.%Y})" if valid_to is not None else ""
    return f"Действует по доверенности № {number} от {issued:%d.%m.%Y}{until}"


def _problem(grant: Grant, day: date, amount: Decimal | None, currency: str | None) -> RejectReason | None:
    if grant.revoked:
        return "revoked"
    if day < grant.valid_from:
        return "not_started"
    if grant.valid_to is not None and day > grant.valid_to:
        return "expired"
    if grant.limit_amount is None or amount is None:
        return None
    if grant.limit_currency != currency:
        return "currency_mismatch"
    return "limit_exceeded" if amount > grant.limit_amount else None


def _ref(grant: Grant) -> ResolvedAuthority:
    return ResolvedAuthority(
        id=grant.id,
        basis=grant.basis,
        basis_number=grant.basis_number,
        basis_date=grant.basis_date,
        valid_to=grant.valid_to,
        limit_amount=None if grant.limit_amount is None else f"{grant.limit_amount:.2f}",
        limit_currency=grant.limit_currency,
    )


def _priority(grant: Grant) -> tuple[int, int, date]:
    return (_RANK.get(grant.basis, 9), 0 if grant.limit_amount is None else 1, grant.valid_to or date.max)


def _problem_text(reason: RejectReason, grant: Grant, name: str, kind: str, amount: Decimal | None) -> str:
    if reason == "revoked":
        return f"{name}: полномочие на «{kind}» отозвано."
    if reason == "not_started":
        return f"{name}: полномочие на «{kind}» начнётся {grant.valid_from:%d.%m.%Y}."
    if reason == "expired" and grant.valid_to is not None:
        return f"{name}: полномочие на «{kind}» закончилось {grant.valid_to:%d.%m.%Y}."
    if grant.limit_amount is None or grant.limit_currency is None:  # недостижимо: остальные причины — про лимит
        return f"{name}: полномочие не подходит."
    limit = money(grant.limit_amount, grant.limit_currency)
    if reason == "currency_mismatch":
        return f"{name}: лимит {limit} задан в другой валюте, чем документ — подписать нельзя без решения руководителя."
    asked = "" if amount is None else f" {money(amount, grant.limit_currency)} превышает"
    return f"{name}: сумма{asked} лимит {limit}."


def evaluate(
    *,
    kind: str,
    amount: Decimal | None,
    currency: str | None,
    on_date: date,
    grants: Sequence[Grant],
    people: Mapping[int, Holder],
    kind_label: str | None = None,
) -> SigningResolution:
    """Подбор подписантов по строкам реестра и проекции сотрудников; без базы и без часов (дата — аргумент)."""
    label = kind_label or kind
    steps: list[ResolveStep] = []
    rejected: list[RejectedSigner] = []
    by_user: dict[int, list[Grant]] = {}
    for grant in grants:
        if kind in grant.kinds:
            by_user.setdefault(grant.crm_user_id, []).append(grant)

    def person(user_id: int) -> PersonRef:
        holder = people.get(user_id)
        return PersonRef(crm_user_id=user_id, full_name=holder.full_name if holder else f"Сотрудник #{user_id}")

    def name(user_id: int) -> str:
        return person(user_id).full_name

    eligible: dict[int, list[Grant]] = {}
    for user_id, user_grants in sorted(by_user.items(), key=lambda item: name(item[0])):
        holder = people.get(user_id)
        if holder is None or not holder.is_active:
            rejected.append(
                RejectedSigner(
                    signer=person(user_id),
                    authority_id=None,
                    reason="holder_inactive",
                    message=f"{name(user_id)}: сотрудник отключён, полномочие не действует.",
                )
            )
            continue
        problems = [(g, _problem(g, on_date, amount, currency)) for g in user_grants]
        good = sorted((g for g, p in problems if p is None), key=_priority)
        if good:
            eligible[user_id] = good
            continue
        for grant, reason in sorted(problems, key=lambda gp: _priority(gp[0])):
            if reason is not None:
                rejected.append(
                    RejectedSigner(
                        signer=person(user_id),
                        authority_id=grant.id,
                        reason=reason,
                        message=_problem_text(reason, grant, name(user_id), label, amount),
                    )
                )

    for refusal in rejected:
        steps.append(ResolveStep(code=refusal.reason, crm_user_id=refusal.signer.crm_user_id, text=refusal.message))

    covers: dict[int, set[int]] = {}  # кандидат -> за кого получил задачу по замещению (пусто — только за себя)
    for user_id in eligible:
        holder = people[user_id]
        if not holder.absent_on(on_date):
            covers.setdefault(user_id, set())
            continue
        target = _deputy_target(user_id, people, on_date)
        until = f" по {holder.deputy_to:%d.%m.%Y}" if holder.deputy_to else ""
        if target is None:
            text = f"{name(user_id)} отсутствует{until}, а цепочка заместителей замкнулась — подписать некому."
            rejected.append(
                RejectedSigner(signer=person(user_id), authority_id=None, reason="deputy_loop", message=text)
            )
            steps.append(ResolveStep(code="deputy_loop", crm_user_id=user_id, text=text))
            continue
        absent_text = f"{name(user_id)} отсутствует{until}: задача подписи переходит к {name(target)}."
        rejected.append(RejectedSigner(signer=person(user_id), authority_id=None, reason="absent", message=absent_text))
        steps.append(ResolveStep(code="absent", crm_user_id=user_id, text=absent_text))
        if target in eligible:
            covers.setdefault(target, set()).add(user_id)
            continue
        text = (
            f"{name(target)} замещает {name(user_id)}, но своего полномочия на «{label}»"
            f"{'' if amount is None else ' на эту сумму'} не имеет — замещение прав не даёт."
        )
        rejected.append(
            RejectedSigner(signer=person(target), authority_id=None, reason="deputy_without_authority", message=text)
        )
        steps.append(ResolveStep(code="deputy_without_authority", crm_user_id=target, text=text))

    candidates = _candidates(eligible, covers, people, person)
    for found in candidates:
        steps.append(_candidate_step(found, name(found.signer.crm_user_id)))
    if not candidates:
        steps.append(_none_step(label, amount, currency, on_date, had_grants=bool(by_user)))
    return SigningResolution(
        kind=kind,
        amount=None if amount is None else f"{amount:.2f}",
        currency=currency,
        on_date=on_date,
        resolved=bool(candidates),
        candidates=candidates,
        rejected=rejected,
        explanation=steps,
    )


def _deputy_target(user_id: int, people: Mapping[int, Holder], day: date) -> int | None:
    """Кто фактически получает задачу отсутствующего: заместитель, его заместитель и так далее; петля — `None`."""
    seen = {user_id}
    current = user_id
    for _ in range(MAX_DEPUTY_CHAIN):
        holder = people.get(current)
        if holder is None or not holder.absent_on(day) or holder.deputy_id is None:
            return current if current != user_id else None
        if holder.deputy_id in seen:
            return None
        seen.add(holder.deputy_id)
        current = holder.deputy_id
    return None


def _candidates(
    eligible: Mapping[int, list[Grant]],
    covers: Mapping[int, set[int]],
    people: Mapping[int, Holder],
    person: Callable[[int], PersonRef],
) -> list[SignerCandidate]:
    items: list[SignerCandidate] = []
    for user_id, replaced in covers.items():
        grants = eligible[user_id]
        main = grants[0]
        items.append(
            SignerCandidate(
                signer=person(user_id),
                position=people[user_id].position,
                acting_for=sorted((person(c) for c in replaced), key=lambda p: (p.full_name, p.crm_user_id)),
                authority=_ref(main),
                authorities=[_ref(g) for g in grants],
                basis_text=basis_text(main.basis, main.basis_number, main.basis_date, main.valid_to),
            )
        )
    items.sort(
        key=lambda c: (not c.acting_for, _RANK.get(c.authority.basis, 9), c.signer.full_name, c.signer.crm_user_id)
    )
    return items


def _candidate_step(item: SignerCandidate, name: str) -> ResolveStep:
    if item.acting_for:
        who = ", ".join(p.full_name for p in item.acting_for)
        text = f"{name} вправе подписать по своему полномочию; задача пришла по замещению ({who})."
        return ResolveStep(code="candidate_deputy", crm_user_id=item.signer.crm_user_id, text=text)
    how = {BASIS_CHARTER: "по уставу", BASIS_ORDER: "по приказу"}.get(item.authority.basis, "по доверенности")
    return ResolveStep(code="candidate", crm_user_id=item.signer.crm_user_id, text=f"{name} вправе подписать {how}.")


def _none_step(label: str, amount: Decimal | None, currency: str | None, day: date, *, had_grants: bool) -> ResolveStep:
    if not had_grants:
        return ResolveStep(code="no_authority", crm_user_id=None, text=f"Полномочий на «{label}» никому не выдано.")
    what = f"«{label}»" + ("" if amount is None or currency is None else f" на {money(amount, currency)}")
    return ResolveStep(
        code="no_signer", crm_user_id=None, text=f"На {day:%d.%m.%Y} подписать {what} некому — см. причины выше."
    )


async def load_holders(session: AsyncSession, ids: set[int]) -> dict[int, Holder]:
    """Сотрудники проекции вместе с заместителями (одним запросом, чтобы пройти цепочку замещения)."""
    if not ids:
        return {}
    wanted = set(ids)
    loaded: dict[int, Holder] = {}
    for _ in range(MAX_DEPUTY_CHAIN + 1):
        rows = (
            await session.execute(select(Employee).where(Employee.crm_user_id.in_(wanted - loaded.keys())))
        ).scalars()
        fresh = {
            e.crm_user_id: Holder(
                crm_user_id=e.crm_user_id,
                full_name=e.full_name or f"Сотрудник #{e.crm_user_id}",
                position=e.position,
                is_active=e.is_active,
                deputy_id=e.deputy_crm_user_id,
                deputy_from=e.deputy_from,
                deputy_to=e.deputy_to,
            )
            for e in rows
        }
        loaded.update(fresh)
        wanted = {h.deputy_id for h in fresh.values() if h.deputy_id is not None} - loaded.keys()
        if not wanted:
            break
    return loaded


def to_grant(row: SigningAuthority) -> Grant:
    return Grant(
        id=row.id,
        crm_user_id=row.crm_user_id,
        kinds=tuple(row.kinds),
        limit_amount=row.limit_amount,
        limit_currency=row.limit_currency,
        basis=row.basis,
        basis_number=row.basis_number,
        basis_date=row.basis_date,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        revoked=row.revoked_at is not None,
    )


async def resolve(
    session: AsyncSession,
    *,
    kind: str,
    amount: Decimal | None,
    currency: str | None,
    on_date: date,
    kind_label: str | None = None,
) -> SigningResolution:
    """Кто вправе подписать `kind` на `amount` `currency` на дату `on_date` (с учётом замещения), по базе."""
    rows = (
        (await session.execute(select(SigningAuthority).where(literal(kind) == any_(SigningAuthority.kinds))))
        .scalars()
        .all()
    )
    grants = [to_grant(r) for r in rows]
    people = await load_holders(session, {g.crm_user_id for g in grants})
    return evaluate(
        kind=kind,
        amount=amount,
        currency=currency,
        on_date=on_date,
        grants=grants,
        people=people,
        kind_label=kind_label,
    )


async def check_signer(
    session: AsyncSession,
    crm_user_id: int,
    *,
    kind: str,
    amount: Decimal | None,
    currency: str | None,
    on_date: date,
    kind_label: str | None = None,
) -> SignerCheck:
    """Вправе ли именно этот сотрудник подписать: он среди кандидатов `resolve` (иначе — причина отказа)."""
    result = await resolve(session, kind=kind, amount=amount, currency=currency, on_date=on_date, kind_label=kind_label)
    return signer_check(result, crm_user_id)


def signer_check(result: SigningResolution, crm_user_id: int) -> SignerCheck:
    for item in result.candidates:
        if item.signer.crm_user_id == crm_user_id:
            return SignerCheck(allowed=True, candidate=item, reason=None, message="Вправе подписать.")
    for refusal in result.rejected:
        if refusal.signer.crm_user_id == crm_user_id:
            return SignerCheck(allowed=False, candidate=None, reason=refusal.reason, message=refusal.message)
    return SignerCheck(
        allowed=False,
        candidate=None,
        reason="no_authority",
        message="У сотрудника нет полномочия на этот вид документа. Полномочия ведутся в Настройках → «Права подписи».",
    )
