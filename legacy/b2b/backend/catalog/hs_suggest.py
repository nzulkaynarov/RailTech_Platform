"""Подсказка кода ТН ВЭД по наименованию товара — ВЫБОР из справочника, а не сочинение.

Ключевая мысль: придуманный код ТН ВЭД хуже отсутствующего. Десять цифр выглядят одинаково
убедительно и когда они верные, и когда выдуманы, а узнает продавец об ошибке на границе.
Поэтому подсказка работает ТОЛЬКО поверх наполненного классификатора (`master_data.HSCode`):
кандидаты выбираются из закрытого списка, и у каждого есть код-первоисточник.

Порядок такой же, как у подбора товара: сначала точное совпадение кода, затем поиск по
наименованию позиции. Языковая модель сюда не входит — это детерминированный retrieval; когда
справочник наполнится, она сможет ВЫБИРАТЬ из этих кандидатов (RAG), но не генерировать цифры.

Справочник пуст — возвращаем пусто и молчим: система обязана работать без него, код тогда
вводится вручную, как сегодня.
"""

from __future__ import annotations

import re

from django.contrib.postgres.search import TrigramWordSimilarity
from django.db.models import F, Func, Q, TextField, Value
from django.db.models.functions import Greatest


def suggest_hs_codes(text: str, limit: int = 5, min_level: int = 6) -> list[dict]:
    """Кандидаты `[{code, name, level, score}]` по наименованию товара.

    `min_level` отсекает слишком общие ветки: группа «84 — Реакторы ядерные, котлы,
    оборудование» в карточке бесполезна, продавцу нужен рабочий уровень субпозиции и ниже.
    """
    from master_data.models import HSCode

    query = (text or "").strip()
    if not query:
        return []

    # Закрытые коды (valid_until в прошлом) не предлагаются: после автосинка с tarif.customs.uz
    # исчезнувшие из редакции коды закрываются датой, и подсказывать их в НОВУЮ карточку нельзя —
    # декларацию с выведенным кодом развернут. `is_known_code` при этом закрытые коды по-прежнему
    # признаёт: старые документы держат старые коды законно.
    from django.utils import timezone

    today = timezone.now().date()
    rows = HSCode.objects.filter(level__gte=min_level).exclude(valid_until__lt=today)
    # Пользователь мог ввести сам код — тогда это точный поиск, а не текстовый.
    digits = "".join(ch for ch in query if ch.isdigit())
    if len(digits) >= 4:
        exact = list(
            HSCode.objects.filter(Q(code=digits) | Q(code__startswith=digits))
            .order_by("code")[:limit]
            .values("code", "name", "level")
        )
        if exact:
            return [dict(row, score=1.0) for row in exact]

    # ПОСЛОВНОЕ сходство, а не сходство целых строк, и не только по запросу целиком, но и по
    # КАЖДОМУ его значимому слову. Две причины, обе с живой базы ГТК (13 тыс. кодов):
    #
    # 1. Имена — длинные пути по дереву через двоеточия. Короткий запрос против такой строки
    #    целиком даёт почти ноль: «тормозная колодка» не находила НИЧЕГО, хотя позиция 6813 81
    #    в базе есть (word-сходство 0.571 против нуля у сходства целых строк).
    # 2. Словарь таможни ≠ словарь инженера: «стрелочный перевод» в номенклатуре зовётся
    #    «рельсы переводные, крестовины глухого пересечения». Слово «перевод» дотягивается до
    #    «переводные», только если мерять по словам запроса, а не по всей фразе.
    #
    # Retrieval здесь отвечает за ОТЗЫВ, точность — за моделью и человеком: лишний кандидат в
    # хвосте безвреден (модель обязана вернуть '' если ничего не подходит), а пропущенный
    # правильный — невосполним, модель из ничего выбрать не может.
    words = [w for w in re.split(r"[^\wА-Яа-яЁё]+", query) if len(w) >= 4][:5]

    def best_similarity(target):
        similarities = [TrigramWordSimilarity(query, target)] + [TrigramWordSimilarity(w, target) for w in words]
        return similarities[0] if len(similarities) == 1 else Greatest(*similarities)

    # Имя ГТК — путь по дереву через «:», и у СОСЕДНИХ кодов он почти одинаков: «перевод»
    # матчился во всей ветке 7302 с равным score, сортировка при равенстве шла по коду, и
    # правильный 7302300000 не влезал в лимит, вытесненный собственными братьями. Последний
    # сегмент пути — СОБСТВЕННОЕ имя позиции («рельсы переводные, крестовины…»), различающее
    # братьев; он и есть главный сигнал ранжирования, полный путь — вторичный.
    leaf = Func(F("name"), Value(r"^.*:"), Value(""), function="regexp_replace", output_field=TextField())
    scored = (
        rows.annotate(leaf_score=best_similarity(leaf), score=best_similarity("name"))
        .filter(score__gt=0.3)
        .order_by("-leaf_score", "-score", "code")[:limit]
        .values("code", "name", "level", "score", "leaf_score")
    )
    return [
        {
            "code": row["code"],
            "name": row["name"],
            "level": row["level"],
            "score": round(float(max(row["score"], row["leaf_score"] or 0)), 3),
        }
        for row in scored
    ]


def is_known_code(code: str) -> bool:
    """Есть ли код в справочнике. Пустой справочник → True: не блокируем работу без данных."""
    from master_data.models import HSCode

    digits = "".join(ch for ch in (code or "") if ch.isdigit())
    if not digits:
        return False
    if not HSCode.objects.exists():
        return True
    return HSCode.objects.filter(code=digits).exists()
