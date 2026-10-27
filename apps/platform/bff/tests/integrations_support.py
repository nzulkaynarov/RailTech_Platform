"""CRM для тестов Admin · Внешние интеграции (W13-A1): ответы в форме `crm.yaml`, данные выдуманы.

`CrmIntegrationsFake` — одна respx-ловушка на `/api/v1/integrations*`, `/admin/external-services*`,
`/models*`, `/spend`, `/admin/ai-spend`, `/system/*`. Ответы по умолчанию — «всё в порядке»; тест
подменяет конкретный ответ через `answer()`. Секреты в тестах — сгенерированные на лету значения,
а не настоящие токены.
"""

import json
import re
import secrets
from collections.abc import Callable
from typing import Any

import httpx

from tests.backends import Backends
from tests.consts import CRM_URL

NOW = "2026-10-26T09:00:00Z"
EARLIER = "2026-10-26T08:55:00Z"


def fresh_secret(prefix: str = "tst", size: int = 24) -> str:
    """Выдуманный секрет для одного прогона: ни настоящих токенов, ни паролей в репозитории."""
    return f"{prefix}-{secrets.token_urlsafe(size)}"


def erp_status(**over: Any) -> dict[str, Any]:
    return {
        "configured": True,
        "mode": "erp",
        "base_url": "http://erp.test",
        "base_url_source": "db",
        "bootstrap_available": False,
        "inbound_token_configured": True,
        "inbound_token_last4": "a1b2",
        "paired": True,
        "previous_secret_until": None,
        "rotation_pending": False,
        "secrets_enabled": True,
        "suggested_base_url": "http://erp-backend:8000",
        "token_configured": True,
        "token_source": "db",
        "token_last4": "9f3c",
        "token_updated_at": EARLIER,
        "webhook_secret_configured": True,
        "webhook_secret_source": "db",
        "webhook_secret_last4": "77de",
        "webhook_secret_updated_at": EARLIER,
        "webhook_secret_previous_configured": False,
        "webhook_secret_previous_source": "none",
        "webhook_secret_previous_last4": None,
        "webhook_secret_previous_updated_at": None,
        **over,
    }


def erp_check(**over: Any) -> dict[str, Any]:
    return {
        "status": "ok",
        "checked_at": NOW,
        "latency_ms": 42,
        "version": "1.9.0",
        "migrations_applied": True,
        "queue_alive": True,
        "retry_after_s": None,
        **over,
    }


def telegram_status(**over: Any) -> dict[str, Any]:
    return {
        "configured": True,
        "source": "db",
        "last4": "Qw7x",
        "updated_at": EARLIER,
        "username": "demo_railtech_bot",
        "mode": "polling",
        "running": True,
        "last_error": None,
        "secrets_enabled": True,
        "channel_id": -1001,
        "channel_title": "Команда (демо)",
        **over,
    }


def text3(ru: str, uz: str = "", en: str = "") -> dict[str, str]:
    return {"ru": ru, "uz": uz or ru, "en": en or ru}


def bot_profile(**over: Any) -> dict[str, Any]:
    return {
        "profile": {
            "name": text3("Демо-бот", "Demo bot", "Demo bot"),
            "short_description": text3("Помощник", "Yordamchi", "Assistant"),
            "description": text3("Отвечает клиентам", "Mijozlarga javob", "Answers customers"),
        },
        "published": {
            "ok": True,
            "at": EARLIER,
            "changed": 3,
            "error": None,
            "retry_after": None,
        },
        **over,
    }


def smtp_status(**over: Any) -> dict[str, Any]:
    return {
        "configured": True,
        "host": "smtp.demo.example",
        "port": 587,
        "security": "starttls",
        "from_email": "noreply@demo.example",
        "from_name": "RailTech (демо)",
        "settings_source": "db",
        "username": "mailer",
        "username_source": "db",
        "password_configured": True,
        "password_source": "db",
        "password_last4": "k3Zp",
        "password_updated_at": EARLIER,
        "secrets_enabled": True,
        **over,
    }


def mail_row(row_id: int, status: str = "sent", **over: Any) -> dict[str, Any]:
    return {
        "id": row_id,
        "to_email": f"colleague{row_id}@demo.example",
        "subject": "Приглашение в Платформу",
        "template": "invite",
        "lang": "ru",
        "status": status,
        "error": None if status != "failed" else "smtp_auth_failed",
        "attempts": 1,
        "user_id": 11,
        "requested_by": 7,
        "created_at": EARLIER,
        "sent_at": EARLIER if status == "sent" else None,
        **over,
    }


