#!/usr/bin/env python3
"""Черновик записи «Что нового» Платформы (W-REL) из строк «Для пользователей» влитых PR.

В описании PR (шаблон .github/PULL_REQUEST_TEMPLATE.md) — необязательная строка:

    Для пользователей (директор, менеджер): Резолюция теперь в одном окне с письмом.
    Для пользователей: Поиск находит счёт по номеру.          ← без скобок — для всех

Скрипт собирает такие строки из PR, влитых между прошлым и новым тегом выкладки (мерж-коммиты first-parent `main`), и
пишет запись `docs/kb/help/changelog/<дата>.md` в формате экрана «Что нового» (`- **Директор, Менеджер:** текст`).
Запись — черновик: deploy.yml открывает с ней черновой PR, архитектор правит формулировки и переводит PR в «Ready for
review» (так CI запускается от человека, а в main ничего не пишет бот).

    scripts/release_notes.py --from <sha> --to <sha> --repo owner/name [--date ГГГГ-ММ-ДД] [--out-dir каталог]
    scripts/release_notes.py --prs-json prs.json [--date …] [--out-dir …]     # без git и gh: [{number, title, body}]

Без `--out-dir` запись печатается. Строк нет — код 0, файл не пишется, в stdout «нет строк». Только stdlib.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

LINE = re.compile(
    r"^\s*(?:[-*]\s+)?(?:\*\*)?Для пользователей(?:\s*\(([^)]*)\))?\s*:(?:\*\*)?\s*(.*?)\s*$",
    re.IGNORECASE,
)
COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
MERGE = re.compile(r"^Merge pull request #(\d+) ")
# Заглушки из шаблона и «нечего сказать»: такие строки в запись не идут.
EMPTY = {"", "…", "...", "-", "—", "нет", "не требуется", "не нужно", "n/a"}
ALL = {"все", "всем", "для всех", "кому"}
MONTHS = (
    "января февраля марта апреля мая июня июля августа сентября октября ноября декабря"
).split()


@dataclass(frozen=True)
class Note:
    roles: tuple[str, ...]
    text: str
    pr: int


def _role(raw: str) -> str:
    raw = raw.strip()
    return raw[:1].upper() + raw[1:]


def notes_of(pr: dict[str, object]) -> list[Note]:
    """Строки «Для пользователей» одного PR; HTML-комментарии шаблона не считаются."""
    body = COMMENT.sub("", str(pr.get("body") or ""))
    out: list[Note] = []
    for line in body.splitlines():
        match = LINE.match(line)
        if not match:
            continue
        text = match.group(2).strip()
        if text.lower().rstrip(".") in EMPTY:
            continue
        roles = tuple(
            _role(r) for r in (match.group(1) or "").split(",") if r.strip() and r.strip().lower() not in ALL
        )
        out.append(Note(roles=roles, text=text[:1].upper() + text[1:], pr=int(str(pr["number"]))))
    return out


def human_date(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]} {day.year}"


def item(note: Note) -> str:
    who = ", ".join(note.roles) if note.roles else "Все"
    return f"- **{who}:** {note.text}"


def render(notes: list[Note], day: date, existing: str | None = None) -> str:
    """Новая запись или дополнение записи того же дня (две выкладки за день — один файл)."""
    prs = ", ".join(f"#{n}" for n in sorted({note.pr for note in notes}))
    items = "\n".join(item(note) for note in notes)
    if existing:
        return f"{existing.rstrip()}\n{items}\n<!-- PR: {prs} -->\n"
    head = f"---\ndate: {day.isoformat()}\ntitle: Обновление {human_date(day)}\n---\n"
    return f"{head}{items}\n<!-- Черновик из строк «Для пользователей» (PR: {prs}); заголовок и формулировки правит архитектор. -->\n"


def merged_prs(base: str, head: str) -> list[int]:
    """Номера PR, влитых в main между тегами: мерж-коммиты first-parent (кнопка «Merge pull request»)."""
    log = subprocess.run(
        ["git", "log", "--first-parent", "--merges", "--reverse", "--format=%s", f"{base}..{head}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [int(m.group(1)) for line in log.splitlines() if (m := MERGE.match(line))]


def fetch_pr(repo: str, number: int) -> dict[str, object]:
    raw = subprocess.run(
        ["gh", "api", f"repos/{repo}/pulls/{number}", "--jq", "{number, title, body}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    data: dict[str, object] = json.loads(raw)
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--from", dest="base")
    parser.add_argument("--to", dest="head")
    parser.add_argument("--repo")
    parser.add_argument("--prs-json", type=Path)
    parser.add_argument("--date", type=date.fromisoformat, default=datetime.now(UTC).date())
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args(argv)

    if args.prs_json:
        prs = json.loads(args.prs_json.read_text(encoding="utf-8"))
    else:
        if not (args.base and args.head and args.repo):
            parser.error("нужны --from, --to и --repo (или --prs-json)")
        prs = [fetch_pr(args.repo, n) for n in merged_prs(args.base, args.head)]

    notes = [note for pr in prs for note in notes_of(pr)]
    if not notes:
        print(f"нет строк «Для пользователей» в {len(prs)} PR — запись не нужна")
        return 0
    if args.out_dir is None:
        sys.stdout.write(render(notes, args.date))
        return 0
    target = args.out_dir / f"{args.date.isoformat()}.md"
    existing = target.read_text(encoding="utf-8") if target.exists() else None
    target.write_text(render(notes, args.date, existing), encoding="utf-8")
    print(f"{target}: пунктов {len(notes)} из {len({n.pr for n in notes})} PR")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
