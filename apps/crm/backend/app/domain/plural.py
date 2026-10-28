"""Согласование числа в русских текстах CRM: «1 задача», «2 задачи», «5 задач», «21 задача»."""


def plural_ru(n: int, one: str, few: str, many: str) -> str:
    """Форма слова после числа: 1 -> one, 2–4 -> few, 0 и 5–20 -> many (11–14 всегда many)."""
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def tasks(n: int) -> str:
    """«1 задача», «3 задачи», «11 задач»."""
    return f"{n} {plural_ru(n, 'задача', 'задачи', 'задач')}"


def minutes(n: int) -> str:
    return f"{n} {plural_ru(n, 'минуту', 'минуты', 'минут')}"
