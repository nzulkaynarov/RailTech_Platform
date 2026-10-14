"""«Сегодня» для бизнеса — дата в часовом поясе компании, а не в UTC.

`timezone.now()` возвращает МОМЕНТ в UTC (USE_TZ=True), и `.date()` от него — это дата
по Гринвичу. Бизнес работает в `Asia/Tashkent` (UTC+5), поэтому каждую ночь с 00:00 до
05:00 по Ташкенту дата UTC отстаёт на сутки. Пять часов в сутки это ломало:

* `Invoice.issued_at` / `Act.issued_at` — документ печатался вчерашней датой, а от неё
  считается срок оплаты (`payment_terms_days`), то есть съезжал и он;
* `Quote.valid_until` = сегодня + N — КП жило на день меньше обещанного;
* `HSCode.is_active` и полнота карточки: выведенный вчера код ещё пять часов считался
  действующим и наследовался в новые КП — ровно та «тихая порча», против которой
  написан трек T2;
* просрочка отгрузок и напоминания об оплате в `crm/tasks.py`.

Канон Django для «сегодня в текущем поясе» — `timezone.localdate()`. Тест держит
границу: возврат к дате из `now()` в продовом коде снова внесёт эту ошибку. Шаблон
ищется регулярным выражением (см. `UTC_DATE_PATTERN`), чтобы этот файл не срабатывал
на самого себя.

Голый `datetime.date.today()` тоже под запретом (W2, 14-08). Он ДАВАЛ верную дату — но
лишь потому, что Django при загрузке настроек выставляет процессу `TZ=settings.TIME_ZONE`
и делает `time.tzset()`. Это побочный эффект инициализации, а не контракт: он не
действует там, где настройки грузятся иначе или процесс переопределяет TZ, и молча
возвращает UTC-дату. Было 4 таких места — плейсхолдер `{{today}}` в печатных документах,
проверка просрочки КП при разборе файла, дата курса ЦБ, синк ТН ВЭД; все переведены на
`localdate()`, который говорит намерение явно и не зависит от окружения.
"""

import pathlib
import re

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]

APPS = ("accounts", "catalog", "core", "crm", "master_data", "notifications", "sourcing")

#: Каталоги, которые не являются продовым кодом: тесты фиксируют СВОИ даты и вправе
#: строить их как угодно, миграции заморожены и переписывать их нельзя.
SKIP_PARTS = ("migrations", "tests")

#: Оба шаблона пишутся через экранирование, чтобы этот файл не срабатывал на самого себя.
#: 1) дата, снятая с момента UTC; 2) голый `date.today()` / `datetime.date.today()`.
UTC_DATE_PATTERN = re.compile(r"timezone\.now\(\)\s*\.\s*date\(\)")
NAIVE_TODAY_PATTERN = re.compile(r"(?<!local)\bdate\s*\.\s*today\(\)")

FORBIDDEN = (
    (UTC_DATE_PATTERN, "дата снята с момента UTC"),
    (NAIVE_TODAY_PATTERN, "голый date.today() — зависит от TZ процесса"),
)


def _production_sources():
    for app in APPS:
        for path in (BACKEND_DIR / app).rglob("*.py"):
            if any(part in SKIP_PARTS for part in path.parts):
                continue
            if path.name.startswith("test_") or path.name.endswith("_test.py"):
                continue
            yield path


def test_business_dates_are_not_taken_from_utc():
    offenders = []
    for path in _production_sources():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for pattern, reason in FORBIDDEN:
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(BACKEND_DIR)}:{number} ({reason}): {line.strip()}")

    assert not offenders, (
        "«Сегодня» для бизнеса (Asia/Tashkent, UTC+5) считается ТОЛЬКО через "
        "`timezone.localdate()`: дата от `now()` — это UTC и с 00:00 до 05:00 по Ташкенту "
        "отстаёт на сутки, а голый `date.today()` верен лишь пока Django выставил процессу "
        "TZ (побочный эффект, не контракт):\n  " + "\n  ".join(offenders)
    )
