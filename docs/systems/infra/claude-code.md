# Рабочее место агентов Claude Code — права, хуки, проверки
Статус: действует · Владелец: архитектор · Обновлено: 2026-10-29

Правила процесса живут в [`ORCHESTRATOR.md`](../../ORCHESTRATOR.md) и `CLAUDE.md` корня; здесь — как их **проверяет машина**,
а не только текст: настройки проекта `.claude/settings.json`, хуки `.claude/hooks/` и git-хук `commit-msg`. Основное место
работы — компьютер владельца (macOS, Docker Desktop); облачные сессии Claude Code — запасной вариант (§6).

## 1. Что где

| Файл | Что делает |
|---|---|
| `.claude/settings.json` | права (`allow` — без вопросов, `ask` — спросить человека, `deny` — нельзя) и подключение хуков |
| `.claude/hooks/guard_bash.py` | PreToolUse(Bash): сторож команд (§3) |
| `.claude/hooks/guard_write.py` | PreToolUse(Write): новый `.md` вне `docs/` не создаётся (ORCHESTRATOR §3 п. 17) |
| `.claude/hooks/format_file.py` | PostToolUse(Edit, Write): форматирует изменённый файл форматтером его приложения (§4) |
| `.claude/hooks/session_start.py` | SessionStart: проверка рабочего места (§5) |
| `scripts/check_commit_msg.py` | git-хук `commit-msg` через pre-commit: сообщение коммита агента (§5) |
| `scripts/tests/test_claude_hooks.py` | тесты всего перечисленного (задание gitleaks в CI, `python3 -m unittest discover -s scripts/tests`) |
| `.claude/settings.local.json` | личные послабления на одном компьютере; в `.gitignore`, в репозиторий не попадает |

Хуки — Python 3.9+ без зависимостей (системный `python3` macOS). Пути в хуках считаются от изменяемого файла, поэтому
сессия из основного checkout, правящая файлы в `.claude/worktrees/<задача>`, форматирует и проверяет их правильно.
`apps/crm/.claude/settings.json` действует, только если Claude запущен из `apps/crm`; штатно сессии стартуют из корня или
worktree.

## 2. Права

- **allow** — повседневное: `make`, `scripts/ci_local.sh`, `uv run`, `pnpm`, `npm run`, `git`, чтение PR и прогонов `gh`,
  `docker ps/logs`, свои проекты `docker compose -p rt-*`. Меньше вопросов — быстрее сессия; опасное ловит сторож (§3).
- **ask** — то, что трогает прод, деньги или настройки GitHub: `ssh`, `scp`, `rsync`, `make up-prod`, `infra/deploy/*.sh`,
  одобрение деплоя (`gh api …pending_deployments`), платные прогоны (`make *eval*`, `promptfoo`, `load-test`, `kb-demo`),
  `gh workflow run`, `gh secret|variable|release`, `gh repo edit`.
- **deny** — чтение `.env` (корня, приложений, `.env.local`, `.env.prod`), `~/.ssh/**`, `~/RailTech-secrets/**`; push в
  `main`, force-push, `--no-verify`, `docker system|volume prune`. Это второй рубеж на случай выключенных хуков: шаблоны
  `deny` сравнивают текст команды и обходятся иначе записанной командой, поэтому основная проверка — сторож.

## 3. Сторож команд (`guard_bash.py`)

Разбирает команду (цепочки `&&`, `;`, `|`, `cd`, `git -C`, `bash -c`; тела heredoc — текст, не команды) и до запуска
отклоняет с объяснением для агента:

| Что | Почему |
|---|---|
| push в `main`: `origin main`, `HEAD:main`, `--delete main`, push без refspec или `HEAD` из ветки `main`, `--all`, `--mirror` | `main` — только через PR (ORCHESTRATOR §4) |
| force-push: `--force`, `-f`, `--force-with-lease`, `+refspec` | запрещён любому агенту (§4); конфликт — `git merge origin/main` в свою ветку |
| `git push --no-verify`, `git commit --no-verify` | обходит gitleaks и pre-commit (§3 п. 6) |
| `commit`, `merge` (кроме `--ff-only`), `cherry-pick`, `revert`, `am` в ветке `main` | работа — только в worktree своей задачи (§4.1) |
| `git clean -x/-X` | стирает `.env` и зависимости |
| `docker … prune`, `docker compose down -v` без `-p` | общие очистки запрещены, тома общего стенда — не трогать (HANDOFF §5, ORCHESTRATOR §4.2) |
| `rm -r` по `/`, `~`, `.`, `..`, `*`, `.git` | слишком широкая цель |
| `cat`, `head`, `tail`, `less`, `base64` … файлов `.env*` (кроме `.example`, `.mock`), `~/.ssh/…`, `~/RailTech-secrets/…` | секреты не попадают в контекст модели; несекретный ключ — `grep '^ИМЯ=' .env` |

