# ADR CRM-0004. Внешние модели и размерность embedding

- Статус: accepted (2026-10-08, решение агента по поручению владельца: «принимай решения по своим рекомендациям и лучшим бенчмаркам»; пересматривается по итогам приёмки на dev)
- Дата: 2026-10-08
- Связано: SPEC §1.6, §2, §5.5, §7, §11 (бюджет), §12; docs/systems/crm/BUSINESS.md §8, §11; PLAN Фаза 1; ADR-0007

## Контекст и проблема

Код знает только алиасы LiteLLM: `dialog-model`, `qualifier-model`, `judge-model`, `embed-model`, `fallback-model` (docs/systems/crm/CONVENTIONS.md §3). Нужно выбрать конкретные модели и размерность векторов (она входит в схему `kb_chunks.embedding`). Ограничения: ответ лиду p95 ≤ 6 с, три языка (ru, uz латиница/кириллица, en), дешёвый квалификатор, независимость от одного провайдера (docs/systems/crm/BUSINESS.md §11).

## Драйверы решения

- Качество ответа и тона на ru/uz/en при коротких ответах (≤ 120 слов).
- Задержка: модели с обязательным adaptive thinking должны работать на низком `effort`.
- Стоимость квалификатора (вызов на каждое сообщение).
- Мультиязычный поиск, включая узбекский; ограничение HNSW pgvector — 2000 измерений для `vector`.
- Запасная модель — другого провайдера.

## Рассмотренные варианты

- Диалог: Claude Sonnet 5.5; Claude Opus 5.5 (дороже в 2 раза, медленнее); Gemini 3.8 Flash.
- Квалификатор: Claude Haiku 5.5; Gemini 3.8 Flash.
- Embeddings: Gemini Embedding 2 (`gemini-embedding-2`, 8K токенов, MRL 128–3072); `gemini-embedding-001` (2K токенов, `task_type`); Voyage 4 (1024, 26+ языков у 3.5, список не опубликован); Cohere embed-v4.0 (объявлен к выводу); OpenAI text-embedding-3-large.

## Решение

| Алиас | Модель (LiteLLM) | Параметры | Цена, $/1M ток. (вход/выход) |
|---|---|---|---|
| `dialog-model` | `anthropic/claude-sonnet-5-5` | `reasoning_effort: low` (LiteLLM → adaptive thinking + `output_config.effort=low`), `max_tokens` 1024, таймаут 20 с | 2.00 / 10.00 |
| `qualifier-model` | `anthropic/claude-haiku-5-5` | `reasoning_effort: low`, structured output (`response_format: json_schema`) | 0.10 / 0.50 |
| `judge-model` | `anthropic/claude-sonnet-5-5` | `reasoning_effort: medium`, только evals | 2.00 / 10.00 |
| `fallback-model` | `gemini/gemini-3.8-flash` | другой провайдер; цепочка fallback для `dialog-model` и `qualifier-model` | 0.75 / 3.75 |
| `embed-model` | `gemini/gemini-embedding-2` | `dimensions: 1536`; префиксы задачи в тексте (см. ниже) | 0.20 |

**Отклонение от рекомендации SPEC §2** («judge — Haiku-класс»): judge на Sonnet 5.5. Faithfulness ≥ 0.95 — порог релиза (SPEC §12), ошибка судьи дороже, а judge вызывается только в evals.

**Embedding.** Размерность 1536 (MRL-усечение 3072 → 1536): укладывается в HNSW `vector` (≤ 2000), вдвое дешевле хранить и сравнивать, чем 3072, потеря качества по документации Gemini минимальна. Вектор после API дополнительно L2-нормализуется в коде (для `gemini-embedding-001` это обязательно, для `-2` — страховка). `gemini-embedding-2` не поддерживает `task_type`; задача передаётся префиксом текста:

- запрос: `task: search result | query: {вопрос}`;
- документ: `title: {заголовок или none} | text: {чанк}`.

Форматирование — в `app/domain/embedding_profile.py`; смена модели = смена профиля + переиндексация (ингест идемпотентен по версии, `make` цель в Фазе 5 / `scripts/kb_ingest.py --reindex`).

**Thinking.** У Sonnet 5.5 и Haiku 5.5 thinking нельзя выключить; глубина — `effort`. LiteLLM 1.104.2 маппит `reasoning_effort` в `output_config.effort` только для моделей с флагом `supports_adaptive_thinking` в карте моделей; во встроенной карте этого тега нет записей Sonnet 5.5 / Haiku 5.5 (есть в main). Поэтому в `infra/litellm.config.yaml` для этих деплойментов явно задаётся `model_info` (флаги и цены), а не только загрузка удалённой карты. Сэмплинг-параметры (`temperature`) этим моделям не передаются (не поддерживаются).

**Отказы (`stop_reason: refusal`).** Классификаторы безопасности Claude могут отклонить запрос; для диалога это ведёт на `fallback-model` (fallback LiteLLM), событие логируется.

### Последствия

- Хорошо: два провайдера (Anthropic + Google) — сбой одного не останавливает бота; ключ Google нужен и для embeddings, отдельного провайдера ради fallback нет.
- Плохо: данные о качестве узбекского у вендоров не опубликованы (в MTEB узбекская латиница есть только в Belebele/WebFAQ, кириллицы нет) — качество подтверждается собственным набором (PLAN Фаза 1: 15 вопросов ru/uz/en, ≥ 3/4 на узбекском) и evals; размерность 1536 зашита в схему — смена модели embedding с другой размерностью требует миграции.
- Стоимость (оценка на 1000 сообщений лида): диалог ~1.5K вход/150 выход ток. → ~$4.5; квалификатор ~2K/300 → ~$0.35; embeddings запросов — копейки.

### Как проверяем

- Фаза 1 (integration + человек с ключами): `scripts/kb_search_eval.py` — top-3 по 15 вопросам демо-KB, ≥ 13/15, uz ≥ 3/4; сравнение `gemini-embedding-2` и `gemini-embedding-001` той же командой.
- Фаза 2/7: evals faithfulness, language match, latency p95 ≤ 6 с.
- Пересмотр — если пороги не достигаются или цена/латентность выходят за бюджет.
