"""Каждый путь до `select_for_update` проходит через транзакцию.

Вне транзакции Django поднимает `TransactionManagementError`, и обработчик отвечает 500.
Проход глазами 03-08 нашёл ШЕСТЬ таких живых путей: покупатель не мог подписать договор,
заказчик — принять акт, продавец — выпустить акт, напомнить и аннулировать. У близнеца
`sign_contract_by_manager` декоратор был, у `sign_contract_by_client` — нет.

**Почему это не поймали 1154 зелёных теста:** `pytest.mark.django_db` оборачивает каждый тест
в транзакцию, поэтому `select_for_update` внутри теста работает всегда — независимо от того,
атомарен сервис или нет. Тест ниже проверяет не поведение, а СТРУКТУРУ исходников; такую
проверку транзакция теста замаскировать не может.

Инвариант: **на пути от публичной функции до блокировки должно быть хотя бы одно атомарное
звено.** Блокировка распространяется вверх по вызовам только через НЕатомарные звенья —
атомарный сервис её «поглощает», и его вызывающим декоратор уже не нужен.

Две тонкости, каждая из которых один раз обманула этот же тест при разработке:

1. **Атомарность читается из AST, а не из текста.** `next_document_number` в докстроке пишет
   «MUST be called inside the caller's `transaction.atomic()` block» — проверка подстрокой
   считала функцию атомарной и пропускала ВСЮ ветку выпуска документов.
2. **Блокировка бывает транзитивной через тонкую обёртку.** `generate_act` не содержит
   `select_for_update` вовсе: он зовёт `_next_act_number`, а тот — `next_document_number`.
   Проверка «только прямые блокировщики» такую цепочку не видит.
"""

import ast
import collections
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[2]
SKIP_PARTS = {"migrations", "__pycache__", "tests", ".venv", "node_modules"}


def _is_atomic(func: ast.AST) -> bool:
    """Настоящая атомарность: декоратор или `with transaction.atomic()`. НЕ докстрока."""
    for decorator in func.decorator_list:
        if "atomic" in ast.unparse(decorator):
            return True
    for node in ast.walk(func):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if "atomic" in ast.unparse(item.context_expr):
                    return True
    return False


def _takes_lock(func: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "select_for_update"
        for node in ast.walk(func)
    )


def _call_graph():
    nodes: dict[tuple[str, str], ast.AST] = {}
    by_name: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    calls: dict[tuple[str, str], set[str]] = collections.defaultdict(set)

    for path in BACKEND.rglob("*.py"):
        if SKIP_PARTS & set(path.parts) or path.name.startswith("test"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover — файлы вне грамматики модуля
            continue
        for func in ast.walk(tree):
            if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            key = (str(path.relative_to(BACKEND)), func.name)
            nodes[key] = func
            by_name[func.name].append(key)
            for node in ast.walk(func):
                if isinstance(node, ast.Call):
                    called = node.func
                    name = (
                        called.id
                        if isinstance(called, ast.Name)
                        else (called.attr if isinstance(called, ast.Attribute) else None)
                    )
                    if name:
                        calls[key].add(name)
    return nodes, by_name, calls


def _resolve(by_name, caller_key, name):
    """Адресат вызова — только когда он ОДНОЗНАЧЕН: тот же файл или единственное определение.

    Иначе `update`/`save`/`get` связали бы весь граф со всем и тест утонул бы в ложных срабатываниях.
    """
    candidates = by_name.get(name, [])
    same_file = [key for key in candidates if key[0] == caller_key[0]]
    if same_file:
        return same_file
    return candidates if len(candidates) == 1 else []


def _leaky_functions():
    """Функции, из которых блокировка достижима, и НИ ОДНО звено пути не атомарно."""
    nodes, by_name, calls = _call_graph()
    leaky = {key for key, func in nodes.items() if _takes_lock(func) and not _is_atomic(func)}

    changed = True
    while changed:
        changed = False
        for key, callees in calls.items():
            if key in leaky or _is_atomic(nodes[key]):
                continue
            if any(target in leaky for name in callees for target in _resolve(by_name, key, name)):
                leaky.add(key)
                changed = True
    return nodes, leaky


#: Функции, для которых «вызывающий открывает транзакцию» — ЗАДОКУМЕНТИРОВАННЫЙ контракт, а не
#: недосмотр: блокировка счётчика обязана жить до коммита вызывающего, иначе номер не
#: гарантирует безразрывность. За них отвечают вызывающие — их тест и проверяет.
CONTRACTUAL_HELPERS = {
    ("crm/services/numbering.py", "next_document_number"),
    ("crm/services/billing.py", "_locked_act"),
}


def test_no_public_path_reaches_a_lock_without_a_transaction():
    nodes, leaky = _leaky_functions()

    offenders = sorted(
        f"{path}:{nodes[(path, name)].lineno} {name}"
        for path, name in leaky
        if not name.startswith("_") and (path, name) not in CONTRACTUAL_HELPERS
    )

    assert offenders == [], (
        "на пути до `select_for_update` нет ни одной транзакции — в живом запросе это 500, "
        "а тесты его не видят (django_db держит собственную транзакцию):\n" + "\n".join(offenders)
    )


def test_contractual_helpers_still_exist_where_declared():
    """Список исключений не должен тихо протухнуть: имя уехало → исключение сняли, не заметив."""
    nodes, _ = _leaky_functions()
    missing = [f"{path}:{name}" for path, name in CONTRACTUAL_HELPERS if (path, name) not in nodes]

    assert missing == [], f"исключения указывают на несуществующие функции: {missing}"


def test_both_sides_of_the_contract_sign_the_same_way():
    """Договор двусторонний: у обеих подписей одинаковые гарантии.

    Дефект был именно в расхождении близнецов — одна функция атомарна, вторая нет.
    """
    from crm.services import contracts

    tree = ast.parse(pathlib.Path(contracts.__file__).read_text(encoding="utf-8"))
    by_name = {func.name: func for func in ast.walk(tree) if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef))}

    for name in ("sign_contract_by_client", "sign_contract_by_manager"):
        assert name in by_name, f"сервис {name} исчез — проверку надо переписать, а не удалять"
        assert _is_atomic(by_name[name]), f"{name} не атомарен"


def test_atomicity_is_read_from_code_not_from_a_docstring():
    """Защита от той самой ошибки, которая один раз обманула этот тест."""
    lying = ast.parse('def f():\n    """see transaction.atomic() in the caller"""\n    pass\n').body[0]
    honest = ast.parse("def f():\n    with transaction.atomic():\n        pass\n").body[0]

    assert not _is_atomic(lying), "упоминание в докстроке не делает функцию атомарной"
    assert _is_atomic(honest)
