"""Запуск erp-mcp: `python -m integration.mcp` (отдельный процесс, compose-сервис `erp-mcp`).

Django поднимается ДО импорта сервера: модули инструментов и вратаря тянут модели и настройки DRF.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

if __name__ == "__main__":
    from .server import main

    main()
