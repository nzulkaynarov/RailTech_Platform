"""`manage.py ai_gateway_sync` — зарегистрировать/обновить виртуальный ключ ERP в LiteLLM.

Запускается одноразовым сервисом `erp-ai-gateway` стенда (infra/compose/base.yml) с мастер-ключом
шлюза. Никогда не падает с ненулевым кодом: недоступный шлюз или пустые переменные — понятная
строка в лог, а ERP работает дальше (ИИ просто вернёт `AI_GATEWAY_UNAVAILABLE`).

Окружение: `LITELLM_BASE_URL`, `LITELLM_API_KEY` (ключ ERP), `LITELLM_MASTER_KEY`,
`AI_DAILY_BUDGET_USD`, `ERP_LANGFUSE_PUBLIC_KEY` / `ERP_LANGFUSE_SECRET_KEY` / `ERP_LANGFUSE_HOST`.
"""

import os

import httpx
from ai.services.budget import daily_budget_usd
from ai.services.provision import KeySpec, LangfuseTarget, sync_erp_key
from django.conf import settings
from django.core.management.base import BaseCommand

DEFAULT_LANGFUSE_HOST = "http://langfuse-web:3000"


def _langfuse_from_env() -> LangfuseTarget | None:
    public_key = (os.environ.get("ERP_LANGFUSE_PUBLIC_KEY") or "").strip()
    secret_key = (os.environ.get("ERP_LANGFUSE_SECRET_KEY") or "").strip()
    if not (public_key and secret_key):
        return None
    host = (os.environ.get("ERP_LANGFUSE_HOST") or DEFAULT_LANGFUSE_HOST).strip()
    return LangfuseTarget(public_key=public_key, secret_key=secret_key, host=host)


class Command(BaseCommand):
    help = "Регистрирует виртуальный ключ ERP в LiteLLM: дневной бюджет и трейсы Langfuse (M1-ERP-06)."

    def handle(self, *args, **options):
        master_key = (os.environ.get("LITELLM_MASTER_KEY") or "").strip()
        erp_key = settings.LITELLM_API_KEY
        if not (settings.LITELLM_BASE_URL and master_key and erp_key):
            self.stdout.write("ai_gateway_sync: пропуск — нет LITELLM_BASE_URL, мастер-ключа или ключа ERP")
            return
        if erp_key == master_key:
            self.stdout.write(
                "ai_gateway_sync: пропуск — ERP ходит мастер-ключом (нет ERP_LITELLM_API_KEY в .env, выполните "
                "make env); бюджет — только журнал ERP, трейсов Langfuse нет"
            )
            return
        budget = daily_budget_usd()
        spec = KeySpec(
            key=erp_key,
            max_budget_usd=float(budget) if budget is not None else None,
            langfuse=_langfuse_from_env(),
        )
        try:
            outcome = sync_erp_key(settings.LITELLM_BASE_URL, master_key, spec)
        except (httpx.HTTPError, RuntimeError) as exc:
            self.stdout.write(f"ai_gateway_sync: шлюз не принял ключ ERP — {exc}")
            return
        self.stdout.write(
            f"ai_gateway_sync: ключ ERP {outcome}; бюджет/день={spec.max_budget_usd} USD; "
            f"Langfuse={'да' if spec.langfuse else 'нет (ERP_LANGFUSE_* пусты)'}"
        )
