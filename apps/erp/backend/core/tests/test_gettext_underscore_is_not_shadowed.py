"""
`_` — это gettext, а не мусорная переменная.

Ловушка сработала третий раз (25-08, аварийное действие админки): в модуле, где
`from django.utils.translation import gettext_lazy as _`, распаковка вида

    _, error = services.some_action(...)

делает `_` объектом. Падает при этом НЕ присваивание, а первый же `_("...")` ниже по функции —
и падает в рантайме, у человека на экране: `TypeError: '<Model>' object is not callable`. Ни один тест этого не ловил, потому что путь шёл через аварийное действие админки.

Гард узкий намеренно: ругаемся только там, где `_` СВЯЗЫВАЕТСЯ и в той же функции ВЫЗЫВАЕТСЯ.
Идиома `obj, _ = get_or_create(...)` в функции без переводов безобидна — запрещать её значило бы
чинить стиль вместо дефекта.
"""

import ast
import pathlib

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]
SKIP_PARTS = {"migrations", "tests", ".venv", "node_modules", "static", "staticfiles"}


def _modules_importing_gettext_as_underscore():
    for path in sorted(BACKEND_ROOT.rglob("*.py")):
        if SKIP_PARTS & set(path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:  # pragma: no cover — сюда попадём только на битом файле
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "django.utils.translation":
                if any(alias.asname == "_" for alias in node.names):
                    yield path, tree
                    break


def _binds_underscore(node) -> bool:
    """Присваивание в `_` — как прямое, так и через распаковку кортежа."""
    for child in ast.walk(node):
        targets = []
        if isinstance(child, ast.Assign):
            targets = child.targets
        elif isinstance(child, (ast.AnnAssign, ast.AugAssign)):
            targets = [child.target]
        elif isinstance(child, ast.For):
            targets = [child.target]
        elif isinstance(child, (ast.With, ast.AsyncWith)):
            targets = [item.optional_vars for item in child.items if item.optional_vars]
        for target in targets:
            for leaf in ast.walk(target):
                if isinstance(leaf, ast.Name) and leaf.id == "_" and isinstance(leaf.ctx, ast.Store):
                    return True
    return False


def _calls_underscore(node) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "_":
            return True
    return False


def test_no_function_shadows_gettext_and_then_calls_it():
    offenders = []
    for path, tree in _modules_importing_gettext_as_underscore():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if _binds_underscore(node) and _calls_underscore(node):
                offenders.append(f"{path.relative_to(BACKEND_ROOT)}:{node.lineno}: {node.name}")

    assert not offenders, "`_` перезаписан и тут же вызван как перевод — это TypeError в рантайме:\n" + "\n".join(
        offenders
    )


def test_the_guard_actually_catches_the_shape():
    """Проверяем гард ЗАВЕДОМО ЛОМАНЫМ входом: без этого он был бы зелёным и на пустом обходе.

    Ровно тот код, что упал 25-08 в `accounts/admin.py`.
    """
    broken = ast.parse(
        "from django.utils.translation import gettext_lazy as _\n"
        "def handler(queryset):\n"
        "    for row in queryset:\n"
        "        _, error = do(row)\n"
        "    return _('готово')\n"
    )
    function = next(node for node in ast.walk(broken) if isinstance(node, ast.FunctionDef))

    assert _binds_underscore(function) and _calls_underscore(function)


def test_the_guard_leaves_the_harmless_idiom_alone():
    """Обратная сторона: `obj, _ = get_or_create(...)` без переводов в той же функции — не дефект."""
    harmless = ast.parse(
        "from django.utils.translation import gettext_lazy as _\n"
        "def load(cls):\n"
        "    obj, _ = cls.objects.get_or_create(pk=1)\n"
        "    return obj\n"
    )
    function = next(node for node in ast.walk(harmless) if isinstance(node, ast.FunctionDef))

    assert _binds_underscore(function) and not _calls_underscore(function)
