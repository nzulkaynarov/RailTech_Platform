"""Статика с префиксом пути запроса (OPS-CONSOLE): Django admin под `/console/erp` на домене Платформы.

Django вычисляет `STATIC_URL` один раз (при первом обращении, ещё без префикса), поэтому `{% static %}` под
`/console/erp/admin/` давал бы `/static/...` — путь чужого домена. Хранилище добавляет префикс текущего
запроса (`get_script_prefix`, его ставит core/console_mount.py) к адресу файла; без префикса — как раньше.
"""

from django.contrib.staticfiles.storage import StaticFilesStorage
from django.urls import get_script_prefix


class ScriptPrefixStaticFilesStorage(StaticFilesStorage):
    def url(self, name: str | None) -> str:
        url = super().url(name)
        prefix = get_script_prefix().rstrip("/")
        if prefix and url.startswith("/") and not url.startswith(prefix + "/"):
            return prefix + url
        return url
