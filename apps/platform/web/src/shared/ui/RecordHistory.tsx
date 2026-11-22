import { type ReactNode, useState } from "react";
import { useTranslation } from "react-i18next";

import type { OnBehalfChannel } from "../api/generated/model";
import { useFormat } from "../lib/useFormat";
import { History, type HistoryItem } from "./History";
import { OnBehalfNote } from "./OnBehalf";

import "./ui.css";

/**
 * Одна запись «Истории» объекта (ЕД-7): когда, кто, что сделано, комментарий и «отмечено сотрудником». Каждый экран
 * приводит свой журнал к этому виду, а вид у всех один — `RecordHistory`.
 */
export interface RecordHistoryEntry {
  at: string;
  /** Кто сделал; `null` — система */
  by?: string | null;
  /** Что произошло, уже словами на языке сотрудника */
  action: ReactNode;
  /** Причина или заметка к действию */
  comment?: string | null;
  /** Действие контрагента записал сотрудник */
  onBehalf?: { channel: OnBehalfChannel; person: string } | null;
  /** К какому подчинённому документу относится запись (КП · Договор · Счёт · Акт): ключ чипа-фильтра */
  filter?: string | null;
  /** Номер документа рядом со временем */
  number?: string | null;
}

export interface RecordHistoryFilter {
  key: string;
  label: string;
}

/**
 * «История» карточки: единственное место, где перечислены события объекта. Подчинённые документы (договор, акт) не
 * копируют журнал, а фильтруют его: ряд чипов над списком, показываются только те, у которых есть записи.
 */
export function RecordHistory({
  entries,
  label,
  filters = [],
  empty,
  timeStyle = "datetime",
}: {
  entries: readonly RecordHistoryEntry[];
  label: string;
  filters?: readonly RecordHistoryFilter[];
  /** Слова, когда записей нет; без поля вкладка пуста — а пустую вкладку каркас не показывает */
  empty?: ReactNode;
  /** Как печатать время: «дата и время» или «сегодня/вчера» (журнал заказа) */
  timeStyle?: "datetime" | "activity";
}) {
  const { t } = useTranslation("ui");
  const { date, activity } = useFormat();
  const [active, setActive] = useState<string | null>(null);
  const chips = filters.filter((f) => entries.some((e) => e.filter === f.key));
  // Выбранный фильтр, у которого записей не осталось, не прячет всё: показываем весь список.
  const current = chips.some((c) => c.key === active) ? active : null;
  const shown = current ? entries.filter((e) => e.filter === current) : entries;
  const items: HistoryItem[] = shown.map((entry) => ({
    state: "done",
    title: entry.action,
    meta: (
      <>
        {[
          timeStyle === "activity" ? activity(entry.at) : date(entry.at, "datetime"),
          entry.by ?? t("recordHistory.system"),
        ]
          .filter(Boolean)
          .join(" · ")}
        {entry.number ? <span> · {entry.number}</span> : null}
        {entry.comment ? <span className="pf-record-history-note">{entry.comment}</span> : null}
        {entry.onBehalf ? (
          <OnBehalfNote channel={entry.onBehalf.channel} person={entry.onBehalf.person} />
        ) : null}
      </>
    ),
  }));
  return (
    <div className="pf-record-history">
      {chips.length > 1 ? (
        <div
          className="pf-record-history-filter"
          role="group"
          aria-label={t("recordHistory.filter")}
        >
          {[{ key: null, label: t("recordHistory.all") }, ...chips].map((chip) => (
            <button
              key={chip.key ?? "all"}
              type="button"
              className="pf-record-history-chip pf-focusable"
              aria-pressed={current === chip.key}
              onClick={() => {
                setActive(chip.key);
              }}
            >
              {chip.label}
            </button>
          ))}
        </div>
      ) : null}
      {items.length > 0 ? <History items={items} label={label} /> : (empty ?? null)}
    </div>
  );
}
