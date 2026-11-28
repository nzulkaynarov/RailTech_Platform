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
from app.models.auth import User


async def run(args: argparse.Namespace) -> int:
    target = not args.unmark
    emails = sorted({e.strip().lower() for e in args.emails if e.strip()})
    container = get_container()
    changed: list[str] = []
    same: list[str] = []
    missing: list[str] = []
    try:
        async with container.session_factory() as session, session.begin():
            rows = (
                await session.scalars(select(User).where(User.email.in_(emails)).with_for_update())
            ).all()
            found = {u.email.lower(): u for u in rows}
            for email in emails:
                user = found.get(email)
                if user is None:
                    missing.append(email)
                elif user.is_service == target:
                    same.append(email)
                else:
                    changed.append(email)
                    user.is_service = target
            if not args.apply:
                await session.rollback()
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
    return 0
