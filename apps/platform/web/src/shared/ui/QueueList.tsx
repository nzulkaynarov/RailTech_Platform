import { Button } from "antd";
import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { StatusTone } from "../lib/statuses";
import { LinkButton } from "./LinkButton";
import { StatusTag } from "./StatusTag";
import "./ui.css";

export interface QueueItem {
  id: string;
  /** Бейдж срока: red «срок сегодня», gold «завтра», purple «служебка» (SPEC-v3 §7.1) */
  badge: { tone: StatusTone; label: string };
  /** Действие словами: «Наложить резолюцию на письмо ВХ-104/26» */
  title: string;
  /** Клиент · объект · от кого · когда */
  caption?: string;
  /** Адрес объекта (бизнес-номер в пути) */
  to: string;
  /** Срок сегодня или просрочено: у такой строки «Открыть» — primary (P2-9, UX-оценка) */
  urgent?: boolean;
  /**
   * У цели нет экрана в Платформе: вместо «Открыть» — вторичная кнопка «Где сделать» с поповером (W15-H2). Содержимое —
   * где работа делается сейчас; строка с `where` ссылки на заглушку не даёт.
   */
  where?: ReactNode;
}

export interface QueueListProps {
  items: readonly QueueItem[];
  /** Заголовок карточки: «Что сделать сейчас» */
  title: string;
  /** Уровень заголовка карточки: `h2` под заголовком страницы, `h3` внутри раздела */
  headingLevel?: 2 | 3;
  /** Пустое состояние словами (SPEC-v3 §7.1) — показывается, когда строк нет */
  empty?: ReactNode;
}

/**
 * «Что сделать сейчас» (docs/architecture/platform-frontend.md §5, SPEC-v3 §7.1): строка с отступом 14/24 и границей `#f0f0f0`, бейдж срока,
 * заголовок 500, подпись 12 px `#6e6e6e`, кнопка «Открыть» (primary — у всех строк «срок сегодня» и «просрочено»)
 * или, если у цели нет экрана, «Где сделать» с поповером.
 */
export function QueueList({ items, title, headingLevel = 2, empty }: QueueListProps) {
  const { t } = useTranslation("ui");
  const headingId = useId();
  const Heading = headingLevel === 2 ? "h2" : "h3";
  // «Где сделать» — встроенная секция сразу после кнопки (не плавающий поповер): фокус входит в неё при открытии, Tab доходит
  // до «Открыть в …», Escape закрывает и возвращает фокус на кнопку (WCAG 2.1.1, 2.4.3).
  const [openId, setOpenId] = useState<string | null>(null);
  const buttons = useRef(new Map<string, HTMLElement>());
  const panels = useRef(new Map<string, HTMLElement>());
  useEffect(() => {
    if (openId) panels.current.get(openId)?.focus();
  }, [openId]);
  return (
    <section className="pf-card pf-queue" aria-labelledby={headingId}>
      <div className="pf-card-head">
        <Heading id={headingId} className="pf-card-title">
          {title}
        </Heading>
      </div>
      {items.length === 0 ? (
        empty
      ) : (
        <ul className="pf-list">
          {items.map((item) => (
            <li key={item.id} className="pf-queue-row">
              <StatusTag tone={item.badge.tone}>{item.badge.label}</StatusTag>
              <div className="pf-queue-body">
                <div className="pf-queue-title">{item.title}</div>
                {item.caption ? <div className="pf-hint">{item.caption}</div> : null}
              </div>
              {item.where === undefined ? (
                <LinkButton
                  to={item.to}
                  type={item.urgent ? "primary" : "default"}
                  aria-label={t("openItem", { title: item.title })}
                >
                  {t("open")}
                </LinkButton>
              ) : (
                <Button
                  ref={(node) => {
                    if (node) buttons.current.set(item.id, node);
                  }}
                  aria-expanded={openId === item.id}
                  aria-controls={`${headingId}-where-${item.id}`}
                  aria-label={t("whereToDoItem", { title: item.title })}
                  onClick={() => {
                    setOpenId(openId === item.id ? null : item.id);
                  }}
                >
                  {t("whereToDo")}
                </Button>
              )}
              {item.where !== undefined && openId === item.id ? (
                <section
                  id={`${headingId}-where-${item.id}`}
                  ref={(node) => {
                    if (node) panels.current.set(item.id, node);
                  }}
                  className="pf-queue-where"
                  tabIndex={-1}
                  aria-label={t("whereToDo")}
                  onKeyDown={(event) => {
                    if (event.key !== "Escape") return;
                    event.stopPropagation();
                    setOpenId(null);
                    buttons.current.get(item.id)?.focus();
                  }}
                >
                  {item.where}
                </section>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
