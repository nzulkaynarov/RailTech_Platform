"""Mark or unmark service accounts by e-mail (ДОСТ-1п).

    python -m app mark-service-users EMAIL [EMAIL ...] [--unmark] [--apply]

Without `--apply` only reports what would change (dry-run). A service account (test or technical
login) stays in the plain employee list with a tag, but is left out of team screens: the
«who can do what» table, «the only one who decides», the list of people who grant access.
Prints e-mails and counts only. Safe to repeat.
"""

import argparse
import sys

from sqlalchemy import select

from app.container import get_container
from app.domain.errors import ConflictError
from app.models.auth import User
from app.security.audit import Actor
from app.services.user_views import UserPatch


async def run(args: argparse.Namespace) -> int:
    target = not args.unmark
    emails = sorted({e.strip().lower() for e in args.emails if e.strip()})
    container = get_container()
    changed: list[str] = []
    same: list[str] = []
    missing: list[str] = []
    blocked: list[str] = []
    try:
        async with container.session_factory() as session:
            rows = (await session.scalars(select(User).where(User.email.in_(emails)))).all()
        found = {u.email.lower(): u for u in rows}
        for email in emails:
            user = found.get(email)
            if user is None:
                missing.append(email)
            elif user.is_service == target:
                same.append(email)
            elif not args.apply:
                changed.append(email)
            else:
                # Через сервис: те же защиты «последний администратор/директор» и запись в журнал,
                # что и у API.
                try:
                    await container.user_service.update(
                        Actor.system(), user.id, UserPatch(is_service=target)
                    )
                except ConflictError as exc:
                    blocked.append(f"{email} ({exc.code})")
                else:
                    changed.append(email)
    finally:
        await container.aclose()
    mode = "применено" if args.apply else "dry-run, ничего не записано"
    word = "служебная" if target else "обычная"
    sys.stdout.write(f"Станет «{word}»: {len(changed)} ({mode}); уже так: {len(same)}; ")
    sys.stdout.write(f"не найдено: {len(missing)}.\n")
    for email in changed:
        sys.stdout.write(f"  {email}\n")
    for email in missing:
        sys.stdout.write(f"  не найден: {email}\n")
    for item in blocked:
        sys.stdout.write(f"  отклонено защитой: {item}\n")
    return 1 if blocked else 0
