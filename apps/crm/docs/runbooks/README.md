# Runbooks

Эксплуатация RailTech CRM. Создаются и обновляются скиллом `.claude/skills/runbook` в том же PR, что и изменение.

| Runbook | Когда |
|---|---|
| [dev-stand.md](dev-stand.md) | Запуск и диагностика dev-стенда |
| [bot-silent.md](bot-silent.md) | Бот не отвечает клиентам |
| [escalations-missing.md](escalations-missing.md) | Посты эскалаций не приходят в канал |
| [cost-spike.md](cost-spike.md) | Алерт бюджета, рост стоимости моделей |
| [prompt-rollback.md](prompt-rollback.md) | Откат изменения промпта |
| [eval-gate.md](eval-gate.md) | Настройка и разбор CI eval-gate |
| [deploy.md](deploy.md) | Первичная настройка VPS, выкладка по тегу, откат |
| [backup-restore.md](backup-restore.md) | Бэкапы, восстановление, проверка на dev |
| [key-rotation.md](key-rotation.md) | Ротация ключей и секретов |

Запланированы (SPEC §13, PLAN): `promote-to-prod.md` (Фаза 9).

## Шаблон

```markdown
# <Название>

## Когда применять
Симптомы, как их видит человек.

## Диагностика
Точные команды и что считается нормой.

## Действие
1. Пронумерованные идемпотентные шаги. ⚠️ — опасные, с откатом.

## Проверка
Как убедиться, что всё в порядке.

## Эскалация
К кому и с какими данными (логи, request_id, время в Asia/Tashkent).
```