STATE_OF_STATUS = {
    "ok": "ok",
    "fail": "broken",
    "warn": "degraded",
    "unknown": "not_checked",
    "off": "not_configured",
}


def service(key: str = "telegram", status: str = "ok", **over: Any) -> dict[str, Any]:
    return {
        "key": key,
        "title": {"telegram": "Telegram Bot API", "mail": "Почтовый релей (SMTP)"}.get(key, key),
        "purpose": "Клиентский бот и канал команды",
        "system": "crm",
        "source": "crm",
        "check": "getMe и getWebhookInfo",
        "frequency": "minute",
        "status": status,
        "summary": "Токен принят" if status == "ok" else "Проверка не прошла",
        "error": None if status == "ok" else "timeout",
        "hint": None if status == "ok" else "Проверьте токен бота",
        "fix_path": "/integrations?tab=bot" if key == "telegram" else None,
        "checked_at": NOW,
        "stale": False,
        "latency_ms": 120,
        "metrics": {"pending": 0},
        "uptime_24h": 0.999,
        "uptime_7d": 0.998,
        "checks_24h": 1440,
        "failures_24h": 1,
        "p95_ms_24h": 300,
        "switch": {
            "kind": "telegram",
            "available": True,
            "disabled": False,
            "effect": "Бот перестанет отвечать клиентам; сообщения встанут в очередь",
            "problem": None,
            "reason": None,
            "changed_at": None,
            "changed_by": None,
        },
        "incident": None,
        "state": STATE_OF_STATUS[status],
        "cause_key": f"{key}:{'ok' if status == 'ok' else 'status'}",
        "owner": None if status in ("ok", "unknown") else "admin",
        "action": None if status in ("ok", "unknown") else "open_settings",
        "more_actions": [],
        "since": None if status == "ok" else EARLIER,
        "last_recovered_at": None,
        "flaps_24h": 0,
        **over,
    }


def group(key: str = "telegram", state: str = "broken", **over: Any) -> dict[str, Any]:
    """Строка-группа CRM: одна причина — один сервис (или несколько через `service_keys`)."""
    return {
        "id": f"{key}:status",
        "state": state,
        "owner": "admin",
        "action": "open_settings",
        "more_actions": ["recheck"],
        "headline": "Проверка не прошла",
        "detail": "Проверьте токен бота",
        "affected": [],
        "service_keys": [key],
        "titles": [key],
        "since": EARLIER,
        "technical": ["timeout"],
        "message": None,
        "flaps_24h": 0,
        **over,
    }


def services_out(
    items: list[dict[str, Any]] | None = None,
    groups: list[dict[str, Any]] | None = None,
    *,
    stand: bool = False,
) -> dict[str, Any]:
    rows = items if items is not None else [service("telegram"), service("mail")]
    summary = dict.fromkeys(("ok", "warn", "fail", "unknown", "off", "disabled"), 0)
    for row in rows:
        summary[row["status"]] += 1
        if row["switch"] and row["switch"]["disabled"]:
            summary["disabled"] += 1
    derived = [
        group(row["key"], row["state"], id=row["cause_key"])
        for row in rows
        if row["state"] != "ok"
        and row["state"] != "not_checked"
        and row["state"] != "disabled"
        and row["status"] != "off"
    ]
    return {
        "checked_at": NOW,
        "summary": summary,
        "services": rows,
        "stand": stand,
        "groups": derived if groups is None else groups,
    }


def service_detail(**over: Any) -> dict[str, Any]:
    return {
        "service": service(),
        "checks": [
            {
                "checked_at": NOW,
                "tier": "manual",
                "status": "ok",
                "latency_ms": 100,
                "summary": "Токен принят",
                "error": None,
            }
        ],
        "days": [
            {"day": "2026-10-25", "ok": 1400, "warn": 0, "fail": 1, "unknown": 0, "uptime": 0.999}
        ],
        "incidents": [
            {
                "id": 5,
                "started_at": EARLIER,
                "ended_at": NOW,
                "duration_s": 300,
                "summary": "Telegram не отвечал",
                "last_error": "timeout",
                "alerted": True,
                "recovery_alerted": True,
            }
        ],
        **over,
    }


def model_row(alias: str = "dialog-model", health: str = "ok", **over: Any) -> dict[str, Any]:
    return {
        "alias": alias,
        "provider": "anthropic",
        "model": "claude-demo",
        "health": health,
        "health_detail": None if health == "ok" else "401 от провайдера",
        "checked_at": NOW,
        "today_usd": 1.25,
        "key_source": "crm",
        "key_last4": "77aa",
        **over,
    }


