"""Коды ошибок ИИ ERP — стабильные UPPER_SNAKE, сравниваются по значению (CONTRACTS §0)."""

AI_BUDGET_EXCEEDED = "AI_BUDGET_EXCEEDED"
AI_GATEWAY_UNAVAILABLE = "AI_GATEWAY_UNAVAILABLE"
AI_GATEWAY_ERROR = "AI_GATEWAY_ERROR"
AI_BAD_RESPONSE = "AI_BAD_RESPONSE"


class AIBudgetExceeded(Exception):
    """Дневной бюджет ERP исчерпан (журнал ERP или бюджет ключа в LiteLLM).

    Единственная ошибка шлюза, которая поднимается наружу: остальные — логируемый no-op с
    нейтральным результатом. Бюджет же должен дойти до пользователя понятным кодом —
    `run_ai_job` превращает его в результат `{"error": "AI_BUDGET_EXCEEDED"}`. Не наследник
    RuntimeError, чтобы не проглатываться ветками `except RuntimeError` сервисов.
    """

    code = AI_BUDGET_EXCEEDED

    def __init__(self, source: str):
        super().__init__(f"{AI_BUDGET_EXCEEDED} ({source})")
        self.source = source
