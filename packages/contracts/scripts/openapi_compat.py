"""Проверка совместимости OpenAPI в packages/contracts/openapi/*.yaml с базой (ADR-0016 п. 2, CONTRACTS §7).

    uv run python scripts/openapi_compat.py [--base REF]

Каждый файл openapi/*.yaml сравнивается с тем же файлом в REF (`git show REF:packages/contracts/openapi/<файл>`;
по умолчанию переменная CONTRACTS_BASE_REF, иначе точка ответвления HEAD от origin/main) командой `oasdiff breaking`.
Файла в базе нет — новый, не ломающее. Ломающее изменение уровня ERR (удалён путь или операция, удалено обязательное
поле ответа, новое обязательное поле или параметр запроса, сужен enum, сменён тип…) — код выхода 1; уровень WARN
печатается и не валит.

Мажор. Контракт версионируется мажором в пути (`/api/v1/…` → `/api/v2/…`, ADR-0016) с двойной публикацией: старый
мажор живёт рядом, пока не пройдёт срок отказа (oasdiff проверяет `deprecated` и `x-sunset`, 180 дней для stable).
Ломающее изменение (ERR) допустимо, только если в head поднят мажор `info.version`, появились пути нового мажора (`/v2`)
И изменение касается операции, помеченной в базе `deprecated`, или пути, которого в базе не было. Ломка операции
старого мажора без `deprecated` — красный, даже при поднятом мажоре.

До 1.0. Семвер разрешает ломать минором, пока мажор 0 (решение архитектора 2026-10-23): у контракта с `info.version`
0.x в head ломающее изменение (ERR) допустимо, если минорная версия head выше минорной базы (0.2.4 → 0.3.0); при той же
минорной (0.2.4 → 0.2.5) — красный; понижение версии — всегда ошибка. Переход 0.x → 1.0.0 с ломающим допустим (первая
стабильная). С 1.0 действует правило мажора выше. Правило «контракт раньше кода, обе стороны в одном PR» остаётся.

Исключения. Одноразовое ломающее изменение внутреннего API (например, снятие вебхука, у которого уже нет потребителей)
допускается только записью в `openapi-breaking-exceptions.yaml` — файл, id проверки, путь, причина, срок `until`
(не молча, видно в ревью). Исключение, которому ничего не соответствует, — предупреждение; с истёкшим `until` — ошибка.

oasdiff запускается закреплённой версией: бинарь из OASDIFF_BIN или одноразовый контейнер OASDIFF_IMAGE (Docker).
Код выхода 2 — проверка невозможна (нет базы, oasdiff, Docker, битый файл исключений) — это не «зелёное».
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONTRACTS = Path(__file__).resolve().parent.parent
OPENAPI_DIR = "openapi"
EXCEPTIONS_FILE = CONTRACTS / "openapi-breaking-exceptions.yaml"
DEFAULT_BASE = "origin/main"
# Закреплено тегом и digest (индекс образов): одна версия на CI и локальный запуск; обновлять осознанно, одним PR.
OASDIFF_VERSION = "v1.33.0"
OASDIFF_IMAGE = "tufin/oasdiff:v1.33.0@sha256:6263a96dd2ef0726c54e21fea9b8e1607eac4841add0079324b424c1f52b819c"
LEVEL_NAMES = {1: "INFO", 2: "WARN", 3: "ERR"}
ERR = 3
WARN = 2
PATH_MAJOR = re.compile(r"(?:^|/)v(\d+)(?:/|$)")


class CompatError(Exception):
    """Проверка не может быть выполнена (код выхода 2)."""


@dataclass(frozen=True)
class Change:
    id: str
    level: int
    text: str
    method: str
    path: str

    @property
    def where(self) -> str:
        return f"{self.method} {self.path}".strip()


@dataclass(frozen=True)
class Exemption:
    file: str
    id: str
    reason: str
    until: dt.date
    path: str | None = None
    operation: str | None = None

    def matches(self, file: str, change: Change) -> bool:
        return (
            self.file == file
            and self.id == change.id
            and (self.path is None or self.path == change.path)
            and (self.operation is None or self.operation.upper() == change.method.upper())
        )


Runner = Callable[[Path, Path], list[Change]]


# ─── oasdiff ───────────────────────────────────────────────────────────────────────────────────


def parse_changes(raw: str) -> list[Change]:
    data = json.loads(raw) if raw.strip() else []
    return [
        Change(
            id=str(item.get("id", "")),
            level=int(item.get("level", 0)),
            text=str(item.get("text", "")),
            method=str(item.get("operation", "")),
            path=str(item.get("path", "")),
        )
        for item in data
    ]


def run_oasdiff(base: Path, head: Path) -> list[Change]:
    """`oasdiff breaking base head` → список изменений уровня WARN и ERR. Файлы лежат в одном каталоге."""
    exe = os.environ.get("OASDIFF_BIN")
    # Срок отказа ADR-0016: старый мажор ≥ 6 месяцев — между deprecated (x-sunset) и удалением не меньше 180 дней.
    args = [
        "breaking",
        "--format",
        "json",
        "--fail-on",
        "ERR",
        "--deprecation-days-stable",
        "180",
        "--deprecation-days-beta",
        "180",
        # allOf сравнивать слитым: по ветвям oasdiff снижает ERR до WARN (суженный enum в allOf проходил бы зелёным).
        "--flatten-allof",
    ]
    if exe:
        cmd = [exe, *args, str(base), str(head)]
    else:
        if not shutil.which("docker"):
            raise CompatError(
                "openapi-compat: нет oasdiff — задайте OASDIFF_BIN=<путь к бинарю "
                f"{OASDIFF_VERSION}> или установите Docker (одноразовый контейнер {OASDIFF_IMAGE.split('@')[0]})"
            )
        root = base.parent
        cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{root}:/work:ro",
            OASDIFF_IMAGE,
            *args,
            f"/work/{base.name}",
            f"/work/{head.name}",
        ]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as e:  # OASDIFF_BIN не существует или не исполняется, docker пропал между проверкой и запуском
        raise CompatError(
            f"openapi-compat: не удалось запустить oasdiff ({cmd[0]}): {e}. "
            "Проверьте OASDIFF_BIN (бинарь oasdiff " + OASDIFF_VERSION + ") или уберите переменную и используйте Docker"
        ) from e
    # --fail-on ERR: код 1 — найдено ERR (вывод разбираем сами); другое ненулевое — oasdiff не смог (схема, образ).
    if done.returncode not in (0, 1):
        raise CompatError(f"openapi-compat: oasdiff завершился с кодом {done.returncode}:\n{done.stdout}{done.stderr}")
    try:
        return parse_changes(done.stdout)
    except (ValueError, TypeError) as e:
        raise CompatError(f"openapi-compat: не разобран вывод oasdiff: {e}\n{done.stdout}{done.stderr}") from e


# ─── мажор ─────────────────────────────────────────────────────────────────────────────────────


def info_major(spec: Mapping[str, Any]) -> int:
    version = str((spec.get("info") or {}).get("version", "0"))
    m = re.match(r"\s*v?(\d+)", version)
    return int(m.group(1)) if m else 0


def info_version(spec: Mapping[str, Any]) -> tuple[int, int, int]:
    """`info.version` → (мажор, минор, патч); недостающие части — 0, нечисловой префикс (`v`) допускается."""
    version = str((spec.get("info") or {}).get("version", "0"))
    m = re.match(r"\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", version)
    return (int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)) if m else (0, 0, 0)


def fmt_version(spec: Mapping[str, Any]) -> str:
    return ".".join(str(n) for n in info_version(spec))


def pre_release_allows(base: Mapping[str, Any], head: Mapping[str, Any]) -> str | None:
    """До 1.0 ломающее допустимо при поднятой минорной (0.2.4 → 0.3.0) и при переходе 0.x → 1.x; иначе None."""
    b, h = info_version(base), info_version(head)
    if b[0] == 0 and h[0] == 0 and h[1] > b[1]:
        return f"до 1.0 ломающее — повышением минорной версии ({fmt_version(base)} → {fmt_version(head)})"
    if b[0] == 0 and h[0] >= 1:
        return f"первая стабильная версия ({fmt_version(base)} → {fmt_version(head)})"
    return None


def path_majors(spec: Mapping[str, Any]) -> dict[int, set[str]]:
    """Мажор из префикса пути (/api/v2/…) → множество путей этого мажора."""
    out: dict[int, set[str]] = {}
    for p in spec.get("paths") or {}:
        m = PATH_MAJOR.search(p)
        if m:
            out.setdefault(int(m.group(1)), set()).add(p)
    return out


def major_bump_allows(base: Mapping[str, Any], head: Mapping[str, Any]) -> str | None:
    """Если head поднял мажор и добавил пути нового мажора — описание переноса; иначе None (ломающее недопустимо).

    Сам перенос ломающее не оправдывает: старый мажор живёт рядом (двойная публикация, ADR-0016). Допустимо только
    для операций, помеченных в базе `deprecated`, и для путей нового мажора — это решает `check_file`.
    """
    if info_major(head) <= info_major(base):
        return None
    base_paths = {p for paths in path_majors(base).values() for p in paths}
    new_majors = {
        major: sorted(paths - base_paths)
        for major, paths in path_majors(head).items()
        if major > max(path_majors(base) or {0}) and paths - base_paths
    }
    if not new_majors:
        return None
    major = max(new_majors)
    return f"мажор {info_major(base)} → {info_major(head)}, новые пути /v{major} ({len(new_majors[major])})"


def deprecated_in_base(base: Mapping[str, Any], change: Change) -> bool:
    """Операция, которой касается изменение, в базе уже помечена `deprecated: true` (снимается по сроку)."""
    path_item = (base.get("paths") or {}).get(change.path) or {}
    operation = path_item.get(change.method.lower()) if change.method else None
    return isinstance(operation, Mapping) and operation.get("deprecated") is True


def is_new_path(base: Mapping[str, Any], change: Change) -> bool:
    return change.path not in (base.get("paths") or {})


# ─── исключения ────────────────────────────────────────────────────────────────────────────────


def load_exemptions(path: Path = EXCEPTIONS_FILE) -> list[Exemption]:
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        items = data.get("exceptions") or []
        result = []
        for item in items:
            until = item["until"]
            if isinstance(until, str):
                until = dt.date.fromisoformat(until)
            reason = str(item["reason"]).strip()
            if not reason:
                raise ValueError("пустая причина")
            result.append(
                Exemption(
                    file=str(item["file"]),
                    id=str(item["id"]),
                    reason=reason,
                    until=until,
                    path=item.get("path"),
                    operation=item.get("operation"),
                )
            )
    except (KeyError, TypeError, ValueError, AttributeError, yaml.YAMLError) as e:
        raise CompatError(
            f"openapi-compat: {path.name} не разобран ({type(e).__name__}: {e}); "
            "нужны file, id, reason, until (ГГГГ-ММ-ДД), необязательно path и operation"
        ) from e
    return result


# ─── проверка ──────────────────────────────────────────────────────────────────────────────────


@dataclass
class Report:
    errors: list[str]
    warnings: list[str]
    notes: list[str]
    used: set[int]  # индексы применённых исключений


def check_file(
    name: str,
    base_spec: Mapping[str, Any] | None,
    head_spec: Mapping[str, Any],
    changes: Sequence[Change],
    exemptions: Sequence[Exemption],
    today: dt.date,
    used: set[int],
) -> tuple[list[str], list[str], list[str]]:
    """Ломающие (ERR) изменения файла с учётом мажора и исключений → (errors, warnings, notes)."""
    errors: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []
    if base_spec is None:
        return errors, warnings, [f"{name}: новый файл — не ломающее"]
    allowed = major_bump_allows(base_spec, head_spec)
    pre_release = pre_release_allows(base_spec, head_spec)
    if info_version(head_spec) < info_version(base_spec):
        errors.append(
            f"{name}: версия понижена ({fmt_version(base_spec)} → {fmt_version(head_spec)}) — "
            "info.version не может уменьшаться"
        )
    hint = ""
    if info_version(head_spec)[0] == 0:
        minor = info_version(base_spec)[1] + 1
        hint = f" — поднимите минорную версию (до 1.0, например до 0.{minor}.0) или новый мажор"
    for change in changes:
        line = f"{name} [{change.id}] {change.where}: {change.text}"
        if change.level < ERR:
            if change.level == WARN:
                warnings.append(line)
            continue
        if pre_release:
            notes.append(f"{line} — допустимо: {pre_release}")
            continue
        if allowed and (is_new_path(base_spec, change) or deprecated_in_base(base_spec, change)):
            notes.append(f"{line} — допустимо: {allowed}")
            continue
        hit = next((i for i, ex in enumerate(exemptions) if ex.matches(name, change)), None)
        if hit is not None:
            ex = exemptions[hit]
            used.add(hit)
            if ex.until < today:
                errors.append(f"{line} — исключение просрочено ({ex.until}): уберите изменение или продлите осознанно")
            else:
                notes.append(f"{line} — исключение до {ex.until}: {ex.reason}")
            continue
        errors.append(line + hint)
    return errors, warnings, notes


def _load(text: str, name: str) -> dict[str, Any]:
    try:
        spec = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise CompatError(f"openapi-compat: {name} не разобран: {e}") from e
    if not isinstance(spec, dict):
        raise CompatError(f"openapi-compat: {name} — не объект OpenAPI")
    return spec


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=CONTRACTS, check=True, capture_output=True, text=True).stdout


def default_base() -> str:
    """База по умолчанию: CONTRACTS_BASE_REF (CI задаёт явно), иначе точка ответвления от origin/main.

    Локально ветка часто отстаёт от main: сравнение с вершиной origin/main видело бы чужие слитые изменения как
    «удалённые» (ложный красный) и заставляло бы делать merge main ради зелёного. Точка ответвления сравнивает только
    свои изменения; итог слияния с main проверяет CI на PR (база — вершина main). Нет общей истории (мелкий клон) —
    вершина origin/main (DECISIONS 2026-10-28).
    """
    env = os.environ.get("CONTRACTS_BASE_REF")
    if env:
        return env
    try:
        return _git("merge-base", "HEAD", DEFAULT_BASE).strip() or DEFAULT_BASE
    except subprocess.CalledProcessError:
        return DEFAULT_BASE


def base_text(ref: str, name: str) -> str | None:
    """Файл в базе или None, если его там нет. Нет самой ссылки — CompatError."""
    try:
        _git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    except subprocess.CalledProcessError as e:
        raise CompatError(
            f"openapi-compat: база {ref!r} не найдена — git fetch origin main или другая база в CONTRACTS_BASE_REF"
        ) from e
    prefix = _git("rev-parse", "--show-prefix").strip()  # packages/contracts/
    full = f"{prefix}{OPENAPI_DIR}/{name}"
    if not _git("ls-tree", "--name-only", "--full-tree", ref, "--", full).strip():
        return None
    return _git("show", f"{ref}:{full}")


def check_all(
    ref: str,
    *,
    runner: Runner = run_oasdiff,
    exemptions: Sequence[Exemption] | None = None,
    today: dt.date | None = None,
    files: Sequence[Path] | None = None,
) -> Report:
    today = today or dt.date.today()
    exemptions = load_exemptions() if exemptions is None else exemptions
    files = files if files is not None else sorted((CONTRACTS / OPENAPI_DIR).glob("*.yaml"))
    report = Report([], [], [], set())
    with tempfile.TemporaryDirectory(prefix="oasdiff-") as tmp:
        for head_path in files:
            name = head_path.name
            head_text = head_path.read_text(encoding="utf-8")
            old = base_text(ref, name)
            base_spec = None if old is None else _load(old, f"{name} в {ref}")
            changes: list[Change] = []
            if old is not None:
                # Имена в общем каталоге: пути в сообщениях oasdiff не используются, берём только id/path/operation.
                base_file, head_file = Path(tmp) / f"base-{name}", Path(tmp) / f"head-{name}"
                base_file.write_text(old, encoding="utf-8")
                head_file.write_text(head_text, encoding="utf-8")
                changes = runner(base_file, head_file)
            errors, warnings, notes = check_file(
                name, base_spec, _load(head_text, name), changes, exemptions, today, report.used
            )
            report.errors += errors
            report.warnings += warnings
            report.notes += notes
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--base", default=None)
    args = ap.parse_args(argv)
    args.base = args.base or default_base()
    try:
        exemptions = load_exemptions()
        report = check_all(args.base, exemptions=exemptions)
    except CompatError as e:
        print(e, file=sys.stderr)
        return 2
    for i, ex in enumerate(exemptions):
        if i not in report.used:
            report.warnings.append(
                f"openapi-breaking-exceptions.yaml: исключение {ex.file} [{ex.id}] {ex.path or ''} "
                "ничему не соответствует — уберите, если изменение уже в базе"
            )
    for line in report.notes:
        print(f"openapi-compat: {line}")
    for line in report.warnings:
        print(f"openapi-compat: предупреждение: {line}")
    if report.errors:
        print(
            f"openapi-compat: ломающие изменения относительно {args.base} "
            "(до 1.0 — поднимите минорную версию info.version, например 0.2.4 → 0.3.0; с 1.0 — только новый мажор "
            "в пути /v2 с двойной публикацией, ADR-0016; CONTRACTS §7.1):"
        )
        for line in report.errors:
            print(f"  - {line}")
        return 1
    print(f"openapi-compat: совместимо с {args.base} (oasdiff {OASDIFF_VERSION})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
