import { keepPreviousData } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type Ref } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { findModule } from "../../modules/registry";
import type { SearchHit } from "../../shared/api/generated/model";
import { useSearch } from "../../shared/api/generated/platform-bff";
import { SearchIcon } from "../../shared/ui/icons";
import { SourceBanner } from "../../shared/ui/SourceBanner";
import "./global-search.css";

const MIN_LENGTH = 2;
const DEBOUNCE_MS = 250;

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

interface Option {
  id: string;
  index: number;
  hit: SearchHit;
}

/**
 * Глобальный поиск шапки (SPEC-v3 §6.1, docs/architecture/platform-frontend.md §4): поле 380 px, результаты группами по модулям, ⌘K/Ctrl+K
 * фокусирует поле (обработчик — в `AppShell`). Это комбобокс со списком: стрелки, Enter, Escape; запрос уходит в BFF
 * через 250 мс после последнего символа и не раньше двух символов. Недоступный бэкенд — плашка в списке, а не пустота.
 */
export function GlobalSearch({ inputRef, shortcut, mobile }: GlobalSearchProps) {
  const { t } = useTranslation("shell");
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
  // Группы с порядковым номером результата сквозь все группы: по нему работают стрелки и aria-activedescendant
  const view = useMemo(() => {
    let next = 0;
    return groups.map((group, g) => ({
      module: group.module,
      options: group.items.map<Option>((hit, i) => ({
        id: `${listId}-${String(g)}-${String(i)}`,
        index: next++,
        hit,
      })),
    }));
  }, [groups, listId]);
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
    void navigate(option.hit.object.path);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (options.length === 0) return;
      event.preventDefault();
      setOpen(true);
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive((prev) => (prev + step + options.length) % options.length);
    } else if (event.key === "Enter") {
      const target = options[active] ?? (options.length === 1 ? options[0] : undefined);
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
  else if (query.isError && !waiting) message = t("search.error");
  else if (waiting && options.length === 0) message = t("search.loading");
  else if (options.length === 0) message = t("search.none", { query: typed });

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
            const name = findModule(group.module)?.name ?? group.module;
            const headingId = `${listId}-h-${group.module}`;
            return (
              <div key={group.module} role="group" aria-labelledby={headingId}>
                <div id={headingId} className="pf-gsearch-group" role="presentation">
                  {name}
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
                    <span className="pf-gsearch-main">
                      <span className="pf-gsearch-title">{option.hit.title}</span>
                      {option.hit.subtitle ? (
                        <span className="pf-hint">{option.hit.subtitle}</span>
                      ) : null}
                    </span>
                    <span className="pf-gsearch-kind">
                      {t(`search.kind.${option.hit.object.kind}`)}
                    </span>
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
