import { Button, Popover } from "antd";
import { type ReactNode, useId } from "react";
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
                <Popover
                  trigger="click"
                  placement="bottomRight"
                  title={t("whereToDo")}
                  content={item.where}
                >
                  <Button aria-label={t("whereToDoItem", { title: item.title })}>
                    {t("whereToDo")}
                  </Button>
                </Popover>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
