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
import { objectLink } from "../../modules/objectLinks";
import { MODULES, moduleName } from "../../modules/registry";
import { GROUP_NAMES, langOf, searchSettings } from "../../modules/admin/settingsRegistry";
import { useSearch } from "../../shared/api/generated/platform-bff";
import { SearchIcon } from "../../shared/ui/icons";
import { MODULE_ICONS } from "../../shared/ui/moduleIcons";
import { SourceBanner } from "../../shared/ui/SourceBanner";
import { matchActions } from "./actions";
import "./global-search.css";

const MIN_LENGTH = 2;
const DEBOUNCE_MS = 250;

/** Совпадение по началу слова: «лог» находит «Журнал · лог», но не «каталог». */
function startsWord(text: string, q: string): boolean {
  return text
    .toLowerCase()
    .split(/[\s,·.\-—/]+/)
    .some((word) => word.startsWith(q));
}

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
  const { t, i18n } = useTranslation("shell");
  const { me } = useAuth();
  const navigate = useNavigate();
  const listId = useId();
  const root = useRef<HTMLDivElement>(null);
  const [value, setValue] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);

  const typed = value.trim();
  const debounced = useDebounced(typed, DEBOUNCE_MS);
  const ready = debounced.length >= MIN_LENGTH && typed.length >= MIN_LENGTH;
  const query = useSearch(
    { q: debounced },
    { query: { enabled: ready, placeholderData: keepPreviousData, staleTime: 10_000 } },
  );

  const groups = useMemo(() => (ready ? (query.data?.groups ?? []) : []), [ready, query.data]);
  const actions = useMemo(() => matchActions(me, typed), [me, typed]);

  // Переход в раздел (⌘K как палитра): доступные роли разделы по названию раздела, модуля и синонимам
  // (`shell:search.keywords.<модуль>.<раздел>`, на языке интерфейса).
  const navItems = useMemo(() => {
    if (typed.length < MIN_LENGTH) return [];
    const q = typed.trim().toLowerCase();
    const keywords = t("search.keywords", { returnObjects: true }) as Record<
      string,
      Record<string, string> | undefined
    >;
    const results: Array<{
      key: string;
      title: string;
      moduleTitle: string;
      path: string;
      moduleCode: keyof typeof MODULE_ICONS;
    }> = [];

    for (const mod of MODULES) {
      // Настройки ищутся по своему реестру — отдельной группой «Настройки» ниже (SET-IA).
      if (!me.modules.includes(mod.code) || mod.code === "admin") continue;
      const modTitle = moduleName(t, mod.code);
      const accessibleSections = mod.sections.filter(
        (sec) => !sec.hidden && canSee(me, sec.access),
      );

      for (const sec of accessibleSections) {
        const secTitle = t(`modules:${mod.code}.sections.${sec.key}`);
        const extra = keywords[mod.code]?.[sec.key] ?? "";
        if (startsWord(secTitle, q) || startsWord(modTitle, q) || startsWord(extra, q)) {
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

  // Группа «Настройки» (SET-IA; Google Admin, HubSpot — поиск находит и настройки): реестр настроек по названию, описанию
  // и ключевым словам на трёх языках, только доступные ролям сотрудника.
  const settingHits = useMemo(() => {
    if (typed.length < MIN_LENGTH || !me.modules.includes("admin")) return [];
    return searchSettings(typed, langOf(i18n.language), (entry) => canSee(me, entry.access)).slice(
      0,
      5,
    );
  }, [me, typed, i18n.language]);

  // Группы с порядковым номером результата сквозь все группы: по нему работают стрелки и aria-activedescendant
  const view = useMemo(() => {
    let next = 0;
    const out: Group[] = [];

    // Группа «Навигация по разделам» отображается в верхней секции при совпадении с запросом
    if (navItems.length > 0) {
      out.push({
        key: "navigation",
        name: t("search.navGroup"),
        options: navItems.map((item) => {
          const Icon = MODULE_ICONS[item.moduleCode];
          return {
            id: `${listId}-nav-${item.key}`,
            index: next++,
            title: item.title,
            subtitle: item.moduleTitle,
            tag: t("search.sectionTag"),
            path: item.path,
            navigation: true,
            icon: <Icon />,
          };
        }),
      });
    }

    if (settingHits.length > 0) {
      const lang = langOf(i18n.language);
      const Icon = MODULE_ICONS.admin;
      out.push({
        key: "settings",
        name: t("search.settingsGroup"),
        options: settingHits.map((hit) => ({
          id: `${listId}-s-${hit.entry.key}`,
          index: next++,
          title: t(`modules:admin.sections.${hit.entry.key}`),
          subtitle: GROUP_NAMES[hit.entry.group][lang],
          tag: t("search.settingTag"),
          path: hit.entry.path,
          navigation: true,
          icon: <Icon />,
        })),
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
          tag: t("search.actions.tag"),
          path: action.to,
          action: true,
        })),
      });
    }
    return out;
  }, [actions, groups, listId, navItems, settingHits, i18n.language, t]);
  const options = useMemo(() => view.flatMap((group) => group.options), [view]);
  const waiting = typed.length >= MIN_LENGTH && (debounced !== typed || query.isFetching);

  // Закрыть по клику вне поля и списка
  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (root.current && event.target instanceof Node && !root.current.contains(event.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  const go = (option: Option | undefined) => {
    if (!option) return;
    setOpen(false);
    setValue("");
    setActive(-1);
    void navigate(option.path);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (options.length === 0) return;
      event.preventDefault();
      setOpen(true);
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((prev) => (prev + step + options.length) % options.length);
    } else if (event.key === "Enter") {
      // Единственный найденный объект выбирается сам: объект важнее перехода в раздел и действия («создать»).
      // Объектов нет — первый вариант (раздел, затем действие).
      const objects = options.filter((option) => option.action !== true && !option.navigation);
      const target =
        options[active] ??
        (objects.length === 1 ? objects[0] : objects.length === 0 ? options[0] : undefined);
      if (target) {
        event.preventDefault();
        go(target);
      }
    } else if (event.key === "Escape") {
      if (open) {
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
      {/* Список может прокручиваться (с группой «Настройки», SET-IA): окно достижимо с клавиатуры, чтобы его можно было
          прокрутить (WCAG 2.1.1, axe scrollable-region-focusable); по строкам ходят стрелками из поля (aria-activedescendant). */}
      <div className="pf-gsearch-pop" hidden={!open} tabIndex={open ? 0 : -1}>
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
                    <span className="pf-gsearch-main pf-gsearch-main-icon">
                      {option.icon ? (
                        <span className="pf-gsearch-result-icon" aria-hidden="true">
                          {option.icon}
                        </span>
                      ) : null}
                      <span className="pf-gsearch-text">
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
      </div>
      <div role="status" className="pf-sr-only">
        {open && ready && !waiting && options.length > 0
          ? t("search.found", { count: options.length })
          : ""}
      </div>
    </div>
  );
}