def system_status(status: str = "ok", **over: Any) -> dict[str, Any]:
    return {
        "status": status,
        "checked_at": NOW,
        "components": [
            {
                "key": "database",
                "title": "База данных",
                "status": "ok",
                "reason": "отвечает",
                "checked_at": NOW,
                "expected_on_stand": False,
            },
            {
                "key": "bot",
                "title": "Бот",
                "status": "ok" if status == "ok" else "fail",
                "reason": "работает" if status == "ok" else "процесс не отвечает",
                "checked_at": NOW,
                "expected_on_stand": False,
            },
        ],
        **over,
    }


def backups(**over: Any) -> dict[str, Any]:
    return {
        "available": True,
        "source": "volume",
        "can_request": True,
        "error": None,
        "databases": [{"name": "crm", "last_success_at": EARLIER}],
        "last_success_at": EARLIER,
        "stale": False,
        "requested_at": None,
        "daemon_alive": True,
        "request_stuck": False,
        "items": [{"name": "crm-2026-10-26.dump", "at": EARLIER, "size_bytes": 1048576}],
        **over,
    }


def spend(**over: Any) -> dict[str, Any]:
    return {
        "days": 7,
        "today_usd": 1.5,
        "daily_usd": 1.0,
        "providers": [{"provider": "anthropic", "spent_usd": 2.0, "limit_usd": 10.0}],
        "series": [{"day": "2026-10-26", "work_usd": 1.2, "test_usd": 0.3}],
        "by_purpose": [{"key": "dialog", "cost_usd": 1.0, "calls": 30}],
        "by_kind": [{"key": "chat", "cost_usd": 1.0, "calls": 30}],
        "total_usd": 9.5,
        "leads": 12,
        "avg_per_lead_usd": 0.79,
        "top_leads": [{"lead_id": 1, "lead_name": "Демо-Депо", "cost_usd": 2.0, "calls": 9}],
        **over,
    }


def ai_spend(**over: Any) -> dict[str, Any]:
    totals = {
        "calls": 10,
        "failed_calls": 1,
        "input_tokens": 1000,
        "output_tokens": 500,
        "cost_usd": 3.5,
        "fallback_calls": 0,
    }
    return {
        "date_from": "2026-09-27",
        "date_to": "2026-10-26",
        "group": "day",
        "timezone": "Asia/Tashkent",
        "rows": [
            {
                "key": "2026-10-26",
                **totals,
                "by_system": [{"system": "crm", "cost_usd": 3.5, "calls": 10}],
            }
        ],
        "totals": totals,
        "systems": [
            {
                "system": "crm",
                "daily_usd": 5.0,
                "today_usd": 3.5,
                "today_calls": 10,
                "over_today": False,
                "period_usd": 3.5,
                "period_calls": 10,
                "fallback_calls": 0,
                "days_over": 0,
                "connected": True,
            }
        ],
        "overruns": [],
        "erp_connected": False,
        "truncated": False,
        "fetched_at": NOW,
        **over,
    }


Handler = Callable[[httpx.Request], httpx.Response]
_API = (
    re.escape(CRM_URL)
    + r"/api/v1/(integrations|admin/external-services|models|spend|admin/ai-spend|system)"
)


