import { keepPreviousData } from "@tanstack/react-query";
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
  type Ref,
} from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { canSee } from "../../app/access";
import { useAuth } from "../../app/auth/useAuth";
import { isActionable } from "../../modules/bridge";
import { objectLink } from "../../modules/objectLinks";
import { MODULES, moduleName } from "../../modules/registry";
import { WhereToDo } from "../../modules/stub/WhereToDo";
import { useSearch } from "../../shared/api/generated/platform-bff";
import { SearchIcon } from "../../shared/ui/icons";
import { MODULE_ICONS } from "../../shared/ui/moduleIcons";
import { SourceBanner } from "../../shared/ui/SourceBanner";
import { matchActions } from "./actions";
import "./global-search.css";

const MIN_LENGTH = 2;
const DEBOUNCE_MS = 250;

/** Дополнительные синонимы разделов для быстрого перехода через палитру команд (⌘K), например «Калькулятор» → /erp/calc */
const SECTION_KEYWORDS: Record<string, readonly string[]> = {
  "erp.calc": ["калькулятор", "себестоимость"],
  "erp.catalog": ["каталог", "справочники"],
  "admin.company": ["шаблоны", "реквизиты", "нумерация"],
  "admin.integrations": ["интеграции", "smtp", "litellm"],
  "admin.audit": ["аудит", "лог"],
};

function useDebounced<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(value);
    }, delay);
    return () => {
      window.clearTimeout(timer);
    };
  }, [value, delay]);
  return debounced;
}

export interface GlobalSearchProps {
  inputRef: Ref<HTMLInputElement>;
  /** «⌘K» или «Ctrl K» */
  shortcut: string;
  mobile: boolean;
}

/** Строка списка: найденный объект или действие («создать заявку»); `path` — куда она ведёт. */
interface Option {
  id: string;
  index: number;
  title: string;
  subtitle?: string | undefined;
  /** Подпись справа: тип объекта или «Действие» */
  tag: string;
  path: string;
  /** Действие («создать заявку») — при Enter не перебивает найденный объект */
  action?: boolean;
  /** Переход в раздел платформы */
  navigation?: boolean;
  /** Иконка модуля для навигации */
  icon?: ReactNode;
}

interface Group {
  key: string;
  name: string;
  options: Option[];
}

/**
 * Глобальный поиск шапки (SPEC-v3 §6.1, docs/architecture/platform-frontend.md §4): поле 380 px, результаты группами по модулям, ⌘K/Ctrl+K
 * фокусирует поле (обработчик — в `AppShell`). Это комбобокс со списком: стрелки, Enter, Escape; запрос уходит в BFF
 * через 250 мс после последнего символа и не раньше двух символов. Недоступный бэкенд — плашка в списке, а не пустота.
 * W15-H2: строка, у цели которой есть экран, открывает его (боковое окно — в адресе); у раздела-заглушки — поповер «Где
 * посмотреть» с мостом в старый экран, а не заглушка. Слова «создать заявку», «служебка», «пригласить» добавляют
 * группу «Действия» (только те, что доступны ролям сотрудника).
 */
