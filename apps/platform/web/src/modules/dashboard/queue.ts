import type { QueueItem } from "../../shared/api/generated/model";
import type { StatusTone } from "../../shared/lib/statuses";

export type Translate = (key: string, options?: Record<string, unknown>) => string;

/** Бейдж срока (SPEC-v3 §7.1): красный «срок сегодня», золотой «завтра», фиолетовый «служебка», серый — дата или «без срока». */
export function dueBadge(
  item: Pick<QueueItem, "due_label" | "due_at">,
  t: Translate,
  formatShort: (value: string) => string,
): { tone: StatusTone; label: string } {
  switch (item.due_label) {
    case "overdue":
      return { tone: "red", label: t("modules:dashboard.queue.due.overdue") };
    case "today":
      return { tone: "red", label: t("modules:dashboard.queue.due.today") };
    case "tomorrow":
      return { tone: "gold", label: t("modules:dashboard.queue.due.tomorrow") };
    case "memo":
      return { tone: "purple", label: t("modules:dashboard.queue.due.memo") };
    case "later":
      return {
        tone: "default",
        label: item.due_at
          ? t("modules:dashboard.queue.due.until", { date: formatShort(item.due_at) })
          : t("modules:dashboard.queue.due.none"),
      };
  }
}

/** Форма числа для «N решений»: правила множественного числа языка, ключи `one|few|many|other` есть во всех языках. */
export function pluralForm(language: string, count: number): "one" | "few" | "many" | "other" {
  const rule = new Intl.PluralRules(language).select(count);
  return rule === "one" || rule === "few" || rule === "many" ? rule : "other";
}