class CrmIntegrationsFake:
    """Ловушка respx для CRM: ответы по умолчанию + подмена на лету + журнал запросов."""

    def __init__(self, be: Backends) -> None:
        self.calls: list[httpx.Request] = []
        self.overrides: dict[tuple[str, str], Handler | httpx.Response] = {}
        self.route = be.router.route(url__regex=_API + r".*").mock(side_effect=self._handle)

    # --- подмена и разбор ---
    def answer(
        self, method: str, path: str, status: int = 200, body: Any = None, **kw: Any
    ) -> None:
        """Ответить на `METHOD /api/v1/<path>` заданным статусом и телом."""
        self.overrides[(method, f"/api/v1/{path}")] = httpx.Response(status, json=body, **kw)

    def error(
        self,
        method: str,
        path: str,
        status: int,
        code: str,
        reason: str | None = None,
        **details: Any,
    ) -> None:
        d = {**details, **({"reason": reason} if reason else {})}
        self.answer(method, path, status, {"code": code, "message": code, "details": d})

    def requests(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.calls if r.method == method and r.url.path == f"/api/v1/{path}"]

    def last(self, method: str, path: str) -> httpx.Request:
        found = self.requests(method, path)
        assert found, f"CRM не вызывали: {method} {path}"
        return found[-1]

    def body(self, method: str, path: str) -> Any:
        return json.loads(self.last(method, path).content)

    @property
    def count(self) -> int:
        return len(self.calls)

    # --- ответы по умолчанию ---
    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        key = (request.method, request.url.path)
        if key in self.overrides:
            hit = self.overrides[key]
            return hit(request) if callable(hit) else hit
        return self._default(request)

    def _default(self, request: httpx.Request) -> httpx.Response:
        def ok(body: Any, status: int = 200) -> httpx.Response:
            return httpx.Response(status, json=body)

        m, p = request.method, request.url.path.removeprefix("/api/v1/")
        table: dict[tuple[str, str], Any] = {
            ("GET", "integrations/erp"): erp_status(),
            ("POST", "integrations/erp/check"): erp_check(),
            ("POST", "integrations/erp/pair"): {
                "status": erp_status(),
                "check": erp_check(),
                "check_error": None,
            },
            ("POST", "integrations/erp/rotate"): {
                "status": erp_status(rotation_pending=True),
                "check": erp_check(),
                "check_error": None,
            },
            ("GET", "integrations/telegram"): telegram_status(),
            ("PUT", "integrations/telegram/token"): telegram_status(last4="Zz9y"),
            ("GET", "integrations/telegram/channels"): [
                {
                    "chat_id": -1001,
                    "title": "Команда (демо)",
                    "chat_type": "supergroup",
                    "detected_at": EARLIER,
                }
            ],
            ("POST", "integrations/telegram/channel/test"): {"ok": True, "id": None},
            ("GET", "integrations/telegram/profile"): bot_profile(),
            ("PUT", "integrations/telegram/profile"): bot_profile(),
            ("GET", "integrations/smtp"): smtp_status(),
            ("PUT", "integrations/smtp"): smtp_status(host="smtp2.demo.example"),
            ("POST", "integrations/smtp/check"): {
                "server": "smtp.demo.example ESMTP",
                "authenticated": True,
                "latency_ms": 85,
            },
            ("POST", "integrations/smtp/test-send"): {
                "email_log_id": 31,
                "to_email": "admin@demo.example",
                "status": "queued",
            },
            ("GET", "integrations/smtp/log"): [mail_row(2), mail_row(1, "failed")],
            ("GET", "admin/external-services"): services_out(),
            ("GET", "models"): [model_row(), model_row("embed-model")],
            ("GET", "spend"): spend(),
            ("GET", "admin/ai-spend"): ai_spend(),
            ("GET", "system/backups"): backups(),
            ("GET", "system/status"): system_status(),
        }
        if (m, p) in table:
            return ok(table[(m, p)])
        if m == "POST" and re.fullmatch(r"integrations/telegram/channels/-?\d+/connect", p):
            return ok({"ok": True, "id": None})
        if p.startswith("admin/external-services/"):
            tail = p.removeprefix("admin/external-services/")
            key, _, action = tail.partition("/")
            if m == "GET" and not action:
                return ok(service_detail(service=service(key)))
            if m == "POST" and action == "check":
                return ok(service_detail(service=service(key)))
            if m == "POST" and action == "disable":
                row = service(key)
                row["switch"] = {
                    **row["switch"],
                    "disabled": True,
                    "reason": "тест",
                    "changed_by": "Админ Демо",
                }
                return ok(row)
            if m == "POST" and action == "enable":
                return ok(service(key))
        if m == "PUT" and re.fullmatch(r"models/providers/[a-z]+/key", p):
            provider = p.split("/")[2]
            return ok(
                {
                    "provider": provider,
                    "roles": [
                        {**_model_change(a), "provider": provider, "key_source": "crm"}
                        for a in ("dialog-model", "qualifier-model")
                    ],
                    "checked": True,
                }
            )
        if p.startswith("models/"):
            alias, _, action = p.removeprefix("models/").partition("/")
            if m == "PUT" and not action:
                return ok(_model_change(alias))
            if m == "POST" and action == "reset":
                return ok(_model_change(alias, key_source="env"))
            if m == "POST" and action == "test":
                return ok(
                    {
                        "alias": alias,
                        "ok": True,
                        "detail": None,
                        "latency_ms": 900,
                        "cost_usd": 0.0002,
                    }
                )
        if (m, p) == ("POST", "system/backups"):
            return ok(backups(requested_at=NOW), 202)
        return httpx.Response(404, json={"code": "not_found", "message": "x", "details": {}})


def _model_change(alias: str, key_source: str = "crm") -> dict[str, Any]:
    return {
        "alias": alias,
        "provider": "openai",
        "model": "gpt-demo",
        "key_source": key_source,
        "reindex_required": alias == "embed-model",
        "quality_check_recommended": True,
    }