export function GlobalSearch({ inputRef, shortcut, mobile }: GlobalSearchProps) {
  const { t } = useTranslation("shell");
  const { me } = useAuth();
  const navigate = useNavigate();
  const listId = useId();
  const root = useRef<HTMLDivElement>(null);
  const [value, setValue] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [where, setWhere] = useState<Option | null>(null);

  const typed = value.trim();
  const debounced = useDebounced(typed, DEBOUNCE_MS);
  const ready = debounced.length >= MIN_LENGTH && typed.length >= MIN_LENGTH;
  const query = useSearch(
    { q: debounced },
    { query: { enabled: ready, placeholderData: keepPreviousData, staleTime: 10_000 } },
  );

  const groups = useMemo(() => (ready ? (query.data?.groups ?? []) : []), [ready, query.data]);
  const actions = useMemo(() => matchActions(me, typed), [me, typed]);

  // Локальная навигация по доступным модулям и разделам из Me.modules / Me.resources
  const navItems = useMemo(() => {
    if (typed.length < MIN_LENGTH) return [];
    const q = typed.toLowerCase();
    const results: Array<{
      key: string;
      title: string;
      moduleTitle: string;
      path: string;
      moduleCode: keyof typeof MODULE_ICONS;
    }> = [];

    for (const mod of MODULES) {
      if (!me.modules.includes(mod.code)) continue;
      const modTitle = moduleName(t, mod.code);
      const accessibleSections = mod.sections.filter(
        (sec) => !sec.hidden && canSee(me, sec.access),
      );

      for (const sec of accessibleSections) {
        const secTitle = t(`modules:${mod.code}.sections.${sec.key}`);
        const extraKeywords = SECTION_KEYWORDS[`${mod.code}.${sec.key}`] ?? [];
        const matchesKeyword = extraKeywords.some((kw) => kw.includes(q));
        if (
          secTitle.toLowerCase().includes(q) ||
          modTitle.toLowerCase().includes(q) ||
          matchesKeyword
        ) {
          results.push({
            key: `${mod.code}-${sec.key}`,
            title: secTitle,
            moduleTitle: modTitle,
            path: sec.path,
            moduleCode: mod.code,
          });
        }
      }
    }
    return results.slice(0, 5);
  }, [me, typed, t]);

  // Группы с порядковым номером результата сквозь все группы: по нему работают стрелки и aria-activedescendant
  const view = useMemo(() => {
    let next = 0;
    const out: Group[] = [];

    // Группа «Навигация по разделам» отображается в верхней секции при совпадении с запросом
    if (navItems.length > 0) {
      out.push({
        key: "navigation",
        name: "Навигация по разделам",
        options: navItems.map((item) => {
          const Icon = MODULE_ICONS[item.moduleCode];
          return {
            id: `${listId}-nav-${item.key}`,
            index: next++,
            title: item.title,
            subtitle: item.moduleTitle,
            tag: "Раздел",
            path: item.path,
            navigation: true,
            icon: <Icon />,
          };
        }),
      });
    }

    groups.forEach((group, g) => {
      out.push({
        key: group.module,
        name: moduleName(t, group.module),
        options: group.items.map<Option>((hit, i) => ({
          id: `${listId}-${String(g)}-${String(i)}`,
          index: next++,
          title: hit.title,
          subtitle: hit.subtitle,
          tag: t(`search.kind.${hit.object.kind}`),
          path: objectLink(hit.object),
        })),
      });
    });
    if (actions.length > 0) {
      out.push({
        key: "actions",
        name: t("search.actions.group"),
        options: actions.map((action, i) => ({
          id: `${listId}-a-${String(i)}`,
          index: next++,
          title: t(`search.actions.${action.key}`),
          // Раздел действия ещё без экрана (до D1-2): честно, где это делается сейчас, без «фазы Pn»
          subtitle: isActionable(action.to) ? undefined : t("search.actions.legacyHint"),
          tag: t("search.actions.tag"),
          path: action.to,
          action: true,
        })),
      });
    }
    return out;
  }, [actions, groups, listId, navItems, t]);
  const options = useMemo(() => view.flatMap((group) => group.options), [view]);
  const waiting = typed.length >= MIN_LENGTH && (debounced !== typed || query.isFetching);

  // Закрыть по клику вне поля и списка
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (root.current && event.target instanceof Node && !root.current.contains(event.target)) {
        setOpen(false);
        setWhere(null);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  const go = (option: Option | undefined) => {
    if (!option) return;
    if (!isActionable(option.path)) {
      // У раздела нет экрана: поиск остаётся открытым и говорит, где это посмотреть сейчас.
      setWhere(option);
      return;
    }
    setOpen(false);
    setWhere(null);
    setValue("");
    setActive(-1);
    void navigate(option.path);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (options.length === 0) return;
      event.preventDefault();
      setOpen(true);
      setWhere(null);
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((prev) => (prev + step + options.length) % options.length);
    } else if (event.key === "Enter") {
      // При наличии навигационного совпадения — быстрый переход в раздел по Enter
      const navTarget = options.find((option) => option.navigation === true);
      const objects = options.filter((option) => option.action !== true);
      const target =
        options[active] ??
        navTarget ??
        (objects.length === 1 ? objects[0] : objects.length === 0 ? options[0] : undefined);
      if (target) {
        event.preventDefault();
        go(target);
      }
    } else if (event.key === "Escape") {
      if (where) {
        event.preventDefault();
        setWhere(null);
      } else if (open) {
        event.preventDefault();
        setOpen(false);
      } else if (value) {
        setValue("");
      }
    }
  };

  let message: string | null = null;
  if (typed.length === 0) message = t("search.hint");
  else if (typed.length < MIN_LENGTH) message = t("search.tooShort");
  else if (options.length === 0) {
    if (query.isError && !waiting) message = t("search.error");
    else if (waiting) message = t("search.loading");
    else message = t("search.none", { query: typed });
  }

  return (
    <div ref={root} className="pf-gsearch" style={{ flex: mobile ? "1 1 0" : "0 1 380px" }}>
      <label className="pf-gsearch-field">
        <span className="pf-sr-only">{t("topbar.search")}</span>
        <span className="pf-gsearch-icon">
          <SearchIcon />
        </span>
        <input
          ref={inputRef}
          type="search"
          role="combobox"
          className="pf-search"
          placeholder={mobile ? t("topbar.searchShort") : t("topbar.searchPlaceholder")}
          autoComplete="off"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={open && options[active] ? options[active].id : undefined}
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            setActive(-1);
            setWhere(null);
            setOpen(true);
          }}
          onFocus={() => {
            setOpen(true);
          }}
          onKeyDown={onKeyDown}
        />
        {mobile ? null : (
          <kbd className="pf-kbd" aria-hidden="true">
            {shortcut}
          </kbd>
        )}
      </label>
      <div className="pf-gsearch-pop" hidden={!open}>
        {open && ready && query.data ? (
          <SourceBanner
            sources={query.data.sources}
            onRetry={() => {
              void query.refetch();
            }}
          />
        ) : null}
        {open && message ? (
          <div className="pf-gsearch-msg" role="status">
            {message}
          </div>
        ) : null}
        <div
          id={listId}
          role="listbox"
          aria-label={t("search.label")}
          hidden={!open || options.length === 0}
        >
          {view.map((group) => {
            const headingId = `${listId}-h-${group.key}`;
            return (
              <div key={group.key} role="group" aria-labelledby={headingId}>
                <div id={headingId} className="pf-gsearch-group" role="presentation">
                  {group.name}
                </div>
                {group.options.map((option) => (
                  <div
                    key={option.id}
                    id={option.id}
                    role="option"
                    aria-selected={option.index === active}
                    className={
                      option.index === active
                        ? "pf-gsearch-opt pf-gsearch-opt--on"
                        : "pf-gsearch-opt"
                    }
                    onMouseDown={(event) => {
                      event.preventDefault();
                    }}
                    onMouseEnter={() => {
                      setActive(option.index);
                    }}
                    onClick={() => {
                      go(option);
                    }}
                  >
                    <span
                      className="pf-gsearch-main"
                      style={{ display: "flex", alignItems: "center", gap: 8 }}
                    >
                      {option.icon ? (
                        <span
                          style={{
                            display: "flex",
                            alignItems: "center",
                            fontSize: 16,
                            color: "#1677ff",
                            flex: "0 0 auto",
                          }}
                        >
                          {option.icon}
                        </span>
                      ) : null}
                      <span style={{ display: "flex", flexDirection: "column" }}>
                        <span className="pf-gsearch-title">{option.title}</span>
                        {option.subtitle ? (
                          <span className="pf-hint">{option.subtitle}</span>
                        ) : null}
                      </span>
                    </span>
                    <span className="pf-gsearch-kind">{option.tag}</span>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
        <div aria-live="polite">
          {open && where ? (
            <section
              className="pf-gsearch-where"
              aria-label={t("search.where")}
              onKeyDown={(event) => {
                if (event.key !== "Escape") return;
                // Escape внутри подсказки закрывает её и возвращает фокус в поле поиска
                event.preventDefault();
                event.stopPropagation();
                setWhere(null);
                root.current?.querySelector("input")?.focus();
              }}
            >
              <h2 className="pf-gsearch-where-title">
                {t("search.where")}: {where.title}
              </h2>
              <WhereToDo path={where.path} />
              <button
                type="button"
                className="pf-gsearch-where-close pf-focusable"
                onClick={() => {
                  setWhere(null);
                  root.current?.querySelector("input")?.focus();
                }}
              >
                {t("search.whereClose")}
              </button>
            </section>
          ) : null}
        </div>
      </div>
      <div role="status" className="pf-sr-only">
        {open && ready && !waiting && options.length > 0
          ? t("search.found", { count: options.length })
          : ""}
      </div>
    </div>
  );
}

export { GlobalSearch as GlobalSearchModal };
export type { GlobalSearchProps as GlobalSearchModalProps };
