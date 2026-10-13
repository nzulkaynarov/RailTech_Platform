"""Запуск MCP-серверов по имени (`python -m app mcp kb|crm|docs`)."""

from importlib import import_module

MODULES = {"kb": "app.mcp.kb_server", "crm": "app.mcp.crm_server", "docs": "app.mcp.docs_server"}


def run(name: str) -> None:
    import_module(MODULES[name]).main()