Нужное действие из этого списка делает **владелец сам** в своём терминале. Сторож не заменяет защиту `main` на GitHub —
он экономит круг «агент ошибся → GitHub отказал → агент чинит».

## 4. Форматирование при правке (`format_file.py`)

Только форматирование тем же инструментом, что проверяет `make check-<приложение>`, без автоисправлений линтера (они
удаляли бы импорт, добавленный раньше своего использования):

| Файлы | Форматтер |
|---|---|
| `apps/erp/backend/**.py` | black и isort из `apps/erp/.venv-tools` (как `make -C apps/erp format`) |
| `apps/crm/scripts/**.py` | ruff бэкенда CRM с его `pyproject.toml` (как pre-commit) |
| прочий `.py` | `ruff format` из `.venv` ближайшего каталога с `pyproject.toml` (CRM, EDS, BFF, rt-bus, rt-docs, contracts) |
| `.ts/.tsx/.js/.jsx/.mjs/.cjs/.css` | prettier пакета, где `format:check` = `prettier --check` (`apps/crm/frontend`, `apps/platform/web`) |

Нет окружения (не сделан `make install`) — хук молчит.

## 5. Проверка рабочего места и сообщения коммита

**SessionStart** пишет в начало сессии только проблемы: uv не той версии, что `UV_VERSION` в `ci.yml`; нет git-хуков
`pre-commit`/`commit-msg`; Docker не отвечает; в облачной сессии — не авторизован `gh`.

**`commit-msg`** (`make hooks` ставит его вместе с pre-commit) проверяет коммиты агентов — в их оболочке `CLAUDECODE=1`
(Claude Code) или `GEMINI_CLI=1`; коммиты человека не проверяются. Ошибка — первая строка не в Conventional Commits или нет
трейлера `Co-Authored-By`; предупреждение — нет задачи `(ID)` в конце первой строки (ORCHESTRATOR §4).

## 6. Новый компьютер

macOS (основное):

1. Docker Desktop (≈ 12 ГБ памяти, HANDOFF §5), Node 22 и `corepack enable` (pnpm 10.28 из `packageManager`), uv той версии,
   что `UV_VERSION` в `.github/workflows/ci.yml` (`curl -LsSf https://astral.sh/uv/<версия>/install.sh | sh`), `gh auth login`.
2. `brew install pre-commit` (или `uv tool install pre-commit`), затем в корне `make hooks` — один раз на клон: хуки лежат в
   общем `.git` и действуют во всех worktree.
3. Первая сессия Claude Code в корне — SessionStart перечислит, чего ещё не хватает.

Облачная сессия Claude Code (запасной вариант): в настройках окружения — скрипт настройки, он идёт до старта сессии:

```bash
curl -LsSf https://astral.sh/uv/0.13.0/install.sh | sh   # версия — UV_VERSION из ci.yml
pip install -q pre-commit
mkdir -p /etc/docker && echo '{"registry-mirrors":["https://mirror.gcr.io"]}' > /etc/docker/daemon.json
nohup dockerd >/var/log/dockerd.log 2>&1 &
cd RailTech_Platform && pre-commit install
```

Зеркало нужно, потому что анонимные загрузки с Docker Hub из облака упираются в лимит (429). `gh` в облаке без своего токена
не авторизован — PR и статус CI там через GitHub MCP.

## 7. Как менять

Права и хуки — PR зоны Infra с тестами в `scripts/tests/test_claude_hooks.py`; ослабление запрета — решение архитектора
(ORCHESTRATOR §4.1). Личное послабление на одном компьютере — `.claude/settings.local.json`, не в репозитории.
