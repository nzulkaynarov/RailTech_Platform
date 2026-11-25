"""Read-only report: staff phones the single E.164 normaliser does not accept (ОНБ-1).

    python -m app staff-phones-check

Prints how many staff phones are already E.164, would be rewritten, or fail; failing user ids only
(no numbers in the output). Writes nothing.
"""

import argparse
import sys
from collections.abc import Iterable

from sqlalchemy import select

from app.container import get_container
from app.domain.lead_sources import normalize_phone_e164
from app.models.auth import User


def classify(rows: Iterable[tuple[int, str | None]]) -> tuple[int, int, list[int]]:
    """(already E.164, would change, ids that fail to normalise) for non-empty phones."""
    same = changed = 0
    failed: list[int] = []
    for user_id, phone in rows:
        if not phone or not phone.strip():
            continue
        normal = normalize_phone_e164(phone)
        if normal is None:
            failed.append(user_id)
        elif normal == phone:
            same += 1
        else:
            changed += 1
    return same, changed, failed


async def run(args: argparse.Namespace) -> int:
    del args
    container = get_container()
    try:
        async with container.session_factory() as session:
            rows = (await session.execute(select(User.id, User.phone))).all()
    finally:
        await container.aclose()
    same, changed, failed = classify((r[0], r[1]) for r in rows)
    sys.stdout.write(
        f"E.164 already: {same}; would be rewritten: {changed}; fail to normalise: {len(failed)}"
        f" (user ids: {', '.join(map(str, failed)) or '-'}).\n"
    )
    return 0
