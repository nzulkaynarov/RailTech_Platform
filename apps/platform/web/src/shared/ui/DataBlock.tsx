import {
  type CSSProperties,
  Fragment,
  type ReactNode,
  type RefObject,
  useLayoutEffect,
  useRef,
} from "react";

import "./data-block.css";

/** Сколько строк скелетона рисовать самое большее: больше не видно на экране, а длинный скелетон сам «прыгает». */
export const SKELETON_MAX_ROWS = 10;

/**
 * Скелетон первой загрузки списка (UX-1c, аудит 2026-10-30, S8): столько строк, сколько придёт на странице (`rows` —
 * размер страницы, но не больше `SKELETON_MAX_ROWS`), высотой строки таблицы, с внутренним отступом. Метка
 * `data-pf-skeleton` говорит `DataBlock` держать прежнюю высоту, пока скелетон на месте.
 */
export function ListSkeleton({ rows = 8, rowHeight = 44 }: { rows?: number; rowHeight?: number }) {
  const count = Math.max(1, Math.min(rows, SKELETON_MAX_ROWS));
  return (
    <div
      className="pf-list-skel"
      data-pf-skeleton=""
      aria-hidden="true"
      style={{ ["--pf-skel-row" as string]: `${String(rowHeight)}px` }}
    >
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="pf-list-skel-row">
          <span
            className="pf-list-skel-bar"
            style={{ width: `${String(40 + ((index * 37) % 45))}%` }}
          />
        </div>
      ))}
    </div>
  );
}

/**
 * Пока внутри скелетон (`[data-pf-skeleton]`), блок держит ровно ту высоту, которую имел с данными: смена вкладки на
 * ещё не загруженную не роняет страницу до высоты скелетона и не растягивает её длинным скелетоном. Высота с данными запоминается при каждом изменении размера и
 * содержимого. Наблюдатели срабатывают до отрисовки кадра (смена узлов — микрозадачей после коммита React, размер — до
 * отрисовки), поэтому промежуточная высота на экран не попадает.
 */
function useHoldHeight<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    let stable = 0;
    const sync = () => {
      if (element.querySelector("[data-pf-skeleton]") !== null) {
        // Ровно прежняя высота: короткий скелетон не роняет блок, длинный — обрезается, а не растягивает его
        if (stable > 0 && element.style.height === "") {
          element.style.height = `${String(stable)}px`;
          element.style.overflow = "hidden";
        }
        return;
      }
      if (element.style.height !== "") {
        element.style.height = "";
        element.style.overflow = "";
      }
      stable = element.getBoundingClientRect().height;
    };
    sync();
    const mutations = new MutationObserver(sync);
    mutations.observe(element, { childList: true, subtree: true });
    const sizes = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(sync);
    sizes?.observe(element);
    return () => {
      mutations.disconnect();
      sizes?.disconnect();
    };
  }, []);
  return ref;
}

/** Чем был фокус внутри блока: тег и подпись — чтобы найти «тот же» элемент после перестройки списка. */
function focusMark(element: Element): string {
  return `${element.tagName}|${element.getAttribute("aria-label") ?? element.textContent.trim()}`;
}

/**
 * Фокус не теряется, когда список перестроен по `resetKey`: был на кнопке «Дальше» под списком — остаётся на ней.
 */
function useKeepFocus<T extends HTMLElement>(
  ref: RefObject<T | null>,
  resetKey: string | undefined,
) {
  const mark = useRef<string | null>(null);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const remember = (event: FocusEvent) => {
      mark.current = event.target instanceof Element ? focusMark(event.target) : null;
    };
    // Ушёл фокусом за пределы блока (фильтр, вкладка) — забываем; узел удалён вместе со списком — помним.
    const forget = (event: FocusEvent) => {
      if (event.relatedTarget instanceof Node && !element.contains(event.relatedTarget)) {
        mark.current = null;
      }
    };
    element.addEventListener("focusin", remember);
    element.addEventListener("focusout", forget);
    return () => {
      element.removeEventListener("focusin", remember);
      element.removeEventListener("focusout", forget);
    };
  }, [ref]);
  useLayoutEffect(() => {
    const element = ref.current;
    const wanted = mark.current;
    if (!element || wanted === null) return;
    // Фокус где-то ещё (поле фильтра, вкладка) — не трогаем; потерян вместе со старым списком — возвращаем.
    const active = document.activeElement;
    if (active !== null && active !== document.body) return;
    const same = [...element.querySelectorAll<HTMLElement>("a[href], button, [tabindex]")].find(
      (candidate) => focusMark(candidate) === wanted,
    );
    same?.focus({ preventScroll: true });
  }, [ref, resetKey]);
}

/**
 * Блок данных списка (UX-1c, инвариант 6 `platform-frontend.md` §4.1): обновление на месте. `busy` — идёт загрузка с
 * новыми условиями, а на экране прежние строки (`isPlaceholderData`): тонкая полоса сверху поверх содержимого и
 * `aria-busy`, высота не меняется. Скелетон внутри (первая загрузка вкладки) — блок держит прежнюю высоту.
 * `resetKey` (`useShownKey`) — ключ показанных данных: пришёл ответ с новыми условиями — список строится заново, а не
 * передвигает совпавшие строки; фокус остаётся на «том же» элементе.
 */
export function DataBlock({
  busy = false,
  resetKey,
  className,
  style,
  children,
}: {
  busy?: boolean;
  resetKey?: string;
  className?: string;
  style?: CSSProperties;
  children: ReactNode;
}) {
  const ref = useHoldHeight<HTMLDivElement>();
  useKeepFocus(ref, resetKey);
  return (
    <div
      ref={ref}
      className={className ? `pf-data-block ${className}` : "pf-data-block"}
      style={style}
      aria-busy={busy || undefined}
      data-busy={busy ? "" : undefined}
    >
      <Fragment key={resetKey}>{children}</Fragment>
    </div>
  );
}

/**
 * Ширины колонок таблицы списка (UX-1c, S9): `table-layout: fixed` и `<colgroup>` — границы колонок не зависят от
 * содержимого страницы и стоят на месте при смене фильтра, вкладки и страницы. `null` — гибкая колонка (тема,
 * название): делит остаток ширины. `tableMinWidth` — ниже этой ширины таблица прокручивается в своей области.
 */
export function TableCols({ widths }: { widths: readonly (number | null)[] }) {
  return (
    <colgroup>
      {widths.map((width, index) => (
        <col key={index} style={width === null ? undefined : { width }} />
      ))}
    </colgroup>
  );
}
